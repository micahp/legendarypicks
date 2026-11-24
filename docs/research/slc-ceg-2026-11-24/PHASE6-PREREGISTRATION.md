# SLC-CEG Phase 6 pre-registration: team and player differentiation (challengers on arm C)

Written 2026-11-24, before any Phase 6 score. Phases 2 to 5 unchanged. Code: `scripts/nfl_sequence/ceg_team.py`,
`scripts/nfl_sequence/ceg_opportunity.py`.

## Why this design

Every earlier team or matchup term lost to the league situation baseline (Phase 0 audit, failed-experiments table). So
team terms here are challengers on top of arm C, each scored against C on its own, never a global strength multiplier.

## Team terms (arm E challengers)

For an outcome class c at a play by offense O against defense D in week w of season S:

p_E(c) is proportional to p_C(c) x r_O(c) x r_D(c), where r_T(c) = [(n_T,c + k p_L,c n_T / n_T') / (n_T + k)] / p_L,c ... in
code: the team's rate for c, shrunk to the league rate with pseudo-count k, over the league rate. n_T,c are the team's
counts on that component's opportunities from season S-1 (all weeks) and season S weeks before w. Only data before the
game. A team with no history gets r = 1.

| component | offense term | defense term |
|---|---|---|
| intent (run, dropback, punt, field goal, kneel, spike) | yes | no |
| dropback outcome (sack, scramble, attempt) | yes | yes |
| targeted outcome (complete, incomplete, interception) | yes | yes |

Each component is scored three ways against C on identical plays: offense term only, defense term only (where it
exists), both.

## Player opportunities (arm D)

The step 1 model from `research/slc-v1-conditional-opportunity-2026-11-23` (in-season counts plus a cross-team prior plus
a situational group factor), retuned under the Phase 1 periods: k chosen on 2024 (priors from 2023, factors from
2022-2023), then scored once on 2025 (priors 2024, factors 2022-2024) against the v1 prior-season share. The candidate set
caveat (players with an opportunity in that game) stays and is reported.

## Selection, periods, metrics

- k from {10, 30, 100, 300, 1000}: chosen on 2024 (prior season 2023), then scored once on 2025 (prior 2024). 2026 weeks
  1 to 11 reported as examined.
- Log loss per opportunity, 95% game-bootstrap interval for E minus C (and D minus the v1 share). A term counts only if
  its 2025 interval is below zero.
- Regular season, no penalty plays.
