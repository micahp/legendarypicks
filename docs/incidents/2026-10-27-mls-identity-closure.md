# MLS identity and roster closure (2026-10-27 incident)

**Status: NOT DONE.** All 23 acceptance tests pass, and the 1,040 baseline people resolve correctly. The closure rule
is not met, for the reasons in section 7. Nothing was merged, deployed, or changed in production. The legacy MLS path
remains the production default. The production cutover is a separate authorization.

Branch: `feat/mls-cutover-2026-10-28`, based on `origin/dev` at `382f5ffe`. Code head: `0e8894a2`. This report is
committed after that head. Evidence files are in `docs/incidents/2026-10-27-mls-identity-closure-evidence/`, with
checksums in its `SHA256SUMS`.

## 1. Commits and changed files

The branch contains the MLS shadow and audit work, which is already on the feature branch, and the cutover work.

| Commit | Change |
|---|---|
| `2e1740da` | Acceptance contract: 23 tests and the production-shaped fixture (written first) |
| `ae653071` | Identity onboarding: corroborated creation, rekeys, review queue |
| `e9389ee6` | Snapshot: hold a disputed person; flag lost keys; atomic publish |
| `d9767ba8` | Membership-gated resolution and the roster cycle, off by default |
| `7d13744f` | Roster job: opt-in `--mls-cutover`, legacy path unchanged by default |
| `0418475d` | End-to-end gate and the migrated-copy builder |
| `dde1cb0b` | Design document |
| `b3c43b53` | Gate the other stale-row consumers: backfill, spine planning, team refresh |
| `0e8894a2` | Props for a past game resolve against the membership on that day |

Earlier commits on the branch (`1831cc54` to `a675a966`) are the snapshot, shadow, audit, and resolver-audit work.

Files changed against `origin/dev` (25 files, 28,592 insertions, 4 deletions):

- New modules: `backend/mls_identity.py`, `backend/mls_resolution.py`, `backend/mls_roster.py`, `backend/mls_cutover_copy.py`
- Changed MLS modules: `backend/mls_snapshot.py`, `backend/test_mls_snapshot.py`
- Shared modules, minimal changes: `backend/_core.py` (dispatch wrapper, off by default), `backend/ingest_published_rosters.py` (opt-in flag), `backend/backfill_from_published_roster.py`, `backend/spine_merge.py`, `backend/refresh_soccer_player_teams.py` (each gated, off by default)
- Tests: `backend/test_mls_cutover_acceptance.py`, `backend/test_mls_cutover_consumers.py`, `backend/test_mls_cutover_e2e.py`
- Fixtures: `backend/fixtures/mls_cutover_2026-10-28.json`
- Documentation: `docs/mls-snapshot-design.md`, `docs/mls-resolver-audit-2026-10-28.md`, `docs/mls-snapshot-shadow-2026-10-28.md`, this report

## 2. Acceptance tests (`backend/test_mls_cutover_acceptance.py`)

Before implementation, against the test file as it stood then: 0 passed, 18 failed, 5 errored. The five errors were
the `cutover` fixture, which fails until the gate exists. The record is `docs/incidents/2026-10-27-mls-identity-closure-evidence/baseline_before_implementation.log`.

Final, on commit `0e8894a2`:

| # | Test | Result | What it asserts |
|---|---|---|---|
| 1 | `test_existing_population` | PASS | 1,855 source records resolve to 1,040 people; no player created; no bind changed |
| 2 | `test_new_signing` | PASS | A corroborated new player is created once; repeats create nothing; a disputed date of birth creates nothing |
| 3 | `test_single_source_new_signing` | PASS | An unpaired new key is queued; coverage partial; existing teams unchanged |
| 4 | `test_namesake` | PASS | Same name and club never merges; both keys queued `namesake_exists`; existing binds unchanged |
| 5 | `test_rekey` | PASS | Unverified rekey: no duplicate, no steal, flagged; verified rekey: bound to the same person |
| 6 | `test_source_id_collision` | PASS | Key `77` at two publishers never carries or binds across people |
| 7 | `test_departure` | PASS | Leaves current membership; binds, history, game logs kept |
| 8 | `test_transfer` | PASS | Same person; new club now; historical membership keeps the old club |
| 9 | `test_single_source_disappearance` | PASS | Retained and flagged `source_lost`; MLS-only people are not flagged |
| 10 | `test_publisher_disagreement` | PASS | The disputed person held at the last verified club; others update |
| 11 | `test_conflict_recovery` | PASS | Agreement returns the person to active; hold cleared; coverage verified |
| 12 | `test_incomplete_fetch` | PASS | Missing club, eight players gone from one club, empty publisher: each refused, last snapshot kept |
| 13 | `test_degraded_recovery` | PASS | Healthy fetch after a failure publishes or refreshes normally |
| 14 | `test_stale_lookup` | PASS | The 16 stale people resolve without the gate and not with it |
| 15 | `test_all_resolver_paths` | PASS | Exact, normalized, alias, and roster paths all refuse a departed person; control shows legacy resolves |
| 16 | `test_historical_resolution` | PASS | Departed and transferred people resolve as of a past date; no snapshot for a date fails closed |
| 17 | `test_current_team_source` | PASS | The current club comes from the snapshot, not `players.team` or roster rows |
| 18 | `test_ligamx_lcup` | PASS | Liga MX unchanged; Leagues Cup resolves to the home person, creates no duplicate; departed home person refused |
| 19 | `test_idempotence` | PASS | Identical roster at a new time: one snapshot, verification time refreshed |
| 20 | `test_transition_idempotence` | PASS | Transfer, departure, rekey, hold, and recovery each followed by two repeats: no extra snapshot |
| 21 | `test_atomicity` | PASS | Publication fails after rows are written: nothing from the cycle is kept, including a new player |
| 22 | `test_data_integrity` | PASS | Snapshot-only cycles change no identity or history table; onboarding changes only players and binds |
| 23 | `test_health_reporting` | PASS | Partial snapshots report blockers, held, lost keys, verification time; a clean run reports verified |

Fault injection, to show the tests can fail. Five defects were reintroduced one at a time in scratch copies. Each was
caught by at least one test: corroboration removed (`test_new_signing`); gate switched off (4 tests); missing-source
check disabled (3 tests); checksum hashing events (`test_transition_idempotence`); publication not rolled back
(`test_atomicity`).

Supporting suites, all passing on the final commit: `test_mls_cutover_consumers.py` (backfill, spine, refresh, and
past-game resolution, on and off), `test_mls_cutover_e2e.py` (the real roster job, fixture and migrated copy), and the
existing MLS and identity suites.

## 3. Full regression, same environment

Both trees were run in worktrees with the same environment. Neither worktree has a migrated dev database, so some
suites fail on missing tables (for example `no such table: player_game_logs_sportsdataverse`). That condition is
environmental and identical on both trees.

| Tree | Passed | Failed | Skipped | xfailed |
|---|---|---|---|---|
| `origin/dev` `382f5ffe` | 3,453 | 80 | 39 | 3 |
| `feat/mls-cutover-2026-10-28` `0e8894a2` | 3,517 | 80 | 39 | 3 |

The 80 failing test IDs are the same on both trees (`comm` shows no difference). The branch adds 64 passing tests and
no failures. The failing modules are the same: ingest team vocabulary, rotowire soccer stats, home featured, UFC/MLS
settlement, props without filter, NCAAF settlement, and others. The lists are in the evidence folder.

This is not a run in a properly migrated dev environment. That is open (section 9, B4).

## 4. Before and after counts (migrated copy, `evidence.json`)

The copy is `mls_cutover_copy.py` output from the production identity scope, read-only on production: production
table definitions, MLS-only rows for per-player tables, 40 MB.

| | Before | After first cycle | After departure and transfer |
|---|---|---|---|
| `players` | 57,435 | 57,435 | 57,435 |
| `player_source_ids` | 10,433 | 10,433 | 10,433 |
| `roster_snapshots` | 0 | 1 | 3 |
| `roster_memberships` | 0 | 1,040 | 3,118 |
| `identity_onboarding_queue` | (table absent) | 0 | 0 |

## 5. Before and after checksums of protected tables

The SHA-256 of each table's rows, from `evidence.json`. Identical before and after all cycles:

| Table | Before (first 12) | After (first 12) |
|---|---|---|
| `players` | af18a1f214a6 | af18a1f214a6 |
| `player_source_ids` | 2d927659c70e | 2d927659c70e |
| `player_game_logs` | 9f4c0d817e7a | 9f4c0d817e7a |
| `props` | fadd21d8bd89 | fadd21d8bd89 |
| `prop_results` | 5c1cfdf20d13 | 5c1cfdf20d13 |
| `settlement_attempts` | dd5a72a1664e | dd5a72a1664e |
| `team_game_results` | dca409594c5d | dca409594c5d |

## 6. Lookup evidence, transitions, and degraded fetches

Current lookups (`evidence.json`, migrated copy, gate on):

- The 16 people the legacy resolver still returns: resolved by the legacy path 16 of 16; resolved with the cutover 0 of 16.
- Every current member (1,040) resolves to themselves; 0 fail.
- Departure of person 32331 (both publishers): recorded as a departure. Current lookup: no match. Lookup as of 2026-10-28: 32331. Bindings kept: 2 before, 2 after.
- Transfer of person 32353 (Atlanta United to Austin FC): recorded as a transfer. Current club: Austin FC. Club on 2026-10-28: Atlanta United. Their 14 game logs keep the club code `ATL`.

Degraded fetches and transitions are covered by acceptance tests 12, 13, 20, and by the fault-injection list above.

## 7. Closure rule

| Criterion | Met? | Evidence or reason |
|---|---|---|
| All 23 acceptance tests pass | Yes | Section 2 |
| All 1,040 baseline players resolve correctly | Yes | Section 6; e2e on fixture and migrated copy |
| Every signing, departure, transfer, disagreement, rekey, recovery behaves as specified | Yes | Tests 2 to 13, 20 |
| No known stale identity lookup remains | **No** | See below |
| Historical-data integrity checks pass | Yes | Section 5; test 22 |
| No critical regression introduced | Yes | Section 3: identical failing sets |
| Isolated, reproducible, ready for a separately authorized cutover | **Partly** | Reproducible copy and tests exist. Live onboarding has not run against live publishers. Blockers in section 9 |

Why "no known stale identity lookup remains" is not met:

1. The gate restricts who may be matched, not which observation rows exist. `backfill_from_published_roster` and `spine_merge` still match current people through observation rows, and a stale row can still propose a match for a current person. Their gating is tested for departed people only.
2. The cutover is off by default. Until it is authorized, every legacy lookup in production is live, including `published_roster.lookup_player` on the props path. That is by design, and it means the criterion describes the state after cutover, not the state today.
3. `players.team` is no longer copied for MLS by the refresh script, but other readers of `players.team` have not been inventoried.

## 8. Production readiness and rollback

Readiness, as of this report:

- Default state: `mls_resolution.CUTOVER_ENABLED = False`, and the roster job runs without `--mls-cutover`. Production behavior is unchanged.
- Schema: `identity_evidence` and `identity_onboarding_queue` are created by `mls_identity.ensure_schema`, which every cycle calls. They are additive.
- Onboarding writes only `players`, `player_source_ids`, `identity_evidence`, and `identity_onboarding_queue`, and is verified not to touch history.
- The default date-of-birth lookups call FotMob's player API and MLS player pages. They have not been run against live publishers as part of this work (B1).

Rollback, if the cutover is enabled and must be reversed:

1. Remove `--mls-cutover` from the job invocation. The next run uses the legacy identity step. Set `CUTOVER_ENABLED` back to `False` for the props path.
2. Snapshot tables are additive. The legacy path ignores them. They may be left or pruned by policy.
3. Identity writes by onboarding cannot be undone by a flag. Each created person has `players`, `player_source_ids`, and `identity_evidence` rows stamped with the cycle time, and rekeys have bind and evidence rows. Rollback means finding rows stamped after cutover start, confirming no prop, game log, or settlement references them, and then deleting them. No script for this exists yet (N2).

## 9. Remaining risks

Blocking (must be resolved before a production cutover):

- **B1. Live onboarding has not been run.** The decision logic is tested with fake dates of birth. The production lookups are untested against live publishers. Required: a read-only shadow of onboarding decisions against the live squads, with the queue reviewed.
- **B2. `players.team` readers not inventoried.** Required: list every reader, and move each to `mls_resolution.current_team` or document why it can stay.
- **B3. Observation rows still feed matching for current people** in backfill and spine planning (section 7, item 1). Required: either restrict those tools to the membership snapshot's own keys, or accept and document the residual.
- **B4. No run in a properly migrated dev environment.** Required: apply the dev migrations to a copy, run the full suite there on both trees, and compare.
- **B5. Branch base.** `origin/dev` lacks 26 local dev commits that the production job runs, including `8b8dbcf6` (spine merge does not bind on name and club alone) and the stale-row commits `b8c81080`, `7dfb4a4c`, `8f566485`. Required: decide the merge order before any merge to `dev`.
- **B6. Historical props from backfills.** The resolver takes the game's day from `prop_games`. A call with no game ID resolves as of today, so a departed person's past prop fails to resolve and is recorded as unresolved, not misattributed. Required: wire the game day into every backfill path before backfilling under the gate.

Non-blocking:

- **N1.** A permanent dispute holds a person at their old club with no time limit. It is visible in health. An operating rule for review is needed.
- **N2.** The review queue has no tool and no alert. A rollback script does not exist (section 8).
- **N3.** Liga MX is not gated, because it has no snapshot. Leagues Cup is gated by a post-filter on the home person.
- **N4.** `spine_merge` gating is not covered by its own test.
- **N5.** Storage. Measured on production: 8.33 GB free for normal users at the last check (8.66 GB earlier). About 21 GB more is reserved for root. The production database is 2.93 GB, with an active WAL of 2.5 MB at measurement. Retained backups total about 14.5 GB: the two incident copies, the pinned UFC copy, the newest UFC copy, and the newest MLB copy. The MLB history job writes a new 2.9 GB copy each morning before it prunes the old one, so it briefly needs one more copy's worth of free space. The cutover itself writes no copies. Recommendation: move backup copies off this filesystem before rollout.
- **N6.** Ten orphan `-shm` and `-wal` sidecar files remain from earlier deletions. They are 32 KB or empty and are not referenced by any main file.

## 10. Changes made to tests during implementation

The contract forbids changing tests to fit wrong behavior. These are the changes made, with the reason for each:

1. `test_existing_population`: the fixture lists some keys twice (MLS and Leagues Cup). The test now inserts each key once. This is a setup fix.
2. Publisher-disagreement and conflict-recovery tests: they assumed person 4 was on Club04. Person 4 is on Club01 (club blocks are 22 people each). The tests now use the person's actual club.
3. Transition-idempotence test: it moved too many people out of one club, which correctly tripped the 20-player minimum. It now disputes a person on another club.
4. `test_stale_lookup`: restructured to run a control with the gate off, to show the defect, then the gate on.
5. `test_new_signing`: a negative case was added for a disputed date of birth. This strengthens the test; the fault injection that removes the corroboration check now fails it.
6. Three tests in `test_mls_snapshot.py` asserted the old whole-league refusal for a club disagreement, a second key from one publisher, and a moved bind. They now assert the hold and the flag, as the contract specifies.
7. Consumer tests: the fold of names that contain digits strips the digits, so a hand-written folded name was wrong. The tests now call the job's own `fold`, and use a distinctive name for the departed person.
8. E2E test: the sample was taken from all fixture players, not from current members. It now checks every current member.

No test was weakened to pass. Expected behavior in the contract was not changed.

## 11. Verification commands

```
cd backend && /usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_acceptance.py -v
LP_MLS_E2E_DB=<migrated copy> /usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_e2e.py -v
/usr/bin/python3 mls_cutover_copy.py <production picks.db> <new copy path>   # read-only on production
```
