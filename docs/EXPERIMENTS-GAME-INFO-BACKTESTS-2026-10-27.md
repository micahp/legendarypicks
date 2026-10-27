# Game-information experiments: guide and status (2026-10-27)

This is the guide for granular backtests of game information: stadium, seating, roof, surface, weather, kickoff day and
time, broadcast, attendance and referees. It lists every experiment we intend to run, what each one answers, how it is
scored, and where it stands. Nothing here changes the production model. A split that survives the decision rule becomes
a variant experiment behind an opt-in flag, and is promoted only after its own holdout.

## Rules that apply to every experiment

- Seasons 2022 to 2025, regular season only (1,087 games). **2026 is never read by a backtest.**
- No betting inputs. `spread_line`, `total_line` and the moneyline columns are never read.
- Outcomes are centred on the season mean. Team strength is removed with leave-one-out team-season points for and
  against, so a strong team's games cannot make a venue, broadcast or day look better or worse.
- Each effect is level minus every other game with a known level of that factor. 95% intervals from 2,000 bootstrap
  resamples within each side. p-values from 2,000 permutations of the level labels within the factor.
- Multiple comparisons: Benjamini-Hochberg across the whole test family of an experiment.
- Minimum sample: 40 games per level (30 for referees and venues).
- Holdout: refit on 2022 to 2024, report 2025 with its own interval. An opposite sign is reported as unstable.
- Decision rule: promote to a variant experiment only if q < 0.05, the holdout sign agrees, and the holdout interval is
  reported. q between 0.05 and 0.10 is reported as weak and not promoted. Anything else is no evidence.
- Observed weather (temperature and wind from the schedule) is the backtest input. Production uses a forecast, which is
  noisier, so every weather effect here is an upper bound on what a forecast-based input would show.

## Data used

| Source | Table or file | Coverage | Notes |
|---|---|---|---|
| Schedule (nflverse games) | `nfl_schedule` in picks.dev.db | 2010 to 2026 | roof, surface, temp, wind, referee, stadium, weekday, gametime (ET) |
| ESPN context | `nfl_game_context` | 2015 to 2025 | attendance, broadcast networks, venue, suspect flags |
| Penalties | `nfl_pbp_penalty` | 2022 to 2025 used | `penalty == 1` is a flagged play |
| Venues | `scratchpad/gameinfo2026/venues.json` (snapshot in `/root/lp-snapshots/nfl-game-info/`) | current | Wikipedia listed capacity (fetched 2026-10-27), OpenStreetMap coordinates |
| Forecast | `forecasts.json` (same snapshot) | week 8 2026 | National Weather Service forecastHourly, hour nearest kickoff, issue time kept |

Known data limits:
- Roof codes change across seasons (`outdoors`, `open`, `closed`, `dome`, blank). They are normalised to four groups.
- Listed capacity is today's figure, so attendance as a percentage of capacity is approximate for past seasons.
- The referee field is the head official only. Crew-level effects need `nfl_game_officials` (21,296 rows).
- Penalty counts are not yet residualised for team, so penalty experiments carry team tendencies.

## Experiments

Status key: **done** (run and reported), **planned** (not run), **blocked** (needs data or a decision).

### E0. Split screen on game information (done)

Question: which game-information levels move total points, home margin, penalties or penalty yards after team strength
is removed?

Factors: roof group, surface, observed temperature (outdoor only), observed wind (outdoor only), weekday, kickoff slot
(ET), first broadcast network, attendance as a share of listed capacity, referee, home venue.

Result (292 tests, `scratchpad/gameinfo2026/backtest/report.md`):
- **0 candidates at q < 0.10.**
- Smallest q: outdoor games, total points residual, -3.11 points [-4.74, -1.47], p = 0.0005, q = 0.146. 2025 holdout
  -1.50 [-4.69, +1.56] on 180 games. Same sign, interval includes zero. Keep as a reference for E2.
- Earlier raw-outcome run showed seven "candidates" (Detroit, Buffalo and New York venues, and attendance above listed
  capacity). They came from team strength, not from the stadium. Superseded by this run and not promoted.

### E1. Weather as an input, forecast versus observed (planned)

Question: how much of the outdoor effect survives when the input is a forecast issued before kickoff?

Needs: archived NWS forecasts issued at a fixed lead (for example 24 hours before kickoff) for past games. Not in the
DB yet. Without it, E1 cannot be scored. Blocked on the archive; the week 8 forecasts are the first capture of this
(snapshot date 2026-10-27).

### E2. Outdoor interaction: temperature by wind (done; the cell re-tested with team-adjusted penalties, see below)

Question: is the outdoor total effect concentrated in cold, windy games?

Method: cells of temperature (under 32F, 32 to 49F, 50 to 69F, 70F and up) crossed with wind (under 10, 10 to 14, 15
mph and up), outdoor games only, centred on team strength. Same decision rule, with cell minimum 40.

### E3. Venue altitude and home-field advantage (done, no candidates)

Question: does Denver show a home margin or total effect beyond team strength? Use the home-venue effect with a
shrinkage prior, because each venue has about 34 games in four seasons.

### E4. Referee crews (done, no candidates)

Question: do full crews (seven officials) move penalties, penalty yards or totals after team strength is removed?

Method: crew-level effects from `nfl_game_officials`, shrunk toward the league mean. Penalties residualised for team.
Target: crews with at least 30 games. Currently only the head official is tested (E0).

### E5. Kickoff slot by broadcast (done, no candidates)

Question: does the national-window effect (primetime, international early slot) survive once team strength is removed,
and is it different by network?

Method: slot by broadcast cells, team-residualised outcomes, decision rule as above. E0 tested the two factors one at a
time.

### E6. Attendance above listed capacity (planned)

Question: is the attendance effect real or a capacity artefact? Compare attendance against the capacity recorded for
each season, not today's listed figure. Needs historical capacity (blocked on a source per season).

### E7. Rest and travel (done, no candidates; not game information)

Question: how much of the day-of-week and slot effect is rest and time-zone travel? Uses `away_rest` and `home_rest`
from the schedule and the venue time zones in `venues.json`.

## Game-information inputs for the week 8 slate

Per-game inputs are recorded in the venue and forecast snapshots. Referees are not assigned in nflverse yet (checked
2026-10-27 18:39 UTC). Broadcast for the three national windows is confirmed from published schedules. The Sunday
CBS and FOX split is not confirmed for any game.

Not yet wired into the simulator. The inputs are recorded here and in the snapshot store. The model does not read them
until a variant experiment passes the decision rule.

## Changes this run made

- `scripts/nfl_sequence/game_info/build_venues.py`: venue table and geocoding.
- `scripts/nfl_sequence/game_info/fetch_forecasts.py`: NWS forecast per game.
- `scripts/nfl_sequence/game_info/backtest_splits.py`: E0 split screen with team-strength residuals.
- Outputs are written under the scratchpad, not the repository.

## First run of E2, E3, E4, E5 and E7 (2026-10-27)

Script: `scratchpad/gameinfo2026/run_experiments.py`. Outputs: `scratchpad/gameinfo2026/experiments/`. Each family is
controlled for multiple comparisons on its own. Same rules as E0. Team-strength residuals for total and margin;
penalties are raw (not yet adjusted for team tendency).

| Family | Tests | Candidates (q < 0.05 and holdout sign agrees) | Smallest q | Note |
|---|---:|---:|---:|---|
| E2 temperature by wind (outdoor) | 20 | 1 | 0.030 | penalties, 50-69F with 10-14 mph wind, see below |
| E3 venue, shrinkage in JSON | 120 | 0 | 0.060 | Detroit total residual +8.1 (weak, not promoted) |
| E4 officials | 464 | 0 | 0.249 | no official passes control |
| E5 slot by broadcast | 28 | 0 | 0.854 | no cell passes control |
| E7 rest and travel | 44 | 0 | 0.198 | none passes control |

E2 candidate, not promoted:
- Outdoor games at 50-69F with 10-14 mph wind: +2.18 flagged penalties, n = 42, q = 0.030.
- 2025 holdout: +2.65 penalties, interval [-0.32, +5.51], n = 8. The interval includes zero.
- Penalties are not yet adjusted for team tendency, so this may be team behaviour rather than weather.
- Next step before any further work: adjust penalties for team, then re-test this cell on the full 2022 to 2025 sample.

Still blocked: E1 (needs archived forecasts) and E6 (needs historical capacity by season).

## Re-test of the E2 penalty cell, team-adjusted, all four seasons (2026-10-27)

Script: `scripts/nfl_sequence/game_info/retest_penalty_cell.py`. Penalties and yards are adjusted for team tendency: each
team's leave-one-out season average of flagged penalties committed per game, summed over the two teams. The cell is
outdoor or retractable-open games at 50-69F with 10-14 mph wind: 42 games across 2022 to 2025.

| Outcome | Effect per game | 95% CI | p | q within family (10 tests) | q across all 970 tests run |
|---|---:|---|---:|---:|---:|
| Flagged penalties, team-adjusted | +2.38 | [0.95, 3.69] | 0.001 | 0.010 | 0.230 |
| Penalty yards, team-adjusted | +17.4 | [5.4, 29.7] | 0.008 | 0.038 | 0.230 |

Season by season (team-adjusted penalties; the cell against the other games that season):

| Season | Cell games | Effect | 95% CI |
|---|---:|---:|---|
| 2022 | 6 | +2.04 | [0.00, 4.17] |
| 2023 | 15 | +1.67 | [-0.58, 3.98] |
| 2024 | 13 | +2.15 | [-0.70, 5.16] |
| 2025 | 8 | +3.06 | [0.33, 5.49] |

Reading:
- The sign is positive in all four seasons, and the team adjustment changes almost nothing (raw +2.14 against +2.38).
- Within its own family the cell passes. Across every test in this guide, the q-value is 0.23, so it does not survive
  the full search. The cell was picked from data, which is the selection problem the wider control is there to catch.
- Per-season intervals are wide and only 2022 and 2025 exclude zero, narrowly.
- A confirmatory test needs games that have not been used. The only unused season is 2026, which is reserved as the
  holdout, so any confirmation needs a decision on that reservation.
