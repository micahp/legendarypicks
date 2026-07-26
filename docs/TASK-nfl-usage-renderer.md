# TASK: NFL usage trend renderer (`UsageTrend`) + `/api/nfl/usage/{player_id}` endpoint

**Owner:** Hermes (worktree)
**Manager:** Codex — reviews the diff against the acceptance criteria below before anything is
reported as done.
**Author:** Claude, 2026-07-25
**Base branch:** `dev` at `2980b33`

---

## Why this exists

`player_game_logs` holds 130k+ rows and is wired as a **computation input only** — it feeds prop
probabilities (`backend/routers/props.py:133`), projections, and game extras, and comes out the
other side as a single number. The raw per-game trend is visible in exactly one place
(`components/Props/PropChart.tsx`), and only when you arrive through a prop that has a market and a
line attached.

Meanwhile `GET /api/players/{player_id}` already returns the last 25 game logs with full stat blobs
(`backend/routers/players.py:96-101`) and **no frontend file consumes it** — grepping `components/`
and `app/` for `game_log|gameLog|game_no` returns zero hits.

So: the data exists, the queries are proven, the endpoint pattern exists. What is missing is a
renderer. This task builds it.

Two new usage inputs landed in commits `4e37340` and `2980b33` and are already backfilled in
`backend/data/picks.dev.db` for 2024 and 2025:

| Key in `stats` JSON | Meaning | Rows (2024 / 2025) |
|---|---|---|
| `off_snaps`, `off_pct` | offensive snaps + snap share (share is pre-computed by nflverse) | 5329 / 5360 |
| `def_snaps`, `def_pct`, `st_snaps`, `st_pct` | defense / special teams | same |
| `air_yds_share` | share of team intended air yards (0–100) | 1253 / 1213 |
| `adot` | average intended air yards | same |
| `separation`, `cushion`, `yac_above_exp` | NGS coverage/YAC context | same |

`targets` was already present for both seasons.

---

## Scope — the ONLY files you may create or modify

**Create:**
1. `backend/routers/nfl_usage.py`
2. `components/Leagues/NflUsageTrend.tsx`
3. `components/Leagues/hooks/useNflUsage.ts`
4. `backend/test_nfl_usage.py`

**Modify (registration only, one line each):**
5. `backend/main.py` — register the new router, following the existing `include_router` pattern
   exactly.
6. `components/Leagues/types.ts` — add the response types. **Append only.** Do not edit or
   reorder existing types.

**Explicitly FORBIDDEN — touching any of these fails review:**
- `backend/_core.py`, `backend/routers/props.py`, `backend/routers/players.py`,
  `backend/analytics/projections.py`, or any existing ingest script
- `components/Props/*` (including `PropChart.tsx`)
- Any migration, `ALTER TABLE`, `CREATE TABLE`, `UPDATE`, `INSERT`, or `DELETE`. **This task is
  read-only against the database.**
- `package.json`, `requirements.txt`, lockfiles — **no new dependencies at all**
- Host-level config: `/etc`, systemd, cron, nginx, shell profiles
- Anything under `.claude/`, `docs/`, or `AGENTS.md`
- Git tags, GitHub Releases, `CHANGELOG.md`, version bumps in `package.json`

---

## Part 1 — `GET /api/nfl/usage/{player_id}`

### Query params
- `season` (int, optional) — defaults to the player's most recent season present in
  `player_game_logs`.
- `weeks` (int, optional, default 8, max 18) — how many most-recent games to return.

### Response shape

```json
{
  "player_id": 1234,
  "name": "Chris Olave",
  "team": "NO",
  "position": "WR",
  "season": 2025,
  "games": [
    {
      "week": 1, "opponent": "ARI", "snaps": 64, "snap_share": 0.85,
      "targets": 6, "target_share": 0.24, "air_yds_share": 34.93, "adot": 7.84,
      "wopr": 0.605, "rec": 4, "rec_yds": 54, "rec_td": 0, "fpts_ppr": 9.4
    }
  ],
  "averages": { "snap_share": 0.83, "target_share": 0.22, "wopr": 0.58 },
  "trend": { "snap_share": "up", "target_share": "flat", "wopr": "up" }
}
```

### Computation rules — follow these exactly

**Target share.** Not stored. Derive it: for each `(season, game_no, team)`, sum `targets` across
all rows for that team in that game, then divide the player's targets by that sum. Use a window
function partitioned by `(game_id, team)` when `game_id` is present, otherwise
`(season, game_no, team)` — 2024 rows have **no `game_id`**, only `game_no`. Verified working:

```sql
ROUND(100.0 * t.tg / SUM(t.tg) OVER (PARTITION BY t.game_id, t.team), 1)
```

**WOPR.** `1.5 * target_share + 0.7 * (air_yds_share / 100.0)`. Note `target_share` is a 0–1
fraction here while `air_yds_share` is stored 0–100 — the `/100.0` is required. Return `null` when
`air_yds_share` is absent (non-receivers, and RB/QB rows generally).

**Two stat vocabularies.** 2024 (`source='nflverse'`) uses `receiving_yards`, `rushing_yards`,
`passing_yards`, `receptions`, `rushing_tds`, `receiving_tds`, `fantasy_points_ppr`. 2025
(`source='nflverse_pbp'`) uses `rec_yds`, `rush_yds`, `pass_yds`, `rec`, `rush_td`, `rec_td`,
`fpts_ppr`. **Every** yardage/reception/TD/fantasy read must `COALESCE` both spellings or 2024 will
silently return nulls. `targets` is identically named in both — do not COALESCE it.

**Trend.** Compare the mean of the most recent 3 games to the mean of the prior 3. `"up"` if the
recent mean exceeds the prior by more than 10% relative, `"down"` if below by more than 10%,
otherwise `"flat"`. Return `null` when fewer than 4 games are available.

**Nulls.** A missing stat key is `null`, never `0`. `off_snaps` is absent for ~0.3% of logs and
`air_yds_share` for all non-receivers; both must render as "—", not as zero.

### Errors
- Unknown `player_id` → 404 `{"detail": "Player not found"}`
- Player exists but `league != 'nfl'` → 400 `{"detail": "NFL only"}`
- Player is NFL but has no game logs → **200** with `games: []`, `averages` all `null`. Not an error.

---

## Part 2 — `NflUsageTrend.tsx`

A read-only presentational component. Props: `{ playerId: number; season?: number }`. Data fetched
through `useNflUsage.ts`, which must follow the existing fetch/loading/error conventions in
`components/Leagues/hooks/useNflDraftBoard.ts` — same shape, same error handling. Do not invent a
new data-fetching pattern.

Renders:
1. A header line: name · position · team · season.
2. A per-game table, most recent first: Week, Opp, Snaps, Snap%, Tgt, Tgt%, aDOT, AY%, WOPR, PPR.
3. A trend row: the three averages with an up/down/flat indicator each.
4. A sparkline-style bar per metric is acceptable **only** if drawn with plain CSS (flex + heights)
   or inline SVG. **No charting library.**

Requirements:
- Loading skeleton and an explicit empty state ("No usage data for this season").
- Nulls render as `—`.
- Must not scroll the page body horizontally — the table goes in its own `overflow-x: auto`
  container. See `docs/DEV-STANDARDS.md`.
- Payload discipline: the endpoint must not return more games than the component renders. Default
  8 games, not the full season. This is a standing rule in `docs/DEV-STANDARDS.md`.

---

## Part 3 — `backend/test_nfl_usage.py`

Follow the existing style in `backend/test_league_stats_contract.py`. Required cases:

1. **Target share sums to ~1.0** within a single `(season, game_no, team)` — assert within 0.001.
2. **2024 vocabulary resolves.** Fetch a 2024 receiver and assert `rec_yds` is non-null in the
   response, proving the COALESCE works. A test that only covers 2025 does not satisfy this.
3. **WOPR matches the formula** for one hand-computed row.
4. **Null preservation** — a row lacking `air_yds_share` returns `null`, not `0`, and `wopr` is
   `null`.
5. **Empty case** — an NFL player with no logs returns 200 and `games: []`.
6. **Non-NFL player** returns 400.
7. **`weeks` cap** — requesting `weeks=99` returns at most 18.

---

## Acceptance criteria — Codex verifies every one of these

- [ ] `cd backend && python3 -m pytest test_nfl_usage.py -q` passes, all 7 cases.
- [ ] `npx tsc --noEmit` is clean.
- [ ] `git diff --stat` touches **only** the 6 files listed in Scope. Any 7th file = reject.
- [ ] `git diff` contains no `INSERT`, `UPDATE`, `DELETE`, `ALTER`, or `CREATE TABLE`.
- [ ] `git diff package.json requirements.txt` is empty.
- [ ] Endpoint verified against a real player with `curl` on the **dev** backend and the JSON
      matches the documented shape. Use `LP_DB_PATH=data/picks.dev.db`.
- [ ] A 2024 response is checked by hand to confirm yardage fields are populated (the vocabulary
      trap).
- [ ] Target share for one real team-game is checked by hand against the SQL in this spec.

## Hard operational rules

- **Do not start, stop, or restart any server.** Ports `:3096`, `:8096` and the cloudflared tunnel
  are externally managed and are in active use. Do not run `hermes-worktree.sh down`.
- **Do not run parallel dev servers.** The box is 5.8GB, currently at ~2.2GB swap with 31 live
  trading processes running. A second Next dev server has OOM'd this machine before. Test the
  backend with pytest and a short-lived uvicorn on a **free high port** if you need one, and kill it
  when done — then verify with `ps` that it actually died.
- **Read `.claude/skills/resource-check/SKILL.md` before running anything batch-like.**
- Write against `backend/data/picks.dev.db` only, and read-only.
- No commits to `dev`. Work in the worktree branch; Codex reviews the diff, then reports back.
- No tags, no releases, no version bumps, no CHANGELOG edits. Not even if it seems appropriate.

## Out of scope — do not build these

Stat-card image rendering, social share output, rarity/"first since" queries, prop integration,
other leagues, snap-count ingestion changes, playoff odds, game previews. This task is the usage
trend surface and nothing else.
