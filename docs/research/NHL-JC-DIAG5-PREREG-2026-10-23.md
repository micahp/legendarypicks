# NHL JC-DIAG5 preregistration: persistence in candidate-minus-M0 deltas

**Base:** `1dcd616906ee39ff46d4d117bd93ff627b24687e`  
**Branch:** `research/nhl-multi-agent-movement-2026-10-23`  
**Status:** frozen before the DIAG5 provenance gate and all DIAG5 Q1–Q5 calculations.

## Scope and code/value questions

The evaluator is necessary because the repository has no frozen evaluator for candidate-minus-M0
pair deltas, this run's fail-closed source gate, or their registered uncertainty summaries. The
delta, persistence, and clustering quantities are project-specific descriptive estimands; no
authoritative published source defines these derived quantities. This run computes them only from
the already frozen DIAG4 development artifacts.

This is a read-only diagnostic of M0, M1, and M2 outputs. It will not refit, resimulate, rescore a
policy, select a candidate, create labels, change a gate or threshold, or modify any frozen artifact.
The only new artifacts are this preregistration, one evaluator, one result JSON, and one report.

## Frozen population statement

Same frozen population as DIAG4: 10 development games, leave-one-whole-game-out predictions, 200 rollout starts (172 group-scored at +45), 2,164 +45 within-team pairs (1,064 Home / 1,100 Away), 142 EqualTeam +45 start/team cells; horizons are ordinal Image Id increments, **not seconds**; no independent tracking population; pairs and starts are not independent — every interval is the same 10-whole-game cluster bootstrap, 10,000 draws, seed 20261024, equal game weight, one matrix shared across all estimates.

## Source gate, fixed before Q metrics

Before calculating Q1–Q5, the evaluator will record expected and actual SHA-256 for each exact path
below. Missing files or any mismatch fail closed: JSON records the named missing/mismatched paths,
`all_assertions_passed` is false, and no Q1–Q5 result values are computed or emitted.

| Name | Exact frozen path | Expected SHA-256 |
|---|---|---|
| `jc_results` | `research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json` | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` |
| `fold_models` | `research/nhl-multi-agent-movement-2026-10-23/results/fold_models-bc91d1610de5.json` | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` |
| `movement_comparison` | `research/nhl-multi-agent-movement-2026-10-23/results/movement_comparison-bc91d1610de5.json` | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` |
| `scenario_archive` | `research/nhl-multi-agent-movement-2026-10-23/results/scenario_archive-bc91d1610de5.json.gz` | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` |
| `rollout_starts` | `/root/lp-research-data/nhl-multi-agent-movement-2026-10-23/rollout_starts.json.gz` | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` |
| `jc_diag_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-attribution-jcdiag-2026-10-23-v1.json` | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` |
| `jc_diag2_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag2-pair-persistence-2026-10-23-v1.json` | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` |
| `jc_diag3_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag3-pair-shrink-2026-10-23-v1.json` | `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd` |
| `jc_diag4_preregistration` | `docs/research/NHL-JC-DIAG4-PREREG-2026-10-23.md` | `66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0` |
| `jc_diag4_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag4-additive-offset-2026-10-23-v1.json` | `cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947` |

After hashes pass, re-assert DIAG4's registered provenance values and frozen support: its M1/M2
team×horizon P1 observed, null, gap, and 95% interval; M0 raw P1 observed and null; DIAG4 +45
EqualTeam M1 intercept and κ with support 2164 / 1966 / 284 / 142 / 10; DIAG3 +45 EqualTeam M1
equal-game and pair-pooled κ; raw-frame counts 1064 + 1100 = 2164; and population counts 10 / 200 /
172. The exact target values and tolerances are the values registered in the DIAG5 brief and the
hash-pinned DIAG4 evaluator/report. Re-run DIAG4's 22 post-compute frozen-method checks from the
frozen source arrays and in-memory DIAG4 helper functions. Do not call the DIAG4 full runner or write
to its outputs. Any failed assertion stops all DIAG5 Q calculations.

## Shared uncertainty and support rules

- Games are the resampling unit. Generate one 10,000 × 10 game-index matrix with seed `20261024`
  and reuse it for every game-cluster interval and estimate. Report equal-game means and percentile
  95% intervals with NumPy's linear quantile convention. Do not treat pairs or starts as independent.
- Persistence nulls use 10,000 within-start/team permutations per transition and cell, seed
  `20261024`, preserving the later vector's multiset. Hold the earlier sign vector fixed. Reuse the
  same permutation index matrix for M1 and M2 for each transition/start/team cell.
- A start/team cell needs at least three common pair IDs for a transition. A persistence cell also
  needs positive later negative mass. EqualTeam starts require both Home and Away cells to be
  estimable. Report all exclusions and zero-mass counts. Do not join pair/start identifiers across
  games.
- Within each game, average eligible starts equally; within a start, average Home and Away cell
  statistics equally. Average games equally. Bootstrap observed, null, and paired observed-minus-null
  game values using the shared matrix.
- No p-values. Describe an estimate as above its permutation null only when its whole-game 95% gap
  interval is entirely positive; this is a descriptive rule, not a hypothesis-test claim.

## Q1 — construct and describe candidate-minus-M0 deltas

At each horizon `h ∈ {15, 30, 45}`, on pair IDs present for M0 and the candidate in that same
game/start/team/horizon, define `d_candidate,h = errors_ft[candidate] - errors_ft[M0]`. Candidate
means M1 and M2 are evaluated separately. Pair identity is scoped to its original game/start/team;
never match identifiers across games. For horizon-level summaries, use cells with at least three
common pairs; EqualTeam requires both team cells.

For each candidate and horizon, report the EqualTeam mean signed delta with per-game values and a
shared-matrix whole-game 95% interval; also report Home and Away separately under the same cell,
start, game weighting. Report the equal-start team-cell offsets per game and their nine-other-game
leave-one-game-out estimates. Separately give the pooled pair-level count, mean, standard deviation,
minimum, quartiles, median, and maximum, explicitly labeled pair-weighted descriptive spread.

For +45, subtract the LOOG team×horizon delta offset defined below, then reproduce DIAG4's variance
decomposition: on starts with both teams eligible, average pair residuals within each team cell,
average Home/Away within start, and compute between-start variance divided by between-start plus
within-start variance. Each start and team has equal weight; within-start variance is the mean of the
two team variances around that start's mean. Report counts and the point share.

## LOOG team×horizon delta offset

For a given game, team, horizon, and candidate, first average pair deltas inside each eligible
start/team cell (minimum three pairs). Within each training game, average its eligible start/team
cell means equally for that team and horizon. For a held-out game, the offset is the unweighted mean
of the nine other game-level team means. Apply that one offset to every common pair in the held-out
team/game/horizon. If any required training game lacks an eligible cell mean, the fold is
non-estimable and must be reported; do not substitute a pooled-pair, global, or own-cell mean.

## Q2 — corrected delta persistence (primary discriminator)

For transitions `+15→+45` (primary), `+15→+30`, and `+30→+45`, subtract the above LOOG team×horizon
offset from each candidate delta at both horizons. On the common pair intersection for that
start/team/transition, calculate:

`observed_share = sum(max(-d_later_corrected, 0) * I(d_earlier_corrected < 0)) / sum(max(-d_later_corrected, 0))`.

For its null, permute the corrected later delta vector across pair IDs within the same start/team,
hold the earlier sign indicator fixed, and calculate the same share. Use the registered 10,000
permutations, minimum support, exclusion rules, shared candidate permutation maps, EqualTeam and
equal-game weighting, and whole-game intervals above. Report observed, null, and paired gap with
95% intervals, negative-mass totals, eligible cells/starts/games, excluded cells, and zero-mass cells
for both candidates and all three transitions.

## Q3 — common reference comparison

Using identical source arrays, cell support, seed and aggregation rules, put these three series in one
comparison table for each transition:

1. M0 raw error persistence, re-derived in memory.
2. M1/M2 candidate error persistence after DIAG4's LOOG team×horizon correction, re-derived in
   memory with the frozen DIAG4 estimator.
3. M1/M2 candidate-minus-M0 delta persistence from Q2.

For every row show observed share, null mean, paired gap, whole-game 95% intervals, and eligible
EqualTeam starts. State which rows meet the descriptive positive-gap rule and by how much. If a
candidate error series exceeds its null but its delta series does not, attribute the surviving
pattern to structure shared with M0 in this comparison and state that the evidence does not justify
a pair-intent label program.

## Q4 — sign, zero, hand-check, and distance-gradient diagnostics

- On the corrected +15→+45 delta series, compute the primary statistic and null for `d` and `-d`
  using the same cells and permutation maps. For `-d`, earlier-negative means `d15 > 0`; later
  negative mass is `max(d45, 0)`. Report both directions and support. Do not assume equality.
- Count exact `d_h == 0.0` pairs at each horizon on the common candidate/M0 support. At +45, such
  rows contribute exactly zero to negative mass and are never classified as negative. Report exact
  zero counts and the fraction of pair rows with zero later mass, separately by candidate.
- Select two distinct +45 `(game, start, team, pair)` rows deterministically: lexicographically
  first eligible nonzero M1-minus-M0 row, then lexicographically first different pair row for M2.
  Print each row's M0 error, candidate error, computed delta, and assert within `1e-12 ft` that
  delta equals candidate minus M0. If two such rows do not exist, fail this check and report why.
- Use DIAG4's fixed cutoff-distance edges `[17.038243596734116, 25.896550730297974,
  36.18400154397977]` feet; do not refit or alter them. On the +45 support used by DIAG4, report
  equal-game, equal-start, equal-team binned means of raw `d45` and the frozen DIAG4 candidate
  residual `errors_ft[candidate] - (a + κ * errors_ft[M0])`, with pair and cell counts. Compare
  the bin-4-minus-bin-1 signed gradient magnitudes and label the delta gradient as attenuated,
  amplified, or not comparable to the candidate-only residual gradient. This is a descriptive
  distance stratification.

## Q5 — registered interpretation before results

Pair-specific residual structure would remain a live descriptive explanation only if at least one of
M1 or M2 has a positive +15→+45 corrected-delta observed-minus-null gap whose whole-game 95% interval
is entirely above zero, and that candidate's two adjacent-transition point gaps are also positive.
The pattern that closes this line is that neither candidate meets that primary rule, especially when
the candidate-only DIAG4 series remains above its null: that combination is consistent with
structure shared with M0 surviving in the candidate series but cancelling in the delta. In that
case, explicitly state that a pair-intent label program is not justified by these results. Any other
pattern is mixed/inconclusive under this preregistration. No outcome changes a threshold or gate.

## Frozen-source diagnostics and output boundary

The evaluator will preserve a machine-readable audit trail: expected/actual hashes, gate assertions,
the 22 re-run DIAG4 checks, pair and cell support, exclusions, offset estimates, shared bootstrap
indices' seed/shape, permutation settings, and hand-check rows. Report the exact prereg file hash and
commit. The report will include the frozen population statement above verbatim in §1, present the
Q5 interpretation before showing numeric results, and avoid p-values and claims about forecast
accuracy, model skill, adoption, or simulator validity.

No existing source, DIAG4 result, or protected artifact may be edited. Results are a separate local
commit after the preregistration commit; the completed research branch will be pushed as requested.
