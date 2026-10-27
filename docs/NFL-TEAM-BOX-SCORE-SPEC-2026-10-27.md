# NFL team box score and situational research: specification and status

Status: dev-only research on `research/nfl-historical-splits-2026-10-27`. It writes nothing to the dev database, changes
no production forecast, and does not touch the frozen Week 8 runs or any existing snapshot. The 2026 season is a sealed
holdout: 2026 games may be stored and described, but never used to confirm or tune a model.

Source: the expansion request pasted on 2026-10-27, written here so that the build order, the rules and the open
questions live in the repo. Sections 1 to 7 restate the request. Section 8 records what the probes have shown so far.

## 1. Goal

Make the full historical team box score the foundation of Legendary Picks' situational modeling system. The splits
should cover more than wins, losses and points. The question is how a team's style of play changes under different
conditions: play selection, offensive efficiency, possession counts, turnovers, drive success and scoring distributions,
after accounting for the opponent.

Build order:

1. Complete historical team-game box scores, as far back as the underlying data supports.
2. Situational splits across day, time, weather, stadium, capacity, officials, rest, travel and other game context.
3. A pregame situational state machine that assembles the relevant information for every upcoming matchup.
4. A tested team-strength model that learns from those situations and must show better out-of-sample predictions.
5. Individual player splits, with QB1, RB1 and WR1 availability, and later Madden ratings as experimental inputs.

Finish the team foundation before extending individual player splits.

## 2. Box score expansion

Stored play-by-play should be the primary source, with logs and game totals next. Derived totals are reconciled against
official box scores or gamebooks where possible. A missing or unreconstructable statistic stays null, never zero.

| Category | Historical team-game measurements |
|---|---|
| Results | W/L/T, points for and against, margin, points by quarter |
| Passing | Attempts, completions, passing yards, TDs, INTs, sacks, sack yards, yards per attempt |
| Rushing | Carries, rushing yards, TDs, yards per carry |
| Offensive efficiency | Total yards, yards per play, EPA per play, success rate, explosive plays |
| Possessions | Drives, points per drive, punts, three-and-outs, scoring drives |
| Situations | Third-down attempts and conversions, fourth-down attempts and conversions, red-zone trips and scores |
| Turnovers | Interceptions, fumbles, fumbles lost, turnover differential |
| Special teams | Field goals, punts, kickoffs, returns, return yardage |
| Penalties | Flagged, accepted, declined, offsetting, enforced yards |
| Game pace | Offensive snaps, drives, possession time where reliable |
| Context | Weekday, kickoff window, primetime designation, weather, roof, surface, referee and crew, stadium, attendance, capacity |

Historical range: the local layer covers 2010 onward. The public nflverse play-by-play archive reaches back to 1999 and
includes postseason data. That is a possible path to earlier seasons, but only after completeness and source terms are
checked. The window should never be presented as uniformly complete across every statistic.

Historical team-game box scores should start with every season in the database, 2010 through the completed 2026 games.
Investigate 1999 to 2009 as an optional expansion after the current coverage is validated, and keep the licensing and
source limits visible.

## 3. Situational context

Each box score joins to: day of week; kickoff time in ET, venue-local and team body-clock time; the actual broadcast
window (Monday, Thursday and Sunday night, international, normal Sunday); stadium, roof, surface, season-specific capacity,
attendance and attendance percentage when known; head referee and all available crew; observed temperature, wind,
precipitation and conditions where sourced; rest, travel, bye week, opponent, home or away, division, and rule regime;
and historical QB1, RB1 and WR1 identities with availability classes and source-confidence labels.

Attendance and actual weather are retrospective context. They are not pregame model inputs. Missing fields are kept,
and their denominators are kept with them.

## 4. Query engine

Any team's complete historical box-score distribution can be queried under one or several situational filters. Results
return the exact game IDs, sample sizes, win rates, points, yards, plays, turnovers, penalties, drives, efficiency,
averages, medians, quantiles and distributions, each compared with the team's overall baseline and its opponent-adjusted
baseline.

Example query: a team's rushing attempts, turnovers, drive count and scoring in domes versus outdoors in high wind,
compared with its opponent-adjusted baseline.

Combinations are computed on request. The engine does not materialize every Cartesian product. Sparse cells fall back to
hierarchical estimates: narrow combination, then team, then opponent, then league.

## 5. Game context contract

Three layers are kept separate and versioned.

- Pregame: information available at the frozen forecast cutoff. Kickoff, day, opponent, venue, rest, travel, published
  official assignments, the weather forecast, the expected roster, and prior team strength.
- In-game: quarter, down, distance, score, clock, possession, field position, personnel, drive history and workload.
- Postgame: the full box score, actual weather, attendance, final participation, officiating outcomes and player
  production. These are historical outcomes, used only for training and for evaluating future forecasts.

Every simulation references its immutable context snapshot, its model version and its rule-regime version. The simulator
will eventually consume the pregame layer and maintain the in-game layer. Postgame values never enter a forecast.

Hierarchical estimates replace one probability table per combination. A team, a Monday night, rain, 15 mph of wind, one
official and QB1 out may have no historical game at all, so the estimate must fall back to broader distributions.

## 6. Team-strength experiment

Compare progressively richer models on the same eligible games, with the same cutoff times:

| Model | Information |
|---|---|
| S0 | Existing Legendary Picks game-winner baseline |
| S1 | Opponent-adjusted strength, recent form, home or away |
| S2 | S1 plus calendar, kickoff window, rest and travel |
| S3 | S2 plus validated stadium, weather-forecast and officiating inputs |
| S4 | S3 plus frozen expected-starter availability |
| S5 | S4 plus player-strength priors, possibly including Madden ratings |

Each addition must show value on later games that were not used to select or tune it. Only strictly pregame features
enter a model. Betting odds never enter the independent model. Any comparison with a market belongs to a sealed
external evaluation layer.

Metrics: winner Brier score and log loss for the game winner; a distributional score (CRPS or another proper metric) for
scores and margins, since the binary Brier score does not apply to them; calibration; and game-level coverage. Ties need an
explicitly defined treatment. Report game-winner Brier by condition: Sunday early against primetime, high wind against
calm, confirmed QB1 against replacement QB. The reference points are a constant 50/50 forecast at 0.2500 and any lower
value as the goal.

Models are not promoted on retrospective correlations.

## 7. Madden ratings, later

Madden ratings are an experimental input. The first step is an inventory of season-matched historical ratings and their
attributes, with dates, IDs, source terms and coverage verified. The comparison asks whether cutoff-eligible ratings add
predictive information beyond historical football statistics. Madden coefficients are never inserted directly, and
current ratings are never substituted for past seasons. A rating revised after kickoff cannot enter an earlier forecast.

## 8. Status

### 8.1 What exists

- The team split store (`team_game_row`, 18,341 games, 36,682 team-games) covers results, weekday, kickoff windows,
  venue-local and body-clock windows, weather bins, referee and crew, stadium, dated capacity history and attendance.
- The splits layer (`team_game`) holds 8,940 completed 2010 to 2026 team-games with plays, yards, passing and rushing
  totals, EPA, success, sacks, turnovers and penalties.
- `nfl_team_game_totals` (2025 and 2026) holds carries, targets and air yards by team-week, from nflverse.
- `team_game_stats` holds ESPN team totals for NFL 2025 only (570 rows, 285 games). The seven keys are first downs, total
  offensive plays, total yards, net passing yards, rushing yards, turnovers and defensive special-teams TDs. No third downs,
  penalties or possession time are stored for NFL.
- No official gamebook or NFL box score is stored for any season.

### 8.2 What the probes have shown

Measured on the dev database's play-by-play, 2024 regular season unless stated.

- Kickoff plays carry the receiving team as `posteam`. The next play's `posteam` matches in 2,762 of 2,774 cases.
- `yards_gained` is 0 on every kickoff and every punt. Return yardage and punt yardage are not stored, so they stay null.
- The `success` flag on extra-point plays is 1 for 1,190 good kicks and 0 for 56 misses. That is a usable made-or-missed
  signal, to be reconciled against scores before it is trusted.
- Field goals made are the field-goal plays whose `series_result` is `Field goal` (14,033). Misses are `Missed field goal`
  (2,586). Other values on field-goal plays are rare and need care.
- `series_result` marks the last play of a series, not the scoring play. Drive outcomes must be grouped by `drive`.
- Drives average about 21.6 per game with both teams counted, which is plausible for the league.
- A third-down conversion by yards (`yards_gained >= ydstogo` or a touchdown) gives 2,750 of 6,828 attempts, about 40%.
  This is a derived definition, not an official one.
- Possession time can be approximated from `game_seconds_remaining` by drive. It is not validated, so it stays flagged.

### 8.3 Build order for this step

1. Write the team box-score schema and derive every field the play-by-play supports (this document, section 8.2 and the
   schema file that follows).
2. Reconcile derived totals against the 2025 ESPN team totals and against the schedule scores, and report match rates.
3. Report coverage by season for every field, with the denominator.
4. Write query examples on the box-score table, including the dome-versus-outdoor high-wind example.
5. Write the source-gap list.
6. Then write the situational state-machine contract and the incremental-Brier experiment plan as separate docs.

Model training waits until steps 1 to 5 pass. The 2026 holdout stays sealed throughout.
