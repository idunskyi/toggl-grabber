#!/usr/bin/env python3
"""
Pulls Toggl Track time entries and writes an aggregated snapshot that the
Chief of Staff briefs (Daily / Monday / Friday) read from.

Usage:
    python3 pull_toggl.py                 # last 7 days, Demigos project only (default)
    python3 pull_toggl.py --days 1        # just yesterday/today window
    python3 pull_toggl.py --since 2026-06-16 --until 2026-06-23
    python3 pull_toggl.py --project all   # include every project, not just Demigos
    python3 pull_toggl.py --project Aquapark

Reads the API token, in priority order, from:
  1. the TOGGL_API_TOKEN environment variable (used by GitHub Actions), then
  2. a .env file in the same folder (TOGGL_API_TOKEN=...), then
  3. toggl_config.json in the same folder (key: "api_token").

Output: toggl_snapshot.json in the same folder. Briefs read this file;
they do not call the Toggl API themselves.

NOTE ON SENSITIVE DATA: time entry descriptions are free text you typed
yourself. If any of them reference patient names, MRNs, or other PHI,
that text is included verbatim in toggl_snapshot.json. The Chief of
Staff project's standing rule (no PHI/patient identifiers in briefs,
refer to it generically) applies to this data the same as any other
source -- it's enforced when the brief is generated, not by this script.
"""
import argparse
import json
import os
import ssl
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(SCRIPT_DIR, ".env")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "toggl_config.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "toggl_snapshot.json")
API_BASE = "https://api.track.toggl.com/api/v9"


def load_env(path=ENV_PATH):
    """Minimal .env loader (no external dependency). Reads KEY=VALUE lines
    from the .env file and sets them in os.environ without overriding
    variables that are already set -- so a real environment variable (e.g.
    a GitHub Actions secret) always wins. Missing .env is fine and ignored."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def build_ssl_context():
    """Use certifi's CA bundle if available -- works around the common
    macOS issue where Python's bundled OpenSSL can't find a local CA
    bundle (CERTIFICATE_VERIFY_FAILED: unable to get local issuer
    certificate). Falls back to the system default if certifi isn't
    installed."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def get_token():
    load_env()
    token = os.environ.get("TOGGL_API_TOKEN")
    if token:
        return token
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
            if cfg.get("api_token"):
                return cfg["api_token"]
    sys.exit(
        "No Toggl API token found. Set TOGGL_API_TOKEN env var, add it to "
        'the .env file (TOGGL_API_TOKEN=...), or add "api_token" to '
        "toggl_config.json."
    )


def api_get(path, token, params=None):
    url = f"{API_BASE}{path}"
    if params:
        from urllib.parse import urlencode
        url += "?" + urlencode(params)
    req = urllib.request.Request(url)
    # Toggl uses HTTP basic auth: api_token as username, literal string
    # "api_token" as password.
    import base64
    auth = base64.b64encode(f"{token}:api_token".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30, context=build_ssl_context()) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        sys.exit(f"Toggl API error {e.code} on {path}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Network error reaching Toggl ({path}): {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7,
                         help="Pull the last N days (default 7). Ignored if --since/--until given.")
    parser.add_argument("--since", help="ISO date, e.g. 2026-06-16")
    parser.add_argument("--until", help="ISO date, e.g. 2026-06-23")
    parser.add_argument("--project", default="Demigos",
                         help='Only include entries for this project (case-insensitive). '
                              'Pass "all" to include every project. Default: Demigos.')
    args = parser.parse_args()

    if args.since and args.until:
        start_date = args.since
        end_date = args.until
    else:
        today = datetime.now(timezone.utc).date()
        start_date = (today - timedelta(days=args.days)).isoformat()
        end_date = today.isoformat()

    token = get_token()

    me = api_get("/me", token)
    workspace_id = me["default_workspace_id"]

    projects = api_get(f"/workspaces/{workspace_id}/projects", token, {"active": "both"})
    project_map = {p["id"]: p for p in projects}

    clients = api_get(f"/workspaces/{workspace_id}/clients", token)
    client_map = {c["id"]: c["name"] for c in clients}

    entries = api_get("/me/time_entries", token, {
        "start_date": f"{start_date}T00:00:00Z",
        "end_date": f"{end_date}T23:59:59Z",
    })

    by_project = {}
    total_seconds = 0
    raw_entries = []

    for e in entries:
        pid = e.get("project_id")
        proj = project_map.get(pid)
        proj_name = proj["name"] if proj else "(No Project)"
        client_name = client_map.get(proj.get("client_id")) if proj else None

        if args.project.lower() != "all" and proj_name.lower() != args.project.lower():
            continue

        duration = e.get("duration", 0)
        if duration < 0:
            # still running; approximate as time elapsed so far
            started = datetime.fromisoformat(e["start"].replace("Z", "+00:00"))
            duration = int((datetime.now(timezone.utc) - started).total_seconds())

        total_seconds += duration

        key = (proj_name, client_name)
        by_project.setdefault(key, {"seconds": 0, "entries": 0})
        by_project[key]["seconds"] += duration
        by_project[key]["entries"] += 1

        raw_entries.append({
            "start": e.get("start"),
            "stop": e.get("stop"),
            "hours": round(duration / 3600, 2),
            "project": proj_name,
            "client": client_name,
            "description": e.get("description") or "",
        })

    by_project_list = [
        {
            "project": k[0],
            "client": k[1],
            "hours": round(v["seconds"] / 3600, 2),
            "entry_count": v["entries"],
        }
        for k, v in sorted(by_project.items(), key=lambda kv: -kv[1]["seconds"])
    ]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "range_start": start_date,
        "range_end": end_date,
        "project_filter": args.project,
        "total_hours": round(total_seconds / 3600, 2),
        "by_project": by_project_list,
        "raw_entries": raw_entries,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Wrote {OUTPUT_PATH}  (project filter: {args.project})")
    print(f"Range: {start_date} to {end_date}  |  Total: {snapshot['total_hours']} hrs")
    for p in by_project_list:
        client_part = f" ({p['client']})" if p["client"] else ""
        print(f"  {p['project']}{client_part}: {p['hours']} hrs across {p['entry_count']} entries")


if __name__ == "__main__":
    main()
