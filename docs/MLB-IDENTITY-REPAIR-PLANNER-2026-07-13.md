# MLB identity repair planner — dry-run review

**Date:** 2026-07-13 (America/Chicago)
**Branch:** `feat/leagues-hub`
**Status:** proposal only; not approved or ready to apply

## Artifacts

- Planner: `scripts/plan_mlb_identity_repairs.py`
- Fixture tests: `scripts/test_plan_mlb_identity_repairs.py`
- Full proposal and review queue:
  `docs/MLB-IDENTITY-REPAIR-PROPOSAL-2026-07-13.json`
- Authoritative source: MLB Stats API People endpoint
- Source snapshot SHA-256:
  `5ea6511c0911ac9e8c58874e7cc991f2b2249e69fe1db111006bd47bd0430fec`

The 3.1 MB raw MLB response was retained outside the repository at
`/tmp/lp-mlb-people-2026.json`. The proposal contains the source hash and every
official identity needed to review its proposed changes.

## Safety contract

The planner has no `--apply` option and contains no mutation path. It requires an
explicit database path, opens SQLite with `mode=ro`, enables `PRAGMA query_only=ON`,
and writes only its JSON artifact.

The whole-population run used an integrity-checked SQLite backup at
`/tmp/lp-mlb-identity-audit.db`, not the shared development database. Its SHA-256 was
the same before and after both planner runs:

`18672b4ebd9f254bd788e03a3b8ba85f5870a4048a7a20b001ff6998db06e796`

No frontend, backend runtime, tunnel, shared development database, or production
database was changed.

## What the defect actually is

This is not primarily a name-display defect. It is a corrupted cross-source mapping.
An ESPN-anchored canonical row may carry the MLBAM ID of a different person while a
separate source-only row carries the correct MLBAM ID for the canonical row's name.

Examples from the proposal:

| Canonical row | Correct MLBAM | Incorrect attached MLBAM | Incorrect ID belongs to | Source row |
|---|---:|---:|---|---:|
| Ethan Roberts (`26777`) | `681799` | `808982` | Jung Hoo Lee | `27919` |
| Erick Fedde (`26950`) | `607200` | `660670` | Ronald Acuña Jr. | `27856` |
| Jack Perkins (`26984`) | `678022` | `592450` | Aaron Judge | `28161` |

Renaming the canonical row to the person identified by its incorrect MLBAM ID would
therefore make the corruption worse: it would attach the wrong ESPN identity, props,
and team to that person.

## Matching policy

A safe crosswalk proposal is emitted only when all of these are true:

1. The mismatched canonical row is the only exact-name row with an ESPN ID.
2. The stored name maps to exactly one official MLBAM identity in the authoritative
   population.
3. That correct MLBAM ID exists on exactly one separate database row.
4. The separate row has the same suffix-preserving normalized name.
5. The separate row has no conflicting ESPN ID.
6. Neither the database nor the official source contains a duplicate MLBAM ID.

Accents, punctuation, casing, and whitespace are normalized. Suffixes remain
significant for cross-ID matching so `Luis Garcia` cannot silently match `Luis Garcia
Jr.` or another similarly named person.

For the same MLBAM ID only, omission of a terminal `Jr`, `Sr`, `II`, `III`, `IV`, or
`V` is classified as benign display variation. This same-ID tolerance can never make
a repair proposal match two different IDs.

## Whole-population result

Population rule: distinct MLB players referenced by 2026 `player_stats`.

| Measure | Count |
|---|---:|
| Current-season population | 2,397 |
| MLBAM IDs in the full MLB spine | 2,404 |
| IDs resolved by the official People endpoint | 2,404 |
| Missing official IDs | 0 |
| Duplicate database MLBAM groups | 0 |
| Duplicate official MLBAM IDs | 0 |
| Exact stored-name/official-name matches | 2,222 |
| Same-ID suffix-only display variants | 9 |
| Remaining identity mismatches | 166 |
| Strict, uniquely supported crosswalk proposals | 135 |
| Mismatched rows requiring manual resolution | 31 |

The earlier handoff reported 169 mismatches, but the exact comparison implementation
used for that audit was not retained. The new planner makes the policy reproducible:
there are 175 strict display-name disagreements; six are `Jr.` omissions and three
are `II`/`III` omissions. Excluding only the six `Jr.` variants yields 169; excluding
all nine terminal-suffix-only variants yields 166. The three additional benign cases
are Victor Scott II, Robert Hassell III, and Lou Trivino III.

The planner does not hide other same-ID differences. Max P. Muncy versus Max Muncy,
Cam versus Cameron Cauley, and Jose Miranda versus Jose F Miranda remain queued
because they require an alias or authoritative human decision rather than suffix-only
normalization.

## Review queue

Each of the 135 proposals also displaces the official person currently represented by
the incorrect MLBAM ID. Every displaced identity is explicitly queued:

| Queue reason | Count |
|---|---:|
| Displaced identity has no other database representation | 103 |
| Displaced identity has one candidate requiring review | 32 |
| Mismatched row has no ESPN anchor | 30 |
| Stored name is not unique in the official population | 1 |

The non-unique official name is Luis Castillo, which maps to two official MLBAM IDs.
No choice is proposed.

## Downstream impact of the 135 proposals

The planner inventories both sides of every proposed consolidation:

| Reference | ESPN-anchored canonical rows | Correct-MLBAM source rows | Total |
|---|---:|---:|---:|
| `props` | 6,347 | 0 | 6,347 |
| `player_game_logs` | 6,593 | 2,781 | 9,374 |
| `player_stats` | 270 | 134 | 404 |
| `predictions` | 0 | 0 | 0 |

This determines the eventual application strategy:

- Props remain on the ESPN-anchored canonical identity.
- Game logs cannot be moved by current `player_id`; they must be re-resolved from
  their stable `source_player_key` after the crosswalk is corrected.
- Existing MLB `player_stats` for affected identities are not trustworthy enough to
  reassign and must be regenerated from authoritative sources.
- Any future predictions derived from affected features must be invalidated and
  regenerated.
- Displaced identities must resolve to an exact canonical row or enter the unresolved
  queue; they must never be silently inserted.

## Known recurrence path

At proposal-generation time, `backend/ingest_statcast.py` still called
`_resolve_or_add` and inserted a new `players` row when an MLBAM ID was absent from
the spine. That violated the repository's resolve-or-queue rule and could recreate
split identities after a repair.

The branch now closes that recurrence path. Statcast resolves only unique MLBAM IDs
already present in the spine. Missing or duplicate IDs are written to
`unresolved_players` with `source_player_key` and `reason`, and their aggregate rows
are skipped. Isolated full-ingest tests and a real-schema database-copy audit confirm
that unresolved input changes the queue but never the `players` population.

## Approval gate and next bounded task

This proposal is deliberately marked `ready_for_apply_planner: false`. Before any
shared-database mutation:

1. **Completed on this branch:** review all 135 crosswalk proposals and 166 queue
   entries; see `MLB-IDENTITY-PROPOSAL-REVIEW-2026-07-14.md`.
2. **Completed on this branch:** harden Statcast ingestion to resolve-or-queue with
   no silent player insertion.
3. **Completed on this branch:** design a transactional, hash-gated, copy-only
   applier with explicit invariants and rollback.
4. **Completed:** apply it to a fresh database copy after a byte-identical rollback
   dry run.
5. **Completed on the copy:** re-resolve source-keyed logs and regenerate affected
   MLB aggregates from a fresh Statcast pull.
6. **Completed at the data layer:** re-run whole-population identity, coverage, and
   props-preservation checks. Real-runtime verification remains required after any
   approved shared-development application.
7. **Completed:** review the copy's before/after diff; see
   `MLB-IDENTITY-COPY-APPLICATION-2026-07-14.md`.
