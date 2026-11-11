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
| Network name | Unknown | The ESPN summary API returned no network name. Do not write "ESPN" as a fact. |
| Golden State record 8-3 | Checked today, as-of unknown | ESPN summary API, 2026-27 standings. The standings snapshot time is not in the response. |
| Houston record | Unknown | Not found in the response I read. A secondary page (SportBusy) shows 7-1. That conflicts with 8-3, which the spec states. It is not a source of truth. |
| Injuries, Houston: Clint Capela (out), Steven Adams (out) | Checked today, as-of unknown | ESPN summary API, `injuries`. No time stamp. Not usable for pregame claims until a time is found. |
| Injuries, Golden State: Will Richard (day-to-day), Gary Payton II (out), Brandon Williams (out), Kristaps Porzingis (out), Moses Moody (out) | Checked today, as-of unknown | ESPN summary API, `injuries`. No time stamp. Not usable for pregame claims until a time is found. |
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

## Endpoint checks, 2026-11-11

| Endpoint | Result | Note |
|---|---|---|
| ESPN summary API, `site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401909974` | HTTP 200 | Usable. Four calls to ESPN today. |
| ESPN web preview page, `espn.com/nba/preview/_/gameId/401909974` | HTTP 403 via WebFetch | The web page is blocked. The API is not. |
| NBA CDN, `cdn.nba.com/static/json/...` (two files) | HTTP 403 | Blocked from this box. |
| NBA stats API, `stats.nba.com/stats/scoreboardv2` | Timed out after 20 s | Not confirmed as blocked. Not reachable in this check. |
| nba.com game page, `nba.com/game/GSW-vs-HOU-0022600225` | Read via WebFetch summary | Gave the date and tipoff time only. The raw page was not inspected. |

Older repo docs also report 403 from stats.nba.com and cdn.nba.com
(`docs/CONTEXT-2026-10-21.md`, `docs/PROPS-SOURCE-AUDIT-2026-10-21.md`).

## Open items

1. Find a time stamp for the injury statuses.
2. Find the network name for the broadcast.
3. Confirm Houston's 2026–27 record from a source.
4. Find an NBA injury source with time stamps.
5. Complete the `nba_schedule` snapshot and its ESPN ID crosswalk.
6. Confirm 2026–27 final scores are written to `nba_schedule`.
7. Confirm a stable NBA player game-log source for 2026–27.
8. Decide whether the official NBA draft page can be the draft source.

## Changes to this doc

Add a row or a dated check when a source changes. Do not move a fact from
Unknown to a checked status until the request or the file that proves it is
cited.
