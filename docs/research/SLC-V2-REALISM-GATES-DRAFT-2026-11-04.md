# SLC v2 whole-game realism gates

Status: revised draft for Micah review, 2026-11-04. This preregisters the whole-game realism gate that decides whether SLC v2 advances. It replaces the failed play-call table gate for that decision. It does not change simulator defaults or authorize a simulation run. This draft is not committed.

No SLC simulation was run for this revision. No SLC simulation output was used to set a threshold. Numeric distance limits are observed 2023-to-2024 season drift. Coverage limits are observed rolling-fold coverage ranges. Metrics 1-7 are reproduced by [`materialize_thresholds.py`](slc-v2-realism-gate-2026-11-04/materialize_thresholds.py) and [`observed_thresholds.json`](slc-v2-realism-gate-2026-11-04/observed_thresholds.json). Metrics 8-11 are reproduced by [`materialize_extended_thresholds.py`](slc-v2-realism-gate-2026-11-04/materialize_extended_thresholds.py) and [`extended_observed_thresholds.json`](slc-v2-realism-gate-2026-11-04/extended_observed_thresholds.json).

## Why this gate replaces the play-call table gate

The 2026-11-02 play-call table gate failed: 2025 run-or-pass log loss was 0.619 versus 0.590 for PlayCallLayer, the table's 2025 team pass-rate correlation was 0.42 versus the required 0.80, and its personnel TV distance was 0.069 versus the old 0.05 threshold. Those results remain evidence about that table. They are no longer the advancement rule for SLC v2.

The existing `football_realism_eval.py` reports game-level points, margins, attempts, scrimmage plays, dropbacks, touchdowns, drives, and player-stat distributions. The E3 joint reference adds joint distributions and situation-conditioned actions. These remain report-only diagnostics. Metrics 1-7 remain unchanged. Metrics 8-11 add four observed-calibrated advancement gates. Metrics 12-13 add season-envelope and baseline reports with no pass thresholds in this revision. The gates reuse existing Wasserstein-1 and total-variation distance definitions where applicable, and reuse the E3 situation buckets. Metrics 1, 3, 4, 6, and 7 add new gate statistics. Metric 5 turns published snap shares into a gate. Metric 2 uses the existing situation action comparison with an explicit low-support rule.

Phase 6 findings constrain interpretation. The separate participation model was fitted on 2022-2024 and checked on 2025, but has not been compared with integrated SLC v1 whole-game outputs. Its free lineup run recorded 1.190 entries per snap against 1.395 observed. The earlier P2 snap-share estimate was not evaluable in development because published-field coverage was 0.0000 in 2023 and 0.2947 in 2024. These motivate measuring the integrated result; they are not thresholds for this gate. The package sampler's 2025 retrospective TV distance of 0.049 is also not used to set any threshold here.

The lineup layer in scope is `scripts/nfl_sequence/participation_field.py`, enabled with `--participation-field`, table schema `lp.nfl.participation-field.v4`. The earlier `lineup_participation.py` reference at commit `9e60f218` is not the module this gate scores. Current-season snap updates and the player-dependent leave hazard are being added behind off-by-default settings. The run ledger's `research_integration` must name the frozen table, its hash, and all flags. For a 2025 check, the participation table must be fitted only on seasons before 2025.

## Data split, cutoff, and population

- **Development fit:** 2022-2024 regular seasons. Parameters for the 2025 check may use these seasons only.
- **Observed threshold folds:** 2023 and 2024 regular seasons, weeks 1-18. Distance thresholds are the direct season-to-season distance between the two observed folds. Metric 7 uses a rolling position-conditioned interval fit: 2022 predicts 2023; 2022-2023 predicts 2024.
- **Validation:** 2025 regular season, weeks 1-18. This is a known validation fold, not an untouched test. It must not be described as independent confirmation.
- **2025 roster denominator:** use published nflverse `roster_weekly_2025.parquet`, `status=ACT`, for the team and week. 2025 has no pregame roster snapshots. Build the simulated 2025 games from this same retrospective active list and label the result **retrospective roster**. An ACT player with no offensive snap gets a zero snap-share line. A player not on that team's ACT list is not a player-game. The same ACT rule is used for the 2023 and 2024 observed coverage folds.
- **Sealed season:** 2026 is outside this gate. Policy permits schema inspection only, no 2026 values for fitting, threshold selection, tuning, or evaluation. The available 2026 sources do not provide per-play participation, so 2026 personnel-on-field and simulated snap-share validation cannot be scored. Do not infer participation from play-by-play outcomes or player statistics.
- **Population:** NFL regular-season games only. Exclude postseason rows. Preserve source coverage, identity matching, team mapping, fallbacks, and excluded-row reasons.

The E3 joint reference pools 2022-2025. Its definitions and buckets can be reused, but its pooled histograms are not the 2025 validation comparator. Use season-specific observed data for scoring.

## Threshold construction and decision statistic

For metrics 1-6 and 9-11, each numeric `T` is the specified comparison statistic computed from observed 2023 and 2024 regular seasons. This is the preregistered season-to-season variability allowance. These are point estimates, not bootstrap percentiles. A 2025 candidate passes a distance gate when its point statistic against observed 2025 is at or below the listed `T`. Report sample counts and a 95% game-cluster bootstrap interval as uncertainty, but do not substitute that interval for the point-estimate decision. Use seed `20261104` and 10,000 replicates if the interval is reported.

For discrete distributions, `TVD = 0.5 * sum(abs(p_i - q_i))`. Wasserstein-1 is the integral of the absolute difference between empirical CDFs, in the metric's stated native unit. Quantiles use linear interpolation at rank `(n-1)p`.

For metrics 7 and 8, each numeric acceptance range is the closed interval from the smaller to the larger observed coverage rate in the two rolling folds. Metric 7 pools roles by line as already specified. Metric 8 gates each line-role and interval level separately. A candidate passes when its observed 2025 coverage rate is inside its range. Report a game-cluster interval for coverage as uncertainty. The empirical ranges, rather than nominal 80%, 50%, or 95% alone, are the thresholds because the historical player lines are discrete and zero-heavy.

No numeric threshold uses 2025 or 2026 values. Metrics 12-13 use the known 2025 validation fold only when scoring, and have no pass threshold here. Source and definition hashes are recorded below. Do not alter thresholds after viewing SLC v2 simulation output. A changed source, definition, table, or flag requires a new versioned gate before scoring.

## Metric registry

The minimum run is 30 independent seeds for each of the 272 2025 regular-season matchups: 8,160 completed simulated games, all 32 teams, and at least 17 distinct validation team-games per team. Thirty is the floor for the empirical intervals in metrics 7-8; with 30 seeds, the central 95% interval endpoints are near the seed extremes and must be reported with that limitation. A game counts only when its box score is valid, complete, and reconciliation passes. Keep failed seeds and report them separately.


| ID and metric | Exact definition and unit | Observed reference and cutoff | Comparison statistic and numeric PASS threshold | Minimum simulated games and teams | Unsupported and low-sample reporting |
|---|---|---|---|---|---|
| 1. Personnel-group frequencies by team | For each offensive scrimmage play, use the SLC v2 grouping code: RB and FB combined, then TE, with `-OL<n>` and `-QB<n>` suffixes when line count is not five or QB count is not one. `group_counts` decodes the code and derives WR count. Count group frequencies separately per team-season. Unit: team-game play; comparison unit: team-season. The controlling observed group is the `group` column contract from `build_tables.py`. | nflverse `pbp_participation_2023.csv` and `pbp_participation_2024.csv`, joined to regular-season PBP for weeks 1-18. The exact `build_tables.py` `group_code` and `nonstandard_offense` rules and `participation_field.group_counts` decoder are pinned by hashes below. | Calculate TVD for each team's 2023 and 2024 group distributions, then take the unweighted mean over 32 teams. `T_personnel = 0.185714 TVD`. Report the RB-only sensitivity, with FB separate, in the validation report; its observed 2023-to-2024 reference TVD is `0.192654`, descriptive and not a second gate. | 8,160 games; 32 teams; at least 17 team-games per team. | Retain six- and seven-lineman and second-QB groups. Exclude and separately count blank, defensive-label, fake-kick, undecodable, and builder-flagged nonstandard rows. A package with fewer than 30 observed plays is `LOW_SUPPORT`; show its count and never silently merge it. Report matched participation coverage per team. |
| 2. Play-call response to game situation | Map `pass` and `qb_spike` to pass; `run` and `qb_kneel` to run; retain punt and field goal as separate actions. For eligible regulation decisions use quarter, down, E3 distance bucket, E3 field bucket, pre-snap score-difference bucket, and E3 clock bucket. Unit: play decision. The primary statistic pools teams; team-by-situation tables are low-support diagnostics only. There is no team-conditioned gate in this revision, as Micah approved. | Official nflverse PBP, 2023 and 2024 regular seasons, weeks 1-18, with legal pre-snap down, distance, field, clock, and score state. Use the exact buckets in `e3_football_realism_joint_reference.py` and `playcall_model.py`. There are 150 pooled situation cells with at least 30 eligible actions in each fold. | For each supported cell, compute action TVD. Weight cells by the mean of their two season decision counts and take the weighted mean. `T_situation = 0.059757 TVD`. Minimum supported-decision share is `0.317564` on both the observed and simulated side, the smaller observed fold share. | 8,160 games; 32 teams; at least 17 team-games per team. | A cell below 30 decisions on either side is `LOW_SUPPORT`, excluded from the supported-cell TVD and included in the support-share denominator. If either side's supported-decision share is below 0.317564, the metric is `NOT_EVALUABLE`. Team-by-situation cells do not reach 30 in both observed folds; report them as low support only. Report fourth-down behavior as a diagnostic. |
| 3. Top receiver target-share spread | For each team-game, divide the highest individual target count by the team's total targets with an identified receiver. The top receiver can be WR, TE, RB, or FB. For each team compare the linearly interpolated p10, p50, and p90 of its team-game top-receiver shares. Unit: target share per team-game; comparison unit: team-season quantiles. | Official nflverse PBP, 2023 and 2024 regular seasons, weeks 1-18; `pass_attempt=1` rows with non-null `receiver_player_id`. Each fold has 544 team-games with identified targets. | Mean absolute difference across the 32 teams and the three quantiles. `T_top = 0.027769 share` (2.7769 percentage points). | 8,160 games; 32 teams; at least 17 team-games per team. | Show identified-target denominators and missing receiver IDs. Fewer than 10 team-games with identified targets for any team is `LOW_SUPPORT` and makes the metric `NOT_EVALUABLE`; retain the count. |
| 4. Second running back participation and usage | In each team-game, rank active roster players classified as position RB by offensive snaps. Exclude FB, including any player listed as RB on the weekly roster but identified as FB in the game-level snap-position source. RB2 is the player with the second-most snaps. Ties are broken by ascending GSIS ID on both the observed and simulated sides, as Micah confirmed. Record whether RB2 played, RB2 offensive snaps, and RB2 opportunities, defined as carries plus identified targets. If fewer than two ACT RBs are available, report a zero team-game line and `no_RB2`. Unit: team-game RB2 line. | Published weekly ACT rosters for 2023 and 2024, game-level nflverse snap-count positions, and PBP player opportunities, regular season weeks 1-18. Each fold has 544 team-games and at least two active RBs in every observed game. | Absolute difference in RB2 appearance rates: `T_RB2_appears = 0.007353` (0.7353 percentage points). Wasserstein-1 for snap count: `T_RB2_snaps = 1.281250 snaps`. Wasserstein-1 for opportunities: `T_RB2_opportunities = 0.676471 opportunities`. | 8,160 games; 32 teams; at least 17 team-games per team. | Zero-fill an active RB with no snap or opportunity. Keep no-RB2 and identity-match counts. Report FB snap and opportunity distributions separately, outside the RB2 gate. Fewer than 10 observed team-games for a team is `LOW_SUPPORT` and `NOT_EVALUABLE`. |
| 5. Simulated snap shares against published nflverse counts | For each player-game with positive published offensive snaps, use `offense_pct` as the observed share and simulated player snaps divided by that simulated team's offensive snaps as the simulated share. Compare pooled and broad position-group distributions. Position groups are QB, RB, FB, TE, WR, OL (C/G/T/OT/OG/OL), and OTHER. Unit: share per player-game. | Published nflverse snap-count parquet files for 2023 and 2024, regular season weeks 1-18; 10,078 positive-snap player-games in 2023 and 10,056 in 2024. | Wasserstein-1 on the pooled shares: `T_snap_all = 0.003384 share`. By position, use the maximum W1 among groups with at least 100 player-games in each observed fold: `T_snap_position = 0.039670 share`. | 8,160 games; 32 teams; at least 17 team-games per team. | Report GSIS/PFR match rate, null `offense_pct`, and team-snap reconciliation. A position group with fewer than 100 player-games in either observed fold or fewer than 30 game clusters is `LOW_SUPPORT`; keep it visible. Do not treat missing shares as zero. Zero-snap ACT players are covered by metric 7. |
| 6. Joint pass rate, snap shares, and targets | One row per skill-player-game with positive offensive snaps and matched identity. The vector is team pass rate, player offensive snap share, and player target share. Pass rate is pass calls, including spikes, divided by pass plus run calls, including kneels. Target share is identified targets to that player divided by team identified targets. Include zero-target players. Unit: skill-player-game. | Join official nflverse PBP, `players.csv` GSIS/PFR crosswalk, and published snap counts for 2023 and 2024 regular seasons, weeks 1-18. Reference samples are 5,968 and 5,928 skill-player-games. | New three-dimensional binned TVD. Pass-rate bins: `<=.40`, `(.40,.50]`, `(.50,.60]`, `(.60,.70]`, `>.70`. Snap-share bins: `<=.10`, `(.10,.25]`, `(.25,.50]`, `(.50,.75]`, `>.75`. Target-share bins: `0`, `(0,.05]`, `(.05,.10]`, `(.10,.20]`, `(.20,.35]`, `>.35`. `T_joint = 0.079724 TVD`. | 8,160 games; 32 teams; at least 17 team-games per team. At least 100 matched skill-player-games and 30 game clusters on each side. | Report each coordinate's missingness, player identity match, zero-target coverage, bin counts, and team-games lacking pass rate or snap denominator. Keep low-count bins and flag bins with fewer than 30 rows; never merge them. Any missing coordinate makes that row unsupported, not imputed. |
| 7. Per-player central 80% interval coverage | For each 2025 active player-game, and each line below, form the simulated interval from the p10 and p90 across that matchup's 30 seeds. Coverage is the share of observed player-game lines inside the inclusive interval. Lines are offensive snap share for all ACT players; passing attempts for QB; rushing attempts and yards for QB/RB/FB/TE/WR; targets, receptions, and receiving yards for RB/FB/TE/WR; and offensive scrimmage touchdowns for QB/RB/FB/TE/WR. Historical interval strata combine RB and FB because the weekly roster position is not consistently split; report FB separately where available. Unit: player-game line. | nflverse PBP, `roster_weekly` ACT rows, published snap counts, and `players.csv` for 2022-2024 regular seasons, weeks 1-18. For 2023, fit position-conditioned p10-p90 intervals on 2022 ACT player-games. For 2024, fit on 2022-2023 ACT player-games. Zero-fill active players with no offensive snap or stat line. Fold denominators: 26,112 active player-games in 2023 and 26,121 in 2024. | For historical calibration, score each held-out fold against the prior-season position-conditioned empirical p10-p90 interval. Pool coverage by line across its specified roles. The 2025 PASS envelope is: snap share `[0.9552, 0.9622]`; passing attempts `[0.9074, 0.9326]`; rushing attempts `[0.9495, 0.9497]`; rushing yards `[0.8972, 0.9037]`; targets `[0.9185, 0.9250]`; receptions `[0.9203, 0.9212]`; receiving yards `[0.8837, 0.8871]`; offensive touchdowns `[0.9450, 0.9682]`. | 8,160 games; 32 teams; 30 seeds for every matchup. At least 100 observed player-game lines per line and 30 observed game clusters. | Report line and game-cluster counts, player identity coverage, zero-line policy, interval endpoints, and coverage by role. A role-line with fewer than 100 training lines or 30 game clusters is `LOW_SUPPORT`; do not silently borrow another role's interval. A line below its minimum is `NOT_EVALUABLE`, not a pass. |
| 8. Per-player central 50% and 95% interval coverage | Use exactly metric 7's ACT roster, zero-filled player-game lines, and position roles. For each line-role, form central 50% intervals from p25-p75 and central 95% intervals from p2.5-p97.5 across the 30 seeds for each 2025 matchup. Unit: player-game line, summarized by line-role coverage. | Same nflverse PBP, ACT weekly rosters, published snap counts, and player crosswalk as metric 7, with 2022-2024 cutoffs, regular seasons weeks 1-18. Historical folds: train 2022, hold out 2023; train pooled 2022-2023, hold out 2024. | For every line-role and each central interval, compare observed 2025 coverage with the closed envelope of the two held-out fold coverages. The full numeric envelopes and held-out counts are in the Metric 8 table below and `extended_observed_thresholds.json`. | 8,160 games; 32 teams; 30 seeds per matchup; at least 100 observed player-game lines and 30 game clusters per line-role. | Report line-role and fold sample counts, endpoints, and coverages. A line-role below 100 training or observed lines, or 30 game clusters, is `LOW_SUPPORT` and `NOT_EVALUABLE`; do not borrow another role's interval. Each line-role and interval level is scored separately. |
| 9. Season mean bias by line and role | For each metric-7 line and position role, calculate the league mean over zero-filled ACT player-games. For each 2025 player-game, use the mean across its 30 simulated seeds; then average those player-game means. Unit: native stat value per player-game, by line-role. | Observed ACT roster player-games, PBP player lines, and published snap shares for 2023 and 2024 regular seasons, weeks 1-18. | `T_mean = abs(mean_2024 - mean_2023)` for each line-role. PASS when the absolute difference between the 2025 simulated and observed league means is at most that line-role's T. Numeric T values and fold counts are in the Metric 9 table and JSON. | 8,160 games; 32 teams; 30 seeds per matchup; at least 100 observed player-game lines and 30 game clusters per line-role. | Report observed and simulated line counts, means, signed bias, T, and game clusters. Any unsupported line-role is `NOT_EVALUABLE`, not a pass. Do not pool roles. |
| 10. Player-game variance ratio by line and role | For each metric-7 line-role, calculate population variance (ddof=0) over single player-game values, including zero-filled ACT lines. The simulated season uses one hash-selected seed result per matchup, not seed-averaged player lines. Unit: squared native stat value per player-game, by line-role. | Observed ACT roster player-games for 2023 and 2024 regular seasons, weeks 1-18. | `T_logvar = abs(ln(var_2024 / var_2023))` for each line-role. PASS when `abs(ln(var_sim_2025 / var_obs_2025)) <= T_logvar`. Use the deterministic one-seed-per-matchup selection rule in the metric notes below. Numeric T values and fold counts are in the Metric 10 table and JSON. | 8,160 games; 32 teams; one of 30 seeds per matchup for scoring; at least 100 player-game lines and 30 game clusters per line-role. | Report the selected seed for each matchup, both variances, sample counts, and T. Zero variance on either comparison side is `NOT_EVALUABLE`; do not add epsilon. A line-role below the minimum is `NOT_EVALUABLE`. |
| 11. Tail frequency by line and role | For each metric-7 line-role, fix p95 and p99 cutoffs from its 2022 zero-filled ACT player-game values using linear interpolation at rank `(n-1)p`. Tail frequency is the fraction of player-games strictly above each cutoff. Unit: player-game tail frequency, separately at p95 and p99, by line-role. | Observed ACT roster player-games for 2022-2024 regular seasons, weeks 1-18. Cutoffs use 2022 only; frequency-drift calibration compares 2023 with 2024. | `T_tail = abs(freq_2024 - freq_2023)` for each line-role and cutoff. PASS when the absolute 2025 simulated-versus-observed frequency difference is at most T. Use the same one-seed-per-matchup selection as metric 10. Numeric cutoffs, T values, and counts are in the Metric 11 table and JSON. | 8,160 games; 32 teams; one of 30 seeds per matchup for scoring; at least 100 player-game lines and 30 game clusters per line-role. | Report cutoff, exceedance numerator, denominator, frequency, and T for both cutoffs. A line-role below the 2022 training or 2025 comparison minimum is `NOT_EVALUABLE`; do not pool roles. |
| 12. Season envelope, report-only | For each complete 2025 season replicate, compute league game means for total points, combined offensive scrimmage plays, pass-call rate, and total offensive drives. Also compute team-game top-receiver target-share and top-carrier share distributions, summarized by p10, p50, and p90. Unit: game mean for the four league metrics; team-game share quantile for the two share distributions. | Observed nflverse 2025 regular-season PBP and final scores, weeks 1-18; 272 matchups and 544 team-games. This is the known validation fold. | Draw one of the 30 seed results for each matchup independently with replacement to form each of 1,000 season replicates. For each league mean and each share-distribution quantile, report the observed value's midrank percentile among the 1,000 simulated values. No PASS threshold. | 8,160 available games across 30 seeds; 32 teams; 1,000 sampled seasons, each containing one game draw per matchup. | Report all failed or incomplete seeds. Top receiver is max identified targets divided by team identified targets, matching metric 3. Top carrier is max identified non-kneel carries divided by team identified non-kneel carries. Show denominators, omitted team-games, observed quantiles, simulated 2.5-97.5% range, and percentile. |
| 13. As-of baseline skill | On each 2025 ACT player-game and metric-7 line-role, compare SLC's 30-seed ensemble with a rolling player-mean baseline. Baseline uses that player's prior 2025 player-games through the previous week; if none, that player's 2024 ACT player-games; if none, the 2024 league mean for that line-role. All lines are zero-filled. Report MAE of the 30-seed ensemble mean and empirical-ensemble CRPS for SLC. The deterministic baseline's CRPS equals its absolute error. Unit: native stat value per player-game. | Observed 2025 weekly ACT roster and player lines, plus prior 2024 ACT player-game lines. Use the retrospective ACT roster because 2025 has no pregame snapshots. No 2026 values. | Report MAE and CRPS for every line-role beside SLC and the baseline on identical rows. For SLC, ensemble CRPS is `mean(|x_s-y|) - 0.5*mean(|x_s-x_t|)` over all ordered seed pairs. Baseline CRPS is absolute error for its point forecast. Comparative report only; this revision assigns no PASS threshold. | 8,160 games; 32 teams; 30 seeds per matchup; at least 100 matched player-game lines and 30 game clusters per line-role. | Report player-game counts, cold-start fallback counts, role and identity coverage, and identical scoring denominators. Missing predictions are unsupported and are not zero-filled; observed ACT stat lines retain the metric-7 zero-fill rule. |

### Coverage envelope calculation details

For metric 7, historical p10 and p90 intervals use linear interpolation at rank `(n-1)p` within each training position-role distribution. All eligible ACT player-games, including zeros, are in the training and held-out distributions. Its reported envelope for a stat is the minimum and maximum of its 2023 and 2024 held-out coverage rates. The eight ranges in metric 7 remain its complete set of thresholds. Metric 8 uses the central 50% and 95% intervals and separate line-role envelopes listed below. Metric 7 position-role coverage remains a required breakdown, while its pass statistic is pooled over the roles listed for that line.

## Materialized thresholds for metrics 8-11

The separate [`materialize_extended_thresholds.py`](slc-v2-realism-gate-2026-11-04/materialize_extended_thresholds.py) computes these values from the same hash-verified 2022-2024 inputs and the exact metric-7 ACT player-game rows, role mapping, and zero-fill logic. The companion [`extended_observed_thresholds.json`](slc-v2-realism-gate-2026-11-04/extended_observed_thresholds.json) contains full precision, per-fold interval endpoints and coverage counts, each season mean and variance, each tail cutoff and exceedance count, and every input hash. FB remains combined with RB, matching metric 7's role mapping; there is no separate FB threshold. The tables below display coverage to six decimals and T values to nine decimals.

### Metric 8: central 50% and 95% coverage envelopes

2023 is held out after training on 2022. 2024 is held out after training on 2022-2023. `n_2023` and `n_2024` are held-out ACT player-game lines. Training counts, endpoints, coverage numerators, and game clusters are in the JSON. PASS requires the 2025 line-role coverage to fall inside both listed envelopes.

| Line | Role | n 2023 | n 2024 | Central 50% envelope | Central 95% envelope |
|---|---:|---:|---:|---:|---:|
| Offensive snap share | OL | 4366 | 4372 | [0.756176, 0.761338] | [1.000000, 1.000000] |
| Offensive snap share | OTHER | 14238 | 14241 | [0.996349, 0.997261] | [0.996349, 0.997261] |
| Offensive snap share | QB | 1112 | 1098 | [1.000000, 1.000000] | [1.000000, 1.000000] |
| Offensive snap share | RB | 1850 | 1846 | [0.494041, 0.537297] | [0.972914, 0.974595] |
| Offensive snap share | TE | 1669 | 1730 | [0.503895, 0.518497] | [0.980228, 0.984393] |
| Offensive snap share | WR | 2877 | 2834 | [0.517290, 0.547445] | [0.982004, 0.983664] |
| Offensive touchdowns | QB | 1112 | 1098 | [0.909173, 0.915301] | [0.986339, 0.986511] |
| Offensive touchdowns | RB | 1850 | 1846 | [0.793608, 0.812973] | [0.994583, 0.995135] |
| Offensive touchdowns | TE | 1669 | 1730 | [0.902890, 0.907130] | [0.990751, 0.991013] |
| Offensive touchdowns | WR | 2877 | 2834 | [0.833804, 0.844282] | [0.973183, 0.981230] |
| Passing attempts | QB | 1112 | 1098 | [0.750000, 0.760474] | [0.975410, 0.987410] |
| Receiving yards | RB | 1850 | 1846 | [0.727568, 0.742145] | [0.950270, 0.959913] |
| Receiving yards | TE | 1669 | 1730 | [0.744757, 0.749711] | [0.970520, 0.971240] |
| Receiving yards | WR | 2877 | 2834 | [0.749471, 0.768161] | [0.965242, 0.976359] |
| Receptions | RB | 1850 | 1846 | [0.782703, 0.802275] | [0.984865, 0.985915] |
| Receptions | TE | 1669 | 1730 | [0.753745, 0.758382] | [0.972254, 0.980228] |
| Receptions | WR | 2877 | 2834 | [0.811927, 0.822037] | [0.985180, 0.985749] |
| Rushing attempts | QB | 1112 | 1098 | [0.748634, 0.770683] | [0.982914, 0.985428] |
| Rushing attempts | RB | 1850 | 1846 | [0.735135, 0.766522] | [0.965872, 0.981081] |
| Rushing attempts | TE | 1669 | 1730 | [0.982081, 0.985620] | [0.982081, 0.985620] |
| Rushing attempts | WR | 2877 | 2834 | [0.882517, 0.887791] | [0.990615, 0.991531] |
| Rushing yards | QB | 1112 | 1098 | [0.654676, 0.663934] | [0.954463, 0.967626] |
| Rushing yards | RB | 1850 | 1846 | [0.728649, 0.731853] | [0.955580, 0.964324] |
| Rushing yards | TE | 1669 | 1730 | [0.983815, 0.989814] | [0.983815, 0.989814] |
| Rushing yards | WR | 2877 | 2834 | [0.888425, 0.893790] | [0.962113, 0.970360] |
| Targets | RB | 1850 | 1846 | [0.820000, 0.832069] | [0.987541, 0.988649] |
| Targets | TE | 1669 | 1730 | [0.752546, 0.758960] | [0.966474, 0.977831] |
| Targets | WR | 2877 | 2834 | [0.534227, 0.549878] | [0.983063, 0.985749] |

### Metric 9: mean-bias thresholds

Means and thresholds use native line units. `n` is the zero-filled ACT player-game count for the indicated season.

| Line | Role | n 2023 | n 2024 | Mean 2023 | Mean 2024 | T mean bias |
|---|---:|---:|---:|---:|---:|---:|
| Offensive snap share | OL | 4366 | 4372 | 0.626525424 | 0.624489936 | 0.002035488 |
| Offensive snap share | OTHER | 14238 | 14241 | 0.000096221 | 0.000107436 | 0.000011215 |
| Offensive snap share | QB | 1112 | 1098 | 0.493372302 | 0.495418944 | 0.002046641 |
| Offensive snap share | RB | 1850 | 1846 | 0.321583784 | 0.319328277 | 0.002255506 |
| Offensive snap share | TE | 1669 | 1730 | 0.418538047 | 0.418219653 | 0.000318394 |
| Offensive snap share | WR | 2877 | 2834 | 0.488199513 | 0.489562456 | 0.001362943 |
| Offensive touchdowns | QB | 1112 | 1098 | 0.104316547 | 0.100182149 | 0.004134397 |
| Offensive touchdowns | RB | 1850 | 1846 | 0.230810811 | 0.254062839 | 0.023252028 |
| Offensive touchdowns | TE | 1669 | 1730 | 0.103055722 | 0.106936416 | 0.003880694 |
| Offensive touchdowns | WR | 2877 | 2834 | 0.176572819 | 0.194424841 | 0.017852022 |
| Passing attempts | QB | 1112 | 1098 | 17.771582734 | 17.470856102 | 0.300726632 |
| Receiving yards | RB | 1850 | 1846 | 9.772432432 | 9.587215601 | 0.185216831 |
| Receiving yards | TE | 1669 | 1730 | 16.237866986 | 16.052023121 | 0.185843865 |
| Receiving yards | WR | 2877 | 2834 | 28.860966284 | 28.745589273 | 0.115377011 |
| Receptions | RB | 1850 | 1846 | 1.367027027 | 1.272481040 | 0.094545987 |
| Receptions | TE | 1669 | 1730 | 1.590173757 | 1.597687861 | 0.007514105 |
| Receptions | WR | 2877 | 2834 | 2.286757039 | 2.293577982 | 0.006820943 |
| Rushing attempts | QB | 1112 | 1098 | 2.142086331 | 2.150273224 | 0.008186893 |
| Rushing attempts | RB | 1850 | 1846 | 6.358378378 | 6.425243770 | 0.066865392 |
| Rushing attempts | TE | 1669 | 1730 | 0.014979029 | 0.035838150 | 0.020859121 |
| Rushing attempts | WR | 2877 | 2834 | 0.161626694 | 0.151023289 | 0.010603406 |
| Rushing yards | QB | 1112 | 1098 | 8.859712230 | 10.032786885 | 1.173074655 |
| Rushing yards | RB | 1850 | 1846 | 26.317837838 | 27.983748646 | 1.665910808 |
| Rushing yards | TE | 1669 | 1730 | 0.020371480 | 0.180346821 | 0.159975341 |
| Rushing yards | WR | 2877 | 2834 | 0.968022245 | 0.757939308 | 0.210082937 |
| Targets | RB | 1850 | 1846 | 1.765945946 | 1.608342362 | 0.157603584 |
| Targets | TE | 1669 | 1730 | 2.244457759 | 2.215028902 | 0.029428857 |
| Targets | WR | 2877 | 2834 | 3.645116441 | 3.627734651 | 0.017381790 |

### Metric 10: log-variance-ratio thresholds

Variance is the population variance (`ddof=0`) of single player-game lines. T is dimensionless.

| Line | Role | n 2023 | n 2024 | Variance 2023 | Variance 2024 | T log variance ratio |
|---|---:|---:|---:|---:|---:|---:|
| Offensive snap share | OL | 4366 | 4372 | 0.204196242 | 0.205961199 | 0.008606297 |
| Offensive snap share | OTHER | 14238 | 14241 | 0.000004900 | 0.000004251 | 0.142156673 |
| Offensive snap share | QB | 1112 | 1098 | 0.218155084 | 0.223992584 | 0.026406738 |
| Offensive snap share | RB | 1850 | 1846 | 0.064648465 | 0.067523167 | 0.043506405 |
| Offensive snap share | TE | 1669 | 1730 | 0.075454903 | 0.075535327 | 0.001065296 |
| Offensive snap share | WR | 2877 | 2834 | 0.105380769 | 0.107368828 | 0.018689729 |
| Offensive touchdowns | QB | 1112 | 1098 | 0.120413022 | 0.124754065 | 0.035416637 |
| Offensive touchdowns | RB | 1850 | 1846 | 0.281320964 | 0.300024122 | 0.064366638 |
| Offensive touchdowns | TE | 1669 | 1730 | 0.115203365 | 0.116310268 | 0.009562385 |
| Offensive touchdowns | WR | 2877 | 2834 | 0.191275985 | 0.215903992 | 0.121116495 |
| Passing attempts | QB | 1112 | 1098 | 327.098904689 | 317.755525861 | 0.028980285 |
| Receiving yards | RB | 1850 | 1846 | 246.583348137 | 233.160053244 | 0.055974921 |
| Receiving yards | TE | 1669 | 1730 | 561.734312047 | 580.803073942 | 0.033382772 |
| Receiving yards | WR | 2877 | 2834 | 1351.380739143 | 1251.265197553 | 0.076971642 |
| Receptions | RB | 1850 | 1846 | 3.053939810 | 2.761615405 | 0.100616698 |
| Receptions | TE | 1669 | 1730 | 4.317363002 | 4.741035116 | 0.093610691 |
| Receptions | WR | 2877 | 2834 | 6.455483296 | 6.454390656 | 0.000169272 |
| Rushing attempts | QB | 1112 | 1098 | 8.708228741 | 8.599458031 | 0.012569229 |
| Rushing attempts | RB | 1850 | 1846 | 48.207240614 | 50.605191571 | 0.048544941 |
| Rushing attempts | TE | 1669 | 1730 | 0.015952980 | 0.128195396 | 2.083909960 |
| Rushing attempts | WR | 2877 | 2834 | 0.262024187 | 0.251715608 | 0.040136908 |
| Rushing yards | QB | 1112 | 1098 | 265.046866104 | 329.720236496 | 0.218337863 |
| Rushing yards | RB | 1850 | 1846 | 1111.265465595 | 1306.544697974 | 0.161886592 |
| Rushing yards | TE | 1669 | 1730 | 0.081070923 | 13.124700458 | 5.086926907 |
| Rushing yards | WR | 2877 | 2834 | 20.461959696 | 12.186290178 | 0.518255974 |
| Targets | RB | 1850 | 1846 | 4.598732213 | 3.948987826 | 0.152321360 |
| Targets | TE | 1669 | 1730 | 7.545992351 | 8.142201878 | 0.076044036 |
| Targets | WR | 2877 | 2834 | 13.283511952 | 13.377649985 | 0.007061840 |

### Metric 11: fixed-cutoff tail-frequency thresholds

Cutoffs come from 2022. Frequencies count lines strictly above the cutoff. Each T is an absolute difference in proportions.

| Line | Role | n 2022 | n 2023 | n 2024 | 2022 p95 cutoff | T p95 | 2022 p99 cutoff | T p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Offensive snap share | OL | 4343 | 4366 | 4372 | 1.0000 | 0.000000000 | 1.0000 | 0.000000000 |
| Offensive snap share | OTHER | 14141 | 14238 | 14241 | 0.0000 | 0.000912280 | 0.0000 | 0.000912280 |
| Offensive snap share | QB | 1102 | 1112 | 1098 | 1.0000 | 0.000000000 | 1.0000 | 0.000000000 |
| Offensive snap share | RB | 1969 | 1850 | 1846 | 0.7660 | 0.005543615 | 0.8900 | 0.002186759 |
| Offensive snap share | TE | 1693 | 1669 | 1730 | 0.9100 | 0.003229929 | 0.9808 | 0.000211265 |
| Offensive snap share | WR | 2768 | 2877 | 2834 | 0.9600 | 0.000136139 | 1.0000 | 0.000000000 |
| Offensive touchdowns | QB | 1102 | 1112 | 1098 | 1.0000 | 0.000171994 | 1.0000 | 0.000171994 |
| Offensive touchdowns | RB | 1969 | 1850 | 1846 | 1.0000 | 0.003872800 | 2.0000 | 0.000552253 |
| Offensive touchdowns | TE | 1693 | 1669 | 1730 | 1.0000 | 0.000261137 | 2.0000 | 0.000620288 |
| Offensive touchdowns | WR | 2768 | 2877 | 2834 | 1.0000 | 0.008047668 | 2.0000 | 0.000674073 |
| Passing attempts | QB | 1102 | 1112 | 1098 | 46.0000 | 0.004925568 | 55.0000 | 0.002823970 |
| Receiving yards | RB | 1969 | 1850 | 1846 | 41.0000 | 0.000965125 | 72.0000 | 0.003231531 |
| Receiving yards | TE | 1693 | 1669 | 1730 | 66.4000 | 0.002955285 | 98.0000 | 0.002552150 |
| Receiving yards | WR | 2768 | 2877 | 2834 | 103.0000 | 0.004833556 | 148.0000 | 0.007899509 |
| Receptions | RB | 1969 | 1850 | 1846 | 5.0000 | 0.003182337 | 8.0000 | 0.002701531 |
| Receptions | TE | 1693 | 1669 | 1730 | 6.0000 | 0.009200414 | 8.0000 | 0.004180621 |
| Receptions | WR | 2768 | 2877 | 2834 | 7.0000 | 0.000683640 | 10.0000 | 0.002311791 |
| Rushing attempts | QB | 1102 | 1112 | 1098 | 8.9500 | 0.003923091 | 13.0000 | 0.002801038 |
| Rushing attempts | RB | 1969 | 1850 | 1846 | 20.0000 | 0.014168838 | 26.0000 | 0.003265497 |
| Rushing attempts | TE | 1693 | 1669 | 1730 | 0.0000 | 0.003539207 | 1.0000 | 0.004025116 |
| Rushing attempts | WR | 2768 | 2877 | 2834 | 1.0000 | 0.005181631 | 3.0000 | 0.000310667 |
| Rushing yards | QB | 1102 | 1112 | 1098 | 49.0000 | 0.020495079 | 89.9900 | 0.000864882 |
| Rushing yards | RB | 1969 | 1850 | 1846 | 103.0000 | 0.013623613 | 144.0000 | 0.004353606 |
| Rushing yards | TE | 1693 | 1669 | 1730 | 0.0000 | 0.003130184 | 6.0000 | 0.005780347 |
| Rushing yards | WR | 2768 | 2877 | 2834 | 7.0000 | 0.005634202 | 26.3300 | 0.004465857 |
| Targets | RB | 1969 | 1850 | 1846 | 6.0000 | 0.008047202 | 9.0000 | 0.003777927 |
| Targets | TE | 1693 | 1669 | 1730 | 8.0000 | 0.004964033 | 10.0000 | 0.006965162 |
| Targets | WR | 2768 | 2877 | 2834 | 11.0000 | 0.002900992 | 14.0000 | 0.000236833 |

Metric 10 and metric 11 use the same selected simulated result per matchup. Sort each matchup's 30 exported seed identifiers, then select index `int(SHA256("slc-v2-m10-m11-20261104|<game_id>").hexdigest()[:16], 16) % 30`. The selection is independent of result values and is fixed before scoring. Metric 9 instead uses each player-game's mean across all 30 seeds.

### Metric 12 and metric 13 reporting protocol

For metric 12, a game row contains both teams. Total points are the final combined score. Scrimmage plays are the sum of team `plays` in the box score, matching `football_realism_eval.py`. Pass-call rate is pass plus spike calls divided by pass, spike, run, and kneel calls. Drives are the sum of both teams' non-null offensive drive groups. Compute each of these four season summaries as the mean across 272 games. For receiver and carrier shares, first calculate one value per team-game and then p10, p50, and p90 across team-games with identified denominators, up to 544 per season. Report the count. The receiver definition is exactly metric 3. Carrier share uses identified player rush attempts excluding `qb_kneel` from numerator and denominator. For every replicate and matchup, choose one of its 30 valid seed results by sorting seed identifiers and taking index `int(SHA256("slc-v2-m12-20261104|<replicate>|<game_id>").hexdigest()[:16], 16) % 30`, for replicate indices 0-999. Report the observed value's midrank percentile: `(count(simulated < observed) + 0.5 * count(simulated == observed)) / 1000`. Also report the empirical 2.5th to 97.5th percentile range. No season-envelope percentile is a gate.

For metric 13, the player baseline is role-specific for each metric-7 line. Use the player's mean over prior 2025 ACT player-games through the previous week. If there are none, use that player's 2024 ACT mean for the same line-role. If the player has no 2024 line-role history, use the 2024 league mean for that line-role and flag a cold-start fallback. Score SLC's 30-seed ensemble and the baseline on the same observed 2025 ACT player-game rows. SLC MAE uses its ensemble mean. SLC CRPS uses the empirical 30-member distribution and the formula in the registry; deterministic-baseline CRPS equals absolute error. Report counts, fallback rates, MAE, and CRPS by line-role. This is a comparative benchmark without a pass threshold in this revision.

## What exports support

`--export-boxscores` produces per-seed box scores, but those rows do not yet carry lineup groups or player snap counts. Metrics 1, 4 snap measures, 5, 6, and the offensive snap-share line in metric 7 need the separately persisted `outcome['playcall']['lineup'][team]` summary from `--participation-field`, with `team_snaps`, `player_snaps` keyed by `gsis_id`, and `groups` keyed by grouping code. Metric 4 opportunities, metric 6 targets, and metric 7's other player lines use the ID-keyed box-score rows; metric 6 combines those rows with lineup snap shares.

Metric 2 needs the per-play decision records and each snap's situation in `participants.lineup`; the summary alone does not retain the situation-conditioned action ledger. Keep the ID-keyed player rows instead of relying on the compact marginal histogram in `football_realism_eval.py`. Retain `short_snaps` and `cell_fallbacks` from `slc_engine.lineup_summary` for support and fallback reporting. A box score alone cannot establish personnel or player snap shares.

## Advance rule and report

SLC v2 advances past this realism gate only if all eleven thresholded metrics (1-11) are evaluable and pass on the 2025 known validation fold, the run meets the minimum games and teams, and there are no `ILLEGAL_STATE`, `NONCAUSAL_INFORMATION`, `STAT_ACCOUNTING`, or `UNSUPPORTED_RULE` failures. `FAIL` and `NOT_EVALUABLE` both block advancement. Metrics 12-13 are reported beside the gate and do not alter its decision. Do not use the report-only game/player evaluator panel as a replacement threshold, and do not clip record outcomes.

Publish one row per thresholded metric with observed and simulated counts, comparison statistic, materialized threshold, uncertainty interval, status (`PASS`, `FAIL`, or `NOT_EVALUABLE`), fallback and identity coverage, source hashes, and all failed-seed evidence. Publish metrics 12-13 as separate descriptive reports with their sample counts and seed coverage. Report low-support cells and groups with their counts, even when the parent metric remains evaluable.

## Source hashes for observed thresholds

The threshold calculations read explicit 2022-2024 value files only. Raw files are under `/root/gridiron-playbooks-research/data/raw/` and `/root/lp-snapshots/nfl-backfill-2026-10-27/raw/`. Hashes pin the exact inputs and definitions; the 2025 and 2026 data files are not in this list.

| Source | SHA-256 |
|---|---|
| `pbp_2022.csv.gz` | `0c69a71eb39498956c7b1d5c1ca52ce7fe679934a95d1af249facb5ea9829ea4` |
| `pbp_2023.csv.gz` | `4649804ee0f0a40b41e51ec75a1ce921949d7fab5459213488656b92f78560e8` |
| `pbp_2024.csv.gz` | `23370d5d10f8104d80d46a1fc5e61f4f6f5a3263fe96fe2dd629913cfcb08c06` |
| `pbp_participation_2023.csv` | `ad01aeb4045ee19a4f086ff38b52b14c8f427d3401e529c3078a4545921650a9` |
| `pbp_participation_2024.csv` | `b1f436a98b2a7759eb4ed1181e072a35c2666f9aeb356a49c943d28d6be6b0b9` |
| `players.csv` | `c5239e1480b397732d004f81c87dbb07565ff6ea4b2a0e6382cbb7ed35f6481e` |
| `snap_counts_2022.parquet` | `3cfde83eb6d859e3477aba4238fa2fb8e0592a5fc5ab8b26128fce085d4b7fea` |
| `snap_counts_2023.parquet` | `97873cab365dfb39286bc1de3ac772fa4b51f09cce52ae5f8317e006cc007f62` |
| `snap_counts_2024.parquet` | `9ec66a0c755939b329d4eba3f90e716bb874b5a6544f325ba220f003991ff99f` |
| `roster_weekly_2022.parquet` | `063c0da93f612811e1c4a4c12727a56fd2716197864795f15aa2f10a591b00c0` |
| `roster_weekly_2023.parquet` | `0fa5abf9b462a087ecb17f3268ed7233ce9935e95d77be94ad6bac66adf8e281` |
| `roster_weekly_2024.parquet` | `4b144e8eda5a159f36037b02e8b7d5a7861acb65b0816b0a063244992038dcf8` |
| `build_tables.py` | `733845e294337f60c9ce0b34bdd68fc2f58b37db7e3c46a1e59b11607e0bcf31` |
| `participation_field.py` | `ce0d3733370a793922284c89cf1435322105446e5d88b174842bf56b85dffa0f` |
| `playcall_model.py` | `b472cb80eb4aa76f418a68cb3aaf5316ab99a2c694520fca8fdacc1f761acbec` |
| `e3_football_realism_joint_reference.py` | `935cbeb1ad4266d957fae1816a7bfbb85b29e76626d5c7751de46ed2e532eb98` |
| `football_realism_eval.py` | `6ec2f03871f3962de95240a5e3db39d58330d6a8f8174e323b33ee8437d124dd` |
| E3 `manifest.json` (bucket-definition reference only) | `a0869894b002728071d427be2f176c3588b5b16412ce06d762a10f91f5c70b31` |
| E3 `situational_action_distribution.csv` (bucket-definition reference only) | `f3968074f010256de0eb960df3701d56a829a912e591bc584512d89a12123011` |
| `football-realism-bumpers-v1-2026-10-30.json` (context reference only) | `4e27d54296ffdcbb1b42d2de0dd9c8ba57837aee04d4b5c2a3b3b36d46fbdfb0` |

The numeric thresholds are materialized by the two season-locked scripts below. No generated reference table or simulation output supplied a threshold. The E3 pooled files and the football-realism bumper file are definition/context references only, not threshold inputs.

## Reproduction artifacts

Each threshold script accepts an output path only. Input paths, seasons, and expected hashes are fixed. The scripts print every input hash, verify digests before loading data, and refuse rows outside the 2022-2024 season window. Run the original seven-metric materializer with:

```sh
python3 docs/research/slc-v2-realism-gate-2026-11-04/materialize_thresholds.py
```

Run the separate extension materializer with:

```sh
python3 docs/research/slc-v2-realism-gate-2026-11-04/materialize_extended_thresholds.py
```

| Artifact | SHA-256 |
|---|---|
| [`materialize_thresholds.py`](slc-v2-realism-gate-2026-11-04/materialize_thresholds.py) | `bfb5c1d9168f34f2f4d5f2ef51008afa1cd9792a67dd5b80076c0cb4f4619191` |
| [`observed_thresholds.json`](slc-v2-realism-gate-2026-11-04/observed_thresholds.json) | `df17d68e7f397cdd947764cd450707ca7cd2cbd74d2c78c5ca4e629b661ac02d` |
| [`materialize_extended_thresholds.py`](slc-v2-realism-gate-2026-11-04/materialize_extended_thresholds.py) | `f4a60f8eb315332c5b9be1137fccc69483cd3de5679e7e47745f81e6bb60c650` |
| [`extended_observed_thresholds.json`](slc-v2-realism-gate-2026-11-04/extended_observed_thresholds.json) | `857104b4ed3c2c674e8f6e04001cb0fb1fb546cd1f65b93f35c19809bc8d43d1` |

The original JSON records the unchanged thresholds for metrics 1-7. The separate extension command below produces every threshold and coverage envelope for metrics 8-11. Both outputs record sample counts and verified input hashes. The extension script verifies the original script hash before importing its metric-7 population logic. The hashes of the original script and JSON remain unchanged.

## Micah's resolutions (2026-11-04)

1. The pooled metric-2 gate is accepted. Team-by-situation tables remain low-support diagnostics only; this revision has no team-conditioned gate.
2. Ascending GSIS ID resolves RB2 snap ties on both observed and simulated sides.
3. No full clean-room redo is requested. The fixed-input script and fresh-process rerun are the agreed reproducibility check.

## Open question for Micah

Should metric 13 affect advancement? This revision treats it as a comparative report because no baseline-improvement acceptance rule was specified. Metrics 12-13 do not change the decision rule until Micah sets an explicit rule for metric 13.

## Drafting audit note

During this revision, a broad repository text search accidentally emitted mixed-season research output that may have included 2026 values. It was not used in any threshold calculation or copied into this document. Threshold computation reads only the explicit, hash-verified 2022-2024 inputs. Because of the accidental search output, strict workspace-level non-exposure to 2026 cannot be certified for this revision. No 2026 values are reproduced here. Micah directed no full clean-room redo; the exposure is also recorded in `/root/lp-slc-v1-5/docs/research/HOLDOUT-EXPOSURE-RECORD-2026.md`.
