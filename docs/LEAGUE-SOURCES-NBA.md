# NBA data sources and gaps

**Status:** Source inventory, written 2026-11-11 from the repository docs, the
dev database schema, and two live checks on this box. It is a record of what is
known and what is missing. It does not add or change any data.

**Why this doc exists:** `docs/LEAGUE-SOURCES-FIELDS.md` covers MLS, NCAAF, and
tennis. It has no NBA section. Any NBA fact used in a preview must name its
source and its gap here first.

## Rules this doc follows

- A fact needs a primary source: the league, the team, or a stats publisher
  that we have checked. Secondary news pages are leads only. They are not
  evidence.
- Every fact carries an as-of time. A fact stamped after a pregame cutoff must
  not enter a pregame preview.
- The NBA game ID is the forecast key. An ESPN ID is not required for a pregame
  preview (`docs/NBA-GAME-MODEL-PHASE1.md`).
- ESPN hosts follow the request-budget rules in the `espn-request-budget`
  skill. Do not add a per-game ESPN loop without that check.

## Source inventory

| Fact needed | Where it lives now | Source | Status | Gap |
|---|---|---|---|---|
| Game identity, date, tipoff | `nba_schedule` in `picks.dev.db` | nba.com game pages, via `ingest_nba_schedule.py` (`docs/CONTEXT-2026-10-03.md`) | Partial | 1,206 regular-season rows, 1 cup row, 66 preseason rows as of the 2026-10-21 snapshot. 24 regular-season games are missing. |
| ESPN game ID | `nba_schedule.espn` | ESPN | Incomplete | Only 5 regular-season rows have an ESPN ID (`docs/NBA-GAME-MODEL-PHASE1.md`). |
| Final scores, 2026–27 | `nba_schedule.home_score`, `away_score` | nba.com game pages | Empty as of 2026-10-21 | No row has a final score in that snapshot. Re-check before use. |
| Team results, 2025–26 | `team_game_results` | SportsDataverse ESPN team boxes | Complete to 2026-04-13 | No 2026–27 games. |
| Team records, 2026–27 | None | Derivable from `nba_schedule` finals | Missing | Depends on the score gap above. |
| Player game logs, 2026–27 | None confirmed | SportsDataverse / NBA Stats releases | Missing | Both releases end with 2025–26 (`docs/NBA-GAME-MODEL-PHASE1.md`). |
| Injury and availability | None | None | Missing | `injury_reports` holds NFL rows only (`docs/CONTEXT-2026-10-20.md`). |
| Broadcast network and national flag | None | None found | Missing | No NBA broadcast source doc exists. nba.com's game page did not show networks on 2026-11-11. |
| Draft position | Not checked | Official NBA draft pages | Unchecked | A check is needed before any draft claim is used. |
| Live forecasts | Prospective forecast rows | ESPN live scoreboard and summary (`docs/NBA-GAME-MODEL-PHASE1.md`) | Active | Subject to the ESPN request-budget rules. |

## Live checks, 2026-11-11

These checks came from this box. They show what the tools could reach that day.

- **nba.com game page** for game 0022600225: returned the date and tipoff only
  (Wednesday, November 11, 2026, 9:30 PM ET). It did not show a venue, a
  network, team records, or injury notes.
- **ESPN preview** for game 401909974: HTTP 403 from this box.
- **stats.nba.com and cdn.nba.com**: HTTP 403 from this box (Akamai). Recorded
  in `docs/CONTEXT-2026-10-21.md` and `docs/PROPS-SOURCE-AUDIT-2026-10-21.md`.
- **Web search results** (secondary, not evidence): SportBusy listed records of
  5-3 and 7-1. Legion Report listed injuries that disagree with each other and
  are dated early November. Neither page is a primary source. Do not use them as
  facts.

## What a pregame NBA preview can say today

- The date and tipoff time, when the matching `nba_schedule` row exists and the
  nba.com page confirms it.
- Season-stage context, from the completed-game count. This needs a verified
  count, not a guess.
- Team streaks and records for 2026–27 only after final scores exist in
  `nba_schedule`. Until then, say nothing about records.
- Player form only from cutoff-safe game logs. No 2026–27 logs are confirmed.
- No injury claims until an NBA injury source exists.
- No broadcast claims until a broadcast source exists. The national-telecast
  sentence in the previews needs a source before it can be used.

## Open items

1. Find an NBA injury and availability source with timestamps.
2. Find an NBA broadcast source with the national flag.
3. Complete the `nba_schedule` snapshot and its ESPN ID crosswalk.
4. Confirm 2026–27 final scores are being written to `nba_schedule`.
5. Confirm a stable NBA player game-log source for 2026–27.
6. Decide whether the official NBA draft page can be the draft source.

## Changes to this doc

Add a row or a dated check when a source changes. Do not remove a gap until the
fix is in the data, and cite the check that proves it.
