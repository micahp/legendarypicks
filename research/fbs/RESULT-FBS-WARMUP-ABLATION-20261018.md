# FBS G2 warm-up ablation — 2023–2025

Generated: 2026-10-18
Phase 1 benchmark: `research/fbs/RESULT-FBS-GAME-WINNERS-20261018.md`
Baseline distinctions: [`research/fbs/BASELINE-DISTINCTIONS.md`](BASELINE-DISTINCTIONS.md)

## Question and method

This ablation keeps G2 completely fixed and changes only how far back its rating history starts, to test whether more history closes the Brier gap.

The five arms start their history in 2022, 2018, 2014, 2010, or 2004. G2 remains chronological Elo with initial rating 1500, logistic scale 400, home advantage 55 (zero at neutral sites), K=20, and 25% offseason regression. G3 is the Phase 1 score-margin model with its existing ridge, time-decay, and probability rules unchanged. The only varying input is the earliest season allowed into prior-result history.

Every arm forecasts the identical 2,398 FBS-vs-FBS games: 792 in 2023, 798 in 2024, and 808 in 2025. Predictions use the Phase 1 one-day UTC-date embargo and only prior completed schedules/results. Training updates include FBS-FBS and FBS-FCS completed results, as in the original G2 definition. No betting, player, team-statistic, play-by-play, or 2026 data enters this experiment.

The published Basic Elo Brier of 0.1976 is shown as context; its published population is 9,356 games across thirteen seasons, so the difference is not a same-population paired comparison.

## Results

| Arm | History starts | Seasons before 2023 | G2 Brier | G2 log loss | G2 BSS | G2 Δ vs A | G3 Brier | G3 log loss | G3 BSS |
|---|---|---|---|---|---|---|---|---|---|
| A | 2022 | 1 | 0.2133 | 0.6162 | 0.1469 | 0.0000 | 0.2155 | 0.6158 | 0.1379 |
| B | 2018 | 5 | 0.2110 | 0.6110 | 0.1558 | -0.0022 | 0.2125 | 0.6103 | 0.1499 |
| C | 2014 | 9 | 0.2105 | 0.6097 | 0.1582 | -0.0028 | 0.2123 | 0.6102 | 0.1507 |
| D | 2010 | 13 | 0.2103 | 0.6094 | 0.1587 | -0.0029 | 0.2123 | 0.6105 | 0.1507 |
| E | 2004 | 19 | 0.2103 | 0.6093 | 0.1588 | -0.0030 | 0.2123 | 0.6105 | 0.1507 |

Brier and log loss are lower-is-better. Brier Skill Score (BSS) is `1 - Brier / 0.25`, relative to a 0.50 coin flip. G2's original Phase 1 result is arm A; the run requires its per-game G2 and G3 probabilities to reproduce the stored Phase 1 ledger within 1e-12.

### Paired game-level comparisons against arm A

| Arm | History starts | G2 Δ Brier [95% CI] | G2 Δ log loss [95% CI] | G3 Δ Brier [95% CI] | G3 Δ log loss [95% CI] |
|---|---|---|---|---|---|
| A | 2022 | 0.0000 (control) | 0.0000 (control) | 0.0000 (control) | 0.0000 (control) |
| B | 2018 | -0.0022 [-0.0034, -0.0011] | -0.0053 [-0.0078, -0.0029] | -0.0030 [-0.0043, -0.0017] | -0.0055 [-0.0084, -0.0025] |
| C | 2014 | -0.0028 [-0.0039, -0.0016] | -0.0066 [-0.0090, -0.0039] | -0.0032 [-0.0045, -0.0018] | -0.0055 [-0.0087, -0.0023] |
| D | 2010 | -0.0029 [-0.0041, -0.0017] | -0.0068 [-0.0093, -0.0042] | -0.0032 [-0.0047, -0.0017] | -0.0053 [-0.0090, -0.0018] |
| E | 2004 | -0.0030 [-0.0041, -0.0018] | -0.0069 [-0.0093, -0.0045] | -0.0032 [-0.0048, -0.0017] | -0.0053 [-0.0092, -0.0017] |

Intervals resample paired game-level differences within season (2,000 replicates), preserving the fixed 2023/2024/2025 game counts. Negative candidate-minus-A values favor the longer-history arm. Since BSS = 1 - Brier / 0.25, its paired difference and interval are exactly -4 times the Brier difference and interval (with interval endpoints reversed). These intervals quantify uncertainty on this fixed evaluation population; they do not make the published Basic Elo comparison paired.

## Elo rating dispersion and convergence

The reported rating SD is the population standard deviation across the fixed set of teams appearing in the 2023–2025 FBS-vs-FBS evaluation games, immediately before 2023 forecasts after the 2023 offseason regression. The convergence reference is arm E (2004 start). A rating set is operationally treated as settled when its mean absolute team-rating gap from arm E is at most 25 Elo points at a season-end checkpoint and remains at or below that threshold at every later checkpoint through 2025. Twenty-five Elo points correspond to about a 3.6 percentage-point neutral win-probability change around an otherwise even matchup.

| Arm | History starts | Seasons before 2023 | Pre-2023 rating SD | Pre-2023 MAE vs E | End-2025 MAE vs E | First stable point |
|---|---|---|---|---|---|---|
| A | 2022 | 1 | 32.76 | 25.99 | 5.58 | 2023 (2 history seasons; 1 eval season) |
| B | 2018 | 5 | 53.14 | 4.43 | 1.29 | 2019 (2 history seasons; 0 eval seasons) |
| C | 2014 | 9 | 55.25 | 0.97 | 0.30 | 2015 (2 history seasons; 0 eval seasons) |
| D | 2010 | 13 | 55.62 | 0.18 | 0.06 | 2011 (2 history seasons; 0 eval seasons) |
| E | 2004 | 19 | 55.69 | 0.00 | 0.00 | Reference arm |

The full checkpoint series is in `fbs_warmup_ablation_rating_convergence_20261018.csv`; the table above makes the pre-2023 starting dispersion and any post-2023 convergence visible. A convergence time is not reported if the threshold is not met through 2025.

## Historical schedule/result coverage

The SportsDataverse release API was checked on 2026-10-18: `cfb_schedules` publishes 2001–2026 and `espn_cfb_schedules` publishes 2004–2026. This run uses only the two schedule/result releases for 2004–2025 (44 Parquet files); every input file's row count, size, direct release URL, and SHA-256 is in `fbs_warmup_ablation_sources_20261018.csv`. No team-info, betting, player, or play-by-play files were read.

### Reconciled historical final-score differences

The 2004–2025 source comparison found two completed FBS-participant games where the CFBD schedule score disagrees with ESPN. ESPN's final scores are the outcomes used by the existing Phase 1 pipeline; both cases were checked against official team records before allowing the mismatch through the otherwise fail-closed loader.

| Game ID | Matchup and date | CFBD score | ESPN score used | Independent official confirmation |
|---|---|---:|---:|---|
| 401014983 | Florida Atlantic–Air Force, 2018-09-08 | 33–26 | 33–27 | [Air Force Athletics](https://goairforcefalcons.com/game-center/4656), [FAU Athletics](https://fausports.com/sports/football/stats/2018/air-force/boxscore/2836) |
| 401021686 | Georgia State–Texas State, 2018-11-03 | 30–40 | 31–40 | [Georgia State Athletics](https://georgiastatesports.com/news/2018/11/3/211778896.aspx), [Georgia State 2018 results](https://georgiastatesports.com/sports/2018/8/31/211770084.aspx) |

For the 2004-start arm, all completed FBS-participant results in each available season through 2022 are eligible rating updates. The separate FBS-FBS counts below document the evaluation-style game population available in each season; FBS-FCS results are retained in training history but excluded from scoring.

| Season | Completed FBS-participant results available to train | FBS-FBS games |
|---|---|---|
| 2004 | 707 | 661 |
| 2005 | 718 | 664 |
| 2006 | 788 | 711 |
| 2007 | 792 | 712 |
| 2008 | 805 | 717 |
| 2009 | 808 | 714 |
| 2010 | 808 | 718 |
| 2011 | 812 | 715 |
| 2012 | 840 | 732 |
| 2013 | 848 | 737 |
| 2014 | 867 | 760 |
| 2015 | 870 | 765 |
| 2016 | 873 | 760 |
| 2017 | 874 | 776 |
| 2018 | 884 | 772 |
| 2019 | 888 | 774 |
| 2020 | 570 | 534 |
| 2021 | 887 | 770 |
| 2022 | 896 | 776 |

All 15,535 completed FBS-participant results in 2004–2022 were trainable; none were excluded for unresolved team IDs, ties, missing kickoff, or duplicate event rows.

## Interpretation

G2 improves monotonically as history deepens and the gain flattens: the full 2004 history closes 18.9% of the initial Basic Elo Brier gap, from 0.01567 to 0.01271, leaving 0.01271; the 2022-start ratings also settle within the 25-point criterion after one evaluation season.

Next lever: Use at least five warm-up seasons: that closes most of the measured history benefit (Δ Brier 0.00223), while extending five to 19 seasons adds only 0.00073, so the remaining 0.01271 gap calls for model/population diagnosis after the archive is available.

## Reproduction and artifacts

Run `/root/legendarypicks/backend/venv/bin/python backend/fbs_warmup_ablation.py` from the repository root. The script fails if the fixed evaluation population changes, if arm A does not reproduce the Phase 1 ledger, or if any required source season is absent.

- Per-arm metrics: `fbs_warmup_ablation_metrics_20261018.csv`.
- Paired game-level intervals: `fbs_warmup_ablation_paired_20261018.csv`.
- Rating checkpoints: `fbs_warmup_ablation_rating_convergence_20261018.csv`.
- Input manifest: `fbs_warmup_ablation_sources_20261018.csv`.
- Forecast ledgers: `fbs_warmup_ablation_forecasts_20261018_arm_<A-E>_start_<year>.csv`.
