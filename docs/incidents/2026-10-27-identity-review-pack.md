# Identity review pack, 2026-10-27

Review pack for the MLS roster and identity work that followed the 2026-10-27 incident. Nothing in this
pack has been applied to prod. The incident diagnosis is in `docs/incidents/2026-10-27-identity.md`.

## Done, no prod writes

- The stale-row check is reverted on dev (`8f566485`). Identity tests pass (79). Prod's next roster run
  uses this reverted code.
- The repair's original values are preserved in
  `incident-2026-10-27-identity/evidence/repair_stale_rows_old_values.json`. The repair changed only
  `team` and `team_code` on three rows. `updated_at` and `player_id` are untouched.
- The restore script is written but not run:
  `incident-2026-10-27-identity/evidence/restore_repaired_rows.sql`. It has three guarded updates and
  rolls back if any count is wrong.
- Both current MLS squads were fetched read-only with the job's own providers. The results are saved in
  `incident-2026-10-27-identity/evidence/mls_squads_2026-10-27_readonly.json`.

## Key facts

- FotMob has 900 players across 30 clubs. MLS Soccer has 955 across 30 clubs.
- The latest run stamped 1,855 rows. That is exactly 900 plus 955, so the stamp matches the current
  squads. The 25 unstamped rows are on neither squad. The timestamp is an accurate current-membership
  signal for this run.
- Every current key already has a bind, so no new identities are needed for the current roster.
- Those 1,855 keys belong to 1,040 players. 815 have one FotMob key and one MLS key. None has two keys
  from the same source.
- The two blockers are stale rows, not current players.

## Current flow

Fetch, upsert with a timestamp, build identity groups from every row (stale ones included), bind or
refuse, report blockers.

## Proposed flow

Fetch both sources, check completeness, resolve each member to its existing player, publish one MLS
snapshot, and build identity groups from that snapshot only. Old rows stay as history. A failed check
publishes nothing, so the last snapshot stays current.

## Reuse, no migration

- `roster_snapshots` (one published snapshot per league) and `roster_memberships` (one row per player per
  snapshot). Prod already has these tables.
- `publish_roster_snapshot` already requires a full population, same-league owners, and an exact team
  count, and it supersedes the previous snapshot.
- `published_roster` stays as the raw observation log.
- `player_source_ids` keeps the bindings. Leagues Cup keeps using home-league binds, with no shadow
  players.

## Coverage checks (proposed thresholds)

- Both sources have 30 clubs. Every club has at least 20 players (observed minimum: 25). Every member maps
  to a player.
- Any failure means nothing publishes.

## Evidence

| | Thayllon | David Ruiz | Marcos Zambrano |
|---|---|---|---|
| Canonical player | 71244 (LAFC) | 58681 (RBNY) | 32334 (NE) |
| Current keys | FotMob 1738398, MLS 315209968 (both LAFC) | FotMob 1348286, MLS 541416 (both RBNY) | FotMob 1794408, MLS 540256 (both NE) |
| Different person | FotMob 1259117: Paysandu, born 2001, historical row | FotMob 1787871: CD FAS, born 2006, historical row | None |
| Game logs | LAFC, 2 games, 11 to 15 Oct | MIA, 11 games, Feb 2025 to Aug 2026; RBNY, 6 games, 6 Sep to 24 Oct | None |
| Status | Current | Current, MIA to RBNY transfer | Current, publisher rekey (old key 315191673 last seen 10 Sep) |
| Why refused before | Stale 1259117 row grouped with the current LAFC Thayllon | Stale 1787871 row grouped with the current RBNY Ruiz | The old bind still counted, so the new key looked like a second key |

## The repairs

The three repaired rows say Paysandu and CD FAS, but their timestamps are September. That claims an
observation nobody made. The original LAFC and RBNY values were real September observations, so the
repair overwrote history. Recommendation: restore them.

## Before and after, on a prod-shaped copy

- Before: 1,855 current keys, 1,040 players, 2 blockers (both stale rows), 0 unresolved current players,
  1,415 MLS players, 27,744 MLS-player game logs, 866,857 prop rows.
- After: a new MLS snapshot with 1,040 memberships. Blockers should fall to 0 because stale rows leave the
  identity step. That is a result of correct logic, not the goal. Historical rows and player counts should
  not change.

## Tests

- Namesake: a new CD FAS David Ruiz must not bind to the RBNY Ruiz.
- Transfer: a club change shows in the new snapshot, and the old snapshot stays.
- Rekey: only with an explicit reviewed mapping.
- Partial fetch: no publish, and the last snapshot stays current.
- Repeated ingestion: same payload, no duplicate memberships.

Each test must fail on the current code where the behavior is wrong.

## Logs and props proof

Checksum `player_game_logs`, `props`, and `prop_results` before and after on the copy. Expected result:
no change.

## Decisions needed

1. Restore the three repaired rows to their September values? The restore script runs after review.
2. Build the snapshot path on a dev branch and test it on the prod copy?
3. Rekeys: only from an explicit reviewed mapping, never inferred. Recommended.
