# MLS identity and roster closure (2026-10-27 incident)

## Status

| Track | Status |
|---|---|
| Engineering | **DONE** |
| Remote publication | **BLOCKED until authorized.** Not pushed. |
| Production cutover | **NOT DEPLOYED.** The cutover switch is off, and the production checkout is unchanged. |

**Engineering DONE** means the closure criteria in section 1 are met on the integrated branch, with the evidence listed
here. Remote publication is blocked: a push of `integrate/mls-cutover-on-dev` was denied by the publication
restriction, and it has not been retried or worked around. Production cutover, live onboarding monitoring, and backup
relocation are rollout work. Section 9 is the deployment checklist.

**Branch:** `integrate/mls-cutover-on-dev`, built on `79e8e05d`, the commit the running dev checkout executes.
**Engineering head:** `9e0eff33`. The commit that adds this report follows it and changes documentation only.
**Evidence:** `docs/incidents/2026-10-27-mls-identity-closure-evidence/`, with checksums in its `SHA256SUMS`.

## 1. Closure criteria

| Criterion | Result | Evidence |
|---|---|---|
| 23 of 23 acceptance tests pass | Met | `acceptance_head_verbose.txt` (23 passed at `1dcff24c`); the acceptance file was re-run after the switch and date-rule changes (97 passed across the MLS suites at `858f9b09`) |
| 54 supporting MLS tests pass | Met | `consumers_rollback_rotowire_snapshot_head_verbose.txt` at `1dcff24c` |
| All 1,040 baseline people resolve | Met | Acceptance test 1; end-to-end gate on the migrated copy (2 passed, at `9e0eff33`); live roster run published 1,040 current memberships (section 6) |
| B1 to B6 resolved, reproducible | Met | Section 2 |
| Historical data unchanged | Met | Section 5 |
| Zero new regression failures relative to origin/dev | Met | Section 4: every failure on the integrated head also fails on origin/dev |
| Integrated gated cutover runs correctly in the migrated environment | Met | Section 6 |
| Rollback demonstrated on a disposable copy | Met | Section 7 |

## 2. Changes in the final pass

Three changes were made after the earlier closure. Each has its own commit and its own tests.

1. **The cutover switch is a runtime setting, default off** (`dcfad87e`). `mls_resolution.cutover_enabled()` reads
   `LP_MLS_CUTOVER` on every call. Only `1`, `true`, `yes` or `on` turns it on. Unset, empty, or any other value leaves it
   off. Tests cover the default, the accepted and rejected values, reads at each call, and the enabled and disabled
   resolver behavior (`test_mls_cutover_setting.py`, 14 tests). The acceptance file changed only how it switches the gate;
   no assertion changed.

2. **Automatic onboarding needs one unambiguous date of birth** (`858f9b09`). Each publisher must give exactly one reading,
   and the two must agree. Two readings from one publisher are `dob_ambiguous`. Two single readings that differ are
   `dob_not_corroborated`. Missing readings are `dob_missing`. In every case that is not accepted, nothing is created or
   rekeyed, and the identity is queued for review. Nothing guesses between readings (`test_mls_identity_dob.py`, 6 tests).

   Effect on the audited sample: the earlier rule accepted a day-month ambiguous MLS page when one reading matched FotMob.
   The new rule queues those. See B1 for the numbers.

3. **Name-only settlement stays pending** (`9e0eff33`). A prop with no ESPN id is no longer matched through the stored
   club, which is today's club. It is counted as `pending` in `settle_game` and `ncaaf_settle`. Nothing is written for it.
   The tracked issue is `docs/issues/settlement-name-only-pending.md`, with the measured counts and the decision still
   needed (`test_settlement_name_only.py`, 2 tests).

## 3. Blockers

### B1. Live onboarding shadow: resolved, with the final-rule numbers

`backend/mls_onboarding_shadow.py` fetched today's squads through the production providers (900 FotMob, 955 MLS).
Production was opened read-only. Onboarding was evaluated on a disposable copy inside a transaction that is always rolled
back. The live readings are saved in the evidence folder.

Onboarding decisions on live data, both runs: 0 unbound live keys, 0 creations, 0 rekeys, 0 queued. Copy row counts were
unchanged in both runs (players 57,435; binds 10,433).

Known-record agreement with the audit (sample of 44, stratified as before). The table compares the rule each run was
scored with.

| Rule | First run (20:08 UTC) | Final run (20:31 UTC) |
|---|---|---|
| Earlier rule: any shared date corroborates | 39 of 44 | 40 of 44 |
| **Final rule: one reading from each publisher, equal** | **31 of 44** | **31 of 44** |

The final rule is scored offline from the saved readings (`recompute_shadow_unique_rule.py`,
`live_shadow_final_unique_rule.json`). No publisher was contacted for it.

Under the final rule, the 13 disagreements in the final run are:
- 11 audited-supported records (2 `supported`, 9 `supported_order_unresolved`) whose MLS page prints two day-month readings.
  The audit accepted them as order-unresolved. The final rule queues them, as the owner asked. This is the main change.
- 2 audit-stale records (59030 and 58508), marked `mls_date_missing` in the audit. The MLS page now publishes one reading,
  equal to FotMob's, so the rule accepts them.

Known limits:
- The live squads had no unbound keys, so the creation path is not exercised by live data. The acceptance tests and the
  end-to-end gate exercise it with fixtures.
- Both runs show that the MLS date field varies between runs. The first run had no MLS date for 58782 (Joe Willis), and
  the final run had two readings. The rule fails closed in both states.
- Owner decision, not engineering: the final rule sends a large share of signings with day-month ambiguous MLS pages to
  review. In the audited sample that is 11 of the 30 supported records. Plan the review capacity before enabling.

### B2. Current consumers of `players.team`: resolved

Inventory: `docs/mls-players-team-consumers-2026-10-28.md`. The search covers every non-test backend file that reads a
player-table team, and each hit is classed (current MLS, historical, other league, vocabulary).

Current MLS consumers, corrected (active only with the switch on):
- `routers/props.py` props list and board: upcoming games show the membership club; past games keep the stored club.
- `routers/players/stats.py` season leaderboard: a current member shows the membership club; a departed player shows the
  season club.
- `ingest_rotowire_props.py` `resolve_player` (MLS and Leagues Cup): a bound key counts only for a current member; a name
  answer comes from the gated resolver; a name match writes no binding; a departed person is queued `not_in_spine`.
- `refresh_soccer_player_teams.py` skips MLS; `promote_mls_player_stats.py` refuses to create MLS players.
- `backfill_from_published_roster.py` and `spine_merge.py`: see B3.

Historical readers are unchanged, as the directive requires. One residual is now closed by the final pass: name-only
settlement no longer uses the stored club (section 2, item 3). The tracked issue covers the rest.

### B3. Backfill and spine planning match membership evidence: resolved under the switch

With the switch on, `backfill_from_published_roster.py` and `spine_merge.py` read the membership snapshot and never read an
observation row. Tests fail if either does. With the switch off they bind as before. The spine gating has its own tests.

The switch is off in production. This takes effect when the cutover is authorized.

### B4. Both baselines in a migrated dev environment: resolved

Environment: a copy of the running dev database (`picks.dev.db`, 3.43 GB), made with the SQLite backup API from a
read-only connection. It passes the application's migration check. Both trees ran against that same file, and its
modification time did not change during the runs.

| Tree | Passed | Failed | Skipped | xfailed | Log |
|---|---|---|---|---|---|
| origin/dev `382f5ffe` | 3,482 | 82 | 5 | 6 | `regression_origin_dev_382f5ffe_migrated.log` |
| integrated head `1dcff24c` | 3,565 | 81 | 5 | 6 | `regression_integration_head_migrated.log` |

All 81 failures on the integrated head also fail on origin/dev. The one origin/dev failure that does not fail on the head
is `test_story_form_season.py::...[nfl-2026-True]`. Its expectation is stale on origin/dev. The integrated lineage
(`79e8e05d`) already has the corrected expectation.

The final-pass changes were checked against origin/dev in the same environment, without the migrated copy, because that copy
was removed:
- Settlement suites (17 files on both trees): 20 failed and 124 passed on the head, which adds 2 new tests; 20 failed and 122
  passed on origin/dev; identical failing sets.
- Touched resolver, ingest, and RotoWire modules: 3 failed and 208 passed on the head; 3 failed and 207 passed on origin/dev;
  identical failing sets.
- End-to-end gate on the migrated identity copy: 2 passed, and the copy's SHA-256 is unchanged.

The full suite was not re-run after the final pass. The changes were checked against the suites that exercise them, and
no new failure appeared.

The first integrated run, on `2fc706f3`, found one new failure (`test_props_slate_upcoming`). The props club expression had
reintroduced `pg.date >= date('now')`, which the board's own test forbids. It is fixed in `fb5835ae`
(`regression_first_integration_2fc706f3_migrated.log` and `regression_integration_fb5835ae_migrated.log`).

### B5. Dev lineage reconciled: resolved

`docs/mls-dev-lineage-2026-10-28.md`. The running checkout runs `79e8e05d`, 26 commits ahead of origin/dev `382f5ffe`. Two
origin/dev commits (`382f5ffe`, `1d35e47e`, NFL blocked-kick fixes) are not in it. The integration starts from `79e8e05d`.
The three identity-relevant uncommitted files that production runs (backup retention) are committed as `293c570a`. The 27
other uncommitted paths and the untracked `picks.db` are untouched. Merge conditions are in that document. They are
decisions for the owner of the running checkout.

### B6. Historical games use the game's date and fail closed: resolved

- `_core._resolve_player_for_ingest(..., game_id=...)` takes the game's day from `prop_games`. A game dated today or later
  uses the current membership. A named game whose day is missing or unparseable returns no match, never today's membership.
- A past game's props resolve against the membership on that day.
- The props ingest passes its game ID. The Bovada scraper resolves as of today and is not a backfill.
- Historical identity resolution keeps working: acceptance test 16.
- Backfill and spine planning attribute no games (B3).

## 4. Acceptance tests (`backend/test_mls_cutover_acceptance.py`)

Result: 23 passed (`acceptance_head_verbose.txt`). The contract is unchanged. The acceptance file changed only in how it switches
the gate (section 2, item 1).

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

Fault injection, from the earlier pass: five defects reintroduced one at a time were each caught by at least one test.

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
`picks.db`. The production file's modification time moved during this work. The running checkout's scheduled jobs write to that
file. This work did not open it for writing.

## 6. Live cutover run on the migrated environment

Run before the final pass (on the code at `1dcff24c`). The final pass changed the date-of-birth rule and the switch, and the
run's decisions were empty in both cases, so the run does not exercise either change. It is repeated on a fresh copy as part of
the deployment checklist (section 9, step 5).

Command, against a disposable copy with live publishers:

```
LP_DB_PATH=<disposable migrated copy> python ingest_published_rosters.py mls --apply --mls-cutover
```

Output (`live_cutover_run.log`):
- `mls via _fotmob_squads: 900 published squad members`; `mls via _mls_squads: 955 published squad members`
- `mls cutover: published (verified); onboarded 0, rekeyed 0, queued 0`
- `identities: mls_cutover_published=1`; `identity_blockers=0`

The snapshot published has 1,040 memberships. The consumer switch was off in that run.

## 7. Rollback

**Identity writes.** `backend/mls_cutover_rollback.py` (commit `2e6c81a2`). It dry-runs by default. With `--apply --archive PATH` it:
1. refuses if a created person is referenced by props, prop results, settlement attempts, or game logs;
2. archives every cutover-era snapshot and its memberships to JSON, deletes them, and marks the newest pre-cutover snapshot
   published again;
3. deletes the bindings the cycle added to people who existed before the cutover, the created people and their bindings, and
   the evidence and queue rows stamped after the cutover start.

It never touches a game log, prop, settlement, or team game result, and it refuses a database named `picks.db`.

Demo, on a disposable copy (`rollback_demo_report.json`): the cycle onboarded player 71985 with two bindings. The plan named
one created player, two bindings, two evidence rows, and no refusal. Apply removed the player and both bindings. Identity and
snapshot checksums and protected-history checksums were equal to their values before the cycle. The copy had no earlier
snapshot, so the restore step was not exercised by the demo. It is covered by
`test_rollback_restores_the_pre_cutover_identity_and_snapshot_state` and three other rollback tests (`test_mls_cutover_rollback.py`, 4 passed).

**Consumer gate.** Revert by unsetting `LP_MLS_CUTOVER` in the service environment. The setting is read from the process
environment, so the change takes effect when the service restarts. A restart needs its own approval (section 9).

## 8. Residuals: not part of the closure rule, each needs a decision

- **Remote publication**: blocked. The branch is committed locally at the engineering head above. The push needs an explicit
  authorization. Section 9, step 0 has the exact action.
- **Merge into `dev`**: decisions in `docs/mls-dev-lineage-2026-10-28.md`: the two origin/dev NFL commits, the 27 uncommitted
  paths, and the owner's agreement.
- **Name-only settlement**: open. Measured on production (read-only, 2026-10-28): 2,644 unsettled name-only MLS props, 1,626
  MLB, 2,136 NHL, 142 UFC, 14 NBA, and none for NFL or NCAAF. These now stay pending. Two decisions are open: fill player IDs,
  or anchor the club to the game's own log. See `docs/issues/settlement-name-only-pending.md`.
- **Prop history display**: `routers/props.py` (about line 408, NHL) still matches the box score by stored club when the player
  has no ESPN id. It displays past outcomes and does not settle. Tracked in the same issue.
- **Identity tables**: `identity_evidence` and `identity_onboarding_queue` are created at runtime by `ensure_schema` on the first
  cycle with `--mls-cutover`. They are not in a registered migration, so the migration check does not cover them.
- **Review queue**: the queue has no tool and no alert. The final rule adds `dob_ambiguous` items (B1). Review capacity needs
  an owner.
- **Stale audit labels**: four `mls_date_missing` records are now corroborated or ambiguous on live data. Re-run the identity
  audit.
- **N1**: a permanent dispute holds a person at their old club with no time limit. **N3**: Liga MX is not gated (no snapshot).
- **Observed, not verified or changed**: `settle_props.py` and `ingest_ufcalendar_dwcs.py` filter on `pg.date` against the
  calendar date, which the board's 2026-08-17 fix showed can disagree with kickoff instants.
- **Pre-existing em dashes** in `ingest_rotowire_props.py` and `routers/props.py` are unchanged. They predate this work.

## 9. Deployment checklist (rollout; none of this is done)

Each step needs its own authorization. The engineering closure does not depend on any of them.

0. **Publish the branch.** Authorize `git push -u origin integrate/mls-cutover-on-dev` from `/root/lp-mls-integrate`, at the
   engineering head `9e0eff33` or later. Never to `dev` or `main`. No force-push.
1. **Decide the merge into `dev`** with the running checkout's owner: the two origin/dev NFL commits (`382f5ffe`, `1d35e47e`), the
   27 uncommitted paths, and the untracked `picks.db`. The branch is based on `79e8e05d`.
2. **Move backups off this filesystem.** About 14.5 GB of retained copies sit on `/` (storage note N5 in the first closure report, `12c95204`). Free
   space was 6.9 GB after this work's copies were removed. The MLB history job writes a 2.9 GB copy daily. Confirm the job has room
   before rollout.
3. **Schema.** `identity_evidence` and `identity_onboarding_queue` are created at runtime on the first `--mls-cutover` cycle. Run the
   migration check on a production copy. Get explicit approval for any production database change. Production receives database
   changes, never a rebuild.
4. **Deploy the code with the switch off.** `LP_MLS_CUTOVER` unset. The scheduled roster job must not include `--mls-cutover`. Run
   the legacy end-to-end test (`test_legacy_path_untouched_when_cutover_off`) before and after deploying.
5. **Dry run on a production copy.** `LP_DB_PATH=<copy> python ingest_published_rosters.py mls --apply --mls-cutover`. Check that
   `identity_blockers=0`, one snapshot is published, about 1,040 memberships exist, and the review queue size is recorded. Run
   `protected_checksums.py` before and after. The history tables must be unchanged.
6. **Review the queue.** Review every `dob_ambiguous`, `dob_not_corroborated`, and `rekey_unverified` item before the switch is
   turned on. There is no review tool. Choose the reviewer and the method first.
7. **Settlement.** Record the pending count for name-only props before and after the deploy. The count should match the issue
   table. Settle nothing by hand from the stored club.
8. **Enable, in one window, with rollback ready.** Set `LP_MLS_CUTOVER=1` for the props service and the roster job together. This
   is a restart and needs approval.
9. **Monitor (not built).** Alert on: onboarding queue growth, `identity_blockers` above 0, snapshot age, the name-only pending
   count, and the props board club display. No alert exists yet. Live onboarding monitoring is part of this step.
10. **Rollback.** Unset `LP_MLS_CUTOVER` and restart the services. For identity writes, run `mls_cutover_rollback.py` in plan mode on
    a copy first, then apply with an archive only after the plan has been reviewed. Keep the incident backups in
    `docs/BACKUP-POLICY.md`.

## 10. Commits on `integrate/mls-cutover-on-dev` (after `79e8e05d`)

| Commit | Change |
|---|---|
| `293c570a` | Backup retention edits the running checkout uses, committed from the saved patch |
| `f7b8bfb4`, `7ece4a3b`, `b780e887`, `db044406`, `e06b2b8c`, `d986866f`, `476da153`, `8dbf6968`, `658ccdff` | The cutover (cherry-picked from `feat/mls-cutover-2026-10-28`) |
| `947b8d0a`, `e49abfe6`, `0a5c1c73`, `80c4888e`, `63d8730e`, `e830a606`, `5eebfc27` | The snapshot, shadow comparison, identity audit, and resolver audit (cherry-picked) |
| `0e091de0` | The earlier NOT DONE closure report, with its evidence (cherry-picked) |
| `6b5d606a` | Current lookups use membership evidence only; historical games fail closed |
| `0b2c77dc` | Current MLS club consumers read the membership snapshot; first inventory |
| `2e6c81a2` | Rollback tool and tests |
| `bef2f12e` | Read-only live onboarding shadow |
| `2fc706f3` | Dev lineage record |
| `fb5835ae` | Props club expression uses the board's upcoming rule (regression fix) |
| `319ad2f8` | RotoWire props for MLS under the gate: membership answers, no binding from a name match |
| `1dcff24c`, `80fb4390`, `5f3dcdb6` | Consumer inventory: RotoWire row, settlement residual, remaining readers |
| `12c95204` | The first DONE closure report, with the integrated evidence |
| `dcfad87e` | Cutover switch: a runtime setting, `LP_MLS_CUTOVER`, default off |
| `858f9b09` | Automatic onboarding: one unambiguous date of birth, both publishers agree |
| `9e0eff33` | Settlement: a name-only prop stays pending; tracked issue |
| this report's commit | Final status, deployment checklist, and the publication block |

## 11. Verification commands

```
cd backend
/usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_acceptance.py -v
/usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_setting.py test_mls_identity_dob.py test_mls_cutover_consumers.py test_mls_cutover_rotowire.py test_mls_cutover_rollback.py -v
/usr/bin/python3 -m pytest -p no:cacheprovider test_settlement_name_only.py -v
LP_MLS_E2E_DB=<migrated identity copy> /usr/bin/python3 -m pytest -p no:cacheprovider test_mls_cutover_e2e.py -v
/usr/bin/python3 ../docs/incidents/2026-10-27-mls-identity-closure-evidence/protected_checksums.py <copy>   # read-only
/usr/bin/python3 ../docs/incidents/2026-10-27-mls-identity-closure-evidence/recompute_shadow_unique_rule.py <report.json> <out.json>   # offline
/usr/bin/python3 mls_onboarding_shadow.py <production picks.db> <disposable copy> <pairs_v4.jsonl> <report.json>   # read-only shadow
LP_DB_PATH=<disposable copy> /usr/bin/python3 ingest_published_rosters.py mls --apply --mls-cutover   # never against production
/usr/bin/python3 mls_cutover_rollback.py <copy> --since <ISO timestamp>   # dry run; add --apply --archive PATH on a copy
```

`pairs_v4.jsonl` is in the evidence folder. The disposable copies were removed after the evidence was collected. Recreate them
with the SQLite backup API from a read-only connection, as in B4.
