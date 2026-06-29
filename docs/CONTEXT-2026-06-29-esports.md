# CONTEXT — 2026-06-29 — Esports "Live Now" build (read FIRST)

A full day on the **`/esports` page** ("Live Now"). This is the state of it. All on **dev**
(branch `analytics-backbone` = `dev`), uncommitted-to-prod. Nothing esports is on prod yet.

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
