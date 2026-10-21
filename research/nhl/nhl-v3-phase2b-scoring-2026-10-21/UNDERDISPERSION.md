# NHL V3 under-dispersion and structural diagnosis

Diagnostic only. This report selects no candidate, changes no gate, does not tune on 2022, and leaves frozen Phase 2A files unchanged. All metrics use the 2021 development population (1,312 games; 16 seeded simulations/game). Actual target-game locations and states are used only in retrospective diagnostics; no target-game starting-goalie identity enters the forecasts.

## Count spread and calibration

The original Phase 2B diagnostic compared pooled observed variance with mean within-game simulation variance. That omits the variation in forecast means across games. The decomposition below separates team means, within-team forecast-mean variation, and within-game predictive variance. The within-team gap therefore compares observed game variation around team rates with forecast-mean movement plus stochastic simulation spread.

| Count | Observed mean / SD | Forecast mean / marginal SD | Between-team variance (obs / forecast means; gap, 95% clustered CI) | Within-team game variance (obs / forecast means + simulation; residual gap, 95% clustered CI) |
|---|---:|---:|---:|---:|
| Attempts | 56.656 / 10.942 | 56.470 / 8.665 | 18.844 / 1.966; +16.877 [+14.395, +21.636] | 100.883 / 73.122; +27.761 [+20.781, +32.652] |
| Official SOG | 31.602 / 6.913 | 31.095 / 5.885 | 7.157 / 0.694; +6.463 [+5.548, +8.336] | 40.635 / 33.937; +6.698 [+3.869, +8.424] |
| Goals | 3.106 / 1.776 | 3.434 / 1.821 | 0.179 / 0.012; +0.167 [+0.142, +0.261] | 2.975 / 3.304; -0.329 [-0.511, -0.195] |

The forecast marginal SD includes game-to-game changes in expected counts as well as each game's simulated spread. The two variance columns show that V3 captures little observed team-to-team rate variation for attempts (forecast 1.97 vs observed 18.84) or SOG (0.69 vs 7.16), and it also misses within-team game spread. The within-team residual gap removes forecast-mean movement and compares observed variation with simulation variance. SOG covers 1,292 games (official SOG disposition ACCEPT); attempts and goals cover all 1,312.

| Count | Effective within-team NB2 alpha (95% clustered CI) | Generator-implied NB2 alpha | Extra alpha beyond generator (95% clustered CI) | 50/80/90% coverage |
|---|---:|---:|---:|---:|
| Attempts | +0.01071 [+0.00851, +0.01222] | +0.00204 | +0.00867 [+0.00650, +0.01020] | 42.6%/62.8%/75.0% |
| Official SOG | +0.00565 [+0.00286, +0.00747] | -0.00124 | +0.00689 [+0.00398, +0.00868] | 47.0%/68.4%/79.0% |
| Goals | -0.05768 [-0.07289, -0.04699] | -0.03039 | -0.02729 [-0.04232, -0.01625] | 62.3%/81.2%/90.5% |

The NB2 column uses a team fixed-effect variance decomposition. For NB2 Var=mu+alpha*mu^2, effective alpha subtracts forecast-mean movement and the Poisson mean from observed within-team variance; extra alpha over the generator instead subtracts the simulator's conditional variance. Alpha is signed for diagnosis, not constrained into a fitted replacement model. A single observed count per team-game cannot distinguish latent tempo variation from omitted predictors or misspecified means; cluster intervals account for paired teams within a game. The separate uncentered residual moment is retained in JSON as a sensitivity check and is confounded by mean misspecification.

## Where the scoring difference enters

Accepted PBP conversion was 9.8188% goals per on-target event. V3 generated 11.0454%; evaluated at the actual accepted shot locations and states, its conditional conversion was 9.2680%, versus observed 9.8188%. This points away from a simple globally too-high per-shot probability: the generator's mixture of shot opportunities, strengths, and states changes the aggregate conversion. The observed-location estimate is slightly low, while the generated mixture is high.

| Stage | Observed / generated | 95% game-cluster interval |
|---|---:|---:|
| SOG per attempt | 55.8329% / 55.0574% | observed [55.5474%, 56.1197%]; generated [54.9916%, 55.1173%] |
| Goals per on-target event | 9.8188% / 11.0454% | observed [9.6158%, 10.0120%]; generated [10.9914%, 11.0984%] |

The attempt-to-SOG step is lower in the generated mixture (55.0574% vs 55.8329%); the larger scoring divergence is goals per generated SOG. The generated joint distance-angle-shot-type distribution has total-variation distance 0.0469 from observed accepted events. The mismatch between 9.268% expected goal probability at observed locations and 11.045% in the generated mixture shows that the sampled opportunity/state mixture compounds across a game.

| Strength | Attempts observed / generated per game | Goals observed / generated per game | Goal error, generated - observed |
|---|---:|---:|---:|
| EVEN | 92.385 / 97.715 | 4.388 / 5.565 | +1.177 |
| ADVANTAGE | 17.787 / 12.979 | 1.312 / 1.146 | -0.167 |
| DISADVANTAGE | 2.445 / 2.245 | 0.149 / 0.157 | +0.009 |
| EMPTY_NET | 0.695 / 0.000 | 0.363 / 0.000 | -0.363 |

Even-strength goals are the largest component error (+1.177/game). The missing empty-net category (-0.363) and advantage-goal shortfall (-0.167) offset part of it; disadvantage goals are close. Penalty under-generation shifts some attempts away from advantage and toward EVEN, but these component differences do not identify a causal allocation.

| Game-state count | Observed / generated | Difference (observed - generated; 95% clustered CI) |
|---|---:|---:|
| Accepted penalties per game | 7.4 / 4.9 | +2.5 [+2.3, +2.7] |
| Games reaching OT | 288.0 / 212.1 | +75.9 [+48.4, +106.0] |
| Games reaching shootout | 102.0 / 77.8 | +24.2 [+5.6, +43.4] |

Conditional on OT, generated goals were 0.633 per game reaching OT, close to 0.646 observed. Shootouts followed 36.7% of generated OT games and 35.4% of observed OT games. The lower totals therefore mostly track fewer OT entries, not missing OT or shootout branches.

| Team-pair count | Observed home-away covariance / correlation | Generated-mixture covariance / correlation |
|---|---:|---:|
| Attempts | -44.710 / -0.382 (covariance CI [-51.677, -37.505]) | -8.820 / -0.119 (covariance CI [-9.916, -7.722]) |
| Official SOG | -11.460 / -0.242 (covariance CI [-14.045, -8.759]) | -0.655 / -0.019 (covariance CI [-1.151, -0.178]) |
| Goals | -0.357 / -0.114 (covariance CI [-0.508, -0.198]) | +0.052 / +0.016 (covariance CI [+0.007, +0.095]) |

Observed opponent shot counts are much more negatively associated than the generator's paired draws. A single shared positive game-tempo multiplier could therefore move dependence in the wrong direction; Phase 2C should separate total-game pace from within-game team shot share.

## Penalty association and possible spread contribution

The projection below uses accepted penalty events per game and team fixed effects. It is associational: game pace, score state, and penalties affect one another, so it is not a causal effect. The variance increment is the linear projection of the difference in observed versus generated within-team penalty spread onto counts.

| Count | Slope per additional penalty (95% CI) | Partial R² | Projected count change from +2.500 penalties/game | Variance increment (95% CI) | Fraction of within-team spread gap |
|---|---:|---:|---:|---:|---:|
| Attempts | -0.0043 [-0.1130, +0.1045] | 0.0000 | -0.011 | 0.000 [0.000, 0.114] | 0.0% |
| Official SOG | +0.0387 [-0.0326, +0.1064] | 0.0004 | +0.097 | 0.011 [0.000, 0.089] | 0.2% |

These estimates quantify association and cannot establish how many missing attempts or SOG are caused by the penalty process. Their intervals and raw inputs are in `underdispersion.json`.

On this projection, the 2.5/game penalty-rate gap accounts for effectively 0.000 attempt variance units and 0.011 SOG variance units (0.2% of the SOG within-team gap); the slopes' intervals include zero. It does not explain the shot-volume under-dispersion, though it remains relevant to strength allocation and scoring.

## Scoring and final margin

Goal central coverage is 0.623/0.812/0.905: the 50% interval is a little wide, while 80% and 90% are close to nominal. Forecast within-team goal variation (3.304) exceeds observed (2.975), so goals do not need extra spread in this fold; the forecast mean remains high by 0.328 goals/team-game. This coverage does not establish shot-process calibration. Final-score margin observed mean/variance is 0.247/7.069; generated mean/full marginal variance are 0.163/6.573, with within-game variance 6.070. Clustered intervals are in `underdispersion.json`.

## Structural omission inventory

The rank is by relevance to the +1.177/game generated EVEN-goal excess. Direct component gaps are not causal decompositions; positive and negative errors offset.

| Rank | Component and measured gap | Classification and frozen-code location | Relation to EVEN-goal excess |
|---:|---|---|---|
| 1 | EVEN goals: generated 5.565 vs observed 4.389/game (+1.177) | Scoring mixture error, not a category absence. | Largest measured scoring error. The per-shot model at observed locations is low, so altered simulated composition/state and its compounding matter. |
| 2 | Empty-net goals: generated 0.000 vs observed 0.363/game; empty-net attempts 0 vs 0.695/game | Hard structural absence: generator `_GameBuilder._strength` in `stochastic_model.py:411-414` only returns EVEN or advantage/disadvantage; no goalie-pull state. Replay classification can identify EMPTY_NET at `stochastic_model.py:146-155`. | Missing goals offset the EVEN overprediction in total goals; they do not explain it. |
| 3 | Accepted penalties: generated 4.890 vs observed 7.390/game (−2.500) | Fitted-rate shortfall plus structural restriction: `simulate_game` at `stochastic_model.py:491-545` permits one minor at a time, suppresses calls in the final 120 seconds of a period, and ends penalties with the simplified even-strength reset. | Observed advantage attempts/goals exceed generated; the missing special-teams share is consistent with excess EVEN exposure. Projection above is noncausal. |
| 4 | OT goals: generated 0.102 vs observed 0.142/game (−0.040); OT game frequency 212.1 vs 288 expected/games | No hard absence: `simulate_game` at `stochastic_model.py:551-580` has 5-minute sudden-death OT. Frequency is short, largely downstream of the simulated regulation score/tie rate; per-OT goal rates are similar. | OT goals are classified EVEN and their shortfall slightly offsets EVEN excess. |
| 5 | Shootout games: 77.8 expected vs 102 observed | No hard absence: `_simulate_shootout` at `stochastic_model.py:626-678` generates shootouts after a tied OT. Conditional on generated/observed OT, the shootout rates are similar; lower count follows fewer OT entries. | Affects final winner/final-score convention, not reg+OT goal CRPS. |
| 6 | Evaluation window: both observed and forecast populations are the same 1,312 2021 development games; 2022 is not used here | No evaluation-window mismatch. | Cannot explain the measured error. |

The generator has exponential event times (`stochastic_model.py:488`, and `:566` in OT) with deterministic fitted rates and no shared game-level latent tempo. Team-to-team rate dispersion is also underpredicted, so a game-level random effect alone would not address all the missing spread. Penalties explain the special-teams exposure shift, but the fixed-effect projection accounts for almost none of total attempt/SOG variance shortfall.

## Stored-prediction variance-only sensitivity (descriptive-after-selection)

| Stored 2021 metric | Phase 2A | C v2 goal prior | C paired delta, baseline minus candidate (95% CI) |
|---|---:|---:|---:|
| Goal CRPS | 1.0544 | 1.0016 | +0.0529 [+0.0357, +0.0697] |
| Final-score energy | 1.6743 | 1.5944 | +0.0799 [+0.0530, +0.1056] |
| Winner Brier | 0.2541 | 0.2375 | +0.0167 [+0.0076, +0.0259] |
| Team SOG CRPS | 3.9126 | 3.9513 | -0.0387 [-0.0618, -0.0163] |

A common NB2 alpha was estimated by moments while holding each stored per-team-game forecast mean fixed; it landed at 0.0000 (the Poisson boundary). Replacing the empirical 16-draw goal distributions with that Poisson/NB2 distribution keeps forecast means unchanged and expands the generator's below-Poisson conditional spread, but does not improve the pooled goal-variance diagnosis: the full generated marginal goal variance is already 3.315 against 3.154 observed, and 50% intervals cover 62.3%. This is descriptive-after-selection, not a candidate or adoption result. Raw C goal-CRPS gain was 0.0529 (original Phase 2B paired 95% CI +0.0357 to +0.0697); Poisson recalibration yielded 0.0461 (fixed-alpha clustered interval 0.0303 to 0.0622), a change of -0.0068. The bootstrap holds alpha fixed, and all these scores reuse the 2021 selection population; neither supports adoption.

## Reproduction and runtime

The seeded simulator was not rerun. The exact Phase 2A and C cache traces were reused after checking cache fingerprint, candidate name, 1,312 games, 16 simulations/game, and zero accounting failures. The 1,510,104-row pinned event ledger was rescanned and reconciled to Phase 2B per-game goals; the compact trace snapshot is committed so the calculations and bootstrap can be rerun without the transient cache.

```sh
/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/underdispersion.py --build-snapshot --rescan-source --cache-dir /tmp/nhl-v3-phase2b-cache-7d5a1e6d4487a74a
/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/underdispersion.py --analyze --bootstrap-replicates 2000
```

The fresh pinned event-ledger scan took 87.35 seconds; full snapshot-build command took 89.59 seconds; analysis/bootstrap took 40.65 seconds. Bootstrap: 2000 game-cluster resamples, seed 20261022.
