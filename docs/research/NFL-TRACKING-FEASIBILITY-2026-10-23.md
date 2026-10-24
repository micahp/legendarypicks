# NFL player-tracking feasibility, Phase 0 (LP data side, 2026-10-23)

**Status:** No NFL full-player tracking is available on this box, and none can be downloaded until the token's account accepts the competition rules on kaggle.com. Listings from the Kaggle API are recorded below; no tracking file has been read. The directive's stop condition applies: narrow to the published 2026 Big Data Bowl throw-to-arrival benchmark only after the files are provided, or record the access blocker. No full-play validation is claimed.

Source directive: gridiron-physics `docs/FOOTBALL-FIRST-AGENT-DIRECTIVE-2026-10-23.md` (`origin/main`), Phase 0 and the LP tracking owner role.

## What was searched, and what it returned

| Check | Command or source | Result |
| --- | --- | --- |
| Local filenames | `find /root /data /srv /mnt /home /opt /var/lib -xdev` for `*tracking*`, `*bigdatabowl*`, `*big-data-bowl*`, `*big_data_bowl*`, `tracking_week*`, `plays.csv`, `games.csv`, `player_play*` | Only NHL tracking: `/root/lp-research-data/stathletes-big-data-cup-2026/*Tracking_P*.csv` (hockey, not NFL). Other matches were unrelated package and cache files. |
| Kaggle access | `KAGGLE_API_TOKEN` in `/root/.hermes/.env` (added by the user, 2026-10-23; value not recorded here) | The token authenticates: the competition file listings return HTTP 200. Every file download returns HTTP 403, 'You must accept this competition's rules before you'll be able to download files.' Rule acceptance is a human step on kaggle.com for the token's account. |
| LP dev database, read-only | `/root/legendarypicks/backend/data/picks.dev.db` (126 tables) | No table has positional tracking columns. Columns checked for x, y, s, a, o, dir, frameId, nflId: none found in any NFL table. |

## Kaggle listings (metadata only, via the API)

| Competition | Listing | Notes |
| --- | --- | --- |
| `nfl-big-data-bowl-2025` | README only (78 bytes) | Tracking files are not listed through this token. |
| `nfl-big-data-bowl-2026-prediction` | 20 files, 334,797,422 bytes total | 11 `kaggle_evaluation/` code files, `test.csv` (177,525 B), `test_input.csv` (8,509,084 B), `train/input_2023_w01.csv` to `w07.csv` (39.9 to 51.1 MB each). No `train/output_*` label files are listed. |

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
3. **Blocker needing your action:** accept the rules of `nfl-big-data-bowl-2026-prediction` (and `nfl-big-data-bowl-2025` if that cohort is wanted) on kaggle.com with the account that owns the token. Nothing was downloaded. A one-week check (`train/input_2023_w01.csv`, about 49 MB) is queued for after acceptance.

## Fields the directive requires, status

Coverage, timestamp cadence, snap/throw/terminal events, orientation, team and field orientation, missingness and source keys: **not verifiable until files exist**. None are claimed here.

## Reproduce

```sh
find /root /data /srv /mnt /home /opt /var/lib -xdev \( -iname "*tracking*" -o -iname "*bigdatabowl*" -o -iname "*big-data-bowl*" -o -iname "plays.csv" -o -iname "games.csv" \) 2>/dev/null
python3 -c "import sqlite3; c=sqlite3.connect('file:/root/legendarypicks/backend/data/picks.dev.db?mode=ro', uri=True); print([r[1] for r in c.execute('pragma table_info(nfl_pbp)')])"
```
