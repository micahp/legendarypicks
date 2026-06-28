# Changelog

All notable changes to Legendary Picks are documented here.

Versioning follows [Semantic Versioning](https://semver.org): `vMAJOR.MINOR.PATCH`.
- **MAJOR** — breaking changes / major product milestones (still `0` pre-launch).
- **MINOR** — new features, backwards-compatible.
- **PATCH** — bug fixes, backwards-compatible.

Each released version corresponds to a git tag and a production deploy. The version
in `package.json` tracks the next (in-development) release.

> Note: a stray `package.json` version of `0.3.1` predated this scheme and was never a
> real release. Disciplined versioning starts here, with the current production state
> tagged `v0.1.0`.

## [Unreleased] — targeting v0.3.0 — depth + richness

v0.3.0 is gated on closing the current UI holes. Each bullet is its own minor build
(v0.2.x), promoted to v0.3.0 once the set lands. See `docs/SPEC-v0.3.0-ui-holes.md`.
- **Richer Stats (league) tab** — match ESPN's depth: separate **player vs team** breakdowns,
  and category splits (e.g. **offensive / defensive**), not a single flat leaderboard.
- **Game detail beyond MLB** — only MLB has a real detail page today. Build NBA/NHL/NFL detail,
  and fill the three empty tabs (**box score, play-by-play, game info**).
- **Post-game recap** — the AI summary today is a *pre-game* preview; add a separate
  **post-game recap/summary** generated once the game is final.
- **Prop outcomes on game detail** — show **what hit** on the game-detail props (today only the
  Props page has a ✅/❌, and its orientation needs rework). Run the front-end design skill on it.
- Player-name links app-wide → player page.
- **UFC rankings** (weight class + pound-for-pound) — P4 from `docs/SPEC-2026-06-27-next-phases.md`.

### Shipped to prod ahead of tag (v0.2.3 — hotfixes)
- **Footer pinned to the viewport bottom** on short pages — the layout wrapper is now a flex
  column with `main` growing (`flex-1`), so the footer stops floating mid-page on the homepage.
- **App icons + favicon: transparent corners** — circular alpha mask applied to every `logo-*.png`,
  `apple-touch-icon.png`, and a rebuilt `favicon.ico`, removing the black square corners while
  keeping the holographic disc and the black "LP" mark intact.

## [0.2.2] — 2026-06-28

### Added
- **Stats (league) tab** — `GET /api/{league}/leaders` leaderboard + a **Players | Teams**
  sub-view toggle on the Stats page; MLB batting/pitching toggle. Player names link to `/player/[id]`.
- **NBA matchups** — the Matchups tab now works for NBA (per-game logs got `opponent`/`home_away`
  via `ingest_nba_logs` fix + `backfill_nba_opponent.py`), no sportsbook data needed.
- **NBA edge slot** on the game page — projected stat lines where NBA has no posted props
  (`/api/game/{lg}/{id}/edge`).
- **AI game previews generated on discovery** — loading a scoreboard warms the preview cache in
  the background (`_core.kick_game_stories` on `/api/{league}/games`), so the preview is instant
  on click instead of making the first viewer wait ~7s. `pregenerate_game_stories.py` backfill helper.
- **Projection-vs-line badge** on player-page prop rows.

### Changed
- **Backend de-monolithed** — `sports_service.py` (2125 lines / 30 routes) split into a thin app
  shell + `routers/{games,players,props,analytics,game_extras}.py` + shared `_core.py`.
- **Frontend game page** split into `components/Game/*`.
- **Analytics tab removed** from the nav (EV all-zero / CLV empty per the M7 audit; deferred).
- Stats tab kept the name **"Stats"** (briefly "Leagues"; reverted pending the richer-stats build).

### Fixed
- Game-state labelling — never show "FINAL" on a live/upcoming game (state-aware ScoreStrip).
- Removed the World Cup dead-click (no detail page exists for WC).

### Docs
- Engineering retro (`docs/RETRO-2026-06-27.md`), next-phase spec
  (`docs/SPEC-2026-06-27-next-phases.md`), AGENTS `§0` current-state pointers.

## [0.2.1] — 2026-06-27

### Added
- **Player page** — `/player/[id]` + `/api/player/{id}`: header, current props (with charts),
  projections, recent games — reached via a new **global player search** in the header
  (search icon on mobile, inline on desktop).
- **Prop visualization** — `<PropChart>` + `/api/props/history`: bar chart of last N games vs
  the line + hit rate + projection, with L5/L10/L20 + home/away + vs-opponent filters. Replaces
  the retrospective ✅/❌ in Props·Lines.
- **MLB pitcher game-logs** — pitcher props (strikeouts/outs/hits_allowed) now chart.
- **Matchups tab** — live player-vs-opponent splits (was a stub).
- `opponent` / `home_away` added to game logs (+ backfill).

### Fixed
- **MLB identity dedup** — merged 317 duplicate player rows; batter prop-chart coverage 53%→90%
  (Freeman/Betts/Kurtz now resolve). `dedupe_mlb.py`.
- Prop market mapping — league-keyed + `total_*` Bovada names + `_base_market` normalization.
- Header nav hidden on mobile; dev frontend silently proxying to prod (`.env.local`).

### Docs
- `IDENTITY-SPINE-STATE.md` + the resolve-or-queue rule in `AGENTS.md §7`.

## [0.2.0] — 2026-06-26 — analytics-backbone (cut; not yet deployed)

### Added
- **Per-game player logs** (`player_game_logs`) across all four leagues — 111k+ logs,
  spine-resolved. The stats foundation projections/fantasy run on, no sportsbook data needed.
  Ingests: NFL weekly 2024 + NFL play-by-play 2025 (EPA/CPOE/air-yards), MLB Statcast,
  NHL nhle.com game-log, NBA ESPN box scores.
- **Player projections** — `/api/projections/player/{id}` + the **Model tab**: recency-weighted
  expected value, floor/median/ceiling, P(over a line), and projected fantasy points.
- **roster_sync** — current ESPN rosters populate `espn_id` and a meaningful `active` flag.
- **World Cup standings** consolidated into the Stats tab as a league option.
- **Tennis scoreboard cards** show per-set game scores (parsed from ESPN `linescores`)
  in a proper scoreboard layout — each player's games-per-set as aligned columns.

### Changed
- **NFL identity dedupe** — removed 380 id-less orphan player rows that shadowed real players
  (distinct same-name players preserved).
- **Standings** page removed; folded into Stats.

### Fixed
- `/api/player/{id}/stats` raised `NameError('now')` on every call — the Performance tab's
  advanced-stats panel was dead for all leagues.
- World Cup / COD live badges (match clock + game number display).
- World Cup winner dimming (winner flag now reaches the frontend; draws no longer dim both sides).

## [0.1.0] — 2026-06-26 — production baseline

First tagged release. Snapshot of what was live on prod:
- backend `dee1133` (COD/breakingpoint scoreboard fix)
- frontend `b4ae8f9` (~2 commits behind backend on the `dev` line — a known deploy drift)

Includes the ESPN-based sports backend, scores/standings/predict/props/stats/analytics pages,
settlement pipeline, odds capture, and EV/CLV/calibration analytics (M1–M7).
