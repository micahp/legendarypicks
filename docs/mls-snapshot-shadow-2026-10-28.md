# MLS snapshot: shadow comparison, 2026-10-28

Development only. The snapshot is not wired into the roster job, and nothing here touched production. Both paths
were run on copies, fed the same squads from the same starting state. The harness is `backend/mls_snapshot_shadow.py`
and its raw output is `report.json` in the scratch folder (checksums in the evidence bundle).

## Verdict

The snapshot is correct on the population that exists today, and it handles departures and transfers that the legacy
path does not. It is not ready to replace the MLS roster path. Four things block replacement, and each is a decision
or a change, not a tuning:

1. `lookup_player` still returns people who are no longer in the squads. It returned 16 of 16 tested people who are
   not in today's squads, and a player removed in the leave scenario still resolves after the legacy run. It reads
   observation rows, not membership. Requirement 6 is not met.
2. The snapshot cannot add a person. A signing stays `partial` until someone binds the new keys by hand. The legacy
   path mints the player automatically.
3. A player who disappears from one publisher while still present in the other is accepted silently, with no flag.
4. A club disagreement between the two publishers refuses the whole MLS snapshot. A disagreement that does not resolve
   freezes every MLS membership update.

## What was run

- **Squads, fetched once:** FotMob 900 records and MLS Soccer 955 records, 30 clubs each. Neither fetcher has a disk
  cache (`paced_http.Fetcher` is built without a cache directory for MLS, and the FotMob `_get` has none).
- **Scope copy:** the identity tables (`players` 57,433; `player_source_ids` 10,423; `published_roster` 3,432;
  `published_roster_name` 3,788; `league_clubs` 311) and the game logs of MLS players (27,744). Opened read-only from
  prod. A full copy was not made: prod is 2.9 GB and the disk is at 99% with 4.0 GB free.
- **Legacy path:** the roster job's own `_write`, then `publish_identities`, in the job's order (FotMob, then MLS),
  run on a copy.
- **Snapshot path:** `mls_snapshot.build` on a copy, with no write. Publishing is tested separately.
- **Prod integrity:** row counts of `players`, `player_source_ids`, `published_roster`, `roster_snapshots`, `props`
  and `prop_results` were identical before and after the run. Prod keeps ingesting, so these counts can move between
  runs, but not during one.

## Today's real change: none

The live squads are identical to the 2026-10-27 fixture: no additions, no removals, no club changes in either publisher.
The MLS offseason may explain it, but it cannot be confirmed from one day. Because nothing moved, the scenarios below
are the only test of the transitions.

On the live squads, both paths agree on the same 1,040 people and clubs:

| | Legacy path | Snapshot |
|---|---|---|
| Outcome | 1,041 touched components, 0 refusals, 0 new binds, 0 new players | verified, 1,040 memberships |
| Blockers, carried, departures, transfers, rekeys | not applicable | 0, 0, 0, 0, 0 |
| People not in today's squads still resolved | 16 | 0 (not in membership) |

The 1,041 components resolve to 1,040 people, so one person is split across two components that both bind to him.
Harmless today, but the legacy grouping depends on spelling and club joins, not on binds.

The 16 people the legacy path still resolves are not in the 2026-10-27 squads, and they are not in the prior
snapshot either. So the snapshot reports no departure for them, and it correctly leaves them out of membership.

## Scenarios

Each scenario changes one thing in the live squads. Each row of the baseline is included in every case, so the
historical counts below subtract the 16 baseline people.

| Change | Legacy path | Snapshot | Reading |
|---|---|---|---|
| **Signs** (new keys in both publishers, not in the database) | Mints 1 player and binds both keys. 0 refusals. | `partial`, 2 blockers. The person is not in membership. | Snapshot cannot add people. Blocker 2. |
| **Leaves** (both keys removed) | Keeps the person bound. He still resolves by lookup. | Confirmed departure (player 32331). Membership 1,039. | Snapshot correct. Legacy stale. |
| **Transfers** (both keys move club; New England to NYCFC, player 32334) | Binds unchanged. Roster row moves. `players.team` unchanged (0 changed). | Transfer recorded. Membership at the new club. | Snapshot correct. `players.team` stale on legacy and never written by the snapshot. |
| **New publisher ID** (FotMob key for a bound player changes) | Refuses: `conflicts`, because the old FotMob key is still bound. The new key stays unbound. | `partial`, 1 blocker. Membership intact. | Neither rebinds. Both need a person. |
| **One publisher only** (FotMob drops a player; MLS keeps him) | No change. The FotMob key stays bound. | `verified`. Membership keeps the MLS key only. No flag. | Silent key loss. Blocker 3. |
| **Publishers disagree on a club** (FotMob moves a player; MLS does not) | Publishes. The two rows become two components bound to one person. No alarm. | Refuses the whole MLS snapshot: "1 identity conflicts". Prior snapshot stays. | Blocker 4. A permanent disagreement freezes all MLS membership. |
| **Club drop** (8 players missing from one FotMob club) | Publishes. The 8 keep stale FotMob bindings. | Refused: Real Salt Lake fell from 37 to 29. | Snapshot correct. Legacy silent. |
| **Club missing** (one FotMob club absent) | Publishes. The club's FotMob rows stay stale. | Refused: 29 clubs, and Atlanta fell from 29 to 0. | Snapshot correct. Legacy silent. |
| **MLS publishes nothing** | Publishes FotMob-only components. 156 people have no refreshed row this run, and their bindings are kept. | Refused: no members fetched. | Snapshot correct. Legacy silent. |
| **Repeat** (same squads, twice) | Second run: 0 binds changed, 0 players inserted. | `unchanged` on both runs. | Both stable. |
| **Degraded, then healthy** (club drop, then recovery) | Not applicable. | Degraded run refused, published checksum unchanged. Healthy run `unchanged`, `verified`. | Snapshot recovers cleanly. |

### Historical records affected

Counts for each changed person only, with the 16 baseline people subtracted. Props and prop results are in prod;
game logs are in the scope copy.

| Change | People | Game logs | Props | Prop results |
|---|---|---|---|---|
| Leaves (player 32331) | 1 | 16 | 61 | 16 |
| Transfers (player 32334) | 1 | 0 | 50 | 1 |
| Signs | 1 (new, no history) | 0 | 0 | 0 |
| New publisher ID, one publisher only | 0 | 0 | 0 | 0 |

The refused scenarios change no person, so they have no history to count.

### Defect found after this report, and fixed

The shadow repeats used squads with no transition in them, so they did not catch this. The population checksum
included the run's events (transfers, departures, rekeys, carries). After a transfer, a second run with the same
squads had `transfers=0`, so its checksum differed and it published an identical second membership set. Reproduced on
a scratch copy: snapshots 2, then 3. Fixed by hashing only the memberships. The events are stored with the population
and refreshed on every run. `test_mls_snapshot_repeats.py` repeats a transfer, a departure, a rekey, a key lost by one
publisher followed by a departure, and a carry, and each repeat publishes nothing.

## Blockers before any replacement

1. **`lookup_player` answers from stale observation rows.** `published_roster.lookup_player` matches on
   `published_roster` names with no date filter. The 16 baseline people resolved on all 16 names tested. A departed
   person in the leave scenario resolves the same way: Nick Markanich (32331) still returns his own id after the
   legacy run on the departure squads. The serving path (`_core.py`, about line 1193) reads this, so a
   replacement must change the lookup to check current membership before any roster cutover.
2. **The snapshot cannot add players.** Signings need a mint path with its own guards (the legacy path's name and club
   narrowing and its `unverified_team` refusal), or a review queue with a measured backlog. The design has neither.
3. **Silent key loss.** A person whose key disappears from one publisher while the other still lists him is accepted
   with no flag. The snapshot needs a per-person record of the missing key and a coverage reason.
4. **Club disagreement refuses the whole league.** One disagreement blocks the entire MLS snapshot. The alternative is
   a per-person hold, reported as partial, with the disputed person kept at the prior club. This is a policy choice.
5. **`players.team` has no owner.** The legacy path never updates it (its update is `COALESCE`), and the snapshot does
   not write `players`. A transfer leaves the old club in `players.team`. `refresh_soccer_player_teams.py` copies that
   value, and it runs by hand.
6. **Liga MX and Leagues Cup were not exercised.** The shadow runs MLS only. The snapshot reads `lcup` binds
   (`binds_from_db` takes `mls` and `lcup`), and Leagues Cup keys are borrowed from the home person. A change to a
   borrowed bind is not covered by this run.

## Not done

## Tests

- `test_mls_snapshot.py`, `test_mls_snapshot_regression.py`, `test_mls_snapshot_shadow.py`, `test_published_roster.py`,
  `test_spine_merge.py`: 109 passed (Python 3.8, pytest 8.3.5).
- Full backend suite, merged branch (`5bb5e4e8`): 80 failed, 3,484 passed, 39 skipped.
- Full backend suite, dev head (`79e8e05d`), same worktree environment: 80 failed, 3,454 passed, 39 skipped.
- The 80 failing tests are the same tests in both runs. They fail on a missing schema in the worktree database
  (for example `no such table: player_game_logs_sportsdataverse`), not on code this branch changes. So the merge
  adds no failures. The suite is not green in this worktree, and it has not been run against the real dev database.

## Not done

- No wiring into the roster job. Running a shadow inside `ingest_published_rosters.py` would change code that the
  production timers run from the dev working tree, so it needs an explicit go.
- No full-database copy. Disk space is the constraint, and the identity scope is what the paths read.
- One day of live squads, with no change in it. The scenarios are constructed from real records, but they are not
  observed events.
- The audit items (named source errors, access per URL, tracked categories) are in the evidence branch as commits
  `e9b89cd7` and `751bbc34`, not here. Nothing was pushed.
