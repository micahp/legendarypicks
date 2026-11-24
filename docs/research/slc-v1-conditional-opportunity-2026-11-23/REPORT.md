# Conditional player opportunities, step 1: who gets each target and carry

Date: 2026-11-23. Branch `research/slc-v1-conditional-opportunity-2026-11-23`, off v1 (`58ef3861`). Local model only:
nothing here runs a game or changes v1. Script: `fit_opportunity_shares.py`; numbers: `opportunity_shares.json`.

## Question

Given that a team throws a targeted pass, or calls a designed run, what is the probability that player i gets it? This is
what v1's share layer sets (`share_distributions`, Dirichlet-multinomial v3).

## Result

**Using this season's usage is a large, clear gain. v1 uses only last season's share on the same team.**

2026 weeks 1 to 11 (Sunday), 162 games, 18,050 opportunities. Mean log loss per opportunity, lower is better. The 95%
interval is a bootstrap over games.

| model | all | targets | designed carries |
|---|---|---|---|
| M0 v1 baseline: last season's share for this team, floor 0.01 | 1.910 | 2.312 | 1.390 |
| M1 + this season's counts before the game week (k = 120) | 1.669 | 2.109 | 1.098 |
| M2 + a traded player keeps his share from his old team | 1.630 | 2.068 | 1.063 |
| M3 + situational factor per position group | 1.614 | 2.063 | 1.032 |

| gain | all | targets | carries |
|---|---|---|---|
| M1 over M0 | 0.241 (0.211 to 0.269) | 0.202 (0.177 to 0.229) | 0.292 (0.237 to 0.339) |
| M2 over M1 | 0.039 (0.026 to 0.053) | 0.041 (0.029 to 0.055) | 0.035 (0.015 to 0.059) |
| M3 over M2 | 0.017 (0.014 to 0.019) | 0.005 (0.003 to 0.007) | 0.031 (0.026 to 0.037) |
| M3 over M0 | 0.296 (0.265 to 0.324) | 0.249 (0.222 to 0.276) | 0.358 (0.303 to 0.412) |

- Every gain has an interval above zero.
- The gain holds in every week. M0 gets worse as the season goes on (1.85 in week 1, 2.02 in week 11), because last
  season's roster drifts further from this one. M3 stays between 1.52 and 1.69.
- Week 1 has no in-season data, so M1 equals M0 there. M2 still gains in week 1 (1.85 to 1.68), from players who
  changed teams.
- Within the realised player's position group (the exact draw v1 makes after it picks the group), M3 is 0.947 against
  M0's 1.182. The situational factor is per group, so by design it adds nothing within a group.

## Why v1 is wrong here: MIN at SF, week 11

The expected count is the sum of each player's predicted share over MIN's actual opportunities in that game (43 targets,
21 designed carries). So this isolates the share, not the team's pass volume.

| player | stat | actual | M0 (v1) | M3 |
|---|---|---|---|---|
| Justin Jefferson | targets | 9 | 20.8 | 15.1 |
| Tai Felton | targets | 12 | 0.7 | 2.0 |
| Jauan Jennings | targets | 6 | 0.7 | 4.5 |
| T.J. Hockenson | targets | 7 | 9.7 | 9.1 |
| Aaron Jones | carries | 8 | 9.3 | 12.5 |
| Jordan Mason | carries | 11 | 11.2 | 8.3 |

- **Jefferson.** v1 gives him 48% of MIN's targets. The reason is the floor: every receiver who was not on MIN last
  season (Felton, Jennings, Price, Bartholomew) starts at 0.01. So Jefferson takes the share they should have. M3 cuts him
  to 35%, still above his actual 21% in this game.
- **Felton** had 12 targets. Every model misses him: he had little usage before week 11. This is the limit of a
  usage-only model.
- **Jones and Mason.** M3 moves the wrong way for this game. This season's usage favours Jones, and in this game Mason got
  more. One game cannot judge this. The season-level gain above is the test.
- **Juszczyk** is not in MIN's data; he plays for SF. SF's fullback usage is a separate question, outside this step.

## What this does not show

- Only the share of a given opportunity. The team's pass and run volume is a separate model. In the sims, Jefferson's
  17 to 20 targets come from both too high a share and too many team targets.
- The candidate set is the players who got at least one opportunity in that game. The sim uses the frozen injury report
  instead. A player who was active but got nothing is not a candidate here, so the log losses read lower than in the sim.
- Positions come from the `players` table. A player with no position is scored in group OTHER.
- k was tuned on 2025 (priors from 2024) and tested on 2026 (priors from 2025). One test season.

## Next

1. Put M2, or M3 for carries, into the v1 complete share layer as an experimental arm: in-season counts before the game
   week, plus the cross-team prior. Smoke test, then compare with v1 complete on week 11, game and props graded.
2. A team opportunity volume model (dropbacks and designed runs per game, by game script), since the share fix alone
   leaves Jefferson's team volume too high.
3. An early-usage signal for players like Felton: snap share from the prior game, which nflverse publishes.
