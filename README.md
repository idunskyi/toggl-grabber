# Toggl → Chief of Staff briefs

`pull_toggl.py` pulls your Toggl Track time entries and writes
`toggl_snapshot.json` in this folder. The Daily/Monday/Friday briefs read
that file (instructions added to each brief's prompt) and fold tracked
hours per project into the relevant section. The briefs run in a sandbox
that can't reach the Toggl API directly, so this script runs on your
machine instead — Claude only reads the file it produces.

## One-time setup

1. Make sure Python 3 is installed (`python3 --version`).
2. Your API token is already saved in `toggl_config.json` in this folder.
   Treat that file like a password — don't share it or commit it to a
   public repo.

## Run it manually

```
cd "/Users/admin/Documents/Claude/Projects/Chief of staff/toggl"
python3 pull_toggl.py              # last 7 days
python3 pull_toggl.py --days 1     # just the last day, for the Daily Brief
python3 pull_toggl.py --since 2026-06-16 --until 2026-06-23
```

Run it before whichever brief you want enriched — `--days 1` shortly
before the Daily Brief (9:06am weekdays), no flags (last 7 days) before
the Monday Operating Brief (12:08pm Mondays) or Friday Close-Out (5:03pm
Fridays).

## Automate it (recommended)

Add to your crontab (`crontab -e`) so it always runs shortly before each
scheduled brief:

```
# Daily Brief prep — 8:55am weekdays
55 8 * * 1-5 cd "/Users/admin/Documents/Claude/Projects/Chief of staff/toggl" && /usr/bin/python3 pull_toggl.py --days 1

# Monday Operating Brief prep — 12:00pm Monday
0 12 * * 1 cd "/Users/admin/Documents/Claude/Projects/Chief of staff/toggl" && /usr/bin/python3 pull_toggl.py

# Friday Close-Out prep — 4:55pm Friday
55 16 * * 5 cd "/Users/admin/Documents/Claude/Projects/Chief of staff/toggl" && /usr/bin/python3 pull_toggl.py
```

Adjust the python3 path if `which python3` gives something different.

## Staleness check

Each brief checks `generated_at` in the snapshot against its window. If
you forget to run the script, the brief will say Toggl data is missing
rather than guess — so worst case is silence, not bad data.
