# NHL JC-DIAG2: preregistration for pair-level spacing persistence

**Base:** Legendary Picks `46f23ad691d0da1e6841f41f86f25e4bad8d7af8`.

**Status:** Frozen before the new provenance gate and P1–P4 calculations. This is descriptive
attribution only. It scores no candidate, selects no policy, changes no gate or coefficient, and
does not authorize adoption. The milestone name is **JC-DIAG2**, not M3.

## Questions and population boundary

The question is whether negative within-team pair-distance errors at longer horizons persist on
the same unordered pairs, migrate across pairs, or concentrate on pairs with large one-step M0
errors. All analyses use the ten already inspected development games and their frozen recorded
M0/M1/M2 trajectories. No fitting, resimulation, JC decision rerun, policy/controller change,
threshold change, or model selection is permitted. Future observed coordinates are labels only.
Track IDs are scoped to their frozen game-period-start; no cross-game or cross-period joining is
allowed. Use feet in the source rink XY plane and ordinal Image Id increments, not seconds.

The JC-DIAG population is 10 development games, leave-one-whole-game-out predictions, 200 rollout
starts (172 group-scored at +45), and 454,983 eligible one-skater training windows. There is no
independent tracking population on disk. Nothing here licenses adoption, an NHL simulator claim, or
a Legendary Picks probability change.

Frozen sources and expected SHA-256 values are the set already pinned by
`attribute_joint_coherence.py`: JC results
`0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c`, movement comparison
`1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8`, fold models
`194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a`, scenario archive
`a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce`, rollout starts
`07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de`, and JC-DIAG preregistration
`c9e3da3ca12ff5197e3ed5b9eed9775548a85b6c427d60465641d28ac1c5bd4c`. The committed JC-DIAG
results JSON, SHA-256
`f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c`, is additionally pinned as
the source for the published attribution scalars checked before P1–P4.

The task names `results/rollout_starts-2026-10-23.json`; that path is absent in this worktree. The
reproducible start manifest used by the frozen JC evaluator is
`/root/lp-research-data/nhl-multi-agent-movement-2026-10-23/rollout_starts.json.gz`, pinned to the
hash above. The evaluator must read that exact file and fail on a hash mismatch. All source files
and the external normalized-data directory are read-only.

## Pair definition and shared aggregation

For a frozen start, team, unordered pair of game-period-scoped track IDs `{i,j}`, model `m`, and
horizon `h`, define signed pair error

`e(m,h,i,j) = distance(predicted_i, predicted_j) - distance(observed_i, observed_j)`.

Negative error means the model's pair is more compact than observed; positive means more spread.
At each endpoint, a track is common only when its cutoff XY, observed target XY, and recorded M0,
M1, and M2 target XY are all finite, matching the JC evaluator's frozen support. A pair is eligible
for a transition only if both IDs are common at both endpoints. Pair identity is the sorted pair of
track IDs within that one start and team.

For start-level summaries, first average eligible pair observations within a start and team. For an
equal-team start summary, average Home and Away team values with equal weight, requiring both team
values. Average eligible starts within each game, then give each of the ten game clusters equal
weight. Report raw pair counts, eligible start/team counts, represented games, and non-estimable
counts. Bootstrap intervals are unavailable if any of the ten games has no eligible value for that
cell; report the observed coverage and descriptive estimate without presenting a partial-game
interval.

Use one common 10,000-draw whole-game bootstrap index matrix for every estimate, difference, and
contribution share. Sample the ten games with replacement and equal game weight. Use NumPy
`default_rng(20261024)` and linear interpolation for percentile endpoints. Never resample pairs,
starts, or teams as independent clusters. For ratios, an interval is reported only when at least
9,500 draws have a valid denominator; count unavailable draws and leave a ratio undefined rather
than replacing it with zero.

## P1 — within-start pair persistence, +15 to +45

For each JC +45-scored start and each team, take unordered pairs common to +15 and +45. Analyze M0,
M1, and M2 as separate descriptive paths. For each pair let `e15` and `e45` be its signed errors.
The later-horizon negative-error mass is

`D45 = sum_p max(-e45_p, 0)`.

The persistent negative-mass share is

`S15→45 = sum_p [max(-e45_p, 0) * I(e15_p < 0)] / D45`.

This weights a pair by its contribution to the +45 under-spread magnitude; it is not the fraction
of pair IDs that remain negative. Report `S15→45` for Home, Away, and the equal-team aggregate with
whole-game intervals. If a start/team has fewer than three common pairs, or `D45 == 0`, mark its
statistic non-estimable and report the count and reason. Exclude only that start/team cell; the
equal-team statistic requires both team cells to be estimable.

### Within-start permutation null

For each eligible start/team/transition, keep the previous-horizon signed errors fixed and randomly
permute the later-horizon signed-error values across the same unordered pair IDs. This preserves
the later error multiset and its total negative mass while breaking its association with which pair
was negative earlier. Use 10,000 permutations per start/team/transition. Generate one permutation
index draw per start/team/transition and apply that same index draw to M0, M1, and M2 (common random
numbers); seed the permutation generator with `20261024`, separate from the game bootstrap RNG.
The null estimate for a start/team/model is the mean persistent share over those 10,000 shuffles.
Aggregate the null with the same start/team/game weights as the observed statistic. Report observed
share, mean permutation-null share, and the paired observed-minus-null difference, with the common
whole-game bootstrap interval for each. A positive difference means persistence exceeds the
within-start random-assignment reference; it does not establish a causal mechanism.

## P2 — adjacent-horizon persistence

Repeat the P1 observed and permutation-null estimators for +15→+30 and +30→+45, using pairs common
to both endpoints of each transition, on the same 172 starts that are JC group-eligible at +45.
Keeping the +45 cohort fixed prevents horizon comparisons from changing the start population.
Apply the same minimum three-pair rule, `D_later > 0` rule, team summaries, game aggregation,
permutation count/seed, and bootstrap matrix. Report the two
adjacent-transition shares, null shares, observed-minus-null differences, support, and intervals
alongside P1's +15→+45 result. Describe the direction from the point estimates as rises, falls, or
is flat; show intervals and their overlap descriptively. Do not fit a slope or report a trend-test
p-value.

## P3 — baseline-error deciles

Use only the 172 starts JC group-eligible at +45 and pairs common to +1, +15, and +45 for all
observed and M0/M1/M2 paths, so the +15 and +45 comparisons use the same pair identities. For each
pair compute its own one-step M0 baseline error
`b = abs(e(M0,+1))`. Define ten bins from the pooled empirical deciles of `b` over this eligible
pair population using linear (type-7) quantiles. Assign values equal to an internal cutpoint to the
higher bin (`searchsorted(..., side="right")`); preserve and report the numeric cutpoints and any
empty bins. Bins are descriptive and are not refit in bootstrap draws.

At +15 and +45, for M1 and M2 separately, report per decile: pair count, scored starts, represented
games, mean signed-error delta `e(candidate,h) - e(M0,h)`, and mean absolute-error delta
`abs(e(candidate,h)) - abs(e(M0,h))`, each equal-team/equal-start/equal-game aggregated with the
whole-game interval. Positive absolute-error delta means larger error than M0. Use the same
within-start/team/bin estimator: average pairs within each start/team/bin, then average the team-bin
means equally across teams represented in that start/bin. Record the represented team cells; a
missing team-bin is unavailable and is never filled with zero. Then average represented starts
within game and games equally. Raw pair counts remain visible and are not the independent
uncertainty unit.

For the share of total positive absolute-error delta, weight each eligible pair by
`1 / (10 * starts_in_game * 2 * eligible_pairs_in_start_team)` and sum only positive pair deltas.
For a bin, divide its weighted positive contribution by the positive contribution over all bins.
In each bootstrap draw, treat every sampled game occurrence as its own cluster occurrence and
recompute weights with that occurrence's number of eligible starts. Recompute the share in each
whole-game bootstrap draw; report a percentile interval only with at least 9,500 defined draws.
Also report the count of pairs with exactly zero M0 one-step error and
the candidate's +15/+45 deltas on that exact-zero group versus the nonzero group. “M0 got right”
means exact zero signed pair error, with no tolerance introduced after seeing results; the deciles
show the broader gradient among nonzero errors. If exact-zero support is empty, state that it is
not estimable.

Compare +15 with +45 descriptively on the common three-horizon pair support. State whether the
candidate's later absolute-error deterioration appears in low-, middle-, high-baseline-error bins,
or across them, and whether that pattern changes with horizon. Do not interpret deciles as player
roles or causal strata.

## P4 — observed cutoff-distance quartiles

For each of the 172 +45-scored starts and each team, use pairs common to the cutoff and +45
target/model support. Define
each pair's baseline distance as the Euclidean distance between its two **observed cutoff** XY
coordinates from the frozen initial state. Pool these eligible distances and define four quartiles
using linear (type-7) quantiles; assign values equal to an internal cutpoint to the higher quartile.
Keep and report the cutpoints. This is a pair-distance split only; do not infer roles, lines,
positions, or attack direction, and do not use jersey numbers or player shape.

By quartile, for M1/M2 at +45 report pair count, scored starts, represented games, mean candidate-minus-
M0 signed-error delta, mean candidate-minus-M0 absolute-error delta, and the equal-game weighted
share of total positive absolute-error delta. A quartile's contribution numerator is its positive
weighted sum; its share denominator is the positive weighted contribution over all four quartiles.
Use the P3 weighting, aggregation, bootstrap, and valid-ratio rules. Report the exact
source-coordinate denominator and any non-estimable quartile.

## Provenance gate and implementation boundary

Before calculating P1–P4, hash-verify the frozen input set pinned by the previous evaluator and the
additional committed JC-DIAG results JSON. Re-assert the task-brief values and intervals at these
frozen JC-DIAG fields: +45 M1 and M2 signed pair error; +45 M1 individual radial gain; +15 M1 Home
signed pair bias; and the +45 Home and Away pair counts and their total. The exact expected values
are fixed by the DIAG2 brief. On any mismatch, stop before P1–P4 and report the exact field, actual
value, and expected value. Record all source hashes, assertions, methods, exclusions, cutpoints,
and per-start/per-game denominators in deterministic JSON without timestamps or runtime.

Use a new evaluator and new result artifact. Keep the JC-DIAG evaluator and result JSON byte-
untouched; keep controller `252ed6d9`, archives `bc91d1610de5` / `43a81ff70918`, clips, manifests,
Gridiron Physics, and all production state untouched. The report opens with the population and
adoption boundary above, presents P1–P4 in order, and closes with what each result implies for the
JC-DIAG shortlist and what additional data are needed. Every finding is descriptive and scores no
candidate.
