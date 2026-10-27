# NFL team box score: schema, coverage, reconciliation and source gaps

Status: dev-only research on `research/nfl-historical-splits-2026-10-27`. The box score is built by
`scripts/nfl_sequence/splits/team_box_build.py` into `/root/lp-snapshots/nfl-splits/team-box-2026-10-27/team_box.sqlite`
(schema `lp-nfl-team-box-1`). It reads the dev database and the splits layer read-only and writes nothing back. The
frozen Week 8 runs and existing snapshots are untouched. The 2026 season is not used to confirm anything.

This document is deliverables 1 to 5 of the expansion request in `NFL-TEAM-BOX-SCORE-SPEC-2026-10-27.md`: the schema,
the coverage audit, the reconciliation report, the query examples and the source-gap list.

## 1. Grain and scope

- One row per team per completed game in `team_box_score` (primary key `game_id, team`): 8,940 rows, 4,470 games.
- Regular season, 2010 to 2026 (8,564 team-games). 2026 covers weeks 1 to 7 only.
- Postseason, 2010 to 2025 (376 team-games). The play-by-play archive has no playoff games, so these rows carry only
  the base results (points, margin, result). Every play-derived field is null for them, by design.
- Context is not repeated here. It joins from `team_game_row` in the team splits store on `game_id, team`.

## 2. Schema

Derivation: every play-derived field comes from `nfl_pbp`, grouped by game and possession team (`posteam`). Penalty
yardage comes from `nfl_pbp_penalty` (2015 onward). The base results come from the splits layer. Null means the stored
data cannot support the value. It is never zero.

| Field | Meaning and derivation | Coverage (regular season) |
|---|---|---|
| `points_for`, `points_against`, `margin`, `result` | Final score from the schedule, and the W/L/T result. | 100% |
| `pts_derived` | Sum of scoring events on the play data (see section 4). Compare with the schedule score. | 100% (95.7% match) |
| `pts_residual` | Schedule points minus `pts_derived`. Zero for 95.7% of team-games. | 100% |
| `pts_q1` to `pts_q4`, `pts_ot` | Derived points by quarter, from the same events, by play quarter. | 100%, derived |
| `plays_off` | Pass and run plays, plus kneels and spikes. Sacks included. | 100% |
| `pass_att` | Pass attempts. Excludes sacks and two-point passes. Includes spikes. | 100% (matches the player logs in 8,560 of 8,564 games) |
| `pass_comp`, `pass_yds`, `pass_td`, `pass_int` | Completions, passing yards, passing TDs, interceptions thrown. | 100% |
| `sacks`, `sack_yards` | Sacks taken, and yards lost (positive). | 100% |
| `net_pass_yds` | `pass_yds` minus `sack_yards`. Matches ESPN net passing 99.8%. | 100% |
| `rush_att`, `rush_yds`, `rush_td`, `ypc` | Rushing, including QB kneels as the official stats do. | 100% |
| `total_yards`, `yards_per_play` | Sum of yards gained on pass, run and kneel plays, net of sacks. | 100% |
| `epa_per_play`, `success_rate` | Mean EPA and success flag over pass and run plays. | 100% |
| `explosive_pass`, `explosive_run` | Pass plays of 20 or more yards, and run plays of 10 or more. | 100% |
| `first_downs` | Pass and run plays that gained the distance or scored, plus penalty first downs awarded to the team. See section 5. | 100%, derived |
| `third_att`, `third_conv` | Third-down scrimmage plays, and those that gained the distance or scored. | 100% |
| `fourth_att`, `fourth_conv` | Fourth-down pass and run plays, and conversions by the same rule. Punts and field goals excluded. | 100% |
| `drives` | Distinct drive index with the team in possession and at least one drive play. | 100% |
| `points_per_drive` | `pts_for` divided by `drives`. | 100% |
| `scoring_drives` | Drives whose last result is a touchdown or field goal. | 100% |
| `punts`, `punt_drives` | Punt plays, and drives ending in a punt. | 100% |
| `three_and_outs` | Punt drives with at most three scrimmage plays and no first down. | 100% |
| `turnover_drives` | Drives ending in a turnover or a turnover on downs, or an opponent touchdown. | 100% |
| `rz_trips`, `rz_scores`, `rz_td` | Drives that reached the 20, those that scored, and those that ended in a touchdown. | 100% |
| `fg_att`, `fg_made`, `fg_missed` | Field goal plays, made (series result `Field goal`), missed. | 100% |
| `kickoffs_kicked` | Kickoffs by the team (the kicking team is the defense on the kickoff play). | 100% |
| `fumbles` | Offensive fumbles on pass and run plays. | 100% |
| `fumbles_lost` | Offensive fumbles lost on pass and run plays, plus fumbles lost on kickoff returns. | 100% through 2025, 0% for 2026 |
| `turnovers` | `pass_int` plus `fumbles_lost`. Matches ESPN turnovers 96.1%. | 100% through 2025 |
| `turnover_diff` | Opponent's turnovers minus own turnovers, in the same game. | Through 2025 |
| `pen_flagged` | Flagged penalties against the team (the play data does not record accept or decline). | 100% |
| `pen_yards` | Penalty yards flagged against the team, from `nfl_pbp_penalty`. Zero when no penalty is flagged. | 2015 to 2025 only |
| `possession_sec` | Derived from the game clock at each drive's first play, until the next drive starts. | 100%, unvalidated |
| `punt_yards`, `return_yards` | Not stored. The play data records zero yards on punts and kickoffs. | 0% |
| `pen_accepted`, `pen_declined`, `pen_offsetting` | Not stored. The play data flags a penalty without its outcome. | 0% |
| `offensive_snaps` | Not stored at team level. Use `plays_off`, or the snap counts for players. | 0% |

Coverage by era (regular season, share of team-games non-null):

| Field group | 2010 to 2015 | 2016 to 2020 | 2021 to 2025 | 2026 (weeks 1 to 7) |
|---|---|---|---|---|
| Plays, passing, rushing, sacks, EPA, success, explosive | 100% | 100% | 100% | 100% |
| Downs, drives, red zone, field goals, kickoffs, punts | 100% | 100% | 100% | 100% |
| Fumbles, turnovers, turnover differential | 100% | 100% | 100% | 0% (fumble-lost column null) |
| Penalties (count) | 100% | 100% | 100% | 100% |
| Penalty yards | 0% (not stored before 2015) | 100% | 100% | 0% (no 2026 penalty table) |
| Possession seconds | 100% (unvalidated) | 100% | 100% | 100% |

The per-season table is in the store (`team_box_coverage`, 1,054 rows: season by field, with the non-null count and the
denominator). Nulls that are structural (punt yards, return yards, accept and decline) read 0% in every season.

## 3. Reconciliation report

Each check compares a derived field with an independent source. Match means exact equality for the game. The store keeps
the per-season detail (`team_box_reconciliation`, 161 rows).

| Check | Source | Team-games compared | Exact match | Note |
|---|---|---|---|---|
| Points against the final score | `nfl_schedule` (regular season) | 8,564 | 95.7% | Residuals are mostly plus or minus 6, 4 and 2. See section 4. |
| Pass attempts | Player game logs, summed by team | 8,564 | 99.95% (8,560) | After excluding sacks and two-point passes, and adding spikes. |
| Passing yards | Player game logs, summed | 8,564 | 99.99% (8,563) | |
| Passing TDs, interceptions, sacks | Player game logs, summed | 8,564 | 100% (8,564) | |
| Rushing yards | Player game logs, summed | 8,564 | 99.7% (8,539) | |
| Rushing TDs | Player game logs, summed | 8,564 | 99.99% (8,563) | |
| Rushing attempts | Player game logs, summed | 8,564 | 95.1% (8,146) | Kneels are included. Remaining misses not explained. |
| Carries | `nfl_team_game_totals` (2025, 2026) | 758 | 95.0% (720) | |
| Net passing yards | ESPN team totals (2025) | 544 | 99.8% (543) | Only ESPN NFL team box in the store. |
| Rushing yards | ESPN team totals (2025) | 544 | 99.8% (543) | |
| Total yards | ESPN team totals (2025) | 544 | 90.1% (490) | Misses are exactly 2 yards, in 47 games. Cause not determined. |
| Total offensive plays | ESPN team totals (2025) | 544 | 81.2% (442) | Spikes and kneels counted; the rest not explained. |
| Turnovers | ESPN team totals (2025) | 544 | 96.1% (523) | Kickoff-return fumbles added. |
| First downs | ESPN team totals (2025) | 544 | 67.3% (366) | Median gap 0. See section 5. |

What the reconciliation shows:

- The play-to-game mapping is sound. Passing and rushing yards, touchdowns, interceptions and sacks agree with the player
  logs almost everywhere, and net passing yards agree with ESPN.
- The disagreements that remain are definitional, and each one is documented where it is defined. None of them is a
  dropped play.
- Official gamebooks are not stored, so there is no reconciliation source for 2010 to 2024 team totals other than the
  player logs. ESPN's team box exists only for 2025, and only for seven keys.

## 4. Points: how they are derived and where they miss

Scoring events are read from the plays: an offensive touchdown on a pass or run is 6. A defensive touchdown (interception
or fumble lost returned for a touchdown) is 6 to the defense. A made field goal (series result `Field goal`) is 3. A good
extra point (`success = 1`) is 1. A successful two-point play is 2 (two-point plays have no touchdown flag, so this is
counted on its own). A safety is 2 to the defense. A kickoff return touchdown goes to the receiving team, and a punt
return touchdown to the defense.

The residuals (schedule minus derived, regular season, 8,564 team-games): 0 in 8,200 team-games; plus or minus 6 in 154;
minus 4 in 60; minus 2 in 56; plus 3 in 41; plus 2 in 19; minus 8 in 23. The likely causes are touchdowns on special-teams
and defensive returns that the play data attributes to the other side, and extra points after those touchdowns. They
spread evenly across seasons, between 16 and 29 team-games a season. The schedule score stays authoritative. Derived
points are used only for the quarter and scoring-type breakdowns.

## 5. First downs: how they are derived and where they miss

First downs are pass and run plays whose gain reached the distance, plus penalty first downs. The play data has no
penalty first-down flag on the play itself, so the penalty count comes from `nfl_pbp_penalty`, credited to the team that
gained it (the other team). That count includes penalties that were declined, because the data does not record the
decision. The total is therefore an upper bound on the penalty component.

Against ESPN (2025, 544 team-games), our count is higher in 172 games (by one in 131, by two in 30, by three or four in
11), lower in 6, and equal in 366. The excess fits declined penalties, which the data cannot separate: a penalty that was
declined still carries the first-down flag. The method is therefore an upper bound on the penalty component. First downs
stay derived, labelled as such, and are not used as a verified field until the decision flag is available.

## 6. Query examples

Dome versus outdoors in high wind, for Buffalo, regular season, with the team and league baselines:

```
python3 team_box_query.py --team BUF --where roof=dome --fields rush_att turnovers drives pts_derived
python3 team_box_query.py --team BUF --where roof=outdoors --where wind_bin=20mph_plus --fields rush_att turnovers drives pts_derived
python3 team_box_query.py --team BUF --where roof=outdoors --where wind_bin=20mph_plus --games
```

Results on the current build (19 dome games, 12 outdoor games with wind of 20 mph or more):

| Field | Dome: mean (median) | Outdoors, wind 20+: mean (median) | Buffalo all games | League all games |
|---|---|---|---|---|
| Rushing attempts | 28.1 (29) | 29.8 (25) | 28.7 | 26.8 |
| Turnovers | 1.65 (2), 17 games | 0.92 (1) | 1.4 | 1.35 |
| Drives | 11.1 (11) | 11.9 (12) | 11.4 | 11.4 |
| Points (derived) | 28.5 (31) | 27.2 (24.5) | 24.2 | 22.8 |

The dome sample has two games with null turnovers (2026, fumbles unknown), which the tool reports rather than counts as
zero. These numbers are descriptive. They are not adjusted for opponent.

The same query form works for any team and for any combination of the dimensions in the team splits store: weekday,
kickoff window, roof, temperature and wind bins, referee, official, stadium, capacity source and attendance share.

## 7. Source-gap list

Each gap names the field it blocks and the source that would close it. None of these has been fetched.

1. Official gamebooks or NFL team box scores for 2010 to 2025 are not stored. This blocks any reconciliation of team totals
   beyond the player logs. A source needs a license review first.
2. Punt yardage and return yardage. The stored play data has zero yards on punts and kickoffs. The public nflverse
   play-by-play archive carries these fields. Re-ingesting them would need approval and a source-terms check.
3. Accepted, declined and offsetting penalties. The stored data flags penalties without their outcome. The same nflverse
   archive has the penalty detail. This blocks a penalty audit and the first-down decision.
4. Possession time. The derived value is unvalidated. Official time of possession is not stored for NFL.
5. 2026 fumbles lost. The stored fumble-lost column is null for every 2026 play. This blocks 2026 turnovers and turnover
   differential, and is the only reason those are null for 2026.
6. Postseason play-by-play. Playoff games have no play data, so their play counts, drives and penalties are null. This
   blocks postseason team splits that go beyond points and results.
7. Penalty yardage before 2015 and for 2026. Not in the stored penalty table.
8. Officials before 2015, and the 2026 crew. Only 16 of 272 games have a crew list for 2026 so far.
9. Team-level snap counts. Offensive snaps are not stored at team level. The player snap counts would need summing.
10. Points by quarter. Derived, with a residual. Official quarter scores are not stored.
11. Team statistics from ESPN for NFL, 2025 only, seven keys. No third downs, penalties or time of possession.
12. Historical play-by-play from 1999 to 2009 (nflverse). An optional expansion after this coverage is validated. It needs a
    source-terms and licensing check before any ingest.
13. Madden ratings. Not inventoried. The inventory step is in the experiment plan.

## 8. What comes next

The schema is ready for the situational join. The next deliverables are the situational state-machine contract and the
incremental Brier experiment plan, written as separate documents. No model is trained until those are reviewed.
