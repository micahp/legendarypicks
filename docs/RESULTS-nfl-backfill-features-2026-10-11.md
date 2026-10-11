# RESULTS: history backfill and the features it supports, 2026-10-11

Plan: [PLAN-nfl-data-backfill-2026-10-11.md](PLAN-nfl-data-backfill-2026-10-11.md). Loader:
`backend/load_nfl_history.py`. Model: `backend/nfl_backfill_features.py` (rules committed in
`70b3daa` before any run; one crash fix in `b23b2f4`, after the Elo benchmark had printed and
before any feature was graded).

## Data now in the dev DB (stored rows = rows in the publisher's file, every load)

| Table | Source | Seasons | Stored = file rows |
|---|---|---|---|
| nfl_hist_injuries | nflverse injuries | 2009-2025 | 90,752 in 17 loads, 0 mismatches (2025 file lacks date_modified: stored NULL) |
| nfl_hist_snap_counts | nflverse snap counts | 2013-2025 | 324,612 in 13 loads, 0 mismatches. 2012 file is published empty |
| nfl_hist_depth_charts | nflverse depth charts | 2010-2024 | 552,514 in 15 loads, 0 mismatches |
| nfl_hist_ftn_charting | FTN via nflverse (CC BY-SA 4.0) | 2022-2025 | 185,215 in 4 loads, 0 mismatches |
| nfl_elo_538 | fivethirtyeight/nfl-elo-game (MIT) | 1920-2020 | 16,810, 0 mismatch |
| nfl_hist_player_ids | nflverse players | n/a | 24,853, 0 mismatch |

Second-way checks against `nfl_schedule` (scored REG games): snap counts cover every game
2013-2025; injury reports cover 511-544 team-weeks a season (all or all but one); FTN covers
284-285 games a season (REG plus playoffs); 538 Elo has 256 REG games for each of 2011-2020.
`nfl_pbp` matches the REG plays of the nflverse 2010-2023 parquets on disk exactly (e.g. 2015:
46,141 = 46,141), so no PBP reload was needed.

Depth chart timing: chart week labels run one past the season (18 labels for a 17-week season).
The label w+1 chart matches game w's actual starter more often (0.93-0.95) than label w
(0.88-0.91), but no publication time is stored and a starter-change test cannot tell whether
label w+1 is written before or after game w. The model uses label w only.

## Verdict

**No model beats any closing line in 2011-2023 or in 2024.** Every cover, over and win Brier
is worse than the line in 2011-2023 with intervals excluding zero. In 2024 the best own-data model
(OWN) has cover Brier +0.0043 [-0.0062, +0.0148] against the line: not distinguishable, not
better. No hit rate interval sits above 52.38%.

## Features against B (the recalibrated v1), win Brier

| Model | 2011-2023 | 2024 | 2025 (second look) | Kept |
|---|---|---|---|---|
| QBI (injury-aware expected starter) | -0.0001 [-0.0011, +0.0008] | -0.0025 [-0.0048, -0.0002] | -0.0012 | no |
| AVAIL (snap-weighted Out/Doubtful load) | -0.0001 [-0.0006, +0.0004] | -0.0017 [-0.0040, +0.0003] | +0.0008 | no |
| OWN (QBI + AVAIL + EPA by unit) | -0.0021 [-0.0042, -0.0001] | -0.0093 [-0.0155, -0.0032] | -0.0027 | yes, marginal; about what EPA alone gave (-0.0019) |
| OWNMP (OWN + market-implied prior) | -0.0055 [-0.0081, -0.0028] | -0.0125 [-0.0208, -0.0044] | -0.0017 | yes, market-derived |

Against the lines, 2011-2023 / 2024:
- OWN: win vs moneyline +0.0103 / +0.0129; cover vs spread +0.0095 / +0.0043 (2024 interval spans 0);
  over vs total +0.0090 / +0.0090. Hit rates: spread 0.4883 / 0.5119, total 0.4908 / 0.5257.
- OWNMP: win +0.0070 / +0.0097; cover +0.0055 / +0.0032 (2024 spans 0).

538 Elo benchmark, 2011-2020 (2,386 of 2,393 games joined): Brier 0.2183 against the market's
0.2097 (+0.0087 [+0.0049, +0.0124]); B is 0.0020 worse than Elo [-0.0012, +0.0053].

## Not obtained, and why

- Snap counts 2010-2012: the 2012 file is empty and earlier ones are not published.
- Depth charts 2025: new schema (dated snapshots, no week); not mapped.
- 538 Elo after 2020: the archive stops there.
- Weather (Open-Meteo), PFR advanced stats, player and team stats, rosters: deferred with
  reasons in the plan. FTN tendencies: loaded, not tested (one development season).
- Pre-kickoff timestamps for any of these files: none are published.
