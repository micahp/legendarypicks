# TASK — league-surface UI pass — **DONE 2026-08-04, pushed to `dev`**

Implemented directly, not delegated. Six commits, `94cde46..056130e` on `dev`.
Verified in chromium against the dev tree (`:3096` / `:8096`) at 375px and 1440px.

| # | shipped | commit |
|---|---|---|
| P0 | NFL kickers + D/ST get a real game log | `80f8c7f` |
| 1 | NHL/NBA seasons read `2025-26` — player page **and** hub chips | `c8c39a6`, `cabffa2` |
| 6 | every coverage-chatter line deleted | `cabffa2` |
| 4 | `Display-only trend` chip deleted | `cabffa2` |
| 3 | tab strip + league switcher no longer drag vertically | `cabffa2` |
| 2 | NHL Last 10 never wraps | `254dfbe` |
| 7 | esports live dot is a circle | `de89454` |
| 5 | Season Outlook on Overview, under the rank card | `5e1a1b8` |
| 8 | World Cup off the hub, kept on Scores | `056130e` |

Suites: frontend 129 passed (was 119; +10 new). Backend 591 passed (was 587; +4 new).
The 2 frontend WC failures and the backend 3-failed/30-errors are pre-existing —
confirmed identical on a clean tree before any of this landed.

---

## What is still open

### Rank cards for MLB / NHL / NBA player pages

`StatRankCard` only ever appears on NFL pages because `stat_ranks` comes from
`backend/nfl_rankings.py` (`nfl_player_rank_context`, called at
`backend/routers/players.py:301`) and every other league is handed `{}`.

This is a **backend** change: a league-generic rank context over `player_stats`,
keyed on the canonical `UNIQUE(player_id, league, season, stat_type)` and using each
league's approved metric list from `_LEAGUE_CATEGORIES` in `routers/players.py`.

The part nobody has decided: **the qualifying population per league.** NFL ranks
against players with enough games to be comparable; MLB's equivalent is a
plate-appearance qualifier and `player_stats` has **no PA or AB column** to build one
(only `games`). So MLB either ranks on a games proxy — which is what already lets a
38-game player lead a 112-game season's batting average — or the column gets added
first. That question needs answering before the endpoint is worth writing.

### Not in scope here, but measured on 2026-08-03 and still true

- **NFL Standings shows 32 teams at 0-0.** `/{lg}/strength` and `/{lg}/standings` are
  the same unlabeled live ESPN passthrough with no season parameter; ESPN already
  reports NFL season 2026, which opens 2026-08-06. The Teams sub-view one click away
  serves 2025 with DEN 14-3.
- **MLB's spine has no team (89% blank) and no position (100% blank)** — the only
  leaderboard with an empty TEAM column. The team is published in our own
  `player_game_logs`, 0 blank of 49,144 rows.
- **NBA leaders serve 2023.** Only 53 of those 525 players have 2026 game logs. The
  2026 logs exist — 23,749 rows, 575 players. It is one missing rollup.
- **Prod still runs the pre-2026-08-04 image.** Everything above is on `dev` only.
