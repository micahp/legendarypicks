# MLS identity and roster closure (2026-10-27 incident)

**Status: DONE (engineering scope).** Every criterion in the closure rule is met on the integrated branch, with the
evidence below. Production is unchanged. The MLS cutover is not enabled, nothing is merged into `dev` or into the running
checkout, nothing is deployed, and the three historical rows are not restored. Each of those needs its own authorization.
None of them is a prerequisite for this closure.

Branch: `integrate/mls-cutover-on-dev`, built on `79e8e05d`, the commit the running dev checkout executes. Code head
for the final regression: `1dcff24c`. The commits after it (`80fb4390`, `5f3dcdb6`, and this report) change documentation
only. Evidence: `docs/incidents/2026-10-27-mls-identity-closure-evidence/`, with checksums in its `SHA256SUMS`.

## 1. Closure criteria

| Criterion | Result | Evidence |
|---|---|---|
| 23 of 23 acceptance tests pass | Met | `acceptance_head_verbose.txt`: 23 passed |
| All 1,040 baseline people resolve | Met | Acceptance test 1; the end-to-end gate on the migrated copy (2 passed); the live roster run published 1,040 current memberships (section 6) |
| B1 to B6 resolved, with reproducible evidence | Met | Section 2 |
| Historical data unchanged | Met | Section 5: protected-table checksums equal before and after the live cutover run on the migrated environment; equal across the rollback demo |
| No new regressions | Met | Section 4: every failure on the integrated head also fails on origin/dev |
| Integrated gated cutover runs correctly in the migrated environment | Met | Section 6: live roster job with `--mls-cutover` on the migrated copy, verified publish, zero identity blockers |
| Rollback demonstrated on a disposable copy | Met | Section 7 |

Production deployment is not part of the criteria. Section 8 lists what remains and who decides it.

## 2. Blockers

### B1. Live onboarding shadow: resolved

`backend/mls_onboarding_shadow.py` fetched today's squads through the production providers (900 FotMob members, 955 MLS
members). Production was opened read-only. Onboarding was evaluated on a disposable identity-scope copy inside a
transaction that is always rolled back. Two runs: the first on `bef2f12e` (the shadow script has not changed since), and
the final on the integrated head.

| | First run (2026-10-28 20:08 UTC) | Final run (20:31 UTC) |
|---|---|---|
| Live keys with no binding | 0 | 0 |
| Creations, rekeys and queued keys decided on live data | 0, 0, 0 | 0, 0, 0 |
| Copy row counts before and after the decision | unchanged | unchanged |
| Known-record agreement with the audit (sample of 44) | 39 | 40 |

The four disagreements in the final run are audit records marked `mls_date_missing` (MLS published no date at audit
time): 58495, 59030, 58508, and 58489. The live MLS page now publishes a date that matches FotMob for each, so the rule
corroborates them. The audit is stale for these four. Two of them (58495 and 58489) show two MLS readings, one per
day-month order, and one reading matches FotMob. That is the audit's own `supported_order_unresolved` case, and the rule
accepts it for the same reason the audit does. The first run also disagreed on 58782 (Joe Willis), whose MLS page had no
date at that time. In the final run the page had one. The MLS date field varies between runs. The rule fails closed when
it is absent.

Limit: today's live squads have no unbound keys, so the creation path is not exercised by live data. The acceptance tests
and the end-to-end gate exercise it with corroborated and disputed fixtures.

### B2. Current consumers of `players.team`: resolved, one residual outside the closure rule

Inventory: `docs/mls-players-team-consumers-2026-10-28.md`. The first pass missed one current consumer, the RotoWire props
resolver. It matched names against stored clubs and bound keys by name. A second pass searched every non-test backend
file for `team` on the `players`, `pl`, `p`, `pp` and `px` aliases, and checked each hit. The search found the RotoWire
resolver, and it is now gated.

Current MLS consumers, corrected (active only with the cutover on):
- `routers/props.py` props list and board: upcoming games show the membership club; past games keep the stored club.
- `routers/players/stats.py` season leaderboard: a current member shows the membership club; a departed player shows the
  season club.
- `ingest_rotowire_props.py` `resolve_player` (MLS and Leagues Cup): a bound key counts only for a current member; a name
  answer comes from the gated resolver; a name match writes no binding; a departed person is queued `not_in_spine`
  (commit `319ad2f8`).
- `refresh_soccer_player_teams.py` skips MLS; `promote_mls_player_stats.py` refuses to create MLS players.
- `backfill_from_published_roster.py` and `spine_merge.py`: see B3.

Historical readers are unchanged, as the directive requires.

Residual: `settlement/settle_game.py` passes the stored club to the box-score match. `boxscore_extract._find_player_stat`
uses that club only when the prop has no ESPN id. With an ESPN id the club is ignored. Without one, a transferred MLS
player keeps the old club in `players.team`, so the match skips the section of the club the player now plays for, and the
prop stays pending. The name match inside the stored club's section is the existing rule. Changing the club source changes
settlement of historical props, so it is a separate decision.

Tests: `test_mls_cutover_consumers.py` (11, including the tests that fail if backfill or spine planning reads an
observation row under the gate) and `test_mls_cutover_rotowire.py` (4). With the gate off, the club expressions are the
legacy SQL, and the RotoWire resolver is the legacy path (tested as the control).

### B3. Backfill and spine planning match membership evidence: resolved under the gate

With the cutover on, `backfill_from_published_roster.py` and `spine_merge.py` (`_published_groups`) read the membership
snapshot and never read an observation row. Tests fail if either does
(`test_under_the_gate_backfill_never_reads_an_observation_row`, `test_under_the_gate_spine_planning_never_reads_an_observation_row`).
With the gate off they bind as before (`test_backfill_with_the_cutover_off_binds_as_before`). The spine gating is now
covered by its own tests, which closes the earlier N4.

The gate is off in production, so this takes effect when the cutover is authorized.

### B4. Both baselines in a migrated dev environment: resolved

Environment: a copy of the running dev database (`backend/data/picks.dev.db`, 3.43 GB), made with the SQLite backup API from
a read-only connection. It passes the application's migration check (`migrate_all.refuse_unmigrated`). Both trees ran
against that same file, and its modification time did not change during the runs.

| Tree | Passed | Failed | Skipped | xfailed | Log |
|---|---|---|---|---|---|
| origin/dev `382f5ffe` | 3,482 | 82 | 5 | 6 | `regression_origin_dev_382f5ffe_migrated.log` |
| integrated head `1dcff24c` | 3,565 | 81 | 5 | 6 | `regression_integration_head_migrated.log` |

Failing sets (`failing_set_comparison.txt`): all 81 failures on the integrated head also fail on origin/dev. The one
origin/dev failure that does not fail on the integrated head is
`test_story_form_season.py::TestAgainstTheRealDatabases::test_real_log_seasons_against_a_real_game_season[nfl-2026-True]`.
Its expectation on origin/dev is stale: it expects NFL logs to stop at 2025. The integrated lineage (`79e8e05d`, the running
checkout) already has the corrected expectation. That is lineage, not MLS.

The 81 shared failures are present on origin/dev in the same environment. They cover ingest team vocabulary, RotoWire soccer
stats, UFC and MLS settlement, props without filter, NCAAF settlement, and a RotoWire archive directory that is absent from
the worktree.

The first integrated run, on `2fc706f3`, found one new failure: `test_props_slate_upcoming`. The props club expression had
reintroduced `pg.date >= date('now')`, which the board's own test forbids. It is fixed in `fb5835ae` by using the board's
`_UPCOMING` predicate. The logs are `regression_first_integration_2fc706f3_migrated.log` (before) and
`regression_integration_fb5835ae_migrated.log` (after).

### B5. Dev lineage reconciled: resolved

`docs/mls-dev-lineage-2026-10-28.md`. The running checkout runs `79e8e05d`, 26 commits ahead of origin/dev `382f5ffe`. Two
origin/dev commits (`382f5ffe`, `1d35e47e`, NFL blocked-kick fixes) are not in it. The integration starts from `79e8e05d`.
The three identity-relevant uncommitted files that production runs (backup retention) are committed as `293c570a`. The 27
other uncommitted paths and the untracked `picks.db` are untouched. The conditions for any merge into `dev` are listed in
that document. They are decisions for the owner of the running checkout, not part of this closure.

### B6. Historical games use the game's date and fail closed: resolved

- `_core._resolve_player_for_ingest(..., game_id=...)` takes the game's day from `prop_games`. A game whose day is today or
  later uses the current membership. A named game whose day is missing or unparseable returns no match, never today's
  membership (`test_a_named_game_whose_day_cannot_be_established_fails_closed`).
- A past game's props resolve against the membership on that day
  (`test_a_past_game_resolves_to_the_club_on_its_day_and_today_uses_the_current_membership`).
- The props ingest passes its game ID. The Bovada scraper path resolves as of today and is not a backfill.
- Historical identity resolution keeps working: acceptance test 16 (departed and transferred people resolve as of a past
  date; no snapshot for a date fails closed).
- Backfill and spine planning attribute no games (B3).

## 3. Acceptance tests (`backend/test_mls_cutover_acceptance.py`)

Result on the integrated head: 23 passed (`acceptance_head_verbose.txt`). Supporting suites (consumers, rollback, RotoWire,
and the snapshot suites): 54 passed (`consumers_rollback_rotowire_snapshot_head_verbose.txt`). End-to-end gate on the migrated
copy: 2 passed (`e2e_migrated_copy_head_verbose.txt`). No acceptance test was changed in the integration pass.

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

Fault injection, from the earlier pass: five defects reintroduced one at a time were each caught by at least one test
(corroboration removed; gate switched off; missing-source check disabled; checksum hashing events; publication not rolled back).

## 4. Regression

See B4 for the table, the failing-set comparison, and the first-run defect that was fixed. The earlier non-migrated
comparison (80 failing on both trees, `branch_failing_tests.txt` and `origin_dev_failing_tests.txt`) is kept for the record.
It is superseded by the migrated run.

## 5. Historical data unchanged

Protected-table checksums (`pre_live_checksums.json`, `post_live_checksums.json`): rows and SHA-256 over every row in rowid
order, before and after the live cutover run in section 6.

| Table | Rows before | Rows after | Checksum equal |
|---|---|---|---|
| `players` | 61,408 | 61,408 | yes |
| `player_source_ids` | 14,642 | 14,642 | yes |
| `player_game_logs` | 584,137 | 584,137 | yes |
| `props` | 924,755 | 924,755 | yes |
| `prop_results` | 740,340 | 740,340 | yes |
| `settlement_attempts` | 183,734 | 183,734 | yes |
| `team_game_results` | 20,798 | 20,798 | yes |
| `prop_games` | 3,944 | 3,944 | yes |
| `roster_snapshots` | 903 | 904 | changed by design: one MLS snapshot published |
| `roster_memberships` | 734,458 | 735,498 | changed by design: +1,040 for that snapshot |
| `identity_evidence` | absent | 0 | created empty by `ensure_schema` |
| `identity_onboarding_queue` | absent | 0 | created empty by `ensure_schema` |

The rollback demo shows the same for the identity and history tables before and after a cycle and its rollback
(`rollback_demo_report.json`: `identity_and_snapshot_tables_equal_before: true`, `protected_history_equal_before: true`).

Production: every access in this work was read-only (`mode=ro`), or made to a copy. The rollback tool refuses the name
`picks.db`. The production file's modification time moved during this work. The running checkout's scheduled jobs write to
that file. This work did not open it for writing.

## 6. Live cutover run on the migrated environment

Command, run against a disposable copy of the migrated dev database, with live publishers and the job's own code path:

```
LP_DB_PATH=<disposable migrated copy> python ingest_published_rosters.py mls --apply --mls-cutover
```

Output (`live_cutover_run.log`):
- `mls via _fotmob_squads: 900 published squad members`; `mls via _mls_squads: 955 published squad members`
- `mls cutover: published (verified); onboarded 0, rekeyed 0, queued 0`
- `identities: mls_cutover_published=1`; `identity_blockers=0`

The snapshot published has 1,040 memberships. Onboarding created nothing because no live key was unbound. The consumer gate
(`CUTOVER_ENABLED`) was off in this run. The consumer gate is exercised by the end-to-end gate, which turns it on, and by the
consumer tests.

## 7. Rollback

`backend/mls_cutover_rollback.py` (commit `2e6c81a2`). It dry-runs by default. With `--apply --archive PATH` it:
1. refuses if a created person is referenced by props, prop results, settlement attempts, or game logs;
2. archives every cutover-era snapshot and its memberships to JSON, deletes them, and marks the newest pre-cutover snapshot
   published again;
3. deletes the bindings the cycle added to people who existed before the cutover, the created people and their bindings,
   and the evidence and queue rows stamped after the cutover start.

It never touches a game log, prop, settlement, or team game result, and it refuses a database named `picks.db`.

Demo, on a disposable copy (`rollback_demo.py`, `rollback_demo_report.json`): the cycle onboarded player 71985 with two
bindings. The plan named one created player, two bindings, two evidence rows, and no refusal. Apply removed the player and
both bindings. Identity and snapshot checksums and protected-history checksums were equal to their values before the cycle.
The copy had no earlier snapshot, so the restore step was not exercised by the demo. It is covered by
`test_rollback_restores_the_pre_cutover_identity_and_snapshot_state`, with `test_rollback_removes_a_rekey_the_cycle_bound_and_keeps_the_original_binding`,
`test_rollback_refuses_when_a_created_player_already_has_props`, and `test_a_dry_run_changes_nothing_and_reports_what_would_go`
(`test_mls_cutover_rollback.py`, 4 passed).

Reverting in production is not a flag flip. `CUTOVER_ENABLED` is a module constant, so turning the consumer gate off needs
a code change (section 8).

## 8. Residuals: not in the closure rule, each needs a decision

- **Production cutover and deployment**: not authorized and not done. `CUTOVER_ENABLED` is a module constant. Before any
  production enable, make it a runtime setting, so the consumer gate can be reverted without a deploy.
- **Merge into `dev`**: decisions in `docs/mls-dev-lineage-2026-10-28.md`: the two origin/dev NFL commits, the 27 uncommitted
  paths, and the running checkout owner's agreement.
- **Disk**: about 3.9 GB free after this work's copies are removed. The MLB history job writes a 2.9 GB copy each morning. Move
  backup copies off this filesystem before rollout (N5).
- **Identity tables**: `identity_evidence` and `identity_onboarding_queue` are created at runtime by `ensure_schema` on the
  first cycle with the flag on. They are not in a registered migration, so the migration check does not cover them.
- **Settlement club source**: see B2. Pending props for transferred MLS players without an ESPN id stay pending until the
  owner decides.
- **Historical readers**: FotMob log attribution (`ingest_fotmob_soccer_logs.py`), and the other historical readers, are
  unchanged by directive. The FotMob name fallback was not re-verified for transferred players.
- **Stale audit labels**: four `mls_date_missing` records are now corroborated by the live page. Re-run the identity audit.
- **Day-month corroboration**: the rule accepts an MLS page whose day-month reading matches FotMob, as the audit's
  `supported_order_unresolved` policy does. The owner should confirm that policy before onboarding signings is enabled.
- **N1**: a permanent dispute holds a person at their old club with no time limit. **N2**: the review queue has no tool and no
  alert. **N3**: Liga MX is not gated, because it has no snapshot.
- **Observed, not verified or changed**: `settle_props.py` and `ingest_ufcalendar_dwcs.py` filter on `pg.date` against the
  calendar date. The board's 2026-08-17 fix shows that calendar dates and kickoff instants can disagree. Outside this scope.

## 9. Test changes

The contract forbids changing tests to fit wrong behavior. The changes made during the first implementation pass are
unchanged from the earlier report: a setup fix for a duplicated fixture key; three assertions moved to the actual club of a
person; a transition test that moved too many people out of one club, corrected to dispute a person on another club; the
`test_stale_lookup` control; a negative case added to `test_new_signing`; three `test_mls_snapshot.py` assertions moved from
the whole-league refusal to the hold and flag; name-fold assertions that call the job's own `fold`; and the end-to-end sample
restricted to current members. In the integration pass no existing test was changed or removed. Tests were added to
`test_mls_cutover_consumers.py` (additions only), and `test_mls_cutover_rollback.py` and `test_mls_cutover_rotowire.py` are new.

## 10. Commits on `integrate/mls-cutover-on-dev` (after `79e8e05d`)

| Commit | Change |
|---|---|
| `293c570a` | Backup retention edits the running checkout uses, committed from the saved patch |
| `f7b8bfb4`, `7ece4a3b`, `b780e887`, `db044406`, `e06b2b8c`, `d986866f`, `476da153`, `8dbf6968`, `658ccdff` | The cutover (cherry-picked from `feat/mls-cutover-2026-10-28`): onboarding, acceptance contract, snapshot holds, membership resolution, the opt-in roster job, the end-to-end gate, the gated stale-row consumers, the past-game props resolution |
| `947b8d0a`, `e49abfe6`, `0a5c1c73`, `80c4888e`, `63d8730e`, `e830a606`, `5eebfc27` | The snapshot, the shadow comparison, the identity audit and the resolver audit (cherry-picked) |
| `0e091de0` | The earlier NOT DONE closure report, with its evidence (cherry-picked) |
| `6b5d606a` | Current lookups use membership evidence only; historical games fail closed |
| `0b2c77dc` | Current MLS club consumers read the membership snapshot; first inventory |
| `2e6c81a2` | Rollback tool and tests |
| `bef2f12e` | Read-only live onboarding shadow |
| `2fc706f3` | Dev lineage record |
| `fb5835ae` | Props club expression uses the board's upcoming rule (regression fix) |
| `319ad2f8` | RotoWire props for MLS under the gate: membership answers, no binding from a name match |
| `1dcff24c`, `80fb4390`, `5f3dcdb6` | Consumer inventory: RotoWire row, settlement residual, remaining readers |
| this report's commit | DONE status and the final evidence |

## 11. Verification commands

```
cd backend
/usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_acceptance.py -v
/usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_consumers.py test_mls_cutover_rollback.py test_mls_cutover_rotowire.py -v
LP_MLS_E2E_DB=<migrated identity copy> /usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_e2e.py -v
/usr/bin/python3 -m pytest -p no:cacheprovider -rfE            # full suite on a migrated copy: LP_DB_PATH and backend/data/picks.dev.db point at it
/usr/bin/python3 ../docs/incidents/2026-10-27-mls-identity-closure-evidence/protected_checksums.py <copy>   # read-only
/usr/bin/python3 mls_onboarding_shadow.py <production picks.db> <disposable copy> <pairs_v4.jsonl> <report.json>   # read-only shadow
LP_DB_PATH=<disposable copy> /usr/bin/python3 ingest_published_rosters.py mls --apply --mls-cutover   # never against production
/usr/bin/python3 mls_cutover_rollback.py <copy> --since <ISO timestamp>   # dry run; add --apply --archive PATH on a copy
```

`pairs_v4.jsonl` is in the evidence folder. The disposable copies were removed after the evidence was collected. Recreate
them with the SQLite backup API from a read-only connection, as in B4.
