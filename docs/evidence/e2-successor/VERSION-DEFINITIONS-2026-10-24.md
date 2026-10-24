# E2 successor: version definitions (2026-10-24)

Every E2 game record carries two stamps. Both are defined and computed in `scripts/nfl_sequence/versions.py`. This document is
the only place their meaning is written down. The stage labels they replace are listed at the end, and the scoped-out
transitions are listed in `UNMODELLED-TRANSITIONS-300-2026-10-24.md`.

## model_version

- **Meaning:** the commit of the engine that produced the record. It is the most recent commit that changed any file in
  `ENGINE_FILES`: `game_state.py`, `e1_drive.py`, `e2_reference.py`, `e0_single_play.py`.
- **Stamped by:** `versions.stamp()`, which refuses to run while any engine or rule file has uncommitted changes. So the value
  always names code that exists and was run.
- **Value on the seed-1 record:** `dfef3e8e40ab9702c1f021ff726e3959d6f9d63b` (the last engine commit, `dfef3e8e`, which fixes the possession change at a half's
  end: see `e1_drive.py` in that commit).
- **Changes when:** an engine file changes. It does not change for evidence, scripts, tests or documents.

## rules_version

- **Meaning:** the SHA-256 of the canonical JSON (sorted keys, no whitespace) of the map `{path: sha256(file)}` over
  `RULE_FILES`: `game_state.py`, `rules_matrix.py`, `e1_drive.py`, `shared_v1.py`. This is the scoped producer set the
  Gridiron envelope already pins under `source.producer_file_sha256`.
- **Why not the envelope file hash:** the envelope contains the record, so its hash would depend on the value it is meant to
  carry.
- **Value on the seed-1 record:** `5ea4eecd2fa94e24c4efa857c35f2aa20724e37b85e5adb49b69a84de875fb7a`.
- **Changes when:** a file in `RULE_FILES` changes. That includes `shared_v1.py`, the v1 projection, which is in the scope the
  envelope already pins.

## What the two stamps mean for a record

- `complete_regulation` is true only for a game with no unmodelled transition and no block. A guarded game is never a
  complete regulation game.
- `regulation_end_reached` is the simulation fact: the game reached regulation end without a block.
- `complete_game` is true only when the game is unblocked, untied and free of unmodelled transitions.
- `status` is `regulation_end_guarded` for a game that reached regulation end but contains an unmodelled transition.
- `valid_full_game` is false for every record: the mode is not `pregame_full_game`, and the unsupported-rule list is never empty.
- The seed-1 research source SHA-256 is `79a65db640e587798f2a067853a3ba8f723aadfbb10e3021cddb3c92ec08c117`; it pins the exact dirty engine/rule tree used for that record.

## Full-game acceptance contract

The primary LP engineering reference is [`NFL-2026-GAME-STATE-RULES.md` on `dev`](https://github.com/micahp/legendarypicks/blob/dev/docs/rules/NFL-2026-GAME-STATE-RULES.md), pinned by its Git blob and content SHA-256 in `PROVENANCE-2026-10-24.json`. It is an implementation contract; the official NFL rulebook remains authoritative.

`valid_full_game=true` requires all of the following, not merely a zero Q4 clock:

- a `pregame_full_game` payload with stable game identity, scheduled kickoff and as-of time, team identities, and eligible roster snapshot;
- normal-mode coin-toss choices and a verified ledger for exactly two half-start kickoffs, one in Q1 and one in Q3, with different kicking teams;
- complete legal possession, down/distance, scoring, try, restart, special-teams, clock, timeout, penalty and period transitions, including explicit clock running/stopped and restart state;
- no tie, blocker, unsupported rule, or unresolved shared-v1 contract residual; independent checks must validate the chronology and terminal state.

The successor engine enforces the normal-mode half-start kickoff invariant. Its 300-seed records are retrospective `legal_game_state_first_piece` research samples, not pregame full-game payloads. They include a checked two-minute-warning crossing marker at the actual post-down clock, but do not model clock running/stopped state or explicit restart transitions; `clock_start_stop` remains guarded. These records therefore cannot set `valid_full_game=true`, even when they pass the model-scoped checks.

## Which commit the survey ran at

The survey and the enumeration were run at the engine commit in the record's `model_version`, `dfef3e8e`. The survey document
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
