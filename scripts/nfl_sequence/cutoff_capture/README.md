# 90-minute cutoff capture (fast host)

These files run on the fast host in `/root/cutoff-captures`. This folder is the committed copy.

- `cutoff_runner.py` runs from cron every 5 minutes (`*/5 * * * * cd /root/cutoff-captures && /usr/bin/python3 cutoff_runner.py >> runner.log 2>&1`).
  For each 2026 game whose cutoff (kickoff minus 90 minutes) has passed, it fetches the nflverse depth chart, injury
  report and roster and writes `snapshots/week-NN/<game_id>/snapshot.json`. A game more than 10 minutes past its
  cutoff is recorded as missed. The schedule comes from the published nflverse `games.csv`, not a database.
- `backfill_cutoff.py` builds missed games after the fact. The depth chart is the capture before each cutoff
  (VERIFIED). Injury and roster data are fetched after the cutoff and labelled FETCHED_AFTER_CUTOFF.

After new snapshots land, copy them to `docs/research/cutoff-snapshots-2026/` and run
`scripts/nfl_sequence/snapshot_index.py` so `docs/research/SNAPSHOT-INDEX-2026.md` shows them.

When you change a file here, copy it to `/root/cutoff-captures` on the fast host too.
