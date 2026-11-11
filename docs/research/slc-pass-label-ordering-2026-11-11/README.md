# SLC pass-label ordering experiment — 2026-11-11

## Current result

The source data supports the ordering concern. On 18,276 eligible 2025 dropbacks, labels A (receiver role), D (pass depth), and E (pass location) were present on **0 of 1,197 sacks**. They were present on 100% of completions, 100% of charted pass depth/location on incompletions, and 98.6%/100%/100% of interceptions. The current lift treats a missing label on a sack as zero conditional support, then shrinks that toward a nonzero all-label sack share. A/D/E therefore suppress sack weight even though sacks have no such label.

| Held-out 2025 metric | Historical situation baseline | Existing A/D/E event lifts | A/D/E removed | Two-stage |
|---|---:|---:|---:|---:|
| Predicted sack rate | 6.52% | 0.12% | 6.52% | 6.52% |
| Actual sack rate | 6.55% | 6.55% | 6.55% | 6.55% |
| Predicted completion rate | 59.85% | 65.14% | 59.85% | 61.03% |
| Multiclass event log loss ↓ | 0.9536 | 1.1982 | 0.9536 | 0.9550 |
| Multiclass event Brier ↓ | 0.5376 | 0.5455 | 0.5376 | 0.5379 |

Each category alone caused the same structural failure: A only predicted 0.16% sacks, D only 0.10%, and E only 0.16%, against the observed 6.55%. The off-versus-legacy game-clustered 95% intervals for the score difference were +0.225 to +0.266 log loss and +0.0068 to +0.0092 multiclass Brier (positive means legacy was worse). The two-stage arm preserved sack probability, but its pass-event scores were slightly worse than the no-lift arm; the paired intervals for its score difference were +0.00032 to +0.00251 log loss and +0.00002 to +0.00067 Brier. This supports fixing event ordering; it does not establish that A/D/E improve pass-outcome prediction.

The audit is a historical, observed-situation comparison. It uses 2022–2024 play data for event frequencies, 2024 team/cell label priors, and 2025 held-out dropbacks. It isolates A/D/E and uses the same event vocabulary in all arms. It does not include coverage, formation, other decision labels, team/player outcome weights, scramble choice, generated situations, or drive/game effects. Fumble-lost combines several football mechanisms. See [audit results](audit-results.json) and its read-only [reproducer](audit.py).

## Coverage, tested separately

Coverage is a pre-play defensive call, so its timing differs from receiver/depth/location labels. On 18,261 2025 dropbacks with known coverage, the 2022–2024 coverage-conditioned model reduced multiclass Brier from 0.5376 to 0.5353, but worsened log loss from 0.9536 to 0.9577. The game-clustered 95% interval for log-loss change was +0.0014 to +0.0069; for Brier it was −0.0036 to −0.0008. It predicted a 4.47% sack rate against 6.54% observed. This is mixed evidence and does not justify the 1.51-point coverage reduction seen in the three-seed trace. Do not combine this result with the A/D/E correction. See [coverage results](coverage-audit-results.json) and [reproducer](coverage-audit.py).

## Experimental sampler

The batch CLI now has `--playcall-pass-label-mode`:

- `legacy` preserves the existing V2 sampler.
- `off` removes A/D/E event lifts while retaining post-event row filtering and other model layers.
- `two_stage` selects the non-pass versus pass-outcome group without A/D/E, then applies the old marginal label lifts only among pass outcomes. Its first-stage pass mass and sack probability are therefore independent of A/D/E. This was the ordering-only experiment; its held-out scores were slightly worse than the no-lift baseline.
- `conditional` uses the fitted, regularized pass-outcome model described in [conditional-model-results.md](conditional-model-results.md). It applies A/D/E after the pass attempt is selected and excludes sacks from that model. Its label effects are calibrated to preserve the baseline pass-event mix under the configured label priors.

The default is `auto`: it selects `conditional` when decision labels are enabled and `legacy` when they are disabled. Set `legacy` explicitly to reproduce previous runs. The conditional historical evaluation and its machine-readable output are [here](conditional-model-results.md) and [here](conditional-model-evaluation.json). Focused sampler tests verify that changing A/D/E cannot change first-stage sack probability and can only change the conditional pass outcome.

All three V2/D1 arms completed on the same paired RNG-v2 stream root and seeds 1–3. All 9 games validated, and all 9 strict box-score reconciliations passed. The corrected two-stage arm was regenerated after fixing an unnecessary RNG draw on the called-run path. The first two-stage attempt is preserved with `initial-superseded` in its filename and excluded from these results. The correction is isolated to two-stage execution; legacy and no-lift results were not rerun.

| Arm | Dropbacks | Sacks | INTs | Completions | All turnovers / 6 team-games | Mean game total |
|---|---:|---:|---:|---:|---:|---:|
| Existing V2 | 211 | 7 (3.32%) | 2 (0.95%) | 139 (65.88%) | 2 (0.33/team-game) | 46.3 |
| V2, A/D/E event lifts off | 209 | 10 (4.78%) | 2 (0.96%) | 136 (65.07%) | 3 (0.50/team-game) | 49.3 |
| Two-stage, corrected | 226 | 17 (7.52%) | 5 (2.21%) | 128 (56.64%) | 6 (1.00/team-game) | 33.7 |

The historical 2025 held-out rates were 6.55% sacks, 1.96% interceptions, 59.82% completions and 2.65% turnovers per dropback. In this small full-game sample, corrected two-stage produced a 7.52% sack rate, 2.21% interception rate and 56.64% completion rate. These are noisy three-seed observations, not evidence of general calibration improvement. Two-stage had two team scores at or below 10 and no games at 60+; the mean game total was 33.7. These scoring tails are also inconclusive at this size.

The corrected ordering-only two-stage scores were 3–36, 10–16 and 16–20. Legacy and no-lift retain their recorded outcomes. Do not treat these three games as a validation of the newly fitted conditional model or claim that it fixes scoring tails. The updated pass sampler did not cause invalid games or reconciliation failures in this ordering smoke test.

The corrected arm's run spent about 275 seconds building context and reference data and 16 seconds generating games (334.7 seconds total before writing the report). This cost is primarily per-run setup, not the three game simulations themselves.

Ordered plays, probability traces, seed ledgers and box-score sidecars are preserved under [simulation outputs](simulation-outputs/). The machine-readable [summary](simulation-results.json) and [summarizer](summarize_simulation.py) assert equal stream roots, seed IDs, complete games and strict reconciliation.

## Inputs and status

- Database: `/root/legendarypicks/backend/data/picks.dev.db`, SHA-256 `1c657408f639a78e1e744bb883abf944b6296ed7bf42710e629456129dd736db`, opened read-only.
- PBP 2026 release: SHA-256 `5030e8fc1739ea8f93ce67b461f76d3ae89b2f952d430ddbfa5b7f7f07d44b18`.
- Game simulation: `2026_09_ARI_SEA`, valid pre-roster-finalization snapshot, D1, RNG v2, seeds 1–3, identical frozen inputs and paired stream roots in each arm, box-score and ordered-play export enabled.
- This is a small development smoke test. It cannot establish matchup-general scoring calibration or adoption readiness.
