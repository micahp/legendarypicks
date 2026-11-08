# Seattle and Arizona RB lineup diagnostic, 2026-11-08

The paired D1 run at simulator commit `1c1afaa0` used the participation field but **did not enable its current-season snap-count update**. All 100 simulated seeds completed and reconciled. The comparison below uses modeled RB scrimmage appearances and `nfl_snap_counts` rows for 2026 weeks 1–8 from the local read-only application database. The source rows were captured on November 8 after the original snapshot, have no recorded acquisition times, and are not verified as cutoff-safe. Observed and simulated snap definitions differ; these are diagnostic comparisons, not week 9 prediction errors.

| Team / RB | Modeled mean snaps | Modeled mean share of team scrimmage plays | Recorded weeks with a row | Recorded mean offensive snap share on those rows |
|---|---:|---:|---:|---:|
| SEA Zach Charbonnet | 40.82 | 0.609 | 1 | 0.370 |
| SEA Emanuel Wilson | 1.16 | 0.017 | 8 | 0.352 |
| SEA George Holani | 13.58 | 0.205 | 8 | 0.371 |
| SEA Jadarian Price | 1.46 | 0.022 | 4 | 0.395 |
| ARI James Conner | 40.93 | 0.605 | 0 | unknown |
| ARI Tyler Allgeier | 1.84 | 0.027 | 8 | 0.525 |
| ARI Jeremiyah Love | 2.10 | 0.030 | 6 | 0.433 |
| ARI Bam Knight | 13.32 | 0.198 | 8 | 0.171 |

A missing snap row does **not** mean the player was inactive, unrostered, or played zero snaps. Shares among recorded rows are conditional on those rows existing. `observed-comparison.json` includes the exact observed rows, query, canonical row hash, simulation ledger hash, per-player comparisons, and explicit limitations. Recorded snap percentages are rounded by the source. The prior simulation's official roster eligibility was unknown.

## Existing calibration and a candidate test

The existing [weekly player backtest](../../participation-model-2026-11-02/WEEKLY-PLAYER-BACKTEST-RESULTS-2026-11-04.md) found the current-season snap update reduced player share error from 0.2034 to 0.1553 in development-exposed 2022–2025 data, but still trailed a simple share-to-date baseline. The update is already implemented in `snap_update.py`; it should be tested with D1 before changing the lineup defaults or adding arbitrary workload caps.

`exploratory-snaps-through-week8.json` extends the earlier published week 1–7 extract (SHA-256 `fc409bce73fae449dcdf160f60979240ad06748506df7e9c66ac75c11f975a94`) with week 8 observed snap rows from the current local database. Its SHA-256 is `6bc6591a1d42befaa6c67e1fb373ca1486001fdd1d55df235a81cfe244d168eb`. It records the original week 8 query rows and their hash, 28 team-game denominators estimated from rounded snap percentages, 514 positive identified player rows, and no unresolved positive rows. It supplies **no active-roster membership for week 8**; zero and missing rows are not turned into active or inactive evidence. The model's week 8 player-share denominator is consequently conditional on observed positive rows and is not a verified active-game denominator. This extract is exploratory and must not be used as proof of an official week 9 roster.
