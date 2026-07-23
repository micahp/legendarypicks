# NFL offseason contracts v1

The NFL league page must not pretend that a league with no games today is inactive. These two DB-only
contracts let the client render a season-aware Training Camp / Draft Room experience without duplicating
the existing leaders, team-aggregate, roster, or schedule pipelines.

## GET /api/nfl/season-context

Contract: nfl-season-context-v1

Returns:

- the verified 2026 league phase and display label;
- official milestone dates and the next actionable event;
- explicit current-season versus reference-season labels;
- measured coverage for prior-season stats, game logs, current rosters, and team aggregates;
- readiness gates for timeline, draft board, opportunity movers, and camp battles;
- the authoritative NFL calendar sources and their verification date.

The route is DB-only. It does not call ESPN, nflverse, or a news feed during a page request.

Example excerpt for July 21, 2026:

    {
      "contract": "nfl-season-context-v1",
      "league": "nfl",
      "as_of": "2026-07-21",
      "phase": "training_camp",
      "phase_label": "Training Camp",
      "current_season": 2026,
      "reference_season": 2025,
      "next_event": {
        "id": "all_teams_report",
        "label": "All 32 teams in camp",
        "date": "2026-07-28",
        "days_until": 7
      }
    }

The calendar deliberately fails closed after December 31, 2026. A future session must verify and add the
next league-year calendar rather than silently displaying an obsolete phase.

## GET /api/nfl/draft-board

Contract: nfl-draft-board-v1

Query parameters:

| Parameter | Default | Allowed |
| --- | --- | --- |
| position | all skill positions | QB, RB, WR, TE, FB, FLEX |
| sort | fantasy_ppr_g | fantasy_ppr_g, fantasy_pts_g, pass_yds_g, rush_yds_g, rec_yds_g, targets |
| limit | 50 | 1–100 |
| offset | 0 | 0 or greater |

The endpoint joins the active player roster to the latest NFL player_stats season through the canonical
players.id identity spine. It returns only the requested bounded slice; it never downloads a full historical
population for a small UI list.

Each player includes:

- canonical player ID, name, and position;
- current roster team and reference-season team;
- reference-season games and fantasy/usage metrics;
- a tri-state team_changed field.

team_changed is true or false only when current-roster freshness is within seven days. It is null when the
roster is stale or unavailable, preventing an old roster from becoming a false transaction claim. Legacy NFL
team abbreviations are normalized before comparison, including LA/LAR, WAS/WSH, OAK/LV, SD/LAC, STL/LAR,
and JAC/JAX.

## Current measured development coverage

Measured against picks.dev.db on July 21, 2026:

- 605 players with 2025 reference statistics;
- 5,377 player-game rows for 605 players;
- 2,928 players across 32 active camp rosters;
- 512 active skill players linked to the 2025 reference season;
- complete 2025 team coverage: 32 teams and 272 regular-season games.

The current roster verification timestamp is June 15, 2026, so the contract correctly marks the roster stale.
The draft board remains usable as a labeled 2025 production baseline, but opportunity-mover and definitive
team-change claims remain blocked until roster_sync.py completes a fresh verified run.

## Intended frontend behavior

The first NFL landing surface should use season-context for its hero and timeline, then load one position slice
from draft-board on interaction. Existing endpoints remain authoritative for their current responsibilities:

- /api/nfl/leaders — complete category leader tables;
- /api/nfl/team-aggregates — full prior-season team comparisons;
- /api/nfl/games?date=YYYY-MM-DD — scheduled games;
- /api/player/{id} — player detail.

Do not copy those payloads into these contracts, create another live-discounts feed, or show blocked experiences
as if data were current.

