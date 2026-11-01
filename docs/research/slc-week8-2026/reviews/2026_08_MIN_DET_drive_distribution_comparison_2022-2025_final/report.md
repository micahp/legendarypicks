# MIN–DET SLC drive distributions vs. 2022–2025 NFL regular season

Historical sample: 1,087 complete regular-season games, 2,174 team-games, seasons 2022–2025. SLC sample: 10,000 frozen MIN–DET games per team. No simulation was rerun.

## Mean comparison

| Measure | NFL avg | DET actual | MIN actual | DET SLC | MIN SLC |
|---|---:|---:|---:|---:|---:|
| Drives per team-game | 10.86 | 10.79 | 11.13 | 9.80 | 9.69 |
| Offensive scoring drives / all drives | 38.0% | 45.3% | 37.6% | 47.0% | 42.7% |
| Punt terminals per team-game | 3.86 | 3.09 | 3.75 | 2.66 | 2.78 |
| Field-goal terminals per team-game | 1.98 | 1.68 | 2.06 | 2.07 | 1.81 |
| Field-goal attempt events per team-game | 1.99 | 1.68 | 2.06 | 2.07 | 1.81 |
| Turnovers on downs per team-game | 0.62 | 0.81 | 0.49 | 0.91 | 0.81 |
| Turnover drives per team-game | 1.25 | 1.01 | 1.59 | 1.24 | 1.69 |
| Period-end drives per team-game | 0.26 | 0.19 | 0.28 | 1.06 | 0.87 |
| Recorded run/pass/kneel/spike/kick events per team-game | 68.47 | 69.81 | 67.75 | 73.75 | 65.76 |
| Scrimmage plays per team-game (team-stat definition) | 61.69 | 63.94 | 61.00 | 68.99 | 61.14 |
| Recorded events per modeled drive | 6.34 | 6.48 | 6.13 | 7.58 | 6.83 |
| Net yards per modeled drive | 30.95 | 36.19 | 30.11 | 41.06 | 38.92 |
| Starting yardline_100 per drive | 70.51 | 69.18 | 70.50 | 71.17 | 72.02 |

## Terminal distribution

Percent of all drive records by terminal. Period-end combines halftime and game-end drives. An `Opp touchdown` is a defensive score: it is counted as a touchdown terminal, but not as an offensive scoring drive.

| Source / team | Punt | Touchdown | FG attempt | Turnover on downs | Turnover | Safety | QB kneel | Period end | Other |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| historical / NFL | 35.6% | 22.9% | 18.3% | 5.7% | 10.1% | 0.2% | 4.4% | 2.4% | 0.4% |
| historical / DET | 28.6% | 32.7% | 15.5% | 7.5% | 8.2% | 0.4% | 5.0% | 1.8% | 0.3% |
| historical / MIN | 33.7% | 22.7% | 18.5% | 4.4% | 12.5% | 0.3% | 5.0% | 2.5% | 0.4% |
| SLC 10K / DET | 27.2% | 27.8% | 21.2% | 9.3% | 3.5% | 0.2% | 0.0% | 10.9% | 0.0% |
| SLC 10K / MIN | 28.7% | 26.0% | 18.7% | 8.4% | 9.1% | 0.2% | 0.0% | 9.0% | 0.0% |

## Findings by category

| Category | Finding | Evidence and interpretation |
|---|---|---|
| Reporting semantics | The archived team punt field undercounts ordinary punts. | It reports 0.013 punts/team-game, while the frozen drive terminals show 2.66 DET and 2.78 MIN. The old producer used `out.get('punt_attempt', out['punt'])`; an explicit `False` suppressed the normal `punt=True` value. Current code uses the OR check with regression coverage. |
| Reporting semantics | Drive event counts include special teams; team `plays` does not. | SLC has 73.75 DET / 65.76 MIN recorded events per game versus 68.99 / 61.14 team-stat scrimmage plays. The differences are 4.76 / 4.61, approximately the punt plus field-goal attempt counts. |
| Engine behavior | Punt frequency remains below the historical comparison after correcting the report. | SLC terminal rates are 2.66 DET and 2.78 MIN per game versus historical team means 3.09 and 3.75; league mean is 3.86. This is a real distribution difference; the aggregate does not isolate fourth-down choice from play outcomes. |
| Engine behavior | Scoring and drive yardage are elevated. | Scoring-drive rates are 47.0% DET / 42.7% MIN versus 45.3% / 37.6% team means. Net yards per modeled drive are 41.06 / 38.92 versus 36.19 / 30.11. The summary identifies gaps, not their causal model layer. |
| Player allocation | Detroit rushing attempts are concentrated in Jahmyr Gibbs. | The frozen summary averages 31.99 Gibbs carries out of 36.83 Detroit team carries (86.9%). This is an allocation-layer finding, separate from team drive frequency. |
| Engine behavior / fidelity limit | Some overtime outcomes have scores but no modeled play sequence. | The frozen run has 694 DET and 693 MIN such drive rows. They remain in terminal/scoring totals and are excluded from event and yardage averages. |
| Historical-data limitation | Team rates are four-season franchise averages. | They cover 2022–2025 and are not a 2026 roster-specific or game-state-matched baseline. The PBP snapshot has no game_type column; its pinned manifest explicitly filters regular-season weeks 1–18. |


## Distribution details

The CSV provides sample size, mean, median, population variance, standard deviation, P95, P99, maximum, and zero rate for metrics derived from the play-by-play and drive rows. The scrimmage-play row for SLC is sourced from the frozen summary and includes its available sample size, mean, and median.

## Definitions and limits

- Historical source: pinned regular-season PBP snapshot; unique game IDs, weeks 1-18 (nfl_pbp season 2022-2025 and regular-season week 1-18; players league=nfl with GSIS id). The pinned source filter is `nfl_pbp season 2022-2025 and regular-season week 1-18; players league=nfl with GSIS id`; only weeks 1–18 in the requested seasons are included. The PBP-only snapshot has no game_type column, so regular-season classification comes from its pinned manifest filter.
- The selected PBP source is read-only. Per-season game counts and source hashes are recorded in the manifest; no 2026 outcomes enter this comparison.
- An actual drive is keyed by game, `drive`, and offense team. Its terminal is the last nonempty `series_result`; intermediate `First down` labels do not terminate a drive. `Opp touchdown` is a defensive touchdown.
- Terminal counts include period-end drives on both sides. Historical QB-kneel terminals remain separate because the available series-result field does not establish that every kneel occurred at a period boundary. SLC score-only overtime drive rows remain in terminal and scoring counts; rows with zero recorded events are excluded from event-count, yardage, and starting-position drive averages.
- Recorded-event counts include run, pass, QB kneel, QB spike, punt, and field-goal rows; `no_play`, kickoff, and try rows are excluded. SLC drive `play_count` follows its saved event count, including kicks.
- SLC team-stat `plays` counts its scrimmage event types only. Drive event counts also include punt and field-goal attempts, so they are expected to exceed team-stat plays. The historical scrimmage-play proxy counts run/pass PBP rows; recorded drive events count the same run/pass rows plus QB kneels, spikes, punts, and field-goal rows.
- Yardage is the sum of each producer’s `yards_gained` values on the included action events. Starting field position is the first included action’s `yardline_100`. These producer fields are useful matched diagnostics; unusual return and penalty conventions can still differ.
- This is a descriptive comparison. It does not establish which model layer caused a difference or justify parameter changes.

Frozen simulation summary SHA-256: `558afbb75f7e546a60b2a3eea058d34b5c2ebe4c536f8a3e0af9a964b2b88c82`.
Frozen simulation drive CSV SHA-256: `59ce438065003aef2b8f5b0c3a944a216f1cd692bd7098a7370d52287f8776bc`.
Historical selected PBP rows SHA-256: `5ed0ac2797d602eea7e2e4401b0f0d525e139ead1db21bc435a937790d94c3c7`.
Historical selected game-index rows SHA-256: `2d8a31014cd79dfcb6da33c05baa3b6915c5c2fa82d454411113320b86a17db9`.
Historical database SHA-256: `896bad9a8dfc9e485aef7fc7e4db3b3988d4d0a1a2cde3e528378d32379d512e`.
Historical reference manifest SHA-256: `4a1a5f413cbca4c629f95111127ac066c77b74d70bf19a5a4563eeba7025b222`.
