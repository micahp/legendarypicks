# NHL v3: team and period strength + shot-based goalie model

**Status:** Deferred design, not implemented. V2 artifact and runner wiring exist on `dev`; this note makes no changes to models, frozen forecasts or services. V4's full-game simulator is explicitly separate: see `docs/NHL-V4-FULL-GAME-SIM-DESIGN.md`.

## Version boundary

- **V2 (current foundation):** team attack/defence ridge-Poisson on complete game goals. `frozen_models_2026-27_v2.json` is frozen on a 23,222-game canonical sample from 2008-09 through 2025-26; the corresponding `team_strength.py` has home advantage, team attack/defence, 400-day recency weighting and regularisation. It yields game-level goal means and probabilities, not a period, goalie or event simulator.
- **V3 (this document):** two independently testable layers. **Layer 1** predicts period-level team shot creation/prevention and opponent-/teammate-adjusted on-ice player effects. **Layer 2** predicts shot difficulty and starter-dependent save probability, using location and shot type. Output shot/goal rates and period-level forecasts; do **not** claim to simulate an entire game.
- **V4 (separate document):** uses V3 rates inside a stateful game simulator with real penalty/manpower transitions, shift/line rotations, power-play goals, game script, empty net, OT and shootouts.

## What v2 does and doesn't know

```
log(mu_home) = b0 + home_adv + attack[home] - defence[away]
log(mu_away) = b0            + attack[away] - defence[home]
```

This is a useful baseline, not a full probabilistic reconstruction of hockey. It has no explicit goalie, period, player shift, shot location, shot type or penalty-state variables. Team defence currently absorbs goaltending and penalty killing.

The v2 historical scorecard documents winner Brier **0.2444** versus v1 reference **0.2462** on the same 9,147 feature-complete 2019-2025 games. The goal-margin forecast distribution widened materially. Those numbers are **model diagnostics only**; not trading ROI, evidence of profit, or proof of superiority to a separately sampled sportsbook market.

## Layer 1: team performance at period and on-ice granularity

The effective unit is a **team-period/strength-state exposure window**, with optional shift intersections where coverage supports them. Model:

1. Team shot attempts, unblocked attempts, shots on goal, chance danger and goals per 60, split by period and score state (leading, tied, trailing).
2. Separate attack and prevention. Retain existing score-/venue-adjusted 5v5 xG and xGA as priors, not as double-counted goals.
3. On-ice conventional plus/minus alongside **on-ice GF/GA and xGF/xGA per 60**, adjusted/shrunk for opponents, teammates and time on ice. Conventional NHL +/- is not a direct causal player rating and typically excludes power-play goals.
4. Reconstruct who was on ice at shot events by joining official play-by-play to **separate** NHL shift charts by game, player, period and elapsed time. Never assume complete on-ice player lists are embedded in every PBP record.
5. For a missing/malformed shift, preserve an unknown deployment indicator rather than inserting a guessed line.

V3 can test period markets and team shot opportunities without yet producing event-by-event simulated possessions. Power-play *observed aggregates* may be calculated here to provide V4 with priors; modelling the full penalty and PP-goal sequence is V4 work.

## Layer 2: shot quality and goaltender contribution

There is **no goalie-specific predictive adjustment** in the current v2 forecasting engine. Goalie saves, goals against, save percentage and starts already exist in LP's player/game-log ingestion, but the NHL forecasting engine does not condition on the starter.

Build:

1. A **league shot-danger model** from shot type (wrist, snap, slap, backhand, tip, etc.), rink-normalised x/y, distance/angle, rebounds, rush/cross-slot movement if observed, score state, period and manpower.
2. For each goalie, compute pregame **goals saved above expected** from shots actually faced, with exposure-weighted shrinkage to a league prior; optionally fit goalie-specific coefficients for shot type/danger zone once enough examples exist.
3. **Pregame starter mixture:** when the starter is unknown, weight candidate goalies by genuinely pregame-known availability/starting probabilities rather than inserting a confirmed starter retrospectively. The October 2026 heuristic starter feed identified the starter only ~49.7% of the time and was not adopted.
4. Feed expected shots × conditional goal probability into **V3 team/period goal-rate projections**, and later into V4 event simulation.

Shot danger, save probabilities and GSAx have distinct targets. Do not use postgame goalies, shot events or end-of-game plus/minus as *pregame* features.

## Data inventory before development

| Source | What it supplies | Limitation |
| --- | --- | --- |
| Current canonical NHL model input | 23,222 game-level goal outcomes; some team 5v5 xG/shot features | No period, shift or individual shot events in the frozen input |
| LP NHL game/player ingestion | Game-level PP opportunities/goals, skater shifts counts, goalie saves/SA | Not timestamped shift or PP event-state distributions |
| NHL gamecenter PBP | Goals, shots, penalties, period/time, event locations when available | Historical field coverage and reliable strength/on-ice joins need auditing |
| NHL shift charts | Player shift start/end intervals | Separate endpoint and potentially incomplete per-season availability |
| MoneyPuck historical shots | Publicly described 2007-08 onward shot events, shot types, locations, xG and pre-shot attributes | Excludes blocked shots; commercial licence unresolved |

NHL API examples:
- `https://api-web.nhle.com/v1/gamecenter/{gameId}/play-by-play`
- `https://api.nhle.com/stats/rest/en/shiftcharts?cayenneExp=gameId={gameId}`
- `https://moneypuck.com/data.htm`

First enumerate complete coverage by season, including event counts, coordinate validity, penalty/strength fields, shot-to-goalie and shot-to-shift joins. Confirm permitted commercial use and attribution before publishing derived features.

## V3 evaluation, separate from trading

Compare v2 against: period/team-only, goalie-only, and their combination, **chronologically on matched games**. Score shot creation, shot danger, goalie residual calibration, period-goal error, winner/total/cover probability reliability and sensible uncertainty intervals. A stronger overall Brier score is **not** the criterion for a profitable trading strategy; it is an engineering/model quality metric. Trading hypotheses belong in `docs/NHL-STANDINGS-ONLY-TRADING-STRATEGY.md` and must be tested against executable prices.

## Deferred sequence

1. Verify PBP, shot coordinates, goalie identity, and shift charts historically by season; secure usable source rights.
2. Create immutable event and shift ingestion and leak-safe pregame aggregates.
3. Test Layer 1 period/shot models and on-ice adjusted effects separately.
4. Test Layer 2 shot danger, regressed goalie GSAx and starter-mixture separately.
5. Combine V3 rates, freeze a new version and compare against v2. **Stop here for V3.**
6. Only then consider the stateful V4 simulator described in its own note.

Do not divert current NHL model selection, calibration or trading work to this deferred roadmap.
