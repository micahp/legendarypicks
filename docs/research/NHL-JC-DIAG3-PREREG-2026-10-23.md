# NHL JC-DIAG3: preregistration for pair-geometry shrink

**Base:** `2cdbe1f3859e5fcf4060c2a698d0e421658e26ca`.

**Status:** Frozen and committed before the JC-DIAG3 provenance gate and all Q1–Q4 calculations.
This is a descriptive analysis of frozen predictions. It fits no predictive model, scores no
candidate, selects no policy, changes no gate, and authorizes no adoption.

## Questions and population boundary

The question is whether +45 candidate pair errors are approximately one through-origin scaled copy
of M0 pair errors, or whether pair-specific structure remains after removing a single global slope.
The hypotheses are descriptive only: a stable slope below one with small, unstructured residuals is
consistent with multiplicative shrink; heterogeneous slopes or structured residuals are inconsistent
with that simple description. Neither result identifies a cause.

The frozen population is exactly 10 development games with leave-one-whole-game-out predictions,
200 rollout starts (172 scored at +45), 2,164 +45 within-team pairs (1,064 Home and 1,100 Away),
and 454,983 eligible one-skater training windows. Horizons are ordinal Image Id increments, not
seconds. No independent tracking population exists on disk. These are not independent adoption data.
Do not claim a validated NHL simulator, predictive skill, or a Legendary Picks probability change.

Only the frozen rollout starts and recorded observations/predictions are inputs. No refit, resimulation,
JC decision rerun, controller change, gate change, or threshold change is allowed. Pairs are unordered
and keyed by sorted, game-period-scoped track IDs within one start/team; there are no cross-game joins
or role/position inferences. For model `m` and horizon `h`, signed pair error in feet is
`e_m(h,i,j) = distance(predicted_i,predicted_j) - distance(observed_i,observed_j)`.

This study-specific statistic is not published by an authoritative source: its pair definition,
frozen prediction support, and estimand are specific to these research artifacts. The evaluator is
needed to make the provenance gate and all per-start/game results reproducible; the values are
computed from the frozen artifacts, not treated as published facts.

## Shared support, weighting, and uncertainty

Use the same 172 JC +45-scored starts at both +15 and +45. At each horizon, a track is common only
when cutoff XY, observed target XY, and recorded M0/M1/M2 prediction XY are finite. A pair is common
when both track IDs are common. Q1's Home and Away support is that team's common pairs. EqualTeam
requires both team cells to be estimable; within each start/team cell its pair observations receive
equal total weight, so each pair weight is `1 / pair_count_in_cell`. Raw pair denominators remain
reported. Do not treat pair rows as independent uncertainty units.

For Home/Away Q1 fits, ordinary pair-weighted through-origin least squares is
`kappa = sum(x*y) / sum(x*x)`, with `x=e_M0`, `y=e_candidate`. For EqualTeam use the same ratio with
the cell-balanced pair weights above. No intercept is fitted. Pearson correlation uses the same
weights as the slope; Spearman is weighted Pearson correlation of midranks; R-squared is the
through-origin form `1 - sum(w*(y-kappa*x)^2)/sum(w*y^2)`. Undefined statistics remain null.

A start/team/model/horizon cell is eligible only with at least three common pairs and a finite,
strictly positive `sum(e_M0^2)` denominator. Report cells and pair rows excluded for each reason.
EqualTeam additionally requires both Home and Away cells in that start. Never drop or trim a game,
start, or outlier. Within an otherwise eligible Q1 cell, finite pairs with `e_M0 == 0` remain valid
OLS observations; report their count and that zero-denominator pairs were not individually excluded.
If the whole cell has a zero denominator, exclude and count all its pair rows. Nonfinite M0 errors
are not expected on the finite common support; count and report any if encountered. Q2 ratios exclude
exact-zero M0 denominators and report the excluded count. For Q1, calculate the pair-pooled estimate over all eligible rows, each game's
through-origin estimate using its eligible rows, and the arithmetic mean of the ten game estimates.
Report all ten game estimates. The equal-game mean is the point estimate for its 95% interval.

Use one common 10,000-draw whole-game bootstrap index matrix for all intervals and estimates, sampled
with replacement from the ten games using `numpy.random.default_rng(20261024)`. Each sampled game
occurrence is a separate cluster occurrence. Give games equal weight; never resample pairs or starts.
Use linear percentile endpoints. Report an interval only with at least 9,500 defined draws; otherwise
report the estimate as undefined for inference and give the valid-draw count. Do not coerce an
undefined ratio or denominator to zero.

## Q1 — through-origin slopes

For Home, Away, and EqualTeam at +15 and +45, compare M1 and M2 against M0 on the shared support.
Report the pair-pooled `kappa`, all ten game-level kappas, equal-game mean and whole-game 95% interval,
Pearson, Spearman, through-origin R-squared, raw pair denominator, eligible start/team cells, and
pair/cell exclusions. EqualTeam uses the cell-balanced weights above. The pair-pooled slope is
descriptive and is not itself the equal-game estimand.

## Q2 — pair-level ratio distribution at +45

On the +45 common support, first report the median of `abs(e_M0)` as the frozen analysis threshold.
For M1 and M2, report the median, first and third quartiles (IQR), and share of pair ratios
`e_candidate/e_M0` in `[0.3, 0.7]` on (a) the full support and (b) pairs with
`abs(e_M0) >= median(abs(e_M0))`. Keep negative ratios in both populations. Exclude only nonfinite
ratios and exact-zero `e_M0`; report counts, including exact zeros. Threshold ties are included.
The median and interval for the `[0.3,0.7]` share use the whole-game bootstrap; IQR quartiles describe
the point-sample ratio distribution. Bootstrap intervals require at least 9,500 defined draws.

## Q3 — structure left after one slope

At +45, separately for M1/M2, define pair residual `r=e_candidate-kappa*e_M0`, where `kappa` is the
Q1 pair-pooled +45 slope for that candidate and group. Use the fixed Q1 slope for all residual bins;
do not re-fit a slope within a bin. Report the equal-game mean residual and 95% interval overall,
then by the fixed JC-DIAG2 observed-cutoff-distance quartiles and by its fixed M0 +1 absolute-error
deciles. Report raw signed candidate-minus-M0 delta beside residual. Within each start/team/bin,
average pair values; average available teams equally within start, starts equally within game, and
games equally. Report pair counts, starts, games, and non-estimable bins. Each bin's cutpoints remain
fixed and are not recomputed in bootstrap draws.

Use the JC-DIAG2 distance cutpoints verbatim (feet): `17.038243596734116`, `25.896550730297974`,
`36.18400154397977`. Use its M0 +1 absolute-error decile cutpoints verbatim (feet):
`0.02013880768063752`, `0.03778431147562884`, `0.057149271788077625`, `0.0772826427731225`,
`0.10184994154651683`, `0.12700537055808211`, `0.16006325254241388`,
`0.2074288029626061`, `0.2889645922798206`. Internal cutpoint ties go to the higher bin. Decile
support requires common +1, +15, and +45 pairs; distance-quartile support requires observed cutoff
and +45 pair coordinates. Both inherited bin definitions were formed on 2,164 pairs; recompute and
assert that support count from the frozen frames before using the cutpoints. The published JC-DIAG2
source hashes and all actual bin counts/cutpoints will be recorded in the result JSON.

## Q4 — stability across games

At +45, report the ten game-level kappas, the ten leave-one-game-out pair-pooled kappas, sign
consistency, and the per-game sign of the equal-team mean residual from Q3's fixed pooled slope.
Report M1/M2 separately and do not calculate p-values. State whether the through-origin relation is
consistent across the ten game clusters or materially depends on one or two games; this is a
descriptive judgment based on the listed values, not a formal test.

## Frozen provenance and stop rule

Before Q1–Q4, verify all eight SHA-256 values and re-read the seven values/assertions in the task
brief, including raw-frame recomputation of +45 pair denominators. Record every source hash, actual
and expected assertion value, and exclusion in deterministic JSON without timestamps or runtime.
On any mismatch, write a failure JSON with `all_assertions_passed: false` and the exact contradiction,
then stop before Q1–Q4. The JC, JC-DIAG, and JC-DIAG2 evaluators/results, controllers, archives, clips,
manifests, Gridiron Physics, production forecasts, and databases remain untouched.

Every finding is descriptive and scores no candidate. The final report will close with what each
result implies for the JC-DIAG shortlist and what independent tracking evidence is needed next.
