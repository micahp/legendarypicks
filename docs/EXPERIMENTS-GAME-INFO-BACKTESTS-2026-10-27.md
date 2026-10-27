# Game-information experiments: guide, rules and status (2026-10-27, revised)

This is the guide for granular backtests of game information: stadium, seating, roof, surface, weather, kickoff day and
time, broadcast, attendance, referees, and rest and travel. Experiment IDs and the status vocabulary follow the situational
research matrix. Nothing here changes the production model. A result becomes a variant only after the adoption gates in the
strategy document.

Governing documents on `dev`:
- Situational research matrix (investigation registry, rules, required outputs):
  `docs/research/NFL-SITUATIONAL-RESEARCH-MATRIX-2010-2026.md`. Matrix IDs below refer to it.
- Granular modeling strategy, section 7 (research design), section 13 (workflow phases A to G), section 16.7 (order R5):
  `docs/STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md`.

## 1. Rules applied to every experiment

These are taken from the matrix rules and strategy section 7. Where our work does not yet meet a rule, the experiment
section says so.

- **R1. Cutoff classification.** Each input is classed (a) strict as-of observed, (b) retrospective date-filtered, or
  (c) unavailable. Only (a) supports a fair forecast comparison. (b) and (c) support exploratory research only.
- **R2. Chronology.** Split by season or game date, never by play. Rolling-origin folds. All rows of a game sit in one fold.
- **R3. Pre-registration.** The feature, comparison and expected outcome are registered before the scoring run.
- **R4. Selection versus confirmation.** A tested period becomes development data. Confirmation needs a reserved, unused period.
- **R5. Uncertainty.** Game-level resampling, and team clustering where teams repeat across games. Disclose the method.
- **R6. Sparse cells.** Hierarchical fallback or shrinkage, with effective sample size recorded. Never read 0 or 1
  observations as a rate.
- **R7. Causal language.** Report associations. "Monday" or "turf" correlations are not causal effects (matrix, Causality).
- **R8. Regimes.** Report rule regimes separately before pooling. The 2024 and 2025 kickoff rule shifts (matrix ST-01) make
  kickoff and total-point results regime-dependent.
- **R9. Sealed holdout.** The 2026 reserved holdout is not read by any experiment here.
- **R10. No betting inputs.** No spread, total, moneyline or implied-probability column is read.
- **R11. Vocabulary.** `hypothesis`, `supported`, `null`, `rejected`, `insufficient_data`. "Candidate" is retired.

Compliance today: partial. Single-season holdouts (R2), no pre-registration (R3), team clustering absent (R5), some cells
unshrunk (R6), and observed weather used as an input-like split (R1) are the main gaps. They are listed per experiment.

## 2. Input classification (R1)

| Input | Source | Class | Note |
|---|---|---|---|
| Weekday, kickoff slot (ET), rest days | `nfl_schedule` | (a) | Known from the published schedule and prior game dates. Prior results are used only after they are final. |
| Stadium identity, listed seats | `nfl_schedule`, venue snapshot | (a) | Fixed for the season. Listed seats are today's figure, so (b) for past seasons. |
| Roof, surface | `nfl_schedule` | (a) for the scheduled roof | Retractable roof state at kickoff is not known from the schedule. |
| Referee assignment | `nfl_schedule.referee`, `nfl_game_officials` | (b) for past games | Stored values are final assignments. Week 8 crews are not assigned yet. |
| Broadcast network | `nfl_game_context` (ESPN) | (b) for past games | `broadcast_known_at` exists in the table. Week 8 national windows need a recorded publication time before they are (a). |
| Attendance | `nfl_game_context` | (c) as a pregame input | Realised after the game. Usable as an outcome or a control only. |
| Observed temperature and wind | `nfl_schedule` | (c) as a pregame input | Hindsight, see VEN-03. Descriptive splits only. |
| Forecast temperature, wind, precipitation | National Weather Service `forecastHourly` | (a) only with its issue time | Week 8 forecasts are recorded with issue times. No archive of past forecasts exists yet. |
| Penalties and penalty yards | `nfl_pbp_penalty` | Outcome | Postgame by definition. |

## 3. Experiment register

| Exp | Matrix ID | Question | Status | Main rule gaps | Next action |
|---|---|---|---|---|---|
| E0 | CAL-01, CAL-03, VEN-01, VEN-02, MISC-01 | Split screen across factors | null | Single 2025 holdout (R2). Observed weather (R1). No pre-registration (R3). No team clustering (R5). Penalty outcomes raw. | Rolling-origin rerun. Team-adjust penalties. |
| E1 | VEN-03 | Forecast versus observed weather | insufficient_data | No archived forecasts. | Archive NWS forecasts at a fixed lead for every game from now. |
| E2 | VEN-03, VEN-01, VEN-02 | Outdoor temperature by wind | hypothesis (penalty cell only) | Cell chosen after looking at the data (R3). Observed weather (R1). Cells unshrunk (R6). 8-game holdout (R2). | Shrink cells. Pre-register the penalty cell on a new season. |
| E3 | VEN-04 | Venue and altitude | null | Single holdout (R2). Empirical-Bayes shrinkage is used. Penalty outcomes raw. | Rolling-origin rerun. |
| E4 | MISC-01 | Official crews | null (total and margin). insufficient_data (penalties). | Penalty outcomes not team-adjusted. Per-official effects unshrunk (R6). | Team-adjust penalties. Shrink toward the league mean. |
| E5 | CAL-03 | Kickoff slot by broadcast | null | National TV selection is a confound the matrix names. Single holdout. Penalty outcomes raw. | Rolling-origin rerun. State the confound in every summary. |
| E6 | none in matrix (proposed MISC-02) | Attendance above listed capacity | insufficient_data | No historical capacity. Attendance is class (c) as an input. | Obtain capacity per season. Ask the matrix owner to register MISC-02. |
| E7 | CAL-02, CAL-04 | Rest and time-zone travel | null | Travel uses standard offsets and no distance. Single holdout. Penalty outcomes raw. | Geographic fixture with distance. Rolling-origin rerun. |

Pool-wide: 848 team-adjusted tests (see the team-adjusted section below). Smallest pooled q is 0.21. Nothing reaches `supported`.

## 4. Experiment records

Each record follows the matrix's required outputs. Fields not listed here are in the scratchpad output files.

### E0. Split screen (CAL-01, CAL-03, VEN-01, VEN-02, MISC-01; status null)

- Question: which game-information levels move total-point residuals, margin residuals, penalties or penalty yards once
  team strength is removed.
- Unit: game. Seasons 2022 to 2025, regular season, 1,087 games.
- Method: leave-one-out team-season residuals; season centring; bootstrap intervals; permutation p-values; Benjamini-
  Hochberg within the family; 2025 holdout after 2022 to 2024 fit.
- Result: 292 tests. No level reaches q below 0.10 on residual outcomes. Smallest q is 0.146 (outdoor games, total residual,
  -3.11 [-4.74, -1.47]; 2025 holdout -1.50 [-4.69, +1.56] on 180 games).
- Earlier raw-outcome "candidates" (Detroit, Buffalo, New York venues, attendance above listed capacity) came from team
  strength and are superseded.

### E1. Forecast versus observed weather (VEN-03; status insufficient_data)

- Question: how much of the outdoor effect survives when the input is a forecast issued before the lock (R1).
- Blocked on an archive. The week 8 forecasts are the first captured, snapshot 2026-10-27.

### E2. Outdoor temperature by wind (VEN-03; status hypothesis for the penalty cell)

- Question: is the outdoor effect concentrated in cold, windy games?
- Cells: under 32F, 32 to 49F, 50 to 69F, 70F and up, crossed with under 10, 10 to 14, 15 mph and up. Outdoor and
  retractable-open games only. Observed weather, so descriptive only (R1).
- The 50 to 69F, 10 to 14 mph cell has +2.38 flagged penalties per game after team adjustment (95% interval [0.95, 3.69]),
  n = 42. Positive in all four seasons; per-season intervals include zero except 2022 and 2025. Pool-wide q is 0.23.
- Status is `hypothesis`, not `supported`: the cell was chosen from the data (R3), the weather is hindsight (R1), the
  cell is unshrunk (R6), and the holdout has 8 games (R2).
- Record: `docs/EXPERIMENT-OUTDOOR-PENALTY-CELL-2026-10-27.md`.

### E3. Venue and altitude (VEN-04; status null)

- Question: does Denver, or any venue, show a home-margin or total effect beyond team strength?
- Raw venue tests: no venue passes control. Detroit total residual is the closest, at q = 0.060 (weak, not promoted).
- Empirical-Bayes shrunk venue means are in the scratchpad output (E3_venue_shrinkage.json).

### E4. Official crews (MISC-01; status null for total and margin, insufficient_data for penalties)

- Question: do individual officials move totals, margins, penalties or penalty yards?
- 464 tests across officials with at least 30 games. No official passes control on total or margin residuals.
- Penalty outcomes are raw, so they carry team tendency and get no verdict until team-adjusted.

### E5. Kickoff slot by broadcast (CAL-03; status null)

- Question: does the national-window effect survive team-strength removal, and does it differ by network?
- 28 tests. Smallest q is 0.85, so no cell passes control on any outcome.
- National TV selection confounds this (matrix CAL-03). The result is an association.

### E6. Attendance above listed capacity (proposed MISC-02; status insufficient_data)

- Question: is the attendance effect real or a capacity artefact?
- Blocked: needs capacity by season. Attendance is class (c) as a pregame input (R1).

### E7. Rest and time-zone travel (CAL-02, CAL-04; status null)

- Question: how much of the day-of-week and slot effect is rest and travel?
- 44 tests. Rest bins for home and away, and a time-zone shift for the away team. Standard offsets, no daylight adjustment,
  no distance.
- The "no shift" level for penalties has a 2025 holdout interval that excludes zero, but its pool-wide q is 0.20 and the
  penalties are raw. Treated as no evidence.

## 5. Data limits

- Roof codes change across seasons (`outdoors`, `open`, `closed`, `dome`, blank). Normalised to four groups.
- Listed capacity is today's figure. Attendance as a share of capacity is approximate for past seasons.
- The referee field is the head official only. Crew effects use `nfl_game_officials` (21,296 rows).
- Penalty outcomes are raw in E0, E4, E5 and E7. Only the E2 penalty cell has a team-adjusted re-test.
- The pooled 2022 to 2025 window spans the 2024 and 2025 kickoff rule shifts (ST-01, R8). Results on kickoff-dependent
  outcomes are not yet split by regime.

## 6. Next actions, in order

1. Done 2026-10-27: team-adjusted penalty outcomes in E0, E2, E4, E5 and E7 (see below).
2. Done 2026-10-27: rolling-origin folds for every E0 factor (descriptive, see below). A formal chronological model is still open.
3. Done 2026-10-27: empirical-Bayes shrinkage across the outdoor weather cells (see below).
4. Done 2026-10-27 as season-week cluster bootstrap (weather is correlated within a week). Team clustering is still open.
5. Archive NWS forecasts at a fixed lead for every upcoming game, starting with week 9 (E1, R1).
6. Obtain listed capacity per season for 2022 to 2025 (E6).
7. Pre-register the penalty cell on a season not yet used. The 2026 reservation (R9) must be decided first.
8. Ask the matrix owner to register MISC-02 for attendance.

## 7. Week 8 slate inputs (not experiments)

Per-game inputs are recorded in the venue and forecast snapshots, and in the game-information snapshot store. Referees are
not assigned in nflverse yet (checked 2026-10-27 18:39 UTC). The three national broadcasts are confirmed from published
schedules. The Sunday CBS and FOX split is not confirmed for any game.

These inputs are attached to simulation output as context. The model does not read them (R1: the forecast is class (a) only
at its issue time, and no game-information effect has passed the adoption gates).

## 8. Code and outputs

- Scripts, under `scripts/nfl_sequence/game_info/`: `build_venues.py`, `fetch_forecasts.py`, `backtest_splits.py`
  (E0 machinery), `retest_penalty_cell.py` (E2 cell).
- Game-information snapshot module: `scripts/nfl_sequence/game_info_snapshot.py`.
- Outputs: E0 and E2 to E7 under the scratchpad (`gameinfo2026/`). The penalty-cell re-test under
  `/root/lp-snapshots/nfl-game-info/experiments/penalty-cell-retest/`. Venue and forecast snapshots under
  `/root/lp-snapshots/nfl-game-info/2026/week08/`.

## Team-adjusted families and robustness checks (2026-10-27)

Script: `scripts/nfl_sequence/game_info/run_team_adjusted_families.py`. Output:
`/root/lp-snapshots/nfl-game-info/experiments/team-adjusted-v2/results.json` (SHA-256 starts `ac07f7082d09ee03`). The repository run
reproduces the scratch run exactly: families, clustering, rolling-origin folds and shrinkage all match.

**Team adjustment.** Each team's expectation uses its full-season leave-one-out average of points for and against, and of
flagged penalties and yards committed. That uses games played later in the same season, so these results are descriptive.
They are not a pregame forecast input. A strictly chronological version is still open (see next actions).

| Family | Tests | Candidates | Smallest q |
|---|---:|---:|---:|
| E0 split screen | 292 | 0 | 0.146 |
| E2 outdoor temperature by wind | 20 | 2 | 0.030 |
| E4 official crews | 464 | 0 | 0.214 |
| E5 slot by broadcast | 28 | 0 | 0.784 |
| E7 rest and travel | 44 | 0 | 0.667 |

Pooled across the 848 team-adjusted tests: smallest pooled q is 0.21. The penalty cell has pooled q 0.24 for penalties
and 0.24 for yards. The earlier 970-test pool mixed raw and adjusted outcomes and is superseded.

**Penalty cell (E2).** Outdoor games at 50 to 69F with a 10 to 14 mph wind, 42 games, 2022 to 2025.
- Flagged penalties: +2.39 per game, family q 0.03. 2025 holdout +3.03, interval [0.30, 5.68], n = 8.
- Penalty yards: +17.5, family q 0.04. 2025 holdout +18.9, interval [1.5, 35.2], n = 8.
- Status: `hypothesis`. The cell was chosen from the data, so it is not pre-registered. The 2025 holdout has 8 games.
  The weather is observed, so it is hindsight. Shrinkage below lowers the estimate.

**Shrinkage (empirical Bayes, outdoor weather cells).** The penalty cell's mean of 1.97 shrinks to 1.39, with weight 0.75.
Measured against the average of the outdoor cells (-0.33), its effect falls from about 2.30 to about 1.73.

**Cluster bootstrap by season and week.** Penalty cell: [0.90, 3.56] by week cluster, [0.74, 3.44] at game level.
Outdoor versus all other roof groups, total residual: -3.11 points, [-4.83, -1.45] by week cluster, [-4.87, -1.45] at game
level. Outdoor versus other roofs, penalties: -0.15, [-0.66, 0.36] at game level, a null result.

**Rolling-origin folds.** 3 of 180 factor-level-outcome combinations keep one direction from the earlier seasons to the
next season: temperature under 32F (penalty yards), referee Brad Allen (penalty yards), and referee Alan Eck (penalties).
Their family-level q values are 0.24, 0.21 and 0.23, so none survives multiplicity control.

**Correction.** An earlier cluster row compared outdoor games only against retractable-open games and reported -8.0. That
row is replaced by the outdoor-versus-all-roofs value above.

**Status after this run.** No result is `supported`. The penalty cell remains a `hypothesis`. No simulator input changes.
