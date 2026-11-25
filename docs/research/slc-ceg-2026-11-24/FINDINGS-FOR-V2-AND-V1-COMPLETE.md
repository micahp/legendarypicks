# CEG findings for V2 and V1 Complete

From CEG Phases 0 to 9 (`research/slc-ceg-2026-11-24`). Short and practical. Each item names its evidence.

## Measurement

1. **Correct drive and game errors for Monte Carlo noise.** A simulated drive's expected points is a mean of a few
   draws; its squared error carries var/n. Without the correction, a simulator looked far worse than a plain rating
   (Phase 8); with it, the situation-only simulator matched the rating (Phase 9).
2. **Use enough seeds for game probabilities.** 40 seeds gives a home-win standard error of about 0.08, so most of the
   spread between games in a 40-seed forecast is noise (Phase 7).
3. **Matched seeds need a fixed RNG stream root.** The portable runner derives the root from the layer description, so
   removing a layer changes every stream unless the control's plan is reused (V2 ablation, amendment 1).

## Team strength

4. **Per-play log score is the wrong tuning target for team terms.** The real per-play gain is tiny next to play noise,
   so it picks near-total shrinkage (Phase 8: team spread 0.17 yards per carry against a true 0.41).
5. **Single-season drive tuning with weak shrinkage gives the right spread but the wrong order** (Phase 9: E9 offense
   ranking 0.68 in 2024, 0.38 in 2025).
6. **Offense signal is much larger than defense** (reliability 0.77 against 0.24 for points per drive, split halves,
   2022-2024).
7. **The best tested approach calibrates a simulator's team shift to a cutoff-safe points-per-drive rating** (E-R):
   it beats the rating on drive error and passes the realism guard, but it still ranks teams below the rating.

## Engine and data

8. **nflverse `penalty_yards` are enforced yards.** Draw nominal yards and apply half-distance once; pass
   interference is a spot foul (E13, fixed in CEG `02ba92ae`).
9. **Kickoff pools built from "receiving team runs the next play" cannot produce onside recoveries, return touchdowns
   or kickoff turnovers** (V2 audit, Phase 1). V2 has this; CEG Phase 4 models them.
10. **In V2, timeouts are a side effect of row sampling, not a decision** (V2 audit, Phase 1). CEG Phase 3 models
    timeouts at real opportunities (C beats B by 0.054 per opportunity).
11. **Separate live-play time from dead-ball time.** The split identifies where the clock runs and stops; Model D's
    single runoff ties on total but cannot answer timeout or out-of-bounds questions (Phase 3).
12. **A loaded table does not mean its mechanism runs.** Record the mechanisms applied per decision (V2 ablation,
    amendment 2).
13. **One standard Python stack** (`lp-standard`: the backend's pinned packages on Python 3.8.20, both hosts), with a
    cross-host exact-match test before trusting a host (`PYTHON-ENVIRONMENT-PINNING-PLAN-2026-11-24.md`).
