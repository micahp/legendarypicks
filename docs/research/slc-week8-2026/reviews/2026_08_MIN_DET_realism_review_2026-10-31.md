# MIN–DET 10K realism review

**Review date:** 2026-10-31

**Run:** `research-8b7d5a2e-2026-10-31` · `2026_08_MIN_DET` · source commit `8b7d5a2ec818d4e53751f5c4baf5a2956b317a7f`
**Disposition:** Preserve the completed batch. No rerun or model-parameter change was made.

## Run integrity and comparison scope

The final audit records 10,000 successes, 0 blocked games, 0 errors, 0 incomplete outcomes, 10,000 boxscores, and 7 final overtime ties. All 10,000 seeds were accounted for. The launch-time header still says `running`; the separate final audit is the authoritative completion record.

The historical team and game-state reference is pinned to 1,087 regular-season games and 2,174 team-games from 2022–2025, weeks 1–18. The player workload reference uses 2022–2024 as training, 2025 as holdout, and an explicitly lower-bound, event-observed 2026 Weeks 1–7 target sample. These windows end before the Week 8 target. The current Dirichlet share implementation itself trains on the preceding season only: 2025 for a 2026 simulation.

Team-specific historical distribution rows use 68 regular-season team-games per team over 2022–2025; simulation rows use all 10,000 games. Percentiles are empirical quantiles. The reference comparison is diagnostic evidence, not a claim that a single matchup should reproduce its historical mean exactly.

## Findings

### 1. Punt output: exporter defect plus a real decision-rate deficit

The published `0.013` punts/game for both teams was a boxscore accounting defect. Regular punts in the play record have `punt=true` and `punt_attempt=false`. `game_stats.py` used `out.get('punt_attempt', out['punt'])`, which returns the explicit false flag and misses ordinary punts. The drive ledger independently records 26,622 Detroit and 27,818 Minnesota punt-terminal drives.

Counting either flag once gives 2.675 punts/game for Detroit and 2.795 for Minnesota, including blocked punts. This fixes the exported statistic; it does not fix the football distribution:

| Team | 2022–25 punts/game | Simulated punts/game | Difference | 2022–25 drives/game | Simulated drives/game |
|---|---:|---:|---:|---:|---:|
| DET | 3.088 | 2.675 | −13.4% | 10.794 | 9.796 |
| MIN | 3.765 | 2.795 | −25.8% | 11.132 | 9.694 |
| League reference | 3.883 | 2.735 combined-team average | −29.6% | 10.855 | 9.745 combined-team average |

Full team-game distributions (historical `n=68` per team, simulated `n=10,000`):

| Team / metric | Historical mean ± SD | Historical zero / median / P95 / P99 / max | Simulation mean ± SD | Simulation zero / median / P95 / P99 / max |
|---|---:|---|---:|---|
| DET drives | 10.794 ± 1.367 | 0% / 11 / 13 / 14 / 14 | 9.796 ± 1.359 | 0% / 10 / 12 / 13 / 16 |
| MIN drives | 11.132 ± 1.765 | 0% / 11 / 13 / 16.32 / 19 | 9.694 ± 1.365 | 0% / 10 / 12 / 13 / 18 |
| DET punts | 3.088 ± 1.483 | 7.4% / 3 / 5 / 5.33 / 6 | 2.675 ± 1.455 | 4.88% / 3 / 5 / 6 / 9 |
| MIN punts | 3.765 ± 1.887 | 0% / 3.5 / 7 / 9.33 / 10 | 2.795 ± 1.491 | 4.43% / 3 / 5 / 7 / 9 |
| DET field-goal attempts | 1.676 ± 1.254 | 19.1% / 2 / 4 / 5 / 5 | 2.111 ± 1.248 | 8.57% / 2 / 4 / 5 / 8 |
| MIN field-goal attempts | 2.059 ± 1.149 | 7.4% / 2 / 4 / 5 / 5 | 1.846 ± 1.195 | 12.29% / 2 / 4 / 5 / 7 |
| DET turnovers on downs | 0.809 ± 1.102 | 51.5% / 0 / 2.65 / 5 / 5 | 0.909 ± 0.896 | 38.0% / 1 / 3 / 3 / 5 |
| MIN turnovers on downs | 0.485 ± 0.757 | 63.2% / 0 / 2 / 3 / 3 | 0.815 ± 0.865 | 42.69% / 1 / 2 / 3 / 5 |

The fourth-down decision ledger confirms different shifts by team. `Go` means a run or pass on fourth down; historical counts are 454 Detroit and 468 Minnesota fourth-down decisions, versus 67,197 and 62,881 simulated decisions.

| Team | Action | Historical rate | Simulated rate |
|---|---|---:|---:|
| DET | Punt | 46.26% | 39.63% |
| DET | Field goal | 22.69% | 28.59% |
| DET | Go | 31.06% | 31.78% |
| MIN | Punt | 54.49% | 44.29% |
| MIN | Field goal | 27.56% | 27.02% |
| MIN | Go | 17.95% | 28.70% |

Detroit’s fourth-down punt deficit is mostly replaced by field-goal attempts; Minnesota’s is mostly replaced by going for it. Minnesota’s elevated turnovers on downs are consistent with that shift. The number of fourth-down decisions is not unusually high relative to team history: 6.72 per game for Detroit and 6.29 for Minnesota, versus 6.68 and 6.88 historical.

The decision rates remain shifted after conditioning on distance. Minnesota’s go-for-it share was 56.9% versus 45.5% historically at 1–2 yards, 38.6% versus 23.9% at 3–4 yards, and 10.9% versus 4.1% at 7–9 yards. The respective historical/simulated sample counts were 99/15,494, 67/12,431, and 97/12,865. Detroit’s distance-conditioned results are mixed: it goes less often at 1–4 yards, roughly matches at 7–14 yards, and goes more often at 5–6 and 15+ yards.

Clock buckets show the same Minnesota tendency in ordinary regulation periods: go-for-it rates were 28.1% vs 12.1% in Q1 (historical/simulated counts 91/15,031), 29.2% vs 18.1% in Q2 (94/14,119), 28.6% vs 13.6% in Q3 (103/15,061), and 29.1% vs 16.2% in the ordinary Q4 bucket (68/11,005). These are marginal state-conditioned rates; the historical samples are small and the table does not fully standardize every joint state.

**Mechanism:** `slc_playcall.py::sample()` selects kick intent from the observed physical situation cell and gates field goals by feasibility. Its score-clock logistic is applied only after the kick-vs-nonkick decision, where it changes run/pass selection. Therefore it cannot correct the kick/go choice for score and clock. Do not impose a target punt rate. The research fix should model punt, field goal, run, and pass as separate, state-conditioned fourth-down actions, while preserving field-goal feasibility and the existing legal-state transitions.

### 2. Team volume and Gibbs’ workload are separate problems

Historical team-volume comparison (historical `n=68`; simulated `n=10,000`):

| Team / metric | Historical mean ± SD | Historical zero / median / P95 / P99 / max | Simulation mean ± SD | Simulation zero / median / P95 / P99 / max |
|---|---:|---|---:|---|
| DET scrimmage plays | 64.868 ± 7.336 | 0% / 64.5 / 77 / 84 / 84 | 68.994 ± 8.094 | 0% / 69 / 82 / 88 / 97 |
| DET rush attempts | 28.765 ± 6.741 | 0% / 30 / 43 / 43 / 43 | 36.830 ± 9.344 | 0% / 37 / 52 / 58 / 68 |
| DET pass attempts | 34.221 ± 8.054 | 0% / 34 / 53 / 59 / 59 | 31.707 ± 7.420 | 0% / 31 / 45 / 52 / 67 |
| MIN scrimmage plays | 61.824 ± 9.378 | 0% / 62 / 78 / 86 / 86 | 61.144 ± 8.551 | 0% / 61 / 75 / 81 / 91 |
| MIN rush attempts | 24.471 ± 6.873 | 0% / 24 / 34 / 43 / 43 | 23.166 ± 7.857 | 0% / 22 / 37 / 43 / 54 |
| MIN pass attempts | 34.338 ± 8.448 | 0% / 34.5 / 48 / 55 / 55 | 37.116 ± 6.849 | 0% / 37 / 49 / 55 / 69 |

Detroit has 28.0% more rush attempts than its 2022–2025 mean, alongside 6.4% more scrimmage plays and 7.3% fewer pass attempts. Minnesota’s mean plays and rushes are near its historical values, while passing is 8.1% higher. Thus Detroit’s excess team rushing volume is real and cannot be explained by player allocation alone.

For Jahmyr Gibbs, the archived player distribution is much further from the cutoff-safe workload references:

| Metric / window | Games | Mean ± SD | Zero / median / P95 / P99 / max |
|---|---:|---:|---|
| Actual carries, 2022–25 eligible games | 49 | 13.78 ± 4.58 | 0% / 13 / 22.6 / 24.56 / 26 |
| Actual carries, 2025 holdout | 17 | 14.29 ± 3.98 | 0% / 15 / 20.4 / 21.68 / 22 |
| Simulated carries | 10,000 | 31.99 ± 9.28 | 0% / 32 / 47 / 53 / 63 |
| Actual rushing yards, 2022–25 eligible games | 49 | 73.06 ± 40.39 | 0% / 68 / 140.8 / 186.84 / 219 |
| Actual rushing yards, 2025 holdout | 17 | 71.94 ± 51.96 | 0% / 65 / 157.4 / 206.68 / 219 |
| Simulated rushing yards | 10,000 | 133.06 ± 53.54 | 0% / 129 / 227 / 275 / 366 |

The simulated mean of 31.99 carries is 2.24× the 2025 holdout mean. Its 63-carry maximum exceeds the NFL observed single-game record of 45; this is a `RECORD_EXCEEDANCE` tail alert, not a claim that an individual outcome is physically impossible. The simulated maximum of 366 rushing yards also exceeds the observed 296-yard record. The average yards-per-carry ratio of means is 4.16 (133.06 / 31.99), below Gibbs’ 2022–25 ratio of 5.30 (73.06 / 13.78), so the inflated yardage is driven by opportunity volume rather than unusually high average efficiency.

The cause separates into team volume and player allocation:

| Counterfactual | Team carries/game | Gibbs share | Gibbs carries/game |
|---|---:|---:|---:|
| Current simulation | 36.83 | 86.8% | 31.99 |
| Replace team volume only with DET 2022–25 mean | 28.77 | 86.8% | 24.98 |
| Replace Gibbs share only with 2023–25 observed share (675 / 1,476) | 36.83 | 45.7% | 16.84 |
| Replace both with historical references | 28.77 | 45.7% | 13.16 |
| Actual Gibbs eligible-game mean, 2022–25 | — | — | 13.78 |

These one-factor counterfactuals hold all other factors fixed; their effects are not additive because volume and share interact.

The frozen 2026 Detroit roster has four eligible running backs: Gibbs, Sione Vaki, Jacob Saylors, and Isiah Pacheco. Under the share model’s 2025 Detroit PBP input, the 432 run plays with identified rushers include 243 Gibbs carries, 1 Vaki carry, 2 Saylors carries, and 0 Pacheco carries. The share layer’s 0.01 floor gives Vaki, Saylors, and Pacheco equal small weights. Conditional normalization over those four current RBs therefore makes Gibbs’ expected pre-Dirichlet RB share `0.5625 / (0.5625 + 0.01 + 0.01 + 0.01) = 94.9%`. The season prior contains meaningful history for Gibbs but little or none for the other current Detroit RBs; historical teammates who are no longer on the frozen roster are excluded from the candidate pool.

The simulation’s realized Gibbs share averages 86.8% of Detroit carries (SD 11.7%; median 90%; P95 98%; P99 100%). His carry share is also nearly flat by quarter: Q1 87.0%, Q2 86.5%, Q3 87.1%, Q4 86.7%. This points to the fixed game-level share draw and current-roster renormalization as the allocation mechanism; the high share is not confined to late-game lead protection. The share vector is sampled once per team and role per game and reused for each play. Team score and clock can affect how many runs occur, but do not reallocate the game’s RB share among eligible players.

**Recommended correction:** fit the participant distribution to the active depth chart and role, with uncertainty/shrinkage for limited player-team history and workload-dependent substitution. Do not cap Gibbs at his mean, P95, or a fixed number of carries. Keep the team run-rate correction separate and evaluate both with paired-seed ablations.

### 3. Overtime is score-sampled without a play sequence

This is not merely an exporter dropping modeled OT snaps. `game_state.py::_observed_overtime_drive()` samples a historical regular-season overtime drive outcome, applies its points and duration, and appends a drive with `plays: []`. The sample includes a terminal outcome, points, and next-possession information, but no play-by-play sequence.

In the immutable batch, 472 games reached this observed-drive OT path, producing 1,387 synthetic overtime drive records. Every such record has zero play records. The batch scored 1,466 Detroit and 1,439 Minnesota OT points; the report consequently shows nonzero OT points but zero OT plays and yards. Those zeros mean **unmodeled**, not observed zero activity. Regulation and OT scores reconcile for all 10,000 games, but OT play, yardage, and player-stat completeness does not.

The exporter now separates `scoring_complete` from `play_stats_complete_by_period`, marks an observed score-only OT period incomplete with reason `observed_overtime_drive_has_no_play_sequence`, and sets the quarterly `complete` flag false for that boxscore. Legacy report inputs are also recognized from an OT drive summary with `play_count=0`. Incomplete-period player lines and play totals are excluded from distribution denominators; period points remain available. The quarter-boxscore schema is versioned as `lp-nfl-slc-quarter-boxscore-2` for this distinction.

For this run, the resulting OT play-stat coverage is 9,528 / 10,000 games (games with no OT remain valid zero-OT observations); OT scoring coverage remains 10,000 / 10,000. A future model can either emit a play sequence for each sampled OT drive or continue to disclose that OT play stats are unavailable.

### 4. Quarter drive totals mix event counts with scrimmage snaps

The old report showed quarter drive-summary means of 73.750 Detroit and 65.758 Minnesota recorded events, compared with final team scrimmage-play means of 68.994 and 61.144. The approximately 4.76 and 4.61 event differences are punts and field-goal attempts included in drive event counts; the `game_stats` team `plays` metric counts scrimmage snaps only.

There was also a separate exporter defect: `_quarter_by_quarter()` added `calculated_side['plays']` directly and then added it a second time through `TEAM_FIELDS`, which already maps `plays`. The old quarterly team-play sums were therefore 137.989 for Detroit and 122.288 for Minnesota—almost exactly twice their final team plays. Cross-quarter drives themselves were not duplicated: each event is grouped once by its `state_before` period.

The duplicate addition is removed. The report labels quarter drive counts **“Drive events (including kicks)”**, while team `plays` remains scrimmage snaps. The quarter output now includes machine-readable count semantics for both fields. A Q1-run/Q2-punt regression proves that the drive has one event in each quarter, the team has one scrimmage snap total, and the punt is counted once in Q2.

## Changes and verification

Research-branch code changes are limited to output/accounting and report semantics; SLC action probabilities and model defaults are unchanged:

- `game_stats.py`: count regular and blocked punts once when either `punt` or `punt_attempt` is true.
- `slc_outputs.py`: remove duplicated quarterly scrimmage plays; expose per-period play-stat completeness and drive-count semantics.
- `render_slc_run_report.py`: preserve the new metadata, infer score-only OT in legacy records, omit incomplete OT play stats, and label drive events clearly.
- Tests cover regular punts, cross-period drive event counting, score-only OT completeness, legacy OT inference, and report labels.

Verification performed:

```text
python3 -m py_compile scripts/nfl_sequence/game_stats.py scripts/nfl_sequence/slc_outputs.py scripts/nfl_sequence/render_slc_run_report.py scripts/nfl_sequence/test_slc_outputs.py scripts/nfl_sequence/test_render_slc_run_report.py
python3 -m unittest scripts.nfl_sequence.test_slc_outputs scripts.nfl_sequence.test_render_slc_run_report -v
Ran 20 tests — OK
```

The existing IND–JAX worker archive is included in the report-renderer tests as a pre-existing artifact. The MIN–DET 10K files were read only and were not regenerated or edited. The independent Week 8 smoke process was not interacted with.

## Priority for follow-up

1. **Fourth-down action model:** separate punt, field goal, run, and pass, conditioning the choice on field position, distance, score, and clock. Validate on the pinned historical holdout; do not force a marginal punt target.
2. **RB opportunity allocation:** replace current-roster renormalization that assigns Gibbs 94.9% expected RB share with a workload-aware role/depth-chart distribution and explicit substitution behavior.
3. **Team run volume:** investigate Detroit’s elevated run rate and play volume separately from Gibbs’ share, with score-clock state conditioning.
4. **Overtime completeness:** retain honest scoring-only labels until the simulator emits legal OT play sequences.

## Provenance hashes

The worker seed and boxscore files are enumerated in `outputs/input-sha256.json`; its hash is `f8875e5e61bf8d07bd54cfa72ab28e1003fa60f42ee3cd9e5e94a6cb08028f54`. The frozen snapshot hash is `476715b5a0f94cac919638b9666b571945cb847b3a6f4e6977b79ae0a36531b1`; simulation input database hash is `feb5179f1c6c2f8cd2265a25ff68f3552d6e68bbba00354e0688f22505aa028f`.

| Artifact | SHA-256 |
|---|---|
| MIN–DET `summary.json` | `558afbb75f7e546a60b2a3eea058d34b5c2ebe4c536f8a3e0af9a964b2b88c82` |
| MIN–DET `outputs/final-audit.json` | `8e98d1f1edd7643991527f93f34e69b8c89315691fff78f47f800fd8b8c7b907` |
| E3 reference `manifest.json` | `a0869894b002728071d427be2f176c3588b5b16412ce06d762a10f91f5c70b31` |
| E3 `situational_action_distribution.csv` | `f3968074f010256de0eb960df3701d56a829a912e591bc584512d89a12123011` |
| Player workload `manifest.json` | `312591afedbeba27443c0246c7ce8ea5aecb15f2eeb3703b65af817c769e6aea` |
| Player workload `team_game_usage.csv` | `23ff9beaf39590d3a57f2d62bf473c4443d8b55ab08424ec6bf3543ce85281f0` |
| Player workload `player_workload_distributions.csv` | `115af3a2e48ecfe3a8386c6d3c42073730a2f54665dd363488514630f9ecc8de` |
