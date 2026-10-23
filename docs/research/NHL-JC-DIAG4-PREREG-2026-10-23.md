# NHL JC-DIAG4: preregistration for additive-offset decomposition

**Base:** `a4f07543704d4170a23f6cd6bfdb7bc4a3578160` (JC-DIAG3, pushed).

**Status:** Freeze this protocol in its own commit before the provenance gate and before any
JC-DIAG4 Q1–Q4 calculation. This is a descriptive analysis of frozen predictions. It fits no
predictive model, performs no refit or resimulation, scores or selects no candidate, and changes no
gate, threshold, promotion rule, production forecast, or database.

## Questions, code need, and population boundary

The question is whether the apparent pairwise negative-error persistence is explained by an
additive prediction offset, or whether persistence remains above the within-start permutation null
after out-of-game additive correction. JC-DIAG3's through-origin slope is not treated as evidence
of proportional contraction; an intercept-and-slope decomposition is required to distinguish the
shared additive level from pair-geometry association.

The evaluator needs to exist because no existing script jointly performs the required provenance
gate, intercept decomposition, additive-correction permutations, and deterministic archival. These
project-specific estimands are not published by an authoritative source; calculate them from the
frozen tracking and prediction artifacts and identify the exact instrument and support.

10 development games, leave-one-whole-game-out predictions within that sample; 200 rollout starts
(172 group-scored at +45); 2,164 +45 within-team pairs (1,064 Home / 1,100 Away, matching the frozen
raw-frame counts); 142 EqualTeam-eligible +45 start/team cells; horizons are ordinal Image Id
increments, **not seconds**; no independent tracking population exists on disk. Nothing here
licenses adoption, a validated simulator claim, or a Legendary Picks probability change.
Descriptive only: no refit of any model, no resimulation, no policy scoring, no candidate selection,
no accuracy or skill claim, no gate, threshold or promotion rule touched. Pairs and starts are not
independent uncertainty units — every interval is a 10-whole-game cluster bootstrap, 10,000 draws,
seed 20261024, equal game weight, shared across all estimates and all models.

Only the frozen rollout starts, archived observed trajectories, predictions, and preceding DIAG2/
DIAG3 result artifacts are inputs. Track IDs are scoped to a frozen game-period-start and team;
never join start IDs or athlete identities across games. Pair rows are unordered pairs of the same
two common track IDs at the compared horizons. Missing/nonfinite coordinates are excluded under the
frozen eligibility rules and reported; no future target is used to fit a movement model.

## Shared support, weighting, and uncertainty

For each horizon in `{15, 30, 45}`, construct signed pair error
`e_m(h,i,j) = predicted pair distance - observed target pair distance` in feet for M0, M1, and M2.
Use the finite common pair support available to all three models. A start/team cell follows the
JC-DIAG3 eligibility rule: at least three common pairs and positive `sum(e_M0^2)`. Home and Away
use equal weight per pair. EqualTeam gives each eligible
start/team cell total weight one (pair weight `1 / cell_pair_count`) and requires both team cells
for that start. The intercept fit as a whole also requires positive weighted centered variance in
M0 error. Report raw and fitted pair counts, start/team cells, starts, represented games, and
exclusions by reason for every fit.

For game-level summaries, first apply the same cell and pair weights within a game, then give each
game equal weight. Use a single 10,000-draw whole-game bootstrap index matrix from
`numpy.random.default_rng(20261024)`, shared across every estimate. Sample the ten games with
replacement; each sampled occurrence is a separate cluster. Use linear percentile 2.5th and 97.5th
endpoints. Report an interval only when all ten game clusters contribute a defined value in at
least 9,500 bootstrap draws; otherwise report the undefined status and valid-draw count. Do not
resample pairs or starts, and do not replace undefined values with zero. Use a separate permutation
RNG, also seeded `20261024`.

## Q1 — intercept-and-slope decomposition

For every horizon `{15, 30, 45}`, group `{Home, Away, EqualTeam}`, and candidate `{M1, M2}`, fit
weighted least squares with an intercept:

`y = e_candidate = a_h + kappa_h * x`, where `x = e_M0`.

Use the support and weights above. Compute `kappa = sum(w*(x-xbar)*(y-ybar)) / sum(w*(x-xbar)^2)`,
`a = ybar - kappa*xbar`, and centered `R2 = 1 - sum(w*(y-a-kappa*x)^2) /
sum(w*(y-ybar)^2)`. Report pooled coefficients, centered R2, equal-game means and whole-game
intervals, pair/start/cell/game counts, all ten per-game fits, and all ten leave-one-whole-game-out
fits. A non-estimable fit remains null with its reason and support counts. No outliers are trimmed.

For context, report each horizon's mean signed pair error for M0 itself and each candidate using the
same cell weighting and equal-game estimand. M0's +45 signed-error level is the reference for
distinguishing shared state error from candidate-specific additive drift.

## Q2 — bias removed by each parameterization

For each horizon, group, and candidate, report the raw mean signed pair error, residual mean after
the matching through-origin Q1 slope, and residual mean after this study's full-support intercept
fit. Recompute the through-origin estimate from the frozen support and assert agreement with
JC-DIAG3 at +15/+45 where the estimands match; calculate it from the same frozen support at +30.
Apply the full-data coefficients fixed in Q1 to every game; do not refit inside games or bins.
Report equal-game estimates and whole-game intervals for each mean.

Define share of mean bias removed as
`1 - abs(equal_game_mean_corrected) / abs(equal_game_mean_raw)`.
Positive values mean smaller absolute mean bias, zero means unchanged, and negative values mean
larger absolute mean bias. Report the same game-bootstrap interval; return null if the raw equal-game
mean is zero. This is a descriptive decomposition, not a selection criterion.

## Q3 — additive correction and pair-level negative-mass persistence

The primary test is the JC-DIAG2 P1 transition `+15 -> +45`. Also report the two preregistered
adjacent transitions from JC-DIAG2 P2 (`+15 -> +30` and `+30 -> +45`) to show the horizon-specific
pattern. Do not add a `+1 -> +15` transition or redefine P1. Use the same common stable pair IDs at
both horizons and the DIAG2 minimum of three pairs per start/team cell.

For each cell and model, reproduce P1 exactly: later negative-error mass is
`max(-e_later, 0)`; observed share is that mass on pair IDs whose earlier signed error is negative,
divided by all later negative mass in the cell. The permutation null shuffles the later signed-error
multiset across stable pair IDs within that start/team cell and recomputes the same share. Use
10,000 shuffles per start/team cell, a separate RNG seeded `20261024`, and one common permutation
map across M0, M1, M2, raw errors, and both corrected variants. A zero negative-mass denominator is
not estimable, not zero. EqualTeam averages the Home and Away cell shares equally within a start
only when both are estimable; average starts equally within game and games equally. Record support
and exclusions for every variant.

Run raw M0/M1/M2 and two M1/M2 corrections:

1. **Primary, out-of-game correction.** For each held-out game, horizon, and candidate, estimate a
   team-by-horizon signed-error offset from the other nine games: take each training game's
   equal-start mean pair error for Home and Away separately, then average those nine game means
   equally. Subtract the held-out game's corresponding team/horizon offset from every pair error
   in that start/team cell. No start IDs are joined across games. Also compute the single
   EqualTeam game-level offset from the other nine games. Compare the two team-specific offsets
   with that EqualTeam offset using an absolute tolerance of `1e-12` feet. If both match, report
   the shared value and explicitly state the identity; do not present them as independent
   evidence. Otherwise report the distinct offsets and their difference.
2. **In-sample-at-cell upper bound.** For each evaluated start/team cell and candidate/horizon,
   estimate the offset as that same cell's own mean signed pair error and subtract it from every
   pair in that cell. This deliberately uses the evaluated cell's pair outcomes, is not
   out-of-sample at the cell level, and must be labeled as an upper-bound sensitivity. It removes
   the cell mean by construction; do not interpret it as a deployable correction or independent
   evidence.

For both corrections, subtract the applicable offset from both earlier and later candidate errors
before computing observed and permuted shares. For each transition, candidate, and correction,
report observed share, permutation-null mean, and observed-minus-null gap with a paired whole-game
bootstrap interval. Also report raw P1 observed and null shares for M0/M1/M2. Bootstrap the
per-game EqualTeam means with the shared game-index matrix; keep observed and null paired within
each game draw. State whether the out-of-game correction brings observed persistence to its null.
Treat the in-sample-at-cell result only as an upper-bound reference.

## Q4 — location and heterogeneity of the additive level

Using the full-support +45 EqualTeam intercept fits:

- Report the distribution (min, quartiles, median, and max) of each start's residual mean, where
  residuals are `e_candidate - (a + kappa*e_M0)` and each start mean gives Home/Away equal weight
  after averaging pairs within each cell. Report the between-start variance share of total pair
  residual variance; calculate the variance decomposition with equal start weight, equal team
  weight within start, and equal pair weight within cell. This is descriptive, with no test.
- Report the ten per-game intercepts `a_h` for each horizon and candidate, plus their equal-game
  means and whole-game intervals.
- Bin +45 intercept-fit residuals by the frozen JC-DIAG2 observed-distance quartile cutpoints
  `17.038243596734116`, `25.896550730297974`, and `36.18400154397977` feet and by the frozen M0 +1
  absolute-error decile cutpoints
  `0.02013880768063752`, `0.03778431147562884`, `0.057149271788077625`,
  `0.0772826427731225`, `0.10184994154651683`, `0.12700537055808211`,
  `0.16006325254241388`, `0.2074288029626061`, and `0.2889645922798206` feet. Do not refit
  cutpoints. For these bins, use each individually eligible +45 start/team cell under the
  JC-DIAG3 minimum-pair and M0-denominator rules, then average represented team cells equally
  within start/bin; do not require both teams to appear in a bin. For the M0 +1 deciles, additionally
  require the pair to be common at +1, +15, and +45. This preserves the frozen DIAG3 support for the
  raw distance-gradient comparison. Report cell/pair/start/game counts and equal-game means with
  whole-game intervals for the intercept residual, raw candidate pair error, and raw
  candidate-minus-M0 signed delta. State whether the raw distance gradient survives the intercept
  fit; describe it without causal attribution.

## Provenance gate and stop rule

Before Q1, verify all eight frozen source hashes pinned by JC-DIAG3, plus the JC-DIAG3
preregistration and result hashes. Assert the published JC-DIAG3 Q1/Q2/Q3 values, intervals,
support and exclusions, including the ten-game negative residual signs; assert JC-DIAG2 P1's
EqualTeam observed/null values; and independently recompute the +45 Home/Away denominators from
the frozen raw frames. Use the expected values and tolerances in the task brief. Record expected
and actual values, tolerances, source hashes, cutpoints, exclusions, and assertion status in
timestamp-free JSON. `--gate-only` must not calculate Q1–Q4. On any mismatch or missing input, write
failure JSON with `all_assertions_passed: false`, state the contradiction, and stop before Q1–Q4.

The JC, JC-DIAG, DIAG2, and DIAG3 evaluators and result JSONs, controllers, archives, clips,
manifests, Gridiron Physics, production forecasts, and databases remain byte-untouched. No new
data or dependency will be added. Results are descriptive on the ten-game development sample; no
adoption, validated simulator, or probability-change claim is permitted.

## Reproduction and archive

The evaluator will expose `--gate-only` and `--output`; full-run JSON is timestamp-free. After the
gate passes, run Q1–Q4 once and rerun to a fresh path with byte-identical `cmp`. Report exact
commands, file line counts, base and both commit SHAs, clean status, and the remote branch SHA.
