# SPEC — Game-detail tabs (Box Score / Play-by-Play / Game Info) for all leagues

**Owner:** spec by Claude (orchestrator). **Implementation: DELEGATE to Hermes** (DeepSeek) per the
feature-dev workflow — see "Hermes execution requirements" at the bottom.

## Goal
The game-detail page (`pages/game/[league]/[gameId].tsx`) already shows three tabs — **Box Score**,
**Play-by-Play**, **Game Info** — but they're only populated for **NBA/NHL**. Every other league
shows "Full box score for this league is coming soon." Fill those tabs for every league **where ESPN
gives us the data for free**, and show a clean "not available for this sport" state where it doesn't.

## Data audit (VERIFIED against ESPN `/summary?event=` — the free source we already use)
ESPN's site API `/summary` (via `espn_client._SITE` + `?event={id}`) carries `boxscore`, `plays`,
`gameInfo`, and (soccer) `keyEvents`/`commentary`/`rosters`. Data populates once a game is **live or
final** (scheduled games return empty — handle gracefully). Per-league reality:

| League | Box score | Play-by-play | Game info | Notes / shape |
|---|---|---|---|---|
| **NBA** | ✅ players + teams | ✅ `plays` (full) | ✅ `gameInfo` | already wired — the reference |
| **NHL** | ✅ players + teams | ✅ `plays` | ✅ `gameInfo` | already wired |
| **MLB** | ✅ players + teams + `rosters` | ✅ `plays` (at-bats) | ✅ `gameInfo` | US-team-sport shape |
| **NFL** | ✅ players + teams | ✅ `plays` (drives/plays) | ✅ `gameInfo` (+weather) | US-team-sport shape |
| **WC (soccer)** | ✅ team match stats + `rosters` (XI) | ✅ `keyEvents` + `commentary` | ✅ `gameInfo` (referee) | **soccer-shaped — different** |
| **ATP / WTA** | ❌ none | ❌ none | ❌ none | `/summary` returns `{}` for tennis — N/A. Card already shows per-set scores. |
| **UFC** | ❌ (fight-card model) | ❌ | ❌ | `/summary` empty — different model, **out of scope** (separate spec) |
| **COD** | ❌ no ESPN path at all | ❌ | ❌ | not an ESPN sport — **out of scope** |

So: implement the **3 tabs for NBA, NHL, MLB, NFL, WC**. For ATP/WTA/UFC/COD show a clean empty
state (or hide the tabs). Two normalization families: **US team sports** (NBA/NHL/MLB/NFL, shared
shape) and **soccer** (WC, its own shape).

## Backend (FastAPI, `backend/routers/games.py` + `espn_client.py`)
Add **three lazy per-tab endpoints** (the frontend loads a tab on demand), each reading the cached
ESPN `/summary` and normalizing per family. Each returns `{ available: bool, ... }` so the UI can
render "not available" without guessing.

1. `GET /api/{league}/game/{id}/boxscore`
   - **US team sports:** `{ available, teams: [{ name, abbrev, stats: [{label,value}] }],
     players: [{ team, group, columns: [..], rows: [{ name, position, stats: [..] }] }] }`
     (group = e.g. "Batting"/"Pitching" for MLB, "Passing"/"Rushing"/"Receiving" for NFL,
     skaters/goalies for NHL, single table for NBA.)
   - **Soccer (WC):** `{ available, teamStats: [{label, home, away}], lineups: [{side, formation,
     players:[{num,name,pos}]}] }` (reuse existing `espn.lineups()`).
2. `GET /api/{league}/game/{id}/playbyplay`
   - **US team sports:** `{ available, periods: [{ label, plays: [{ clock, text, scoreAway, scoreHome,
     scoringPlay: bool }] }] }`.
   - **Soccer:** `{ available, events: [{ minute, type (goal|card|sub|var), text, team }] }` (from
     `keyEvents`/`commentary`, reuse `espn.match_events()`).
3. `GET /api/{league}/game/{id}/gameinfo`
   - `{ available, venue, city, attendance, capacity, officials: [..], odds: {spread, overUnder,
     favorite}, weather (NFL), broadcasts: [..] }` from `summary.gameInfo` + `summary.header`.

Implementation notes:
- Reuse `espn_client` — add `summary(league, game_id)` (cached, ttl ~20s) that returns the raw
  summary once; the three endpoints derive from it. (`game_result`, `boxscore`, `lineups`,
  `match_events` already hit `/summary` — refactor to share one cached fetch to avoid 3 calls.)
- **Do not regress NBA/NHL.** They currently render from `/api/{league}/game/{id}/detail`
  (DB-snapshot path). Option A (lower risk): leave NBA/NHL as-is, add the new endpoints for
  MLB/NFL/WC only, frontend picks source per league. Option B (cleaner): move all 5 to the live
  ESPN endpoints and retire the snapshot path. **Recommend A** for this pass; note B as a follow-up.
- Scheduled game (empty summary) → return `{ available: false }`, not an error.

## Frontend (`components/Game/*`, `pages/game/[league]/[gameId].tsx`)
- **Tab gating:** compute supported tabs per league. Tennis/UFC/COD → render the matchup header +
  story + props (as today) and **hide the three tabs** (or one disabled "Detailed stats aren't
  available for this sport yet."). Don't show empty tabs.
- **Box Score tab:**
  - Keep `NBABoxScore` / `NHLBoxScore`.
  - Add **`MLBBoxScore`** (batting + pitching tables) and **`NFLBoxScore`** (passing/rushing/receiving
    + defense), driven by the generic `{group, columns, rows}` contract — ideally ONE
    `<StatTable group columns rows>` component reused across MLB/NFL (and refactor NBA/NHL onto it
    if cheap).
  - Add **`SoccerBoxScore`** — team-stat comparison bars (possession, shots, xG…) + both lineups
    (formation + XI/subs).
- **Play-by-Play tab:** generalize the existing `PlayByPlay` to render `{periods:[{label,plays}]}`
  for US sports; add a **soccer event timeline** (minute • icon • text) for WC.
- **Game Info tab:** extend `GameInfo` to show venue/city/attendance/officials/odds/weather/broadcast
  from the new endpoint (keep the strength priors it already shows).
- Loading skeletons per tab; lazy-fetch a tab's endpoint on first open; `cache:'no-store'` for live.

## Acceptance criteria
- For a **live or final** NBA, NHL, MLB, NFL, and WC game: all three tabs render real data
  (player box score, chronological play-by-play / soccer key events, venue+info). Verified
  **visually in a headless browser**, not just HTTP 200.
- MLB shows batting + pitching; NFL shows passing/rushing/receiving; WC shows team stats + both XIs +
  goal/card/sub timeline.
- ATP/WTA/UFC/COD: tabs hidden / clean "not available" — no empty boxes, no errors.
- Scheduled games: "stats start when the game's live" message, no crash.
- **NBA/NHL detail still works exactly as before** (no regression).

## Out of scope
- Tennis match stats (aces/winners — ESPN summary is empty for it), UFC fight stats, CoD — separate
  specs if/when a data source exists.

## Hermes execution requirements (per our feature-dev workflow)
- **Delegate to Hermes** (`scripts/hermes-worktree.sh`), DeepSeek — not a Claude subagent.
- The task MUST spawn **executor + validator subagents for BOTH backend and frontend**. The
  **frontend validator must visually test each league's tabs in a headless browser** (200 ≠ done) —
  screenshot a live/final MLB, NFL, and WC game's three tabs.
- Dev DB only; do not touch prod. Don't regress NBA/NHL.
- gstack skills are available (`gstack-spec`, `gstack-design-review`, etc.).
- **I (orchestrator) verify Hermes's "done" myself** — load the pages, confirm real data renders per
  league — **before merging** to `analytics-backbone`.
