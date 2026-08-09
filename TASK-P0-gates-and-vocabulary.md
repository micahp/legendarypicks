# TASK P0 — make the gates run, and get fantasy slots out of `players.position`

**Phase:** P0 · **Effort:** days · **No schema changes, no table moves.**
**Why now:** NFL drafts are 3–5 weeks out. Everything here protects that window or
closes a gate that is currently green over broken data. Nothing here is the refactor.

Work in `/root/legendarypicks`, absolute DB paths, never a worktree. Back up with
`VACUUM INTO`, **not** `cp` — a plain copy of a live database races writers and produces a
torn snapshot (proved 2026-08-05: the copy reported `database disk image is malformed`
while the source passed `integrity_check`).

---

## 1. Wire the gates into the release preflight

`scripts/release.sh` runs `diff_databases.py` **advisory** (`|| true`), and does not run
`audit_league_stats.py` at all. A gate that only runs when someone remembers is a gate in
name only — that is how seven dev-only fixes reached three releases.

* **`diff_databases.py`: SCHEMA and SEASONS findings become blocking.** A table, column or
  season present on one database and absent from the other is never "dev is deliberately
  ahead" — it is always a promotion that did not happen. **VOLUME stays advisory**: live
  odds (`prop_odds_snapshots` prod 409,617 vs dev 3,526) and dev-only mock drafts are
  legitimate drift. Split the severities inside the tool; do not make the whole thing
  blocking or people will learn to skip it.
* **Add `audit_league_stats.py` for nfl/mlb/nba/nhl to the preflight**, blocking on `FAIL`
  only. **Not on `UNVERIFIED`** — NFL trips that today for accepted reasons (nickname vs
  legal-name variants) and blocking on it would just get the check disabled.

## 2. Fix the two checks that pass over broken data

* **Check D (`leaders-reach-logs`) has no season predicate.** `audit_league_stats.py:528`
  reads `WHERE g.player_id = s.player_id AND g.league = s.league` — a log from three
  seasons ago counts as "reachable" today. Add `AND g.season = s.season`. One line. This
  read PASS for NHL twice on 2026-08-05 while a season-scoped join returned **0**.
* **Check B (`position-content`) measures presence, not coverage.** It samples `LIMIT 500`
  and passes if a key appears **at all**, so one row in 500 is a pass — it read PASS at
  **30%** coverage. Rewrite it to report `filled / sampled` against a declared threshold,
  the same shape check A already uses (`check_required_stats`). Copy that pattern; do not
  invent a second one.

## 3. MANIFEST entries for the invisible leagues

`ufc` (47 players) and `wc` (63) are in the database and **no check in
`audit_league_stats.py` can see them** — no MANIFEST entry means no checks run at all.
Write the entries. Unmeasured is worse than measured-and-failing. If a league genuinely
has nothing to declare, say so in the entry rather than omitting it.

## 4. A gate for the thing that actually broke

On 2026-08-04 the production draft pool served **4,508 players with `injury_status` set on
0 of them** for ~18 hours. The API returned the keys, always null — no error, no empty
state. Add a check that fails when the NFL pool's `injury_status` / `last_news_date`
population falls below a floor. Reference: dev and prod both carry ~2,617 / ~1,994 today.

## 5. Get fantasy slots out of `players.position`

`C/vocabulary[position]` for NFL currently fails with:

```
CB under DEF, DE under DEF, DT under DEF, LB under DEF, S under DEF, FB under RB
```

Five of those six are `DEF` sitting in the same column as real defensive positions. A team
defence plays no position; `DEF` is a fantasy slot.

**Where it goes — nowhere new. It is already stored.** `nfl_adp` holds ESPN's fantasy
position label per player per season (`DEF` 32, `TQB` 32, `HC` 32) alongside adp and PPR
rank. That table is already the fantasy table in all but name.

```
players.position     ->  NULL            "a team defence plays no position" is true
players.entity_type  ->  team_defense    already present and backfilled (840d2e7)
nfl_adp.position     ->  'DEF'           unchanged, already correct
```

Apply the same to `TQB` and `HC`. Nothing is lost, and check C loses five of six
complaints — leaving the genuine `FB under RB`.

**Do NOT delete the rows.** They are real draftable entities with ids, names and teams.

## 6. One spelling per position

`K` (339 rows) and `PK` are the same position from two writers; so are `S` and `SAF` (146).
A draft board filtering `position='K'` misses every kicker the ADP ingest wrote as `PK`,
silently. Pick the published spelling — `_ESPN_POSITION` in `ingest_nfl_adp.py:57` says
`5: "PK"` and `13: "S"` — normalise at the ingest boundary, and migrate existing rows in
the same change. **Migrate the league entire or not at all**: a half-migration leaves both
spellings live, which is the current state and worse than either alone.

---

## Frontend — required, do not skip

Two surfaces key on the position string directly:

* **`components/Leagues/hooks/useNflDraftBoard.ts:10`** —
  `const POSITIONS = ['all','QB','RB','WR','TE','FLEX','PK','DEF']`
* **`components/MockDraft/roster.ts:80`** — `addSlot('D/ST', 'DEF', true)`

**The API contract must not change.** The draft-pool response should keep serving
`position: 'DEF'` for team defences, composed from `nfl_adp` rather than read from
`players.position`. If that holds, **no frontend change is needed for item 5** — verify it
by diffing the `/api/nfl/mock-draft/pool` payload before and after; the `position` values
must be byte-identical.

For item 6, the board already expects `PK`, so normalising `K → PK` moves the data toward
what the frontend already assumes. Confirm no component filters on `'K'`.

## Done means

* `release.sh --dry-run` shows both gates running, and blocks on a seeded schema difference
* checks D and B fail on data they previously passed (prove it, don't assert it)
* `C/vocabulary[position]` for NFL reports only `FB under RB`
* `/api/nfl/mock-draft/pool` payload unchanged — same count, same `position` values
* full `pytest` green, prod and dev both migrated in the same session, `diff_databases.py`
  shows no new SCHEMA or SEASONS rows
