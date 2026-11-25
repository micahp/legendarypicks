# SLC V2 mechanism ablation: results

Date: 2026-11-25. Spec: `SLC-V2-LAYER-ABLATION-SPEC-2026-11-24.md` (amendments 1-3). Runner and graders:
`slc-v2-audit/ablation-runner/`, `slc-v2-audit/grading/`. Results: `slc-v2-audit/results-full/`.

## Result

1. **The control is exact.** A00 reproduces the frozen Week 11 V2 on all 13 games: 260/260 seeds identical in scores
   and player box scores. All 38 SLC arms completed every game (100% valid full games, except P1 at 98%).
2. **V2's row filters collapse its historical support.** The filters run in a chain. On the control, a play's candidate
   rows fall from about 1,560 (after the event draw) to 706 after the formation filter, then to about 54 after the streak
   filter, and to **1.5 rows on average after the label filter**. Most V2 plays copy one or two specific historical rows,
   not a distribution.
3. **Removing filters and context improves player props.** Six removals lower the prop Brier score with an interval
   below zero (1,037 graded props per arm):

| removed | prop Brier vs control | prop log loss vs control |
|---|---|---|
| S1 participation lineup | -0.022 (-0.045 to -0.003) | -0.114 (-0.192 to -0.049) |
| K3 streak context (all streak mechanisms) | -0.017 (-0.028 to -0.007) | -0.049 (-0.078 to -0.019) |
| P2 point-split play-calling shift | -0.012 (-0.017 to -0.008) | -0.038 (-0.060 to -0.014) |
| K2 streak row filter | -0.010 (-0.018 to -0.001) | -0.030 (-0.062 to -0.001) |
| F3 formation row filter | -0.010 (-0.019 to -0.000) | -0.028 (n.s.) |
| C3 coverage row filter | -0.009 (-0.016 to -0.002) | -0.031 (-0.058 to -0.008) |
| P1 score-clock play-calling | -0.009 (-0.017 to -0.002) | -0.032 (-0.052 to -0.012) |

4. **Player allocation helps props.** Removing it makes them worse: L5 label participant allocation +0.016
   (+0.005 to +0.027), log loss +0.053; D1 Dirichlet shares log loss +0.055 (+0.017 to +0.094).
5. **Game lines barely move.** Only one removal hurts the home-win Brier score with an interval above zero: F1
   formation choice, +0.064 (+0.022 to +0.109). D1 lowers it by 0.046 (-0.078 to -0.019), which is very likely
   noise: player allocation should not change winners. Every other game-level change has an interval that includes zero.
6. **Redundant and inactive mechanisms.**
   - The QB target-role row filter (Q3) changes nothing. It runs on 1.1 candidate rows on average, after the label
     filter has already matched the target role, so Q3 is identical to the control.
   - The zero-weight guards never fired in any arm.
   - The sparse fallback path is rare: 0.16% to 0.25% of decisions.
   - G4 (team and player tables removed) equals G3 (their switches off), as it must.
7. **The minimal arm Z1 could not run.** With no SLC sampler, all 260 games blocked at
   `field_goal_distance_sampler_missing`. This pack's plain game path has no field-goal distance sampler, so Z1
   needs a pack built for the plain path. Recorded, not dropped.

## Setup

- 39 arms; 13 week 11 2026 games; 20 matched seeds per game (300001-300020); RNG v2 with the control's stream root.
- Fast host, `/usr/bin/python3.12` with the same engine and environment as the frozen runs. Each game runs in a forked
  child of a parent that decoded the pack once, so no state carries between games (amendment 3).
- Graded with the frozen week 11 grader, on the same inputs: `games.csv` f3a6752c, player stats 0be2a210, props from
  `picks.dev.db`. Arm minus control, 95% game-bootstrap interval. Log loss clips at 0.025.

## Control values

Home-win Brier 0.211, log loss 0.603; cover Brier 0.321; over Brier 0.315; mean absolute total error 12.0 points;
prop Brier 0.316, log loss 0.948; mean team points 20.8 (actual 23.7); SD of team mean points over the 26 team-games 3.46.

## Group arms

G1 (all multipliers off), G2 (all optional filters off) and G3 (both) show no game-level effect with an interval
excluding zero. G2 lowers the prop Brier score by 0.009 (-0.018 to +0.001). Without multipliers and filters, the SD of
team mean points falls from 3.46 to 1.93: the layers do make teams differ, but the forecasts do not show that this
difference is right.

## Limits

- 13 games. Many comparisons at once: with 38 arms, a few intervals below zero are expected by chance. The pattern
  (filters and context hurt props; allocation helps them) is consistent across related arms, which makes it more
  credible than any single result.
- 20 seeds per game, so a prop probability moves in steps of 0.05.
- Not yet measured: realism against the 2025 season per team-game, and the noise-removed between-team variance.

## What to do next

1. **Test a simpler V2 candidate prospectively** (week 12 and later): without the streak context, the point-split
   shift and the formation, coverage and streak row filters; keeping the Dirichlet shares, the label participant
   allocation and the formation choice. Matched seeds against the frozen V2. Pre-register it first.
2. **Fix the filter chain before any fallback design.** A chain that ends at 1.5 rows is the main structural problem.
   The unified fallback architecture should start from a minimum support per draw, and relax conditioning when that
   floor is not met. Today each filter only stops when it would leave zero rows.
3. **Rebuild the two pending arms** (Y1 season adaptation, Y2 snap-count update) and the Z1 plain-path pack.
