"""nfl_score_dist.py -- joint home and away score distribution (SPEC A task 4.2).

Pre-registration, written 2026-10-11 BEFORE any run. Changing any rule below after seeing a
result is a new experiment and must be labelled as one in docs/.

WHAT THIS IS
For a game with v1 walk-forward expected points (eh, ea), draw realistic final scores: integers,
real football shapes, ties at the real rate. Win, spread, total and team-total probabilities all
come from these draws. Used by the season simulation (4.1 step 3) and market probabilities (4.5).

METHOD: NEAREST NEIGHBOURS, NO SCORE RESHAPING
Training pool = every REG game of the earlier seasons with (eh, ea, actual home score, actual away
score), where (eh, ea) is v1 walk-forward expected points (fit on earlier weeks of that season
only, never on the game itself).

For a target game: standardize (expected margin, expected total) by the training pool's standard
deviations of those two quantities (pool means subtracted, pool sds divided), take the K nearest
training games by Euclidean distance in that standardized space, and draw one of their actual
(home, away) score pairs uniformly with replacement. Scores are never shifted, rescaled or
rounded; the drawn pair is an actual NFL final score.

TRAINING AND TEST SEASONS
- Training seasons: 2010-2019.
- Test seasons: 2020-2025. Each test season uses training data from all earlier seasons only
  (2010..season-1), so 2020 trains on 2010-2019 and 2025 trains on 2010-2024.
- Leakage rule: the target season is never in its own neighbour pool, and the target game is never
  in its own pool. A test season's own games are also never in a later test season's pool except
  as allowed by the line above.

K GRID AND SELECTION RULE
- Grid: K in {25, 50, 100, 200}.
- Selection: lowest out-of-sample score-pair log loss over 2011-2019, walk-forward (season s is
  scored with pool = 2010..s-1), ties broken to the smaller K. 2010 is training data only: it has
  no earlier season, so it cannot be scored.
- 2020-2025 is never used to choose K.

SCORE-PAIR LOG LOSS, EXACTLY
The sampler is a discrete distribution over score pairs: P(pair) = (n_pair + 1) / (K + V), where
n_pair is the number of the K neighbours whose actual pair equals the pair, and V is the number of
distinct pairs in that pool (add-one smoothing over the pool's observed pairs, so a pair absent
from the K neighbours is unlikely, not impossible). The floor 1/(K+V) is present for every K, so
the comparison is driven by how often the actual pair is among the K neighbours. Log loss is
natural log, averaged over the scored games.

GATE (ship or stop, decided before running)
The candidate is the K chosen above, applied to 2020-2025.
- Win Brier (decisive games only, ties excluded from the Brier and counted): candidate must be no
  worse than the current Normal(projected margin, sigma = 13.295) model. No worse means the
  candidate's Brier is less than or equal to the Normal's.
- Cover and over calibration: candidate's sum of squared bin errors (10% bins) for
  P(home covers spread_line) and for P(over total_line) must be lower than the comparator's. The
  comparator is the bivariate independent Normal: margin ~ N(proj_margin, sd_margin), total ~
  N(proj_total, sd_total), with sd_margin and sd_total fitted on the same training pool by the
  residual sds of actual minus expected margin and total. Bins with fewer than 20 games are
  reported but excluded from the squared-error sum.
- If the gate fails, report it and STOP. Do not tune K on 2020-2025. K is not re-chosen after
  the gate result.
Also reported (no gate): tie frequency predicted vs actual overall and for 2017+ (overtime was
shortened to 10 minutes in 2017), and a probability integral transform histogram of the actual
margin in 10 bins.

API
- sample(eh, ea, rng, n) -> list of (home, away) integer pairs.
- probabilities(eh, ea, spread, total, n=20000, rng) -> dict with p_home_win, p_tie, p_cover,
  p_push, p_over, and the counts they came from. p_home_win is conditional on a decisive result
  (ties excluded from its denominator), matching the published win probability in SPEC A 4.2.
"""
