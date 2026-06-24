# TASK — M5: Team-stats enrichment (NBA/NHL/NFL)

**For:** hermes
**Scope:** ONE additive per-game team-stats table + backfill + read endpoint.
**Do NOT** attempt the full game→team→player spine migration (M2-impl) — that is a
separate, larger task. Build M5 **incrementally on the current schema**, the same
way M6 odds-capture does.

## Problem
Team stats surfaced today are a "glorified standings" (win%, differential, streak,
last-10 via `/api/{league}/strength`). There is no first-class per-game team-stats
table for NBA/NHL/NFL. We want real boxscore-derived team totals so EV/quality
models can use them.

## Deliverable
1. **Schema (additive, one table):**
   ```sql
   CREATE TABLE team_game_stats(
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     game_id INTEGER NOT NULL REFERENCES games(id),   -- confirm the right FK table name first
     league TEXT NOT NULL,                            -- 'nba'|'nhl'|'nfl'
     team_id INTEGER,                                 -- resolve to existing team id by ID, never name
     team_name TEXT,
     stat_name TEXT NOT NULL,                         -- e.g. 'points','rebounds','shots_on_goal','total_yards'
     stat_value REAL NOT NULL,
     captured_at TEXT NOT NULL,
     UNIQUE(game_id, league, team_id, stat_name));
   ```
   Confirm the actual `games`/team table names + id columns in the live DB before
   writing the DDL. Use the existing ESPN client (`backend/espn_client.py` /
   `sports_service.py`) to fetch — do not hand-roll a new fetcher.

2. **Backfill script:** `backend/backfill_team_stats.py` — for each settled game in
   NBA/NHL/NFL (start with a bounded sample: last ~30 days, or a specific season),
   pull the ESPN boxscore team totals and upsert into `team_game_stats`.
   Idempotent (UNIQUE + UPSERT).

3. **Endpoint:** `GET /api/{league}/team-stats?game_id=...` (and/or a season
   roll-up). Returns the real per-game team totals.

## Which team-level stats to pull (per league)
- NBA: points, field_goals_made/att, rebounds, assists, steals, blocks, turnovers,
  three_pt_made/att, free_throw_made/att.
- NHL: shots_on_goal, faceoffs_won, power_play goals/chances, penalty_minutes,
  hits, blocks.
- NFL: total_yards, passing_yards, rushing_yards, turnovers, first_downs,
  penalties, time_of_possession.

Pull what ESPN actually exposes per league — curl-verify the boxscore payload for
ONE real finished game in each league before coding, and pin the sample stat names
in your progress log. If a stat isn't in the payload, skip it; don't fabricate.

## GUARDRAILS (non-negotiable — from AGENTS.md + CEO feedback)
- **Do NOT commit, push, or deploy.** Build, test against real data, write your
  progress to `logs/AGENT-M5-hermes.md`, hand back.
- **No destructive DB op** (DROP/DELETE/TRUNCATE) without a fresh
  `backend/data/picks.db.bak-<date>` in place. M5 is additive (CREATE TABLE +
  INSERT/UPSERT) — back up anyway before the first write.
- **Verify before you trust.** Curl real ESPN boxscore payloads, confirm the team
  stat fields are non-empty. 200 ≠ working.
- **Resolve identity by ID**, never name-string joins (AGENTS §7).
- **Bounded + polite.** Small sample first (a few games), cache, rate-limit. No
  machine-wide greps, no strings-on-DB, no unbounded loops (these locked the CEO
  out of SSH before).
- **Write progress to `logs/AGENT-M5-hermes.md`** as you go. If you pass ~70%
  context, STOP new work and write a complete handoff (state + exact next step +
  blockers) in that file.

## Done criteria (orchestrator will verify these against real data)
- `team_game_stats` table exists with rows from real finished NBA/NHL/NFL games.
- Backfill is idempotent (run twice → same row count).
- `/api/{league}/team-stats` returns real, non-empty team totals.
- Progress log explains what's verified vs open.
