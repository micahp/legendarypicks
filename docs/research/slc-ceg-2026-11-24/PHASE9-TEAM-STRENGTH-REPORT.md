# SLC-CEG Phase 9: team strength tuned on drive points

Date: 2026-11-24/25. Pre-registration: `PHASE9-PREREGISTRATION.md` v2 (`865341e8`, before any score). Code:
`scripts/nfl_sequence/ceg_phase9.py` (`c57872b8`). Results: `phase9/tune2024_AB.json`, `phase9/eval2025_with_er.json`,
`phase9/perplay2025.json`, `phase9/er_slope_2024.json`, `phase9/eval2025_versions.json`. Candidates:
`CANDIDATES.md`.

## Result

1. **No team-strength candidate beats "no team terms" (C) on 2025 drive points.** The pre-registered test was the
   corrected squared error with a 95% game-bootstrap interval below zero. E9 (drive-tuned) +0.008 (-0.168 to +0.199);
   E-R (calibrated to R) -0.103 (-0.260 to +0.056); E8 -0.113 (-0.248 to +0.018); E6 -0.068 (-0.165 to +0.021).
2. **E-R is the best candidate.** It beats the simple baseline R on drive error by 0.262 (0.067 to 0.464), passes the
   realism guard, and ranks offenses at r 0.48. R ranks them at 0.62, so the simulator's ranking is still weaker than
   the plain points-per-drive rating.
3. **The simulator already matches R on drive error without team terms.** Once Monte Carlo noise is removed, C's error
   (7.88) is lower than R's (8.04; R minus C +0.159, -0.038 to +0.383). The situation, field position and clock carry
   most of the drive signal; team strength is a small part on top.
4. **Weak shrinkage gives the right spread but not the right order.** E9's offense SD (0.29) is close to the actual
   (0.33), but its 2025 ranking (0.38) is far below its 2024 tuning value (0.68): with lambda 10, much of the spread is
   noise that does not carry from one season to the next.
5. **Defense signal stays weak.** Step B kept defense strength at lambda 1,000. Defense ranking on 2025: R -0.09,
   E9 0.17, E-R 0.16.

## Tuning on 2024 (5,827 drives, 2 draws, 0 halts)

| arm | corrected error | offense r | offense SD | defense r | guard |
|---|---|---|---|---|---|
| C | 7.807 | -0.04 | 0.08 | 0.15 | |
| O1000 D1000 | 7.744 | 0.40 | 0.14 | 0.12 | pass |
| O100 D1000 | 7.708 | 0.67 | 0.25 | 0.20 | pass |
| O30 D1000 | 7.686 | 0.67 | 0.27 | 0.16 | fail (run yards -2.2%) |
| **O10 D1000 (E9)** | **7.685** | 0.68 | 0.29 | 0.14 | fail (run yards -2.4%) |
| O10 D100 | 7.745 | 0.66 | 0.27 | 0.10 | fail |
| O10 D30 | 7.710 | 0.64 | 0.27 | 0.12 | fail |
| R | 7.892 | 0.71 | 0.29 | 0.27 | |
| actual | | | 0.40 | | |

The pre-registered rule chose lambda_O by the lowest corrected error (O10, which edges O30 by 0.0007), then lambda_D
(1,000). The realism guard is scored on 2025, where E9 passes it.

## 2025 retrospective (5,698 drives, 4 draws, 0 halts)

| arm | corrected error | vs C (95%) | offense r | offense SD | mean expected points | guard |
|---|---|---|---|---|---|---|
| C | 7.877 | | -0.14 | 0.00 | 1.963 | |
| E6 | 7.809 | -0.068 (-0.165 to +0.021) | 0.05 | 0.06 | 1.969 | pass |
| E8 | 7.764 | -0.113 (-0.248 to +0.018) | 0.23 | 0.10 | 1.973 | pass |
| E9 | 7.884 | +0.008 (-0.168 to +0.199) | 0.38 | 0.29 | 1.971 | pass |
| E-R | 7.774 | -0.103 (-0.260 to +0.056) | 0.48 | 0.28 | 1.991 | pass |
| R | 8.036 | +0.159 (-0.038 to +0.383) | 0.62 | 0.29 | | |
| actual | | | | 0.33 | 2.116 | |

E-R: the slope of league expected points per drive against a common offense shift, measured once on 2024, is 2.21
points per drive per logit (1,000 drives at b -0.15 and +0.15).

**Components on 2025 (generated, against actual):** yards per carry 4.30 to 4.38 (actual 4.29); YAC per completion
5.18 to 5.25 (actual 5.13); third and fourth down conversion 0.399 for every arm (actual 0.416); red-zone touchdown rate
0.596 to 0.601 (actual 0.610). Team strength moves none of these at the league level, as the guard requires.

**Per-play log loss on 2025 (E9's terms against their runtime base):** offense dropback outcome (k 10) -0.0035
(-0.0055 to -0.0016); defense run yards -0.0006, defense YAC -0.0005, defense targeted outcome -0.0007 (all with
intervals below zero); offense run yards +0.0002, offense YAC +0.0008, offense targeted outcome +0.0009 (none
significant). At lambda 10, the offense yardage and completion terms add noise per play.

## Runs and environment

The 2025 runs ran on the fast host from a copy of the code at `cbcabc0e`, with system Python 3.12.3, pandas 3.1.1,
numpy 2.4.4. A 20-drive smoke test gave identical draws there and on this box (Python 3.8.10, pandas 1.5.3), and
again under the standard `lp-standard` environment. All arms of one season ran from the same code and environment.
The E13 penalty-yard fix (`02ba92ae`) came after these runs and is not in them.

## What it means for the next step

- Team strength in the play-level generator has a small, real per-play signal (defense terms, the offense
  dropback term), but at drive level it does not yet beat the situation-only simulator.
- The strongest candidate is calibration to a points-per-drive rating (E-R). Before building more component terms,
  test E-R on prospective drives (2026 week 12 and later), as pre-registered.
- Do not choose team-term strength by per-play log score (Phase 8) or by a single season's drive error with weak
  shrinkage (E9): both overfit or underfit the team spread.
