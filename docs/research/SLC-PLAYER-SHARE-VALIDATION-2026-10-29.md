# SLC player-share validation, 2026-10-29

Status: research only. The validation fits on 2024 regular-season player counts and scores the next season, 2025. No 2026 game outcome was used. The results do not establish player projections or team-score calibration.

## Method

The Dirichlet-multinomial MLE v2 model in scripts/nfl_sequence/share_distributions.py fits each team's player opportunity shares from 2024 and estimates one concentration parameter per role by maximum likelihood using the full game-level likelihood and each game's opportunity total. A beta-binomial marginal benchmark is also fit for each role. For each 2025 team-game, the fixed-share model uses the same 2024 shares; the Dirichlet-multinomial allows shares to vary between games around that mean.

The held-out score includes only players with 2024 history on the same team. Shares are renormalized across those players. Counts and summaries are keyed by team and player, so a transfer remains a separate player-team unit. Team-games with zero total opportunities for that returning-player group are skipped. The result therefore describes returning players, not the full 2025 rosters.

## Cohort and log score

Each role's fit used 544 team-game rows across 32 teams and 272 distinct NFL games. The held-out score includes 543 receiver team-games across 272 games and 526 carry team-games across 271 games. It covers 506 receiver player-team units (494 unique player IDs) and 332 carry player-team units (329 unique player IDs). The held-out score is restricted to players with fit-season history on the same team.

The game-cluster sample size is 272 for fitting and 272/271 for held-out target/carry scoring; the two team rows from one game are not treated as independent resampling units. Concentration profile intervals still use the fitted team-game likelihood without a cluster adjustment.

| role | Dirichlet concentration (profile 95% interval) | beta-binomial concentration | fixed-share log score / team-game | Dirichlet-multinomial log score / team-game | improvement (game-cluster 95% interval) |
|---|---:|---:|---:|---:|---:|
| targets | 24.406 [22.777, 26.152] | 24.831 | -21.4356 | -17.1322 | +4.3034 [3.9611, 4.6353] |
| carries | 7.542 [6.918, 8.082] | 7.413 | -13.9681 | -8.4250 | +5.5431 [4.9105, 6.1984] |

Higher log scores are better. The score intervals are percentile bootstrap intervals from 2,000 resamples of NFL game IDs, keeping both teams in each sampled game together. The concentration intervals are profile-likelihood intervals on the team-game fit and do not adjust for paired-team dependence.

## Opportunity dispersion

| role | observed mean count | fixed / Dirichlet mean count | observed mean variance per player-team unit | fixed / Dirichlet predicted variance | observed zero rate | fixed / Dirichlet predicted zero rate |
|---|---:|---:|---:|---:|---:|---:|
| targets | 1.3276 | 1.3276 / 1.3276 | 2.7085 | 1.4987 / 2.5458 | 0.6837 | 0.4948 / 0.5562 |
| carries | 1.7402 | 1.7402 / 1.7402 | 4.7983 | 2.5111 / 5.2936 | 0.7614 | 0.5864 / 0.6730 |

Variance is calculated over player-team units with repeated held-out games, and includes both the conditional count variance and the between-game variation in expected counts as opportunity totals change. The model's variance is closer for both roles: slightly below observed for targets and slightly above for carries. Predicted zero rates remain below observed. The held-out mean count quantiles are averages of the discrete 10th, 50th and 90th quantiles for each player-team unit:

| role | quantile | observed | fixed share | Dirichlet-multinomial |
|---|---:|---:|---:|---:|
| targets | 10th | 0.2530 | 0.2885 | 0.1719 |
| targets | 50th | 1.1245 | 1.1225 | 0.9783 |
| targets | 90th | 2.7925 | 2.6344 | 2.9308 |
| carries | 10th | 0.5964 | 0.6114 | 0.3825 |
| carries | 50th | 1.4669 | 1.5090 | 1.2741 |
| carries | 90th | 3.2831 | 3.0512 | 3.4729 |

The DM model improves the joint held-out log score and variance, and moves zero rates closer, but it does not improve every marginal quantile: its lower and median quantiles are too low, while the 90th is closer. These results do not establish that the simulated count distributions are fully calibrated.

## Full-game score check

I reran the player-share control on the same current source state as the saved Dirichlet arm. Both runs used the frozen 2026 Week 8 CAR-GB snapshot, the same play-call artifact and reference frame, and seeds 1 to 100. Each completed 99 full games; seed 32 was blocked in both. Every paired valid seed had exactly the same final score, home margin, and total points. Mean total points were 39.99 and mean home margin was -0.43 in both arms.

This confirms that per-game share variation changes who receives credit without changing team scores on this snapshot. The layer is off by default. The output hashes and exact input fingerprints are in docs/research/SLC-RESULTS-PIN-2026-10-29.json.

In the per-seed ledgers, target counts differed by player on all 99 paired games (total player-count L1 difference 6,386), and carry counts differed on all 99 (L1 4,850). Team points and home margin were still identical on every pair. This validates that the flag changes pre-event opportunity allocation, not only post-game attribution.

## Integration gates

| gate | status | evidence / remaining limit |
|---|---|---|
| Chooser, reference loader, single-game runner and batch runner | pass | `--playcall-dirichlet-shares` is explicit, off by default, and implies the fixed player-share adapter; one-game smoke runs completed through both runners. |
| One reusable share draw per team, role, game and seed | pass | The chooser samples over the full eligible group and reuses the vector across play-specific candidate groups. Receiver and carry regression tests cover draw reuse. |
| Team/player transfers and opportunity/outcome boundary | pass | Counts remain keyed by team and player; participant assignment happens before outcome sampling, so targets/carries select a player while catches and yards remain downstream outcomes. |
| Frozen roster eligibility and assignment before outcome | pass for tested paths | Out and Doubtful players are excluded, shares renormalize, and missing-history, one-player and empty-eligible groups are covered. The held-out historical score itself remains limited to returning same-team players. |
| Runtime model and cutoff manifests | pass | Runner output records `dirichlet-multinomial-mle-v2`, source season, forecast cutoff, source commit and file hashes. The smoke run used source season 2025 for cutoff 2026. |
| Held-out calibration | partial | Joint target and carry log scores improve; variance and zero rates move closer to observed values. Lower and median quantiles remain too low, and full frozen-roster coverage is unscored. |
| Matched OFF versus ON | pass for one snapshot | Player target and carry counts change on all 99 shared valid seeds while team scores remain identical. This is one matchup, not broad outcome calibration. |
| Team opportunity volume | open | Simulated scrimmage plays remain about 9 to 11 percent high relative to 2025, independent of player-share allocation. |
| Player-conditioned outcomes | open | Selected players do not yet condition completion, interception, sack, yards or touchdown outcomes. |

The focused integration suite passed 80 tests with the backend virtualenv:
`python3 -m unittest test_share_distributions test_run_slc_game_flags test_share_manifest test_share_validation test_scoring_cohort test_pre_event test_slc_playcall test_slc_engine`.
The implementation remains research-only with the flag off by default; these results do not clear every acceptance gate.

## Limits

The held-out comparison is conditioned on returning players with same-team history; newly eligible players and full frozen-roster coverage are not scored here. The full-game score comparison is one matchup and 99 valid seeds. Marginal count quantiles are not all calibrated, and outcomes are not player-conditioned. The flag remains off by default; neither result supports a default change or a scoring-calibration claim.
