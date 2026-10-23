# NHL JC-DIAG: preregistration for joint-coherence error attribution

**Frozen before attribution measurements.** Descriptive attribution only. This does not score a
candidate, select a model, alter the JC decision, or authorize adoption. Do not call this milestone
M3; its name is JC-DIAG.

**Base:** Legendary Picks `f147e67fa42b3f878674db6b9f018150934a37ed`.

## Population and boundary

Use only the ten-game development population and the exact 200 rollout starts in the committed JC
evaluation. The frozen JC eligibility rule determines common tracks and group-scored states at each
horizon. At +45, report the complete-case population from that artifact (172 scored starts across
the ten development-game clusters). The original one-skater training population is 454,983 eligible
windows. All horizons are ordinal Image Id suffix increments, not seconds. There is no independent
tracking population on disk. Nothing in this analysis licenses adoption, an NHL simulator claim, or
a Legendary Picks probability change.

Read the frozen JC result, comparison, fold-model, and scenario-archive artifacts, plus the external
normalized-data inputs, read-only. Use only recorded M0/M1/M2 trajectories and observed target
coordinates. Do not refit, re-simulate, alter policies or controller behavior, alter thresholds or
gates, or apply the JC decision rule again. Future coordinates are labels only. Do not join tracks
across games or periods. Keep all findings descriptive; do not rank or select candidates.

The published JC evaluator does not expose a defense/forward role in its common-track records.
Q1 may use only an explicit, source-provenanced D/F role carried by the frozen cutoff track record.
Do not infer roles from jersey numbers, team shape, events, identities, future frames, external
rosters, or model outputs. If the frozen records contain no such explicit label, mark all role-pair
cells unavailable, report the exact field/schema check in the result, and continue with the
team-split analysis. A missing role is not a zero or a guessed class.

## Shared aggregation and uncertainty

Use the same paired set of starts and common observed/model track IDs as the JC result at each
horizon. A pair metric is first computed within a scored start. Average starts within each game,
then give each of the ten games equal weight. For pair-based summaries, average pair observations
within the applicable cell and start before the game aggregation; report raw pair counts, scored
starts, and represented-game coverage so the weighting is auditable.

For estimates and candidate-minus-M0 differences, use 10,000 whole-game cluster bootstrap draws,
sampling the ten game clusters with replacement and equal game weight. Use the JC seed `20261024`,
one common draw matrix for all reported metrics, and linear interpolation for percentile endpoints.
Never resample pairs or rollout starts as independent clusters. A full ten-game interval is reported
only when every game contributes an eligible observation to that metric cell. Otherwise provide the
available descriptive values and coverage, and label the full-population interval unavailable.

All distances and errors are in rink-coordinate feet. Signed pair-distance error is predicted
distance minus observed distance; positive means the model over-spreads that pair. Signed axis
errors use predicted absolute coordinate separation minus observed absolute coordinate separation.
Positive signed error indicates greater model separation on that axis. Absolute error is the
magnitude of the corresponding signed error. Candidate-minus-M0 differences are paired on the
same start, cell, and game. Include M0 as the reference distribution for Q1-Q3.

## Q1 — decompose team-spacing error

At each primary JC horizon (+1, +15, +30, +45 ordinal increments, not seconds), for M0, M1, and M2,
compute signed bias and absolute error in within-team pair distances. Report:

- the marginal pair-type cells: defence-defence, defence-forward, and forward-forward;
- the marginal team cells: Home and Away;
- the pair-type by team cross-cells where explicit role labels support them;
- the candidate-minus-M0 paired difference in absolute error for each estimable cell.

Within each start and cell, average signed pair errors over the cell's unordered pairs; report this
signed bias, its absolute value (the cell's team-spacing error), and mean absolute per-pair error
separately. Apply shared equal-start-within-game, equal-game aggregation and whole-game intervals.
Report exact pair counts and scored starts for every cell. If a cell is empty in a game, its
ten-game interval is unavailable; if it is empty in the population, mark it non-estimable. Describe
sparse cells from their measured pair and game coverage rather than silently pooling or inventing
role labels.

## Q2 — signed pair-error distribution

At +1 and +45 ordinal increments (not seconds), for every model, report within-team pair signed
error distributions: over-spread share (`error > 0`), under-spread share (`error < 0`), exact-tie
share (`error == 0`), and linear empirical quantiles at 0.10, 0.25, 0.50, 0.75, and 0.90. Also
report the same descriptive pair distribution at +2 solely to reconcile the existing preregistered
signed-mean diagnostic; +2 is not a primary horizon and does not enter a decision. For each start,
calculate shares and quantiles from its eligible pairs, average start summaries within game, then
give each game equal weight and use the shared game-cluster bootstrap for intervals. Include pair
counts and start/game coverage.

Report the raw pair and start counts. Use these distributions to assess whether compact
signed *mean* bias at the early diagnostic step can coexist with high absolute error: report the sign
balance, median, tails, and absolute-error distribution together. If they do not identify the
reconciliation, say that this population cannot resolve it. Do not treat the preregistered +2 signed
mean as a primary horizon or a candidate score.

## Q3 — rink-axis decomposition

At each primary horizon and for each model, for each within-team pair define
`x_error = abs(predicted_delta_x) - abs(observed_delta_x)` and
`y_error = abs(predicted_delta_y) - abs(observed_delta_y)`, using source rink XY axes. Report the
signed and absolute x/y errors, plus paired candidate-minus-M0 absolute-error differences, with the
same equal-team, equal-start, equal-game aggregation and game-cluster intervals as Q1. Report pair
and state counts. Label axes as source X/Y unless the frozen source metadata independently
establishes longitudinal/lateral direction; do not infer an attack-direction transform. This is an
axis-projected separation diagnostic, not an additive decomposition of Euclidean distance or a
physical explanation by itself.

## Q4 — concentration of +45 team-spacing loss

For each candidate separately, define each +45 start's team-spacing loss as candidate absolute
team-spacing error minus M0 absolute team-spacing error. Average starts within game, then weight
games equally. List all ten per-game deltas and signs; report the number positive, negative, and
zero. Report the leave-one-game-out range of the equal-game mean.

For game concentration, report the sum of the three largest positive game deltas divided by the
sum of all positive game deltas, with the numerator, denominator, and net signed gap. Also report
the top-three-positive sum divided by the net gap when that ratio is defined, so offsetting negative
games remain visible rather than hidden. If a denominator is zero or nonpositive, say the share is
undefined.

For start concentration, use the exact +45 group-scored starts. Rank starts by their unweighted
team-spacing loss, highest first; the worst decile is the largest `ceil(0.10 * N)` starts. For
contribution calculations, weight a start by `1 / (10 * starts_in_its_game)` so start contributions
sum to the equal-game gap. Report the worst-decile contribution divided by total positive weighted
loss and, if defined, by the net weighted gap. Recompute the equal-game mean after removing those
starts, re-averaging within each game; report whether its sign changes and the retained coverage.
Give the equal-game net gap and both concentration shares 95% intervals using the shared
whole-game bootstrap. In each draw, recompute the positive-game top-three share from the sampled
game deltas (duplicate draws count as separate clusters); for start concentration, carry every
start in each sampled game occurrence, recompute the worst decile with `ceil(0.10 * N_draw)`, and
recompute its equal-game contribution share. A draw with a zero or invalid denominator is
unavailable and counted; report an interval only when at least 9,500 of the fixed bootstrap draws
have a defined statistic. Do not replace undefined ratios with zero.

## Q5 — individual/group dissociation at +45

Use the exact common track IDs in each +45 JC-scored start. Per start and model, compute individual
rollout endpoint radial error as the mean Euclidean distance between predicted and observed target
coordinates across those common tracks. Define individual gain as `M0 radial error - candidate
radial error` (positive is lower radial error) and group-spacing loss as the Q4 start-level delta
(positive is worse spacing).

For M1 and M2 separately, report the pooled per-start Spearman correlation between gain and loss,
using average ranks for ties, with a game-cluster bootstrap interval. Each bootstrap resample draws
whole games; include every scored start for each selected game occurrence, including duplicate game
draws. If either vector is constant in a draw, that draw is unavailable; report unavailable-draw
count and do not silently substitute a value. Also report all four paired sign quadrants for gain
and loss (both positive, gain only, loss only, neither), with start and game coverage and
game-cluster intervals. Interpret the pattern descriptively as within-start co-occurrence or
between-start composition; do not impose a pass/fail threshold or claim causality.

## Q6 — archived mechanism screen

Inspect the frozen JC frame and comparison artifacts read-only for explicit per-player or per-pair
labels identifying M2 constraint activity at the corresponding step. An aggregate constraint count
without IDs is not a per-pair activity label. If explicit labels exist, report their recorded
definitions, coverage, and the descriptive association between affected labels and the Q1/Q2
worsening pairs. If labels are absent or cannot be linked without inference, state exactly that the
archive does not support this attribution. Do not infer touches from displacement, re-simulate,
create labels, or change the frozen policies.

## Frozen artifact checks and outputs

Before attribution calculations, a new evaluator must verify the SHA-256 of
`research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json` is
`0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c`, then recompute and assert
the seven scalar values enumerated in the task brief (although the brief calls them six): the three
one-step radial means, the M1/M2
+45 team-spacing paired deltas, the M1 +45 pooled-centroid paired delta, and the M2 +1 team-spacing
paired delta. On any mismatch, fail closed before Q1-Q6 and report the mismatch.

The deterministic, versioned JSON records the preregistration and all source hashes; provenance
assertions; exact method/schema availability; per-start and per-game measurements and denominators;
equal-game estimates and paired game-bootstrap intervals; concentration and dissociation outputs;
and mechanism-label availability. Exclude timestamps and runtime. Re-run the evaluator to a fresh
path and require byte-identical results. Report both JSON SHA-256 values.

The report starts with the development-only population and adoption boundary, gives Q1-Q6 in order,
and ends with a ranked shortlist of possible mechanisms, each tied to a reported measurement that
supports or weakens it. If the ten-game data cannot distinguish a mechanism, specify the additional
measurement needed. This shortlist is diagnostic, not a candidate ranking or model-selection result.
