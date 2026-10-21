# NCAAF forecasting operations: outages, postponements and terminal statuses

Date: 2026-10-20
Status: **Policy approved for candidate implementation and isolated tests only.**
Candidate reviewed: `candidate/ncaaf-parity-repair-2026-10-20` @ `977cf4449ac4ae1ff3e4d841c09e053c362cd117`.
Not authorized: merge to dev, modify an operational DB, issue an operational certificate, run a T-90 scheduler, deploy, or enable live forecast locks.

## Evidence and operational boundary

The worker reports and remote source reflects a scratch-only parity certificate, 42 lower-assurance source-date identity matches reconciled to ESPN identities/finals, 11 stale 2026 schedule-completion flags reconciled to ESPN final scores, and an ESPN final-status grading guard. The isolated clock test locked two 23:00 UTC fixtures at simulated 21:45 UTC and kept the remaining 63 as previews. These are *test results*, not authorization to create official locks.

**Current coupling to remove:** `backend/fbs_model_runner.py:run()` calls `espn_final_scores(store.pending_grades(...))` before writing previews, locks, ratings or grades. If an old scoreboard read fails, `run()` halts the entire operation even when the *upcoming* slate has independently passed verification. One failed historical final-status request should not cause an unrelated valid T-90 window to be missed.

## Decision A: ESPN outage policy

Distinguish **current-fixture integrity** from **past-game outcome grading**.

- **Unverified current slate:** halt *new previews and locks* if any required date of the current scoreboard window is unreadable, stale beyond the documented freshness window, incomplete or inconsistent. Do not treat unavailable dates as days with no games. Do not substitute a stale cache for current kickoff and status confirmation at lock time. Preserve prior immutable forecasts. Report an explicit `slate_unavailable` incident and missed T-90 window if it expires.
- **Past-game grading board unavailable:** defer *grading* those games and report `grade_source_unavailable`, but permit independently verified current-slate forecasts to continue **if** its own source fetch, code/coverage parity certificate, fixture IDs, real-time kickoff/status and all other lock gates pass.
- Preserve fail-loud behavior on a confirmed **archive/ESPN score mismatch**. Stop grades for the affected results, alert, and quarantine for reconciliation; do not poison forecasts for unrelated games solely due to a historical score discrepancy.
- Avoid turning one multi-purpose run with global early writes into a partially committed operation. Refactor into an explicit **preflight and separate database transactions/commands** for forecast/lock vs grade, with source-provenance and a truthful per-subsystem run report. Failed forecast preflight must not create a *new* preview/lock; failed grade preflight must not write any result from the failed batch. Prefer grouping grades in verifiable atomic batches rather than mixing them with model writes.
- Any future automatic retry/backoff must obey the upstream feed's limits, avoid duplicated locks, and record distinct feed health, timestamp, request status and number of delayed games. A fallback provider is a new independently reconciled data decision.

## Decision B: postponed, cancelled, abandoned, suspended and missing fixtures

**Never infer a final outcome from an ESPN event's absence or just the existence of play-by-play rows.** Use the provider's actual status fields and current kickoff to govern state transitions.

- `scheduled` / `in_progress`: preview when safely before kickoff; **lock only pre-kickoff in its approved window**, with matching event ID, present-day kickoff, certified model and complete source verification. Started events never lock, even if delayed start times are ambiguous.
- `postponed` / `suspended` / `delayed` with uncertain resumption: suspend *new locks and grades*; flag `schedule_unresolved`, preserving every immutable prediction. If reliable official provider assigns a verified new kickoff before the game starts, version a *new fixture schedule revision* and regenerate the preview; no backdating. Decide any new lock separately under that fresh pregame state.
- `cancelled` / `no_contest` / `abandoned` / `forfeit` where ordinary final-game settlement is not supported: mark `void_or_ungraded` with the source and observed time. Never classify as win/loss or include in official Brier; do not delete or alter prior locked p_home. Do not conflate a void with a model miss or score 0.
- `completed`: only grade after **ESPN reports final status and both final scores**, the recorded event ID/home/away/kickoff revision match, and the archive agrees where available. Do not treat live score or partial archive as final. Reconcile overtime/forfeit/final-type as needed rather than score a nonstandard termination as an ordinary game.
- `absent_from_board` / `feed_error` / `unknown_status`: **unknown**. Retain the record and retry on a bounded schedule, never silently treat as completed/cancelled/missed. Escalate an alert after a recorded SLA, e.g. 24 hours post-kickoff, and retain it in a visible unresolved queue until a source-based terminal status is established. The SLA is alert timing, not permission to classify or grade.
- A `missed_t90_window` is a *separate operational failure*, not a game outcome. Postponed/cancelled fixtures must not inflate missed-window metrics while no eligible lock window exists.
- Retain published, immutable original lock rows and their source kickoff. Any reschedule uses a separate revision/status record and, if allowed, a separate lock identity with a unique game + model + kickoff revision. Under the current single-row `PRIMARY KEY(game_id,model)`, do **not** try to write a second lock into the same primary key or update immutability triggers. Introduce versioned fixture/lock tracking first and specify which revision, if any, counts in the official record; never count both as two independent game outcomes.

## Concrete implementation checks

1. Build a state-machine test matrix for on-time scheduled, in-progress, ESPN delayed, postponed/new start, cancelled, suspended then resumed, unlisted-on-day-board, failed board fetch, true final, score mismatch, and changed opponent/event ID. Explicitly distinguish game status from grading status from lock status.
2. Simulate **historical grading request failure with a fresh, valid future slate**, prove certified new previews/locks can proceed and grading remains untouched. Simulate **current slate failure with a fresh historical final**, prove **no new lock/previews** and safe independent grading if invoked.
3. Verify the live scoreboard is rechecked at or near each lock and that no score/status data from an earlier snapshot is mistaken for a fresh source. A cached replay is for **tests only**, not live lock authorization.
4. Test postponed/cancelled **before T-90** and **inside T-90**, a new kickoff after postponement, and an existing locked row that subsequently becomes cancelled. Assert immutable probabilities unchanged, correct void accounting and no false win/loss/missed lock.
5. Test unfinished/unlisted past events have a bounded retry/alert lifecycle rather than lingering silently forever. Verify old scheduled date and Eastern date fallback behavior, especially midnight UTC, to avoid a permanently lost event after a reschedule.
6. Exercise a complete synthetic neutral-site game through feature generation and actual `service.fit/predict` and confirm `neutral_site` and conference inputs, not just flag pass-through.
7. Keep the research parity and hash fingerprint constraints unchanged. Re-issue scratch certificates after relevant code changes; never copy them beside the operational DB. No T-90 scheduler or deployment without separate authorization.
8. Perform browser QA on an **owner-authorized isolated server** with fixtures for source-down, preview, locked, delayed, cancelled, void and records. Never restart the existing managed `:3096` server without authorization.

## Promotion

This is permission to **implement and test** the above on a candidate branch, not permission to ship. A reviewed PR to dev is the next step only after documented test evidence and visual QA. Operational parity certification and scheduled T-90 locking are separate, later authorization decisions.


## Review of lifecycle candidate 4f4385ef (2026-10-20)

Remote candidate `candidate/ncaaf-parity-repair-2026-10-20` verified at `4f4385efeb443a162b015a7a61f2101b3320024e`. The worker reports 72 tests, the unchanged 2,397-game true-path parity (C2 0, G2h 1.5e-8), 53/53 cached ESPN grade checks, and an isolated scratch certificate. These are worker reports reviewed against committed code; this documentation update did not execute the remote data-dependent tests.

### Owner policy ruling: unknown statuses and operational metrics

**Reject counting every unknown-status unverified game as an ordinary `missed_t90_window`.** An unverified fixture was not eligible for a lock under the approved safety rule. Use disjoint reasons and counters:

- `locked_eligible`: independently verified, valid scheduled status and kickoff, certified, locked inside its official window.
- `missed_t90_window`: an eligible, verified scheduled fixture reached kickoff without its required lock (including runner not scheduled, certificate absent, or process failure); annotate reason.
- `blocked_unverified_at_cutoff`: fixture existed in previews but latest required source/status/identity could not be verified at its cutoff. Not part of *eligible* lock opportunities; still an operational loss requiring alert and root-cause record. Retain last verified fixture and changed-status evidence for diagnostics.
- `no_eligible_window`: postponed, delayed with unconfirmed kickoff, suspended, cancelled, abandoned, no-contest, explicit identity mismatch; never silently classify as a successful or missed eligible lock.

On source outages, retain separate `source_unavailable` / `blocked_unverified` incidents. Do not infer a valid final kickoff, status, or settlement from stale previews or from the absence of an ESPN event. If status later becomes authoritative, append a source-based resolution; do not retroactively claim a frozen lock.

The current `record_missed_windows()` in `backend/fbs_model_store.py` excludes `NO_WINDOW_LIFECYCLES` and identity changes but **does not exclude `unknown`**. Fix before promotion; add explicit verification-gap tests.

### Owner policy ruling: retries and alerts

**Approve** historical unresolved-result exponential retry beginning at 15 minutes and capped at **six hours**, and an unresolved-grade alert after **24 hours after kickoff**. These are operational limits, not a licence to infer an outcome or trigger a new lock.

**Not sufficient for pregame failures.** If a candidate enters an unverified state during a prospective T-90 lock window, create an **immediate lock-risk alert** and visible `blocked_unverified` incident. Do not wait 24 hours after kickoff. Schedule-level polling or automatic retries in a live system remain unapproved. The queue/status implementation must not rely on a previously issued lock to discover unknown pregame fixtures.

The current `forecast_step()` upserts `fbs_game_status` for unknown fixtures but does not add an `fbs_unresolved` entry for every such game. The `record_unresolved()` flow is primarily in historical grading and currently requires a locked, due-to-grade game. The agent must add a first-class pregame incident lifecycle and observable queue for games that never locked.

### Code-review blockers separate from model parity

1. **Forecast transaction boundary.** `forecast_step()` claims a preflight-and-write transaction, but helpers including `observe_fixture()`, `set_game_status()`, `upsert_previews()`, `lock_forecasts()`, and `record_missed_windows()` commit independently, as do reporting helpers. Refactor helpers to allow `commit=False`, and use one explicit transaction for the verified forecast/write batch; if it fails, rollback all fixture/status/preview/lock/missed-event/rating/meta changes in that batch. Record failure information separately if useful. Tests must inject a failure *after* writing fixtures and previews but *before* lock insertion and assert no partial state. Keep historical grade transaction independent.
2. **Migration preflight.** `open_db(readonly=False)` executes schema and `_migrate()`. Before any operational-use approval, create backup + integrity-check + schema-diff + rollback/rehearsal evidence on a separately copied DB. Verify historical immutable triggers, legacy exclusion, new tables/columns and no row mutation beyond documented migration. Do not open the operational DB writable during this phase.
3. **Fresh public-source dry run.** Execute a preview-only dry run against *live* ESPN in a scratch DB, without a valid operational parity certificate, and reconcile event IDs, status names, kickoff timestamps, duplicates, missing/contradictory status, FBS team eligibility, and model rows. No locks.
4. **True neutral-site integration.** Current test stubs the Elo base; add a deterministic fixture that exercises the real baseline from actual event loading through final `service.fit/predict` and checks the neutral-home adjustment. Current model-side conference wiring is useful but is not full end-to-end coverage.
5. **Browser QA.** Requires explicitly authorized isolated server; no restart of existing managed `:3096` or prod. Inspect visible previews, locks, unverified state, postponed/cancelled, grade/void, source outage, coverage/records and legacy exclusions.
6. **Certificate.** Passing scratch certificate authorizes no operational lock. After code changes, code and coverage fingerprints must invalidate the earlier certificate. Keep the live DB certificate absent and locks disabled, no scheduler or dev merge until separate owner approval.

**Promotion verdict:** continue candidate fixes and isolated testing. No operational certificate, deployment, T-90 schedule, or `dev` merge authorized by this note.


## Follow-up: timezone capture, explicit migration and season attribution (5c0f37ab)

Decision date: 2026-10-20. Remote candidate \`candidate/ncaaf-parity-repair-2026-10-20\` verified at \`5c0f37ab1e3e6b830130b9fb1098fbffc1f59ebb\`. Reported worker verification: 78 passing tests, 2,397/2,397 research parity rows (G2/C2 0; G2h max 1.5e-8), an isolated 109-game live ESPN preview run with 327 previews and zero locks, and repeatable migration rehearsal on a copy of the 336-row legacy database. These are worker test reports, not an independent execution here.

### Decision 1: capture across UTC midnight — APPROVED for candidate only

**Fix before dev review.** The code currently requests \`(now + offset days).strftime("%Y%m%d")\` in UTC. An Eastern-local evening game can enter its T-90 window after 00:00 UTC while still belonging to the previous ESPN Eastern scoreboard day, making it disappear from the fetch.

Use \`America/New_York\` and derive **all required Eastern scoreboard dates** to cover the requested future kickoff interval \`(now, now + horizon]\`. Include a neighbouring date only where needed for boundary/provider-placement robustness, with no unbounded additional daily requests. Require daylight-saving aware time conversion. Dedupe the same ESPN event ID across fetched dates **only if team identity, start timestamp, lifecycle/status and season agree**; otherwise mark slate unverified and fail closed, rather than arbitrarily keeping first.

**Yes, filter new previews and lock candidates to kickoff strictly after \`now\`**, current verified pregame status and correct game season. This is not a grading filter. Already-started games stay eligible for postgame lifecycle and grading where independently confirmed final. Don't allow a past game to be reintroduced as a new pregame forecast. Preserve the separate unverified/blocked queue for previously observed prospective fixtures that drop off the current board, and test Eastern-date out-of-window avoidance.

Explicit temporal regressions should cover 00:30 UTC / 22:00 Eastern kickoff at 02:00 UTC on the DST side of midnight; standard-time winter equivalent; DST transition days; midnight in both timezones; exact kickoff boundary; the **end-of-horizon** inclusion/exclusion; and duplicate/conflicting rows on neighbouring boards. The board request set used for absent-from-board classification must match the exact dates actually queried.

Re-run the actual production-path parity check and a new **preview-only live ESPN dry run with a scratch, uncertified DB**; compare game/preview counts, event IDs, kickoff and status against source. A change in number of games caused by excluding already-started events is expected and should be explicitly explained, not hidden to maintain 109.

### Decision 2: implicit migrations — REJECT

The current \`fbs_model_store.open_db(readonly=False)\` still performs \`executescript(SCHEMA)\`, \`_migrate()\`, \`executescript(TRIGGERS)\`, and a commit on each open. This mutates an existing DB, can change its triggers and columns, and bypasses the approved backup/integrity/row-digest process.

**Require explicit schema migration for any existing DB:** a runtime writable open must validate schema version and required triggers and fail closed with \`migration_required\` without altering its file if version differs. An explicitly separate \`migrate()\` command, with collision-safe backup, SQLite integrity check, unchanged original-row digest, trigger verification and reproducible evidence, is the only authorized path to schema change. A truly new scratch DB may be explicitly initialized with a separate \`initialize_new_db()\` operation. Do not accidentally conflate an empty new DB with a legacy unmigrated file. Validate a second migration is idempotent and no backup gets overwritten. **Do not migrate or open the operational DB writable on this authority.**

### Decision 3: football season versus calendar year — REQUIRED fix

The current \`g2_for_slate()\` still uses \`int(row.kickoff_utc.year)\` for team-conference lookup and the inserted Elo event, ignoring the ESPN \`row.season\` field that \`event_facts()\` already provides. January bowls for the **prior football season** can be attributed to the next calendar year. In \`forecast_step()\`, \`season=int(frame["season"].max())\` is also passed to \`slate_features()\` and \`team_ratings()\`; this could select the wrong feature/rating season, especially at season boundaries.

Use **authoritative event football season** per game through Elo, FBS membership, feature lookup, fixture revisions and stored predictions. Validate/match season with independently loaded season source; missing/contradictory season blocks official locks rather than falling back to calendar year. Make \`slate_features()\` compute as-of team ratings **per target game**, strictly before its kickoff. If current football season has no earlier games, make prior-season fallback explicit, source-provenanced and test it; never silently use a future week or an unrelated season. Separate model fit cutoff from season attribution: \`service.fit(..., now)\` currently time-filters by \`utc_date < as_of\`; preserve this property, while ensuring its training frame cannot contain source outcomes or feature histories captured post-cutoff. \`team_ratings()\` should not silently attribute all output to the training frame's maximum season. Tests for early season, season rollover, 2026-season January 2027 game, conference realignment and missing current-season PBP are mandatory.

Maintain frozen 2023–2025 reference parity and its **actual existing per-game \`1e-6\` check**; the runner's unused stale \`PARITY_TOLERANCE=5e-4\` constant does not control \`check_parity()\` and should be deleted or aligned, without loosening the gate.

### Promotion and authorization

These changes are authorized as candidate research/operational-hardening code and tests **only**. After the three fixes: inspect schema guard on unmigrated copies, re-run 2,397-game parity and all tests, perform live ESPN preview-only scratch check, and present a reviewable diff/PR candidate. **Browser QA on an owner-authorized isolated server remains open.** No merge to dev, production/development server restart, operational certificate, live database migration, T-90 scheduler, locked forecast or production deployment is authorized by this note.


## Review of a4cda8c3: postseason lock policy, horizon and legacy audits

Decision date: 2026-10-21. Confirmed remote candidate \`candidate/ncaaf-parity-repair-2026-10-20\` at \`a4cda8c3d1edcd7e7f5a10d7b8f5799415799629\`; commit changes only candidate code and tests. Worker reports 110 FBS tests passing, 2,397/2,397 research parity (G2 and C2 0; G2h maximum row delta 1.5e-8), a fresh uncertified ESPN scratch run (112 ESPN events, 64 eligible forecast games/192 preview rows, 0 locks) and a successful copy-only explicit migration rehearsal preserving legacy rows. These are agent-reported empirical results; this document review inspected committed code but did **not** independently rerun the data-dependent tests.

### A. Postseason forecast status: research-only previews approved; official locks NOT approved

\`slate_features()\` correctly builds current as-of features from completed team history, but the committed historical research rows assign postseason bowls week 1, making their as-of inputs differ from what a real postseason forecast should know. The agent measured differences up to 10.8 feature units on three 2025 bowls. Historical parity preserves the **old**, potentially stale bowl-feature encoding; a passing parity check is not prospective validation of corrected live bowl predictions.

- Allow **internal/research-only** postseason previews with conspicuous \`postseason_research_hold\` provenance. Do not treat those previews as validated forecasts or official performance records, show them as official player-facing selections, or automatically lock them.
- **Current code has a metric bug:** \`_write_forecast()\` keeps bowls in \`fbs_previews\` and omits them from \`lock_rows\`, but their pregame lifecycle remains \`scheduled\`. \`fbs_model_store.window_outcome()\` therefore classifies such an unlocked, eligible-looking preview as \`missed_t90_window\` at kickoff. Record a **durable exclusion reason** \`postseason_research_hold\` on each affected fixture/model before cutoff, and classify it as \`window_not_eligible\`; do not inflate verified missed-window counts. Test this *after simulated kickoff*, not just while the forecast is pending. Ensure the exclusion survives later status changes (including final results).
- Preserve ESPN \`season_type=3\` and postseason phase in constructed Elo events and report provenance rather than hardcoding \`game_phase="Regular season"\` for bowl previews (currently \`g2_for_slate()\`). Evaluate whether this changes G2 predictions, with explicit tests. Do not relax other lock gates.
- Correct bowl chronological ordering and any resulting refitting/rebaselining **in a separate preregistered research track**. Compare original versus corrected 2023–2025 per-game features/outcomes and out-of-time proper scores. Do not silently rewrite the frozen parity ledger, its certificate gate, or existing C2/G2h parameter results to force adoption. Leave official bowl locks disabled until a separate owner research decision.

### B. Ten-day forecast horizon: include the full Eastern boundary date — APPROVED

Interpret the displayed \`days=10\` preview horizon as \`now < kickoff < midnight after the Eastern date containing (now + 10 elapsed days)\`. That explicitly includes **all of Saturday 2026-10-31** in the agent's reported Oct 21 Eastern run instead of cutting off at 01:15 Eastern. Calculate the **exclusive next-local-midnight boundary** with \`America/New_York\`/a timezone-aware calendar date; don't extend the UTC instant by a naïve fixed 24 hours, because the DST transition changes elapsed time.

The existing \`scoreboard_dates()\` list (previous Eastern date through the inclusive last Eastern date) can continue, and every requested board must be accounted for. **Apply the identical cutoff** in \`forecast_candidates()\`, preview inventories, and absent-from-board checks. Preserve \`kickoff > now\`, current \`scheduled\` status, and independent grading, and do not make a lock whose cutoff has passed. Tests: exactly now, exactly midnight after final date, one second before it, October 31 late kickoff, Nov 1 DST transition and dates on both sides. Rerun live scratch validation and explain any 64→109 game count increase (depending on a stable slate) without inventing fixture data.

### C. Legacy read-only opening and audits — APPROVED with schema-awareness

Allow \`open_db(readonly=True)\` on an unmigrated file, expressly for read-only schema discovery, audit, migration planning and backup. **Do not** weaken the writable \`SCHEMA_VERSION\` gate, which must continue to fail \`migration_required\` with bytes unchanged.

The \`--audit\` command must inspect \`sqlite_master\`/columns before querying each optional table and column. For a legacy DB, return useful supported legacy counts and \`schema_status="migration_required"\`, plus unavailable-feature reasons (or a structured migration-required audit result). No raw \`sqlite3.OperationalError: no such table\` and no automatic migration. Test a migrated copy and a legacy copy without optional tables/triggers, both read-only and byte-stable.

### D. Additional audit discovery: duplicate event identity must cover all forecast-driving fields

\`fbs_model_runner._identity()\` currently compares ESPN game ID, team IDs, kickoff, season, lifecycle and status, but **omits \`neutral_site\`, \`season_type\`, \`week\`, and any materially conflicting final-score/completion fields**. Two provider copies with the same basic identity but conflicting neutral flags could silently select the first and alter the Elo home adjustment. Fail closed on disagreement in any field that affects classification, forecast, eligibility or outcome; add injected duplicate tests for neutral-site and postseason type mismatches, preserving the existing same-copy deduplication path. Add a clear source exception if any provider field is known to legitimately vary by timestamp; never silently first-win.

### E. Next stage and operational authorization

Agent is authorized to implement the small policy/quality fixes above on the **candidate branch**, run unit/integrity/parity tests, and repeat a **preview-only, uncertified scratch DB** live ESPN capture and **copy-only** migration/audit check. None of these owner decisions authorize an operational DB migration, an official parity certificate, schedule installation, player-facing postseason release, live locking or production deploy.

A PR/engineering code review targeting dev can be prepared **after** those fixes are evidenced, with the postseason restriction explicit. Browser QA on an **owner-authorized isolated server** is still required before **merging** to dev or operational promotion; the server has not been authorized here. Postseason **model research** need not block code review of the regular-season lifecycle if the postseason official-lock hold and metric exclusion remain enforced; lifting that hold requires a separate research approval.


## Review of 9056257c: full Eastern horizon, postseason hold and audit

Review date: 2026-10-21. Confirmed remote candidate \`candidate/ncaaf-parity-repair-2026-10-20\` at \`9056257c5f3c2e941d98cdec1a4b08131fbc52de\`. Compared source with \`a4cda8c3\`. Agent reports 136 FBS tests, per-game 2,397/2,397 parity at 1e-6 (G2/C2 zero and G2h maximum 1.5e-8), fresh live-ESPN preview-only reconciliation of 112 games / 109 eligible / 327 previews / zero locks, and read-only/copy-only migration audits. This reviewer verified the remote implementation and committed test coverage, **not** the agent's local execution artifacts or live provider output.

### Disposition

The three previous policy corrections are now implemented: (i) the whole final Eastern date using an exclusive next-midnight cutoff, (ii) preseason/postseason source labels, durable \`postseason_research_hold\` and the exclusion from \`missed_t90_window\`, (iii) a schema-aware \`--audit\` that can inspect legacy files without changing their bytes. Source duplicate identity now includes neutral-site, week, season type, scores when final, and completion; different in-progress scores alone may differ between fetches because they are not used for pregame forecasts or final grading. Final-score conflicts fail closed.

**Approve opening a DRAFT code review/PR against dev, not merging.** Three narrow safety fixes remain as code review blockers:

1. **Defense-in-depth for postseason lock prohibition.** The runner omits held bowls from \`lock_rows\`, but \`fbs_model_store.lock_forecasts()\` currently checks only lifecycle, kickoff, fixture revision and teams. An alternate caller can pass a scheduled held-bowl row directly and insert an official lock. Make \`lock_forecasts()\` consult the persisted \`fbs_game_status.hold_reason\` and reject \`postseason_research_hold\` regardless of caller input; record a \`blocked_hold\` counter. Test direct store lock attempts, not only runner-originated rows. Preserve all other official lock gates.

2. **Expose the research hold in the exported API payload.** \`fbs_model_store.export_payload()\` currently exports previews with \`game.status="preview"\` and \`status_reason\` reflecting ESPN lifecycle; it does **not** export \`hold_reason\` on the game or model. A held scheduled bowl has no visible hold reason. Expose game-level and, if useful, per-model \`hold_reason\` and a truthful research-only status so the UI can render \`postseason_research_hold\` and exclude from official counts. Test export round trip pre- and post-kickoff and ensure a held preview cannot be mistaken for a locked/official forecast.

3. **Validate required columns at writable open.** \`schema_state()\` currently accepts \`PRAGMA user_version=SCHEMA_VERSION\` plus required tables and trigger names, but does **not** check \`REQUIRED_COLUMNS\`. A malformed or partially updated version-2 DB missing \`hold_reason\` could be deemed current and passed to writers, causing runtime failure. Include required-column checks in schema validation. Test a version-2 file with all expected tables/triggers but a missing hold column; \`open_db(readonly=False)\` must fail \`migration_required\` without touching bytes, and explicit \`migrate()\` on a copy must recover it safely.

### Non-blockers and remaining gates

- The absence of live December postseason fixtures in the October ESPN capture window is **not** a blocker for regular-season code review or a reason to weaken the hold. Keep bowl locks disabled and schedule separate real-data bowl verification and historical bowl feature-chronology research before any bowl lock authorization.
- In-progress ESPN score copies may legitimately differ when both are non-final; do not grade from them. The existing rule of comparing final scores when both copies report final is acceptable, provided lifecycle/completion disagreement fails closed and independent final/archive cross-checks remain mandatory.
- Before merge to dev: rerun unit/falsification tests and frozen parity after the three small fixes, repeat scratch preview-only source reconciliation where necessary, inspect candidate diff, and perform **browser QA on an expressly owner-authorized isolated server**. Do not restart managed \`:3096\`, merge, deploy, change the operational DB, issue an operational parity certificate or enable live T-90 on this authority.


## Draft PR #15 review at 07dfd7b1 (2026-10-21)

Confirmed [draft PR #15](https://github.com/micahp/legendarypicks/pull/15) at \`07dfd7b102397303b830fe3973b18dbe7c363d58\` (base \`dev\`). GitHub mergeability now reports \`clean\`; PR is still draft and open, not merged. Compared PR files to \`dev\`: 15 files changed, 22,840 additions, 264 deletions, including the source-pinned generated coverage CSV and no frontend changes. No GitHub workflow runs were found for the head commit at the time of review. The agent reports 143 FBS tests passing, 2,397/2,397 reference parity, and 109 live ESPN preview games/327 rows with zero official locks. These agent-run tests were not independently rerun during this review.

### Backend dispositions

- **Direct lock guard:** \`fbs_model_store.persisted_hold()\` checks the fixture-level persisted hold or the specific model's preview hold and \`lock_forecasts()\` increments \`blocked_hold\` without locking. Source inspection confirms the guard. Tests include direct store mutation/falsification.
- **Research-only export:** \`export_payload()\` sets \`research_hold\`, \`official=false\`, \`research_only=true\`, and \`hold_reason\` for normal fixture-level postseason holds, and refuses to export a held fixture that also has an official lock. The old app does not know this status yet.
- **Schema validation:** \`schema_state()\` checks every \`REQUIRED_COLUMNS\` entry as well as schema version, tables and triggers. Explicit backup-backed migration remains required for writable access to older schemas.

**One additional export edge case before integration signoff:** a *model-preview-only* hold (with no fixture-level \`fbs_game_status.hold_reason\`) is valid under \`persisted_hold()\`. In \`export_payload()\`, the game-level \`hold_reason\` and \`research_only\` are eventually set from fixture status only, and iterating multiple previews can overwrite the aggregate \`research_hold\` game status with a later non-held \`preview\`. Test and resolve per-model/aggregate semantics deterministically; model-level holds cannot be silently lost. Fixture-level postseason holds should remain all-model holds. If mixed model states are unsupported, expose an explicit consistency failure instead of silently downgrading.

### Independent generated coverage artifact check

Fetched the committed Git blob \`f210b28db6e27cdfbc9f279f902f6882601a3623\` corresponding to \`backend/fbs_coverage/cfbfastr_pbp_coverage.csv\`. Independently computed the SHA-256 of the complete UTF-8 CSV in memory. It matches \`cfbfastr_pbp_coverage.manifest.json\` exactly: \`abb009b362b9eb4714d6157b398385540d20c81a1f7597b87c579d0cad28c64b\`. The generator source SHA-256 also matches \`d8f0246067ba1bd81a4104b5a3e41dd1885dd8b58b7e66ea80cb5e4fe323bac6\`. The CSV has 18,758 data rows across five seasons, each per-season per-status count matches its manifest (including zero categories), and no duplicate \`(season, game_id)\` keys were found. This verifies the **committed artifact against its manifest**, not regeneration from the underlying source parquet inputs or independent verification of their pinned source digests.

### Frontend contract required before dev merge

The current \`components/Leagues/FbsModelTab.tsx\` on \`dev\` accepts only \`preview | locked | missed | legacy\`; \`STATUS_LABEL\` does not include \`research_hold\`. PR #15 changes no frontend file, and \`components/Leagues/FbsModelTab.test.tsx\` lacks research-hold fixtures.

Before merge, extend typed payload and UI to handle \`status="research_hold"\`, \`hold_reason\`, \`research_only\`, and \`official\`. Use a conspicuous truthful **Research only — not an official forecast** label; do not describe a held bowl as a pending T-90 lock, qualifying pick or counted official projection. After kickoff, let a viewer inspect the held/research state without including it in the official record and Brier. Add negative tests for an official record that accidentally includes a held preview, and clear UI fallbacks for preview, lock, legacy, missed and source unavailable. Check possible mixed per-model hold states. Do not hide upcoming predictions merely because \`state="awaiting_first_lock"\`.

**Review status:** backend changes and coverage manifest integrity are accepted for continuing code review. Keep the PR in draft. Frontend integration, the preview-only hold export edge-case, isolated-browser QA on an owner-authorized server, and ordinary PR verification remain gating. No permission to merge to dev, migrate the operational DB, create an operational certificate, enable official live T-90 locks, change prod, restart the managed server or lift postseason lock restrictions.
