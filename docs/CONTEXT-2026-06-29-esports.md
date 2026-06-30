# CONTEXT — 2026-06-29 — Esports "Live Now" build (read FIRST)

A full day on the **`/esports` page** ("Live Now") + a **discovery rail and free audio on the
Scoreboard**. This is the state of it. All on **dev** (branch `analytics-backbone` = `dev`),
uncommitted-to-prod.

## Update (later 06-29) — discovery rail + free World Cup audio
- **Scoreboard "Live Now" rail** (`pages/scores.tsx` → `LiveNow`): surfaces every in-progress game
  as a clickable chip + a **"🎮 Live esports →"** pull + (when a WC match is live) the audio player.
  This is the **discovery thesis** — pull a viewer who came for one sport into another that's live.
- **Free WC audio** (`components/ListenLive.tsx`): native `<audio>` playing iHeart's FIFA World Cup
  station **direct AAC stream** `https://stream.revma.ihrhls.com/zc11554` (FOX English commentary,
  all 104 games, free, **US-accessible**). On the WC game-detail page too. Verified playing.
  - **Audio saga / lessons:** talkSPORT(TuneIn) = UK geo-blocked; iHeart's full *page* embed
    defaulted to a local station (Kiss.fm); the fix = the **direct stream URL in a native player**
    (got it from iHeart's `api.iheart.com/api/v2/content/liveStations/<id>`). Don't embed consumer
    radio *pages* — get the stream URL.
- **GRID live: only feature ON-AIR matches.** GRID's `finished` flag lags (a Bo3 ends but stays
  started && !finished), so we were featuring dead series with offline streams. Now gated on
  `seriesState.updatedAt` freshness (<4 min) + stable pick (prefer a tournament we have a channel
  for, earliest-started). Can't query Kick/Twitch live-status directly (both block servers).
- **Valorant assessment** (deferred — EWC starts Jul 2): GRID Open Access EXCLUDES Valorant (Riot
  paid tier); paths are (1) GRID paid = trivial code add, contract blocker; (2) unofficial vlrggapi
  scrape = ~half day, ToS-grey. Plan: vlrggapi stopgap for EWC + ask GRID Valorant pricing.

## What the page does now (`pages/esports.tsx`)
Top to bottom:
1. **Featured live match — exactly ONE at a time**, priority: **MSI (LoL) > GRID CS2/Dota > chess**.
   - Live video embed + live data overlay + a "moment that matters" callout.
2. **MSI 2026 — Win Predictions** (pre-game): power-ranking prior (Sheep, Elo→Bo5) priced vs the
   **Bovada moneyline**; an amber EDGE chip when model% disagrees with market%. Split into
   **Scheduled** and **Results · backtest**. (Predictions belong in the future Leagues tab,
   tournament-level — see Open items.)
3. **Chess** only shows as the featured match when nothing bigger is live (fallback).

Design: one system — tracked-caps eyebrows + gradient hairline section headers, mono+tabular
numerals for all data, emerald reserved for the "moment that matters" beacon.

## Data sources (and the gotchas — this is where confusion creeps in)
- **MSI / LoL** = the **unofficial LoL Esports web API** (`esports-api.lolesports.com` +
  `feed.lolesports.com/livestats/v1/{window,details}`, public web key in code). Gives live game
  state, **full player rows** (champ via DDragon, role, live K/D/A+CS), Bo5 series, AND the
  broadcast stream ids (YouTube/Twitch). ToS-grey — fine for prototype, NOT for monetization.
  Live feed needs a `?startingTime=` ~now-60s param or it returns opening frames (all zeros).
- **CS2 + Dota 2** = **GRID Open Access (OFFICIAL, commercial-legit)**. Host **`api-op.grid.gg`**
  (NOT api.grid.gg), key `GRID_API_KEY` in `/root/.hermes/.env`, header `x-api-key`. central-data
  `allSeries` (schedule/teams) + live-data-feed `seriesState(id)` (live score + per-player K/D).
  **Covers CS2(1)+Dota2(2) ONLY** (LoL/Valorant/R6 excluded). **`series.streams[]` is EMPTY** on
  Open Access → GRID gives no broadcast URL.
- **Chess** = Lichess TV (free) + Stockfish for the win% (kept; the gold-based LoL win% was
  rejected as uncalibrated — don't show uncalibrated win%).
- **Bovada** = esports moneylines for the model-vs-market edge.
- **DDragon** = LoL champion portraits.

## Stream embedding (the part that's been fiddly)
- **MSI**: YouTube primary (clean), Twitch one-tap fallback (Twitch overlays clutter the video).
  Stream ids come straight from the LoL API.
- **GRID CS2/Dota**: GRID gives no stream, so a **tournament→channel map** (`_GRID_STREAM_MAP` in
  `backend/routers/esports.py`). The bookmaker-sponsored **minor leagues stream on KICK**
  (`player.kick.com/<ch>`, no parent param) — EPL→`epldota_en2`/`eplcs_en2`, United21→`united21_en`,
  CCT→`cct_cs2`, Thunderpick. **Majors on Twitch** (ESL/BLAST/PGL/EWC). Embeds **unmuted** (autoplay
  with audio; may need one click). Kick/YouTube can't render in headless (anti-bot) — verify on a real browser.
- **Stable featured pick**: `grid_live` collects all live series and picks deterministically (prefer
  a tournament we have a channel for, then earliest-started) so it stops flipping between matches.

## Known limitations (real, not bugs to chase blindly)
- **Multi-channel minor leagues** (EPL runs many concurrent matches across en1/en2/…): the embedded
  league channel may show a DIFFERENT match than the card's stats. Clean only for single-match
  marquee events. (This caused the "stream flipped to something else" confusion.)
- Channel liveness is best-guess for the long tail (no Twitch/Kick API to find the live sub-channel).

## Endpoints (`backend/routers/esports.py`)
- `GET /api/esports/chess/live` — Lichess + Stockfish win%.
- `GET /api/esports/lol/msi/predictions` — Sheep Elo prior + Bovada edge.
- `GET /api/esports/lol/msi/live` — MSI live (state, player rows, series, YT/Twitch).
- `GET /api/esports/grid/live` — live CS2/Dota via GRID + Kick/Twitch channel.

## Ops
- **Dev backend must run with both env vars**: `LP_DB_PATH=…/picks.dev.db` AND `GRID_API_KEY`.
  Restart: `setsid env LP_DB_PATH=… GRID_API_KEY=$(grep GRID_API_KEY /root/.hermes/.env|cut -d= -f2-) uvicorn sports_service:app --app-dir backend --port 8095 …`
- **Prod deploy (when ready)** needs `GRID_API_KEY` passed at up-time (like DEEPSEEK) + Stockfish in
  the backend Dockerfile (already added).
- Frontend fetches use `cache:'no-store'` (browser was caching the GET → stale live data).

## Open items / next
- **Carousel of "more live matches"** (Micah's idea): when multiple GRID series are live, show a
  rail below the feature; click to switch which is featured. (Solves the multi-match problem cleanly.)
- **Leagues hub**: Stats → ESPN-style sport/league directory, each league its own tabs
  (scores/stats/standings/predictions). Home for the schedule + off-board sports + predictions.
- **GRID schedule** into the Scheduled view (CS2/Dota) — once the Leagues tab exists.
- **Player props / projections** (LoL): need accumulated per-player history → **Oracle's Elixir**
  CSVs feeding LP's existing projection engine (GRID gives CS2/Dota finished-series stats too).
- **Twitch/Kick API** to pin the exact live sub-channel for minor leagues (needs app creds).
- **Backlog bugs** (non-esports): World Cup stats stuck on group stage; tennis cards show "P3" not
  "Set 3"; a winner-arrow / "final/10" UI thing (needs Micah's screenshot — never attached).
- Add the **main esports games to the scoreboard** too (lives with the Leagues hub).

## Rules learned today
- Don't show **uncalibrated win%** (fake precision) — Micah rejected the gold-based LoL one.
- **Never suggest pausing** / "watch the game" — keep working.
- When he sends rapid feedback, KEEP shipping consistently; don't go data-only/lazy on one surface
  while another (chess) has the richer treatment.

## Update (late 06-29) — Game-detail tabs for all leagues
- **Branch:** `feat/game-detail-tabs` (off `analytics-backbone`, worktree `/root/lp-game-detail-tabs`)
- **Backend** (`0b3ad8d`): 3 new lazy per-tab endpoints — `GET /api/{league}/game/{id}/boxscore`,
  `GET /api/{league}/game/{id}/playbyplay`, `GET /api/{league}/game/{id}/gameinfo`. Shared cached
  `espn.summary()` (20s TTL) replaces 5 duplicate `/summary` fetches. Two data families: US team
  sports (MLB/NFL/NBA/NHL — period-grouped plays + team/player stat tables) and soccer (WC — team
  match stats + lineups + key-events timeline). ATP/WTA/UFC/COD return `{available:false}`.
  Existing `/api/{league}/game/{id}/detail` path (NBA/NHL DB-snapshot) untouched — no regression.
- **Frontend** (`f9193e0`): MLBBoxScore (batting+pitching, ◆ HR markers, AVG glow), NFLBoxScore
  (passing/rushing/receiving 3-col grid + defense), SoccerBoxScore (stat bars + lineups),
  generalized PlayByPlay (period timeline + soccer event rail), extended GameInfo (odds chips,
  weather, broadcasts, capacity fill%). TabBar gating hides tabs for unsupported leagues (ATP/WTA/
  UFC/COD show clean "Detailed stats aren't available for this sport yet."). NBA/NHL use legacy
  `/detail` path unchanged.
- **One bug caught:** ESPN uses `sg.type` (not `sg.name`) for stat group names — backend patched.
- **Dev preview:** http://127.0.0.1:3096/game/mlb/401815676 (backend :8096).
- **Not yet merged** — awaiting frontend validator (headless browser screenshots). Merge to
  `analytics-backbone` with `git -C /root/legendarypicks merge --ff-only feat/game-detail-tabs`.
- **Merged** (`78c8912`) — orchestrator review caught 2 crashes the validators missed: (a) WC soccer
  lineup `pos` was a raw ESPN object `{name,displayName,abbreviation}` → React crash, fix = emit
  `.abbreviation` string. (b) Soccer PBP clock `"45'+2"` broke `int(x.replace)` → all minutes showed 0,
  fix = take leading digits before `+`. Both fixed in merge (`9d8c415`). Root cause: frontend validator
  skipped WC — must headless-render EVERY league family. Learnings codified in AGENTS.md §10.
- **Git hygiene:** `git add -A` committed `__pycache__/` and `venv` symlink → dirty-tree merge blocks.
  Use targeted `git add` only. Cleaned up in `6413739`.

## Update (late 06-29) — Leagues hub (Stats → per-league tabbed pages) + WC knockout fix
- **Branch:** `feat/leagues-hub` (off `analytics-backbone`, worktree `/root/lp-leagues-hub`).
  Not yet merged — user verifies before merge.
- **Commits:** `04a02e1` (7 files, 1006 lines), `31156f4` (ESPN object extraction fix).
- **Backend:** New `wc_knockout_standings()` in `espn_client.py` — reads scoreboard for knockout
  bracket when group stage is over. ESPN `/standings` returns empty `{children:[]}` but `/scoreboard`
  carries knockout events with results. `/api/wc/standings` now returns `{rounds:[{name,matches}]}`
  with knockout data (Brazil 2-1 Japan, etc.) instead of stale 12 group tables. Fix: `season.type`
  can be an int (not a dict) — added isinstance guards.
- **Frontend:** New `/leagues` index grid (6 league cards) + `/leagues/[league]` hub with tabs:
  Standings, Stats (Players|Teams), Schedule (+ Rankings for UFC). Nav "Stats" → "Leagues".
  `/stats` redirects to `/leagues`. Reuses all stats.tsx patterns. `normalizeGame` fixed: league
  field can be ESPN object — extract string.
- **Verification:** Frontend validator headless-rendered ALL 6 league hubs (NBA/MLB/NHL/NFL/WC/UFC)
  with ZERO pageerrors. WC knockout confirmed rendering. Two-tone design verified. Backend
  validator caught `/api/wc/knockout` home/away still shipping as objects — fixed to plain strings.
- **Dev preview:** http://127.0.0.1:3097/leagues (frontend :3097, backend :8097).
- **Merge:** `git -C /root/legendarypicks merge --ff-only feat/leagues-hub` (after user review).
- **Tear down:** `scripts/hermes-worktree.sh down leagues-hub`
