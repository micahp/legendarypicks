# NBA game model, Phase 1

**Status:** research candidates and prospective dev pipeline are implemented on `feat/nba-game-model-phase1`. The branch is pushed separately; it has not been merged, installed, or activated on the shared dev service. No production database was opened for writing.

## Model card

### Intended use

Compare three pregame NBA game-outcome candidates, publish their forecasts and historical research metrics on the NBA Model tab, then collect immutable forecasts prospectively before tipoff. Every candidate remains research only. There are no betting recommendations or retrospective forecast records.

### Candidates

| Candidate | Method | Pregame output |
| --- | --- | --- |
| G1 Elo | K=20 Elo; 65-point home-court adjustment; 75% rating carry between seasons | Home-win probability. It does not project scores. |
| G2 Efficiency | EWMA 0.08 pace and opponent-adjusted offense/defense; 50% offseason carry; two-point home adjustment | Home/away points, spread, total, and winner probability. Possessions use FGA + 0.44×FTA − OREB + turnovers. |
| G3 Joint scores | G2 means plus a prequential bivariate normal residual model, sampled into 2,048 integer score pairs | Score, winner, margin, and total distributions all come from the same simulated scores. |

Parameters are fixed before validation and holdout evaluation. Games on one local date share a pregame state; results are applied after the full date block. No lineup, injury, post-tipoff, or future result features are used. The prospective feature snapshot stores the cutoff, fitted-through date, history count, and source hashes.

### Data and chronological protocol

Training and evaluation use free SportsDataverse releases: ESPN team box scores and the NBA Stats schedule release used to classify regular-season games and exclude the NBA Cup final. A one-to-one crosswalk matches each game by canonical teams, a date window of one day, and the exact home/away score pair; ambiguous or conflicting matches fail. The benchmark inputs and SHA-256 hashes are in [`research/nba-game-model/sources.json`](../research/nba-game-model/sources.json), and the measured output is in [`research/nba-game-model/benchmark.json`](../research/nba-game-model/benchmark.json).

| Ending-year season | Regular schedule games | Crosswalked box scores | Eligible with efficiency inputs | Coverage note |
| ---: | ---: | ---: | ---: | --- |
| 2017 | 1,230 | 1,229 | 1,229 | One schedule game has no box score. |
| 2018 | 1,230 | 1,229 | 1,229 | One schedule game has no box score. |
| 2019 | 1,230 | 1,230 | 1,230 | Complete. |
| 2020 | 1,059 | 1,059 | 1,059 | Shortened season; four ESPN date labels differ by one day. |
| 2021 | 1,080 | 1,080 | 1,080 | Shortened season. |
| 2022 | 1,230 | 1,230 | 1,230 | Complete. |
| 2023 | 1,230 | 1,230 | 1,230 | Complete. |
| 2024 | 1,230 | 1,231 | 1,230 | One NBA Cup final is crosswalked and excluded. |
| 2025 | 1,230 | 1,231 | 1,230 | One NBA Cup final is crosswalked and excluded. |
| 2026 | 1,230 | 1,231 | 1,229 | One NBA Cup final is excluded; one regular-season box score lacks aggregate turnovers. |

Eligible samples are 5,827 train games (2017–2021), 2,460 validation games (2022–2023), and 2,460 untouched test games (2024–2025). A separate state refit uses 11,976 complete regular-season games through 2025–26 for prospective forecasts. The two 2017–18 missing boxes and the one 2025–26 missing-turnover game are excluded rather than imputed.

The existing dev DB audit found:

- `nba_sportsdataverse_games` covers only 2025–26 locally: 1,230 REG, one CUP final, six play-in, and 85 playoff games.
- NBA `team_game_results` covers 1,231 games / 2,462 team rows through 2026-04-13; NBA `team_game_stats` has 2,462 ESPN summary rows for those games.
- Joining the SportsDataverse REG+CUP games to `team_game_results` by ESPN event ID matches all 1,231 games, with no score mismatch. 945 date labels differ, so the ESPN event ID is the identity join; date is not.
- The current `nba_schedule` snapshot has 1,206 REG rows, one CUP row, and 66 preseason rows for 2026–27. Only five REG rows have ESPN IDs, and no row has a final score. Forecasts use the official NBA game ID, so an ESPN ID is not required for a pregame preview. Missing schedule rows mean the preview feed will omit those games until the dev schedule is completed.

As checked on 2026-10-21, the SportsDataverse ESPN team-box release lists seasons only through ending year 2026 (2025–26; last asset written 2026-09-09), and the NBA Stats schedule release also ends at 2026 (last asset written 2026-08-13). Neither contains 2026–27 logs yet. That release is not a research blocker: prospective forecasts use the free ESPN live scoreboard/summary path. When the 2026–27 SportsDataverse release is published and validated, its season-specific assets can be appended to the standalone model history without changing earlier-season source hashes. The source project publishes [ESPN NBA team box scores](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/espn_nba_team_boxscores) and [NBA Stats schedules](https://github.com/sportsdataverse/sportsdataverse-data/releases/tag/nba_stats_schedules); these are free historical releases.

### Holdout results

All candidates and baselines use the same 2,460 eligible holdout games. Lower is better for Brier, log loss, ECE, and MAE.

| Model | Winner Brier | Winner log loss | ECE10 | Home points MAE | Away points MAE | Spread MAE | Total MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 fixed training home-win rate | 0.24887 | 0.69091 | 0.02764 | — | — | — | — |
| B1 fixed training league points | 0.24887 | 0.69091 | 0.02764 | 10.752 | 10.923 | 12.527 | 17.578 |
| G1 Elo | 0.21465 | 0.61674 | 0.03763 | — | — | — | — |
| G2 Efficiency | 0.21474 | 0.61857 | 0.04610 | **9.736** | **9.745** | **11.191** | **15.797** |
| G3 Joint scores | **0.21339** | **0.61452** | **0.02595** | 9.741 | 9.749 | 11.194 | 15.805 |

Validation results on the preceding 2,460 games:

| Model | Winner Brier | Winner log loss | ECE10 | Team points MAE | Spread MAE | Total MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0/B1 baselines | 0.24621 | 0.68555 | 0.00894 | B1: 10.217 | 11.557 | 16.773 |
| G1 Elo | **0.22567** | **0.64351** | **0.02326** | — | — | — |
| G2 Efficiency | 0.22910 | 0.65277 | 0.04660 | 9.498 | 10.833 | 15.513 |
| G3 Joint scores | 0.22703 | 0.64702 | 0.03237 | **9.490** | **10.825** | **15.500** |

G3 ranks first on holdout winner Brier, log loss, and calibration, but its advantage over G1/G2 is small. G2 has the lowest point, spread, and total MAE by a few thousandths. On validation, G1 led winner metrics and G3 led point, spread, and total MAE by small amounts. G3's validation 80% margin interval covered 83.1% at mean width 35.93; its 80% total interval covered 80.4% at mean width 48.72. Validation distribution scores were margin CRPS 7.716, total CRPS 10.974, and joint Gaussian score NLL 7.741. On test, G3's 80% margin interval covered 80.7% of games at mean width 35.57 points; its 80% total interval covered 78.0% at mean width 48.68. Test distribution scores were margin CRPS 7.996, total CRPS 11.142, and joint Gaussian score NLL 7.784. Bin calibration details are preserved in the JSON benchmark.

The fixed league-points baseline has 10.838 combined team-points MAE. G2/G3 reduce that to 9.740/9.745 on the untouched holdout. The models beat the fixed home-rate baseline on winner scores, but this is not evidence of betting value.

There is no stored, historical NBA pregame bookmaker line feed with trustworthy timestamps. NFL line snapshots are league-specific and the current prop snapshots do not provide NBA game prices. Consequently there is no valid historical market comparison; the UI and benchmark say so rather than using closing or post-tipoff prices.

## Prospective forecasts and grading

- The standalone file `nba-model.dev.sqlite3` keeps model history, replaceable previews, immutable lock rows, immutable grade rows, and missed-window events separate from the picks DB.
- Live history accepts a game only after the ESPN scoreboard, ESPN summary competitors/scores, team codes, paired box-score inputs, and any final already in `nba_schedule` agree. It records a source hash and never writes to `picks.dev.db`.
- Previews use games strictly earlier than the target NBA local game date, and live observations must also have been captured by the forecast's UTC cutoff. Later box-score corrections and same-day completed games are held out. The lock runner accepts exactly G1/G2/G3 as one atomic set during the two-minute window beginning T−90 minutes. A passed window is recorded as missed; no retrospective lock is created.
- Grades require a previously locked forecast and a post-tipoff ESPN final that passed the same schedule/scoreboard/summary checks. SQLite triggers reject update or delete of locked forecasts and grades.
- Dev-only systemd service/timer files are provided under `ops/systemd`. They are not installed or enabled by this branch. The shared API process has not been restarted, and the tab will appear on shared dev after the branch is reviewed, merged, and the dev API is reloaded under Micah's authorization.
- Isolated runtime smoke on 2026-10-21 verified all 20 source assets, imported 11,976 historical games, copied 1,273 current schedule rows from the dev DB opened read-only, and generated/persisted 75 display previews across 25 games in the three-day horizon. The run used a temporary model DB and created no locks.

## Verification output

- `pytest backend/test_nba_game_model_phase1.py -q`: **8 passed**. Covers chronological split, pinned/additive history, live scoreboard/summary agreement, late corrections excluded by observation cutoff, dev-only API scope, lock timing/immutability, and final grading.
- `jest components/Leagues/NbaModelTab.test.tsx --runInBand`: **3 passed**. TypeScript `--noEmit` check passed for the tab and its test.
- `python3 -m py_compile` passed for the new backend modules and router.
- The full backtest printed `source_sha256_verified=true`, 5,827 train / 2,460 validation / 2,460 test games. Its generated JSON matched the checked-in benchmark byte for byte (SHA-256 `5dcac97364004580f4b1d3b38c5d15ab4996bf31f822749c57e583cd369f923f`).
- The temporary dev-schedule runtime smoke printed: `sha256_assets_verified=20 history_rows_added=11976 historical_games=11976 schedule_rows_read_only=1273 preview_games=25 preview_rows_generated=75 preview_rows_persisted=75 locks_created=0`.

To initialize the dev-only history after the branch is deployed, use the serial, hash-verified importer with explicit dev paths:

```sh
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
NBA_MODEL_DB_PATH=/root/legendarypicks/backend/data/nba-model.dev.sqlite3 \
NBA_MODEL_SOURCE_DATA=/root/legendarypicks/backend/data/nba-model-source \
/root/legendarypicks/backend/venv/bin/python \
/root/legendarypicks/backend/import_nba_model_history.py --download
```

In a fresh research environment, install the pinned Parquet reader with `python -m pip install -r research/nba-game-model/requirements.txt`, then reproduce the backtest with:

```sh
PYTHONPATH=backend python3 backend/backtest_nba_game_model.py \
  --data-dir backend/data/nba-model-source \
  --output research/nba-game-model/benchmark.json
```

## Research limitations and next decisions

- The current schedule snapshot is missing 24 REG games; prospective coverage follows the games actually present in `nba_schedule`.
- The historical holdout is two seasons. G1/G2/G3 have no prospective sample yet, so none is qualified for adoption.
- No timestamped NBA bookmaker odds, injury feed, confirmed lineups, rest/travel features, or paid data are used. No odds benchmark or player-level simulation is included.
- Public historical SportsDataverse files are final release snapshots rather than capture-time archives, so timestamps for later corrections to earlier-game box scores are unavailable. The backtest applies only prior-date game records and keeps all same-day results out of that date's forecasts, but it cannot reconstruct whether an old box-score correction arrived before a later game's tipoff.
- G2/G3 share almost the same score means; G3 currently adds probabilistic distributions without a measurable point-forecast gain. More prospective calibration evidence should decide whether that complexity is useful.
- The NBA Model tab, timers, and API are committed on the feature branch only. No merge, prod write, release, or service restart has happened.
