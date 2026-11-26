# TASK P3 — nickname aliases: keep market names, make the gate honest, log every consolidation

**Phase:** P3 · **Effort:** hours · **Written:** 2026-08-05
**Decision recorded (Micah, 2026-08-05):** nicknames win. ESPN fantasy and Yahoo fantasy
both publish "Kenny Gainwell" — the nickname is the market-facing canonical form. Our rows
are right; the G/published-identity gate is the thing that needs to learn aliases, not the
data. No renames, no data migration, frontend untouched.

Work in `/root/legendarypicks`, absolute DB paths, never a worktree. Back up with
`VACUUM INTO`, never `cp`.

## Why

`G/published-identity` fails on 16 rows across three leagues, all the same human under a
different published name form:

- nba 1: id=29356 'Nate Williams' nba_id=4397821 publishes as 'Jeenathan Williams' (same
  person; ESPN spells the nickname, hoopR spells the legal name — verified 2026-08-05)
- nfl 4: 'Jalen Cropper' -> 'Jalen Moreno-Cropper'; 'Kenneth Gainwell' -> 'Kenny
  Gainwell'; 'Zach Tom' -> 'Zach Bako-Bewele'; 'JT Tuimoloau' -> 'Jaylahn Tuimolaou'
- nhl 11: 'Josh Dunne' -> 'Joshua Dunne'; 'Joe Veleno' -> 'Joseph Veleno'; 'Tommy Novak'
  -> 'Thomas Novak'; plus Max/Maxim Shabanov, Maxim/Maksim Tsyplakov, A.J./Anthony-John
  Greer, Jake/Jacob Middleton, Jeffrey/Jeffrey Truchon-Viel, Frederick/Freddy Gaudreau,
  Joshua/Josh Mahura, Jamie/Jamieson Oleksiak

The audit comparison (`_identity_name_key`) folds diacritics, case, punctuation,
generational suffixes and bare middle initials — decoration. It must NOT learn to fold a
different person. The fix is an explicit alias map: "id X is allowed to appear as name A
or name B", decided per-id by a human, reviewed in diff.

The gate stays strict about *people* (it will never tolerate a wrong id — the 224 MLB
corruption class). It just learns that a row named Kenneth with nfl_gsis_id 00-0036919 is
the same person the publisher calls Kenny.

## The consolidation artifact

Every dedupe/merge path appends one JSONL line to `backend/data/identity-consolidations.jsonl`:

```json
{"ts": "2026-08-05T22:10:00Z", "script": "merge_nba_identities.py", "db": "picks.db",
 "direction": "loser->winner", "from": [{"id": 29355, "name": "Jeenathan Williams"}],
 "to": {"id": 29356, "name": "Nate Williams"},
 "moved": {"player_stats": 0}, "note": "269 split pairs -> 0"}
```

- append-only, never rewritten; a `cat` tells the whole consolidation history
- wired into: `scripts/merge_nba_identities.py`, `dedupe_mlb.py`,
  `apply_mlb_identity_repairs_copy.py`, and `fetch_identity_names.py` when it renames
- future ingest-time dedupes use the same helper
- `identity-consolidations.jsonl` is a reviewable artifact like
  `published-identity-names.json`: it lives in `backend/data/`, tracked in git, and a
  consolidation without a log line is a defect

## Pieces

1. **CREATE `backend/name_aliases.py`** — the helper module:
   - `load_aliases()` — read `backend/data/name-aliases.json` once
   - `matches_published(id_value, league, row_name)` — does the row name match the
     publisher's name OR any recorded alias for that id?
   - `record_consolidation(entry: dict)` — append one JSONL line to
     `backend/data/identity-consolidations.jsonl` (mkdir/append, never truncate)
2. **CREATE `backend/data/name-aliases.json`** — checked-in, one entry per id, the 16
   rows above with their accepted alternate spellings (normalized to
   `_identity_name_key` form so the gate compares apples to apples)
3. **MODIFY `backend/audit_league_stats.py`** — `check_published_identity`: before
   reporting FAIL, consult `name_aliases.matches_published(ext, league, name)`. PASS when
   the name matches the publisher's or any alias. Keep UNVERIFIED semantics unchanged.
4. **MODIFY the three consolidation paths** to call `record_consolidation`:
   - `scripts/merge_nba_identities.py` — after apply, log the run
   - `dedupe_mlb.py` — after repoint, log dup groups consolidated
   - `scripts/apply_mlb_identity_repairs_copy.py` — after repair, log
   - `fetch_identity_names.py` — when it renames a row, log the old->new
5. **CREATE `backend/test_name_aliases.py`** + gate tests:
   - alias file loads; matches_published true for alias, false for different person
   - record_consolidation appends (never truncates); file has a line for the new event
   - audit: G passes for the 16 known rows against prod and dev; G still FAILS for a
     fabricated wrong-person id (strictness preserved)

## Done means

- `backend/venv/bin/python audit_league_stats.py --db data/picks.db --league nfl --league
  nba --league nhl` reports `G/published-identity` PASS on all three (and MLB still PASS)
- `data/name-aliases.json` reviewed in diff; every entry traceable to a real row
- `data/identity-consolidations.jsonl` exists and shows an entry for the NBA merge that
  already ran (back-filled from the 2026-08-05 apply), plus one for each subsequent run
- full `pytest` green
- no `players` row changed by this task; no schema change; `diff_databases.py` clean

## Out of scope

- Renaming any `players` row (decision: keep nicknames)
- P2 source separation (separate task, its own doc says it does nothing for identity)
- C/vocabulary position_group for NFL/NBA (separate task)
- Deleting anything; docker; host config; `git push`

## Report back between `===RESULT===` and `===END===`

What you ran, what changed, gate lines verbatim, `git status --short`, `git log --oneline -5`.
