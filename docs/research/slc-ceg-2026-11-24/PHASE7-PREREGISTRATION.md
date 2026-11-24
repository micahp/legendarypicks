# SLC-CEG Phase 7 pre-registration: full-game evaluation

Written 2026-11-24, before any Phase 7 game is simulated. Code: `scripts/nfl_sequence/ceg_game.py`,
`scripts/nfl_sequence/ceg_phase7.py` (grading). Arm: CEG-SEL (Phases 2 to 4 selective) plus arm E team terms (Phase 6),
run from parameter-only artifacts with every data read blocked.

## 1. Statistical realism

300 games from the 2026 week 11 artifact with no team terms (league-average teams), seed 1. Compared with the 2025
regular season per team-game: points, scrimmage plays, enforced fouls, yards, sacks, interceptions, fumbles lost, punts,
field-goal attempts and makes, touchdowns, drives, overtime share. Reported as simulated, observed and the ratio. No
threshold; this states how far the engine is from a real game.

## 2. Week 11 2026 (examined)

The 13 week 11 games, 40 seeds each, from the 2026 week 11 artifact with team terms (data through week 10). Graded
against the final scores and the nflverse closing lines (`games.csv`): home-win Brier, winners right, cover and over
Brier, mean absolute margin and total error, against the market and the week 11 frozen-SLC results in
`docs/research/week11-rerun-preflight-2026-11-23/grading.json` (branch `fix/roster-preflight-2026-11-22`). These games
were examined before (week 11 batch), so this is not a confirmation.

## 3. Week 12 2026 (prospective)

The 16 week 12 games, 40 seeds each, from a 2026 week 12 artifact with team terms (data through week 11). Forecasts
committed before the first kickoff (2026-11-25 20:00 ET). Graded after the games with the same metrics, against the
nflverse lines as fetched on 2026-11-24.

## Limits stated now

- 40 seeds per game: a home-win share has a standard error of up to 0.08.
- The team terms are small (Phase 6): CEG will sit close to 50% on most games, and it has no home-field term.
- No player attribution, so no props.
