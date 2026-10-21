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

All candidates and baselines use the same 2,460 eligible holdout games. These are point estimates; lower is better for Brier, log loss, ECE, and MAE. Paired date-cluster intervals follow below.

| Model | Winner Brier | Winner log loss | ECE10 | Home points MAE | Away points MAE | Spread MAE | Total MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 fixed training home-win rate | 0.24887 | 0.69091 | 0.02764 | — | — | — | — |
| B1 fixed training league points | 0.24887 | 0.69091 | 0.02764 | 10.752 | 10.923 | 12.527 | 17.578 |
| G1 Elo | 0.21465 | 0.61674 | 0.03763 | — | — | — | — |
| G2 Efficiency | 0.21474 | 0.61857 | 0.04610 | 9.736 | 9.745 | 11.191 | 15.797 |
| G3 Joint scores | 0.21339 | 0.61452 | 0.02595 | 9.741 | 9.749 | 11.194 | 15.805 |

Validation results on the preceding 2,460 games:

| Model | Winner Brier | Winner log loss | ECE10 | Team points MAE | Spread MAE | Total MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0/B1 baselines | 0.24621 | 0.68555 | 0.00894 | B1: 10.217 | 11.557 | 16.773 |
| G1 Elo | 0.22567 | 0.64351 | 0.02326 | — | — | — |
| G2 Efficiency | 0.22910 | 0.65277 | 0.04660 | 9.498 | 10.833 | 15.513 |
| G3 Joint scores | 0.22703 | 0.64702 | 0.03237 | 9.490 | 10.825 | 15.500 |

Point estimates put G3 lowest on holdout winner Brier and log loss, while G2 is lowest on the holdout point, spread, and total MAE. Validation point estimates favor G1 on winner scores and G3 on point and spread errors. These small differences are evaluated with paired date-cluster intervals below. G3's validation 80% margin interval covered 83.1% at mean width 35.93; its 80% total interval covered 80.4% at mean width 48.72. Validation distribution scores were margin CRPS 7.716, total CRPS 10.974, and joint Gaussian score NLL 7.741. On test, G3's 80% margin interval covered 80.7% of games at mean width 35.57 points; its 80% total interval covered 78.0% at mean width 48.68. Test distribution scores were margin CRPS 7.996, total CRPS 11.142, and joint Gaussian score NLL 7.784. Bin calibration details are preserved in the JSON benchmark.

The fixed league-points baseline has 10.838 combined team-points MAE; G2/G3 have point estimates of 9.740/9.745 on the untouched holdout, with paired intervals below the baseline for home, away, spread, and total MAE. The model point estimates are below the fixed home-rate baseline on winner scores, but this is not evidence of betting value.

There is no stored, historical NBA pregame bookmaker line feed with trustworthy timestamps. NFL line snapshots are league-specific and the current prop snapshots do not provide NBA game prices. Consequently there is no valid historical market comparison; the UI and benchmark say so rather than using closing or post-tipoff prices.

### Date-clustered paired uncertainty

Each replicate resamples 329 validation or 323 test NBA local game-date clusters with replacement, keeping every game on a selected date. Candidate and comparator losses use the same sampled dates. The bootstrap uses 2,000 replicates per split, seed 20261021, and two-sided percentile 95% intervals. Δ is candidate minus comparator, so negative favors the candidate; P(candidate better) is the share of replicates with Δ < 0. B0 is the fixed training home-win-rate baseline; B1 is the fixed training league-points baseline. G2's CRPS treats its point forecast as a degenerate point-mass distribution, for which CRPS equals absolute error. Bold marks a lower-loss model only when the paired interval excludes zero. Intervals that include zero are labeled “indistinguishable on this holdout.”

| Split | Metric | Candidate | Comparator | Δ (candidate − comparator) | 95% CI | P(candidate better) | Result |
| --- | --- | --- | --- | ---: | --- | ---: | --- |
| Validation | Winner Brier | G1 | G2 | -0.003426 | [-0.007572, +0.000619] | 95.2% | indistinguishable on this holdout |
| Validation | Winner Brier | G1 | G3 | -0.001357 | [-0.005188, +0.002313] | 74.5% | indistinguishable on this holdout |
| Validation | Winner Brier | **G1** | B0 | -0.020539 | [-0.026386, -0.014500] | 100.0% | G1 lower loss |
| Validation | Winner Brier | **G1** | B1 | -0.020539 | [-0.026386, -0.014500] | 100.0% | G1 lower loss |
| Validation | Winner Brier | G2 | **G3** | +0.002069 | [+0.001099, +0.003021] | 0.0% | G3 lower loss |
| Validation | Winner Brier | **G2** | B0 | -0.017113 | [-0.024588, -0.009738] | 100.0% | G2 lower loss |
| Validation | Winner Brier | **G2** | B1 | -0.017113 | [-0.024588, -0.009738] | 100.0% | G2 lower loss |
| Validation | Winner Brier | **G3** | B0 | -0.019181 | [-0.025823, -0.012593] | 100.0% | G3 lower loss |
| Validation | Winner Brier | **G3** | B1 | -0.019181 | [-0.025823, -0.012593] | 100.0% | G3 lower loss |
| Validation | Winner log loss | G1 | G2 | -0.009261 | [-0.018935, +0.000099] | 97.4% | indistinguishable on this holdout |
| Validation | Winner log loss | G1 | G3 | -0.003514 | [-0.012137, +0.004761] | 78.2% | indistinguishable on this holdout |
| Validation | Winner log loss | **G1** | B0 | -0.042044 | [-0.055273, -0.028872] | 100.0% | G1 lower loss |
| Validation | Winner log loss | **G1** | B1 | -0.042044 | [-0.055273, -0.028872] | 100.0% | G1 lower loss |
| Validation | Winner log loss | G2 | **G3** | +0.005747 | [+0.003176, +0.008244] | 0.0% | G3 lower loss |
| Validation | Winner log loss | **G2** | B0 | -0.032783 | [-0.050347, -0.015214] | 100.0% | G2 lower loss |
| Validation | Winner log loss | **G2** | B1 | -0.032783 | [-0.050347, -0.015214] | 100.0% | G2 lower loss |
| Validation | Winner log loss | **G3** | B0 | -0.038530 | [-0.053614, -0.023163] | 100.0% | G3 lower loss |
| Validation | Winner log loss | **G3** | B1 | -0.038530 | [-0.053614, -0.023163] | 100.0% | G3 lower loss |
| Validation | Home points MAE | G2 | G3 | +0.007432 | [-0.003510, +0.018668] | 9.1% | indistinguishable on this holdout |
| Validation | Home points MAE | **G2** | B1 | -0.709975 | [-0.976957, -0.439451] | 100.0% | G2 lower loss |
| Validation | Home points MAE | **G3** | B1 | -0.717407 | [-0.982120, -0.445827] | 100.0% | G3 lower loss |
| Validation | Away points MAE | G2 | G3 | +0.008822 | [-0.001638, +0.019329] | 5.1% | indistinguishable on this holdout |
| Validation | Away points MAE | **G2** | B1 | -0.728508 | [-1.013305, -0.456518] | 100.0% | G2 lower loss |
| Validation | Away points MAE | **G3** | B1 | -0.737331 | [-1.018342, -0.461876] | 100.0% | G3 lower loss |
| Validation | Spread MAE | G2 | G3 | +0.007876 | [-0.004923, +0.020577] | 12.5% | indistinguishable on this holdout |
| Validation | Spread MAE | **G2** | B1 | -0.724416 | [-0.984133, -0.470243] | 100.0% | G2 lower loss |
| Validation | Spread MAE | **G3** | B1 | -0.732292 | [-0.992687, -0.476575] | 100.0% | G3 lower loss |
| Validation | Total MAE | G2 | G3 | +0.012571 | [-0.005084, +0.030645] | 7.0% | indistinguishable on this holdout |
| Validation | Total MAE | **G2** | B1 | -1.260088 | [-1.729262, -0.783723] | 100.0% | G2 lower loss |
| Validation | Total MAE | **G3** | B1 | -1.272659 | [-1.744457, -0.799124] | 100.0% | G3 lower loss |
| Validation | Margin CRPS | G2 | **G3** | +3.117002 | [+2.997254, +3.238391] | 0.0% | G3 lower loss |
| Validation | Total CRPS | G2 | **G3** | +4.538288 | [+4.362150, +4.714746] | 0.0% | G3 lower loss |
| Test | Winner Brier | G1 | G2 | -0.000095 | [-0.003994, +0.004057] | 51.5% | indistinguishable on this holdout |
| Test | Winner Brier | G1 | G3 | +0.001261 | [-0.002276, +0.004953] | 23.6% | indistinguishable on this holdout |
| Test | Winner Brier | **G1** | B0 | -0.034225 | [-0.040410, -0.028254] | 100.0% | G1 lower loss |
| Test | Winner Brier | **G1** | B1 | -0.034225 | [-0.040410, -0.028254] | 100.0% | G1 lower loss |
| Test | Winner Brier | G2 | **G3** | +0.001356 | [+0.000460, +0.002255] | 0.2% | G3 lower loss |
| Test | Winner Brier | **G2** | B0 | -0.034130 | [-0.041834, -0.026369] | 100.0% | G2 lower loss |
| Test | Winner Brier | **G2** | B1 | -0.034130 | [-0.041834, -0.026369] | 100.0% | G2 lower loss |
| Test | Winner Brier | **G3** | B0 | -0.035486 | [-0.042511, -0.028458] | 100.0% | G3 lower loss |
| Test | Winner Brier | **G3** | B1 | -0.035486 | [-0.042511, -0.028458] | 100.0% | G3 lower loss |
| Test | Winner log loss | G1 | G2 | -0.001831 | [-0.011030, +0.008051] | 63.6% | indistinguishable on this holdout |
| Test | Winner log loss | G1 | G3 | +0.002220 | [-0.005856, +0.010820] | 28.5% | indistinguishable on this holdout |
| Test | Winner log loss | **G1** | B0 | -0.074172 | [-0.088058, -0.060548] | 100.0% | G1 lower loss |
| Test | Winner log loss | **G1** | B1 | -0.074172 | [-0.088058, -0.060548] | 100.0% | G1 lower loss |
| Test | Winner log loss | G2 | **G3** | +0.004051 | [+0.001500, +0.006635] | 0.1% | G3 lower loss |
| Test | Winner log loss | **G2** | B0 | -0.072342 | [-0.090403, -0.053794] | 100.0% | G2 lower loss |
| Test | Winner log loss | **G2** | B1 | -0.072342 | [-0.090403, -0.053794] | 100.0% | G2 lower loss |
| Test | Winner log loss | **G3** | B0 | -0.076393 | [-0.092698, -0.060366] | 100.0% | G3 lower loss |
| Test | Winner log loss | **G3** | B1 | -0.076393 | [-0.092698, -0.060366] | 100.0% | G3 lower loss |
| Test | Home points MAE | G2 | G3 | -0.005338 | [-0.015019, +0.004835] | 86.2% | indistinguishable on this holdout |
| Test | Home points MAE | **G2** | B1 | -1.016432 | [-1.329206, -0.713358] | 100.0% | G2 lower loss |
| Test | Home points MAE | **G3** | B1 | -1.011094 | [-1.329412, -0.709984] | 100.0% | G3 lower loss |
| Test | Away points MAE | G2 | G3 | -0.004351 | [-0.014111, +0.006235] | 78.7% | indistinguishable on this holdout |
| Test | Away points MAE | **G2** | B1 | -1.178528 | [-1.524448, -0.815779] | 100.0% | G2 lower loss |
| Test | Away points MAE | **G3** | B1 | -1.174177 | [-1.517356, -0.813973] | 100.0% | G3 lower loss |
| Test | Spread MAE | G2 | G3 | -0.003107 | [-0.015135, +0.009630] | 70.2% | indistinguishable on this holdout |
| Test | Spread MAE | **G2** | B1 | -1.335804 | [-1.637666, -1.045702] | 100.0% | G2 lower loss |
| Test | Spread MAE | **G3** | B1 | -1.332698 | [-1.633454, -1.042628] | 100.0% | G3 lower loss |
| Test | Total MAE | G2 | G3 | -0.008389 | [-0.023033, +0.006812] | 87.0% | indistinguishable on this holdout |
| Test | Total MAE | **G2** | B1 | -1.781007 | [-2.389825, -1.173752] | 100.0% | G2 lower loss |
| Test | Total MAE | **G3** | B1 | -1.772617 | [-2.375749, -1.164364] | 100.0% | G3 lower loss |
| Test | Margin CRPS | G2 | **G3** | +3.195177 | [+3.063270, +3.331433] | 0.0% | G3 lower loss |
| Test | Total CRPS | G2 | **G3** | +4.655088 | [+4.473437, +4.841719] | 0.0% | G3 lower loss |

## Prospective forecasts and grading

- The standalone file `nba-model.dev.sqlite3` keeps model history, replaceable previews, immutable lock rows, immutable grade rows, and missed-window events separate from the picks DB.
- Live history accepts a game only after the ESPN scoreboard, ESPN summary competitors/scores, team codes, paired box-score inputs, and any final already in `nba_schedule` agree. It records a source hash and never writes to `picks.dev.db`.
- Previews use games strictly earlier than the target NBA local game date, and live observations must also have been captured by the forecast's UTC cutoff. Later box-score corrections and same-day completed games are held out. The lock runner accepts exactly G1/G2/G3 as one atomic set during the two-minute window beginning T−90 minutes. A passed window is recorded as missed; no retrospective lock is created.
- Grades require a previously locked forecast and a post-tipoff ESPN final that passed the same schedule/scoreboard/summary checks. SQLite triggers reject update or delete of locked forecasts and grades.
- Dev-only systemd service/timer files are provided under `ops/systemd`. They are not installed or enabled by this branch. The shared API process has not been restarted, and the tab will appear on shared dev after the branch is reviewed, merged, and the dev API is reloaded under Micah's authorization.
- Isolated runtime smoke on 2026-10-21 verified all 20 source assets, imported 11,976 historical games, copied 1,273 current schedule rows from the dev DB opened read-only, and generated/persisted 75 display previews across 25 games in the three-day horizon. The run used a temporary model DB and created no locks.

## Verification output

- `pytest backend/test_nba_game_model_phase1.py -q`: **10 passed**, including date-cluster resampling, paired deltas, deterministic output, and G2 point-mass CRPS.
- `jest components/Leagues/NbaModelTab.test.tsx --runInBand`: **3 passed**. A focused TypeScript `--noEmit` check for `NbaModelTab.tsx` passed.
- `python3 -m py_compile backend/nba_game_model.py backend/backtest_nba_game_model.py backend/test_nba_game_model_phase1.py` passed.
- Two full backtest runs each printed `source_sha256_verified=true` and 5,827 train / 2,460 validation / 2,460 test games. Both produced 2,460 validation games over 329 date clusters and 2,460 test games over 323 date clusters, with 32 paired comparisons per split. The uncertainty block hashes were run 1 `392bd568345fd9c146d6db0289ece599b384475e7a85a1133775073206b2faac` and run 2 `392bd568345fd9c146d6db0289ece599b384475e7a85a1133775073206b2faac`; the full benchmark hashes were `3b030d5dcefeab6f0c87579d108e9e15937abf2d38bb827e96e7d8e452f29fe6` for both runs. All pre-existing benchmark keys and values were unchanged, and the serialized `metrics` block is byte-identical.
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
- Research-only advancement criterion: a candidate can be named the overall winner on winner Brier only if its paired 95% test interval favors it over each of the other two candidates and the validation point deltas have the same favorable sign. No candidate qualifies in this run: G3 beats G2 on both splits, but G3 versus G1 is indistinguishable on test and reverses sign between validation and test. This criterion does not define production adoption.
- G3 has lower winner Brier and log loss than G2 on both validation and test, with paired intervals excluding zero. G3 versus G1 is indistinguishable on test, and the Brier point-delta sign reverses between validation and test. G2 and G3 are indistinguishable on all four point-forecast MAEs in both splits; G3 has lower margin and total CRPS than G2's deterministic point-mass forecasts in both splits. More prospective evidence should establish whether these retrospective differences persist.
- The NBA Model tab, timers, and API are committed on the feature branch only. No merge, prod write, release, or service restart has happened.
