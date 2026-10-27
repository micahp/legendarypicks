# NFL historical splits: audit, layer, queries, and Week 8 context

Status: dev-only research on `research/nfl-historical-splits-2026-10-27`. It writes no table in `picks.dev.db`, changes no
simulator default, promotes no model, and calls no external service. Descriptive splits are information. None of them
feeds a simulation or a projection.

Commits: `9088e92c` (layer, query module, tests, audit script), `524f2f3a` (Week 8 context attachment), and this doc.

## 1. What was built

| Piece | Where | What it does |
|---|---|---|
| Layer builder | `scripts/nfl_sequence/splits/layer.py` | Reads `picks.dev.db` read-only and writes a new SQLite file. Refuses to overwrite. |
| Layer file | `/root/lp-snapshots/nfl-splits/layer-2026-10-27/splits_layer.sqlite` | 8,940 team-game rows (4,470 games), 294,286 player-game rows, 25,692 role rows, 21,296 official rows |
| Query module | `scripts/nfl_sequence/splits/splits_query.py` | Read-only team and player splits with filters, exact game IDs, sample warnings, missing-class counts, baselines |
| Coverage audit | `scripts/nfl_sequence/splits/audit_coverage.py` | Per-season counts and join checks, computed at run time |
| Tests | `scripts/nfl_sequence/splits/test_splits.py` | 23 unit tests: clock, usage ties, status classes, weather rules, query rules |
| Week 8 context | `scripts/nfl_sequence/splits/week8_context.py` | Attaches cutoff-safe history to the 14 frozen Week 8 games |
| Week 8 output | `/root/lp-snapshots/nfl-splits/week08/2026-10-27/historical_context.json` | `used_by_model: false`; no simulation run or snapshot is read for writing |

Layer tables: `team_game` (one row per team per completed game, with calendar, kickoff windows, venue, weather,
officials and outcomes from `nfl_pbp`), `game_official`, `player_game` (from `player_game_logs`, with snaps and counting
stats), and `team_role` (QB1, RB1 and WR1 for each regular-season team game, with how the role was identified and
whether that player played).

Source fingerprint: `picks.dev.db` is written by live ingests, so a whole-file hash changes between builds. The first
build hashed `298fb6aca746`, and the build at the committed code hashed `1d56ed29ce0f`. Both builds produced identical
row counts for every layer table. The layer records its source hash, but the stable check is the row counts above.
Re-run `audit_coverage.py` before quoting any number from a later build.

## 2. Coverage and join audit

Measured by `audit_coverage.py` against the dev database (counts, not table presence).

| Source | Seasons with data | What it does and does not cover |
|---|---|---|
| `nfl_schedule` | 2010 to 2025 complete; 2026 has 272 scheduled and 107 scored | Day, kickoff, roof, surface, referee, stadium. Temp and wind are observed. |
| Outdoor weather (scored regular-season outdoor games) | At most 2 missing a season from 2015 to 2021; missing 81 of 177 (2022), 30 of 180 (2023), 5 of 178 (2024), 4 of 180 (2025), 26 of 69 (2026) | Dome and closed-roof games have null weather by design. Outdoor nulls are real gaps. |
| `nfl_pbp` | Regular season 2010 to 2025 complete (256 to 272 games a season; 2022 has 271); 2026 has 107 games | No playoff games. In 2026, `fumble_lost` is null on every play, so 2026 fumbles are unknown while interceptions are known. |
| `nfl_pbp_penalty` | 2015 to 2025 | Flagged penalties only; no accepted, declined or offsetting split. Team codes LA and WAS, mapped to LAR and WSH. |
| `nfl_game_officials` | 2015 to 2025 complete (seven positions per game, with 11 exceptions in 2024 and 1 in 2022); 2026 has 16 of 272 games | Nothing before 2015. Week 8 2026 has no assignments. |
| `nfl_game_context` | 2015 to 2025 (venue state, city, attendance, broadcast) | No 2026 rows. 44 games with a null venue state were played outside the US. |
| `player_game_logs` (nflverse weekly) | Regular season 2010 to 2026 (282,236 rows); postseason 2010 to 2025 | Stat keys include attempts, yards, targets, carries, dropbacks. Snaps are inside the JSON only from 2024 (partial for 2024). |
| Snap counts | `nfl_hist_snap_counts` 2013 to 2025 (keyed by pfr ID); `nfl_snap_counts` 2024 to 2026 (keyed by LP player ID) | None before 2013 (2010 to 2012 have log presence only). The two 2024 to 2025 sources have different row counts (50,701 vs 53,228) and are not reconciled. The layer uses `nfl_snap_counts` from 2024. |
| `player_game_availability` | Rows 2010 to 2026 | `played` and `reason` are populated for 2024 to 2026 only. For 2010 to 2023, `played` is null on every row. |
| `nfl_hist_depth_charts` | 2010 to 2024 (regular season and playoffs, weeks 1 to 22) | No 2025 rows. |
| `nfl_depth_chart` | 2026 only: four snapshots (2026-07-27, 07-28, 10-05, 10-19) | Not weekly. |
| `injury_reports` (nfl) | 2024 to 2026 | `date_modified` exists for 2024 only, so 2025 and 2026 report timing is unknown. |
| `nfl_hist_injuries` | Regular season 2009 to 2025 (weekly, with report and practice status) | No 2026 rows. |
| `nfl_hist_participation` | 2016 to 2025 (plays with personnel) | Not used in v1. |
| `nfl_team_game_totals` | 2025 and 2026 only | Not used in v1. |
| `team_game_results` | All leagues; 2026 includes `scheduled` rows | Filter on `status = 'completed'`. |

Join checks (measured):

- `player_game_logs.game_id` matches `nfl_schedule.game_id` for every row, every season.
- Logged NFL player IDs resolve to `players.id` for 7,998 of 7,999 players. 7,997 have a GSIS ID. 98 logged rows have no GSIS ID and cannot be role-classified.
- `nfl_hist_depth_charts` GSIS IDs all resolve to `players.nfl_gsis_id` for 2024.
- `nfl_hist_snap_counts` pfr IDs resolve through `nfl_hist_player_ids` for 99.8% of 2024 rows.
- Team codes are consistent: schedule and play-by-play use LAR and WSH in every season. Only the penalty tables use LA and WAS.
- `players.nfl_gsis_id` is the bridge from logs to roles and snaps.

Findings that change the design:

1. The existing with/without module cannot answer history before 2024. Measured on Josh Allen and Stefon Diggs,
   2022: `player_splits.py` classified all 16 Buffalo games as unknown (0 matched, 0 not matched). The same question
   on the layer, with snaps from `nfl_hist_snap_counts`, returns 16 games with Diggs present, averaging 268 passing
   yards. In 2025 the existing module works.
2. Depth charts do not give a single WR1. In regular seasons from 2010 to 2024, a team-week has exactly one depth-1
   QB 99.8% of the time (8,622 of 8,641), one depth-1 RB 89% of the time (7,721 of 8,632), and two or more depth-1
   WRs 98% of the time (8,555 of 8,695). WR1 needs a tie-break from prior usage.
3. 2025 and 2026 have no weekly depth chart in the stored data, so role identity there is usage-based.
4. Retrospective absence reasons exist only for 2024 onward (official inactive labels, injury-out labels) and for
   2009 to 2025 in the historical injury report. Before 2024 an absent player is `absent_no_reason` unless a report
   names him.
5. Playoff games have no play-by-play, so their play, penalty and turnover fields are null in the layer. Playoff
   scores are present.

## 3. How QB1, RB1 and WR1 were identified

Two different questions are kept apart.

- Retrospective availability (what the layer stores): for a team game, was the role player identified as the expected
  starter, and did he play? This is what the history shows.
- Pregame expectation (what a simulator would need): the expected starter known before kickoff. The layer does not
  claim this for history. For 2026 it is available only through the frozen snapshots collected from Week 8 onward.

Identification order, for each regular-season team game, for QB, RB and WR:

1. Candidates are the offense depth-1 players of that position in the historical depth chart for that season, week and
   team (2010 to 2024).
2. One candidate: that player is the role (`depth_chart_week`).
3. Two or more candidates (a tie): the candidate with the most prior-game usage is the role
   (`depth_chart_week+prior_usage`). The usage metric is dropbacks for QB, carries for RB and targets for WR. If the top
   two candidates tie, or nobody has usage, the role is `tie_unresolved` and nothing is guessed.
4. No depth row (2025, 2026): the role is the position's leader in prior usage (`usage_prior_3g`).
5. No prior games in the season (week 1): the role is `no_prior_usage` and unidentified.

Prior usage is the team's last three regular-season games before the game being classified. No role reads the game it
describes. WR1 is never defined by the target game's receiving production or by season totals.

Counts (regular season):

| Era | Identified by | Count |
|---|---|---|
| 2010 to 2024 | `depth_chart_week` | 14,758 |
| 2010 to 2024 | `depth_chart_week+prior_usage` | 7,712 |
| 2010 to 2024 | `tie_unresolved` | 826 |
| 2010 to 2024 | `usage_prior_3g` | 113 |
| 2010 to 2024 | `no_prior_usage` | 9 |
| 2025 to 2026 | `usage_prior_3g` | 2,047 |
| 2025 to 2026 | `no_prior_usage` | 227 |

Status classes, recorded with the source of the reason:

| Status | Meaning | Reason source |
|---|---|---|
| `played` | Logged, with snaps above zero or with snaps unknown | snap source named in the row |
| `officially_inactive` | Labelled inactive without an injury report (2024 onward only) | `player_game_availability.reason` |
| `injured` | Out, doubtful or questionable on a report, or injury-out reason | availability reason, or `nfl_hist_injuries` |
| `absent_no_reason` | Not logged, or logged with zero snaps, and no reason on record | none (never classed as healthy) |
| `unidentified` | No role identity for the game | identification reason |

Counts by era, regular season: 2010 to 2023 played 19,171, injured 1,246, absent_no_reason 587, unidentified 782.
2024 to 2026 played 3,271, officially_inactive 93, injured 167, absent_no_reason 95, unidentified 280.

Known limits of this identification:

- The depth chart is a prior, not a verified starter. CAR 2024 week 8 lists Andy Dalton as QB1, and his report says
  Doubtful. The layer records him as `injured`, which is what happened.
- Usage-based identity can name the wrong player for a game. Josh Allen's "QB1 not played" universe contains one game
  where he logged a line, which means the QB1 was misidentified there. Role statuses are research labels, not facts.
- The layer does not classify roster eligibility, because no stored table records it.

The Week 8 expected QB1 is different. It comes from the frozen full-depth roster (starter True), and the frozen
availability decision applies the same rule the simulator uses: if the QB1 is excluded, the best available QB2 takes the
role. KC_DEN and PHI_WAS have no frozen roster, so their QB1 history is not attached. NE_MIA has a frozen roster but a
blocked simulation, so its QB1 history is attached and the output carries the sim status.

## 4. Query module

Filters, all optional, all combinable (no materialized product):

- Calendar: season range, game type (REG by default, POST, ALL), weekday, kickoff window in Eastern (`window_et`),
  kickoff window in venue-local time (`window_venue`), kickoff window in the team's home-zone clock (`window_body`).
- Venue: roof, surface, international, home or away, opponent, division.
- Officials: referee, or any named official.
- Weather: temperature and wind bounds. These apply to outdoor games only. Dome games are excluded, not counted
  missing. Outdoor games with no recorded value are counted as missing.
- Roles: `QB`, `RB` or `WR` with any of `played`, `injured`, `officially_inactive`, `absent_no_reason`,
  `unidentified`, or `not_played` (any absence).
- Teammate: a named player played or did not play, counting only seasons in which he was on that team.
- Expected starter: a named player was the identified starter and played (`available`), was the identified starter
  and did not play (`unavailable`), or someone else was (`other`).

Every result lists: games, wins, losses, ties, win percentage with a Wilson 95% interval, points, margin with standard
error, yards and plays, yards per play, EPA per play, success rate, sacks, turnovers, penalties and penalty yards, the
exact game IDs, the seasons covered, the missing-classification games, and `shrinkage: none (raw)`. Warnings: `very_thin`
below 3 games, `thin` below 8. Baselines: the team's games in the same seasons with no filters, the league's games in
the same seasons, and the team's season-by-season split. Player results show per-game mean, median, quartiles and
maximum, with played games, missed games, and logged zero-snap games counted separately.

Examples:

```
python3 splits_query.py team --team BUF --weekday Sunday --window_et early --home_away home
python3 splits_query.py team --team PHI --weekday Sunday --window_et primetime --role WR=not_played
python3 splits_query.py player --gsis 00-0034857 --teammate 00-0031588=played --season_from 2022 --season_to 2022
```

## 5. Examples: three Week 8 matchups

These are descriptive history. They are not model inputs. Numbers are from the committed code on the layer above.

### BAL at BUF (Sunday 1:00 PM ET, Buffalo home, outdoors, forecast wind 3 mph, 64 F)

- Buffalo, same weekday, kickoff window and home role: 102 games, 65-37 (63.7%, 95% interval 54.1% to 72.4%), margin
  +3.9 (standard error 1.5), EPA per play 0.024, yards per play 5.68.
- Buffalo outdoor games with wind 15 mph or more: 45 games, 28-17 (62.2%), margin +4.3 (standard error 2.2). Wind under
  15 mph: 177 games, 96-81 (54.2%), margin +1.5 (standard error 1.2).
- Josh Allen as the identified starter who played: 128 games, 90-38 (70.3%), margin +7.5 (standard error 1.2), EPA per
  play 0.102. When he was the starter and did not play: 3 games (thin), 1-2. When someone else was the starter: 133
  games, 56-77 (42.1%), margin -2.9.
- Baltimore, same weekday, window and away role: 71 games, 37-34 (52.1%), margin +3.5 (standard error 1.7).
- Lamar Jackson as the identified starter who played: 104 games, 74-30 (71.2%), margin +8.4. When he was the starter and
  did not play: 12 games, 5-7 (41.7%), margin -1.5. Someone else was the starter: 150 games, 84-66 (56.0%), margin +2.9.

### CAR at GB (Thursday 8:15 PM ET, Green Bay home, outdoors, forecast wind 2 mph, 56 F)

- Carolina, Thursday primetime: 13 games, 4-9 (30.8%), margin -6.1. Carolina as the away team on Thursday primetime: 6
  games (thin), 2-4.
- Green Bay, Thursday primetime, home: 12 games, 7-5 (58.3%), margin +4.7 (standard error 4.6).
- Green Bay outdoor games with wind 15 mph or more: 24 games, 14-10 (58.3%), margin +1.8. Under 15 mph: 180 games,
  124-54-2 (68.9%), margin +5.5.
- Bryce Young as the identified starter who played: 39 games, 13-26 (33.3%), margin -6.7. Someone else was the starter:
  221 games, 99-121-1 (44.8%), margin -1.7. When Young was the starter and did not play: 4 games (thin), 1-3.
- Jordan Love as the identified starter who played: 53 games, 30-22-1 (56.6%), margin +3.6. Someone else was the
  starter: 208 games, 135-71-2 (64.9%), margin +4.0. When Love was the starter and did not play: 5 games (thin), 3-2.

Note that "someone else was the starter" for Love includes his seasons as a backup in 2020 to 2022, so the comparison
is not a clean starter-versus-backup test. It is shown because the request asks for it, and the sample is the
descriptive question, not the causal one.

### PHI at WSH (Sunday 8:20 PM ET; simulation blocked, no frozen roster)

- Philadelphia, Sunday primetime: 32 games, 20-12 (62.5%), margin +3.3, EPA per play 0.03.
- Philadelphia, Sunday primetime, when the identified WR1 did not play: 5 games (thin), 3-2, margin +0.6.
- Philadelphia, Monday games, when the identified WR1 did not play: 2 games (very thin), 0-2, margin -7.5.
- Philadelphia over its whole regular-season history: 268 games, 56.7% wins. League margin across all teams: 0.0
  (a sanity check that every game is counted once per team).

The request asks for the WR2 and tight end split with WR1 out. The layer identifies WR1 only. WR2 and tight end need the
same identification (a second receiver and a tight end role), which is not built, and the number of Philadelphia
Monday games with WR1 out is 2. This example shows the limit, not an answer.

## 6. Week 8 attachment

`historical_context.json` covers the 14 frozen Week 8 games.

- Cutoff: the manifest `as_of_utc`, 2026-10-27T18:20:23Z. Every history game used has kickoff before this time. The
  check runs per split (`assert_before_cutoff`), in chunks, and fails on any violation.
- Per team: calendar split (weekday; weekday and window; weekday, window and role), outdoor wind split beside the frozen
  forecast wind, and the expected QB1 split (available, unavailable, other).
- Forecasts: wind and temperature from the frozen NWS forecast in the 2026-10-27 game-information snapshot. The roof
  labels are mapped to the layer's vocabulary (`Open` is open-air, so `outdoors`). Retractable-roof games carry no
  weather split. The historical wind is observed, not forecast, which is a comparability caveat.
- Officials: not assigned for any Week 8 game in the stored data, so no official split is attached.
- Not attached: QB1 history for KC_DEN and PHI_WAS, which have no frozen full-depth roster. NE_MIA has a frozen roster
  but a blocked simulation; its history is attached and its `sim_status` is `error`.

## 7. Missing data and ESPN

Missing data, with what each gap blocks:

1. Weekly depth charts for 2025 and for 2026 weeks 1 to 7. Blocks depth-based roles for those seasons.
2. Depth-chart publication time for 2010 to 2024. Blocks a pregame claim for any historical role.
3. Official inactive lists before 2024. Blocks official-inactive splits before 2024.
4. Injury report timestamps for 2025 and 2026, and for 2024 the report timing is recorded only as `date_modified`.
   Blocks any pregame classification of injury status.
5. Snaps before 2013, and reconciliation of the two 2024 to 2025 snap sources.
6. Officials before 2015, and for 2026 (16 of 272 games assigned so far; none for Week 8).
7. Outdoor temperature and wind for 2022 and 2023 (81 and 30 outdoor games missing), and for 2026 (26 of 69). Blocks
   weather splits for those games.
8. Venue state before 2015, and a stadium capacity or time-zone reference table in the layer. Venue-local and
   body-clock windows are missing for 2010 to 2014.
9. Archived forecasts with issue times. Blocks E1 (weather forecast skill) and any forecast-based split.
10. Playoff play-by-play. Blocks playoff team efficiency and penalties.
11. 2026 fumbles lost. Blocks 2026 turnovers.
12. Accepted, declined and offsetting penalty flags. Blocks a penalty audit.
13. Absence reasons for non-role players. The layer records reasons only for QB1, RB1 and WR1. A player split reports
    missed games without a reason.
14. WR2, tight end and other role identities. Blocks the example the request asks for.

ESPN: this session did not call ESPN. The request asked for an evaluation of the athlete splits endpoint before any
ingest. That needs a probe under the ESPN request-budget rules: the limit is a per-host burst rate, so the probe must be
paced and counted, and it needs your go-ahead first. Fields worth testing for acquisition, if the probe
confirms coverage: athlete splits by day, month, home and away, surface, outdoor conditions, weather and starter status,
for 2010 to 2026 where it exists; kickoff and primetime flags; and official crew, if published. Each would be compared
with the stored data before any ingest. Nothing is ingested.

## 8. Proposal: how validated splits could condition the simulator

Stage 1 (now): descriptive only. Splits appear beside a frozen run as context, with `used_by_model: false`. No
simulator input changes.

Stage 2 (research): a split becomes a candidate effect only after its estimate survives the controls the repo already
uses. Adjust for team strength by residualizing against the team's season and opponent baseline. Use leave-one-team-out
or leave-one-season-out estimates. Test chronologically (rolling origin), never on 2026 holdout data. Shrink toward
zero with a stated prior and report the shrinkage. Cluster standard errors by team-week. Correct across the family with
Benjamini-Hochberg, and pre-register each family before running it.

Stage 3 (opt-in variant): a validated, shrunk effect enters the simulator through a named variant, off by default. It
shifts play-type rates for the affected team, and the run record names the variant. Production defaults do not change.
Roles for any conditioning come from frozen pregame snapshots only. Retrospective roles from this layer are for
research. Weather conditioning waits on E1 (archived forecasts with issue times).

Gate for Stage 3: the effect has the same sign and a usable magnitude in at least two independent seasons blocks after
adjustment, the shrunk estimate clears its family correction, and the variant improves a pre-registered score on the
rolling-origin test. Failing any gate keeps the split descriptive.

## 9. Verification

- Unit tests: `python3 -m unittest test_splits`, 23 tests, all passing on the committed code.
- Layer counts: 8,940 team-game rows (8,564 regular season and 376 postseason), 294,286 player-game rows (282,236
  regular season and 12,050 postseason), 25,692 role rows (three per regular-season team game).
- Points: every team-game's points match `nfl_schedule` scores. Win, loss and tie are symmetric in every game.
- Monday games: Buffalo's 16 Monday regular-season games match an independent query on the schedule (margin 85 in both).
- Early window: Buffalo's early count is 185 in the layer and 183 by a raw clock-text count on the schedule. The two
  extra games kicked off at 9:30 AM ET in London (2015 and 2023), which the layer counts as early by design.
- Yards: Buffalo's 2025 week 1 game (`2025_01_BAL_BUF`) has 502 yards and 77 plays, matching the play-by-play.
- Passing: Josh Allen's 2025 passing yards are 3,668 from the raw stat JSON and from the layer.
- Role identity: CAR 2024 week 8 matches the depth-chart query (Andy Dalton, depth 1).
- Not verified: a live ESPN probe, any archived forecast, and whether the usage-based identity is right for 2025 and 2026
  beyond the cases above.

## 10. Open items

- Run `audit_coverage.py` again after the next dev ingest, and record the row counts in this doc.
- Chronological team tendencies, the penalty audit (accepted, declined, offsetting), and team clustering: not started.
- WR2 and tight end identities for the PHI example: not built.
- Absence reasons for non-role players: not built.
- E1 (archived forecasts) and E6 (capacity history): not started. E1 is the next research item the request names.
