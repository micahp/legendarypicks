# NHL JC-DIAG7 preregistration: out-of-sample value of pair identity

**Source base:** `a7b50ffc3d597f8e7d89a5a23826e37b7107891a`\
**Required correction commit, first:** `f7be2a19d3860ff17156c0c3d0de6d411424a782`\
**Branch:** `research/nhl-multi-agent-movement-2026-10-23`
**Status:** freeze this preregistration in its own commit before the DIAG7 provenance gate and before any Q1–Q3 value is calculated.

## Scope and code/value questions

A separate evaluator is needed: the frozen DIAG6 artifacts do not test pair-residual prediction on held-out games or compare within-pair concordance with a different-pair control. These are project-specific statistics; no publisher supplies them. The evaluator will read frozen tracking/model artifacts and write only this preregistration, its evaluator, result JSON, and report. It will not alter a DIAG1–DIAG6 result, controller, archive, gate, threshold, coefficient, production surface, or model-selection rule.

The analysis is read-only and descriptive on the same ten development games. It does not resimulate, refit movement policies, or establish value beyond this inspected population. No production database will be opened.

## Required DIAG6 correction and provenance gate

The first commit is the correction subsection in `docs/research/NHL-JC-DIAG6-REPORT-2026-10-23.md`, committed alone as `correct DIAG6 retained-fraction framing`. The original report hash was `620b7b3867ce8442e1fdc83646a65487aa05d8637ff4924772ed8736aeb18afa`; after that authorized report-only correction its hash is `cf72e2646e00a3da27ccff849f96e9e00cbb2f22bfd12433b4f9feba03d67e45`. The DIAG6 JSON is not changed.

Before Q1–Q3, the evaluator will fail closed unless these exact artifacts match:

| Artifact | Path | Expected SHA-256 |
|---|---|---|
| DIAG6 result JSON | `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag6-distance-conditioned-2026-10-23-v1.json` | `8dfe2f551727484e43c612c5e2ede85ce0d237f4f479edb89e7ad1e5e59c62ed` |
| Corrected DIAG6 report | `docs/research/NHL-JC-DIAG6-REPORT-2026-10-23.md` | `cf72e2646e00a3da27ccff849f96e9e00cbb2f22bfd12433b4f9feba03d67e45` |
| DIAG6 evaluator | `research/nhl-multi-agent-movement-2026-10-23/diagnose_distance_conditioned_persistence.py` | `71e162ffa625fde1067413913d3a0ff9b63c1c64e657a24684efd73d289f1c37` |
| DIAG6 preregistration | `docs/research/NHL-JC-DIAG6-PREREG-2026-10-23.md` | `f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48` |

The result JSON pins all 17 frozen upstream artifact hashes. The evaluator will verify all 17 entries against disk and record expected/actual values. The five direct DIAG6 source hashes are:

| Frozen source | Expected SHA-256 |
|---|---|
| JC results | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` |
| Fold models | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` |
| Movement comparison | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` |
| Scenario archive | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` |
| Rollout starts | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` |

Reassert the frozen DIAG6 values before computing new estimands, with exact floating-point values and only the explicitly given tolerance:

- Q1 conditioned primary gaps: M1 `0.3751768756918231`; M2 `0.35885185351280086`.
- Q2 matched-cell retained fractions: M1 `0.8933858227557131`; M2 `0.9442712649286923`.
- Q3 raw-scale between-bin shares: M1 `0.6102114758698477`; M2 `0.5921480205186526`.
- Q3 within-cell rank between-bin shares: M1 `0.436971230453636`; M2 `0.44036099329465817`.
- DIAG6 Q4 +45 delta SDs: M1 `3.0274` ft; M2 `3.0550` ft.
- Population: 10 games, 200 starts, 172 +45 scored starts, 2,164 +45 pairs, 142 EqualTeam starts, 311 eligible team cells.

Any hash, value, population, or source-identity contradiction writes a gate failure with no Q1–Q3 fields and stops. The only anticipated exception to complete pair-identity support is an explicitly reported unseen-pair fallback described below; it is not a license to weaken the source gate.

## Identity boundary

The prior frozen DIAG2–DIAG6 protocols define pair IDs as sorted track IDs scoped within a game-period/start/team and prohibit cross-game joins. The reports also state that cross-game athlete identity is unverified. DIAG7 will not strip those scopes, infer athlete identity from a numeric track-ID collision, or join rollout starts across games.

A cross-game pair key is usable only if the frozen source provides a stable pair/athlete identity with source documentation establishing that it persists across games. If it does not, all target pairs are treated as unseen for B and C and fall back to A; the evaluator will report those counts explicitly. Q2 then has no verified cross-game pair matches and is non-estimable; it must report that support result rather than manufacture a comparison. This is an anticipated data limitation, not a post-result exclusion.

## Population, delta, and common support

Use the frozen DIAG6 population: 10 development games; 200 rollout starts, 172 scored at +45; 2,164 +45 within-team pair observations; 142 EqualTeam starts; and 311 eligible team cells. Image Id is ordinal and not seconds. No independent tracking sample is available. The target for each candidate is the +45 signed pair-error delta in feet, `delta = errors_ft[candidate] - errors_ft[M0]`, using the frozen DIAG6 source rows.

All Q1 variants are scored on the identical held-out rows: a row is included only when the frozen DIAG6 A prediction exists; otherwise the evaluator fails closed. B and C always return A for an unseen/under-supported pair, so they cannot silently change the common pair set. Report the pair count for every held-out game and distance bin, plus the total. Do not treat pair rows as independent uncertainty units.

## Q1 — held-out prediction, outer leave-one-game-out

Evaluate M1 and M2 separately. For each held-out game `g`, the outer training population is exactly the other nine games.

### A: frozen distance-only predictor

Use DIAG6 Q1's stored LOOG `(team,+45,distance-bin)` prediction for each target pair, unchanged. Do not refit its cutpoints, bin membership, or target-game prediction. A distance-bin prediction missing for any otherwise eligible held-out row is a gate failure, not a dropped row.

### B: distance plus a shrunk pair residual

For training residuals, use only the outer nine games. To prevent a training game's outcome from entering its own distance baseline, build each training game's residual against the same frozen-bin mean estimated from the other eight outer-training games. Pair residuals are delta minus that baseline. No row from the outer held-out game is used to estimate pair means or variance components.

The grouping key is the source-verified stable pair identity. If only local track IDs exist, retain their game-period/start/team scope; they cannot match the outer held-out game. For a pair with at least two training residual observations, estimate its raw residual mean and shrink it toward zero using the one-way random-intercept method-of-moments variance components computed on the outer training residuals. For groups `p` with counts `n_p`, means `r̄_p`, total `N`, and group count `J`, define:

```text
SSW = Σp Σi (r_pi − r̄_p)^2
SSB = Σp n_p (r̄_p − r̄)^2
within_variance = SSW / (N − J)
tau2 = max(0, (SSB − within_variance*(J−1)) / (N − Σp(n_p^2)/N))
lambda_p = tau2 / (tau2 + within_variance/n_p)
pair correction = lambda_p * r̄_p
```

If the denominator/degrees of freedom are unavailable, the variance components are nonfinite, or a pair has fewer than two training observations, set its weight to zero and use A. Report the estimator inputs, `tau2`, `within_variance`, fallback count, unseen count, and count receiving nonzero weights. When a stable cross-game key is absent, game-scoped pair groups may inform these generic training-only variance components across repeated starts, but may never be used to match a held-out identity.

### C: unshrunk training pair mean (overfit control)

Add the raw mean training residual for a verified pair key to A, without shrinkage, when at least one training residual exists. An unseen pair falls back to A. C is a diagnostic control and cannot be selected.

### Metrics and uncertainty

For each outer held-out game and variant, compute pair-row MAE and MSE. Aggregate with equal game weight: MAE is the mean of game MAEs; RMSE is the square root of the mean of game MSEs. Estimate each variant's Gaussian sigma separately within each outer fold using inner leave-one-game-out residual predictions over its nine training games. For an inner held-out training game `h`, fit A on the other eight outer-training games; generate each of those eight games' pair-training residuals from means fitted on the other seven (excluding both `g`, `h`, and the residual row's game); then fit B/C and predict `h`. Set sigma squared to the equal-game mean of those nine inner game MSEs (Gaussian MLE); use the same frozen bins and pair-identity rules. No outer held-out-game target may contribute to sigma. A nonpositive or nonfinite sigma is a hard failure, not an epsilon-clamped score. Report the equal-game mean Gaussian log predictive score on the outer held-out rows.

Use 10,000 whole-game cluster bootstrap draws, seed `20261024`, equal game weight, and one shared game-index matrix for every variant/metric. Report paired B−A and C−A differences for MAE, RMSE, and mean Gaussian log score with percentile 95% intervals. Define relative B RMSE improvement as `100*(RMSE_A - RMSE_B)/RMSE_A`; compute its interval draw-by-draw with the same paired game draws. Report the 10 per-game scores and differences. Q1's main decision quantity is B−A relative RMSE improvement.

## Q2 — distance-matched pair identity concordance

Use the frozen DIAG4 distance edges and membership, with no refit. For each team and distance bin, first average a pair's +45 delta over its eligible starts within each game, then center those pair means by the mean of pair means in that same game/team/bin. This prevents a pair observed in many starts from receiving extra weight. Only source-verified stable pair keys observed in at least two games in the same bin are eligible.

For every unordered game pair and team/bin with at least two shared stable pair keys, calculate (a) sign agreement and (b) Spearman rank correlation between the two games' within-bin-centered deltas for the same pair keys. For the different-pair control, derange the second game's pair labels within that same team/bin/game-pair cell, excluding fixed points, and compute the same measures on the same support. Use 10,000 seeded derangements (`20261024`) per estimable cell and report within-pair minus different-pair concordance. Sign zero is a distinct sign and agrees only with zero. Spearman is non-estimable with fewer than three shared keys or a constant vector; report its support separately.

Aggregate estimable team/bin cells equally within each game pair, then aggregate game pairs equally. For intervals, resample whole games with replacement (10,000 draws, seed `20261024`); recompute from the sampled game clusters and the fixed, seeded different-pair maps. Report pair counts by bin, number of stable pair keys observed in at least two games, eligible game-pair/cell counts, and all zero/non-estimable support. If no verified keys recur, report Q2 as non-estimable with zero eligible matches and no concordance estimate.

## Q3 — materiality and support decision

Precommit a **5% relative RMSE improvement** bar for B over A. At the frozen +45 delta SD of about 3.03 ft, this corresponds to roughly 0.15 ft of RMSE reduction at that scale. That is the minimum reduction worth prototyping a distance-dependent pair correction given only ten development games and unresolved cross-game identities. Call Q1 material only when the lower endpoint of the paired 95% interval for relative RMSE improvement exceeds 5%; a positive estimate below that bar is not sufficient.

Report A-versus-B held-out residual spread reduction as `1 - SD_B/SD_A`, where each variant's SD is the square root of the equal-game mean of its within-game population residual variance on the common pair rows. Bootstrap this paired quantity by whole game. Also report per-game held-out pair counts and counts by frozen distance bin. Name any bin with zero support in a held-out game or training fold; do not merge or redefine bins.

## Registered reading (verbatim)

- Q1 B−A improvement interval **excludes zero and exceeds the precommitted materiality bar** → pair identity carries transferable out-of-sample value; next spend is a correction prototype, still no label program, no gate change.
- Q1 interval **includes zero** → the pair-identity line closes: no correction, no labels, and the DIAG2–DIAG6 persistence is recorded as a descriptive property of the ten inspected games only. Q2 may contradict; if it does, report "structure present, immaterial out of sample" and do not narrate a winner.
- Both Q1 and Q2 negative → close the line, say so in the Decision section in one sentence.

Operationally, an interval wholly above zero but whose lower endpoint does not exceed the 5% bar is positive yet below the registered materiality requirement; it does not authorize a correction prototype. If Q1 includes zero, the pair-identity line closes regardless of Q2; any Q2 contrast in the positive direction is described as structure present but immaterial out of sample. No label program or gate change can be justified by this development-only analysis.

For the final bullet, “Q1 and Q2 negative” means the Q1 relative RMSE-improvement point estimate and both estimable Q2 within-minus-different concordance contrasts (sign agreement and Spearman) are below zero. A non-estimable Q2 result is reported as such, not classified as negative. If Q1 is positive but below the materiality bar, it does not qualify for a prototype; positive Q2 evidence is described as structure present but immaterial out of sample.

## Report and reproducibility contract

Write `docs/research/NHL-JC-DIAG7-REPORT-2026-10-23.md` and `research/nhl-multi-agent-movement-2026-10-23/results/jc-diag7-oos-pair-value-2026-10-23-v1.json`. The report must include the population and identity boundary, expected/actual provenance gate, Q1–Q3 tables, every game's held-out scores, support/fallback counts by bin, registered decision, runtime, evaluator/result SHA-256 and byte count, and reproduction commands. Do not use forbidden performance claim categories. State that these ten games are inspected development data and not an independent evaluation set.

Use `/usr/bin/python3` with `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1`. Run `ast.parse`, `git diff --check`, a full deterministic rerun to a temporary JSON and `cmp` byte-for-byte. Commit the evaluator, result JSON, and report together after the preregistration commit. Push the correction, preregistration, and results commits to `research/nhl-multi-agent-movement-2026-10-23`; verify local HEAD equals the remote SHA and the worktree is clean.
