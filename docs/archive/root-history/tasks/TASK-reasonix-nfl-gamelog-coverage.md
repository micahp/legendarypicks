# TASK — the player page renders the wrong game-log columns for K and D/ST

Branch `dev`, worktree `/root/legendarypicks`. Dev only: frontend `:3096`, backend
`:8096`. **Prod is under an active stand-down** — no prod DB writes, no
`docker compose` anything, no container restarts, no touching `backend/data/picks.db`.

## The defect

Not a data gap. The data is present and correct; the page renders the wrong columns.
Measured on dev 2026-08-03 on `/player/{id}`, Game Log tab:

| | returning | displaying |
|---|---|---|
| **Aubrey (882, PK)** | 17 games, 45 stat keys incl. `fg_made 4, fg_att 6, fg_long 41, pat 2/2` | 17 rows of `WK OPP CAR YDS TD FPTS PPR` — **rushing**. 16 rows read `—\|—\|—\|0.0\|0.0`; **one** has data (wk 15, 1 carry, 6 yds) |
| **Borregales (2217, PK)** | 17 games | **no table at all** |
| **NO D/ST (30116, DEF)** | `recent_games: []` | **no Game Log section at all** |

The one populated row is why this was reported as "Aubrey has 2 games".

## Root cause

`pages/player/[id].tsx:191` — `NFL_GAMELOG_BANDS` hardcodes **four** bands: Passing,
Rushing, Receiving, Fantasy. **No Kicking. No Defense.** Line 245 keeps only bands with
a non-zero value, then `if (!bands.length) return null`.

- Aubrey: his single carry is the only non-zero value in those four bands → renders a
  kicker's rushing log.
- Borregales: zero carries all season → no band matches → `return null` → blank.
- D/ST: `player_game_logs` has **zero DEF rows for any season**, and `line 594`'s
  `p.recent_games.length > 0` skips the whole section before bands even matter.

## Constraint you must not break

`pages/player/[id].tsx:604/614/625` renders **three separate phase tables** — Postseason,
Regular Season, Preseason — from `postseason_recent_games`, `recent_games` and
`preseason_recent_games`, each with its own `scheduleGames` fill.

**Do NOT replace this with `components/Leagues/PlayerGameLog.tsx`.** That component
fetches `/api/nfl/draft/player/{id}/game-log`, which serves the reference **regular**
season only — swapping it in would silently delete the postseason and preseason logs.
Keep the three-phase structure.

## What to do

**1. Backend — publish the position's fields, and give D/ST its rows.**
`backend/routers/nfl_mock_draft.py` already has both pieces working; verified live:

```
882   PK  tabs=[Kicking]  fields=[fg_made,fg_att,fg_long,pat_made,pat_att]  17 played
30116 DEF tabs=[Defense]  fields=[sacks,interceptions,fumble_rec,safeties,points_allowed]
```

- `/api/player/{id}` must populate `recent_games` for **DEF** from `nfl_dst_stats`,
  reusing the same query the draft endpoint uses — do not write a second one.
  `nfl_mock_draft.py:1374` already explains why: *"D/ST have no player_game_logs rows at
  all — their week rows live in nfl_dst_stats. Read that table rather than reporting 17
  weeks of absence for a defense that played every one of them."*
- `/api/player/{id}` must also publish the position's `tabs`/`fields` (same shape as the
  draft contract) so the page stops guessing.
- **`_LOG_FIELDS["K"] = _LOG_FIELDS["PK"]`**, next to the existing
  `_LOG_FIELDS["TE"] = _LOG_FIELDS["WR"]`. `K` is a live legacy label: `players` holds
  **336 `K`** vs **87 `PK`**, and 10 `K`-labelled players have 2025 logs — Daniel Carlson
  (3636, 17 games), Matt Prater (17), Brandon McManus (15). Today the endpoint returns
  `tabs: []`, `fields: []`, `stats: {}` for all of them. Do **not** normalise
  `players.position` — that is a separate migration and is out of scope.

**2. Frontend — drive the columns from the published fields, not a second list.**
`NFL_GAMELOG_BANDS` becomes the fallback for a payload that does not carry fields, not
the source of truth. Apply the published fields to **all three** phase tables. Deleting
the hardcoded list outright is better than adding a fifth and sixth band to it — the
reasoning in `components/MockDraft/columns.tsx` about two surfaces owning one cell is
exactly this situation.

Keep the non-NFL fallback log untouched.

**3. Do NOT fix kicker fantasy points in this task.** Aubrey's wk-15 row shows
`fpts 0.6 / fpts_ppr 0.6` for a game with 4 FG + 2 PAT (~16 kicking points) — the scoring
counts his one carry and ignores every kick, while `pk_pts_per_game` (10.6) is right.
Real defect, different blast radius, its own pass. Leave it and report it.

## Gate first, then the code — two commits

`REG-render` drives the mock-draft overlay, **not** `/player/[id]`, which is why this
survived a green suite. Add a browser gate over the player page that asserts, per
position, that the log shows **that position's own stats**:

- QB → Passing band; RB/WR/TE → Rushing/Receiving
- **PK → a Kicking band containing `fg_made` and `fg_att`**
- **DEF → a Defense band containing `sacks`**
- **Row count > 0 AND at least one row with a non-empty stat cell.** A row-count-only
  assertion passes both of today's failures — Borregales rendered nothing and Aubrey
  rendered 17 rows of dashes.
- All three phase headings still render where the player has those games.

Fixtures: `469` QB, `9772` RB, `5818` WR, `9819` TE, `882` + `2217` PK, `3636` K,
`30116` DEF. Commit the gate red, then the fix.

## Files you may touch — and only these

- `pages/player/[id].tsx`
- `backend/routers/nfl_mock_draft.py`
- `scripts/` — the new gate script
- `verify-gates.sh` — **append** a new gate; do not edit any existing one
- `components/Leagues/NflGameLog.test.tsx` (it imports `NflGameLog` from the page)

**Forbidden:** `components/Leagues/PlayerGameLog.tsx`, `components/MockDraft/**`,
`backend/data/**`, any ingest/migration/backfill script, `docker-compose.yml`,
`package.json`, `CHANGELOG.md`, git tags, and all host config (`/etc`, systemd, cron,
nginx). No prod anything. No release.

## Definition of done

1. New gate **red before, green after** — paste both runs.
2. `npx tsc --noEmit -p tsconfig.json` — no new errors in touched files (12 project-wide
   errors are standing: `@onflow/fcl` missing + TS2802 in `pages/scores.tsx`).
3. `npx jest components/Leagues` green.
4. Real browser, numbers not adjectives: `/player/882` Kicking columns, 17 rows, wk 1
   reads `fg_made 2, fg_att 2, fg_long 53`. `/player/2217` renders a table at all.
   `/player/30116` Game Log section exists, 17 rows, wk 1 `sacks 5`. `/player/3636`
   Kicking columns. `/player/469` **unchanged** — this must not regress the positions
   that already work.
5. `bash verify-gates.sh all` — no regression against the 23/2 baseline.
6. Two commits (gate, then fix). **Do not push, do not tag.**

Report measured values. "Looks right" is not a result.
