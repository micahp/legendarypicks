# NBA historical relationships: what this branch has and has not built

Full explanation and caveats: [WORK-AND-CAVEATS.md](WORK-AND-CAVEATS.md).

Branch `feat/historical-relationships-nba`. Draft. No merge, no deploy, no production change.

## Built
| Piece | File | Tests |
|---|---|---|
| Ingest of NBA.com's official player movement file | `backend/ingest_nba_player_movement.py` | `test_ingest_nba_player_movement.py` (21) |
| Pure graph: trade transactions, team stints, shared tenure, as-of filter | `backend/sports_relationships.py` | `test_sports_relationships.py` (18) |
| Deterministic candidate detector | `backend/storyline_candidates.py` | `test_storyline_candidates.py` (30) |
| Editorial ranking (rubric v0-unvalidated) | `backend/storyline_ranking.py` | `test_storyline_ranking.py` (22) |
| Adapter and read-only collector (`story_engine.py` unchanged) | `backend/story_engine_relationships.py` | `test_story_engine_relationships.py` (18) |
| Plain wording templates and an independent audit of the finished text | `backend/storyline_templates.py`, `backend/storyline_audit.py` | `test_storyline_audit.py` (28) |

Kinds detected: `former_team_matchup`, `reciprocal_trade_reunion`, `first_team_meeting_after_trade`, `former_arena_return`, `first_return_to_former_arena`, `former_teammates_now_opponents`.

## Not built (spec items still open)
- Wiring the adapter into the preview runtime, an endpoint or a timer. Nothing calls it yet.
- `playoff_series_rematch`, `championship_or_franchise_milestone_connection`, `historical_rivalry`, `first_actual_opponents_after_trade`. No series, championship or appearance source is loaded.
- The 12-game editorial evaluation, the 50-game held-out set, before/after stories, latency measurement.
- A real inactive-list source. Whether Durant played on 2025-11-24 must come from one. The detector only takes availability as an input.
- A schedule for the ingest (not in `ingest_registry.py`, no timer).

## Known limits (measured 2026-11-12 and 2026-11-13)
- The movement file starts 2015-07-01 and carries the effective date only. No agreement date.
- Only 746 of 2,357 player ids in the file match `player_source_ids`. Older players do not join.
- A "re-signed" row proves a player was already on a team, so it never marks a tenure start as documented. Tatum and Brown at Boston come out `complete=False`.
- The ingest created two tables on the dev DB only (`nba_player_movement`, `nba_player_movement_snapshots`). Prod has neither.

## Run
```
cd backend
python3 -m unittest test_ingest_nba_player_movement test_sports_relationships test_storyline_candidates
python3 ingest_nba_player_movement.py --db <db>        # one request to stats.nba.com, plain client
```
