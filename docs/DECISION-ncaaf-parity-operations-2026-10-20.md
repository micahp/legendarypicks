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
