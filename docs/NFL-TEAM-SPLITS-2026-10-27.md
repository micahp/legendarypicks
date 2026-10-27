# NFL team splits: points, wins and conditions, as far back as the data goes

Status: dev-only research on `research/nfl-historical-splits-2026-10-27`. The store is read-only input to queries, the
dev database is not written, no simulator default changes, and nothing here feeds a projection. Results are raw, with no
shrinkage and no team-strength adjustment. Read every difference as a correlation, not an effect.

Scope: team splits first. Player splits (a play-by-play job, starting with 2026) wait for the next direction.

## 1. What was built

| Piece | Where | What it does |
|---|---|---|
| Builder | `scripts/nfl_sequence/splits/team_splits_build.py` | Builds one store from the splits layer, the dev database (attendance flags and the Elo table), the stadium capacity history and the 2026 capacity snapshot. Refuses to overwrite. |
| Capacity history | `scripts/nfl_sequence/splits/data/stadium_capacity_history.csv` | 175 rows for 51 buildings: each stated period, its basis, and its source page. Reviewable in the repo. |
| Query tool | `scripts/nfl_sequence/splits/team_splits_query.py` | Team tables by dimension, combined conditions, game lists, coverage, CSV export. Read-only. |
| Tests | `scripts/nfl_sequence/splits/test_team_splits.py` | 26 tests: bins, building mapping, capacity lookup, Elo conversion, metrics, coverage, combined filters. |
| Store | `/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.sqlite` | `team_game_row` (18,341 games, 36,682 team-games), `team_game_official`, `team_split` (33,702 rows), `team_split_coverage` (6,394 rows). |
| CSV | `/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.csv` | Every split row, without game IDs. Regenerate after any rebuild. |

Query examples:

```
python3 team_splits_query.py --team BUF                                  # every dimension, both tiers
python3 team_splits_query.py --team BUF --dimension capacity_bin --scope tier_a
python3 team_splits_query.py --team BUF --where weekday=Sunday --where window_et=early --where roof=outdoors
python3 team_splits_query.py --team BUF --where official="Clete Blakeman" --games
python3 team_splits_query.py --team BUF --coverage
```

Combined conditions are computed on the game rows at query time. The store does not hold every combination, so no full
product is built.

## 2. Two tiers, and what each one knows

Tier A is 2010 to 2026. It comes from the splits layer: schedule, play-by-play, weather, officials, attendance, and the
stadium capacity history.

Tier B is 1920 to 2009. It comes from the Elo game table, which has scores, weekday, home or away, playoff status and
neutral-site status. It has no kickoff time, weather, officials, venue or attendance.

Coverage (team-games known, by dimension, all teams):

| Dimension | Known team-games | Missing | Seasons known |
|---|---|---|---|
| Weekday, home or away, opponent, season, game type | 36,682 | 0 | 1920 to 2026 |
| Kickoff time, window (ET), roof, surface, stadium, division, international | 8,940 | 27,742 | 2010 to 2026 |
| Window, venue-local | 6,174 | 30,508 | 2015 to 2026 |
| Window, body clock | 6,270 | 30,412 | 2015 to 2026 |
| Temperature and wind (outdoors only) | 8,482 | 28,200 | 2010 to 2026 |
| Referee | 8,856 | 27,826 | 2010 to 2026 |
| Official crew member (any position) | 6,088 | 30,594 | 2015 to 2026 |
| Attendance (cleaned) | 5,742 | 30,940 | 2015 to 2025 |
| Stadium capacity, dated history | 4,968 | 3,972 | 2010 to 2026 |
| Attendance as a share of dated capacity | 3,232 | 5,708 | 2015 to 2025 |

Capacity has two rows in the coverage table because the history has gaps. Every tier A game is classed (`capacity_bin`
includes a `no_dated_capacity` level), but only 4,968 games have a dated figure for their building and season.
The `capacity_source` dimension says which of the three cases each game is in: a dated figure (4,968), an undated figure
only (3,278), or no source at all (694).

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
- **Stadium**: the building the game was played in. Each recorded stadium name maps to exactly one building. A renamed
  building is one building. A rebuilt stadium is a different building: Buffalo's 2016 to 2025 stadium (New Era Field) and
  the 2026 Highmark Stadium are separate rows.
- **Stadium capacity (history)**: the seating capacity a building's Wikipedia page states for the years the game was
  played. A row counts only when its basis states a year or a span: dated tables, dated infobox former and current figures,
  an opening statement, a dated text figure, a bracketed span (two statements with no change stated between them), or an
  implied start year. Where two dated rows cover the same season, the one that starts later applies. Undated figures
  (infobox figures with no years) are recorded and never used in a historical bin. A gap between dated rows stays unknown.
- **Capacity source**: `dated` (a dated row covers the game's season), `undated_only` (the building has an undated figure
  but no dated one for that season), `none` (no figure for the building), or `no_building_match`.
- **Attendance**: the recorded attendance. Zero is missing (2020 had no or limited crowds, 153 games). Four games flagged
  as suspect in the database are excluded. Attendance share is attendance divided by the dated capacity for that season.
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
- **Stadium history, Buffalo**: the old stadium is 73,079 for 2010 to 2013, 71,857 in 2014, 71,870 in 2015, and 71,608
  for 2016 to 2025 (its New Era Field years). The new Highmark Stadium is 60,108 seats for 2026. The two are separate rows,
  and the test suite pins that.
- **Spot checks against the stored rows**: Lambeau Field 72,928 in 2010 and 81,435 in 2016. Qualcomm Stadium 70,561 in 2011.
  Bank of America Stadium has no dated figure for 2021 to 2024, and the store reports those seasons as unknown.
- **Snapshot against the pages**: the 2026 capacity snapshot (30 venues) matches the cited Wikipedia list for its own
  listing, but it differs from each building's Wikipedia page for 15 of 30 buildings. Examples: EverBank 69,132 in the
  snapshot against 42,507 on the page for 2026, a renovation-year figure; Arrowhead 73,426 against 76,416 (2010 to
  present); Raymond James 65,890 against 69,218 (2022 to present). The history uses the page figures. The snapshot stays in
  its own column (`capacity_snapshot_2026`) and no bin reads it.
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
| Dated capacity under 65k | 834 | 32 | +0.97 | +2.0 pts |
| Dated capacity 65k to 69k | 1,772 | 32 | +0.30 | +1.0 pts |
| Dated capacity 70k and up | 2,362 | 32 | -0.67 | -1.8 pts |
| Attendance under 85% of dated capacity | 193 | 14 | +1.91 | +4.6 pts |
| Attendance 85% to 94% of dated capacity | 456 | 21 | +0.93 | +2.3 pts |
| Attendance 95% to 99% of dated capacity | 1,432 | 32 | -0.46 | -1.6 pts |
| Attendance under 60k (2015 to 2025) | 731 | 30 | +0.70 | +2.3 pts |
| Attendance 75k and up (2015 to 2025) | 888 | 30 | -0.12 | -0.9 pts |

Read these with care:

- No effect here has been adjusted for opponent strength, schedule, or rest. Primetime and Saturday games are played by a
  narrower set of teams. The capacity and attendance effects overlap with which teams play in which buildings, and a small
  crowd can reflect a weaker team or a weaker market rather than the building itself.
- The capacity result rests on the dated history, which is fewer than half of tier A team-games. The undated figures and
  the 694 games with no source are not in these numbers.
- None of these has a significance test or a multiple-comparison correction in this document. The team-adjusted families
  run earlier in the research (E0 to E7) produced no candidate that survived the pooled and rolling-origin checks, and
  these team-relative numbers are not that analysis.
- The sample for a single team and a single level is often small. The query tool flags it. The CSV keeps the flag.

## 6. Limits

- The capacity history comes from each building's Wikipedia page. Pages state figures with different precision and
  basis, so each row carries its basis, and undated figures are not used for history. Some buildings have a dated history
  and some have only a current figure. Some have none that applies to NFL use.
- Buildings with no dated figure for the games they hosted: the Los Angeles Memorial Coliseum (its only table is college
  football), the Metrodome (as Mall of America Field, 2010 to 2013), Cleveland Browns Stadium (2010 to 2013), the Georgia
  Dome and Edward Jones Dome (undated figures only), and the international venues (undated figures, most of them not
  football-specific). These games stay `undated_only` or `none`.
- Two current figures are the 2026 renovation year and need care. EverBank's page lists 42,507 for 2026, during its
  renovation; the store uses it for the 2026 Jacksonville home and away games it covers (four team-games). The
  snapshot's 69,132 is kept in its own column and not used.
- Attendance is the realized measure, for 2015 to 2025 only, and 2020 is mostly zeros. A crowd figure is not a capacity:
  the attendance share depends on the capacity figure being right for that season.
- Weather is observed, not forecast. The forecast-based split waits for E1 (archived forecasts with issue times).
- Officials before 2015 are the schedule's referee only, and crew members are not available.
- Tier B has no kickoff, weather, officials or venue. Any split on those dimensions starts in 2010, and most start in 2015.
- Playoff games have no play-by-play. Their points and results are used; their play counts are not.
- 18 games (36 team-games) where the schedule and the crew list name different referees are resolved in favour of the crew
  list.
- Wikipedia's figures are secondary and approximate. Each row's source URL is in the CSV, so a figure can be checked and
  changed by editing one line and rebuilding.

## 7. Next

Player splits are the next piece: a job that reads the layer's player rows one player-season at a time, joins the same
team conditions, and writes a `player_split` table. The same engine runs on player rows, and the calendar, weather,
officials and capacity conditions come from the team rows above. Waiting on your direction before starting it.
