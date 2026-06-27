# PLAN — Entity-page UX restructure (v0.3.0 roadmap)

Large, multi-session undertaking. Source of truth for the work + delegation. Check off
todos as they land; keep this doc current (handoff across sessions/agents).
**v0.2.0 is cut** (per-game logs + projections + Model tab + tennis). This plan = the **v0.3.0** line.

## The vision
Top-level **tabs: Scoreboard · Leagues · Props** + global search. The richness is **entity
pages** (Player / Game / Team) as the depth behind those tabs, plus a real **prop visualization**.

**Top nav:**
- **Scoreboard** (`/scores`, kept) — today's games → Game pages. Landing page routes here.
- **Leagues** (upgrade of the Stats tab → renamed) — per-league standings/strength + team stats
  + leaders + schedule. Drills into Team + Player pages. *(Stats only ever showed league data,
  so it becomes the Leagues tab.)*
- **Props** — the slate/board **+ the prop visualization** (see below). Drills into Game/Player.

**Destinations (via search + clicking names, NOT tabs):**
| Page | What it is | Reached from |
|---|---|---|
| **Game** `/game/[lg]/[id]` | Matchup + today's projections / props / edges (game-contextual projections live here). | Scoreboard, Props |
| **Player** `/player/[id]` | Asset/profile: stats, game logs, form trajectory, projection trend, prop charts, "next game" card. | Search, any player name |
| **Team** `/team/[lg]/[id]` | Roster, schedule, team stats → players. | Leagues, Game |

## ⭐ The prop visualization (headline upgrade — addresses the #1 gap)
Today the prop display is **retrospective** — a ✅/❌ *after* the game. Useless for deciding a bet.
The industry standard (props.cash, PrizePicks, Underdog) is a **bar chart of the player's last N
games for that stat with the line drawn across it**, so hit rate reads at a glance:

```
Tatum — Points     Line 27.5      L10: 7/10 over     Proj 29.4
  ▆     ▇        ▅
  ▆  ▆  ▇  ▆  ▆  ▅  ▇  ▆  ▇  ▆
──┼──┼──┼──┼──┼──┼──┼──┼──┼──┼── 27.5
  31 24 33 28 26 22 35 29 30 27   (bars over line = hit, color-coded)
```

We **already have the data**: `player_game_logs` (per-game values) + the prop line (`props`) +
the projection (`/api/projections`). This is the payoff of the per-game-log foundation — it makes
the prop *decision-useful*. Filters: L5/L10/L20, home/away, vs-opponent. Used in **Props, Player
page, and Game detail**.

## The Analytics tab → folded (not a user-facing tab)
EV / CLV / Brier are sharp-bettor / model-quality metrics — and 2 of 3 are non-functional
(**EV all zeros** w/o a real model edge; **CLV empty** w/o closing-odds capture). Calibration works
but "Brier 0.21" means nothing to a user. **Remove the Analytics tab.** Calibration becomes a quiet
"model accuracy / track record" credibility element; EV/CLV return only once there's a model + odds
feed (Phase 6). The genuinely useful analytic is the **prop visualization above**, in the prop.

### Persona → door
- **Prop bettor** (props.cash) → Scoreboard → Game / Props (prop charts + edges)
- **Casual fan** (ESPN) → Scoreboard / Leagues (what's on, standings)
- **Fantasy** → Player projections + Game (start/sit)
- **Trader** (sport.fun, later) → Player page as asset (trajectory/value)

## Already built (foundation — reuse, don't rebuild)
- `player_game_logs` (111k logs, 4 leagues) + per-game ingests + `roster_sync` + NFL dedupe.
- `/api/projections/player/{id}` — recency-weighted EV + floor/median/ceiling + P(over) + fantasy pts.
- `/api/player/{id}/stats` (advanced metrics, all leagues — `now` bug fixed).
- `espn_client`: `games`, `team_strength`, `boxscore`, `roster`, `game_result`.
- `/api/{lg}/games`, `/strength`, `/team-stats`, `/api/props*`, `/api/players/search`.
- Routes today: `/scores`, `/stats`(→Leagues), `/props`, `/predict`, `/analytics`(→remove), `/game/[league]/[gameId]`.
- See `CONTEXT-2026-06-26.md` + `PROJECTIONS-METHODOLOGY.md`.

---

## Phases & todos
Delegation-ready: scope + files + acceptance. Verify every "done" on the live tunnel
(data flowing ≠ it looks right — the tennis lesson).

### Phase 0 — Scaffold + global search
- [ ] Routes skeleton: `/league/[league]`, `/player/[id]`, `/team/[league]/[id]` (keep old tabs live until parity).
- [ ] Header global search (wraps `/api/players/search`) → player page.
- [ ] Per-page data contracts (short doc).

### Phase 1 — ⭐ Prop visualization (headline; data ready, highest value)
- [ ] **Backend** `/api/props/history?player=&market=&line=` (or `/api/props/{id}/history`):
      last N game values for the stat (from `player_game_logs`) + per-game hit/miss vs line +
      L5/L10/L20 hit rates + projection. Filters: window, home/away, opponent.
- [ ] **Frontend** `<PropChart>` bar-chart component (bars = games, horizontal line = prop line,
      color over/under, hit-rate + projection labels). Replace the retrospective ✅/❌ in Props·Lines.
- [ ] Reuse `<PropChart>` on Player page + Game detail.
- [ ] Acceptance: open a prop → see last-10 bars vs the line + hit rate + projection. Tunnel-verified.

> ⚠️ **v1 is a FIRST DRAFT — not done.** Backend endpoint + a working bar chart + MLB dedup
> (batter coverage 53%→90%) shipped and verified. **Remaining before this is "done":**
> - **Design polish** — the chart is functional, not finished; treat like the tennis-card pass.
> - **Filters** — L5/L10/L20 toggle exists; add **home/away** and **vs-opponent** (props.cash has these).
> - **Opponent data** — MLB logs store `opponent=NULL`; backfill it (for vs-opp + hover labels).
> - **Non-chartable UX** — markets with no logs show a bare "no data"; show a clear "chart not
>   available for this market" / hide the expand instead of looking broken.
> - **Data gaps** — pitcher props + composite markets (total_hits_runs_rbis) not chartable yet
>   (needs pitcher logs — `TASK-mlb-pitcher-logs.md`); ~10% batters unresolved (mlbam crosswalk).
> - **Reuse** — only in Props·Lines so far; not yet on Player page / Game detail.
> - **Projection marker** — show the projection on the chart, not just the line.

### Phase 2 — Player page (asset/profile hub)
- [ ] **Backend** `/api/player/{id}` aggregate (stats + recent logs + projections + props-on-player +
      next-game ref) OR compose from existing endpoints.
- [ ] **Frontend `/player/[id]`:** header, projection trend, game-log table, advanced metrics,
      **prop charts** for their active props, **"next game" card → /game/...**. Subsumes Performance/Matchups/Model.
- [ ] Wire search + every player name → player page.
- [ ] Acceptance: search any player → real logs + projections + prop charts; next-game links to a real game.

### Phase 3 — Game page + enhance scoreboard (daily loop)
- [ ] **Backend** `/api/projections/game/{lg}/{id}` — projections for both rosters in the matchup.
- [ ] **Frontend Game page** (`/game/[league]/[id]` exists — extend): matchup + per-player
      **projections vs lines + prop charts + edges** + props for the game. Today's projections live here.
- [ ] **Keep & enhance `/scores`** as the slate — each game links into the Game page. Landing still routes here.
- [ ] Acceptance: scoreboard → tap a game → per-player projections + prop charts (where MLB props exist).

### Phase 4 — Leagues tab (rename/upgrade Stats) + Team page
- [ ] **Backend** league leaders endpoint (top players by stat, from `player_game_logs`).
- [ ] **Frontend Leagues tab** (rename Stats → Leagues): standings/strength + team stats + leaders +
      schedule, per league. World Cup stays as a league here.
- [ ] **Frontend `/team/[league]/[id]`:** roster (→ players) + schedule + team stats.
- [ ] Acceptance: Leagues tab = old Stats + leaders/schedule, no regression; team page lists current roster.

### Phase 5 — Nav cleanup
- [ ] Top nav = **Scoreboard · Leagues · Props** + global search (+ Predict if kept).
- [ ] **Remove the Analytics tab** (calibration → credibility element; EV/CLV deferred). Fold old
      Props sub-tabs (Performance/Matchups/Model) into Player/Game. Keep `/scores` + landing.
- [ ] Redirects for `/stats`→Leagues, `/analytics`→gone. Update OG/meta, mobile nav, empty states.
- [ ] Acceptance: every old surface reachable via the three tabs + entity pages; no dead links.

### Phase 6 — Model + breadth (post-restructure)
- [ ] Projection model beyond Marcel: opponent/matchup adjustment, regression-to-mean, opportunity share.
- [ ] Props breadth beyond MLB (odds source decision) → real lines on more games.
- [ ] Revive EV/CLV with a real model + closing-odds capture (then maybe a sharp "edge" view).
- [ ] Fantasy: rankings / start-sit / rookie "best available" (→ sport.fun lane).

## Sequencing
```
Phase 0 (scaffold + search)
   ├─> Phase 1 (Prop viz — ship first, highest value, data ready)
   ├─> Phase 2 (Player page)  ─┐
   ├─> Phase 3 (Game/scoreboard) ┤ parallelizable (uses Phase-1 PropChart)
   └─> Phase 4 (Leagues/Team)  ─┘
                 └─> Phase 5 (nav cleanup — after 1–4 reach parity)
                          └─> Phase 6 (model + breadth)
```

## Delegation notes — parallel backend/UI split
Run backend and UI in parallel against a clean contract so neither blocks the other:
- **I (Claude) own backend** — endpoints + data shape. **Hermes owns UI** — components/pages that
  consume those endpoints. Define the JSON contract first; both build to it independently.
- Carve **independent slices**: e.g. I ship `/api/props/history` (returns the shape), Hermes builds
  `<PropChart>` against that shape (mock until live); or I add a route stub, Hermes fills the page.
  Removals/renames that are self-contained (e.g. "remove the Analytics tab") → hand straight to Hermes.
- Each todo → a self-contained spec (like `TASK-tennis-set-scores.md`): goal, files, data shape,
  definition-of-done, dev-only constraints. Hermes is warmed on this repo.
- **roma-dspy(trial) can't write code** (calculator toolkit only) — use Hermes / meeseeks.sh for builds.
- Verify every agent "done" on the live tunnel yourself — its "done" is a claim (the tennis lesson:
  data flowing ≠ it looks right; check the actual render).

## Guardrails
- Dev only: `LP_DB_PATH=backend/data/picks.dev.db`, backend :8095, frontend :3095. Never touch prod.
- Branch per slice off `analytics-backbone`; merge when verified. No AI/Claude attribution.
- Tag releases as the line ships (semver, CHANGELOG.md). This plan = v0.3.0.
