# PLAN — Entity-page UX restructure

Large, multi-session undertaking. Source of truth for the work + delegation. Check off
todos as they land; keep this doc current (it's the handoff across sessions/agents).

## The vision
The app's spine becomes **entity pages, not feature tabs.** Data reorganizes around
**League → Team → Player**, with **Games** as the time cross-section and **Slate** as the
daily home. Today's feature tabs (Scores/Stats/Props/Predict/Analytics) dissolve into:

| Entity page | What it is | Replaces / absorbs |
|---|---|---|
| **Slate** (home) | Today's games across leagues → drills into games. The daily workbench. | Scores (today) |
| **Game** `/game/[lg]/[id]` | Matchup + **today's projections / props / edges** for its players. Where today's-game projections live (they're game-contextual). | Props·Lines/Slate, Predict |
| **Player** `/player/[id]` | Asset/profile: stats, game logs, form trajectory, projection trend, "next game" card → game. | Props·Performance/Matchups/Model |
| **League** `/league/[lg]` | Standings/strength + team stats + leaders + schedule. | **Stats tab** |
| **Team** `/team/[lg]/[id]` | Roster, schedule, team stats → players. | (new) |
| **Global search** | Jumps to any entity (players first). | (new, header) |

### Persona → door (all share the entity pages)
- **Prop bettor** (props.cash) → Slate → Game (tonight's edges)
- **Casual fan** (ESPN) → Scores/League (what's on, standings)
- **Fantasy** → Player projections + Game (start/sit)
- **Trader** (sport.fun, later) → Player page as asset (trajectory/value)

## OPEN DECISION — lock before Phase 1
**Front door: Slate-first vs League-first.**
- Slate-first (props.cash): open into today's games + edges; league/player are drill-downs.
- League-first (ESPN): top nav = leagues; each → league page; slate is "Today" within.
- **Recommendation: Slate-first + a league switcher** — the bettor/fantasy edge is the
  differentiated value. Revisit if casual-fan is persona #1.
- ⛳ **Owner decision needed. Everything below assumes slate-first; adjust nav if league-first.**

## Already built (foundation — reuse, don't rebuild)
- `player_game_logs` (111k logs, 4 leagues) + per-game ingests + `roster_sync` + NFL dedupe.
- `/api/projections/player/{id}` — recency-weighted EV + floor/median/ceiling + P(over) + fantasy pts.
- `/api/player/{id}/stats` (advanced metrics, all leagues — `now` bug fixed).
- `espn_client`: `games(lg,date)`, `team_strength(lg)`, `boxscore(lg,id)`, `roster(lg,team)`, `game_result`.
- `/api/{lg}/games`, `/strength`, `/team-stats` (M5), `/api/props*`, `/api/players/search`.
- Existing routes: `/scores`, `/stats`, `/props`, `/predict`, `/analytics`, `/game/[league]/[gameId]`.
- See `CONTEXT-2026-06-26.md` + `PROJECTIONS-METHODOLOGY.md`.

---

## Phases & todos
Each task is delegation-ready: scope + files + acceptance. Hand specs to Hermes/meeseek;
verify every "done" against the live UI (data flowing ≠ it looks right — the tennis lesson).

### Phase 0 — Decisions + scaffolding
- [ ] Lock front-door model (slate-first vs league-first) — **owner**.
- [ ] Add routes skeleton (empty pages + types): `/` (slate), `/league/[league]`,
      `/player/[id]`, `/team/[league]/[id]`. Keep old tabs live until parity.
- [ ] Header: global search component (wraps `/api/players/search`) → routes to player page.
- [ ] Define data contracts per page (what each endpoint must return) — short doc.

### Phase 1 — Player page (highest value, foundation ready)
- [ ] **Backend:** `/api/player/{id}` aggregate (compose stats + recent logs + projections +
      props-on-player + next-game ref) OR compose client-side from existing endpoints.
- [ ] **Frontend `/player/[id]`:** header (name/team/pos), projection trend, game-log table,
      advanced metrics, **"next game" card → /game/...**. Subsumes Performance/Matchups/Model.
- [ ] Wire global search + every player name (slate, game, league, box scores) → player page.
- [ ] Acceptance: search a player in each league → page shows real logs + projections; next-game
      card links to a real game. Verify on tunnel.

### Phase 2 — Game page + Slate (the daily decision loop)
- [ ] **Backend:** `/api/projections/game/{league}/{id}` — projections for both rosters in the
      matchup (reuse per-player projection; later: opponent-adjust per PROJECTIONS-METHODOLOGY).
- [ ] **Backend:** enrich slate endpoint (games + has-props/projections flags).
- [ ] **Frontend Game page** (`/game/[league]/[id]` exists — extend): matchup header + player
      **projections vs lines + edges** + props for the game. Today's projections live here.
- [ ] **Frontend Slate (`/` home):** today's games across leagues (league filter) → game pages.
      props.cash-style board; bettor's home.
- [ ] Acceptance: open slate → tap a game → see per-player projections (+ lines where MLB props
      exist). Verify on tunnel.

### Phase 3 — League page (retire Stats) + Team page
- [ ] **Backend:** league leaders endpoint (top players by stat, from `player_game_logs`).
- [ ] **Frontend `/league/[league]`:** standings/strength (from `/strength`) + team stats + leaders
      + schedule. World Cup standings as a league here. **Retire the Stats tab.**
- [ ] **Frontend `/team/[league]/[id]`:** roster (→ players) + schedule + team stats.
- [ ] Acceptance: league page replaces Stats with no data regression; team page lists current roster.

### Phase 4 — Nav consolidation + retire old tabs
- [ ] New top nav: Slate/Today + league switcher + global search (+ Predict if kept as engagement).
- [ ] Redirect/remove `/scores`, `/stats`, `/props`, `/analytics` as absorbed (keep redirects).
- [ ] Update OG/meta, mobile nav, empty states.
- [ ] Acceptance: every old surface's content reachable via new entity pages; no dead links.

### Phase 5 — Model + breadth (post-restructure)
- [ ] Projection model beyond Marcel: opponent/matchup adjustment, regression-to-mean, opportunity
      share (PROJECTIONS-METHODOLOGY steps 2/4/5).
- [ ] Props breadth beyond MLB (Bovada/odds source decision) → real lines on more games.
- [ ] Fantasy: rankings / start-sit / rookie "best available" (player-asset → sport.fun lane).

## Sequencing / dependencies
```
Phase 0 (decide + scaffold)
   └─> Phase 1 (Player)  ─┐
   └─> Phase 2 (Game/Slate) ─┤── can run in parallel (different agents/sessions)
   └─> Phase 3 (League/Team) ┘
                 └─> Phase 4 (nav cleanup — after 1–3 reach parity)
                          └─> Phase 5 (model + breadth)
```
Phases 1/2/3 are independent slices (good for parallel delegation). Phase 4 only after they
reach feature parity with the old tabs. Phase 5 is open-ended follow-on.

## Delegation notes
- Each todo → a self-contained spec (like `TASK-tennis-set-scores.md`): goal, files, data shape,
  definition-of-done, dev-only constraints. Hand to Hermes (warmed on this repo) or meeseek.
- **roma-dspy(trial) can't write code** (calculator toolkit only) — use Hermes / meeseeks.sh for build tasks.
- Verify every agent "done" against the live tunnel yourself — its "done" is a claim.

## Guardrails
- Dev only: `LP_DB_PATH=backend/data/picks.dev.db`, backend :8095, frontend :3095. Never touch prod.
- Branch per slice off `analytics-backbone`; merge when verified. No AI/Claude attribution.
- This is v0.2.0+ territory — tag releases as slices ship (semver, see CHANGELOG.md).
