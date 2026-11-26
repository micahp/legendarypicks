# NBA game forecasting model card

[Registry](README.md) · [Original Phase 1 model card](../NBA-GAME-MODEL-PHASE1.md)

**Evidence scope:** October 21, 2026 historical specification and evaluation on the separately pushed `feat/nba-game-model-phase1` research branch. It reported the prospective pipeline implemented but not merged, activated or deployed. Current operational status has not been reaudited. No betting edge claim.

| Candidate | Algorithm | Pregame output |
|---|---|---|
| G1 Elo | K=20, home adjustment 65 rating points, 75% offseason carry | Winner probability only |
| G2 Efficiency | EWMA .08 pace and opponent-adjusted efficiency, 50% offseason carry, two-point home adjustment | Scores, margin, total, win probability |
| G3 Joint scores | G2 means with prequential bivariate normal residuals; 2,048 integer score pairs | Coherent joint score distribution and derived probabilities |

Inputs: SportsDataverse ESPN team box scores and NBA Stats schedules; match canonical teams and scores within date window, fail on ambiguous joins. Same local-date games share pregame state; no post-tipoff, lineup or future result inputs. Preserve source hashes and cutoffs.

| Candidate | Test Brier | Spread MAE | Total MAE |
|---|---:|---:|---:|
| Fixed home-win/league-points baseline | .24887 | 12.527 | 17.578 |
| G1 | .21465 | — | — |
| G2 | .21474 | 11.191 | 15.797 |
| G3 | .21339 | 11.194 | 15.805 |

Same 2,460 eligible 2024–25 holdout games (ending-year 2024 and 2025); 5,827 training and 2,460 validation, 1,229 confirmation games separately. Small between-model point-estimate differences are not automatically significant; consult paired date-cluster intervals. No valid historical market comparison: no trustworthy timestamped NBA game-line feed in the original report. Forecast publication/grade, slate completeness and deployment remain separate checks. Full details, coverage and source manifests: [Phase 1](../NBA-GAME-MODEL-PHASE1.md).
