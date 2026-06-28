# SPEC — v0.3.0 UI holes (gating the 0.2.x → 0.3.0 promotion)

v0.2.2 promoted what's built (Stats leaderboard, NBA matchups, props page tabs, PropChart,
game-detail props, AI previews). **We do not bump to v0.3.0 until these holes close.** Each is
its own minor build (v0.2.x). Run the **frontend-design skill** before building UI-heavy ones.
Backend is split — add endpoints to the matching `backend/routers/*.py` (see `AGENTS.md §0`).

## 1. Richer Stats (league) tab — match ESPN's depth
Today: one flat sortable leaderboard per league. Target: ESPN-grade breadth.
- **Player vs Team** are different lenses, each with **category breakdowns** — e.g. **offensive vs
  defensive** (and league-appropriate groupings: NBA scoring/rebounding/defense, NFL passing/rushing/
  receiving/defense, NHL skaters/goalies, MLB batting/pitching/fielding).
- Backend: extend `/api/{league}/leaders` with a `category` param (or add `/api/{league}/teams/leaders`)
  so each tab pulls the right column set; reuse `player_stats` + `team_game_stats`/`strength`.
- AC: each league shows ≥2 player categories and ≥2 team categories with real, sorted data; columns
  match what the table renders; off-season leagues degrade cleanly.
- Look at how ESPN lays out league → stats (player leaders grid + team stat rankings) for structure.

## 2. Game detail beyond MLB + fill the empty tabs
Today: only MLB renders a real detail page; NBA/NHL have box-score data but the page is thin, and the
three bottom tabs (**Box Score, Play-by-Play, Game Info**) are empty for most leagues.
- Build real NBA/NHL/NFL detail pages (`components/Game/*` already split for this).
- Populate the three tabs from existing capture helpers in `_core` (`_snapshot_*`, `_extract_*`,
  `team_game_stats`, `scoring_plays`, `game_context`); ingest where data is missing.
- AC: for each supported league, a final game shows a populated box score + play-by-play + game info;
  upcoming/live degrade per state (no fake FINAL).

## 3. Post-game recap (the current summary is pre-game only)
Today: `_core.generate_game_story` writes a **pre-game preview**. Need a **post-game recap** too.
- Add a recap path (separate prompt grounded in the final box score + scoring plays + who-hit), stored
  alongside the preview (e.g. `game_story.kind = preview|recap`), generated when a game goes final
  (hook the same discovery path / a state==post check).
- AC: a final game shows a recap grounded only in real final stats; pre-game still shows the preview;
  no invented narrative.

## 4. Prop outcomes on game detail + orientation rework
Today: only the Props page shows a ✅/❌ (and its info orientation needs rework, per owner). The
game-detail props don't show **what hit**.
- Backend: join `prop_results` so game-detail props carry hit/miss + actual value.
- Frontend: run the **frontend-design skill** to rethink how prop info is oriented (player → prop →
  line → result), on both the game-detail props module and the Props page.
- AC: settled props on game detail show outcome + actual; the new orientation is reviewed via the
  design skill before shipping.

## Also tracked
- Player-name links app-wide → `/player/[id]`.
- **UFC rankings** (weight class + P4P) — P4 in `docs/SPEC-2026-06-27-next-phases.md`.

## Deploy note (carry-over blocker)
Prod DB `picks.db` is **missing `player_game_logs`** and has **stale `player_stats`**. The marquee
features (player page, matchups, PropChart, projections, NBA edge, stories) need that data. **Migrate
it into `picks.db` (without clobbering prod's live `props`/`prop_results`) before the container deploy.**
