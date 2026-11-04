# SLC v2 lineup layer: 2025 substitution check, thresholds

Written 2026-11-04, before the 2025 replay was run. Branch `pbv1-integration-2026-11-02`.

## What is checked

The lineup layer (`scripts/nfl_sequence/lineup_participation.py`) with inputs fitted on 2022-2024 participation
(`model-2022-2024.json`, from `lineup_transition_fit.py --fit 2022,2023,2024`). The 2025 replay feeds each team-game's
observed package sequence (slot counts by weekly-roster group), so it tests substitution mechanics given the calls, not the
calls. 2025 is a known validation fold, not an untouched test.

Eligible players are the team-week's ACT weekly roster. Entry weights and leave hazards use only published snap shares from
before the game. Five seeds per team-game.

## Fit-season reference (2022-2024, observed)

- Same skill lineup (every non-OL player) on consecutive snaps: 28.4% of 107,038 transitions.
- Player entries per team-game: 89.0 over 1,630 team-games.

## Pass thresholds for 2025 (all three must pass)

1. Same-skill-lineup rate: simulated within 0.05 (absolute) of observed 2025.
2. Entries per team-game: simulated within 20% of observed 2025.
3. Snap share: the mean absolute error of simulated snap share against published `offense_pct`, per player-game over the
   eligible roster, is lower for the fitted model than for both baselines, and the game-clustered 95% interval of each
   difference (fitted minus baseline) is entirely below zero. Baselines: `independent` (every player leaves after every
   snap, so each lineup is a fresh weighted draw) and `static` (nobody leaves voluntarily).

A FAIL is reported as a FAIL with the numbers. Thresholds are not changed after the run.
