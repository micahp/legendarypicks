# Playcall decisions, owner ruling (2026-11-02)

Status: resolved. This record closes the open items D1, D2, D3 and Q1 in
`PLAYCALL-DESIGN-NOTE-M1-2026-11-02.md` and `PLAYCALL-ABLATION-SPEC-M3-DRAFT-2026-11-02.md`.
The source write-up is not canonical. The research in this repo is canonical.

## Correction on populations

A 2025 historical average and a 2026 matchup-audit number are different populations. They must not be treated as
the same population, and an earlier interpretation that did so was wrong. Do not reuse 22.86, 68.7% or 23.3% as 2025
baselines unless they are independently verified for the same population.

We must also keep the remaining opportunity for genuine out-of-sample evaluation. Reconciling old numbers does not
justify spending it.

## D1. Data boundaries

- 2026 may be opened, read-only, only to reconcile the source numbers in the earlier ARI-DAL player-tail audit.
  Access is isolated from model fitting, tuning, feature choice, threshold selection, and arm ranking.
- Log every 2026 access in `HOLDOUT-EXPOSURE-RECORD-2026.md` before opening the file. The record already has an
  uncommitted entry 12 from hermes2; that entry stands as logged exposure.
- Previously inspected 2026 results are exposed exploratory evidence, not a clean holdout.
- 2025 is previously exposed. It is an explicitly labelled retrospective evaluation fold, not an untouched test set.
- Reconcile the 2026-versus-2025 discrepancy in one table with these columns: season, game population, source file,
  numerator, denominator, metric definition, value.

## D2. Temporal evaluation

- Development fold A: train on 2022, validate on 2023.
- Development fold B: train on 2022-2023, validate on 2024.
- Freeze arm definitions and hyperparameters on development evidence only.
- Final retrospective evaluation: train on 2022-2024, evaluate once on 2025. Do not tune on 2025.
- A 2026-oriented model may be fit through 2025 after retrospective review, provided every source is eligible before
  each prediction cutoff.
- Prospective evaluation: lock predictions, code, feature provenance and input hashes before future 2026 kickoffs.
  Do not label historical 2026 backtests as prospective.
- The earlier coaching research tuned a penalty on 2023. That result is not an independent test.

## D3. Research advance gates (predeclared decision rules; frozen)

These are engineering thresholds set before viewing any 2025 or 2026 result. They are not claimed to be optimal.

Play-calling alternatives:
- Improve run/pass predictive log loss by at least 0.001 absolute over the corresponding baseline.
- A paired, game-clustered 95% confidence interval supports the improvement.
- Run/pass Brier does not increase by more than 0.001 absolute.

Player-share and participation alternatives:
- RB and WR share-variance ratios within 0.80 to 1.20 of observed, for adequately supported cohorts.
- At least 10% reduction in absolute variance-ratio error versus baseline.
- No more than 5% relative worsening of team opportunity-count absolute bias.

All arms:
- Zero new football legality or accounting failures.
- Report effect sizes, bootstrap intervals, coverage, zero rates, P95 and P99 behaviour, and subgroup regressions.
- Account for multiple candidate-arm comparisons before making a statistical claim.
- Insufficient sample support is inconclusive, not passed.
- Passing the retrospective gates qualifies an arm for prospective validation. It does not adopt the arm into production.
- For rare tails, report P95, P99, support counts and uncertainty. Do not impose arbitrary individual-player ceilings.

## Q1. Playbook prior

- `v1_full_stack` enables the playbook prior: `slc_config.py` sets `playcall_playbook=True` in `V1_OPTIONS`, and the
  runner forwards the resolved flag to `load_reference()`. The "off by default" text in `playbook_prior.py` describes
  standalone or optional use only.
- Verify actual execution from the resolved profile manifest: enabled-layer flags, source hashes, and nonzero
  playbook-prior usage. A prior that is enabled but unused is a diagnostic failure.
- Do not edit the profile to change a layer's state.

## Instructions to the executing agent, in order

1. Finalize M3 as a frozen research spec. It must state the definitions, metric denominators, folds, and the gates
   above. Commit it. Record the freeze commit SHA and sha256 hashes of: the 2022-2025 baseline tables, the personnel
   table, the 2022-2025 play-by-play and participation inputs, and each SLC code file the arms use.
2. Only after that freeze commit: log the 2026 access in `HOLDOUT-EXPOSURE-RECORD-2026.md`, then do the read-only
   reconciliation of the ARI-DAL audit numbers. Output the D1 table.
3. Build development folds A and B. Freeze arms and hyperparameters. Evaluate 2025 once, as a labelled retrospective fold.
4. Put tests and results on the research branch. Do not modify production. Do not rerun the archived 10K batches.
5. Focus the work on whether explicit personnel and participation modelling improves team play decisions and player
   workloads. Do not add post-hoc caps or invented injuries.
6. The baseline and personnel data are immutable. Observed personnel counts for 2022-2025: 11 personnel 58.1% of plays,
   12 personnel 21.8%, all other groups about 20%. Nearly 42% of observed plays use something other than 11. This
   supports prioritising personnel-package selection and substitutions before fatigue or injury mechanisms. It does not
   prove that those changes will improve workload prediction.
