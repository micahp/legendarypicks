# SLC-CEG Phase 7: full-game evaluation

Date: 2026-11-24. Pre-registration: `PHASE7-PREREGISTRATION.md` (`1aac2ca6`, before any game). Code:
`scripts/nfl_sequence/ceg_game.py`, `ceg_phase7.py`. Results: `phase7/realism_2025.json`, `phase7/week11_grading.json`,
`phase7/w11_forecasts.json`, `phase7/w12_forecasts.json` (frozen, `ada09944`), `phase7/realism_300.json`.
Every game ran from a parameter-only artifact with every data read blocked.

## Result

1. **CEG plays complete, legal football games without historical rows:** 300 of 300 realism games and 1,160 of 1,160
   forecast games completed; every drive passed `check_drive`.
2. **It moves the ball close to the real game, but scores too little:** yards 0.94 of 2025, plays 1.03, sacks,
   interceptions, fumbles lost and punts within 5%, drives 0.98; but points, touchdowns and field goals are all 0.87 of
   2025, and enforced fouls 0.78.
3. **It does not forecast games yet.** On the 13 week 11 games its home-win Brier is 0.245, a coin is 0.250, the
   market 0.183 and frozen v2 0.205. Its home-win chances run only from 0.375 to 0.675: the two Phase 6 team terms are
   real but far too small to separate teams. Cover Brier 0.418 is worse than a coin, because CEG gives near-even margins
   in games the market makes clear favorites.
4. **The week 12 forecasts are frozen** for a prospective grade after the games.

## 1. Statistical realism (300 games, league-average teams, against the 2025 regular season per team-game)

| measure | simulated | 2025 | ratio |
|---|---|---|---|
| points | 20.11 | 23.01 | 0.87 |
| touchdowns | 2.24 | 2.56 | 0.87 |
| field-goal attempts | 1.78 | 2.00 | 0.89 |
| field goals made | 1.48 | 1.71 | 0.87 |
| yards | 303.1 | 321.0 | 0.94 |
| plays (scrimmage and no-play fouls) | 67.6 | 65.9 | 1.03 |
| enforced fouls | 4.93 | 6.36 | 0.78 |
| sacks | 2.27 | 2.37 | 0.96 |
| interceptions | 0.72 | 0.70 | 1.03 |
| fumbles lost | 0.47 | 0.46 | 1.03 |
| punts | 3.71 | 3.55 | 1.04 |
| drives per game | 20.7 | 21.1 | 0.98 |
| overtime share | 0.063 | 0.051 | 1.22 |

0 blocked games; 5 ties in 300 (1.7%), more than the NFL's.

**Where the missing points come from, as hypotheses to test, not findings:** fewer field-goal attempts (the B field-goal
make model and the field-goal ceiling), red-zone yardage (the hazard model's goal-line censoring), and the penalty
simplifications (no spot fouls such as pass interference).

## 2. Week 11 2026 (examined, 13 games, 40 seeds each)

| model | home-win Brier | cover Brier | over Brier | winners right | margin error | total error |
|---|---|---|---|---|---|---|
| market | 0.183 | | | 9 | 7.8 | 10.8 |
| CEG-SEL + E | 0.245 | 0.418 | 0.313 | 6 | 12.1 | 11.2 |
| frozen v2 | 0.205 | 0.302 | 0.321 | 8 | 9.9 | 12.3 |
| frozen v1.6 | 0.230 | 0.302 | 0.331 | 9 | 10.0 | 13.1 |
| coin | 0.250 | | | | | |

CEG's total error (11.2) is the best of the simulators and close to the market's (10.8), because its totals sit near
league average. Its margins do not separate teams.

## 3. Week 12 2026 (prospective)

16 games, 40 seeds each, from `ceg-sel-e-2026w12.pkl` (sha256 `05554214c1ff...`, data through week 11), committed at
2026-11-24T11:52Z (`ada09944`), before the first kickoff (2026-11-25 20:00 ET). To grade after the games:
`python3 scripts/nfl_sequence/ceg_phase7.py grade --forecasts docs/research/slc-ceg-2026-11-24/phase7/w12_forecasts.json --games-csv <fresh games.csv> --out .../week12_grading.json`.

## What would make CEG forecast games

Team strength is the gap, and the earlier lesson stands: broad strength terms lost to the league baseline. The next
challengers, each pre-registered and scored against arm C component by component:

- team terms on the components that drive scoring: run and completion yardage (hazard-level team adjustments), red-zone
  touchdown conversion, and field-goal range decisions;
- arm D in the runtime (player attribution, backlog E10), so the quarterback and receivers in the snapshot change the
  outcomes;
- the regression and GAM challengers for the coarse cells (backlog E9).
