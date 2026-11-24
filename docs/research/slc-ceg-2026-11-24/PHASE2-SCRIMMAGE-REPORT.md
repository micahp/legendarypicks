# SLC-CEG Phase 2: scrimmage components, arms B, C and C-FTN

Date: 2026-11-24. Pre-registration: `PHASE2-PREREGISTRATION.md` (committed `b5a62b8f` before any 2025 score). Code:
`scripts/nfl_sequence/ceg_phase2.py` (estimators, tuning, scoring), `ceg_generator.py` (one play per snap, exit checks).
Results: `phase2/tune_2024.json`, `phase2/final_2025_2026.json`, `phase2/exit_checks_arm_C.json`,
`phase2/exit_checks_arm_B.json`. No frozen SLC version changed; no simulation batch.

## Result

1. **Arm C beats arm B on 6 of 11 components in 2025**, with the interval below zero: the play call (-0.390 per play),
   air yards (-0.025), run yards (-0.009), targeted outcome (-0.007), dropback outcome (-0.0025) and throwaway (-0.0015).
   It does not beat B on YAC, scramble yards, sack yards, fumble or fumble lost. The 2026 examined weeks point the same
   way on every component.
2. **C-FTN beats C on no component** under the pre-registered rule (both observed and generated context better than C).
   The charted context helps the targeted outcome when it is observed, and stops helping when the simulator must
   generate it.
3. **The generator never refuses a scrimmage state.** Arms C and B: each 0 refusals in 64,152 plays over a 21,384-state
   grid, and 0 in 33,372 plays over all 25 week 11 v1 and v1.5 scrimmage failure cells. Every drawn distribution summed to 1.
4. **The situation cells are finer than the data supports.** Tuning chose k = 300, the top of the pre-registered grid,
   for 10 of 11 components (the play call chose 10). Heavier shrinkage was still improving. This is reported, not fixed
   after the fact.

## Components and denominators

Regular season, no penalty plays, no two-point tries. Train 2022-2024, confirmation 2025, examined 2026 weeks 1 to 11.

| component | denominator | 2025 n |
|---|---|---|
| intent | scrimmage snap with a call | 35,659 |
| dropback outcome | dropback (sack, scramble, attempt) | 19,420 |
| throwaway | pass attempt with an FTN row | 17,107 |
| air yards | targeted attempt | 16,414 |
| targeted outcome | targeted attempt (given air-yards bucket) | 16,414 |
| YAC | completion, no fumble lost (censored at the goal line) | 11,001 |
| run yards | designed run, no fumble lost (censored) | 12,806 |
| scramble yards | scramble (censored) | 1,028 |
| sack yards | sack | 1,206 |
| fumble | run, scramble, sack, completion | 26,253 |
| fumble lost | fumble with a known recovering team | 407 |

## 2025 confirmation: log loss per opportunity

Lower is better. C minus B with a 95% game-bootstrap interval.

| component | B | C | C minus B | C better |
|---|---|---|---|---|
| intent | 1.0073 | 0.6178 | -0.3895 (-0.3986 to -0.3799) | yes |
| air yards | 3.5296 | 3.5048 | -0.0248 (-0.0319 to -0.0176) | yes |
| run yards | 2.7650 | 2.7559 | -0.0090 (-0.0144 to -0.0036) | yes |
| targeted outcome | 0.6693 | 0.6624 | -0.0069 (-0.0088 to -0.0050) | yes |
| dropback outcome | 0.4474 | 0.4449 | -0.0025 (-0.0043 to -0.0009) | yes |
| throwaway | 0.1696 | 0.1681 | -0.0015 (-0.0024 to -0.0005) | yes |
| YAC | 2.5390 | 2.5366 | -0.0024 (-0.0059 to +0.0010) | no |
| sack yards | 2.6282 | 2.6216 | -0.0066 (-0.0185 to +0.0058) | no |
| scramble yards | 2.8492 | 2.8500 | +0.0008 (-0.0097 to +0.0117) | no |
| fumble | 0.0789 | 0.0789 | -0.0000 (-0.0006 to +0.0005) | no |
| fumble lost | 0.6846 | 0.6833 | -0.0012 (-0.0062 to +0.0039) | no |

2026 examined (weeks 1 to 11), C minus B: intent -0.404, air yards -0.021, run yards -0.015, targeted outcome -0.006,
dropback outcome -0.002, throwaway -0.001; YAC, sack yards, scramble yards, fumble and fumble lost all include zero.

Reading it: the play call depends strongly on the situation (4th down, field position, the clock), so C gains a lot.
Outcomes given the call depend on it only a little: small, real gains. Yardage after the catch, scrambles, sacks and
fumbles show no situational signal that survives the shrinkage at this data size.

## C-FTN: charted context, observed and generated

Scored on identical FTN-covered plays. Context: pass rushers and play action (dropback outcome), play action and screen
(targeted outcome), defenders in the box (run yards).

| component | 2025 observed minus C | 2025 generated minus C | 2026 observed | 2026 generated |
|---|---|---|---|---|
| dropback outcome | -0.0001 (-0.0014 to +0.0011) | -0.0004 (-0.0007 to -0.0000) | -0.0012 (n.s.) | -0.0003 (n.s.) |
| targeted outcome | -0.0020 (-0.0036 to -0.0005) | +0.0011 (+0.0000 to +0.0023) | -0.0046 (below 0) | +0.0009 (n.s.) |
| run yards (box) | +0.0046 (+0.0014 to +0.0078) | -0.0016 (-0.0030 to -0.0003) | +0.0039 (above 0) | -0.0000 (n.s.) |

- **Targeted outcome:** knowing play action and screen helps (both seasons). But a simulator has to draw them first from
  the situation, and the mixture is no better than C, slightly worse in 2025. The information is in the observed charting,
  not in anything the situation predicts.
- **Run yards and box count:** splitting on box count first makes the fit worse (thinner cells), and the generated
  mixture is about equal to C. Box count would need a better-shaped model (box as an adjustment, not a first split)
  before it is worth testing again.
- **Dropback outcome:** no gain either way.

So C-FTN is not adopted for any component. The throwaway label from FTN is kept in both arms (it is a node of the chain,
not a predictor).

## Generator and exit checks

`ceg_generator.py` fits every component on 2022-2024 with the chosen k and draws one `GeneratedPlay` per call: the intent,
then the chain for that intent; a fumble and its recovery for runs, scrambles, sacks and completions; an interception
or fumble return from an arm B league return model censored at the end zone. Every play passes `ceg_contract.validate`.

| check | arm C | arm B |
|---|---|---|
| state grid (down 1-4, 9 distances, yardline 1-99, 3 score states, 2 half states), 3 draws each | 21,384 states, 64,152 plays, 0 refusals | 21,384 states, 64,152 plays, 0 refusals |
| week 11 v1 and v1.5 scrimmage failure cells (all 25), every integer state inside each cell | 11,124 states, 33,372 plays, 0 refusals | 11,124 states, 33,372 plays, 0 refusals |

Events on the arm C grid: run 19,091; completion 17,127; incompletion 9,121; punt 7,948; field goal attempt 4,482; sack
2,159; kneel 1,887; scramble 1,486; interception 641; spike 210. Boundaries reached: 2,795 at the opponent goal line
(touchdowns), 189 at the own goal line (safety by the rules core). Arm B, which ignores the situation, calls far fewer
   punts (3,488) and field goals (1,093) and more runs and passes on the same grid; that is the play-call gap in the table.

The week 11 failures also include 25 kick failures (blocked kicks, thin 50+ field goal cell, safety free kick). Those
are Phase 4.

**What the generator does not do yet (stated in each play's provenance):** the clock (Phase 3; plays carry no clock and
are validated with `require_clock=False`); players (the existing `pre_event` chooser fills the role slots); punt and
field goal results (Phase 4); penalties (Phase 4). Returns use an arm B league model that Phase 2 did not evaluate.

## Deviations and open items

- k = 300 at the edge of the grid for 10 components. A wider grid (or coarser cells) is a new pre-registered test, not
  a change to these results.
- The sack and scramble yardage samples are small (about 1,000 a season); their intervals are wide.
- 257 fumbles with an unknown recovering team are left out of "fumble lost" (Phase 1 audit).

## Next

Phase 3: the clock and timeouts, with live-play duration fitted on stopped-clock plays and dead-ball runoff on running-
clock plays, timeouts as decisions at the dead-ball opportunity, and the existing conditional clock model as the baseline.
