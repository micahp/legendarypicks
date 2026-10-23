# NHL JC-DIAG6 preregistration: distance-conditioned pair persistence

**Base:** `c84b570ce761879f19f76c46eb6a429bd6a03e9c`  
**Branch:** `research/nhl-multi-agent-movement-2026-10-23`  
**Status:** freeze this file in its own commit before the provenance gate and before any DIAG6 Q1–Q4 value is computed.

## Scope and code/value questions

The new evaluator is necessary: existing code computes persistence and distance-bin summaries separately, but no existing evaluator fits the registered leave-one-game-out distance response and compares raw with conditioned persistence under shared support and uncertainty. These are project-specific descriptive quantities; no publisher defines them. The evaluator will read the frozen movement artifacts and write only this run's preregistration, evaluator, result JSON, and report.

This run is descriptive and read-only on every DIAG1–DIAG5 artifact. It will not refit a movement policy, resimulate, score a policy, create labels, select a candidate, or change a gate, threshold, coefficient, promotion rule, or production surface.

## Population and fixed geometry

Population is identical to DIAG5: 10 development games, leave-one-whole-game-out predictions, 200 rollout starts (172 group-scored at +45), 2,164 +45 within-team pairs (1,064 Home / 1,100 Away), 142 EqualTeam +45 start/team cells, and 311 eligible +45 team cells. Horizons are ordinal Image Id increments, **not seconds**; no independent tracking population is available. Pairs and starts are dependent; all confidence intervals use the same 10-game cluster bootstrap, 10,000 resamples, seed `20261024`, equal game weight, and one shared game-index matrix.

The distance for a pair is its frozen cutoff distance at the rollout start. Assign it once to one of four bins using the frozen DIAG4 edges `[17.038243596734116, 25.896550730297974, 36.18400154397977]` feet: lower edge inclusive, upper edge exclusive, with the final bin open-ended. The evaluator must compare the little-endian float64 bytes of its cutpoint array against DIAG4's frozen constant and DIAG5's recorded list; any difference fails the gate. It must record the cutpoint bytes' SHA-256 and pair counts by horizon/bin. No edges or bin memberships are refit.

The pair-delta definition is frozen: `delta = errors_ft[candidate] − errors_ft[M0]` on the same pair/game/start/team/horizon. A pair key is scoped to its source game, start, and team; never join pair or start identifiers across games.

## Provenance gate — before any DIAG6 Q1–Q4 value

For every exact path below, record expected and actual SHA-256. Missing paths or any mismatch set
`all_assertions_passed: false`, record the named path, emit no Q1–Q4 values, and stop. These are the
full DIAG5 expected source hashes plus its own frozen preregistration, result, and evaluator hashes.

| Name | Exact path | Expected SHA-256 |
|---|---|---|
| `jc_results` | `research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json` | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` |
| `fold_models` | `research/nhl-multi-agent-movement-2026-10-23/results/fold_models-bc91d1610de5.json` | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` |
| `movement_comparison` | `research/nhl-multi-agent-movement-2026-10-23/results/movement_comparison-bc91d1610de5.json` | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` |
| `scenario_archive` | `research/nhl-multi-agent-movement-2026-10-23/results/scenario_archive-bc91d1610de5.json.gz` | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` |
| `rollout_starts` | `/root/lp-research-data/nhl-multi-agent-movement-2026-10-23/rollout_starts.json.gz` | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` |
| `jc_diag_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-attribution-jcdiag-2026-10-23-v1.json` | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` |
| `jc_diag2_preregistration` | `docs/research/NHL-JC-DIAG2-PREREG-2026-10-23.md` | `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234` |
| `jc_diag2_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag2-pair-persistence-2026-10-23-v1.json` | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` |
| `jc_diag3_preregistration` | `docs/research/NHL-JC-DIAG3-PREREG-2026-10-23.md` | `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de` |
| `jc_diag3_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag3-pair-shrink-2026-10-23-v1.json` | `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd` |
| `jc_diag4_preregistration` | `docs/research/NHL-JC-DIAG4-PREREG-2026-10-23.md` | `66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0` |
| `jc_diag4_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag4-additive-offset-2026-10-23-v1.json` | `cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947` |
| `jc_diag4_evaluator` | `research/nhl-multi-agent-movement-2026-10-23/diagnose_additive_offset.py` | `2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a` |
| `jc_diag5_preregistration` | `docs/research/NHL-JC-DIAG5-PREREG-2026-10-23.md` | `18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70` |
| `jc_diag5_results` | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag5-delta-persistence-2026-10-23-v1.json` | `9510d70d418c09da63a6218077b8c1e2b7cc9a11e3b7ed82e63a5457c1039099` |
| `jc_diag5_evaluator` | `research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py` | `2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742` |

After hashes pass, re-assert values from the pinned DIAG5 JSON, not from prose: M1/M2 delta P1
observed/null/gap/interval; M0 raw and M1/M2 candidate-only observed/null/gaps; the four M1 +45
delta-distance-bin means and pair counts; the fixed cutpoints; plus45 total and team pair counts;
142 EqualTeam cells; and 311 eligible team cells. Float checks use absolute tolerance `5e-9`;
counts and cutpoint bytes are exact. A failed assertion stops all DIAG6 calculations.

## Common statistic, support, and uncertainty

- For each transition, use pair IDs common to both horizons for the same game/start/team. A cell
  requires at least three such pairs. P1 is unchanged:
  `sum(max(-later, 0) * I(earlier < 0)) / sum(max(-later, 0))`.
- The permutation null permutes the later vector across pair IDs within that start/team while holding
  the earlier sign vector fixed. Use 10,000 permutations per cell, seed `20261024`. Generate one
  index map per transition/start/team and reuse it across every series and raw/conditioned version.
- A cell with zero later negative mass is non-estimable for P1. For raw-versus-conditioned gap
  comparisons, use the intersection of cells with positive mass in both versions, so both gaps and
  their retained fraction use identical cell/start support. This denominator rule does not remove
  pairs by distance bin. Report cell exclusions, zero-mass counts, pair rows, and EqualTeam starts for
  each series/version.
- Aggregate Home and Away cell shares equally within a start, starts equally within each game, then
  games equally. Calculate each game's observed, null, and paired gap before bootstrapping. Use the
  same 10,000 × 10 whole-game index matrix for all intervals and comparisons; percentile interval
  endpoints use linear quantiles. No pair/start-level independent intervals and no p-values.
- The retained fraction point estimate is the conditioned equal-game mean gap divided by the raw
  equal-game mean gap. In each shared bootstrap draw, divide the conditioned resampled game-mean gap
  by its paired raw resampled game-mean gap. Record draws with zero/non-finite denominator and report
  valid draw count. Do not substitute an unpaired ratio of per-game fractions.

## Q1 — primary LOOG distance-conditioned delta persistence

For M1 and M2 separately, start from the **raw** candidate-minus-M0 delta (do not first subtract the
DIAG5 team×horizon offset in Q1). For each held-out game, team, horizon `h ∈ {15,30,45}`, and pair
distance bin `b`, predict the delta by the pair-weighted mean across the other nine games of all
training pair rows in `(team,h,b)`. If that training cell contains fewer than 30 pair rows, use the
pair-weighted mean for `(h,b)` pooled over Home and Away from those same nine games. Record the
training pair count and whether fallback fired for every held-out `(game,team,h,b)`. If the pooled
fallback is empty, fail closed; do not invent a broader fallback or drop held-out pairs.

Subtract that prediction from each held-out delta to obtain its residual. Distance affects only the
prediction: retain every held-out pair row and the original horizon intersections; do not calculate
separate P1 values per bin. Compute observed/null/gap and whole-game 95% intervals for +15→+45
(primary), +15→+30, and +30→+45, for M1 and M2. Report prediction/fallback records, pair/cell support,
and zero-mass exclusions.

## Q2 — raw and conditioned gaps for five series

Use these five series:

1. M0 raw error `errors_ft[M0]`.
2. M1 candidate-only error after DIAG4's LOOG team×horizon offset.
3. M2 candidate-only error after DIAG4's LOOG team×horizon offset.
4. M1 delta after DIAG5's LOOG team×horizon delta offset.
5. M2 delta after DIAG5's LOOG team×horizon delta offset.

Apply distance conditioning to each series using the same nine-game bin-response rule as Q1. For the
candidate-only series, subtract DIAG4's team×horizon LOOG offset **first**, then fit/apply the
distance prediction. For the delta series, subtract DIAG5's team×horizon LOOG offset **first**, then
fit/apply the distance prediction. M0 has no upstream correction. These pre-distance series are the
raw comparator for Q2; conditioned values are their residuals after the distance response.

For each series, report raw and conditioned observed/null/gap estimates and intervals on the matched
support above, the raw and conditioned pair-level spreads, and the conditioned/raw retained gap
fraction with its paired whole-game bootstrap interval. For the primary +15→+45 transition, also
report per-game raw gaps, conditioned gaps, and retained fractions; each held-out game's distance
response is trained on the other nine games. Reproduce the all-cell DIAG5 raw gap values as a
provenance check, while labeling the matched-support raw estimate used in the retained-fraction
comparison.

## Q3 — within-cell covariance decomposition

Use pair rows common to +15 and +45 within each original start/team. Analyze M0 raw error, M1 raw
delta, and M2 raw delta. A start/team cell with fewer than three common pairs is excluded and counted.
Distance bin is fixed from the start cutoff distance.

Within each eligible cell, let `X` and `Y` be +15 and +45 values and `p_b` the observed share of cell
pairs in distance bin `b`. Compute population (ddof=0) covariance components:

- `between_bin = Σ_b p_b (mean(X|b)-mean(X)) (mean(Y|b)-mean(Y))`;
- `within_bin = Σ_b p_b Cov(X,Y|b)`, with singleton-bin covariance defined as zero;
- `total = between_bin + within_bin`.

This empirical-frequency weighting is the law-of-total-covariance decomposition and gives zero
weight to empty bins. Aggregate each component by equal Home/Away weight within start, equal starts
within game, and equal games. Report between/within/total components and their shares of total, with
whole-game intervals from the shared bootstrap matrix. If total is zero or non-finite, report the
share as not estimable and retain the components.

Repeat after separately replacing X and Y within each cell by centered midranks across that cell's
common pair rows (average rank for ties, ranks 1…n). Use the same distance bins, cell support, and
aggregation. Report the rank decomposition separately; do not pool raw and rank covariance.

## Q4 — spread, game variation, sign, zeros, and support

- For each raw/conditioned series and horizon, report pair-weighted population SD and IQR on the
  exact same pair rows. Flag a conditioned P1 series as **underpowered for a null interpretation**
  if either its residual SD or IQR is at most half its raw counterpart; a null under that condition
  is not evidence against persistent structure.
- For all five Q2 series on +15→+45, report game-level raw and conditioned gaps and per-game
  conditioned/raw fractions. Report the LOOG training-game mapping; each game is held out from its
  own distance response.
- On the primary Q1 conditioned delta residual, compute P1 and its null for `d` and `−d` with the
  same cells and permutation maps. For `−d`, earlier-negative is `d15 > 0` and later negative mass is
  `max(d45,0)`. Report both orientations and their support.
- Count exact-zero raw DIAG5 deltas and exact-zero Q1 conditioned residuals per horizon. At +45,
  report rows with zero negative mass (`value >= 0`) and total pair denominator, comparable with
  DIAG5's registered 0/2164 exact-zero deltas and 156/2164 (M1) / 161/2164 (M2) zero-negative-mass
  rows.
- Report eligible pair counts per horizon/bin and every fallback decision per held-out
  `(game,team,h,bin)`. Assert the evaluator's cutpoint bytes equal the pinned DIAG4/DIAG5 bytes.

## Q5 — registered reading before results

For each candidate, if the conditioned Q1 primary gap interval includes zero, the result is
consistent with the frozen monotone distance response explaining the surviving persistence; state
that a pair-intent label program is not justified by this evidence and that the next research spend
is a distance-dependent candidate correction, not labels. If the interval excludes zero, report the
conditioned gap and retained fraction: residual sign structure remains beyond the frozen distance
response, but no behavioral mechanism is identified and labels are not justified by this evidence.
If Q1 excludes zero while Q3 attributes at least half of pair covariance to between-bin structure,
or Q1 includes zero while Q3 attributes less than half to between-bin structure, classify the result
as mixed and do not narrate a winner. Apply this reading separately to both candidates and raw/rank
Q3 diagnostics; if they disagree, report the disagreement as mixed. No p-values and no claims about
accuracy, skill, win rate, or forecasts.

## Reproduction and output boundary

The report will state the Q5 reading before its DIAG6 result values. The evaluator will include
expected/actual source hashes, gate assertions, prediction counts and fallback choices, support and
exclusions, per-game estimates, bootstrap/permutation settings, covariance components, and cutpoint
byte checks. Run `ast.parse` on the evaluator, `git diff --check`, then a complete second run to a
temporary JSON path and `cmp` it byte-for-byte with the committed result. Do not write into or
regenerate any DIAG1–DIAG5 artifact. Commit this preregistration alone first, then the evaluator,
result JSON, and report in a second commit; push both commits as requested.
