# MLB identity repair — consolidated handoff

**Updated:** 2026-07-14 (America/Chicago)  
**Branch:** `feat/leagues-hub`  
**Current status:** implemented and proven on an isolated database copy; not applied
to shared development or production

## Executive summary

The MLB identity defect is a corrupted cross-source mapping, not a cosmetic naming
problem. In 135 safely resolvable cases, an ESPN-anchored canonical player row carries
another person's MLBAM ID while a source-only duplicate row carries the canonical
player's correct MLBAM ID. Renaming rows would preserve the bad crosswalk and attach
props, teams, and source data to the wrong people.

The branch now contains a reproducible read-only planner, a reviewed proposal, a
resolve-or-queue Statcast ingestion policy, and a hash-gated copy-only transactional
applier. The complete repair was validated on a fresh `/tmp` copy: all 135 safe
crosswalks were repaired, affected logs were re-resolved from stable source keys,
untrustworthy aggregates were archived and regenerated, props were preserved, and
the planner produced zero remaining safe proposals.

This work is parked while four-league team statistics are the product priority. Do
not apply or extend the identity repair merely because the tooling exists.

## What is complete

1. The planner audited the entire 2026 MLB population referenced by `player_stats`
   against the MLB Stats API People endpoint.
2. All 135 strict crosswalk proposals passed independent current-database row, name,
   identifier, and reference-count review.
3. Statcast ingestion no longer silently inserts missing MLB players. Missing or
   duplicate MLBAM IDs are recorded in `unresolved_players`, and their aggregates are
   skipped.
4. A copy-only applier performs the reviewed repair in one transaction and fails
   closed on database drift, proposal drift, unexpected references, or failed
   invariants.
5. A rollback dry run left the database copy byte-identical to its original hash.
6. A committed copy run passed SQLite integrity, archive, uniqueness, preservation,
   regeneration, and whole-population identity checks.

Local commits containing the work are:

- `609c949` — resolve-or-queue Statcast ingestion;
- `871f964` — whole-proposal population review;
- `819b174` — copy-only repair applier and copy application report.

## Measured population and repair outcome

The planner's current-season population contains 2,397 players and a 2,404-ID MLB
spine. The authoritative People snapshot resolved every ID. Before repair, the audit
found 2,222 exact identity matches, nine benign same-ID suffix display variants, 166
material mismatches, 135 strict repair proposals, and 31 deliberately unresolved
cases.

The isolated committed copy produced:

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
| Duplicate MLBAM groups after repair | 0 |

A fresh 200-day Statcast pull then regenerated 1,268 batting and 1,070 pitching
aggregates. All 135 repaired canonical players and all 32 represented displaced
candidates received regenerated data. The post-repair planner found zero safe
crosswalk proposals and only the expected 31 unresolved mismatches.

## Deliberately unresolved population

The remaining 31 mismatches are not safe to infer:

- 30 rows have no ESPN anchor, so there is no proven canonical side;
- one official name, Luis Castillo, maps to multiple MLBAM identities.

Separately, 103 displaced official identities were absent from the database and were
queued in the repaired copy instead of being silently created. The fresh Statcast run
observed another 26 off-spine IDs. These identities require a separate review and are
not part of the 135-proposal transaction.

## Durable artifacts

| Purpose | Artifact |
|---|---|
| Read-only proposal planner | `scripts/plan_mlb_identity_repairs.py` |
| Planner fixture tests | `scripts/test_plan_mlb_identity_repairs.py` |
| Reviewed proposal | `docs/MLB-IDENTITY-REPAIR-PROPOSAL-2026-07-13.json` |
| Planner and defect analysis | `docs/MLB-IDENTITY-REPAIR-PLANNER-2026-07-13.md` |
| Population review | `docs/MLB-IDENTITY-PROPOSAL-REVIEW-2026-07-14.md` |
| Copy-only transactional applier | `scripts/apply_mlb_identity_repairs_copy.py` |
| Applier guard tests | `scripts/test_apply_mlb_identity_repairs_copy.py` |
| Copy application evidence | `docs/MLB-IDENTITY-COPY-APPLICATION-2026-07-14.md` |
| Statcast identity behavior | `backend/ingest_statcast.py` |
| Statcast identity tests | `backend/test_ingest_statcast_identity.py` |

The original 3.1 MB MLB People response was retained outside the repository at
`/tmp/lp-mlb-people-2026.json`. It is ephemeral; the checked-in proposal contains its
SHA-256 and the official identities needed to review the proposal. A future apply
must fetch or retain a fresh authoritative snapshot rather than assume the `/tmp`
file still exists.

## Safety properties

The planner has no apply mode. It requires an explicit database path, opens SQLite in
read-only URI mode, enables `PRAGMA query_only=ON`, and writes only its JSON output.

The applier refuses:

- any database outside `/tmp`;
- symlinked or hard-linked database files;
- active SQLite WAL or SHM sidecars;
- a database or proposal whose SHA-256 differs from the supplied expected value;
- proposal-row, identity, reference-count, source-key, or population drift;
- unclassified player references or failed post-transaction invariants.

It archives complete original JSON payloads before deleting active game logs or
aggregates, wraps every mutation in `BEGIN IMMEDIATE`, and defaults to rollback unless
`--commit-copy` is explicitly passed. It cannot be pointed at the shared development
database without changing its code, and that guard must not be weakened casually.

## Shared-development and production boundary

No identity repair was applied to:

- the shared development database at
  `/root/legendarypicks/backend/data/picks.dev.db`;
- the shared backend or frontend runtime;
- the user-visible tunnel;
- production.

Shared-development mutation requires explicit user approval. Production is a
separate promotion requiring its own approval, backup, migration, and verification.
The isolated proof is evidence that the algorithm works; it is not authorization to
change either environment.

## Approved resume procedure

When identity repair becomes the priority again, use this sequence:

1. Obtain explicit approval before any shared-development mutation.
2. Capture the shared runtime commands, working directories, database path, and
   environment without restarting services.
3. Take a fresh SQLite-safe backup and verify `PRAGMA integrity_check` on the backup.
4. Fetch a fresh authoritative MLB People snapshot and generate a new proposal from
   the exact pre-apply database snapshot.
5. Review the new population. Do not assume the historical count remains 135.
6. Run the copy-only applier in default rollback mode using exact database and
   proposal hashes; confirm the copy remains byte-identical.
7. Run it again with `--commit-copy`, then regenerate affected Statcast aggregates and
   repeat whole-population identity, uniqueness, queue, archive, and props checks.
8. Review a before/after data diff from the fresh copy.
9. Only then design or authorize the shared-development migration. Preserve the same
   transaction, archive, hash, and invariant guarantees instead of bypassing the
   copy-only path guard.
10. After an approved shared-development application, verify the real API, browser,
    enrichment jobs, and unresolved queue without disrupting the shared runtime.

If any proposal, row count, source key, reference inventory, or hash differs from the
reviewed inputs, stop and regenerate the plan. Never repair by display-name guess,
move props away from their ESPN-anchored identity, reuse stale `player_stats`, or
infer game-log ownership from the current `player_id`.

## Current decision

Keep this work parked. The active product goal is measured, season-appropriate team
statistics for MLB, NBA, NFL, and NHL with explicit coverage guarantees. Identity
repair can resume later from this handoff without rediscovering the defect, proof, or
safety boundary.
