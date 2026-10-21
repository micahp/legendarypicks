# NHL V3 Phase 2A stochastic shot and scoring model

- **Base:** `2f2d1245d7459f17ed656111da5c6494d192e332`
- **Research branch:** `research/nhl-v3-phase2a-stochastic-2026-10-21`
- **Model artifact SHA-256:** `8e0304b9dbe4230f9deb17abda0ebe79cd89653289d2661a1612d79f8914addb`

## Reproduction

From the repository root, run `/root/legendarypicks/backend/venv/bin/python research/nhl/nhl-v3-phase2a-stochastic-2026-10-21/run_phase2a.py --validation-sims 128 --holdout-sims 256 --seed 20261021`. Input paths can be overridden with `--help`; input artifact hashes and the split are recorded in `TRAINING-DATA.json` and `EVALUATION.json`. Invariant suite: `/root/legendarypicks/backend/venv/bin/python -m unittest discover -s research/nhl/nhl-v3-phase2a-stochastic-2026-10-21 -p 'test_*.py' -v`.

## Adoption decision

**NOT ADOPTED for promotion over the simple historical-rate baseline.** The prototype is a coherent,
reproducible event generator and is useful for continued simulator development. Adoption requires
paired improvement on the untouched 2022 holdout with uncertainty that excludes zero, plus adequate
calibration. The holdout has only 343 games, so it cannot establish broad seasonal
generalization. No market, ROI, or production claim is made.

## Cohort and training

- Frozen frame: 4,876 regular-season games, start seasons 2018–2022 (2022 partial through November 27).
- Forward split: 2018–2020 fit; 2021 development; 2022 partial final holdout, untouched during design and fitting.
- Official team score target: 4,876 games accepted by Phase 1. Scores remain eligible independently of shift-chart quality.
- Official team SOG: 4,814 accepted game targets; 62 quarantined game targets are excluded from SOG target metrics.
- Historical PBP: 1,510,104 source-ordered events. Raw hashes and the full Phase 1 replay were rechecked before fitting.
- The fitter reads no shift rows. Goalie identity and player-on-ice fields are not predictors.
- SOG and score histories for pregame team attack/defense use only accepted official team SOG from earlier calendar dates; same-date games do not update one another.
- Prediction requests contain the Phase 1 `PregameSnapshot` only. The date-only frame has no puck-drop timestamp, so historical snapshots use a documented noon UTC boundary and prior-date features; a production caller must supply the published scheduled start.

Training details: {"development_fit_counts": {"accepted_shot_events": 362514, "accepted_spatial_shot_events": 362508, "accepted_team_goals_used_for_state": 19056, "evaluation_2021_accepted_shot_events": 148665, "evaluation_games": 1312, "event_outcome_blocked": 88300, "event_outcome_goal": 19028, "event_outcome_missed": 74578, "event_outcome_saved": 180608, "fit_games": 3221, "fit_penalty_calls": 20584, "fit_score_team_targets": 6442, "fit_shootout_attempts": 1708, "fit_shootout_goals": 533, "official_score_targets_from_all_fit_games": 6442, "official_sog_eligible_fit_games": 3181, "official_team_score_game_targets": 6442, "official_team_score_games": 3221, "rate_timeline_clock_regression_seconds": 591409, "rate_timeline_clock_regressions": 14961, "rate_timeline_excluded_games": 5, "rate_timeline_games": 3216, "rate_training_attempts": 362508, "rate_training_exposure_minutes": 390446.6667, "v2_neutral_site_fit_games": 13, "v2_shootout_decision_games": 238, "v2_team_strength_fit_games": 3221}, "development_seasons": [2021], "development_v2_fit": {"fit_games": 3221, "training_shootout_home_win_rate": 0.47478991596638653}, "environment": {"numpy_version": "1.24.4", "python_version": "3.8.10"}, "feature_history_window_games": 10, "final_fit_counts": {"accepted_shot_events": 511179, "accepted_spatial_shot_events": 511173, "accepted_team_goals_used_for_state": 27206, "evaluation_2022_accepted_shot_events": 39949, "evaluation_games": 343, "event_outcome_blocked": 123675, "event_outcome_goal": 27178, "event_outcome_missed": 104864, "event_outcome_saved": 255462, "fit_games": 4533, "fit_penalty_calls": 29197, "fit_score_team_targets": 9066, "fit_shootout_attempts": 2455, "fit_shootout_goals": 757, "official_score_targets_from_all_fit_games": 9066, "official_sog_eligible_fit_games": 4473, "official_team_score_game_targets": 9066, "official_team_score_games": 4533, "rate_timeline_clock_regression_seconds": 591409, "rate_timeline_clock_regressions": 14961, "rate_timeline_excluded_games": 5, "rate_timeline_games": 4528, "rate_training_attempts": 511173, "rate_training_exposure_minutes": 549725.0, "v2_neutral_site_fit_games": 16, "v2_shootout_decision_games": 340, "v2_team_strength_fit_games": 4533}, "final_holdout_seasons": [2022], "final_v2_fit": {"fit_games": 4533, "training_shootout_home_win_rate": 0.4852941176470588}, "fit_seasons_development": [2018, 2019, 2020], "fit_seasons_final": [2018, 2019, 2020, 2021], "official_score_targets_in_development_fit": 6442, "same_date_feature_updates": "excluded; exact game start timestamps are absent from the pinned frame", "shift_rows_read_by_fitter": 0, "source_pins": {"approved_disposition_rules": "research/nhl/fullframe-event-audit-2026-10-21/DISPOSITION-RULES.md", "approved_label_artifact": {"path": "/root/lp-data/nhl-official-outcome-quality-adjudication-2026-10-20/research_label_quality.csv", "reader": "research/nhl/official-outcome-backfill-2026-10-20/nhl_research_data.py", "reader_base_commit": "c91ae36c39b57f86c7c839a2e424eec3ee9330a0", "sha256": "cc9be34586dc16701f162bbc04cf256a9fd0c4c3c823625ecb02ff24eed1f60c"}, "approved_schema": "research/nhl/fullframe-event-audit-2026-10-21/PROPOSED-SCHEMA.md", "artifacts": {"event_dispositions.csv.gz": "c5ee8cc948e8de2f070d6b5b417d3756a731135d771d91d911d3e0f24c356e1f", "game_metrics.csv": "7162cb7bdc0859f6d6310702e44557e84724584b27abdc958cdcfe192d1d3a17", "game_source_provenance.csv.gz": "33ae97e296b797ef8e5a68e5b1e8e391ed563a3c2c1495de6e376ee797618013", "player_shift_dispositions.csv.gz": "c665ef85477c34a8accabff260a87111838a6f5f6c28228cab6c65fced23be82", "target_reconciliation.csv.gz": "f093d8108a5492a2bd1c7400e71b2fa8b2c782d66ee3cba855ba85e110166a47", "unresolved_issues.csv.gz": "b6b39dcb332963ff9f4a08d22ae6a4d958333a700db3daa32f489273e88614fb"}, "base_commit": "33c6b8fad5c36fd7749557c6b56bb21898e33135", "canonical_frame_sha256": "f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b", "expected_population": {"games": 4876, "pbp_events": 1510104, "seasons": {"2018": 1271, "2019": 1082, "2020": 868, "2021": 1312, "2022": 343}}, "official_artifacts": {"canonical_frame.csv": "f417a1272b2bb4adff5757dae398dd1000dd2284f43b6ccb7dd28eaae99edf2b", "official_team_sog_validation.csv": "46c8c732c4bcb4965c8eff9a4c7a5b06a03096059e2e58d5a489ab3597213038"}}, "v2_reference_source": {"canonical_games_sha256": "7cd2fc9a6e84470c177b704aa56ba328ad67522698244ce1f182ddcb9e439f52", "frozen_model_file_sha256": "032f8383e946260eee11128a83b2753e2aefd0207b8905cb2483d488d6ea9e59", "frozen_model_fit_games": 23222, "frozen_model_internal_sha256": "f9cb43fc2073425bbca6e26c8f473f975e065df6981495f535c9f5cf680542fb", "frozen_model_version": "nhl-prospective-2026-27-v2", "reference_code_commit": "3935814dfba0bd2e33fb282e450d41b89a58486f", "reference_code_sha256": "021a7364bb026240dfc2dd5aacba2f3981743484596e9c809bd3a2ebade57955"}}

## Components

1. Shot attempt hazard: ridge Poisson log-linear model with period, observed/generation strength, score state, time remaining in the period and game, home/away, and rolling team shot-for/shot-against quality.
2. Attempt outcome: separate ridge logistic models for on-target probability, blocked-vs-missed probability, and goal-vs-save probability. The goal model includes accepted shot-location distance/angle bands and accepted shot type.
3. Shot locations/types: deterministic reservoir sample of accepted historical event locations, sampled by generated strength state. Invalid or quarantined coordinates are not used.
4. Goaltending: population response only. No actual starter or goalie identity enters the fit or evaluation.
5. Penalties: estimated pooled event rate; generated as single two-minute minors, at most one active minor, with release on a power-play goal. No double minors, majors, coincidental penalties, delayed calls, team discipline, or OT penalties.
6. Regulation: three 20-minute periods. A tied game receives five-minute sudden-death 3v3 overtime. A remaining tie gets alternating best-of-three shootout attempts and sudden-death pairs. Shootout events are separate from regular SOG; only the winner's final-score representation receives the NHL one-goal convention. Shootout `period_clock_seconds` stores the attempt ordinal and carries `clock_semantics=attempt_order`, since a shootout has no game clock.

Each ordinary shot emits `SHOT_ATTEMPT` plus one outcome (`SHOT_BLOCKED`, `SHOT_MISSED`, `SHOT_SAVED`, or `GOAL`). SOG is derived from saves/goals, and all scores are recomputed from goal events. Invalid event states raise `SimulationInvariantError`.

## Forward evaluation

Simulation counts per game: development 128; final holdout 256. All values below are per-game means; paired differences use the same matchup set. Positive baseline-minus-model differences favor the fitted model.

| Metric | 2021 model | 2021 simple average | Paired delta (95% game bootstrap) | 2022 model | 2022 simple average | Paired delta (95% game bootstrap) |
|---|---:|---:|---:|---:|---:|---:|
| Team SOG CRPS | 3.777 | 3.958 | 0.181 (0.132, 0.229) | 3.870 | 4.098 | 0.227 (0.139, 0.320) |
| Team reg+OT goal CRPS | 0.998 | 0.997 | -0.002 (-0.014, 0.011) | 0.993 | 0.945 | -0.048 (-0.084, -0.013) |
| Home winner Brier | 0.2426 | 0.2536 | 0.0110 (0.0069, 0.0153) | 0.2424 | 0.2502 | 0.0078 (-0.0004, 0.0160) |
| Final score energy score | 1.587 | 1.587 | -0.000 (-0.021, 0.019) | 1.586 | 1.504 | -0.082 (-0.138, -0.030) |

2021 game count: 1312 (1292 SOG-eligible); 2022 final holdout: 343 (341 SOG-eligible). Event-outcome log loss/Brier, winner reliability bins, period SOG/goal MAE, exact final-score mass, Monte Carlo uncertainty, runtime, and per-game rows are in `EVALUATION.json`. Event-outcome diagnostics condition on each historical shot's observed pre-shot period, strength, score, and clock state. Full matchup simulations generate those states from their own event sequence.

Accounting failures: development 0/167936; holdout 0/87808. Mean home-SOG Monte Carlo SE: 0.353; mean home-win probability SE: 0.0309. Runtime: development 4750.1s, holdout 2448.4s.

## Existing model comparison

The frozen v2 artifact was **not** scored directly because its fit includes 2022, which would leak the final holdout. Instead, the published v2 `TeamStrength` method was re-fit on the same 2018–2020 development training window and 2018–2021 final training window. The source code, canonical game file, and frozen artifact were hash checked. The canonical file joined all 343 final holdout games by game ID; season, date, home/away labels, and official scores were asserted, then team IDs were checked against those labels. The goal target was the replayed accepted regular-plus-overtime score. The existing independent-Poisson score distribution and shootout tiebreak convention were retained, with the home shootout rate estimated from each training window. This score-only model has no team-SOG prediction, so SOG comparisons are not applicable.

The canonical xG columns are passed through only to preserve the v2 reference constructor's auxiliary xG fit. Its `mus()` prediction method uses the goal-fitted team ratings; evaluation-game xG and goals are not predictor inputs.

| Metric | 2021 v2 refit | 2021 stochastic | v2 minus stochastic (95% paired game bootstrap) | 2022 v2 refit | 2022 stochastic | v2 minus stochastic (95% paired game bootstrap) |
|---|---:|---:|---:|---:|---:|---:|
| Reg+OT team-goal CRPS | 0.986 | 0.998 | -0.012 (-0.026, 0.004) | 0.947 | 0.993 | -0.046 (-0.083, -0.010) |
| Winner Brier | 0.2382 | 0.2426 | -0.0044 (-0.0104, 0.0014) | 0.2439 | 0.2424 | 0.0015 (-0.0098, 0.0124) |
| Final-score energy score | 1.563 | 1.587 | -0.024 (-0.045, -0.003) | 1.500 | 1.586 | -0.086 (-0.140, -0.032) |

Positive paired deltas favor the stochastic simulator. V2 fit rows, Monte Carlo errors, per-game scores, and exact source pins are retained in `EVALUATION.json` and `TRAINING-DATA.json`.

## Limitations and next interfaces

This is a team-level event model, not a full NHL process model. It does not assign players, select lineups, model goalie identity, model line changes, infer possession, model rebounds, or simulate empty-net pulls. Shot opportunity times are exponential waiting times, not observed possession/shift sequences. Historical event coordinates and official targets are not equivalent to a tracking system. The limited minor-only penalty generator omits important special-teams states.

Next extension points are: (1) shooter opportunity allocation from current generated shot/team states; (2) player SOG distributions conditional on generated team opportunities and pregame player snapshots; (3) goalie-specific response, gated on verifiable pregame goalie identity; (4) scorer/assist allocation after a generated goal; (5) fuller penalty/service/manpower transitions; (6) lineup and shift deployment. Each attaches through generated event attributes and the existing pregame snapshot boundary.
