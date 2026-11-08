# CONTEXT 2026-11-08: SLC v2 pairing, validation and Sunday smoke

Predecessor: `docs/CONTEXT-2026-11-04-SLC-V2.md`. The research branch `research/news-evidence-audit-2026-11-07` was fast-forwarded into `slc-v2`; both were pushed at `fe7d5877`. The SLC worktree is `/root/lp-slc-v2`. This context file is a subsequent local change.

## SLC execution and evidence

- The repaired engine's Sunday smoke ran three seeds across all 13 matchups with RNG v2 and five ordinary blocker fixes: 39/39 games completed and 39/39 exported box scores reconciled. One game went to overtime. The run used the fast host's current read-only application database. Details and per-seed identities: `docs/research/slc-sunday-v2-smoke-2026-11-08/`.
- The smoke produced 17,864 fallback events, including 15,734 missing decision-category matches. Multiple misses can occur in one decision; event counts are not play counts or accuracy measurements. All 1,491 exported player rows had unknown roster eligibility. Reconciliation does not establish complete player snaps, true possession time, or verified eligibility.
- RNG-v2 paired-layer comparisons now check control input identity, the requested layer change, shared stream roots and per-seed evidence. The model and matrix default to the five ordinary blocker fixes; `--no-slc-blocker-fixes` opts out. Sack ablation A remains separate and opt-in. Disabling Dirichlet player shares also disables its dependent fixed-share adapter, so that intervention is combined.
- The final ARI–SEA matrix CLI passed a three-seed smoke for score-clock and combined workload interventions. A later 50-seed evaluation matched streams for all requested seeds but has only 48 reconciled pairs in each comparison: control seed 18 and workload seed 31 hit validator errors, and score-clock seed 28 hit `no_supported_scrimmage_intent_in_cell`. Both full comparisons are marked invalid. Subsequent validator fixes accept the saved legal seed 18 and 31 records; the original run has not been reclassified or rerun. The source-coverage guard remains to investigate. Results and limitations: `docs/research/slc-ari-sea-paired-evaluation-2026-11-08/`.
- Validation and accounting failures now preserve complete compressed records and identity metadata when available; later changes also capture incomplete records and explain when a record was unavailable. Tests cover intentional failure capture and reload.
- After the merge, 222 focused SLC tests passed. This and the smoke are not a full 13 × 200 repaired-engine run or proof of model realism.

## Historical run and host data

- The historical Sunday regeneration used source `d6caadd3` and RNG v1: 2,585/2,600 games validated, with 15 refusals in ten matchups. Its raw failure records were not retained, so the refusals remain unclassified; the later v2 runs do not replay that execution identity. See `docs/research/slc-sunday-rerun-2026-11-08/`.
- The fast host's `/tmp/picks-dal-phi-simulation-copy.db` was trimmed of requested non-NFL data to free space. It is no longer the original historical database; preserve old manifest hashes and use the new identity and recorded checks in `docs/research/slc-trimmed-historical-db-2026-11-08/`. The Sunday v2 smoke used a separate database.
- Full paired-run outputs remain on the fast host at `/root/ot-sim-out/slc-matrix-ari-sea-eb936b6e-50/`; the cross-slate smoke outputs are at `/root/ot-sim-out/slate-v2-regression-090a4f05-2026-11-08/`.

## Open work

- Investigate the blocked score-clock seed and decision-category coverage, then repeat a controlled paired regression on the current validator before treating a larger run as complete. Evaluate fallback behavior against observed data.
- Upstream roster eligibility remains unknown. Full player snaps and actual possession time were requested but have not been implemented; reconciliation alone does not provide them.
- A full repaired-engine slate and paired sack ablation A remain future work. Keep their input identities, results and limitations distinct from the historical v1 run.

## News evidence audit

The starter/coach and injury-designation audit, its corrections and rationale are in `docs/research/news-evidence-precision-2026-11/INDEPENDENT-AUDIT-2026-11-07.md`; related classifier changes and tests are included on `slc-v2`.
