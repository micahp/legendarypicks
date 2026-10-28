# NHL A1 Gap Estimator Comparison

| Metadata | Value |
|---|---|
| Date | 2026-10-28 |
| Branch | `research/nhl-a1-gap-estimator-comparison-2026-10-28` |
| Historical result SHA-256 | `75046cb85f06c51c23015ce80be7203d39fea07829c10b6a555b33645bc05f77` |
| Risk-spell cache SHA-256 | `29c2d721d03a17fe153f504ccc03c4299059af96f466b91ab2c1d9adccd9b08a` |

## Scope and data boundary

A0 and A1 remain frozen controls. B1 replaces A1's uniform timing pseudocount with the pooled training timing distribution at the same 600-count prior strength. B2-E and B2-W fit discrete event-time distributions using event and right-censored spells. All event marks use the unchanged A1 mark model. The 2021 season is exposed development data, not an independent test. No scoring, production forecast, or gate changed.

## Where A1's timing prior goes

A1 uses 0.5 pseudocount at each of 1,200 gap seconds, or 600 total prior counts per selected context. Across 2021 pre-gap contexts, the measured prior mass share was **14.534%**. Its uniform prior's mean duration is **600.50s**; the context-weighted raw empirical mean is **15.22s**, and A1's smoothed mean is **100.31s**. The full 1-second PMF and survival arrays are in the JSON.

| Duration bin | Observed 2021 gaps | A1 raw context PMF | A1 smoothed PMF | Uniform-prior contribution | A0 pooled PMF | B1 pooled-shrink PMF |
|---:|---:|---:|---:|---:|---:|---:|
| 1-5s | 60,505 | 0.2580 | 0.2203 | 0.0006 | 0.2573 | 0.2571 |
| 6-10s | 52,258 | 0.2250 | 0.1926 | 0.0006 | 0.2245 | 0.2247 |
| 11-20s | 59,502 | 0.2619 | 0.2254 | 0.0012 | 0.2615 | 0.2622 |
| 21-30s | 29,279 | 0.1300 | 0.1126 | 0.0012 | 0.1299 | 0.1303 |
| 31-60s | 24,934 | 0.1100 | 0.0979 | 0.0036 | 0.1099 | 0.1102 |
| 61-120s | 3,295 | 0.0149 | 0.0201 | 0.0073 | 0.0150 | 0.0150 |
| 121-300s | 69 | 0.0002 | 0.0220 | 0.0218 | 0.0005 | 0.0003 |
| 301-600s | 0 | 0.0000 | 0.0363 | 0.0363 | 0.0005 | 0.0001 |
| 601-900s | 0 | 0.0000 | 0.0363 | 0.0363 | 0.0005 | 0.0001 |
| 901-1200s | 0 | 0.0000 | 0.0363 | 0.0363 | 0.0005 | 0.0001 |

## Historical-state replay

| Estimator | All-gap NLL / 5v5 min | Δ vs A0 (95% game-cluster CI) | Δ vs A1 (95% game-cluster CI) | p50 | p90 | p95 | p99 | Unsupported raw gaps |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A0 | 14.64069 | reference | -0.37774 [-0.38640, -0.36936] | 11.0 | 34.0 | 44.0 | 69.0 | 12 |
| A1 | 15.01846 | +0.37774 [+0.36930, +0.38628] | reference | 14.0 | 375.0 | 788.0 | 1118.0 | 951 |
| B1 | 14.45102 | -0.18979 [-0.19724, -0.18262] | -0.56754 [-0.57458, -0.56038] | 11.0 | 34.0 | 44.0 | 67.0 | 951 |
| B2-E | 14.62753 | -0.01319 [-0.01695, -0.00963] | -0.39094 [-0.39917, -0.38308] | 11.0 | 36.0 | 47.0 | 73.0 | n/a |
| B2-W | 14.48610 | -0.15466 [-0.16167, -0.14801] | -0.53240 [-0.53891, -0.52588] | 12.0 | 35.0 | 45.0 | 69.0 | n/a |

A0 and A1 use the same categorical timing estimator and 0.5 count at each second. A0 pools 329,667 training gaps, so its 600-count prior is **0.182%** of each denominator. A1 selects contexts (training support min 133, median 2,786.5, p90 6,007.8, max 10,837); its same-sized uniform prior contributes **14.53%** on average (median 13.81%, p90 21.71%, maximum 81.86%). That prior has mean 600.5 seconds and puts **10.90%** probability above 300 seconds. The 2021 complete-gap sample has no gaps above 300 seconds. A0's pooled support dilutes the pseudocount; A1's context-specific denominators do not.
B2-E/W fit 99 selected context buckets. B2-W training event support per bucket ranges from 15 to 10837 (median 2,744.0; p90 6,003.6); censored support ranges from 4 to 1073 (median 124.0). Weibull fits converged in 99/99 contexts, with 0 boundary hits. Full context-by-context support and optimizer data are in the JSON.

| Transition stratum | n | Observed p50/p90/p95/p99 | A0 NLL/min, p90 | A1 NLL/min, p90 | B1 NLL/min, p90 | B2-E NLL/min, p90 | B2-W NLL/min, p90 |
|---|---:|---|---:|---:|---:|---:|---:|
| First retained transition per period | 3,843 | 16/40.0/51.0/75.57999999999993 | 11.751, 34.0 | 11.491, 57.0 | 11.323, 36.0 | 11.673, 41.0 | 11.369, 37.0 |
| Later transitions | 225,999 | 11/33.0/43.0/66.0 | 14.708, 34.0 | 15.101, 381.0 | 14.524, 34.0 | 14.697, 36.0 | 14.559, 35.0 |

Period entry remains a separate stratum: 3,256 initial 5v5 event observations have p50/p90/p95 **0.0/0.0/0.0 seconds**, reflecting the event at the period's opening second. These are not treated as post-event gaps or candidate targets.
The 2021 replay has 229,842 frozen complete-gap transitions: 229,673 event-observed risk spells plus 169 same-second boundary ties. There are 10,727 right-censored spells and 3,577,668 fully observed 5v5 risk seconds. Censor causes and both Kaplan–Meier tie conventions are in the JSON.
Separately, 2,573 otherwise eligible event origins did not begin in a verified 5v5 second and have no following 5v5 exposure (reasons: {'origin_at_period_end': 59, 'origin_not_verified_5v5': 2514}). They are excluded from risk spells, not converted to long gaps.

| 2021 censor reason | Count |
|---|---:|
| 5v5 exit (including same-second ineligible bundle) | 7,598 |
| Period end | 2,520 |
| Ambiguous state (including ineligible bundle) | 158 |
| Ineligible bundle without a state boundary | 282 |
| Eligible-event same-second boundary ties | 169 |

Event-gap NLL contrasts are game-clustered; confidence intervals for both A0 and A1 comparisons are shown above for the all-gap population and preserved by stratum in the JSON.

### Censoring and survival likelihood

The source extractor reconciles event-observed risk spells plus same-second boundary-tied event censors exactly to the frozen transition cache. Ineligible event bundles, 5v5 exits, ambiguous state, period end, and eligible-event boundary ties are separate right-censor reasons. A censor is not encoded as a long event gap. Whole-second censor ties are shown under both censor-first and event-first Kaplan–Meier conventions.

| Estimator | Censored spells | Joint event+censor NLL / at-risk min | Δ vs A0 (95% game-cluster CI) | Δ vs A1 (95% game-cluster CI) | Support failures |
|---|---:|---:|---:|---:|---:|
| A0 | 10,727 | 14.28018370205626 | reference | -0.32286 [-0.33156, -0.31436] | 0 |
| A1 | 10,727 | 14.603090950604393 | +0.32286 [+0.31433, +0.33147] | reference | 0 |
| B1 | 10,727 | 14.101178073661654 | -0.17911 [-0.18638, -0.17218] | -0.50197 [-0.50925, -0.49434] | 0 |
| B2-E | 10,727 | 14.261671115682558 | -0.01854 [-0.02208, -0.01499] | -0.34140 [-0.34972, -0.33351] | 0 |
| B2-W | 10,727 | 14.126040265631353 | -0.15421 [-0.16109, -0.14786] | -0.47707 [-0.48390, -0.47004] | 0 |

### First event and later events

A period-entry/re-entry observation is reported separately and is not pooled with post-event gaps. Within the frozen transition sample, the first retained transition per period and later transitions are scored separately. Full predicted/observed quantiles, survival calibration, and censoring splits are preserved in the JSON.

## Autonomous rollout

The rollout used 3,876 periods × 10 common seeds, for 193,800 traces. Candidate and control marks remain A1's frozen mark model.

| Metric | Estimator | Generated mean | Observed mean | CRPS | CRPS delta vs A0 (95% game-cluster CI) | Generated p50/p90/p95/p99 |
|---|---|---:|---:|---:|---:|---|
| bundle_count | A0 | 75.052 | 80.043 | 8.6211 | reference | 77.0/89.0/92.0/98.0 |
| bundle_count | A1 | 18.244 | 80.043 | 56.3116 | +47.6905 [+47.2112, +48.1833] | 16.0/34.0/39.0/52.0 |
| bundle_count | B1 | 80.863 | 80.043 | 8.2741 | -0.3470 [-0.4801, -0.2145] | 81.0/92.0/96.0/102.0 |
| bundle_count | B2-E | 76.167 | 80.043 | 8.5437 | -0.0774 [-0.1370, -0.0165] | 76.0/87.0/91.0/97.0 |
| bundle_count | B2-W | 74.055 | 80.043 | 8.9654 | +0.3443 [+0.2570, +0.4409] | 74.0/86.0/90.0/96.0 |
| family:blocked-shot | A0 | 9.721 | 9.337 | 2.3388 | reference | 10.0/14.0/15.0/18.0 |
| family:blocked-shot | A1 | 2.304 | 9.337 | 6.2227 | +3.8840 [+3.7544, +4.0220] | 2.0/5.0/6.0/8.0 |
| family:blocked-shot | B1 | 10.344 | 9.337 | 2.4033 | +0.0645 [+0.0374, +0.0914] | 10.0/15.0/16.0/19.0 |
| family:blocked-shot | B2-E | 9.738 | 9.337 | 2.3319 | -0.0069 [-0.0302, +0.0167] | 10.0/14.0/15.0/18.0 |
| family:blocked-shot | B2-W | 9.469 | 9.337 | 2.3143 | -0.0244 [-0.0477, -0.0002] | 9.0/14.0/15.0/17.0 |
| family:faceoff | A0 | 4.537 | 16.997 | 11.3343 | reference | 4.0/8.0/9.0/10.0 |
| family:faceoff | A1 | 1.199 | 16.997 | 15.1954 | +3.8611 [+3.8329, +3.8886] | 1.0/3.0/4.0/5.0 |
| family:faceoff | B1 | 5.446 | 16.997 | 10.4137 | -0.9206 [-0.9470, -0.8962] | 5.0/8.0/9.0/11.0 |
| family:faceoff | B2-E | 5.129 | 16.997 | 10.7641 | -0.5702 [-0.5957, -0.5459] | 5.0/8.0/9.0/11.0 |
| family:faceoff | B2-W | 4.989 | 16.997 | 10.9086 | -0.4257 [-0.4509, -0.4020] | 5.0/8.0/9.0/11.0 |
| family:giveaway | A0 | 6.860 | 6.353 | 2.4293 | reference | 7.0/11.0/12.0/14.0 |
| family:giveaway | A1 | 1.735 | 6.353 | 4.2249 | +1.7955 [+1.6651, +1.9277] | 1.0/4.0/5.0/7.0 |
| family:giveaway | B1 | 7.514 | 6.353 | 2.5268 | +0.0975 [+0.0705, +0.1237] | 7.0/11.0/12.0/15.0 |
| family:giveaway | B2-E | 7.080 | 6.353 | 2.4368 | +0.0075 [-0.0132, +0.0270] | 7.0/11.0/12.0/14.0 |
| family:giveaway | B2-W | 6.887 | 6.353 | 2.4025 | -0.0268 [-0.0466, -0.0080] | 7.0/10.0/12.0/14.0 |
| family:goal | A0 | 1.889 | 1.768 | 0.9499 | reference | 2.0/4.0/4.0/6.0 |
| family:goal | A1 | 0.539 | 1.768 | 1.2592 | +0.3092 [+0.2761, +0.3400] | 0.0/2.0/2.0/3.0 |
| family:goal | B1 | 2.512 | 1.768 | 1.0625 | +0.1126 [+0.0973, +0.1276] | 2.0/5.0/5.0/7.0 |
| family:goal | B2-E | 2.361 | 1.768 | 1.0253 | +0.0754 [+0.0626, +0.0879] | 2.0/4.0/5.0/7.0 |
| family:goal | B2-W | 2.296 | 1.768 | 1.0112 | +0.0613 [+0.0492, +0.0734] | 2.0/4.0/5.0/6.0 |
| family:hit | A0 | 17.571 | 18.373 | 4.5648 | reference | 18.0/24.0/25.0/29.0 |
| family:hit | A1 | 4.309 | 18.373 | 12.6621 | +8.0973 [+7.8131, +8.3703] | 4.0/9.0/10.0/14.0 |
| family:hit | B1 | 18.895 | 18.373 | 4.6079 | +0.0431 [-0.0077, +0.0923] | 19.0/25.0/27.0/30.0 |
| family:hit | B2-E | 17.807 | 18.373 | 4.5874 | +0.0226 [-0.0100, +0.0543] | 18.0/24.0/25.0/29.0 |
| family:hit | B2-W | 17.317 | 18.373 | 4.5916 | +0.0268 [-0.0062, +0.0608] | 17.0/23.0/25.0/28.0 |
| family:missed-shot | A0 | 8.208 | 7.812 | 2.1632 | reference | 8.0/12.0/14.0/16.0 |
| family:missed-shot | A1 | 1.999 | 7.812 | 5.1423 | +2.9791 [+2.8633, +3.0901] | 2.0/4.0/5.0/8.0 |
| family:missed-shot | B1 | 8.932 | 7.812 | 2.2616 | +0.0984 [+0.0724, +0.1240] | 9.0/13.0/14.0/17.0 |
| family:missed-shot | B2-E | 8.405 | 7.812 | 2.1696 | +0.0065 [-0.0150, +0.0281] | 8.0/12.0/14.0/16.0 |
| family:missed-shot | B2-W | 8.172 | 7.812 | 2.1442 | -0.0190 [-0.0402, +0.0019] | 8.0/12.0/13.0/16.0 |
| family:other | A0 | 0.683 | 0.473 | 0.4873 | reference | 0.0/2.0/2.0/3.0 |
| family:other | A1 | 0.234 | 0.473 | 0.4250 | -0.0623 [-0.0756, -0.0485] | 0.0/1.0/1.0/2.0 |
| family:other | B1 | 1.145 | 0.473 | 0.6576 | +0.1703 [+0.1580, +0.1824] | 1.0/3.0/3.0/4.0 |
| family:other | B2-E | 1.076 | 0.473 | 0.6290 | +0.1417 [+0.1308, +0.1527] | 1.0/3.0/3.0/4.0 |
| family:other | B2-W | 1.046 | 0.473 | 0.6160 | +0.1287 [+0.1181, +0.1392] | 1.0/2.0/3.0/4.0 |
| family:shot-on-goal | A0 | 19.963 | 19.398 | 3.3409 | reference | 20.0/26.0/28.0/32.0 |
| family:shot-on-goal | A1 | 4.786 | 19.398 | 12.9285 | +9.5877 [+9.3822, +9.7907] | 4.0/10.0/12.0/16.0 |
| family:shot-on-goal | B1 | 21.217 | 19.398 | 3.4830 | +0.1421 [+0.1080, +0.1757] | 21.0/27.0/29.0/33.0 |
| family:shot-on-goal | B2-E | 19.984 | 19.398 | 3.2995 | -0.0413 [-0.0667, -0.0158] | 20.0/26.0/28.0/31.0 |
| family:shot-on-goal | B2-W | 19.427 | 19.398 | 3.2839 | -0.0570 [-0.0880, -0.0263] | 19.0/25.0/27.0/31.0 |
| family:stoppage | A0 | 20.448 | 15.370 | 4.5089 | reference | 21.0/27.0/29.0/32.0 |
| family:stoppage | A1 | 4.821 | 15.370 | 8.9612 | +4.4523 [+4.2204, +4.6856] | 4.0/10.0/12.0/17.0 |
| family:stoppage | B1 | 21.445 | 15.370 | 5.0623 | +0.5535 [+0.5124, +0.5941] | 21.0/27.0/29.0/33.0 |
| family:stoppage | B2-E | 20.192 | 15.370 | 4.3226 | -0.1863 [-0.2229, -0.1493] | 20.0/26.0/28.0/31.0 |
| family:stoppage | B2-W | 19.633 | 15.370 | 4.0229 | -0.4860 [-0.5242, -0.4480] | 19.0/25.0/27.0/31.0 |
| family:takeaway | A0 | 4.817 | 5.007 | 1.8799 | reference | 5.0/8.0/9.0/11.0 |
| family:takeaway | A1 | 1.226 | 5.007 | 3.4633 | +1.5834 [+1.4999, +1.6738] | 1.0/3.0/4.0/5.0 |
| family:takeaway | B1 | 5.445 | 5.007 | 1.9115 | +0.0316 [+0.0094, +0.0535] | 5.0/9.0/10.0/12.0 |
| family:takeaway | B2-E | 5.133 | 5.007 | 1.8828 | +0.0029 [-0.0137, +0.0197] | 5.0/8.0/9.0/11.0 |
| family:takeaway | B2-W | 4.989 | 5.007 | 1.8714 | -0.0084 [-0.0239, +0.0072] | 5.0/8.0/9.0/11.0 |
| goals | A0 | 1.889 | 1.768 | 0.9499 | reference | 2.0/4.0/4.0/6.0 |
| goals | A1 | 0.539 | 1.768 | 1.2592 | +0.3092 [+0.2761, +0.3400] | 0.0/2.0/2.0/3.0 |
| goals | B1 | 2.512 | 1.768 | 1.0625 | +0.1126 [+0.0973, +0.1276] | 2.0/5.0/5.0/7.0 |
| goals | B2-E | 2.361 | 1.768 | 1.0253 | +0.0754 [+0.0626, +0.0879] | 2.0/4.0/5.0/7.0 |
| goals | B2-W | 2.296 | 1.768 | 1.0112 | +0.0613 [+0.0492, +0.0734] | 2.0/4.0/5.0/6.0 |
| shot_attempts | A0 | 39.781 | 38.315 | 4.8759 | reference | 41.0/49.0/52.0/57.0 |
| shot_attempts | A1 | 9.628 | 38.315 | 25.6110 | +20.7351 [+20.4128, +21.0661] | 8.0/18.0/22.0/29.0 |
| shot_attempts | B1 | 43.005 | 38.315 | 5.5010 | +0.6251 [+0.5531, +0.6922] | 43.0/52.0/54.0/59.0 |
| shot_attempts | B2-E | 40.488 | 38.315 | 4.7829 | -0.0931 [-0.1302, -0.0571] | 40.0/49.0/51.0/56.0 |
| shot_attempts | B2-W | 39.364 | 38.315 | 4.6351 | -0.2408 [-0.2848, -0.1962] | 39.0/48.0/51.0/56.0 |
| sog | A0 | 21.852 | 21.166 | 3.4745 | reference | 22.0/29.0/31.0/34.0 |
| sog | A1 | 5.325 | 21.166 | 13.9944 | +10.5199 [+10.2948, +10.7247] | 5.0/11.0/13.0/18.0 |
| sog | B1 | 23.729 | 21.166 | 3.7657 | +0.2911 [+0.2454, +0.3335] | 24.0/30.0/32.0/36.0 |
| sog | B2-E | 22.346 | 21.166 | 3.4665 | -0.0080 [-0.0343, +0.0193] | 22.0/29.0/31.0/34.0 |
| sog | B2-W | 21.723 | 21.166 | 3.4105 | -0.0640 [-0.0906, -0.0355] | 22.0/28.0/30.0/34.0 |

Generated first-arrival, later emitted-gap, and terminal-censor proposal quantiles, mark-family counts, SOG, attempts, goals, trace reproducibility, and per-candidate plus total runtimes are in the rollout JSON.

### Rollout interpretation

The complete rollout and clustered scoring took 1206.4s. Each estimator generated 38,760 traces. The recorded fixed-seed replay check was byte-identical. Each candidate had one terminal proposal per trace and no first-arrival right-censored trace.

B1 lowers bundle-count CRPS versus A0 by -0.3470 [-0.4801, -0.2145], but its nominal central-80% interval covers only 50.2% of observed period counts. Its estimated predictive count variance, combining within-period trace variance and across-period forecast-mean variance, is 90.65 versus observed period variance 179.41. B2-E and B2-W have bundle-count CRPS deltas -0.0774 [-0.1370, -0.0165] and +0.3443 [+0.2570, +0.4409], with predictive variances 74.09 and 89.83.

All three timing candidates worsen goal CRPS against A0, with game-clustered intervals wholly above zero: B1 +0.1126 [+0.0973, +0.1276]; B2-E +0.0754 [+0.0626, +0.0879]; B2-W +0.0613 [+0.0492, +0.0734]. SOG results are mixed: B1 +0.2911 [+0.2454, +0.3335], B2-E -0.0080 [-0.0343, +0.0193], and B2-W -0.0640 [-0.0906, -0.0355].

The frozen event-mark process also leaves a separate faceoff-count discrepancy: timing candidates generate 4.99–5.45 faceoffs per period versus 17.00 observed. Therefore the historical timing fit does not establish adequate joint event generation. The timing candidates fail the preregistered no-goal-deterioration criterion.

No candidate is selected: the bundle-count score improvement does not compensate for count underdispersion and the goal/event-family tradeoffs. Shot conversion and the frozen mark model were not tuned.

## Decision and limitations

This is a mechanism comparison on exposed 2021 development data. It does not select or adopt a timing model. B1's complete-gap fit does not use censored spells in its PMF, while B2-E/W use the reconstructed right-censored risk set; censoring reason is retained because penalty/state exits may be informative rather than independent. No puck tracking, new source, or production data was needed for this timing investigation.

A0/A1 original artifacts remain unchanged. All candidate paths keep the shot/mark sampler fixed. The autonomous rollout is not an independent validation of the NHL game model.

## Repository history rewrite

The 70.46 MB 10/27 diagnostic JSON was removed from every commit in this branch's rewritten range. The exact file remains outside Git with its original SHA-256. No model code, metrics, source inputs, or preregistration document contents changed; commit IDs changed because their ancestry changed. The preregistration and result metadata use the rewritten commit IDs below, while the frozen preregistration documents retain their original recorded IDs.

| Original commit | Rewritten commit | Change |
|---|---|---|
| `38e181418500be26df61a8b12fe42c78750d9292` | `0c84b49fe0e27e4c219a87b926c0092079a019f9` | Parent diagnostic |
| `f5d682007133be69127a34077f972c5c1c816d7b` | `fe5fed48660c4a9055c04c3266d9e6c95e9045a7` | Preregistration |
| `aa6fa660c9cdf92eb962c97f9815e5a364288cb5` | `100c57aa10ecee91d9362b3513f4417e629e7686` | Input pin |
| `7dbe2bb7555627f275a0a23cf3ba95304045b04a` | `89c4509a3066beba4b8233b7edb31776a354d690` | Censor convention preregistration |
| `03aea31b9abdfc210b510f45a0cdd40798f21295` | `c792fb8163a0f7267744675cffaddf988169ba5a` | Boundary-tie preregistration |
| `15db83cd4571141a148c7ab135dee2e9d4517db5` | `26a0bd30a1802c271cb2e6c6c48db4a8adb372bf` | Estimator implementation |
| `f04b267bf4f46a90a55905ed67d6be30c9b0790f` | `6ed2d0ed6973ad3bb83b8623cac89fc1598e7ab3` | Period-end correction |
| `01ee949a07aee55ef67fd727ff5e6cb1a65eda4e` | `92755645177664496ecb9abbfe178cc24dc3344c` | Historical result |
| `6c441f76bd12c70120a6c54dd51ef353902d5038` | `e52ebbac2ff861545f294bfa871adcfec77301ab` | Rollout progress logging |
| `30ee263672ec6cee1fcb2612b1f07f3d7378d6a6` | `86ea97882806e6b5b74bd84e2170ba6a1abdae1d` | Rollout result |
| `d6aaa9b8d6936a5bd6d7996344fbdcbd891b9d1f` | `162f20b285de3ac56995392265749b79c12f56b6` | Artifact removal and report-only replacement |

## Reproduction

```bash
python3 research/nhl/autonomous-5v5/gap_estimator_comparison.py --stage audit --game-limit 1
python3 research/nhl/autonomous-5v5/gap_estimator_comparison.py --stage historical
python3 research/nhl/autonomous-5v5/gap_estimator_comparison.py --stage rollout
python3 -m unittest discover -s research/nhl/autonomous-5v5/tests -p 'test_gap_estimator_comparison.py'
```

- Preregistration: [protocol](NHL-A1-GAP-ESTIMATOR-COMPARISON-PREREG-2026-10-28.md).
- Machine-readable historical results: [`nhl-a1-gap-estimator-comparison-historical-2026-10-28.json`](../../research/nhl/autonomous-5v5/results/nhl-a1-gap-estimator-comparison-historical-2026-10-28.json).
- Machine-readable rollout results: [`nhl-a1-gap-estimator-comparison-rollout-2026-10-28.json`](../../research/nhl/autonomous-5v5/results/nhl-a1-gap-estimator-comparison-rollout-2026-10-28.json).
- Implementation/tests: [`gap_estimator_comparison.py`](../../research/nhl/autonomous-5v5/gap_estimator_comparison.py), [`test_gap_estimator_comparison.py`](../../research/nhl/autonomous-5v5/tests/test_gap_estimator_comparison.py).
