# RESULTS: G4 follow-up, is the narrow team spread the margins' fault or the sampler's? (2026-10-13)

Experiment, rules and decision rule: `backend/nfl_sim_margin_source.py` docstring, committed 8d48e3b before any run.
Harness: `backend/backtest_nfl_sim_scores.py --source v1|elo --n-sims 2000 --current 20000` (single thread, nice).
Raw output: `g4_v1.json` and `g4_elo.json` in the session scratchpad. Seasons 2020 to 2025, cutoffs after weeks 5 and 12.

## Verdict: hypothesis refuted

Hypothesis H: the shortfall (G4 ratio 0.791 against a 0.80 floor) comes from the expected margins, because the v1
ratings regress toward the mean, and not from the score sampler.

Decision rule, applied as written: supported only if Elo's expected spread is more than 1.05 times v1's, Elo's G4 ratio beats
v1's by more than twice the noise, and both slopes are in [0.9, 1.1]. Refuted if Elo is wider but its ratio does not rise
beyond noise, or if v1's slope is below 0.9.

| Measurement | v1 source | Elo source |
|---|---|---|
| M1 expected points spread across teams (sd, points per game) | 3.089 | 2.977 (0.96 times v1, not wider) |
| (stack source, for reference) | 2.814 | |
| Real spread across teams | 4.571 | 4.571 |
| G4 simulated spread across teams | 3.616 | 3.504 |
| **G4 ratio (floor 0.80)** | **0.791, fails** | **0.767, fails** |
| M3 slope of simulated on expected points per game | **0.723** | 0.697 |
| Ratio if the slope were 1 (M3 predicted) | 0.905 | 0.889 |

- v1's slope is 0.723, below 0.9, so the rule says refuted. The sampler passes only about 72% of a team's expected
  difference through to simulated points per game.
- Elo's expected spread is not wider than v1's (2.98 against 3.09), so the lever the hypothesis named does not exist, and
  its ratio is lower (0.767), not higher.
- The shortfall has two parts. Even with a pass-through slope of 1 the ratio would be about 0.905, so the inputs are
  themselves too compressed. The sampler's shrinkage then takes it down by about 0.11 to 0.791.

## Gates for the Elo source (unchanged thresholds)

| Gate | Result |
|---|---|
| G1 outcome calibration | pass. Win Brier 0.225070 against 0.225028 for the Elo normal, same up to noise. On the same 1,515 games v1's normal scores 0.228281, so Elo's single-game probabilities are better by 0.0033 |
| G2 validity | pass (6.74M games, 0 invalid, tie rate 0.319%) |
| G3 totals | pass (mean 45.62 against 45.84, sd 13.93 against 13.81) |
| G4 team spread | fail, ratio 0.767 |
| G5 playoff odds against the placeholder | **fail**. Playoff Brier +0.00597 against noise 0.00057 (bound 0.00113); division Brier +0.00190 (bound 0.001). Mean absolute change per team 4.9 points, largest 32 points (CAR 2021 after week 5, 53.6% to 21.2%) |
| G6 ties | pass (48,000 seasons, 0 exceptions, 0 violations) |

Trade-off: an Elo margin source predicts single games better but makes the season odds worse. The cause was not
investigated. A candidate: Elo ratings are held fixed inside a simulated season, while v1's hot update path adjusts them.

## What this does and does not show

- It refutes H-A as the main cause (Elo is not wider) and shows H-B is false: the sampler does shrink.
- It does not show that fixing the sampler would pass G4. The M3 predicted ratio with a slope of 1 is 0.905, an estimate from
  the measured spread and slope, not a run.
- v1 stays the default margin source and the placeholder stays the default score option.
- Next experiment, if wanted: raise the sampler's pass-through (fewer neighbours, or a variance-restoring step on the
  expected points), pre-registered before it runs, with G1 to G6 unchanged. K and the thresholds are not touched here.
