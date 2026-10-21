# Phase 2A training data specification

## Population and dispositions

- Frozen evaluation frame: 4,876 regular-season games, start seasons 2018–2022 (2022 is partial).
- The Phase 1 official team-score component is accepted for all 4,876 games. Each included game is replayed and reconciled to its official final score before its events enter fitting or evaluation.
- Official team SOG targets are accepted for 4,814 games. The remaining 62 games are quarantined only for SOG use; they remain in accepted score training, scoring reconciliation, and goal distribution evaluation.
- PBP events come from the frozen Phase 1 normalized event ledger and retain publisher source order. Phase 1 raw body and input pin checks were rerun for this work; see `REPLAY-VALIDATION.md`.
- The fitter reads zero shift rows. Shift chart or player identity quality cannot remove an otherwise accepted team score.
- Event outcome fitting requires accepted event and team-count dispositions plus ordinary-shot eligibility. Spatial coordinates and shot type enter only when their own component disposition is accepted.
- Attempt classes are blocked, missed, saved, and goal. Every generated attempt has one outcome; saved shots and goals contribute SOG.

## Chronology and folds

- Development: fit on 2018–2020, evaluate on 2021.
- Final: fit on 2018–2021, evaluate on the partial 2022 season. The 2022 outcomes do not affect fitting, feature categories, hyperparameters, or the adoption rule.
- Team attack and defense snapshots use the prior ten accepted official team-SOG games for each stable team ID. “Attack” is SOG for; “defense” is opponent SOG allowed. Only games on earlier calendar dates update a snapshot. The source frame lacks exact puck-drop timestamps, so same-date games do not update one another.
- Historical snapshots use an explicit noon UTC synthetic scheduled start and make prior-date features available by 23:59:59 UTC on the previous date. This conservative boundary is not a substitute for scheduled-start timestamps in a prospective production caller.
- Period, strength, score-state, and time-remaining values for historical event rows are reconstructed from earlier accepted PBP state in source order. Observed strength comes from event situation codes, never shift charts. Prospective simulation uses only its generated strength transitions.
- The publisher's within-period clock can move backward in source order. Events are never sorted or removed for this; rate-exposure intervals and time features use a per-period elapsed-time high-water mark, so already traversed clock intervals are not counted twice. The number and total seconds of these backward-clock rows are recorded in the fit counters.
- Rate exposure is admitted only for games whose accepted event chronology and clocks pass the timeline gate. Goal reconciliation and accepted shot outcomes remain component-scoped and are not filtered on shift quality.

## Feature and target provenance

| Feature/target | Construction | Source and gate |
|---|---|---|
| Period | Regulation P1/P2/P3 and OT | Accepted event period number |
| Strength | Even, advantage, disadvantage, empty net, unknown | Parsed observed situation code in training; generated limited penalty state in simulation |
| Score state | Leading, tied, trailing for shooting team | Accepted prior goal sequence, including accepted goals when another component is quarantined |
| Time remaining in period | Early (>15m), middle (>5m to 15m), late (≤5m) | Accepted source clock mapped through its monotone high-water envelope; rate exposures split at bucket boundaries |
| Time remaining in game | Regulation game time: early, middle, late; overtime | Period number plus monotone within-period clock; distinct fitted dimension |
| Home/away | Home or away shooting side | Stable game venue identity |
| Team attack/defense | Prior-10 official SOG for/allowed per game, categorized against fit-only overall reference | Accepted official team SOG validation artifact, stable team IDs, prior calendar dates only |
| Attempt outcomes | Blocked, missed, saved, goal | Accepted PBP event and team-count components; four classes reconcile to each accepted shot attempt |
| Goal quality | Distance/angle bins and shot type | Accepted spatial and shot-type dispositions only; unknown category otherwise |
| Whole-game goals | Replayed ordinary goal events and final-score reconciliation | Official accepted team score; no shift or player identity condition |
| Whole-game SOG | Sum of generated saved/goal outcomes | Official team SOG target only on the 4,814 accepted games |
| Existing v2 score comparator | Refit goal targets, venue, team attack/defense, shootout rate | Hash-pinned v2 canonical source joined by game ID and reconciled to Phase 1; v2 method source hash/commit in `TRAINING-DATA.json` |

## Fit counts

Development fit counts: `{"accepted_shot_events": 362514, "accepted_spatial_shot_events": 362508, "accepted_team_goals_used_for_state": 19056, "evaluation_2021_accepted_shot_events": 148665, "evaluation_games": 1312, "event_outcome_blocked": 88300, "event_outcome_goal": 19028, "event_outcome_missed": 74578, "event_outcome_saved": 180608, "fit_games": 3221, "fit_penalty_calls": 20584, "fit_score_team_targets": 6442, "fit_shootout_attempts": 1708, "fit_shootout_goals": 533, "official_score_targets_from_all_fit_games": 6442, "official_sog_eligible_fit_games": 3181, "official_team_score_game_targets": 6442, "official_team_score_games": 3221, "rate_timeline_clock_regression_seconds": 591409, "rate_timeline_clock_regressions": 14961, "rate_timeline_excluded_games": 5, "rate_timeline_games": 3216, "rate_training_attempts": 362508, "rate_training_exposure_minutes": 390446.6667, "v2_neutral_site_fit_games": 13, "v2_shootout_decision_games": 238, "v2_team_strength_fit_games": 3221}`

Final fit counts: `{"accepted_shot_events": 511179, "accepted_spatial_shot_events": 511173, "accepted_team_goals_used_for_state": 27206, "evaluation_2022_accepted_shot_events": 39949, "evaluation_games": 343, "event_outcome_blocked": 123675, "event_outcome_goal": 27178, "event_outcome_missed": 104864, "event_outcome_saved": 255462, "fit_games": 4533, "fit_penalty_calls": 29197, "fit_score_team_targets": 9066, "fit_shootout_attempts": 2455, "fit_shootout_goals": 757, "official_score_targets_from_all_fit_games": 9066, "official_sog_eligible_fit_games": 4473, "official_team_score_game_targets": 9066, "official_team_score_games": 4533, "rate_timeline_clock_regression_seconds": 591409, "rate_timeline_clock_regressions": 14961, "rate_timeline_excluded_games": 5, "rate_timeline_games": 4528, "rate_training_attempts": 511173, "rate_training_exposure_minutes": 549725.0, "v2_neutral_site_fit_games": 16, "v2_shootout_decision_games": 340, "v2_team_strength_fit_games": 4533}`

All source artifact pins and the v2 source, frozen-model, and canonical-data hashes are retained in `TRAINING-DATA.json`. The fitted final parameter artifact is `FITTED-MODEL.json`; evaluation scores and per-game predictions are in `EVALUATION.json`.

## Player-prop extension points

Generated shot events carry attempt identity, team owner, period, clock, strength, score state, location, and shot type. Shooter allocation and player SOG distributions can attach to the attempt/outcome pair; goalie response can attach to saved/goal outcomes once a verifiable pregame goalie identity source exists; player goals/assists can attach after goal events; richer penalty transitions can extend manpower events; lineup and shift deployment can attach via generated player-entry and on-ice attributes. None of those player or goalie-identity components are fitted in Phase 2A. Shootout events remain separate from ordinary shot/SOG accounting; their clock field is tagged as attempt order, and the final-score one-goal shootout convention is recorded at `GAME_END`.
