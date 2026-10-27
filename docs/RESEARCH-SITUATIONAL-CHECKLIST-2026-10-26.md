# NFL situational research checklist (2026-10-26)

Purpose: find out how circumstances change what teams and players do, how often events happen, and how those changes move
the final score. Investigate every measurable factor, and assume none has an effect until it is measured.

## Rules for every item

- [ ] Register the variable and its definition before looking at outcomes. No hand-picked multipliers in the simulator.
- [ ] Use the observed data for the cell. Where the cell is thin, borrow strength from a parent cell with explicit shrinkage,
      and label the fallback.
- [ ] Report for every estimate: sample size, numerator and denominator, historical window, fallback source, fitted value,
      and chronological evaluation (fit on earlier seasons, test on later ones).
- [ ] Control for team strength and situation before reading a factor as causal. Compare against the matched baseline.
- [ ] Respect the cutoff: a replay before a date may use only information known before that date.
- [ ] Keep the reserved 2026 two-point holdout unevaluated.
- [ ] Mark each item as data available, needs a source check, or needs an outside source.

## Data available locally (checked 2026-10-26)

- Play-by-play: nflverse parquet for 2022–2025 (`/root/nflverse-raw`, checksummed); local database `nfl_pbp` for 2010–2026
  (2026 through Oct 25). The database copy lacks kick, try, penalty-description and roof fields; the parquet has them.
- Regular-season games 2010–2025: 4,175 distinct game IDs (week ≤ 18), confirmed in the database.
- Schedule `nfl_schedule`: weekday, game time, rest days, roof, surface, temperature, wind, starting quarterbacks, coaches,
  referee, stadium, betting lines, division flag.
- Historical tables present, coverage not yet checked: `nfl_hist_injuries`, `injury_reports`, `nfl_hist_snap_counts`,
  `nfl_snap_counts`, `nfl_hist_participation`, `nfl_depth_chart`, `nfl_hist_depth_charts`, `nfl_hist_ftn_charting`,
  `player_game_logs`, `team_game_stats`, `team_game_results`, `nfl_elo_538`.
- Not in the play-by-play: injuries, snap counts, participation, depth charts. Those come from the tables above.
- Weather observations: the schedule carries temperature and wind per game. Humidity and forecasts are not checked.

## 1. Scheduling

- [ ] Monday vs Thursday vs Sunday, early vs late window, night vs day (data available: weekday, game time)
- [ ] Rest difference, short weeks, bye weeks (data available: rest days; bye needs a source check)
- [ ] Consecutive road games and travel distance (needs a source check: stadium coordinates)
- [ ] Thursday after a Sunday or Monday game (data available: schedule)

## 2. Team situation

- [ ] 2–4 vs 2–4, winning and losing streaks, divisional games, playoff implications (data available: prior results)
- [ ] Early season vs late season, and trend within a season
- [ ] Results against strength-matched opponents, not raw record (needs a strength rating: `nfl_elo_538`, check coverage)

## 3. Matchup

- [ ] Strong offense vs weak defense, pass rush vs offensive line, run defense vs rushing offense (data: team game stats)
- [ ] Prior meetings in the same season (data available: schedule)

## 4. Quarter and clock

- [ ] First quarter vs fourth quarter efficiency, opening drives, halftime adjustments (data available: play-by-play)
- [ ] Last two minutes of each half, timeouts, clock management (data available: play-by-play)
- [ ] Overtime: first-possession and choice effects (the coin toss table exists; see `overtime_coin_toss_2023_2026.csv`)

## 5. Score and pressure

- [ ] Tied, leading, trailing, one-score games, comeback situations, garbage time (data available: play-by-play)
- [ ] Efficiency by score state, controlling for game situation (down, distance, field position)

## 6. Quarterbacks

- [ ] Backup starts and mid-game quarterback changes (data: schedule quarterback names, play-by-play; check coverage)
- [ ] Returning starter and rookie starter (needs a source check: player logs)
- [ ] Quarterback performance by coverage or pressure (needs participation or charting: check coverage)

## 7. Injuries and availability

- [ ] Quarterback out, multiple offensive linemen out, receivers or defenders missing (needs injury tables: check coverage)
- [ ] Players returning from injury
- [ ] Injury effect on a single game's result: needs an injury source for each game, and an explicit model. Not a decision tree.

## 8. Field and stadium

- [ ] Grass vs turf, dome vs outdoors, retractable roof, home vs away, stadium-specific effects (data available: roof,
      surface, stadium)
- [ ] Players on turf vs grass, dome vs open stadium (data: play-by-play and player logs; check player-level coverage)

## 9. Weather

- [ ] Wind, rain, cold, heat, snow, humidity effects on passes, kicks, turnovers (data available: temperature and wind per
      game; rain, snow and humidity need a source check)
- [ ] Forecasts vs observations: a forecast is not an outcome. Use observed weather for estimation.

## 10. Fatigue and workload

- [ ] Defensive snaps accumulated in a game, consecutive drives, time of possession (data: play-by-play; snap counts need
      a check)
- [ ] Short-rest teams and fatigue after long games (data available: rest days)

## 11. Coaching decisions

- [ ] Fourth-down attempts, punts, field goals, two-point conversions, timeouts, onside kicks, overtime choices
      (data available: play-by-play)
- [ ] Field-goal attempts from 67 yards and beyond: attempt decision and make probability by distance (in progress)
- [ ] Overtime two-point decisions: conditional table (built, `try_fallback_2022_2025.csv`)
- [ ] Coin-toss kick-or-receive decision: observed table (2025 regular season: 10 kicks in 14 games; 2026: 4 in 6)

## 12. Player usage

- [ ] Snap share, target share, rushing share, substitution patterns (needs snap or participation tables: check coverage)
- [ ] Performance against a given opponent and coverage (needs player logs and charting)

## 13. Play design and defense

- [ ] Personnel packages, formation, route, coverage, pressure, rushing direction, explosive plays (needs participation
      and charting: check coverage; FTN charting table exists)

## 14. Special teams

- [ ] Field-goal distance, blocked kicks, punt returns, kickoff strategy, touchbacks, coverage efficiency (data available:
      play-by-play)

## 15. Rules and era

- [ ] Overtime format, kickoff rules, season-length changes, rule-based effects on play selection (rule-regime metadata:
      to be written from the rulebook for each season)
- [ ] Every rule-regime split is reported separately before any pooling

## Order of work

1. Confirm coverage of the historical injury, snap-count, participation and depth-chart tables before using them.
2. Finish the long field-goal and overtime-decision models (in progress).
3. Build the situational cells for scheduling, quarter, score and field, with shrinkage and chronological evaluation.
4. Add weather, fatigue and personnel after their sources are checked.
