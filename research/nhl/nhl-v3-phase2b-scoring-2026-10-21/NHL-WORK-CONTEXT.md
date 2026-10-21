# NHL research context: V3 replay, scoring, and rate variation

Updated 2026-10-21. This is a handoff across the NHL modeling sessions. Phase 1 through the current rate-variation audit are research artifacts. No NHL live picks, production models, or production data were changed.

## Status and boundaries

- Current worktree: `/root/lp-nhl-v3-rate-variation-2026-10-21`.
- Current branch: `research/nhl-v3-rate-variation-2026-10-21`, created at `ad79a135e7488e0f9700cdc60066d0143148bec8`.
- Prior accepted research branch: `research/nhl-v3-underdispersion-2026-10-21` at `ad79a135e7488e0f9700cdc60066d0143148bec8`; the manager verified and pushed that base.
- Current task is diagnostic only. No candidate, gate, or promotion rule was changed. Phase 2A artifacts remain byte-identical to their frozen hashes.
- The 2022 season was already exposed during prior evaluation. Treat it as historical diagnostic evidence; use 2021 for development analysis and reserve a later season or prospective slate for confirmation.
- Phase 2C implementation requires Micah's approval. Do not start it as a continuation of these diagnostics.

## Phase 1 — deterministic replay and data eligibility

`research/nhl/nhl-v3-phase1-replay-2026-10-21/` established the source-pinned event and identity boundary for later modeling. It replayed all 4,876 games and 1,510,104 PBP rows in source order, verified raw PBP and shift bodies, reconciled accepted team scores for 4,876/4,876 games and official team SOG for 4,814/4,876 games. The 62 SOG-ineligible games remained quarantined. Ordinary attempts, ordinary SOG, regulation/OT goals, and shootout outcomes remain separate counts.

Phase 1 is a replay and eligibility layer, not a probability model. Its 12-test replay engine suite passed on 2026-10-21. Phase 2A and later phases consume its approved, component-specific dispositions and pinned source artifacts.

## Phase 2A — stochastic shot and scoring prototype

Frozen Phase 2A base: `19bb60cf8997abe1368b732983a4ed2ac1904cd3`. Fit seasons are 2018–2020, development is 2021 (1,312 games), and the partial 2022 holdout has 343 games (341 SOG-eligible). Historical team attack and defense features use prior accepted team-SOG games only, with same-date outcomes excluded. The simulator receives a pregame snapshot; actual target-game shots, locations, shooter identities, and goalie identities are not predictors.

Phase 2A is a coherent generated-event prototype, but it was **not adopted** over the simple historical-rate baseline. In the same-window 2022 comparison, V3 had team goal CRPS 0.993 versus 0.947 for the v2 score-model refit, and final-score energy 1.586 versus 1.500. Winner Brier was 0.2424 versus 0.2439, with uncertainty that did not establish a win. The older simple-baseline comparison also showed V3 SOG CRPS improving by 0.227 while team-goal CRPS worsened by 0.048 and final-score energy worsened by 0.082. The 2022 window is historical evidence, not a reusable tuning set.

Frozen Phase 2A artifact hashes:

- `EVALUATION.json`: `24d5a55754a6b072f66203096a1936036a8d209df870ef6f8787bd0a22fc3930`
- `FITTED-MODEL.json`: `8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb`
- `REPORT.md`: `b0867d3cf1ef64a30469d087a03bda9ed156bbbbe020458b3efbb562473036f0`

The prototype remains team-level. It does not assign shooters or lineups, model goalie identity, possession, rebounds, line changes, empty-net pulls, or a full penalty process. Generated clocks are exponential; penalties are limited to one minor at a time and omit much of actual special-teams behavior.

## Phase 2B — controlled scoring diagnosis

Phase 2B retained the Phase 2A generator and tested isolated scoring adapters on 2021. Candidate C (v2 goal-rate prior distributed over generated shot chances) ranked best on development goal CRPS, gaining 0.0529 over Phase 2A and improving final-score energy by 0.0799, while worsening team-SOG CRPS by 0.0387. Those are selected-fold descriptive results, not adoption evidence. No Phase 2B result changes the frozen Phase 2A artifacts.

On 2021, observed versus Phase 2A predicted/generated per team-game means were: attempts 56.656/56.470; official SOG 31.602/31.095; regulation-plus-OT goals 3.106/3.434. Observed goals per PBP SOG were 0.0982, versus 0.1105 on generated SOG. Evaluating conditional goal probability at the actual event locations gave 0.0927 versus the observed 0.0982. This points to shot-quality/state composition and full-game compounding as material factors; it does not isolate a causal error.

Additional diagnostics: generated even-strength goals exceeded observed by 1.177 per game; generated empty-net goals were zero versus 0.363 observed per game; accepted penalties were 4.890 versus 7.390 per game. Overtime and shootout entries were also undergenerated. The one-minor penalty process and missing empty-net pull logic are structural limitations.

## Under-dispersion follow-up

Committed on the accepted under-dispersion research branch at `ad79a135e7488e0f9700cdc60066d0143148bec8`. The work rescanned all 1,510,104 pinned event rows and reused 41,984 stored simulation paths (1,312 games × 16 draws × two candidates); it did not rerun Monte Carlo.

The main correction is to distinguish within-game predictive variance from total across-team-game variance. For attempts, observed total variance was 119.726 and the full Phase 2A predictive mixture variance was 75.089; 62.992 was only its within-game predictive component. Observed between-team mean variance was 18.844 versus 1.966 forecast. For official SOG, total variance was 47.792 versus 34.631, with between-team components 7.157 versus 0.694. For goals, observed and full-predictive marginal variances were 3.154 and 3.315; observed within-team variance was 2.975 and the forecast mean was high by 0.328 goals/team-game.

Observed home-away attempt covariance/correlation was −44.710/−0.382 versus −8.820/−0.119 generated. For SOG it was −11.460/−0.242 versus −0.655/−0.019. A penalty fixed-effect projection explained very little of the attempt/SOG variance gap and was explicitly noncausal. The goal-variance sensitivity was descriptive-after-selection and did not justify adopting a variance adjustment.

## Current rate-variation diagnostic

Files added by this branch:

- `RATE-VARIATION.md` — concise findings.
- `rate_variation.json` — machine-readable measurements, pins, per-team bucket assignments, bootstrap intervals, and reproduction details.
- `rate_variation.py` — full source-and-trace reproduction; no Monte Carlo rerun.

The audit uses all 1,312 2021 development games and 148,665 accepted attempts. The quality reference is 31.198301 prior SOG/team-game. Attack quality is LOW at a ratio ≤0.90, AVERAGE above 0.90 and below 1.10, HIGH at ≥1.10; defense reverses strong/weak. By modal 2021 pregame assignment, 27 of 32 teams are AVERAGE, four HIGH, and one LOW. There are 1,389 distinct realized eight-part categorical rate keys at accepted attempts; the JSON contains every realized key and its attempt count. The frozen rate path has no continuous team-level term: `quality_level` maps rolling team rates to categories, `state_key` returns category labels, and `shot_rate` exponentiates a linear predictor over them.

Frozen forecast between-team variance remains 1.966 attempts and 0.694 SOG against observed 18.844 and 7.157. The gaps are 16.877 and 6.463; their approximate additive log-scale SDs are 0.0725 and 0.0804. Forecast-mean variance is almost entirely associated with bucket-frequency terms in the descriptive feature decomposition (attempts 1.926 bucket / approximately 0 home-away / 0.040 unallocated; SOG 0.662 / 0.005 / 0.027).

Crucially, a same-fold descriptive projection of observed team means on attack-bucket and opponent-defense-bucket frequencies plus home share explains 16.691/18.844 attempt variance and 6.971/7.157 SOG variance. This uses the same 2021 outcomes and is descriptive-after-selection, not validation. It means the full forecast gap is **not proven to be unreachable with categorical features** and does not show that a continuous team term must supply all 16.877 variance units. Current bucket coefficients or other generator structure may be too weak or misaligned; within-bucket distinctions remain structurally impossible. Cluster-bootstrap intervals resample game IDs with both teams kept together.

The clock mechanism is the sum-rate exponential clock plus shooter choice by rate share, equivalent to independent team Poisson clocks. No common game tempo or fixed combined-attempt constraint is present. A common positive mean-one tempo multiplier adds positive covariance: for attempts, SD/CV 0.05 moves generated covariance from −8.820 to −0.872; 0.10 moves it to +22.971; 0.15 to +62.709. This is the wrong sign relative to observed −44.710. SOG similarly turns positive at CV 0.05. No generator changes were made.

## Separate 2026–27 prospective NHL score model

This is a separate product/prediction track from the historical V3 event-generator research. The 2026-10-19 context records a prospective v2 ridge-Poisson team-strength model (`research/nhl-team-strength-2026-10-19` at `4ad7b0ba`), with attack, defense, home advantage, neutral-site suppression, and a 400-day recency half-life. It improved Brier over its earlier NHL version on walk-forward evaluation but remained worse than the closing-market benchmark on the matched sample. The context explicitly says NHL picks are unsupported; no result from that track promotes V3.

## Reproduction and next decision boundary

Run the current diagnostic from the repository root:

```sh
/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2b-scoring-2026-10-21/rate_variation.py --bootstrap-replicates 2000
```

All reported intervals cluster by game ID with both teams retained. The current run took 149.27 seconds including full pinned-source validation and 2,000 resamples. Do not use 2022 for more tuning. Do not implement Phase 2C, change a gate, adopt a candidate, alter live picks, or modify the frozen Phase 2A artifacts without a separate authorized decision and properly separated later-season/prospective evidence.
