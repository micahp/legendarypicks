# NFL team splits: points, wins and conditions, as far back as the data goes

Status: dev-only research on `research/nfl-historical-splits-2026-10-27`. The store is read-only input to queries, the
dev database is not written, no simulator default changes, and nothing here feeds a projection. Results are raw, with no
shrinkage and no team-strength adjustment. Read every difference as a correlation, not an effect.

Scope: team splits first. Player splits (a play-by-play job, starting with 2026) come after this is accepted.

## 1. What was built

| Piece | Where | What it does |
|---|---|---|
| Builder | `scripts/nfl_sequence/splits/team_splits_build.py` | Builds one store from the splits layer, the dev database (attendance flags and the Elo table) and the 2026 capacity snapshot. Refuses to overwrite. |
| Query tool | `scripts/nfl_sequence/splits/team_splits_query.py` | Team tables by dimension, combined conditions, game lists, coverage, CSV export. Read-only. |
| Tests | `scripts/nfl_sequence/splits/test_team_splits.py` | 20 tests: bins, stadium renames, Elo conversion, metrics, coverage, combined filters. |
| Store | `/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.sqlite` | `team_game_row` (18,341 games, 36,682 team-games), `team_game_official`, `team_split` (33,342 rows), `team_split_coverage` (5,838 rows). |
| CSV | `/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.csv` | Every split row, without game IDs. |

Query examples:

```
python3 team_splits_query.py --team BUF                                  # every dimension, both tiers
python3 team_splits_query.py --team BUF --dimension weekday --scope tier_a
python3 team_splits_query.py --team BUF --where weekday=Sunday --where window_et=early --where roof=outdoors
python3 team_splits_query.py --team BUF --where official="Clete Blakeman" --games
python3 team_splits_query.py --team BUF --coverage
```

Combined conditions are computed on the game rows at query time. The store does not hold every combination, so no full
product is built.

## 2. Two tiers, and what each one knows

Tier A is 2010 to 2026. It comes from the splits layer: schedule, play-by-play, weather, officials and attendance.

Tier B is 1920 to 2009. It comes from the Elo game table, which has scores, weekday, home or away, playoff status and
neutral-site status. It has no kickoff time, weather, officials, venue or attendance.

Coverage (team-games known, by dimension, all teams):

| Dimension | Known team-games | Missing | Seasons known |
|---|---|---|---|
| Weekday, home or away, opponent, season, game type | 36,682 | 0 | 1920 to 2026 |
| Kickoff time, window (ET), roof, surface, stadium, capacity level, division, international | 8,940 | 27,742 | 2010 to 2026 |
| Window, venue-local | 6,174 | 30,508 | 2015 to 2026 |
| Window, body clock | 6,270 | 30,412 | 2015 to 2026 |
| Temperature and wind (outdoors only) | 8,482 | 28,200 | 2010 to 2026 |
| Referee | 8,856 | 27,826 | 2010 to 2026 |
| Official crew member (any position) | 6,088 | 30,594 | 2015 to 2026 |
| Attendance (cleaned) | 5,742 | 30,940 | 2015 to 2025 |

Tier A's missing counts are the games where a condition is unknown: 2026 weeks 1 to 7 have no crew list for most games,
and 2010 to 2014 have no venue state. Dome and closed-roof games are not missing for weather. They are classed
`not_outdoors`.

## 3. Definitions

- **Kickoff windows (ET)**: early before 2:30 PM, late afternoon 2:30 PM to 7:59 PM, primetime from 8:00 PM. Early includes
  9:30 AM London kickoffs (two Buffalo games, 2015 and 2023).
- **Venue-local and body-clock windows**: the same thresholds applied to the kickoff in the stadium's time zone (venue) and
  in the home team's time zone (body clock). Available from 2015, where the venue state is known.
- **Weather**: observed temperature and wind from the schedule, for outdoor games (`outdoors` and retractable `open`).
  Temperature bins: under 40 F, 40 to 59 F, 60 to 79 F, 80 F and up. Wind bins: under 10 mph, 10 to 14, 15 to 19, 20 and up.
- **Officials**: the referee from the crew list when present (2015 onward), otherwise the schedule's referee. Every crew
  member counts once per game, in any position.
- **Stadium**: the building the game was played in. A rename of the same building is grouped under the current name
  (20 renames, listed in the code). A rebuilt stadium or a move is not.
- **Capacity**: the current listed capacity (2026 snapshot, 30 venues) of the building the game was played in. This is
  not the capacity the building had when the game was played. Games in buildings with no current listing are
  `no_current_capacity` (1,080 team-games).
- **Attendance**: the recorded attendance. Zero is missing (2020 had no or limited crowds, 153 games). Four games flagged
  as suspect in the database are excluded.
- **Points in wins and losses**: the team's points scored and allowed in the games it won and in the games it lost.
- **Deltas**: a level's mean margin minus the team's own mean margin in the same scope (`delta_margin_vs_team`), and the
  same against the league (`delta_margin_vs_league`). Each row also reports its sample flag: `very_thin` below 3 games,
  `thin` below 8.
- **Postseason**: included in the scopes and the game-type dimension. Playoff games have no play-by-play, so their play
  counts are not used here.

## 4. Checks

- **Elo against the schedule**, 2010 to 2020: 2,762 games matched by date and teams, and every score agrees. In all 2,727
  non-neutral games, team 1 in the Elo table is the home team.
- **Buffalo, Sunday games (schedule recomputed directly)**: 236 games, 23.79 points for, 22.35 against. Stored: the same.
- **Blakeman with Green Bay (schedule recomputed directly)**: 19 games, 13 wins, 29.37 points for. Stored: the same.
- **Green Bay home wins (schedule)**: 105 games, 30.57 points for. Stored: the same.
- **Stadium capacities**: all 30 values match the Wikipedia list cited in the snapshot (checked 2026-10-27).
- **Stadium renames**: Buffalo's "New Era Field" (2016 to 2025) is not mapped to the 2026 Highmark Stadium listing (60,108),
  because that name is a different building. The test suite pins this.
- **Referee names**: the schedule and the crew list disagree on 18 games (36 team-games). Most are one spelling ("Ron"
  against "Ronald" Torbert, 151 games), which is unified. The rest are real conflicts between sources, where the crew
  list is used.
- **Oakland**: the Elo table codes the Raiders as OAK through 2020. They are mapped to LV, the current franchise code.

## 5. Results, raw

Buffalo, tier A (2010 to 2026): 282 games, 157 wins, 125 losses. Points for 24.3, against 22.1, margin +2.2. Points for in
wins 29.5, in losses 17.8.

Buffalo by weekday, tier A (from the query tool):

| Weekday | n | W-L-T | Points for | Points against | Margin | Points for in wins | Points for in losses |
|---|---|---|---|---|---|---|---|
| Sunday | 236 | 130-106 | 23.79 | 22.35 | +1.45 | 28.92 | 17.50 |
| Monday | 17 | 8-9 | 26.06 | 20.23 | +5.82 | 36.12 | 17.11 |
| Thursday | 16 | 11-5 | 25.75 | 20.62 | +5.12 | 28.00 | 20.80 |
| Saturday | 12 | 8-4 | 30.58 | 21.17 | +9.42 | 33.75 | 24.25 |

The Monday, Thursday and Saturday rows are small samples. Read them as descriptions only.

Team-relative effects across all 32 teams. Each team's margin in a level minus its own margin, averaged across teams and
weighted by team-games. Levels with fewer than 8 games for a team are excluded. Only levels with at least 100 team-games
are shown.

| Condition and level | Team-games | Teams | Mean margin vs team | Mean win% vs team |
|---|---|---|---|---|
| Home | 4,470 | 32 | +2.04 | +5.5 pts |
| Away | 4,470 | 32 | -2.04 | -5.5 pts |
| Weekday Sunday | 7,440 | 32 | +0.07 | +0.2 pts |
| Weekday Thursday | 550 | 32 | -0.25 | -0.5 pts |
| Weekday Saturday | 259 | 23 | -0.63 | -2.1 pts |
| Kickoff early (ET) | 4,660 | 32 | +0.39 | +1.1 pts |
| Kickoff late afternoon (ET) | 2,530 | 32 | -0.28 | -0.8 pts |
| Kickoff primetime (ET) | 1,750 | 32 | -0.64 | -1.9 pts |
| Primetime, body clock (2015 onward) | 601 | 17 | -1.17 | -2.1 pts |
| Primetime, venue-local (2015 onward) | 507 | 23 | -0.60 | -0.7 pts |
| Outdoors, under 40 F | 978 | 31 | -0.66 | -2.3 pts |
| Outdoors, 80 F and up | 688 | 31 | +0.52 | +1.6 pts |
| Outdoors, wind 15 to 19 mph | 539 | 30 | +0.10 | +0.3 pts |
| Outdoors, wind under 10 mph | 3,914 | 32 | -0.08 | -0.2 pts |
| Roof closed | 1,120 | 32 | +0.34 | +0.9 pts |
| Dome | 1,348 | 32 | -0.18 | -0.2 pts |
| Stadium capacity under 65k (current listing) | 747 | 19 | +1.08 | +2.8 pts |
| Stadium capacity 70k and up | 3,182 | 32 | -0.25 | -0.7 pts |
| Attendance under 60k (2015 to 2025) | 731 | 30 | +0.70 | +2.3 pts |
| Attendance 75k and up (2015 to 2025) | 888 | 30 | -0.12 | -0.9 pts |

Read these with care:

- No effect here has been adjusted for opponent strength, schedule, or rest. Primetime and Saturday games are played by a
  narrower set of teams. The capacity and attendance effects overlap with which teams play in which buildings.
- None of these has a significance test or a multiple-comparison correction in this document. The team-adjusted families
  run earlier in the research (E0 to E7) produced no candidate that survived the pooled and rolling-origin checks, and
  these team-relative numbers are not that analysis.
- The sample for a single team and a single level is often small. The query tool flags it. The CSV keeps the flag.

## 6. Limits

- Capacity is the current listing. A stadium's seating changes over the years, and historical capacity is not in the
  sources. This is item E6 in the research matrix, and it needs a source for historical capacities per building.
- Attendance is the measure of what the building held. It is available for 2015 to 2025 only, and 2020 is mostly zeros.
- Weather is observed, not forecast. The forecast-based split waits for E1 (archived forecasts with issue times).
- Officials before 2015 are the schedule's referee only, and crew members are not available.
- Tier B has no kickoff, weather, officials or venue. Any split on those dimensions starts in 2010, and most start in 2015.
- Playoff games have no play-by-play. Their points and results are used; their play counts are not.
- 18 games (36 team-games) where the schedule and the crew list name different referees are resolved in favour of the
  crew list.

## 7. Next: player splits

The same engine can run on player rows. The layer already has 294,286 player-game rows, with snaps from 2013 onward, and
calendar and venue data come from the team rows above. The plan:

1. A job that reads the layer's `player_game` one player-season at a time, joins the team conditions, and writes a
   `player_split` table in the same shape as `team_split`. It starts with 2026, then goes back.
2. Player results use per-game means and distributions, with the games behind each row, and the same baselines.
3. Teammate and expected-starter conditions reuse the role table, which was checked against ESPN's published starts
   for Josh Allen (`NFL-HISTORICAL-SPLITS-2026-10-27.md`, section 7).

No ESPN ingest is planned for this. The team splits do not need one.
