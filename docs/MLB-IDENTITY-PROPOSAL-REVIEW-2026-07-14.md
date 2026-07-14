# MLB identity proposal population review

**Date:** 2026-07-14

**Artifact reviewed:** `MLB-IDENTITY-REPAIR-PROPOSAL-2026-07-13.json`

**Database:** current development database, opened read-only with `query_only=ON`

## Decision

The 135 proposed canonical/source crosswalks pass structural population review. No
proposal failed its current-database row, name, identifier, or reference-count checks.
This is enough to proceed to design and test a transactional applier on a database
copy. It is **not** approval to mutate the shared development database.

## What was checked

For every proposal, the review independently re-read the current database and
confirmed:

- the canonical and source player rows still exist;
- both rows normalize to the stored and official player name;
- the canonical row has the recorded ESPN ID and displaced MLBAM ID;
- the source row has no ESPN anchor and has the correct MLBAM ID;
- canonical and source reference counts still match the artifact for props, logs,
  aggregates, and predictions;
- all 135 canonical IDs and all 135 source IDs are unique and disjoint.

Result: **135 reviewed, zero anomalies**. Database integrity was `ok`.

## Displaced identities

The displaced side divides into two materially different populations:

| Population | Count | Required treatment |
|---|---:|---|
| Exact represented candidate | 32 | Move the displaced MLBAM ID to the candidate row |
| Not represented | 103 | Queue the official identity; never create it silently |

All 32 represented candidates:

- exactly match the displaced official name;
- are ESPN-anchored;
- currently have no MLBAM ID;
- are disjoint from every proposal's canonical and source rows;
- collectively own 995 props and no game logs, aggregates, or predictions.

Those rows are real product identities. An applier must preserve them and attach the
displaced MLBAM ID to them. Treating them as duplicates of the canonical row would
move 995 props onto the wrong players.

## Rows that remain out of scope

The 166 review-queue entries remain intentionally unresolved:

| Reason | Count |
|---|---:|
| Displaced official identity not represented | 103 |
| Displaced official identity candidate requires reviewed reassignment | 32 |
| Mismatched row has no ESPN anchor | 30 |
| Stored official name is non-unique | 1 |

The single non-unique name is Luis Castillo. The 30 rows without an ESPN anchor do
not have a safe canonical side and must not be folded into this transaction.

## Transaction constraints for the next task

A copy-only applier must perform one transaction and fail closed unless the artifact
still matches the database exactly. Its order of operations must account for both
sides of each incorrect crosswalk:

1. Revalidate every row, identifier, and reference count from the reviewed artifact.
2. For the 32 represented displaced identities, attach the displaced MLBAM ID to the
   exact ESPN-anchored candidate.
3. For the 103 absent displaced identities, persist an unresolved queue entry keyed
   by the displaced MLBAM ID.
4. Move the correct MLBAM ID from the source row to the canonical ESPN row without
   leaving a duplicate MLBAM assignment.
5. Re-resolve affected game logs from `source_player_key`; never infer their identity
   from the current `player_id` or display name.
6. Regenerate affected MLB `player_stats`; do not copy or rename the existing rows.
7. Preserve all props on their current ESPN-anchored identities.
8. Assert uniqueness, reference totals, queue coverage, and transaction rollback on
   any mismatch.

Only after a fresh-copy application and whole-population before/after audit should
permission be requested for shared-development-database mutation.
