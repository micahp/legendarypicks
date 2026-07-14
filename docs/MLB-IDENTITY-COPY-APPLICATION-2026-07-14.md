# MLB identity repair: copy application report

**Date:** 2026-07-14

**Scope:** isolated `/tmp` database copy only. The shared development and production
databases were not mutated.

## Outcome

The reviewed 135-proposal repair applied successfully in one transaction to a fresh
copy of the current development database. SQLite integrity passed before and after.
The transaction was first executed as a rollback dry run; after performing every
mutation, the copy's SHA-256 was byte-identical to its pre-run value.

The committed copy run produced:

| Change | Count |
|---|---:|
| Canonical ESPN rows assigned the correct MLBAM ID | 135 |
| Represented displaced candidates assigned their MLBAM ID | 32 |
| Source-only duplicate player rows removed | 135 |
| Correct-key logs moved to canonical rows | 2,781 |
| Displaced-key logs moved to represented candidates | 1,380 |
| Unrepresented displaced logs archived | 5,213 |
| Existing aggregates archived for regeneration | 404 |
| Absent displaced identities queued | 103 |
| Affected props preserved in place | 7,342 |
| Duplicate MLBAM groups after application | 0 |

The archive retains the full original JSON payload, player ID, source key,
disposition, run ID, and timestamp for every removed log and aggregate.

## Copy-only safety controls

`scripts/apply_mlb_identity_repairs_copy.py`:

- refuses database paths outside `/tmp`;
- refuses symlinked and hard-linked database files;
- refuses active SQLite WAL/SHM sidecars;
- requires exact database and reviewed-proposal SHA-256 values;
- revalidates all 135 rows, names, IDs, reference totals, and log source keys;
- inventories every table containing `player_id` before deleting a source row;
- archives data before removing it from active joins;
- asserts expected archive, queue, reference, and MLBAM uniqueness totals;
- wraps all mutations in `BEGIN IMMEDIATE` and rolls back on any mismatch.

## Authoritative aggregate regeneration

The repaired copy was regenerated from a fresh 200-day Statcast pull:

- 463,785 pitches;
- 1,377 batters and 1,091 pitchers observed;
- 1,268 batting and 1,070 pitching aggregates written;
- all 135 repaired canonical players received regenerated aggregates;
- all 32 represented displaced candidates received regenerated aggregates (34 rows,
  including two-way/stat-type cases).

Resolve-or-queue handled 129 off-spine Statcast IDs without creating players. All 103
absent displaced IDs were among that population; the remaining 26 are newly observed
off-spine IDs and remain queued for separate identity review.

## Whole-population official identity result

Rerunning the proposal planner against the repaired and regenerated copy produced:

| Metric | Before | After |
|---|---:|---:|
| Safe crosswalk proposals | 135 | 0 |
| Stored-name/official-name mismatches | 166 | 31 |
| Exact identity matches | 2,222 | 2,257 |
| Duplicate MLBAM groups | 0 | 0 |
| Missing official MLBAM IDs | 0 | 0 |

The 31 remaining mismatches are exactly the deliberately unresolved population:

- 30 mismatched rows with no ESPN anchor;
- one non-unique official name, Luis Castillo.

No new repair proposal was generated for any of the 135 repaired identities.

## Approval boundary

This copy proof does not authorize shared-development mutation. Before changing the
shared database, obtain explicit approval, take a fresh backup, regenerate the
proposal against the exact pre-apply snapshot, require matching hashes, and repeat
the full API/browser/enrichment verification after the transaction.

Production remains a separate promotion with its own backup, migration, and approval.
