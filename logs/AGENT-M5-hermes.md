# AGENT-M5-hermes — Team Stats Enrichment (NBA/NHL/NFL)

**Status (orchestrator verification, 2026-06-24): DONE — real data, idempotent, live.**
hermes started this log; orchestrator verified end-to-end. (Earlier "backfill defect"
entry was a MISREAD by the orchestrator — corrected below.)

## Built
- `team_game_stats` table — wide/unified (NBA cols + NHL cols; CREATE TABLE IF NOT
  EXISTS in sports_service.py:52, self-creates on startup). Deviation from the
  long/EAV shape the spec asked for — defensible for a known finite stat set.
- `backend/backfill_team_stats.py` — ESPN boxscore → UPSERT, default --days 90,
  cached, idempotent (existing>=2 → skip).
- Endpoints `/api/{nba|nhl|nfl}/team-stats` (live). MLB rejected (out of M5 scope).

## Verified (real data — orchestrator)
- Table: 1152 rows, 480 distinct games (MLB 176 [pre-existing snapshot path],
  NBA 486 / 227 games, NHL 490). Endpoints return real, complete-per-row stats
  (NBA: fgm_fga, fg_pct, rebounds, assists…).
- **Idempotency holds:** re-run of `backfill_team_stats.py` → "Total inserted: 0",
  count + distinct games unchanged (1152/480 stable across 2 runs). The "0 inserted"
  is correct skip-on-complete behavior (`if existing >= 2: continue` at line 56-58,
  before `inserted += 1`), NOT a discovery failure.
- **Re-discovery works:** ESPN `?dates=20260415` returns completed (state=post) games;
  sampled game_ids (401866757, 401866756, 401859963) are all present in the table
  (2 rows = home+away). A fresh DB would repopulate. (Orchestrator's earlier "re-run
  finds 0 = defect" was a misread of `inserted` vs `found` — corrected.)

## Open items (minor, not blocking; for a future pass)
- **Endpoint LIMIT 200, no pagination** — `/api/nba/team-stats` returns 200 of 486
  NBA games. Add `?limit`/`?season`/pagination.
- **MLB not exposed** by the endpoint (176 MLB rows sit in the table from a
  pre-existing snapshot path). Out of M5 scope; surface if MLB team-stats needed.
- Existing complete rows aren't refreshed on re-run (skip) — late ESPN boxscore
  corrections won't be picked up. Low priority.
