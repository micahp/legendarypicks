# TASK — MLB pitcher per-game logs (unlock pitcher prop charts)

## Goal
Our MLB game logs are **batting-only** (`ingest_mlb_logs.py` groups Statcast by *batter*).
So pitcher props — `strikeouts`, `outs`, `hits_allowed`, `earned_runs`, pitcher walks —
the **biggest chunk of the daily slate** — show "no data" in the prop chart. Add a per-game
**pitching** log so those props chart.

## Approach (mirror the batting ingest)
`ingest_mlb_logs.py` already pulls Statcast and groups batting events by `(batter, game_pk)`.
Add a parallel path that groups by **`(pitcher, game_pk)`** and derives a per-game pitching
line from the pitch-level data:
- `K` = count of `events == 'strikeout'`
- `outs` = sum of outs recorded (use `events`: outs on the play; simplest = count PA-ending
  events that are outs — strikeout, field_out, force_out, grounded_into_double_play (×2), sac_fly, etc.)
- `hits_allowed` = count of `events in (single, double, triple, home_run)`
- `earned_runs` — not directly in Statcast pitch data; approximate or leave null (note it)
- `BB` = count of `events == 'walk'`
- `batters_faced` = PA count
Statcast `pitcher` is the mlbam_id of the pitcher (same id space as batters). Resolve to
`players.id` via `mlbam_id` — **resolve-or-queue, never create a dup row** (see AGENTS.md §7 /
`docs/IDENTITY-SPINE-STATE.md`). Write to `player_game_logs` with a stat_type/marker so pitching
rows are distinguishable (e.g. store the pitching stats under their own keys: `K`, `outs`,
`hits_allowed`, `BB`, `batters_faced`).

## Market mapping (so the chart finds them)
Add to `_MARKET_STAT_KEY['mlb']` in `backend/sports_service.py`:
`strikeouts→K (pitcher)`, `outs→outs`, `hits_allowed→hits_allowed`, `total_pitcher_walks→BB`.
Note: `strikeouts` as a *batter* market would also map to K — but pitcher strikeout props are
the common ones; the player's role (their logs) disambiguates. Keep it simple: pitcher logs
carry `K`/`outs`/`hits_allowed`; batter logs carry `H`/`TB`/`HR`. A player has one or the other.

## Definition of done
- `ingest_mlb_logs.py` (or a new `ingest_mlb_pitcher_logs.py`) writes per-game pitching lines.
- A starting pitcher with a `strikeouts` prop today charts: e.g. find a pitcher in today's props,
  call `/api/props/history?player_id=<id>&market=strikeouts&line=<n>&league=mlb` → returns games
  with their K per start + hit/miss vs the line.
- No dup player rows created (verify: dedup check stays at ~0 new MLB dups).

## Constraints
- Dev only: `LP_DB_PATH=backend/data/picks.dev.db`, backend :8095. Do NOT touch prod or deploy.
- Branch off `analytics-backbone`. No AI/Claude attribution on commits.
- Verify against real data (a real pitcher's K log), not just that it runs.
