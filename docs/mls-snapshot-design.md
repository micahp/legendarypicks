# MLS snapshot: design, consumers, and the coverage tradeoff

Development design for the MLS current-membership snapshot. Not wired into the roster job.

## Two guarantees, two stores

| Question | Answered by | Changes over time? |
|---|---|---|
| Which canonical person is this publisher key? | `player_source_ids` (binds) | Yes, but history is kept: a bind is never silently rewritten |
| Who is on which MLS club now? | `roster_snapshots` (latest published) and `roster_memberships` | Replaced each verified run; prior snapshots are kept as superseded |
| What did each publisher observe, and when? | `published_roster` | Upserted; a row is a last observation, not a history |

The snapshot answers membership. Identity lookups answer identity. Neither writes the other.

## Data flow

Current (roster job):
1. Fetch FotMob and MLS Soccer squads.
2. Upsert the observations into `published_roster`, stamped with the run time.
3. `publish_identities` builds identity groups from every row in the league, stale rows included. It binds,
   refuses, or mints.

Proposed (snapshot path):
1. Fetch both squads. Each run's squads are the only membership evidence.
2. `prior_state` reads the latest published snapshot from the database. Callers cannot pass prior counts.
3. `check_completeness`: 30 clubs per source, a minimum club size, and abnormal club or total drops against
   the prior counts. Any failure refuses. Nothing publishes and the current snapshot stays.
4. `resolve`: lookup only. One membership per person. Conflicts (two keys from one source, or sources that
   disagree on a club) refuse.
5. `_classify`: compare with the prior snapshot, person by person. It sorts people into carried, blocker,
   confirmed departure, single-source departure, bind moved, transfer, and rekey.
6. `build` sets the coverage: `verified` or `partial`, with every count recorded in the payload.
7. `publish`: a checksum of the population (the memberships), not the fetch time or this run's events. An
   unchanged population refreshes the verification time and the stored events, and creates no second membership
   set. Transfers, departures, rekeys and carries are reported on the run that sees them and not hashed, so a repeat
   of the same squads after a transition publishes nothing.

## Coverage: the tradeoff

Unresolved keys can appear when a publisher adds a player. Two options:

| Option | What happens | Cost |
|---|---|---|
| A. Refuse publication when any key is unresolved | The current snapshot stays. Freshness stops for every club until a person resolves the key. | One new player blocks all membership updates. |
| B. Publish a `partial` snapshot with measured reasons | The new snapshot lists every blocker, carried person, and single-source departure. Health reports the counts. | Consumers must read the coverage before treating membership as complete. |

Chosen: **B**. A new player should not freeze freshness for 1,040 people. The snapshot must not claim to be
complete when it is not, so coverage is in the payload and in `health()`. Refusal is kept for the cases
where the data itself is untrustworthy: incomplete squads, identity conflicts, and a club count other than 30.

## Consumers, mapped before integration

Lookups (`published_roster.lookup` and `lookup_player`):

| Consumer | Use | Effect of the snapshot |
|---|---|---|
| `_core.py` (about line 1193) | Serving-time name to player for props. Read only; never fetches or mints. | Reads observations, not membership. Should resolve through current binds, and accept a name only when the bound person is current in the latest verified snapshot. |
| `spine_merge.py` (about line 212) | Roster claims for merge planning | Merge evidence should come from the latest verified membership, not from stale rows. |
| `backfill_from_published_roster.py` (about line 83) | Backfill of player IDs from observations | Historical use. Keep, with the same current-membership restriction for current-season scope. |
| `migrate_published_roster_name.py` | Name spelling table migration | Unaffected. |
| `club_crosswalk.py` | `fold` only | Unaffected. |

Publication (`publish_identities`): called only by `ingest_published_rosters.py` (the roster job). Tests call it
too. Unchanged until the snapshot path is wired.

Readers of `published_roster` rows:

| Reader | Concern |
|---|---|
| `refresh_soccer_player_teams.py` | Copies a club from the observation rows into `players.team`. A stale row can supply a club that no current squad lists. It should read the latest verified membership instead. It is a manual script, not on a timer. |
| `ingest_registry.py` (freshness) | Checks the newest MLS observation within 72 hours. It should use the snapshot's verification time, so a partial snapshot is visible rather than hidden by fresh observations. |
| `identity_status.py` | Reads `ingest_runs`. Not affected. |
| `repair_reviewed_player_names.py` | Name repair. Not affected by membership. |

## Leagues Cup

Leagues Cup keys bind to the home MLS or Liga MX person. The snapshot never creates a Leagues Cup membership and
never rewrites a club from a competition. The test `test_leagues_cup_keys_resolve_through_the_database_lookup_to_the_home_mls_person`
runs through `binds_from_db`, and `test_a_leagues_cup_key_bound_to_a_different_person_is_a_bind_disagreement`
covers a disagreement.

## What is not yet proven

- Identity accuracy for the cross-source pairs. See the audit report in the evidence bundle. Membership accuracy
  (who is on which club now) is the snapshot's guarantee. Identity accuracy depends on the binds.
- Completeness by count is coarse: a drop of up to three players per club passes. The per-person comparison
  (`_classify`) is the finer check, and it reports rather than refuses.
- Consumers above are mapped, not migrated. Migration is a separate, reviewed change.
