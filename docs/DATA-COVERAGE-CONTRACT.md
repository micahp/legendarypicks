# Data coverage contract

**Status:** adopted 2026-08-02. Read this before adding a league, adding a season, or
building any surface that shows what a player did or did not do.

Companion to `.claude/skills/published-first/SKILL.md` §6 (how to get the publisher's
expected total) and `.claude/skills/honest-data-ui/SKILL.md` §5 (the accent marks
absence). This doc is the part in between: **what our own data is allowed to claim.**

---

## 1. The problem, stated once

A missing row in `player_game_logs` has two possible causes:

1. **The player did not play.** That is information about the player, and it is the most
   valuable thing on the page — it is the whole availability thesis.
2. **We did not ingest it.** That is information about us, and it is worth nothing to a
   user.

**Today the UI cannot tell them apart, and renders the second as the first.**
`PlayerGameLog.tsx` types a week as `played: boolean`. Anything not played draws the
amber absence accent. So an un-ingested week becomes a confident, saturated, on-brand
claim that a healthy player missed a game.

This is not hypothetical. Measured 2026-08-02 against `picks.dev.db`:

- **NFL 2024 has 612 players against 2025's 2,024** — WR/RB/TE/QB and almost nothing
  else, never re-ingested after the all-positions fix.
- **Every NFL 2024 row has a NULL `game_type`.** `routers/nfl_offseason.py` checks that
  the *column exists* and then filters `AND game_type='REG'`. The column exists. The
  values are NULL. The filter matches zero rows, `games_played` comes back 0, and every
  player in the season reads **"missed 17"** in amber.

The column-presence guard is the bug in miniature: **presence of a column was taken as
integrity of its values.** Nothing raised. Nothing logged. It renders.

---

## 2. The rule

> **Absence renders as a claim about the player only where we can prove we looked.
> Everywhere else it renders as a claim about us.**

Three states, never two:

| state | meaning | treatment |
|---|---|---|
| `played` | we have the row | normal, neutral |
| `missed` | the team played, the player did not, **and the season is verified complete** | the amber absence accent |
| `unknown` | we have no row and cannot prove we should have one | quiet neutral, visibly not a zero and visibly not an accent |

`unknown` is **quieter** than `missed`, not louder. Ink goes to the holes because the
holes are information; our own gaps are not information about the player, and dressing
them up as a warning trains users to discount the accent that matters.

The `honest-data-ui` corollary already covers the shape of this: *"Rookies read 'no NFL
sample,' never zero and never a low floor. Zero is a claim about the player. Absence is a
claim about us."* An un-ingested week is the same sentence one row down.

---

## 3. Where the proof lives: `team_stats_coverage`

**It already exists. Do not build a second one.** Per published-first rung 1 — the value
is already a column.

```
team_stats_coverage(
  run_id, league, season, season_start, season_end, status,
  expected_teams, fetched_teams, expected_games, fetched_games,
  paired_games, paired_stat_games, failure_count, completed_at, source
)
```

It was populated once, `2026-07-14`, for `nfl 2025`, `nba 2026`, `nhl 2026`, all
`status='complete'`, then never refreshed. There is no MLB row — which is why
`team_stats_contract.py` special-cases MLB by parsing `substr(game_date,1,4)` instead of
reading the manifest. Nothing in the frontend reads this table at all.

Three changes make it the coverage source of truth:

1. **`reconcile_totals.py` writes it.** The script already computes exactly these
   numbers, and it gets `expected_games` from ESPN in **one** request where the
   2026-07-14 run traversed 32 team schedules to reach the same integer.
2. **Add player-level columns**, because game coverage is not player coverage — NFL 2024
   has 100% of games and 30% of players:
   `expected_players`, `fetched_players`, `null_key_rows` (rows whose `game_type`,
   `team`, or `game_id` is NULL — the integrity check the column-presence guard missed).
3. **`status` becomes load-bearing and gains `partial`.** Any surface reading a season
   reads its row first. **No row is `unknown`, not `complete`** — an unmeasured season is
   never assumed good, per `feedback_presence_is_not_integrity`.

A season is `complete` only when every count equals its published total **and** the
oracle was actually reachable. `NO-ORACLE` writes `status='unverified'`, never
`complete`.

---

## 4. League vocabulary standard

We are adding leagues. Every one of these has already cost us once, and each is the same
failure: **a wrong key does not raise, it misses.**

### 4.1 Season key — ESPN's start year, everywhere

Adopted 2026-08-02. Today one NHL season is **four different integers**:

| holder | 2025-26 NHL season |
|---|---|
| `player_game_logs.season` | `20252026` |
| `team_game_results.season` | `2026` |
| `team_stats_coverage.season` | `2026` |
| ESPN (the oracle) | `2025` |

And `team_game_results.season` is **empty for all 3,305 MLB rows**.

**The canonical internal season key is the year the season started**, matching ESPN and
matching the already-canonical ESPN team codes (`reference_lp_team_code_vocabularies`).
NFL is unaffected — one calendar year, already aligned. NBA/NHL/MLB migrate.

- Normalise **at ingest, once.** Not at each read site. We already carry three copies of
  the `LA → LAR` map and that is two too many.
- The **display layer** maps `2025 → "2025-26"`. Users never see a bare start year for a
  split-year league.
- Reconciliation then compares integers directly, with no translation table to forget.

### 4.2 `game_type` — required, never NULL

Populated for NFL 2025 and nothing else: NULL for NFL 2024 and for every MLB, NBA, NHL,
UFC and WC row. Any query that adds `AND game_type='REG'` silently returns zero for all
of them.

- `game_type` is **NOT NULL** on ingest for every league. Backfill before adding a league
  that needs it.
- Values are the publisher's, normalised at the boundary: `PRE` / `REG` / `POST` /
  `ALLSTAR`. Keep the finer NFL round codes (`WC`/`DIV`/`CON`/`SB`) in `nfl_schedule`
  where they already live; `player_game_logs` carries the coarse four.
- **Never guard on column presence and then filter on value.** If the filter is
  load-bearing, assert the values are populated for the season being queried, and fail
  loud when they are not.

### 4.3 What the oracle counts is not always what we count

ESPN files the Pro Bowl under season type 3, so its postseason count is 14 where the
bracket is 13. Its `athletes/<id>/eventlog` is regular-season only. The first run of
`reconcile_totals.py` reported both as defects and named seven healthy Patriots as short.

**A disagreement with the publisher is a question, not a verdict.** Reconcile the
definitions, then encode the reconciliation in code with the measurement in a comment —
see `published_real_games()`.

---

## 5. UI changes

### 5.1 API — the type change that forces the rest

`GameRow.played: boolean` becomes:

```ts
status: 'played' | 'missed' | 'unknown'
```

A boolean cannot express what we know, and every surface downstream inherits its
dishonesty. Change it at the endpoint; TypeScript then walks us to every consumer.

Every payload that carries availability also carries the season's coverage:

```ts
coverage: {
  status: 'complete' | 'partial' | 'unverified'
  games: { fetched: number; expected: number | null }
  players: { fetched: number; expected: number | null }
  verified_at: string | null
}
```

`expected: null` is explicitly "we never asked," and must not render as a pass.

### 5.2 Surfaces, in order of exposure

| surface | change |
|---|---|
| `Leagues/PlayerGameLog.tsx` | third row state; header line reads coverage, not just `N of M team games` |
| `Leagues/PlayerDetailOverlay.tsx` | availability summary suppressed on a `partial` season rather than shown low |
| `Leagues/NflDraftRoom.tsx`, `MockDraft/PoolList.tsx`, `MockDraft/columns.tsx` | `games_played` / `games_missed` columns read `—` on unverified seasons; **never 0** |
| `pages/stats.tsx`, `Leagues/StatsTab.tsx` | season picker labels an unverified season and does not default to it |
| `Leagues/NflUsageTrend.tsx` | a trend across an un-ingested week must break the line, not interpolate through it |

### 5.3 Rules that survive the specific components

- **Never default to an unverified season.** The picker may offer it; the page may not
  land on it.
- **A rate whose denominator is unverified does not render.** `12 of 17` where the 17 is
  unproven is fake precision with extra steps.
- **State `n` and state the source season** wherever a derived average appears —
  `honest-data-ui` §4.
- **The coverage line is part of the surface, not a tooltip.** Self-evident beats
  self-explanatory.

---

## 6. Adding a league — the checklist

1. Find its ESPN core path (`sport/leagues/<league>`) and confirm `?limit=1` returns
   `count` for events, teams, and athlete eventlog.
2. Add it to `ESPN_PATH` in `backend/reconcile_totals.py` and write its checks.
3. Ingest with the **start-year** season key and a **NOT NULL** `game_type`.
4. Normalise team codes at the boundary to the ESPN vocabulary.
5. Run `reconcile_totals.py` and land a `team_stats_coverage` row. **A league with no
   coverage row renders as `unverified` and is not offered as a default anywhere.**
6. Screenshot the player surface for a player with a missed game *and* for a season we
   have not fully ingested. The two must not look the same.

---

## 7. Open, not decided here

- **The NFL 2024 backfill itself** — the re-ingest that makes 2024 `complete`. Deferred
  deliberately: the UI must be able to say "we don't know" before we go fix a season, or
  we will fix this one and learn nothing that protects the next.
- **NBA's 1,227 vs ESPN's 1,239** for 2025-26. A 12-game gap, unexplained, and exactly
  the kind of difference §4.3 says is a question rather than a defect. Measure before
  filing.
- **MLB's empty `team_game_results.season`** and the special-case it forces in
  `team_stats_contract.py`. Falls out of the §4.1 migration; sequence it there.
