# Addendum — FBS joint score distribution calibration diagnosis

**Status remains NOT_ADOPTED.** This addendum diagnoses the existing run only. It does not refit a model, create a candidate, change a gate or threshold, or use 2025 for selection. The original result report is unchanged.

## What the candidate and coherence gate actually establish

The candidate uses one smoothed empirical joint score matrix per training fold: `p0_by_max_season` is built from all eligible historical games through each fold cutoff (`backend/fbs_joint_dist_2026.py:319-328, 486-495`). Its base score shape is not conditioned on teams or other game-specific score inputs. The only game-level adjustment is a tilt whose target is assigned directly from H1's home-win mass, `target_p_home_win = float(h1_joint[HOME_WIN].sum())` (`backend/fbs_joint_dist_2026.py:303-316, 530-542`). Thus candidate and H1 have exactly the same home-win probability. The candidate adds **zero win-probability information** over H1; its measured gains over H1 are from score-shape and dependence, not additional team signal.

The G-COHERENCE hard gate cannot fail as implemented. The margin and total PMFs used for scoring are computed by pushing forward the same joint matrix (`backend/fbs_joint_dist_2026.py:331-337, 385-400`). In the draw check, `sampled_total` and `sampled_margin` are first defined as `sampled_home + sampled_away` and `sampled_home - sampled_away`, then asserted equal to those same expressions (`backend/fbs_joint_dist_2026.py:546-560`). The reported 27,470,000-draw pass is therefore satisfaction by construction, not independent evidence of coherence. This is a disclosure only; neither the run nor gate is changed.

## Diagnostic method

PITs and interval-hit indicators below are read from `research/fbs/joint-dist-2026-10-19/per_game_scores.csv`; no model was rescored. Histograms use ten equal-width bins, with expected count 159.0 per bin in walk-forward and 80.7 in holdout. Seasonal KS tests compare randomized PITs with Uniform(0,1). Coverage entries are observed hit fractions in the order 50% / 80% / 90%; values above (below) nominal mean overcoverage (undercoverage).

The score CSV does not store candidate expected total. For the requested predicted-total split only, I reconstructed `E[home + away]` from the frozen fold empirical joint and each row's stored `candidate_theta`. This adds a grouping covariate, not a fit or a new outcome score. Terciles of `abs(p_h1_forecast_orientation - 0.5)` and deciles of reconstructed expected total are rank-balanced separately within each period. Stratum KS p-values are descriptive and unadjusted for multiple comparisons. The 2025 holdout rows remain diagnostic only and were not used to choose or tune anything.

## Ten-bin randomized PIT histograms

Counts in bins `[0,.1), [.1,.2), ..., [.9,1.0]`:

| Period | Outcome | n | 0–.1 | .1–.2 | .2–.3 | .3–.4 | .4–.5 | .5–.6 | .6–.7 | .7–.8 | .8–.9 | .9–1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Walk-forward | Margin | 1,590 | 115 | 175 | 167 | 132 | 149 | 171 | 181 | 190 | 169 | 141 |
| Walk-forward | Total | 1,590 | 169 | 200 | 173 | 169 | 159 | 147 | 168 | 150 | 124 | 131 |
| Holdout | Margin | 807 | 62 | 78 | 82 | 85 | 64 | 90 | 91 | 91 | 79 | 85 |
| Holdout | Total | 807 | 104 | 87 | 87 | 101 | 75 | 82 | 73 | 65 | 74 | 59 |

## KS by season

| Season | n | Margin KS D | Margin p | Total KS D | Total p |
|---:|---:|---:|---:|---:|---:|
| 2023 | 792 | 0.0373 | 0.2143 | 0.0546 | 0.01726 |
| 2024 | 798 | 0.0455 | 0.07087 | 0.0620 | 0.004164 |
| 2025 holdout | 807 | 0.0429 | 0.09931 | 0.0796 | 0.0000680 |

Total PIT rejects uniformity in each season, not just in one pooled period. Margin PIT does not reject within any one season at 0.05; the registered walk-forward pooled margin test still rejects (p=0.02220 in the original result), and the strata below show where that pooled departure sits.

## Shortest and central interval coverage

Observed coverage, shown as 50% / 80% / 90%:

| Season | Shortest margin | Shortest total | Central margin | Central total |
|---:|---:|---:|---:|---:|
| 2023 | 0.5013 / 0.8472 / 0.9356 | 0.4937 / 0.8220 / 0.9040 | 0.5480 / 0.8535 / 0.9381 | 0.4924 / 0.8169 / 0.9078 |
| 2024 | 0.4962 / 0.8346 / 0.9223 | 0.5376 / 0.8421 / 0.9135 | 0.5251 / 0.8434 / 0.9273 | 0.5263 / 0.8321 / 0.9236 |
| 2025 holdout | 0.5180 / 0.8265 / 0.9257 | 0.5204 / 0.8178 / 0.9257 | 0.5304 / 0.8290 / 0.9281 | 0.5366 / 0.8191 / 0.9232 |

At 80% and 90%, every season/outcome/interval construction is above nominal, indicating overcoverage. At 50%, coverage is close to nominal and mixed: 2023 total and 2024 shortest margin are slightly below nominal; the other entries are above. The interval picture is therefore mostly broad intervals at 80–90%, not a uniform undercoverage problem.

## PIT tail miss

Each tail has 0.10 expected under a uniform PIT. The high-tail interval is `[0.9,1.0]`; the low tail is `[0,0.1)`.

| Period | Outcome | Low tail count / rate (delta from .10) | High tail count / rate (delta from .10) |
|---|---|---:|---:|
| Walk-forward | Margin | 115 / 0.0723 (−2.77 pp) | 141 / 0.0887 (−1.13 pp) |
| Walk-forward | Total | 169 / 0.1063 (+0.63 pp) | 131 / 0.0824 (−1.76 pp) |
| Holdout | Margin | 62 / 0.0768 (−2.32 pp) | 85 / 0.1053 (+0.53 pp) |
| Holdout | Total | 104 / 0.1289 (+2.89 pp) | 59 / 0.0731 (−2.69 pp) |

For example, holdout total puts only 7.31% of PITs in `[0.9,1.0]` versus 10% expected, while 12.89% land below 0.1. That left-tail excess/right-tail deficit is consistent with realized totals falling low in the forecast CDF more often than uniformity allows.

## PIT by H1 probability extremity

Each period is split into equal-count terciles of `abs(p_h1 - 0.5)`. Cells report mean PIT / KS p / low-tail rate / high-tail rate; each tail is expected to be 0.10.

| Period | Tercile | n | `abs(p_h1−.5)` range | Margin: mean / p / low / high | Total: mean / p / low / high |
|---|---:|---:|---:|---:|---:|
| Walk-forward | 1 (nearest .5) | 530 | .0003–.1210 | .4854 / .00167 / .0509 / .0472 | .4791 / .1285 / .1057 / .0792 |
| Walk-forward | 2 | 530 | .1214–.2571 | .5150 / .3015 / .0717 / .0755 | .4642 / .00531 / .0962 / .0962 |
| Walk-forward | 3 (farthest .5) | 530 | .2579–.4782 | .5465 / .0000403 / .0943 / .1434 | .4627 / .00906 / .1170 / .0717 |
| Holdout | 1 (nearest .5) | 269 | .0004–.0609 | .4861 / .3011 / .1041 / .0669 | .4462 / .00589 / .1227 / .0706 |
| Holdout | 2 | 269 | .0611–.1280 | .4911 / .7570 / .0818 / .0743 | .4569 / .03739 / .1264 / .0706 |
| Holdout | 3 (farthest .5) | 269 | .1282–.3059 | .5838 / .0000132 / .0446 / .1747 | .4699 / .07365 / .1375 / .0781 |

Margin miscalibration is concentrated away from 0.5 in both periods. In walk-forward, the farthest tercile has a 14.34% high tail and mean PIT 0.5465, against 4.72% high-tail mass and mean 0.4854 in the nearest tercile. Holdout shows the same direction: 17.47% versus 6.69% high-tail mass, and mean PIT 0.5838 versus 0.4861. This is direct evidence consistent with a fixed-shape margin PMF failing as H1 win probability becomes more extreme. Total PIT is less monotone across these terciles and does not show the same clean pattern.

## PIT by predicted-total decile

Rows are rank-balanced deciles within each period, ordered by candidate `E[home + away]`. Cells report mean PIT / KS p / low-tail rate / high-tail rate; each tail is expected to be 0.10. Expected-total ranges are in score points.

| Period | Decile | n | Candidate E[total] range | Margin: mean / p / low / high | Total: mean / p / low / high |
|---|---:|---:|---:|---:|---:|
| Walk-forward | 1 | 159 | 55.1902–55.2610 | .5933 / .000277 / .0629 / .1761 | .4702 / .1177 / .0881 / .0755 |
| Walk-forward | 2 | 159 | 55.2618–55.3031 | .5362 / .2447 / .0692 / .1132 | .4466 / .01076 / .1195 / .0818 |
| Walk-forward | 3 | 159 | 55.3034–55.3354 | .4969 / .08456 / .0314 / .0818 | .5063 / .9603 / .0881 / .1069 |
| Walk-forward | 4 | 159 | 55.3355–55.3663 | .4863 / .1951 / .0629 / .0629 | .4786 / .5716 / .0692 / .0881 |
| Walk-forward | 5 | 159 | 55.3665–55.4138 | .4889 / .5969 / .1006 / .0692 | .4497 / .03182 / .1069 / .1132 |
| Walk-forward | 6 | 159 | 55.4151–55.7268 | .5709 / .000428 / .1006 / .1950 | .4836 / .8589 / .1069 / .0692 |
| Walk-forward | 7 | 159 | 55.7269–55.7480 | .5574 / .03677 / .0252 / .0881 | .4532 / .1586 / .0943 / .0503 |
| Walk-forward | 8 | 159 | 55.7482–55.7650 | .5223 / .04959 / .0189 / .0503 | .4383 / .02280 / .1258 / .0377 |
| Walk-forward | 9 | 159 | 55.7651–55.7804 | .4584 / .02624 / .0881 / .0252 | .4869 / .2226 / .1258 / .1195 |
| Walk-forward | 10 | 159 | 55.7806–55.8055 | .4457 / .1896 / .1635 / .0252 | .4732 / .5361 / .1384 / .0818 |
| Holdout | 1 | 81 | 54.9453–55.0128 | .6526 / .00000208 / .0247 / .2469 | .4916 / .7509 / .1111 / .0741 |
| Holdout | 2 | 81 | 55.0139–55.0329 | .5700 / .05971 / .0494 / .1235 | .4807 / .4562 / .1111 / .0741 |
| Holdout | 3 | 81 | 55.0330–55.0468 | .5670 / .1563 / .0617 / .1728 | .4697 / .3592 / .1728 / .0741 |
| Holdout | 4 | 80 | 55.0470–55.0595 | .5532 / .3213 / .0375 / .1500 | .4164 / .005149 / .1375 / .0875 |
| Holdout | 5 | 81 | 55.0597–55.0723 | .5027 / .8461 / .0988 / .0741 | .5036 / .5768 / .1111 / .0617 |
| Holdout | 6 | 81 | 55.0723–55.0842 | .4889 / .8574 / .0988 / .0494 | .4636 / .3008 / .1111 / .0988 |
| Holdout | 7 | 80 | 55.0842–55.0989 | .5481 / .07271 / .0875 / .0875 | .4710 / .8414 / .1000 / .0750 |
| Holdout | 8 | 81 | 55.0991–55.1110 | .4592 / .6064 / .1358 / .0864 | .4796 / .7971 / .0741 / .0864 |
| Holdout | 9 | 81 | 55.1113–55.1314 | .4709 / .1244 / .0741 / .0247 | .3517 / .00000552 / .2222 / .0370 |
| Holdout | 10 | 80 | 55.1323–55.1821 | .3900 / .003168 / .1000 / .0375 | .4484 / .1396 / .1375 / .0625 |

Total PIT failures are not concentrated monotonically in the highest predicted-total decile: the walk-forward tenth-decile total KS p is 0.5361, and the holdout tenth-decile p is 0.1396, while a holdout mid-high ninth decile rejects strongly. The reconstructed candidate expected total itself spans only 55.1902–55.8055 in walk-forward and 54.9453–55.1821 in holdout. So a game-specific total/tempo shape is a plausible structural requirement, but these deciles do **not** establish high predicted totals as the cause of total PIT failure. For margins, the extremity split above is much clearer evidence for the fixed-shape limitation.

## Next-candidate priorities (diagnostic only)

| Rank | Conditioning to preregister next | Evidence row |
|---:|---|---|
| 1 | Let margin distribution shape/dispersion vary with H1 win-probability extremity. | Walk-forward H1-extremity tercile 3 versus 1: margin high-tail PIT 0.1434 vs 0.0472 (mean PIT 0.5465 vs 0.4854). |
| 2 | Let total location and shape vary with a game-specific pregame total expectation or pace/tempo input. | Walk-forward total KS rejects in both seasons (2023 p=.0173; 2024 p=.00416); pooled low/high tails are .1063/.0824. Walk-forward predicted-total deciles do not isolate the highest bin, so this is a hypothesis to preregister, not a confirmed high-total mechanism. |

The next candidate should first condition margin shape on H1 probability extremity, where walk-forward high-tail PIT rises from 4.72% in the near-.5 tercile to 14.34% in the far tercile. Second, it should condition total location/shape on game-specific total or pace information because total PIT rejects in both walk-forward seasons and the pooled low tail is 10.63% versus 8.24% in the high tail; the walk-forward total-decile split does not establish a high-total-specific cause. These are research priorities only; no candidate was fitted, and 2025 was not used for selection.
