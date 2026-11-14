# Source inventory: NBA historical relationships (measured 2026-11-12)

Scope: what the dev DB (`backend/data/picks.dev.db`) and public ESPN endpoints hold for NBA player-team history, transactions, appearances and team results. Read-only. Each line says what was asked and when. A gap here is a statement about the endpoint asked, not about the world.

## Held in the dev DB

| Source | NBA coverage measured | Can build | Missing |
| --- | --- | --- | --- |
| `player_game_logs_all` (`team`, `opponent`, `game_date`, `game_type`, `appearance_status`) | season 2025 (2025-26): 34,786 rows, 591 players, 2025-10-21 to 2026-06-13. season 2026: 1,739 rows (2026-01-14 to 2026-10-20, needs a look). season 2027 (2026-27): 7,039 rows, 644 players. Nothing before Oct 2025. | Per-game team for a player, so tenure by game for 2025-26 and 2026-27. Played vs dnp (28,713 played, 6,070 dnp, 8,778 blank, 3 unknown). | Any season before 2025-26. A row only exists when ESPN listed the player. |
| `team_game_results` | 2,462 rows, 1,231 games, 2025-10-21 to 2026-04-13. Regular season only. | Team-vs-team results for 2025-26. | Playoffs, earlier seasons. |
| `game_summaries` | 229 NBA rows, all completed. | Per-game payloads for a small set. | Most games. |
| `roster_snapshots` / `roster_memberships` | ESPN: 4 snapshots, 2026-08-04 to 2026-11-12. NBA.com: 2 snapshots, 2026-10-03 to 2026-11-12. | Current roster, per-source status. | Any roster before Aug 2026. No transaction dates. |
| `player_team_shares` | by season and team | Team share of a stat | Not tenure evidence. |
| `nfl_transactions` | NFL only (2,046 rows) | A pattern to copy | No NBA table exists. |
| `players` | 740 NBA players with logs. Identity gates pass (NBA league gate 18 pass, 0 UNVERIFIED, 0 FAIL on dev). | Stable ids (`players.id`, `espn_id`, nba.com id in `player_source_ids`) | Players with no log in 2025-27. |

## Public publishers asked

| Asked (2026-11-12) | Result | Use |
| --- | --- | --- |
| `site.web.api.espn.com/apis/site/v2/sports/basketball/nba/transactions` | 200. 437 rows, 18 pages, 2026-01-02 to 2026-11-11. The `year=2025` parameter was ignored (`requestedYear` stayed 2026). Rows are free text with a team and a date. | A source for signings, waivers and trades since Jan 2026. Does NOT reach the July 2025 Durant trade. Same host as `nfl_transactions_sync.py`. |
| `sports.core.api.espn.com/.../nba/transactions?limit=1` | 200, count 0 | Nothing at this endpoint. |
| `sports.core.api.espn.com/.../nba/athletes/3202/statisticslog` | 200. One entry per season with the team ref for that season. | Tenure by season for any athlete, one request per player. Season level only. |
| `stats.nba.com` and `cdn.nba.com` (plain client, earlier today) | timeout and 403 | Not usable from this box. |

Not yet asked: NBA.com official transactions pages, the Rockets and Suns announcement pages named in the task, ESPN `statisticslog` for the fixture players. Request cost for the fixtures is about 3 to 10 requests.

## Findings that change the design

1. **Our logs start in Oct 2025.** The Durant trade (July 2025) is not in any table we hold. A transaction fact needs a published source, a pinned fixture, or a new ingest. Per-season team history before 2025-26 is available from `statisticslog`, not from our DB.
2. **An absent log row is not an inactive record.** Durant has 81 logs for 88 HOU games in 2025-26 (79 played, 2 dnp). He has no row for the 2025-11-24 game. That fits "did not play" but our data cannot prove it. The `inactive` status needs a source such as the box score inactive list or the game summary.
3. **Apr 7, 2026 return:** a `played` log exists (game 401811012, HOU at PHX, REG). So the playing return is supported by our data.
4. **Date conventions differ.** `player_game_logs_all.game_date` and `team_game_results.game_date` differ by one day for 945 games (local date vs UTC date). Join on `game_id`, never on date.
5. **Season keys:** `season` 2025 is 2025-26 and 2027 is 2026-27. Season 2026 holds 1,739 rows with dates from 2026-01 to 2026-10. I have not explained those rows.
6. **Story engine gap confirmed by reading `story_engine.py`:** `select_story_angle` has team records, streaks, standings and `rematch_performance`. There is no `former_team`, `former_teammates` or trade category. `_db_player_facts` stays untouched.
7. PR #35 (postgame prototype) is still OPEN. Keep the relationship module independent of it.

## Next step (needs a decision)

Pin fixtures for the HOU, PHX trade and Durant tenure from official pages, then build the pure graph module with the 20 tests listed in the task. A bulk NBA transaction ingest is only worth building after the fixtures show the shape.
