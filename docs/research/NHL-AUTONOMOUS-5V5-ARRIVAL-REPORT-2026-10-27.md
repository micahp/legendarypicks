# NHL Autonomous 5v5 Event-Arrival Experiment

- **Date:** 2026-10-27
- **Branch:** `research/nhl-autonomous-5v5-2026-10-27`
- **Base:** `da2475f1ea70648a1aeba805006776028368e8d5`
- **Preregistration:** `d97357c522a35b69a7f8c4d865217f2c90e420dc`; operational addendum `70da7619783eb26a2ed6b90bf20bd97a03a004a0`
- **Decision:** `A0_SIMPLER_REFERENCE_OR_NEITHER` (development-only)

## Data and evaluation boundary

Training games: 1,921 eligible 2019/20 games; development: 1,292 eligible 2021 games and 3,876 regulation game-periods.
State-ambiguous clock: 62,346/4,651,200 seconds (1.340%). Shift-derived non-5v5 time is 871,987 seconds; usable adjacent 5v5 interarrival exposure is 57,645.7 minutes.
Eligible development transition gaps: 229,842; periods with eligible gap exposure: 3,843; periods without: 33.
Extractor-eligible 5v5 source bundles: 242,973; destination bundles with a qualifying preceding gap: 229,842; eligible source goals: 5,247; goals retained as transition destinations: 5,054; goals without a qualifying preceding gap: 193.

This experiment models only event arrivals and source-family bundles during continuous 5v5 exposure. The fixed 20-minute traces assume 5v5 and both goalies remain present; they are not complete or rule-valid NHL periods. No 2021 events were used in fitting.


### Event-State and bundle coverage

The pinned Event-State v3 diagnostics count individual events with an eligible reconciled 5v5 state and resolved team ownership. This extractor has a stricter bundle contract: all records at a whole-second timestamp must be eligible, map to a supported event mark, and have a supported owner; transition destinations additionally require a qualifying preceding 5v5 gap. The counts therefore use different eligibility units. Deltas below are exposed as coverage differences, not silently treated as exact reconciliation.
Attempt counts include goals, shots on goal, missed shots, and blocked shots; SOG counts include goals and ordinary shots on goal.

| 2021 measure | Event-State v3 eligible event rows | Extractor eligible bundle tokens | Difference | Transition destination tokens | Eligible tokens without qualifying predecessor |
|---|---:|---:|---:|---:|---:|
| attempt | 115,765 | 115,233 | -532 | 109,998 | 5,235 |
| sog | 63,878 | 63,481 | -397 | 60,647 | 2,834 |
| goal | 5,329 | 5,247 | -82 | 5,054 | 193 |

The first extraction run was invalidated before accepting its scores. 8,041 development shift rows are zero-duration annotations; equal endpoints or an explicit zero duration with a missing endpoint are treated as no interval. Positive intervals missing a parseable duration remain fail-closed and make the period ambiguous.
Event-State v3 audit SHA-256: `1029c286cc3e20907338fea3f5f5bc612c6bb0bec793661f558ab57edd934f75`. The JSON contains the same reconciliation vectors for 2019/20 and 2021, the corrected cache hash, and source/extractor/runner hashes.

## Primary held-out sequence score

NLL includes the positive inter-bundle gap and the ordered destination bundle mark, normalized by eligible 5v5 interarrival minutes. Entry gaps and excluded/censored intervals are omitted and counted in the coverage fields.

| Candidate | Transitions | Gap NLL | Mark NLL | Total NLL | NLL nats / 5v5 minute |
|---|---:|---:|---:|---:|---:|
| A0 | 229,842 | 843973.55 | 768636.75 | 1612610.31 | 27.97450 |
| A1 | 229,842 | 865750.37 | 765200.85 | 1630951.21 | 28.29266 |

Paired game-cluster bootstrap for A1 − A0: 0.318134 nats/min, 95% interval [0.300034, 0.334830] (2,000 replicates; seed 20261027).

## Per-20-minute event-count rates

Observed period targets use event counts from eligible destination bundles divided by their eligible interarrival exposure, scaled to a 20-minute rate. Simulated traces use ten paired common-random-number replicates per 2021 game-period. CRPS uses the ten trace counts against the fractional 20-minute-equivalent observed target.

| Metric | A0 CRPS | A1 CRPS | A1−A0 CRPS | A1−A0 95% interval | A0 observed/forecast | A1 observed/forecast |
|---|---:|---:|---:|---:|---:|---:|
| bundle_count | 8.62109 | 56.31157 | 47.69701 | [47.20852, 48.17918] | 1.06650 | 4.38730 |
| shot_attempts | 4.87592 | 25.61102 | 20.73476 | [20.42201, 21.05211] | 0.96314 | 3.97956 |
| sog | 3.47450 | 13.99439 | 10.51731 | [10.31161, 10.71584] | 0.96860 | 3.97483 |
| goals | 0.94995 | 1.25920 | 0.30878 | [0.27866, 0.33992] | 0.93582 | 3.27696 |
| family:goal | 0.94995 | 1.25920 | 0.30878 | [0.27866, 0.33992] | 0.93582 | 3.27696 |
| family:shot-on-goal | 3.34087 | 12.92852 | 9.58561 | [9.39715, 9.78144] | 0.97171 | 4.05350 |
| family:missed-shot | 2.16319 | 5.14229 | 2.97994 | [2.87020, 3.09529] | 0.95177 | 3.90887 |
| family:blocked-shot | 2.33878 | 6.22274 | 3.88549 | [3.75400, 4.01713] | 0.96045 | 4.05178 |
| family:faceoff | 11.33429 | 15.19543 | 3.86153 | [3.83386, 3.88906] | 3.74612 | 14.18056 |
| family:stoppage | 4.50889 | 8.96117 | 4.45630 | [4.21887, 4.67654] | 0.75168 | 3.18816 |
| family:hit | 4.56480 | 12.66209 | 8.10329 | [7.83687, 8.37114] | 1.04569 | 4.26371 |
| family:giveaway | 2.42932 | 4.22486 | 1.79606 | [1.65146, 1.93771] | 0.92610 | 3.66082 |
| family:takeaway | 1.87986 | 3.46329 | 1.58533 | [1.49820, 1.67482] | 1.03946 | 4.08406 |
| family:other | 0.48732 | 0.42501 | -0.06238 | [-0.07609, -0.04807] | 0.69309 | 2.02311 |

Bundle-count calibration across 3,843 game-periods:
- Observed mean 80.04 bundles per 20-minute-equivalent exposure; A0 forecast 75.05, A1 forecast 18.24.
- Observed period variance 179.41; mean within-period trace variance A0 175.14, A1 111.75.
- Empirical central 80% coverage from ten traces per period: A0 55.6%, A1 0.0%.

## Arrival gaps, reproducibility, and runtime

Observed eligible gap distribution: {'n': 229842, 'p50_seconds': 11.0, 'p90_seconds': 33.0, 'p95_seconds': 43.0}. Generated: {'A0': {'n': 2908975, 'p50_seconds': 11.0, 'p90_seconds': 33.0, 'p95_seconds': 43.0}, 'A1': {'n': 707290, 'p50_seconds': 12.0, 'p90_seconds': 46.0, 'p95_seconds': 230.0}}.
The frozen A1 gap prior assigns 0.5 to each of 1,200 possible integer gaps, or 600 pseudo-counts per context. At the minimum eligible context size (100 bundles), that is 85.7% of posterior mass. Its generated p95 gap is 230s versus 43s observed. This is a post-hoc diagnosis of the frozen smoothing choice; it was not retuned.
The fixed-seed replay check was byte-identical: `True`. Generated traces: 77,520 (10 per eligible game-period and candidate).
Runtime seconds: `{"cache_load_or_build": 3.0570188750280067, "model_fit": 7.028268901980482, "simulation_and_metrics": 78.94884139695205, "total": 108.01745951699559}`. Sequence cache SHA-256: `9cfba618ded78ed92ad2cb6e15be64b493ef768fc8d094669f2a9138ec5275b2`; analysis runner SHA-256: `a120a1a0b21987853faa9e145b3c4631d99347b2322e40fd5c7150eef60fa7a6`.

## Decision and limitations

Frozen decision rule: A1 primary NLL interval entirely below zero = `False`; A1 bundle-count CRPS not worse than A0 = `False`. Result: **A0_SIMPLER_REFERENCE_OR_NEITHER**.

D0 B2 donor-slot reference: **NOT_AVAILABLE** — No frozen event-level B2 donor-slot output was present in the pinned evaluation artifacts; aggregate score summaries cannot recover a matched clock-slot likelihood or event trace.

The training population is a research development sample, and 2021 is not an untouched test. The model does not generate penalties or handle exits from 5v5, stoppage restart legality, player deployment, teams, goalies, tactics, overtime, shootouts, or physical movement. No adoption or production change is supported by this comparison.

Reproduce with `python3 research/nhl/autonomous-5v5/run_experiment.py` after verifying the source manifests. The derived transition cache is stored outside Git; its SHA-256 and frozen source hashes are in the result JSON.
