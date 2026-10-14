# NHL baseline follow-up: exploratory diagnostics

This follow-up preserves the preregistered baseline report. The 2025–26 breakdown is diagnostic only and was not used to tune anything. The 2022–24 results were already examined in the baseline report, so the additional comparisons here are exploratory, not a new untouched test. Market prices are not model features.

## Why Elo's 2025–26 Brier worsened

The deterioration is concentrated in the regular season: Elo Brier was 0.2524 over 1,312 regular-season games and 0.2404 over 82 playoff games. Overall home-win rate was 51.9%, versus 56.5% in 2024. Home wins were less common in the 2025–26 regular season (52.2%) than in 2024–25 (56.2%). Elo also looked too extreme: among 952 home-favored games its average probability was 0.603 versus a 0.538 home-win rate; among 442 road-favored games, it forecast 0.429 home probability versus 0.480 realized. In its 0.60+ bin, 0.666 predicted versus 0.586 realized over 430 games. This points to excessive probability spread and lower home advantage as diagnostic hypotheses, not proven causes. Full favorite and probability-band breakdowns are in `next_questions_elo_calibration_segments.csv`.

| Season | Phase | Games | Home win rate | Elo Brier | xG-derived Brier | Goals+xG Brier | Elo+xG Brier |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2022–23 | Regular | 1312 | 0.5236 | 0.2352 | 0.2430 | 0.2415 | 0.2344 |
| 2022–23 | Playoffs | 88 | 0.4659 | 0.2599 | 0.2551 | 0.2580 | 0.2559 |
| 2023–24 | Regular | 1312 | 0.5412 | 0.2352 | 0.2426 | 0.2409 | 0.2343 |
| 2023–24 | Playoffs | 88 | 0.4773 | 0.2429 | 0.2467 | 0.2480 | 0.2419 |
| 2024–25 | Regular | 1307 | 0.5624 | 0.2393 | 0.2417 | 0.2417 | 0.2363 |
| 2024–25 | Playoffs | 86 | 0.6047 | 0.2325 | 0.2334 | 0.2360 | 0.2304 |
| 2025–26 | Regular | 1312 | 0.5221 | 0.2524 | 0.2466 | 0.2466 | 0.2468 |
| 2025–26 | Playoffs | 82 | 0.4756 | 0.2404 | 0.2475 | 0.2461 | 0.2406 |

## Exploratory Elo+xG score model

Added pre-game Elo rating difference to the rolling xG Poisson model. Alpha was selected on 2018–21 goal likelihood (`[{'alpha': 0.01, 'validation_team_goal_nll': 1.9256209912852589}, {'alpha': 0.1, 'validation_team_goal_nll': 1.933137787527906}, {'alpha': 1.0, 'validation_team_goal_nll': 1.9459440518408637}, {'alpha': 10.0, 'validation_team_goal_nll': 1.9505259247099653}]`; selected 0.01) and coefficients were refit through 2021. It uses no player, goalie, or market inputs. Since 2022–24 has already been examined, treat this as exploratory evidence; 2026–27 is the next prospective evaluation.

| Season | Games | Goals MAE / team | Total goals MAE | Joint goal NLL |
| ---: | ---: | ---: | ---: | ---: |
| 2022–23 | 1400 | 1.3889 | 1.8281 | 3.8605 |
| 2023–24 | 1400 | 1.3816 | 1.8590 | 3.8687 |
| 2024–25 | 1393 | 1.3875 | 1.8571 | 3.8729 |
| 2025–26 | 1394 | 1.3633 | 1.8261 | 3.8527 |

## Moneyline Brier differences versus Elo

Negative means the named model has lower Brier than Elo. Intervals are paired game bootstrap intervals; the 2022–24 interval is descriptive because that sample has already been inspected.

| Sample | Model | Difference | 95% interval | Games |
| --- | --- | ---: | ---: | ---: |
| exploratory previously-seen 2022-2024 | xG score dist. | 0.00550 | [0.00203, 0.00891] | 4193 |
| exploratory previously-seen 2022-2024 | goals+xG score dist. | 0.00463 | [0.00143, 0.00779] | 4193 |
| exploratory previously-seen 2022-2024 | Elo+xG Poisson | -0.00164 | [-0.00327, -0.00007] | 4193 |
| diagnostic only 2025-2026 | xG score dist. | -0.00503 | [-0.01002, -0.00010] | 1394 |
| diagnostic only 2025-2026 | goals+xG score dist. | -0.00516 | [-0.00995, -0.00048] | 1394 |
| diagnostic only 2025-2026 | Elo+xG Poisson | -0.00529 | [-0.00779, -0.00280] | 1394 |

## Paired score-loss differences for Elo+xG

Negative favors the Elo+xG model. These are exploratory paired game-bootstrap intervals.

| Sample | Comparator | Metric | Difference | 95% interval | Games |
| --- | --- | --- | ---: | ---: | ---: |
| exploratory previously-seen 2022-2024 | B3 | per_game_team_goals_mae | -0.01126 | [-0.01535, -0.00714] | 4193 |
| exploratory previously-seen 2022-2024 | B3 | joint_goal_nll | -0.02634 | [-0.03134, -0.02130] | 4193 |
| exploratory previously-seen 2022-2024 | B4 | per_game_team_goals_mae | -0.01863 | [-0.02458, -0.01267] | 4193 |
| exploratory previously-seen 2022-2024 | B4 | joint_goal_nll | -0.03318 | [-0.04034, -0.02619] | 4193 |
| exploratory previously-seen 2022-2024 | B5 | per_game_team_goals_mae | -0.01285 | [-0.01781, -0.00787] | 4193 |
| exploratory previously-seen 2022-2024 | B5 | joint_goal_nll | -0.01850 | [-0.02413, -0.01291] | 4193 |
| exploratory previously-seen 2022-2024 | B6 | per_game_team_goals_mae | -0.01211 | [-0.01679, -0.00746] | 4193 |
| exploratory previously-seen 2022-2024 | B6 | joint_goal_nll | -0.01368 | [-0.01907, -0.00810] | 4193 |
| diagnostic only 2025-2026 | B3 | per_game_team_goals_mae | -0.01208 | [-0.01835, -0.00595] | 1394 |
| diagnostic only 2025-2026 | B3 | joint_goal_nll | -0.02657 | [-0.03435, -0.01922] | 1394 |
| diagnostic only 2025-2026 | B4 | per_game_team_goals_mae | -0.00734 | [-0.01551, 0.00096] | 1394 |
| diagnostic only 2025-2026 | B4 | joint_goal_nll | -0.01454 | [-0.02443, -0.00478] | 1394 |
| diagnostic only 2025-2026 | B5 | per_game_team_goals_mae | 0.00054 | [-0.00589, 0.00689] | 1394 |
| diagnostic only 2025-2026 | B5 | joint_goal_nll | -0.00202 | [-0.00966, 0.00557] | 1394 |
| diagnostic only 2025-2026 | B6 | per_game_team_goals_mae | -0.00008 | [-0.00694, 0.00677] | 1394 |
| diagnostic only 2025-2026 | B6 | joint_goal_nll | 0.00149 | [-0.00689, 0.00963] | 1394 |

## Files

`next_questions_metrics_by_season.csv` contains regular/playoff moneyline results for Elo, xG-derived, goals+xG, and Elo+xG forecasts. `next_questions_elo_calibration_segments.csv` breaks Elo calibration by favorite status and predicted-probability bands. `next_questions_paired_goals.csv` contains paired Elo+xG score-loss comparisons. `next_questions_predictions.csv` contains per-game exploratory predictions. Existing locked results remain in `nhl_baseline_ladder_results.md`.
