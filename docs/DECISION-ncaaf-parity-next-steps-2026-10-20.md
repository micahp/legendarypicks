# Decision: NCAAF research parity recovery and candidate promotion gates
Date: 2026-10-20
Status: **Conditional go for verifying candidate repair; no-go for merge/deploy/locks yet.**
Scope: G2/C2/G2h game-winner pipeline and NCAAF Model/Forecasts surface.

## Evidence received from the parity worker

**Remote verification update:** Candidate repair **54800dad87154b5f9cf1981dd80259f3c00676ac** is pushed to [candidate/ncaaf-parity-repair-2026-10-20](https://github.com/micahp/legendarypicks/tree/candidate/ncaaf-parity-repair-2026-10-20). Its changed service and integrity test files are retrievable. **Forensics remote status subsequently verified**: [research/ncaaf-parity-forensics-2026-10-20](https://github.com/micahp/legendarypicks/tree/research/ncaaf-parity-forensics-2026-10-20) is now at **5a1ced4a**, which includes prior **ccade77f**. The research source report, source-coverage script, frozen-holdout comparison, and ESPN live-preview scratch results are accessible. The numerical measurements below remain a **worker report, not independently rerun here**. Preserve/push the original forensics report, manifests and scripts to the research branch separately; do not merge or alter dev. Keep the original worktree and raw evidence.

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

1. **Preserve and push forensics**: candidate 54800dad is confirmed remote; push/verify research ccade77f on its forensics branch. Review docs/RESULT-ncaaf-parity-forensics.md and scripts/manifest, require reproducible commands, exact hashes, game-id comparison, and independent rerun against frozen source.
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

**One-sentence handoff (updated below):** Preserve the adopted model and 2014+ feature history; replace the hardcoded EPA exception with a pinned, validated cfbfastR game-coverage manifest and certify service fit/predict, operational results, and UI before any C2/G2h lock or default landing promotion.


## Decision update: cfbfastR coverage contract (2026-10-20 local; worker addendum dated 2026-10-21 UTC)

**Decision:** Authorize a **narrow, offline, source-pinned cfbfastR game-coverage manifest and ingest** as a prerequisite to considering the C2/G2h parity repair production-ready. Do **not** authorize a full second PBP ingestion system, changing the adopted sample, a dev merge, deployment, a T-90 scheduler, or public model locks.

Remote source verification: forensic branch \`research/ncaaf-parity-forensics-2026-10-20\` @ \`5a1ced4a\`, candidate \`candidate/ncaaf-parity-repair-2026-10-20\` @ \`54800dad\`.
The following measurements are **worker-generated reproducible outputs reviewed from GitHub**, not independently rerun by the documentation author:

- Archived \`cfbfastR_cfb_pbp\` contains plays for **3,523 of 3,524** historical candidate games and matches research \`epa_diff\` eligibility with **zero disagreements**. One absent game, \`401778314\`, is not an identity failure; it lacks plays in that source.
- Production ESPN drive-source coverage marks **3,474 of 3,524**, mismatching the research eligibility on **49** games. The production \`ncaa_mfb_pbp_cfbfastr\` game IDs intersect **zero** of this game's canonical ID population and are **not** an acceptable zero-effort replacement.
- The candidate \`service.fit\`/\`predict\` matches the committed frozen 2025 holdout on **807** rows: C2 max \`3.33e-16\`; G2h max \`1.09e-13\`.
- A **scratch-only, uncertified** ESPN snapshot dry run had 65 fixtures, with 3 already started; 62 upcoming fixtures / 186 preview rows across three models had source-matching kickoffs and **no locks**. No neutral-site fixture was exercised. No parity certificate exists.

### Minimal data implementation contract

1. Generate offline from the **same pinned archival \`cfbfastR_cfb_pbp\` PBP file set** used by research, ideally from original game IDs that already match the Phase 3 schedule population. Derive \`play_count\` and \`has_source_plays = play_count > 0\` at the canonical game ID. Export only coverage metadata unless deeper PBP data is independently needed and approved.
2. Persist a versioned, immutable game-coverage table or file (e.g., \`game_id\`, \`season\`, \`source_dataset\`, \`source_file_sha256\`, \`snapshot_id\`, \`play_count\`, \`coverage_status\`, \`ingested_at_utc\`). Pin a reproducible snapshot and manifest hash. Attach the manifest fingerprint to model/data certification so a changed archive cannot silently change historical eligibility.
3. **Three-valued coverage:** \`has_plays\`, \`no_plays_in_complete_snapshot\`, \`unknown_source_or_identity\`. An absent game in a **validated complete pinned source snapshot** can be excluded from historical research training; a missing source-season file, corrupt archive, incomplete ingest or ambiguous/unresolved ID is **unknown** and must halt parity/official model certification, not be treated as zero.
4. Join **only by verified game ID**, with game-date/team/season cross-checks against the published fixture spine. Never join this source to production \`ncaa_mfb_pbp_cfbfastr\` by assuming the IDs match; if future crosswalk work is needed, build and audit an explicit one-to-one mapping with ambiguous matches quarantined.
5. Eligibility applies **only to completed historical training rows** under the versioned adopted Phase 3 research protocol, **never to upcoming fixtures**, which naturally have no play-by-play yet. Ensure future games can be previewed with properly as-of drive ratings even when no coverage record for the future kickoff exists. Coverage is a property of an archive, not a statement that a player did or did not play.
6. The candidate's hardcoded \`401778314\` exclusion may remain in **frozen parity fixtures** only. No exception-by-ID is permitted in the production fitted population. The resulting training set must reproduce the exact 3,523/3,524 historical eligibility and the original 2,397 2023–25 evaluated games under the pinned input version.
7. Keep the separate adopted feature-history dependency on **2014 onward** intact. Do not shorten it to 2022; the root cause of the original parity failure was too little history. Build features offline; serving reads only persisted snapshots, never full archive files or ESPN on an HTTP request. Review usage rights before distributing any underlying PBP records.

### New blocking tests

- **Corpus reconciliation:** for every one of the 3,524 games, compare coverage state to the original adopted research availability; assert zero disagreement, source-season presence, identity uniqueness and source SHA stability. Explicitly confirm \`401778314\` excluded by data, not source-code literal.
- **Fail closed:** delete one required archive season, mutate coverage for the excluded game, or substitute a mismatched ID namespace; parity and lock certification must fail. Test no false historical exclusion on source-outage.
- **True production path:** parity runner must call the same \`service.fit\`/\`predict\` path used by the live \`--run\` forecaster for every research date block (plus a separate frozen 2025 holdout), retaining the **1e-6 max per-row delta** rule and matching training identity. Check scaler application and archive fingerprints.
- **Live fixture separation:** 65-fixture recorded slate, three started and 62 still upcoming. Test that an upcoming game with no source PBP is **included**, not excluded. Add a neutral-site fixture and assert official kickoff, team/conference and data-cutoff values.
- **Operations:** independently source-confirm final results before grading; audit incomplete datasets, status/legacy rows and frontend visual states on an expressly authorized server. No retroactive promotion of the three historically early-created legacy predictions.

### Promotion decision

**Research parity reproducible; candidate appears equivalent to the adopted model; production adoption remains conditional.** Once the game-coverage manifest, true forecasting-path certificate and operational QA all pass, open a code-review PR into \`dev\` for human approval. Do not issue live locks or schedule T-90 automatically under this decision.

**T-90 scheduler remains separately gated.**


## Coverage stage review: 20cc4334 (2026-10-20)

Remote candidate verified at \`20cc433468a360d9a4ecd8878806bfd9bcb67d06\`. New files include \`backend/fbs_cfbfastr_coverage.py\`, the hashed coverage CSV+manifest in \`backend/fbs_coverage/\`, and revised production service, parity runner and tests. This source review is **not** an independently executed 2,397-row reproduction. Worker reports 33 FBS tests, C2 exact and G2h max 1.5e-8 in the true service fit/predict parity gate, and 62/62 upcoming games in a scratch, preview-only slate. Previous hardcoded game-ID exclusion has been removed. Locks and real-environment certificate remain blocked.

### Decision 1: missing source dates for 42 games

**Accept as a specifically marked, lower-assurance source identity tier for historical training, conditionally.** A missing PBP start-date is not evidence of a wrong game. The source matches the exact game ID in the proper season, and the normalized set of both participants matches the scheduled fixture. The manifest explicitly labels \`teams_only_source_date_missing\` instead of pretending it passed a date cross-check.

Before certification, export all 42 distinct \`season, game_id, scheduled kickoff, home, away, identity_check, source sha, play count\` rows. Cross-check those 42 independently to an ESPN/publisher schedule on game ID, season, participants, and start day when such reference is available; report exceptions rather than hiding them. Assert IDs are unique within season and that no known source start-date contradicts the schedule. Include the 42-row count and its game IDs in the certification evidence; fail loudly on a future increase or mismatch until reviewed. This tier is **not** sufficient evidence of final status for grading.

Do not rewrite original source dates, fabricate dates, drop the 42 rows to improve metrics, or convert \`teams_only_source_date_missing\` to \`teams_and_date\`.

### Decision 2: 11 stale 2026 schedule completion flags

**Accept play-by-play evidence over the older 2026-10-17 snapshot for the narrow fact \`has_plays\` only.** This permits reproduction of the frozen *historical research eligibility* without the snapshot's stale completed indicator incorrectly removing games. The output must show the source snapshot date and all 11 discrepant IDs.

**Do not equate \`has_plays\` with \`source-confirmed final\`.** A game can have play rows during live play, after postponement, or without a complete/certified final. Grading and completed-game training eligibility require a separate final-status/score reconciliation against authoritative ESPN (or an equivalent independent published final-status source), correct season/home-away identity, and verified outcome. Until implemented, **do not grade official NCAAF predictions**, and do not treat an archive row with a score and PBP as automatically final. Refresh or reconcile the schedule status snapshot in an offline ingest; keep the original frozen research snapshot pinned for parity so the research ledger is never silently rewritten. Report research-population parity separately from current operating completeness.

### Decision 3: parity certificate vs operational lock authorization

**Approve generating and examining a parity certificate in an isolated scratch environment only**, using an explicitly specified disposable \`--db\` directory, with no scheduled runner, no live data writes and no copied certificate to a shared model/production DB directory. Preserve the evidence (code/module fingerprints, ledger hash, manifest hash, exact scored population, per-game max deltas) and assert a mutated manifest/estimator invalidates that certificate.

**Do not issue or place a passing certificate beside the actual dev/production model DB yet.** In the current runner, \`--parity\` creates a certificate next to the selected DB, and \`--run\` uses a matching certificate to enable \`store.lock_forecasts\`. A real-environment certificate is therefore an *operational gate*, not a harmless research note. Grading's current \`has_plays\` check does not yet verify ESPN's final-status flag. Existing live QA, browser QA, full coverage audits, synthetic neutral-site fixture, grading safety and explicit T-90 scheduling authorization remain mandatory.

### Next worker instructions and acceptance

1. Export the 42 missing-source-date identities and cross-check them to an independent published game schedule; report exact exceptions and make source-identity tier visible in the audit.
2. Export/reconcile the 11 stale \`schedule_completed\` flags; distinguish \`has_plays\`, \`authoritative_final\`, \`historical_model_eligible\`, and \`official_grade_eligible\` rather than conflating them. Build a strictly read-only test against authoritative published final status and scores; unit tests must show in-progress PBP never triggers a grade.
3. Generate a **scratch-only** parity certificate, verifying the true service fit/predict path and all relevant hashes. Prove it revokes when the CSV/manifest/inputs/code change. Do not copy that certificate to dev/prod. Test \`--run\` remains lock-blocked absent a real certificate.
4. Add a proper synthetic neutral-site game that reaches fit/predict and validates every relevant field, plus a late/missing/partial game outcome and status fixture.
5. Prepare a code-review diff/PR for owner inspection when all code integrity and operator QA gates are met. Do not merge to dev, restart \`:3096\`, deploy, or schedule live T-90 work on this authority.

**Final ruling:** historical model parity is sufficiently promising to continue staged review; **official locking, grading, production readiness and default Forecasts landing are still NOT APPROVED**.
