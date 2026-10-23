# NHL joint movement coherence (JC): preregistration

**Frozen before the JC evaluation.** Research measurement only; no adoption decision.

**Bases:** Legendary Picks `e43c09fe7d1f955794717099f53be3392ee8e6ea`; Gridiron Physics
`896e71e533259b39df6223183ed2b052b9ab7487`.

## Population and boundary

This is a ten-game development study using leave-one-whole-game-out predictions, the existing 200
rollout starts (20 per game), and 454,983 eligible one-skater windows. The ten inspected games are
not an independent population; there are no independent tracking games in this study. JC cannot
license adoption, an NHL simulator claim, or changes to Legendary Picks probabilities. All horizons
below are Image Id suffix increments, not elapsed seconds. The source timebase remains unvalidated.

Use only the already committed M0 (independent), M1 (interaction), and M2 (interaction plus 2D
constraints) predictions. JC is the name of this measurement milestone; M0/M1/M2 retain their
existing meanings. Do not fit or tune a movement policy, feature, constraint, coefficient, threshold,
or success rule. Observed future coordinates are evaluation labels only. No event, outcome, future
position, inferred possession, or cross-game identity may be used as a predictor.

Frozen inputs:

- Rollout-start manifest: SHA-256
  `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de`.
- Existing scenario trajectories: SHA-256
  `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce`.
- Existing one-step comparison: SHA-256
  `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8`.
- Existing fitted fold models: SHA-256
  `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a`.

The group evaluator reads the recorded M0/M1/M2 paths and observed labels for the exact 200 start
IDs in the frozen starts manifest. It does not regenerate movement. Use horizon +1, +15, +30 and +45
ordinal increments only. Every result table must label these as ordinal increments, not seconds.
The one-step endpoint comparator is the existing held-out endpoint prediction at +15 ordinal
increments. Keep its original per-game scores and do not refit it.

## Common scoring population and missing tracks

At a start and horizon, the common IDs are the eligible game-period-scoped skater tracks with valid
finite XY at the observed cutoff and at the observed target, and with a recorded prediction from
each of M0, M1 and M2. The initial cutoff coordinates for these same IDs define their starting
centroids. A missing or invalid observed target is omitted for scoring and never imputed. Missing
labels do not change any generated path. Do not join tracks across games or periods.

A group-scored state requires at least two common skaters from each team. If either team has fewer,
mark the state ineligible for every group metric at that horizon. Report eligible states out of 200,
game clusters represented out of 10, common skater counts, and each metric's exact player/group/pair
counts. Never substitute individual position error for an unavailable group metric. For a horizon
with no eligible state in any game, mark the group estimate and interval unavailable. If any of the
ten games has no eligible state for a metric/horizon, report the available-state descriptive values
and coverage, mark its ten-game interval unavailable, and do not count that measure toward JC.

All measures are computed separately for each model and scored state from the same common IDs.
Distances and errors are in rink-coordinate feet. No physical speed, traction, reaction time,
possession, contact, or 3D mechanic is inferred.

## Frozen group measures

Report per scored state first, then average starts within each game, then give each game equal weight.
The group-scored states are paired across models. Lower errors indicate closer agreement with the
observed group geometry.

1. **Group centroid displacement error, pooled and per team.** For a team or for the pooled two-team
   group, compute each common skater's observed displacement from cutoff to target and the model
   displacement from the same cutoff to its predicted target. The error is the Euclidean distance
   between the corresponding mean displacement vectors. Report the pooled value and each team's
   value; identify teams only as the source's Home/Away labels. Record the common skater count for
   each centroid. The pooled centroid is the primary centroid value for the JC rule.
2. **Team-spacing error.** For each team, compute the mean distance over every unordered pair of
   its common skaters in the observed target and in the predicted target. The state error is the
   absolute difference between those means, averaged equally over the two teams. Report each
   team's pair count and the two-team total. A team contributes only with at least two common
   skaters.
3. **All-pair distance error.** Across every unordered pair among all common skaters from both
   teams, including same-team and opposing-team pairs, calculate the absolute difference between
   predicted and observed pair distance. Report the mean and 90th percentile of these pair errors
   in feet, plus the unique pair count. The mean and P90 are two reported components of one JC rule
   family; both must qualify for that family to count as improved.
4. **Nearest-opponent distance-quantile gap.** For each common skater, find the nearest common
   opponent in the observed target and separately in the model target. At quantiles 0.10, 0.25,
   0.50, 0.75 and 0.90, take the absolute difference between the model and observed quantiles; the
   state value is the equal-weight mean of those five gaps, in feet. Report the skater count used.

No optional shape or Procrustes term is evaluated.

## Individual and group reporting

For each of M0, M1 and M2, report one-step endpoint radial error from the frozen +15 held-out
one-step evaluation alongside free-running endpoint radial error and all four group-measure
families at +1, +15, +30 and +45 ordinal increments (not seconds). Report equal-game means with
95% game-cluster intervals, not bare means. Include paired candidate-minus-M0 differences and
their intervals. The dissociation table must keep individual endpoint accuracy adjacent to group
coherence so an endpoint gain cannot hide a group loss.

For each model/horizon/measure cell, report scored-state count, represented games out of 10, and
the relevant tracked-skater, team, and pair counts. For pair-based measures, include total pairs
and mean pairs per scored state. Use the same group-state denominator for the three models.
Per-team centroid values and team-spacing values are separately visible; do not collapse them into
per-player errors.

Form each game-level statistic by averaging its eligible rollout starts within that game. Compute
95% percentile intervals from 10,000 bootstrap resamples of the ten whole-game clusters, sampled
with replacement and equal game weight. For each candidate-minus-M0 comparison use paired game
values and one common bootstrap draw matrix for all models, horizons and group measures. Freeze the
bootstrap seed at `20261024`. Do not resample players, pairs, or starts as independent clusters.
If one or more game clusters lack a scored state for a cell, follow the missing-coverage rule above
and do not use a partial-game interval for the JC decision.

## Frozen JC decision rule

Evaluate M1 and M2 separately against M0. A candidate is **group-coherent** only if it improves at
least three of these four measure families at both +1 and +45 ordinal increments (not seconds),
with each counted improvement's paired game-cluster 95% interval entirely below zero for the
candidate-minus-M0 difference:

1. pooled group centroid displacement error;
2. team-spacing error;
3. all-pair distance error, requiring both its mean and P90 differences to have intervals entirely
   below zero;
4. nearest-opponent distance-quantile gap.

The candidate's equal-game one-step endpoint radial error at +15 ordinal increments must also
increase by no more than 2% versus M0, defined as `100 * (candidate_mean / M0_mean - 1) <= 2`.
Report the paired 95% interval for that one-step difference as well. Report pass, fail, or
not-estimable exactly as measured. Do not alter this rule after looking at results. This rule is a
development diagnostic, not an adoption gate.

## Frozen output and versioning

Produce deterministic JSON containing source and preregistration hashes, per-scenario group
measurements and counts, per-game aggregates, equal-game estimates, paired and absolute intervals,
coverage, the JC decision, and the declared model/source versions. Exclude wall-clock runtime and
timestamps from the hashed JSON. Serialize deterministically and rerun the evaluator against the
same frozen inputs; the result JSON must be byte-identical and its SHA-256 reported.

The Gridiron viewer retains the existing Observed/M0/M1/M2 panes. Register the new JC enriched
scenario archive under the new immutable ID `jc-2026-10-23-v1`; never overwrite earlier scenario
archives, clips, manifests, or the frozen movement policy/controller. Any new visual-validation
record must identify this preregistration, source archive hash, both code commits, scenario, cutoff,
horizon and uncertainty status. Label recorded positions **observed** and generated paths
**simulated**; the rink-side camera remains a view of observed 2D XY.

No policy is selected or adopted in this milestone. The ten-game sample remains development-only,
and independent tracking is required for any adoption claim.

## Amendment frozen before evaluation: exact spacing-onset profile

The primary reporting horizons and JC decision rule above remain unchanged. To meet the task's
request to locate when players begin separating incorrectly, calculate the same group measures at
every +1 through +45 ordinal increment, not seconds. For every model and step, retain the same
common-label and two-tracks-per-team rules, equal-game weighting, per-state counts and paired
10-game bootstrap intervals. These 45-step profiles are descriptive diagnostics only; they do not
add a success gate or policy-selection opportunity. Report all steps so the first change is not
chosen after inspecting a sparse subset of horizons.

At each step also report two signed direction diagnostics, in feet: (a) each team's mean predicted
within-team pair distance minus its observed mean, plus the equal-team average; positive means the
generated group is more spread out, negative means more compact; (b) for nearest-opponent distances,
the model-minus-observed differences at quantiles 0.10, 0.25, 0.50, 0.75 and 0.90 and their
equal-weight mean, with positive indicating greater separation. These signed quantities diagnose
direction and onset only; they do not replace the four registered error families or enter the JC
decision. For each signed diagnostic, label its earliest step whose unadjusted game-cluster
interval excludes zero as a descriptive onset, not a confirmatory finding; no multiplicity correction
is added.

Use linear interpolation for empirical pair-error P90, nearest-opponent quantiles, and bootstrap
percentile endpoints. This amendment changes no model, input, primary horizon, JC decision rule,
gate, threshold, or coefficient.
