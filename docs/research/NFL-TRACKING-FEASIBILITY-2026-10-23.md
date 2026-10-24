# NFL player-tracking feasibility, Phase 0 (LP data side, 2026-10-23)

**Status:** No NFL full-player tracking is available on this box. The directive's stop condition applies: narrow to the published 2026 Big Data Bowl throw-to-arrival benchmark only after the files are provided, or record the access blocker. No full-play validation is claimed.

Source directive: gridiron-physics `docs/FOOTBALL-FIRST-AGENT-DIRECTIVE-2026-10-23.md` (`origin/main`), Phase 0 and the LP tracking owner role.

## What was searched, and what it returned

| Check | Command or source | Result |
| --- | --- | --- |
| Local filenames | `find /root /data /srv /mnt /home /opt /var/lib -xdev` for `*tracking*`, `*bigdatabowl*`, `*big-data-bowl*`, `*big_data_bowl*`, `tracking_week*`, `plays.csv`, `games.csv`, `player_play*` | Only NHL tracking: `/root/lp-research-data/stathletes-big-data-cup-2026/*Tracking_P*.csv` (hockey, not NFL). Other matches were unrelated package and cache files. |
| Kaggle credentials | `/root/.kaggle/kaggle.json`, `KAGGLE*` environment variables, `import kaggle` | All absent on 2026-10-23. The public 2025/2026 Big Data Bowl files need an account download. |
| LP dev database, read-only | `/root/legendarypicks/backend/data/picks.dev.db` (126 tables) | No table has positional tracking columns. Columns checked for x, y, s, a, o, dir, frameId, nflId: none found in any NFL table. |

## NFL play-level tables that do exist (observed context, not frames)

| Table | Rows | Seasons | Coordinates | Notes |
| --- | --- | --- | --- | --- |
| `nfl_pbp` | 753,668 | 2010–2026 | none | `game_id`, `play_id`, down/distance, yardline, EPA, drive, `series_result`, outcome flags |
| `nfl_hist_participation` | 478,989 | 2016–2025 | none | `n_offense`, `n_defense`, personnel, box count, pressure, time to throw |
| `nfl_hist_ftn_charting` | 185,215 | 2022–2025 | none | charting booleans (play action, screen, RPO, blitzers, drop, contested) |

These are usable as the observed play-outcome and drive/game baseline, owned by LP. They cannot supply player trajectories.

## Rights

The user stated on 2026-10-23 that the rights are already in place, and asked that the permitted-use assessment be set aside. Not verified against a licence text. Recorded as user-reported.

## Consequence for the directive

1. **Full-play, from-snap tracking:** not available locally. Not verified in the 2025 or 2026 public releases from here, because the download needs credentials.
2. **Narrow fallback (2026 Big Data Bowl throw-to-arrival):** needs the competition files. The 2026 prediction task starts at ball release and provides the target receiver and landing coordinates, so it is admissible only as a conditional post-throw benchmark.
3. **Blocker needing your action:** place the Big Data Bowl files at a local path, or provide Kaggle credentials for a download. Not downloaded without that authorization.

## Fields the directive requires, status

Coverage, timestamp cadence, snap/throw/terminal events, orientation, team and field orientation, missingness and source keys: **not verifiable until files exist**. None are claimed here.

## Reproduce

```sh
find /root /data /srv /mnt /home /opt /var/lib -xdev \( -iname "*tracking*" -o -iname "*bigdatabowl*" -o -iname "*big-data-bowl*" -o -iname "plays.csv" -o -iname "games.csv" \) 2>/dev/null
python3 -c "import sqlite3; c=sqlite3.connect('file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro', uri=True); print([r[1] for r in c.execute('pragma table_info(nfl_pbp)')])"
```
