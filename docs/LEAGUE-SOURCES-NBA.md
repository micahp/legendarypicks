# NBA data sources and gaps

**Status:** Source inventory, updated 2026-11-11. Every fact in this doc has one
of three labels:

- **Checked today:** I ran the request on 2026-11-11 and saw the result.
- **Repo doc:** a statement from another doc in this repo. I did not re-check it.
- **Unknown:** no source confirms it. Do not use it.

Nothing here changes any data.

**Why this doc exists:** `docs/LEAGUE-SOURCES-FIELDS.md` covers MLS, NCAAF, and
tennis. It has no NBA section.

## Rules this doc follows

- A fact needs a source you can name and check. Secondary news pages are leads
  only.
- Every fact carries an as-of time. A fact with no as-of time cannot enter a
  pregame preview.
- The NBA game ID is the forecast key. An ESPN ID is not required for a pregame
  preview (`docs/NBA-GAME-MODEL-PHASE1.md`, repo doc).
- ESPN hosts follow the request-budget rules in the `espn-request-budget`
  skill.

## Game 0022600225 / ESPN 401909974 (Golden State at Houston, 2026-11-11)

| Fact | Status | Source and detail |
|---|---|---|
| Tipoff: 2026-11-12 02:30 UTC, which is 9:30 PM ET on Nov. 11 | Checked today | ESPN summary API, `header.competitions[0].date`. Converted to ET by hand (UTC-5 after the DST change). |
| Venue: Toyota Center, Houston | Checked today | ESPN summary API, `gameInfo.venue`. |
| Game state: scheduled | Checked today | ESPN summary API, `header` status. |
| Broadcast is national | Checked today | ESPN summary API, `broadcasts[].market.type = National`. |
| Network: ESPN (national) | Checked today | ESPN scoreboard API, `dates=20261111`, event 401909974: `broadcasts` market national, names ESPN; `geoBroadcasts` TV, ESPN. |
| Golden State record 8-3 | Checked today | ESPN team and scoreboard APIs (home/away record fields, `records[0]` = overall). No time stamp in the response; the request time was 2026-11-11, before tipoff. |
| Houston record 8-3 | Checked today | ESPN team API, `teams/10`, overall record `8-3`; the scoreboard shows the same. A secondary page (SportBusy, 7-1) conflicts. It is not a source of truth. |
| Injuries, Houston: Clint Capela (out, 2026-11-09 23:56Z), Steven Adams (out, 2026-11-09 23:55Z) | Checked today | ESPN league injuries API, `injuries`, feed timestamp 2026-11-12 00:35:37Z (before the 02:30Z tipoff). Each row has its own `date`. |
| Injuries, Golden State: Will Richard (day-to-day, 2026-11-11 19:09Z, "upgraded to probable"), Gary Payton II (out, 2026-11-10 21:36Z), Brandon Williams (out, 2026-11-10 21:24Z), Kristaps Porzingis (out, 2026-11-06 21:26Z), Moses Moody and Jimmy Butler III (out, 2026-10-16, long-term) | Checked today | ESPN league injuries API, same feed timestamp as above. Each row has its own `date`. |
| Players in the spec's fixture (Lendeborg, Curry, Durant) | Unknown in this doc | Not checked here. |

## Source inventory

| Fact needed | Where it lives now | Source | Status | Gap |
|---|---|---|---|---|
| Game identity, date, tipoff | `nba_schedule` in `picks.dev.db` | nba.com game pages, via `ingest_nba_schedule.py` (`docs/CONTEXT-2026-10-03.md`) | Repo doc | Repo doc (2026-10-21 snapshot): 1,206 regular-season rows, 1 cup row, 66 preseason rows; 24 regular-season games missing. Not re-checked today. |
| ESPN game ID | `nba_schedule.espn` | ESPN | Repo doc | Repo doc (2026-10-21): only 5 regular-season rows have an ESPN ID. Not re-checked today. |
| Final scores, 2026–27 | `nba_schedule.home_score`, `away_score` | nba.com game pages | Repo doc | Repo doc (2026-10-21): no row has a final score. Re-check before use. |
| Team results, 2025–26 | `team_game_results` | SportsDataverse ESPN team boxes | Repo doc | Repo doc: complete to 2026-04-13. No 2026–27 games. |
| Team records, 2026–27 | None | Derivable from `nba_schedule` finals | Unknown | Depends on the score gap above. |
| Player game logs, 2026–27 | None confirmed | SportsDataverse and NBA Stats releases | Repo doc | Repo doc: both releases end with 2025–26. |
| Injury and availability (database) | None | None | Repo doc | Repo doc: `injury_reports` holds NFL rows only (`docs/CONTEXT-2026-10-20.md`). |
| Broadcast network and national flag (database) | None | None found | Unknown | No NBA broadcast source doc exists. |
| Draft position | Not checked | Official NBA draft pages | Unknown | Must be checked before any draft claim is used. |
| Live forecasts | Prospective forecast rows | ESPN live scoreboard and summary (`docs/NBA-GAME-MODEL-PHASE1.md`) | Repo doc | Subject to the ESPN request-budget rules. |

## Player facts for the pinned game, checked 2026-11-11

Sources: ESPN roster API (`teams/9` and `teams/10` with `enable=roster`), ESPN
athlete overview (`athletes/{id}`), and ESPN game logs (`athletes/{id}/gamelog`).
ESPN gives game dates in UTC. The dates below are converted to Eastern time.
Averages are computed here from the listed regular-season games.

| Fact | Status | Detail |
|---|---|---|
| Yaxel Lendeborg, draft | Checked today | ESPN athlete overview, `displayDraft`: "2026: Rd 1, Pk 11 (GS)". 11th overall pick, 2026. |
| Lendeborg, regular-season points | Checked today | 23, 23, 17, 16, 37, 6, 26, 31, 26, 18, 12 (11 games, Oct. 22 to Nov. 10). Average 21.4 (computed: 235 / 11). |
| Lendeborg, last three games | Checked today | Nov. 1 vs LAC (37), Nov. 7 vs ORL (23), Nov. 9 vs NO (23). ESPN dates are UTC: Nov. 2, Nov. 8, and Nov. 10 in UTC. |
| Stephen Curry, points per game | Checked today | 30.6 (computed from 9 regular-season games in the ESPN log: 23, 24, 24, 44, 31, 34, 29, 41, 25). The log has 9 games, not 11. |
| Kevin Durant, points per game | Checked today | 21.0 (computed from 11 regular-season games in the ESPN log). Last game: 23 vs DEN, Nov. 9 ET, a 110-100 win. |
| Durant and the Warriors history | Unknown | Not checked. The spec lists it as a possible angle. |

## Endpoint checks, 2026-11-11

| Endpoint | Result | Note |
|---|---|---|
| ESPN summary API, `site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909974` | HTTP 200 | Usable. |
| ESPN scoreboard API, `.../nba/scoreboard?dates=20261111` | HTTP 200 | Usable. Lists 10 events for the date. |
| ESPN team API, `.../nba/teams/10` (Houston) | HTTP 200 | Usable. |
| ESPN league injuries API, `.../nba/injuries` | HTTP 200 | Usable. Feed has a timestamp and per-row dates. |
| ESPN athlete APIs (Lendeborg 5175737, Curry 3975, Durant 3202): overview and gamelog | HTTP 200 | Usable. |
| ESPN web preview page, `espn.com/nba/preview/_/gameId/401909974` | HTTP 403 via WebFetch | The web page is blocked. The API is not. |
| NBA CDN, `cdn.nba.com/static/json/...` (two files) | HTTP 403 | Blocked from this box. |
| NBA stats API, `stats.nba.com/stats/scoreboardv2` | Timed out after 20 s | Not confirmed as blocked. Not reachable in this check. |
| nba.com game page, `nba.com/game/GSW-vs-HOU-0022600225` | Read via WebFetch summary | Gave the date and tipoff time only. The raw page was not inspected. |

Older repo docs also report 403 from stats.nba.com and cdn.nba.com
(`docs/CONTEXT-2026-10-21.md`, `docs/PROPS-SOURCE-AUDIT-2026-10-21.md`).

## Open items

1. Check Durant's history with Golden State. Not checked yet.
2. Complete the `nba_schedule` snapshot and its ESPN ID crosswalk.
3. Confirm 2026–27 final scores are written to `nba_schedule`.
4. Confirm a stable NBA player game-log source for 2026–27.
5. Decide whether the official NBA draft page can be the draft source.

## Changes to this doc

Add a row or a dated check when a source changes. Do not move a fact from
Unknown to a checked status until the request or the file that proves it is
cited.
