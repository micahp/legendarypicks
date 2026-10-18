# TASK: repair the NFL mixed-ID crosswalk without name matching

## Classification and clone rehearsal (2026-10-10)

Do not treat all 6,340 non-`00-` values in `players.nfl_gsis_id` as defects. Against a fresh,
complete nflverse player register (24,853 rows; SHA-256
`48aa03d4910d82cc7156f1faa4624836c969a324ae6d768fbd38d08766030975`), 5,673 are exact values in
the publisher's `gsis_id` column and 667 are absent under that value. The old 2026-08-05 snapshot
and its 654-row classification are stale.

The clone plan contains 674 actions: those 667 nonstandard values, five standard-looking IDs absent
from the register, and two values that are published GSIS IDs but belong to different people than
the rows' ESPN IDs. Of the 6,340 nonstandard values, 5,671 remain as valid published GSIS IDs;
the two other valid-but-wrong-person IDs are replaced. The plan dispositions are:

- 472 set to a publisher `gsis_id` through stable source-ID evidence and consistency gates:
  457 via ESPN plus ESB, 13 via ESB, and two via ESPN with matching name and position.
- 202 cleared to NULL; the previous key is preserved in `player_source_ids` (200 have no unique
  publisher-ID bridge; two fail the publisher-name consistency gate).
- 183 of the actions affect player rows used in the current-season logs or shares. No name-based
  identity discovery, duplicate target ownership, or protected-reference changes.

The 674-action plan was applied only to `/tmp/lp-nfl-identity-repair.LSkYRO/picks.dev.fixed.db`,
cloned from the read-only baseline. It updated 674 player rows, inserted 674 typed crosswalk rows,
left zero unpublished GSIS values, found zero duplicate GSIS owners, preserved every player
reference and the fingerprints of logs, shares, stats, and props, and passed `PRAGMA quick_check`.

The 2026 play-by-play comparison went from 218 differing player-games (109 each direction) to zero.
The five existing 2026 log rows with `player_id IS NULL` carry zero-valued stat payloads and were
not changed. Stored shares remain the publisher's values; their byte-level table fingerprint is
unchanged.

## Forward prevention: do not schedule the repair

A clone repair only reconciles rows that already exist. Gate G is a detector, not a write guard;
running the repair every day would conceal an unfixed producer.

The writer inventory found no scheduled NFL ingest that directly assigns `players.nfl_gsis_id`.
Weekly stats, depth charts, snap counts, injuries, and NGS read it for resolution. The recurring
roster and ADP ingests can attach an ESPN ID to an existing name-matched row, which could preserve
or create an ESPN/GSIS identity conflict. Both now check nflverse's committed ESPN-to-GSIS
crosswalk before that assignment. Explicit promotion (`migrate_logs_to_prod.py`) and generic merges
(`spine_merge.py`) also reject known conflicting ESPN/GSIS pairs. Gate G now checks the same
cross-source relationship as a detector.

The original import or manual action that populated the mixed values remains unidentified. The
tracked write, promotion, and merge paths above are now guarded and have regressions replaying the
conflicting ESPN/GSIS shape. The one-time repair remains a clone rehearsal, not a recurring job.
Do not write DEV or production without a separately reviewed apply plan.

## Required work

1. Register: 24,853 rows, SHA-256
   `48aa03d4910d82cc7156f1faa4624836c969a324ae6d768fbd38d08766030975`; ESPN crosswalk has 16,578
   unique IDs and no ambiguous ESPN IDs.
2. Gate G: the baseline fails on 459 explicit ESPN/GSIS conflicts. The repaired clone passes; all
   1,521 current-season nflverse source keys are in the publisher map, with no current player outside it.
3. Remaining repair holds are the 202 rows cleared to NULL: 200 unbridged and two name-disagreement
   cases. They are not guessed. The register itself has one duplicate ESB key and one duplicate smart
   key; neither was used to set a repair target.
4. No DEV or production database, service, deployment, or remote repository was changed.

No DEV/prod writes, service changes, deploy, push, or name-only repair without a separately reviewed apply plan.
