# Decision: NCAAF research parity recovery and candidate promotion gates
Date: 2026-10-20
Status: **Conditional go for verifying candidate repair; no-go for merge/deploy/locks yet.**
Scope: G2/C2/G2h game-winner pipeline and NCAAF Model/Forecasts surface.

## Evidence received from the parity worker

The worker reports two **local-only, NOT pushed** commits: research forensics **ccade77f** on research/ncaaf-parity-forensics-2026-10-20 and a repair **54800dad** on candidate/ncaaf-parity-repair-2026-10-20. At documentation time these commits were not available at their remote refs, so the measurements below are a **worker report, not independently rerun here**. Ask the worker to push **both** branches separately, without merging them or touching dev. Keep the original worktree and raw forensics evidence.

The report:
- The original frozen writer, backend/fbs_phase3_increment_g.py, successfully reproduces G2h with max abs difference **1.7e-8**, and C2 **4.4e-16**; G2 exact.
- Existing production fails C2 parity on **2,397/2,397** rows (max **0.19563**) and G2h on **2,397/2,397** rows (max **0.18841**). First divergent model-fit block **2022-09-25**, training population **201** games.
- **Primary cause** for both C2/G2h: rolling drive features were built with **2022–2026** history in production, while the adopted research features are based on **2014–2026** history. The difference impacts **3,474** scored feature rows.
- **Secondary population mismatch:** the research writer drops games with null epa_diff. Game **401778314, 2025-12-26**, is excluded from its training population; including it changes **28** later 2025 predictions. That is the earlier "28 rows", *not* a 28-game drive-feature rebuild.
- **C2-only additional cause:** production fitter uses raw C2 features, 0.5-ridge penalty and different solver; research uses fold-specific standardization and the full penalty. Against research inputs, this estimator difference alone reaches **0.089** absolute C2 probability difference. G2h shares its estimator class with research and is affected by input mismatches.
- Existing check_parity replays research walk-forward methods, not the true production fit/predict path: a certificate from this gate alone is insufficient to prove the live model.
- The reported **candidate 54800dad** recovers full feature history, pinned population exclusion and research-compatible C2 fit. It reproduces **all 2,397** scored C2 rows to **3.3e-16** and G2h to **1.5e-8**, with production rebuilt input checks; all **23** FBS tests pass. The worker did **not** merge, certify, enable locks, run live-slates or visual QA.

## Product decision

**Approve the candidate as the basis for a separate verification/implementation branch, not for immediate adoption or release.** The recovered original writer makes the historical model credible again. The fix corrects production *toward* the preregistered research model rather than inventing a new estimator. The evidence is strong enough to continue with validation, not yet enough to grant official forecast locks.

Keep the **1e-6 row-parity threshold**. Do not choose a model by retrospectively cherry-picking its Brier score. Do not alter original frozen predictions, remove failed checks, move eligible cutoff times or retroactively promote legacy rows. The original adopted G2h Brier **0.1946** remains a research result and must not be labeled as a certified live-model performance score until the full replay/certification is completed.

## Work to complete before any model-code merge

1. **Preserve and push forensics**: push research ccade77f and candidate 54800dad to their named branches. Review docs/RESULT-ncaaf-parity-forensics.md and scripts/manifest, require reproducible commands, exact hashes, game-id comparison, and independent rerun against frozen source.
2. **Eliminate the hard-coded exclusion as the permanent production policy.** The candidate's pinned 401778314 exception is acceptable *only in a frozen parity replay fixture*. General production must implement the same reproducible historical **EPA-availability eligibility rule** that research used (or train a newly preregistered model on a deliberately different population). Explicitly document its consequence for recent-season player/schedule coverage. Never silently exclude an upcoming fixture based on a scoring-only feature.
3. **Make drive-feature history an explicit dependency**: retain/ingest 2014–2026 lookback for the adopted model, hash source versions, assert minimum history and fail loudly when required seasons or team identities are missing. Do not substitute 2022-only ratings and still call the result G2h.
4. **Unify the estimators**: research and production C2 must share the same normalization, penalty and numerical settings; G2h uses its published HierarchicalLogistic as pinned. Avoid diverging copied solvers. Persist fitted scaling stats for future predictions so no future-game information enters a scaler.
5. **Test the actual forecasting path**: on the **full 2,397-game walk-forward population**, for each date block, call the same service fit/predict implementation used by --run with the exact pre-date cohort, and compare to the originally frozen ledger. Compare exact per-row p_g2, p_c2 and p_g2h; fail if any abs delta exceeds 1e-6. A research replay alone is **not** enough. Include correct 2025 frozen holdout (separate from walk-forward) and stored forecast version/feature fingerprint.
6. **Verify the candidate on live upcoming games**: fixture identity, conferences, neutral-site examples (synthetic if the current slate has none), ESPN full UTC kickoffs, strictly as-of feature history, and the actual preview data via API. A stable live prediction must not rely on the parity replay's 2025 exception.
7. **Production health before locking**: grade only source-confirmed final results, audit model-versioned feature coverage and missing slates, check legacy/missed statuses, run headless/browser visual QA on a separately authorized server, and verify no ungraded/late records enter official stats.
8. **T-90 scheduler is not approved in this doc**: request operator authorization and resource/schedule review separately after all integrity and UI gates pass. Verify multiple daily/weekly windows, delayed games, retries and missed-window alerts; document operations ownership.
9. **Regression/falsification**: 23 passing tests alone do not prove operational parity; reintroduce a short feature-history archive, raw C2 fit, missing EPA eligibility and fake kickoff to ensure the new gate fails. Review fixtures, paired metrics and browser behavior before any promotion.
10. **Use a separate code-review PR** targeting dev only after evidence is complete; do not push dev, restart :3096 or prod, or write locks on the strength of this decision memo.

## The legacy-record ruling

Three old records were created before their actual ESPN kickoff times, which is useful *creation-time evidence* but not proof of a valid immutable T-90 lock. Keep all legacy records out of official pregame performance, including these three. Do not backdate/reclassify them as certified predictions. If helpful, add a read-only explanatory provenance field without changing lock eligibility.

## Exit verdict

- **Research writer reproduction:** worker-reported PASS, independent reproduction pending remote evidence.
- **Candidate on historical parity fixture:** worker-reported PASS, independent production-path certification pending.
- **C2/G2h public official locks:** **BLOCKED**.
- **NCAAF Forecasts default league landing:** **NOT YET APPROVED** until certified + browser QA.
- **Game-level picks requiring market prices:** independent data/policy gate, unchanged.
- **FBS direct player-distribution candidates:** independent Props research track, unaffected.

## References

- docs/BRIEF-ncaaf-parity-forensics-2026-10-20.md (existing remote research branch)
- backend/fbs_phase3_increment_g.py; research/fbs/phase3-g/forecasts_walk_forward.csv (adopted writer + ledger)
- backend/fbs_model_runner.py, backend/fbs_model_service.py (production gate and fit path)
- docs/DECISION-forecast-first-leagues-market-first-props-2026-10-20.md (product IA; certify before using as landing view)

**One-sentence handoff:** Push the two local commits; review and replay the candidate's 2014-onward inputs, EPA cohort and unified estimators; certify the actual production fit/predict path before any official C2/G2h lock or default landing promotion.
