# FBS Game-Winner Baseline — Phase 1

Generated: 2026-10-17 22:01 UTC
Model version: `fbs-game-winner-baselines-v1-20261017`
Research brief: `docs/BRIEF-fbs-game-prediction-research-plan.md`

## Result

This is the first reproducible, chronological game-winner benchmark. It forecasts the probability that the schedule's home team wins. It uses no player-prop, player, box-score, or play-by-play features. The 2022 season warms the models; evaluation begins in 2023. 2025 is evaluated across the full season with earlier 2025 results entering later forecasts only after the embargo. 2026 is a forward sample through the source snapshot dated 2026-10-17.

| Period | Model | Games | Brier | Log loss | Accuracy | Predicted / actual | Reliability | Resolution |
|---|---|---|---|---|---|---|---|---|
| 2023-2025 | Historical home/neutral base rate | 2398 | 0.2427 | 0.6785 | 0.5817 | 0.5820 / 0.5855 | 0.0002 | 0.0002 |
| 2023-2025 | Chronological Elo | 2398 | 0.2133 | 0.6162 | 0.6651 | 0.5761 / 0.5855 | 0.0097 | 0.0372 |
| 2023-2025 | Opponent-adjusted margin strength | 2398 | 0.2155 | 0.6158 | 0.6355 | 0.6771 / 0.5855 | 0.0165 | 0.0417 |
| 2025 holdout | Historical home/neutral base rate | 808 | 0.2420 | 0.6771 | 0.5842 | 0.5854 / 0.5953 | 0.0009 | 0.0000 |
| 2025 holdout | Chronological Elo | 808 | 0.2082 | 0.6053 | 0.6757 | 0.5747 / 0.5953 | 0.0104 | 0.0405 |
| 2025 holdout | Opponent-adjusted margin strength | 808 | 0.2125 | 0.6089 | 0.6522 | 0.6808 / 0.5953 | 0.0153 | 0.0405 |
| 2026 forward | Historical home/neutral base rate | 350 | 0.2346 | 0.6621 | 0.6314 | 0.5924 / 0.6314 | 0.0015 | 0.0000 |
| 2026 forward | Chronological Elo | 350 | 0.2051 | 0.5994 | 0.6886 | 0.5878 / 0.6314 | 0.0107 | 0.0357 |
| 2026 forward | Opponent-adjusted margin strength | 350 | 0.2071 | 0.5976 | 0.6571 | 0.7169 / 0.6314 | 0.0213 | 0.0466 |

Brier is the primary score; lower is better. Reliability and resolution use fixed 0.10 probability bins, with lower reliability error and higher resolution preferred. Calibration is shown as average predicted probability / actual home-win rate. The reported Brier decomposition terms are binned summaries; their sum approximates the Brier score.

## Season results

| Season | Model | Games | Brier | Log loss | Accuracy |
|---|---|---|---|---|---|
| 2023 | Historical home/neutral base rate | 792 | 0.2441 | 0.6812 | 0.5745 |
| 2023 | Chronological Elo | 792 | 0.2138 | 0.6180 | 0.6717 |
| 2023 | Opponent-adjusted margin strength | 792 | 0.2163 | 0.6179 | 0.6351 |
| 2024 | Historical home/neutral base rate | 798 | 0.2421 | 0.6772 | 0.5865 |
| 2024 | Chronological Elo | 798 | 0.2179 | 0.6255 | 0.6479 |
| 2024 | Opponent-adjusted margin strength | 798 | 0.2179 | 0.6206 | 0.6190 |
| 2025 | Historical home/neutral base rate | 808 | 0.2420 | 0.6771 | 0.5842 |
| 2025 | Chronological Elo | 808 | 0.2082 | 0.6053 | 0.6757 |
| 2025 | Opponent-adjusted margin strength | 808 | 0.2125 | 0.6089 | 0.6522 |
| 2026 | Historical home/neutral base rate | 350 | 0.2346 | 0.6621 | 0.6314 |
| 2026 | Chronological Elo | 350 | 0.2051 | 0.5994 | 0.6886 |
| 2026 | Opponent-adjusted margin strength | 350 | 0.2071 | 0.5976 | 0.6571 |

## Data coverage and reconciliation

| Season | All schedule rows | FBS-vs-FBS scheduled | Completed FBS-vs-FBS | Completed FBS-vs-FCS | ESPN final / CFB incomplete | Canceled or not final |
|---|---|---|---|---|---|---|
| 2022 | 3713 | 776 | 776 | 120 | 0 | 0 |
| 2023 | 3734 | 792 | 792 | 118 | 0 | 0 |
| 2024 | 3801 | 799 | 798 | 121 | 0 | 1 |
| 2025 | 3831 | 808 | 808 | 126 | 0 | 0 |
| 2026 | 3679 | 761 | 350 | 121 | 11 | 411 |

- The all-division SportsDataverse `cfb_schedules` release supplies historical FBS membership (`fbs_game` / `fbs_participant`), season-specific conferences, schedule phase, neutral-site and venue IDs. The ESPN-native schedule supplies event home/away orientation, kickoff timestamps, final status and scores.
- All completed FBS-participant rows in 2022–25 joined to an ESPN schedule row. Seven 2022–24 FBS games have reversed home/away orientation between the two schedule releases; ESPN orientation and scores reconcile to the CFBD scores after swapping sides. The model uses that orientation and reorients conference and rank metadata by team ID.
- In 2024, one canceled FBS-vs-FBS game carries a 0–0 placeholder in the all-division schedule; it is excluded because ESPN does not mark it final.
- In the 2026 snapshot, 11 ESPN-final FBS-vs-FBS games were not yet marked completed by the all-division schedule. ESPN final rows are used for those outcomes; the source lag is visible in the coverage table.
- The 2026 schedule table is `cfb_schedules_2026_snapshot_20261017.parquet`, fetched separately to preserve the earlier cached file.
- Local Saturday classification uses the home team's IANA timezone for non-neutral games and a venue-ID timezone match for neutral sites. 1907 of 2398 evaluated 2023–25 games are Saturday, 378 are off-Saturday, and 113 have unknown local venue timezone and are excluded from those two slices.
- Lower-conference labels are descriptive, retrospective season groupings: non-SEC/Big 12 conferences with no Top-10-ranked team in schedule rank fields and no CFP participant. These labels are not model features. 2026 postseason status is unknown, so those games are not assigned to the lower-non-elite group.
- The cached betting releases contain spread/total fields but no timestamped moneyline prices. No market probability or market favorite label is used. Favorite/underdog error slices use each candidate model's own pregame pick.

## Paired Brier comparisons

Negative differences favor the candidate. Intervals are paired game-level bootstrap intervals (2,000 resamples); they do not account for dependence between games involving the same teams.

| Period | Candidate | Control | Games | Δ Brier (candidate minus control) | 95% interval |
|---|---|---|---|---|---|
| Walk-forward 2023-2025 | Chronological Elo | Historical home/neutral base rate | 2398 | -0.0294 | [-0.0328, -0.0260] |
| Walk-forward 2023-2025 | Opponent-adjusted margin strength | Historical home/neutral base rate | 2398 | -0.0272 | [-0.0319, -0.0224] |
| Walk-forward 2023-2025 | Opponent-adjusted margin strength | Chronological Elo | 2398 | 0.0023 | [-0.0016, 0.0065] |
| 2025 complete season | Chronological Elo | Historical home/neutral base rate | 808 | -0.0338 | [-0.0400, -0.0275] |
| 2025 complete season | Opponent-adjusted margin strength | Historical home/neutral base rate | 808 | -0.0295 | [-0.0375, -0.0218] |
| 2025 complete season | Opponent-adjusted margin strength | Chronological Elo | 808 | 0.0042 | [-0.0031, 0.0115] |
| 2026 current forward | Chronological Elo | Historical home/neutral base rate | 350 | -0.0295 | [-0.0389, -0.0198] |
| 2026 current forward | Opponent-adjusted margin strength | Historical home/neutral base rate | 350 | -0.0275 | [-0.0405, -0.0143] |
| 2026 current forward | Opponent-adjusted margin strength | Chronological Elo | 350 | 0.0020 | [-0.0109, 0.0144] |

## Saturday, conference, and phase slices (2023–25)

| Slice | Model | Games | Brier | Log loss | Accuracy |
|---|---|---|---|---|---|
| Local kickoff day: Off-Saturday | Historical home/neutral base rate | 378 | 0.2518 | 0.6969 | 0.5317 |
| Local kickoff day: Off-Saturday | Chronological Elo | 378 | 0.2237 | 0.6380 | 0.6164 |
| Local kickoff day: Off-Saturday | Opponent-adjusted margin strength | 378 | 0.2379 | 0.6665 | 0.5847 |
| Local kickoff day: Saturday | Historical home/neutral base rate | 1907 | 0.2404 | 0.6739 | 0.5978 |
| Local kickoff day: Saturday | Chronological Elo | 1907 | 0.2097 | 0.6087 | 0.6807 |
| Local kickoff day: Saturday | Opponent-adjusted margin strength | 1907 | 0.2103 | 0.6037 | 0.6445 |
| Local kickoff day: Unknown | Historical home/neutral base rate | 113 | 0.2509 | 0.6950 | 0.4779 |
| Local kickoff day: Unknown | Chronological Elo | 113 | 0.2388 | 0.6704 | 0.5664 |
| Local kickoff day: Unknown | Opponent-adjusted margin strength | 113 | 0.2290 | 0.6505 | 0.6549 |
| Game phase: Bowl | Historical home/neutral base rate | 109 | 0.2531 | 0.6994 | 0.4495 |
| Game phase: Bowl | Chronological Elo | 109 | 0.2483 | 0.6899 | 0.5138 |
| Game phase: Bowl | Opponent-adjusted margin strength | 109 | 0.2489 | 0.6917 | 0.5963 |
| Game phase: Conference championship | Historical home/neutral base rate | 28 | 0.2442 | 0.6813 | 0.5714 |
| Game phase: Conference championship | Chronological Elo | 28 | 0.2366 | 0.6656 | 0.6071 |
| Game phase: Conference championship | Opponent-adjusted margin strength | 28 | 0.2341 | 0.6582 | 0.5714 |
| Game phase: Playoff | Historical home/neutral base rate | 25 | 0.2352 | 0.6633 | 0.6400 |
| Game phase: Playoff | Chronological Elo | 25 | 0.2287 | 0.6491 | 0.6000 |
| Game phase: Playoff | Opponent-adjusted margin strength | 25 | 0.1871 | 0.5578 | 0.7600 |
| Game phase: Regular season | Historical home/neutral base rate | 2236 | 0.2423 | 0.6776 | 0.5877 |
| Game phase: Regular season | Chronological Elo | 2236 | 0.2111 | 0.6117 | 0.6740 |
| Game phase: Regular season | Opponent-adjusted margin strength | 2236 | 0.2140 | 0.6122 | 0.6369 |
| Conference matchup: Lower non-elite conferences only | Historical home/neutral base rate | 718 | 0.2457 | 0.6845 | 0.5682 |
| Conference matchup: Lower non-elite conferences only | Chronological Elo | 718 | 0.2183 | 0.6270 | 0.6588 |
| Conference matchup: Lower non-elite conferences only | Opponent-adjusted margin strength | 718 | 0.2257 | 0.6388 | 0.6003 |
| Conference matchup: SEC/Big 12 involved | Historical home/neutral base rate | 571 | 0.2482 | 0.6895 | 0.5447 |
| Conference matchup: SEC/Big 12 involved | Chronological Elo | 571 | 0.2208 | 0.6319 | 0.6392 |
| Conference matchup: SEC/Big 12 involved | Opponent-adjusted margin strength | 571 | 0.2305 | 0.6495 | 0.6042 |
| Conference matchup: SEC/Big 12 vs lower non-elite | Historical home/neutral base rate | 107 | 0.2018 | 0.5957 | 0.8037 |
| Conference matchup: SEC/Big 12 vs lower non-elite | Chronological Elo | 107 | 0.1729 | 0.5314 | 0.8131 |
| Conference matchup: SEC/Big 12 vs lower non-elite | Opponent-adjusted margin strength | 107 | 0.1288 | 0.4194 | 0.8318 |

The `SEC/Big 12 vs lower non-elite` slice contains 107 games. Lower non-elite means the opposing conference had no Top-10-ranked team in the schedule rank fields and no CFP participant that season. This is a retrospective reporting label, never a prediction feature. Unknown-timezone neutral-site games remain separately visible.

Conference team-game rows below use each team's season-aligned conference. In same-conference matchups, both teams count as observations; probabilities and outcomes are converted to each team's win perspective.

| Conference team-games | Model | Team-games | Brier | Log loss | Accuracy |
|---|---|---|---|---|---|
| Conference team: ACC | Historical home/neutral base rate | 575 | 0.2481 | 0.6893 | 0.5530 |
| Conference team: ACC | Chronological Elo | 575 | 0.2295 | 0.6507 | 0.6035 |
| Conference team: ACC | Opponent-adjusted margin strength | 575 | 0.2386 | 0.6682 | 0.5878 |
| Conference team: American Athletic | Historical home/neutral base rate | 494 | 0.2460 | 0.6853 | 0.5648 |
| Conference team: American Athletic | Chronological Elo | 494 | 0.2073 | 0.6035 | 0.6781 |
| Conference team: American Athletic | Opponent-adjusted margin strength | 494 | 0.2138 | 0.6101 | 0.6275 |
| Conference team: Big 12 | Historical home/neutral base rate | 544 | 0.2482 | 0.6895 | 0.5496 |
| Conference team: Big 12 | Chronological Elo | 544 | 0.2357 | 0.6638 | 0.5938 |
| Conference team: Big 12 | Opponent-adjusted margin strength | 544 | 0.2468 | 0.6883 | 0.5790 |
| Conference team: Big Ten | Historical home/neutral base rate | 615 | 0.2385 | 0.6699 | 0.6049 |
| Conference team: Big Ten | Chronological Elo | 615 | 0.1958 | 0.5787 | 0.7024 |
| Conference team: Big Ten | Opponent-adjusted margin strength | 615 | 0.1863 | 0.5487 | 0.7073 |
| Conference team: Conference USA | Historical home/neutral base rate | 367 | 0.2390 | 0.6710 | 0.6022 |
| Conference team: Conference USA | Chronological Elo | 367 | 0.2139 | 0.6181 | 0.6649 |
| Conference team: Conference USA | Opponent-adjusted margin strength | 367 | 0.2143 | 0.6143 | 0.6322 |
| Conference team: FBS Independents | Historical home/neutral base rate | 106 | 0.2472 | 0.6877 | 0.5755 |
| Conference team: FBS Independents | Chronological Elo | 106 | 0.2001 | 0.5876 | 0.7075 |
| Conference team: FBS Independents | Opponent-adjusted margin strength | 106 | 0.2108 | 0.6035 | 0.6509 |
| Conference team: Mid-American | Historical home/neutral base rate | 432 | 0.2368 | 0.6664 | 0.6157 |
| Conference team: Mid-American | Chronological Elo | 432 | 0.2047 | 0.5976 | 0.6852 |
| Conference team: Mid-American | Opponent-adjusted margin strength | 432 | 0.2027 | 0.5859 | 0.6505 |
| Conference team: Mountain West | Historical home/neutral base rate | 422 | 0.2409 | 0.6748 | 0.5972 |
| Conference team: Mountain West | Chronological Elo | 422 | 0.2179 | 0.6269 | 0.6659 |
| Conference team: Mountain West | Opponent-adjusted margin strength | 422 | 0.2175 | 0.6222 | 0.6374 |
| Conference team: Pac-12 | Historical home/neutral base rate | 192 | 0.2475 | 0.6882 | 0.5521 |
| Conference team: Pac-12 | Chronological Elo | 192 | 0.2108 | 0.6111 | 0.6823 |
| Conference team: Pac-12 | Opponent-adjusted margin strength | 192 | 0.2152 | 0.6150 | 0.6458 |
| Conference team: SEC | Historical home/neutral base rate | 552 | 0.2381 | 0.6691 | 0.5978 |
| Conference team: SEC | Chronological Elo | 552 | 0.1958 | 0.5789 | 0.7156 |
| Conference team: SEC | Opponent-adjusted margin strength | 552 | 0.1935 | 0.5642 | 0.6739 |
| Conference team: Sun Belt | Historical home/neutral base rate | 497 | 0.2442 | 0.6815 | 0.5734 |
| Conference team: Sun Belt | Chronological Elo | 497 | 0.2237 | 0.6387 | 0.6660 |
| Conference team: Sun Belt | Opponent-adjusted margin strength | 497 | 0.2283 | 0.6463 | 0.6097 |

## Favorite and strength-difference slices (2023–25)

Favorite status is each model's own pregame pick. Margin bands use the opponent-adjusted model's predicted score-margin difference before kickoff.

| Slice | Model | Games | Brier | Log loss | Accuracy |
|---|---|---|---|---|---|
| Favorite status: Model selects home | Historical home/neutral base rate | 2247 | 0.2420 | 0.6772 | 0.5892 |
| Favorite status: Model selects away | Historical home/neutral base rate | 151 | 0.2525 | 0.6981 | 0.4702 |
| Favorite status: Model selects home | Chronological Elo | 1865 | 0.2097 | 0.6083 | 0.6611 |
| Favorite status: Model selects away | Chronological Elo | 533 | 0.2258 | 0.6439 | 0.6792 |
| Favorite status: Model selects home | Opponent-adjusted margin strength | 2182 | 0.2150 | 0.6139 | 0.6214 |
| Favorite status: Model selects away | Opponent-adjusted margin strength | 216 | 0.2213 | 0.6347 | 0.7778 |
| Margin-model strength <= -14 | Historical home/neutral base rate | 0 | — | — | — |
| Margin-model strength <= -14 | Chronological Elo | 0 | — | — | — |
| Margin-model strength <= -14 | Opponent-adjusted margin strength | 0 | — | — | — |
| Margin-model strength -14 to -7 | Historical home/neutral base rate | 20 | 0.2891 | 0.7723 | 0.4000 |
| Margin-model strength -14 to -7 | Chronological Elo | 20 | 0.1551 | 0.4956 | 0.9000 |
| Margin-model strength -14 to -7 | Opponent-adjusted margin strength | 20 | 0.1382 | 0.4613 | 0.9000 |
| Margin-model strength -7 to 0 | Historical home/neutral base rate | 196 | 0.2972 | 0.7886 | 0.2806 |
| Margin-model strength -7 to 0 | Chronological Elo | 196 | 0.2109 | 0.6136 | 0.7347 |
| Margin-model strength -7 to 0 | Opponent-adjusted margin strength | 196 | 0.2298 | 0.6524 | 0.7653 |
| Margin-model strength 0 to 7 | Historical home/neutral base rate | 746 | 0.2766 | 0.7471 | 0.3834 |
| Margin-model strength 0 to 7 | Chronological Elo | 746 | 0.2509 | 0.6949 | 0.5174 |
| Margin-model strength 0 to 7 | Opponent-adjusted margin strength | 746 | 0.2740 | 0.7422 | 0.4102 |
| Margin-model strength 7 to 14 | Historical home/neutral base rate | 1023 | 0.2284 | 0.6497 | 0.6647 |
| Margin-model strength 7 to 14 | Chronological Elo | 1023 | 0.2207 | 0.6331 | 0.6657 |
| Margin-model strength 7 to 14 | Opponent-adjusted margin strength | 1023 | 0.2184 | 0.6273 | 0.6686 |
| Margin-model strength >= 14 | Historical home/neutral base rate | 413 | 0.1886 | 0.5691 | 0.8862 |
| Margin-model strength >= 14 | Chronological Elo | 413 | 0.1309 | 0.4394 | 0.8862 |
| Margin-model strength >= 14 | Opponent-adjusted margin strength | 413 | 0.0998 | 0.3491 | 0.8862 |

## Model definitions and leakage controls

1. **Historical home/neutral base rate:** expanding prior FBS-vs-FBS home-win rate, separated by neutral-site status, with a Beta(1,1) smoothing prior.
2. **Chronological Elo:** team ratings start at 1500; logistic scale 400; fixed 55-point home advantage (zero at neutral sites); K=20; 25% offseason regression toward 1500; FBS-vs-FBS and FBS-vs-FCS outcomes update ratings.
3. **Opponent-adjusted margin strength:** ridge least-squares team ratings from previous score margins, with a fitted home-advantage term, fixed ridge penalty 15, and season weights halved per prior season. It trains on FBS-participant games and estimates probability with a normal margin CDF; the scale is the prior in-sample FBS-vs-FBS residual standard deviation, floored at 15 points.

For every UTC kickoff date, predictions are made before adding games kicked off on that date or the immediately preceding UTC date. The last eligible kickoff date is therefore at least 24 hours before the forecast date; this conservative date embargo avoids relying on unavailable final-whistle timestamps. Each CSV row records that game's actual kickoff as the prediction cutoff. Neutral games receive no standard home-field advantage. No random split or future season result enters a prediction. Predictions, cutoff, source phase, teams, actual scores, and model probabilities are in `research/fbs/fbs_game_winner_predictions.csv`.

## Limitations and next experiment

- The base-rate and Elo results are the cleanest first controls. Margin-strength probabilities rely on a normal approximation and an in-sample residual scale, so calibration is a known limitation; the paired results decide whether it merits further work.
- The current 2026 sample is incomplete and is not a full-season validation.
- Conference slices are uneven, and Saturday coverage omits neutral sites without a venue timezone in the available reference file.
- No timestamped historical moneyline data is available in the cached betting releases, so the sportsbook comparison is unavailable.
- **Decision:** Elo is the lead result-only baseline: Brier 0.2133 versus 0.2155 for the margin-strength probability. The paired margin-minus-Elo Brier difference is 0.0023 (95% interval -0.0016 to 0.0065), so the margin model does not establish an improvement on the primary metric. It also predicts a 0.6771 average home-win probability against a 0.5855 observed rate, showing material overprediction. Keep Elo and the base rate as benchmarks; do not add team-stat features yet. The next justified experiment is chronological probability calibration for margin strength, judged against frozen Elo on the same games.

## Reproduction

`/root/legendarypicks/backend/venv/bin/python backend/fbs_game_winner_baseline.py`
