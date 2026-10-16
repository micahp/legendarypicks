# NFL model card

**Scope:** NFL regular-season game forecasts, player projections and team playoff-odds simulations implemented in this repository. The game forecasts are locked as separate model versions. This card describes the code and validation evidence available on 2026-10-16; it is not a claim of betting advantage.

## Game forecasts

| Model | Method | Operational status |
|---|---|---|
| `nfl-v1` points model | Recency-weighted team offense/defense points ratings with a prior carried from the previous season; fitted expected points and a Normal margin-to-win-probability link | Current adopted/legacy baseline |
| `nfl-v2` EPA (Spec A EPA v2, play-by-play) | Pass and rush EPA offense/defense ratings, converted to points and calibrated on a prior season | Trial only; not adopted |
| `nfl-v1+elo stack` | Frozen v1 margin plus a 538-style Elo gap in a fitted linear stack | Research challenger; the lock code labels it trial |

The v1 lock version records the frozen settings: half-life 6 weeks, margin cap 14, prior strength 4 games, prior shrinkage one third, and win-probability scale `sigma=13.295`. It fits only on scored regular-season games before the target week. The preseason prior comes from the previous season and is shrunk toward the league mean. Neutral-site status affects home advantage. A lock is created from 90 minutes before kickoff up to kickoff; later runs cannot replace it. The shared ledger retains later unlocked runs for audit, while grading uses the first lock for each model version.

The v2 implementation models pass and rush EPA separately for offense and defense, weights recent play-by-play more heavily, carries shrunken previous-season ratings forward, and calibrates expected points and margin scale from prior-season walk-forward predictions. It requires complete earlier game results and play-by-play. Its historical holdout did not establish an improvement, so it remains a challenger.

The Elo stack combines the frozen v1 margin with an Elo difference and home-field term, fits its coefficients and residual scale on earlier seasons, and preserves v1's projected total. Its retrospective test improved Brier over v1 in the reported pooled seasons, but the API still treats it as experimental. The prospective evaluation should complete before changing the operational default.

## Targets, grades, and validation

The game model outputs projected home and away points, margin, total, and home-win probability. The grader records winner-probability Brier and log loss, margin and total absolute errors, and ATS result against the market line captured with the lock. Ties are handled separately from decisive win/loss outcomes. Market comparisons use the captured line, not a subsequently updated schedule value.

For a binary winner target, Brier is the mean squared difference between predicted home-win probability and the observed outcome (1 for a home win, 0 for an away win). Zero is perfect; lower is better. A 50/50 forecast scores 0.25 on a balanced outcome set. The captured, de-vigged market probability is the stronger practical benchmark.

| Model and evaluation | Brier (n) | Reference Brier | Readout |
|---|---:|---:|---|
| `nfl-v1`, 2025 holdout | 0.2288 (255) | 0.2500 50/50; 0.2497 constant 57% home; 0.2137 closing market | Beats naive references; worse than market |
| `nfl-v2` EPA, 2025 second look | 0.2291 (255) | 0.2288 `nfl-v1` on the same games | No improvement; paired difference +0.0003, 95% CI [−0.0083, +0.0087] |
| v1 + Elo research stack, 2011–2023 | 0.2197 (3,158) | 0.2229 recalibrated v1; 0.2104 closing market | Retrospective improvement over v1; still worse than market |

### Additional historical Brier benchmark markers

These results come from different seasons and evaluations, so they provide context rather than a like-for-like ranking against the locked model results above.

| Forecasting system | Brier score | Context |
|---|---:|---|
| Coin-flip probabilities | 0.250 | Mathematical baseline |
| Legendary Picks v1 | 0.2225 | 2024 development season |
| Legendary Picks v1 | 0.2288 | 2025 frozen evaluation |
| Historical NFL Elo benchmark | 0.222 | Independent 2012–2025 project |
| Historical NFL predictive model | 0.216 | Same project's more complex model |
| Vegas closing moneylines | 0.211 | Same project's market benchmark |
| FiveThirtyEight | 0.208 | Actual 2020 regular season |

The frozen v1 configuration was selected on 2024 and evaluated once on the 2025 holdout. Its mean absolute margin error was 10.67 points versus 9.97 for the spread, and total error was 10.61 versus 10.17 for the closing total. The sample is one season and roughly 255 games, so differences are uncertain. The Elo comparison is retrospective, not prospective confirmation, and does not change the operational default. The EPA challenger failed its adoption gate.

## Playoff odds

The separate team playoff-odds job fits regular-season offense and defense ratings, then simulates remaining games and applies NFL seeding and tiebreaking rules. It reports playoff, division, bye, seed, and wins probabilities. The current default score method is `placeholder-split-40` (`nfl-playoff-odds-v1.2`). A historical-score sampling option (`nfl-playoff-odds-v1.3`) passed most distribution checks but failed the pre-registered across-team scoring-spread gate, so it is not the default. Reported playoff and division probabilities were close between methods and within simulation noise; the season-scoring spread failure remains material.

The playoff-probability Brier benchmark is 0.246 for the naive 14-of-32 team playoff-rate forecast. In the 2020–2025 historical comparison (384 team forecasts), the results were:

| Simulation method and seed | Playoff Brier | Division Brier |
|---|---:|---:|
| Placeholder A | 0.13262 | 0.12121 |
| Placeholder B | 0.13319 | 0.12072 |
| Historical scores A | 0.13277 | 0.12135 |
| Historical scores B | 0.13190 | 0.12142 |

The seed-level differences were within simulation noise. This result evaluates playoff odds, not weekly game-winner forecasts.

## Player projections

The live player route is `GET /api/projections/player/{id}` (`backend/routers/players/projections.py`), backed
by `backend/analytics/projections.py`. It is Marcel-lite, not a fitted model. `project_stat` returns a
recency-weighted mean (0.5 over the last five games, 0.3 over the last ten, 0.2 over the season) plus
empirical floor, median and ceiling percentiles. `prob_over` returns the share of the player's own
same-season games in which the stat beat the line, with no shrinkage and no fitted distribution. Both are
computed per request from `player_game_logs`; nothing is stored. Below three games in the season the route
returns no projection at all, so it serves nothing in weeks 2 and 3.

Graded on 2026 sportsbook props, on `picks.dev.db` 2026-10-16, on the 14,431 items (354 player-games) it can
actually serve, which are weeks 4 and 5:

| Target | Live route | Reference |
|---|---:|---:|
| P(over) Brier | 0.3082 | 0.2500 constant 0.5; 0.2463 de-vigged market |

The served P(over) is worse than a coin flip. The cause is sample size, not the formula: with three or four
prior games a hit rate can only be 0, 1/4, 1/3, 1/2, 2/3, 3/4 or 1, and it is emitted as a probability. A
hit rate of 0 over three games renders as 0.000 and the overs land 50.5% of the time. The same route replayed
over the whole season, target game included, scores 0.1911, which would read as beating the market; that
number is look-ahead, not accuracy. Method, exclusions and the full calibration table are in
`RESULTS-nfl-prop-baseline-2026-10-16.md` on `scratch/spec-b-rebase`.

A second engine exists on `scratch/spec-b-rebase`, not merged: `backend/nfl_player_projection_v2.py` with job
`nfl_player_projections_job.py`. It is **Spec B volume x share x efficiency** (box scores, not play-by-play):
team volume, the player's share of it, and his per-opportunity efficiency, then a simulated distribution. It
projects targets, receptions, receiving yards and TDs, carries, rushing and QB passing, and returns a mean, p10,
p90 and P(over) from 4,000 simulated draws.

| Target | v2 | Marcel-lite | Read |
|---|---:|---:|---|
| Receiving yards MAE, 2025 | 15.910 | 16.431 | gain, interval excludes zero |
| Receptions MAE, 2025 | 1.216 | 1.237 | small gain |
| Targets MAE, 2025 | 1.578 | 1.589 | tie |
| Rushing yards MAE, 2025 | 6.602 | 6.536 | tie |
| Carries MAE, 2025 | 1.182 | 1.108 | worse, not published |
| QB passing yards MAE, 2025 | 59.32 | 63.46 | gain |

The MAE rows are branch results from `docs/RESULTS-player-projection-v2-2026-10-12.md`, measured on 2025. Props
exist for 2026 only, so the probability comparison is a different season and a different population.

On the items both can grade (2026 weeks 4 and 5, 14,431 items on 354 player-games), v2 scores 0.2706 against
the live route's 0.3082, an improvement of 0.0376 with the interval clustered by player-game excluding zero.
v2 still loses to the market's 0.2463 by 0.0243, and that interval also excludes zero. On its own larger
population, which includes the 19,088 items (57%) where the live route serves nothing, v2 scores 0.2747
against the market's 0.2460.

### How the player numbers relate to the game numbers

The game-winner Brier in `Targets, grades, and validation` and these prop Briers are not the same target or
the same population, so they are not ranked in one table. The market's own Brier differs between them (0.2137
for the 2025 game holdout, 0.2460 for the 2026 props), so the quantity that is comparable across the two is
the gap to market:

| Model | Brier | Market | Gap to market |
|---|---:|---:|---:|
| `nfl-v1` game winner, 2025 holdout | 0.2288 | 0.2137 | +0.0151 |
| Spec B player props, 2026 weeks 2 to 5 | 0.2747 | 0.2460 | +0.0287 |
| Live Marcel-lite props, 2026 weeks 4 and 5 | 0.3082 | 0.2463 | +0.0619 |

Read on that axis: the game model is 0.015 behind the market, the Spec B player engine is 0.029 behind, and the
projection the site serves today is 0.062 behind.

**External marker (self-reported):** @ManiBetz reports an NFL player-prop Brier of about 0.24
([projexions.io](https://projexions.io/)). It is self-reported and we cannot check it: his public pages carry a
betting record (171-132 over 303 settled plays, +35.63u, ROI +11.8%) and no Brier, so neither the number nor
the population behind it is verifiable. Two differences rule out a like-for-like reading: his card is only the
plays where he disagrees most with the market, while our 0.2747 covers every sportsbook line on 920
player-games, and his own project page states the engine "isn't built to be calibrated" and that its raw
probabilities "run more confident than reality." Recorded as the nearest outside marker for this task, not as a
verified score.

The two levels are not connected. `game_projections` holds one row per game and no code turns it into player
lines; the player engine reads its own logs and team-share history instead. Player volume ignores the
projected game script (a margin-based adjustment was tested and rejected on 2025 MAE). Availability is not an
input to any live projection. The props page runs on Marcel-lite, so the graded prop numbers above are not the
numbers the page shows. Nothing checks that a player forecast agrees with the team forecast for the same game.
`docs/NFL-DATA-INVENTORY.md` section 7 is the full inventory of what is live, what is branch-only and what is
not connected.

## Next steps

Ordered by what unblocks the most, with the measurement that would settle each.

1. **Decide on the served P(over) before anything else.** It is worse than a coin flip and the props page
   renders it beside a line with no sample size. Until a calibrated probability is served, that field should
   be gated or shown as what it is (a historical hit rate over n games), not as a probability.
2. **Merge decision for `scratch/spec-b-rebase`.** Merging lets the installed availability timer's snap ingest
   create `nfl_snap_team_sources` on PROD. The branch status doc lists that as a decision to make first, and it
   is the one item that needs an explicit call rather than more measurement.
3. **Separate the point gate from the probability gate.** The v2 gate optimizes MAE, which for right-skewed
   stats selects a median and is not the objective for P(over). A P_LOG variant that fixed bias and RMSE was
   rejected for raising MAE. Grade point accuracy and probability calibration separately, and stop promoting a
   model because its yardage MAE improved.
4. **Grade unique player-game-market groups, not items.** The 33,519 items are alternate lines on 902
   player-games, so item-level intervals are optimistic. Report clustered uncertainty beside every n.
5. **Capture before kickoff.** The 2026 numbers are walk-forward recomputations, not pre-kickoff captures.
   Store the predicted distribution and the market line before the game, then grade exactly those.
6. **Repair prop probability calibration.** The v2 P(over) barely moves across probability bins while the
   observed over rate stays near 0.5, which is the downward bias showing up as probability. This is the gap
   between v2 and the market.
7. **Connect the two levels.** Feed the game projection into player volume so the same game assumptions produce
   both, and test shared simulated game states rather than another margin multiplier. A simple multiplier
   already failed its backtest.
8. **Audit the settlement disagreements.** 38 graded items in the v2 grade and 15 in the baseline grade have a
   box-score outcome that disagrees with the book's own `prop_results.hit`. Neither has been investigated.
9. **Improve rushing or drop it.** Carries fail the gate against Marcel-lite, so rushing stays on the live
   route. Either fix the volume model or keep it out of the published set.

## Intended use and limits

Use forecasts as uncertain estimates, not as betting recommendations. The game model is not market-leading on the reported 2025 holdout. Early-season team ratings have less current-season evidence. The Elo challenger has retrospective results but needs prospective scoring. The EPA model is not adopted. The playoff simulation's history-score option failed a season-level distribution check. Injury, quarterback availability, and other late roster information are not comprehensively modeled in these game forecasts. The lock-time market quote is a benchmark and is not a feature in the game model.

The player projections are weaker than the game forecasts and should be read that way. The live P(over) is worse than a coin flip on the only weeks it can serve, and the live point projection is a recency-weighted mean over at most the current season, so it has no prior-season or role information and no availability input. The v2 engine on `scratch/spec-b-rebase` is better than the live route and is still not market-leading, and it is not merged or served. Nothing in the player layer is a betting signal.

The backend uses nflverse schedules, scores, and play-by-play. Data-source terms and permitted redistribution or commercial use should be checked before external use of derived outputs.

## References

- `backend/nfl_ratings.py`, `backend/nfl_ratings_data.py`, `backend/lock_nfl_week.py` — v1 ratings and locks.
- `backend/nfl_epa_model.py`, `backend/lock_nfl_epa.py` — EPA challenger.
- `backend/lock_nfl_elo.py`, `backend/nfl_elo_replica.py` — Elo stack.
- `backend/grade_nfl_locks.py` — locked-game scoring.
- `backend/nfl_sim.py`, `backend/jobs/nfl_playoff_odds.py` — playoff simulation.
- `backend/analytics/projections.py`, `backend/routers/players/projections.py`: the live Marcel-lite player projections.
- `backend/grade_nfl_prop_baseline.py`, `docs/RESULTS-nfl-prop-baseline-2026-10-16.md` (both on branch `scratch/spec-b-rebase`): the live P(over) baseline and the paired comparison against v2.
- `backend/grade_nfl_prop_probabilities.py`, `backend/nfl_player_projection_v2.py`, `docs/RESULTS-player-projection-v2-2026-10-12.md` (branch `scratch/spec-b-rebase`): the v2 engine and its grades.
- `docs/NFL-DATA-INVENTORY.md` section 7: what each projection is, where it is stored, and what is not connected.
- `docs/RESULTS-A3-nfl-backtest-2026-10-09.md` — v1 holdout and baselines.
- `docs/RESULTS-A9-nfl-epa-v2-backtest-2026-10-11.md` — EPA adoption-gate results.
- `docs/RESULTS-nfl-elo-and-era-2026-10-13.md` — Elo and feature research.
- `docs/RESULTS-nfl-sim-scores-2026-10-13.md` — playoff score-simulation validation.
