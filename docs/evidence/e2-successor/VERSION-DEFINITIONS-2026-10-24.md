# E2 successor: version definitions (2026-10-24)

Every E2 game record carries two stamps. Both are defined and computed in `scripts/nfl_sequence/versions.py`. This document is
the only place their meaning is written down. The stage labels they replace are listed at the end, and the scoped-out
transitions are listed in `UNMODELLED-TRANSITIONS-300-2026-10-24.md`.

## model_version

- **Meaning:** the commit of the engine that produced the record. It is the most recent commit that changed any file in
  `ENGINE_FILES`: `game_state.py`, `e1_drive.py`, `e2_reference.py`, `e0_single_play.py`.
- **Stamped by:** `versions.stamp()`, which refuses to run while any engine or rule file has uncommitted changes. So the value
  always names code that exists and was run.
- **Value on the seed-1 record:** `75962ffe5fca9eddee9b49ff377031c5075e2c16` (the last engine commit, `75962ffe`).
- **Changes when:** an engine file changes. It does not change for evidence, scripts, tests or documents.

## rules_version

- **Meaning:** the SHA-256 of the canonical JSON (sorted keys, no whitespace) of the map `{path: sha256(file)}` over
  `RULE_FILES`: `game_state.py`, `rules_matrix.py`, `e1_drive.py`, `shared_v1.py`. This is the scoped producer set the
  Gridiron envelope already pins under `source.producer_file_sha256`.
- **Why not the envelope file hash:** the envelope contains the record, so its hash would depend on the value it is meant to
  carry.
- **Value on the seed-1 record:** `7f0578bf96dc05eb2c217e247aaac6a7cc3695ae5f975af3e4457263450bc167`.
- **Changes when:** a file in `RULE_FILES` changes. That includes `shared_v1.py`, the v1 projection, which is in the scope the
  envelope already pins.

## What the two stamps mean for a record

- `complete_regulation` is true only for a game with no unmodelled transition and no block. A guarded game is never a
  complete regulation game.
- `regulation_end_reached` is the simulation fact: the game reached regulation end without a block.
- `complete_game` is true only when the game is unblocked, untied and free of unmodelled transitions.
- `status` is `regulation_end_guarded` for a game that reached regulation end but contains an unmodelled transition.
- `valid_full_game` is false for every record, because the unsupported-rule list is never empty.

## Which commit the survey ran at

The survey and the enumeration were run at the engine commit in the record's `model_version`, `75962ffe`. The survey document
(`SURVEY-300-SUCCESSOR-2026-10-24.md`) gives the counts from that run.

## Stage labels replaced

- `e1_drive.py`: `MODEL_VERSION = 'e1-empirical-v0'` and `RULES_VERSION = 'e1-drive-2026-10-24'`. These stay on E0/E1 standalone
  fixtures, which are not E2 records.
- `shared_v1.py`: `rules_version = 'nfl-2026-regular-season'` and `model_version = e1.MODEL_VERSION`. The v1 document now reads both
  from the record, and it refuses a record without them (`test_shared_v1.Stamps`).
- The Gridiron contract example values (`nfl-seq-v0.1`, `nfl-2026-regular-season`) are not used.

## Consumer checks

- The record's `rules_version` must equal the `rules_version` recomputed from the envelope's `producer_file_sha256` map.
- The record's `model_version` must be a commit in the producing repository, and the envelope's `source.base_commit` must be a
  commit at or after it.
- Gridiron's viewer requires a complete regulation record. A guarded record is therefore refused by the viewer, and accepted by
  structural validation with its findings reported (`gridiron-adapter-proof-*.json`, both modes).
- Gridiron's cache key `(game_id, snapshot_hash, model_version, rules_version, seed)` changes only when an engine or rule file
  changes. A record regenerated after an evidence-only commit keeps its key.
