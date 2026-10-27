# NHL Autonomous 5v5 Arrival Experiment: Operational Addendum

- **Date:** 2026-10-27
- **Branch:** `research/nhl-autonomous-5v5-2026-10-27`
- **Original preregistration:** `d97357c522a35b69a7f8c4d865217f2c90e420dc`
- **Status:** Frozen before candidate fitting and 2021 scoring.
- **Effect:** Operationalizes the original experiment; it does not change populations, candidate definitions, metrics, or the decision rule.

## Pinned evidence implementation

Use the v0.1 source/eligibility loader and Event-State v3 reconciliation already in the branch:

| Input | SHA-256 |
|---|---|
| `research/nhl/statistical-full-game-v0.1/nhl_statistical_game.py` | `b6afea41c21660c564ea13ea75c5c17a6088e95cec1f590fb11426c95016e9fc` |
| `research/nhl/behavior-evidence/audit_behavior.py` | `5b03df12a6e1dfd2bf546192c59c35b26c6bf2b75b04b338b14b57f85cc145a9` |
| `research/nhl/behavior-evidence/evidence_core.py` | `cdcccbb1b4f5185df96178fccad4450a1bb3d8c9e5c4124389439c2281fc3490` |
| `research/nhl/behavior-evidence/results/nhl-behavior-evidence-event-state-v3-2026-10-27.json` | `1029c286cc3e20907338fea3f5f5bc612c6bb0bec793661f558ab57edd934f75` |

The loader must reproduce 1,921 eligible 2019/20 training games and 1,292 eligible 2021 development games. Each PBP and shift body is verified against its frozen manifest. No database or current-season input is used.

## Event and exposure construction

1. Sort each regulation period’s PBP records by `sortOrder`, then group all records sharing the same whole-second `timeInPeriod` into one ordered event bundle. `sortOrder` is not treated as subsecond time.
2. Exclude period/game boundary markers from event marks. Normalize source families to `goal`, `shot-on-goal`, `missed-shot`, `blocked-shot`, `faceoff`, `stoppage`, `hit`, `giveaway`, `takeaway`, or `other`. `other` is retained as an explicit family and its source-type composition is reported. A penalty anywhere in a bundle excludes that bundle from the event-mark population.
3. A bundle is 5v5-eligible only if every included source record has an eligible Event-State v3 attribution, the reconciled state is exactly five skaters and a goalie on each team, and the bundle contains no penalty. Never infer a missing/conflicting state.
4. A positive gap is eligible only between adjacent eligible bundles in the same regulation period and only if every shift-chart-defined open interval across the gap has complete, nonduplicated personnel and remains 5v5 with both goalies present. Gaps crossing a penalty, non-5v5 state, period boundary, ambiguous bundle, or shift-state uncertainty are broken and excluded. The destination bundle’s marks are the outcome for that gap. Do not bridge excluded time.
5. The initial generated state is fixed and target-independent: regulation time 0, score tied, five skaters and a goalie per team, possession known after a generic opening faceoff, and previous family `faceoff`. The opening faceoff itself is initialization and is not sampled into the generated timeline. No target-game opening-faceoff winner or event is copied.
6. The possession proxy is binary known/unknown. It becomes known after a faceoff with a resolved winner or a source giveaway/takeaway with a resolved owner. It becomes unknown after a goal, shot attempt, or stoppage unless a later event in that same bundle resolves possession. Other source marks retain the prior proxy state. It is not continuous possession truth.
7. `score_state` is pre-arrival home-leading, tied, or away-leading, updated only by generated/observed regulation goals. The five-minute clock bucket is the elapsed departure bucket `floor(previous_bundle_second / 300)`, clipped to 0–3. Both are available at the prediction point.
8. The model family mark is the ordered sequence of `(normalized family, owner side)` tokens; owner side is home, away, or unknown, with faceoff ownership taken from the resolved winner where available. No player identifiers, coordinates, target identities, or future events enter a mark.

## Probability and scoring details

- A0 samples positive integer gaps from 1–1200 seconds and bundle marks from pooled training observations.
- A1 uses the frozen hierarchy in the original preregistration. A context’s eligibility count is its number of training transition observations; use that level only at `n >= 100`.
- Discrete gap, bundle-size, and token distributions use symmetric Dirichlet smoothing with fixed `alpha=0.5`. The family alphabet is the fixed normalized set above; owner alphabet is `{home, away, unknown}`. Bundle marks are sampled as a bundle-size draw followed by ordered event-token draws conditioned on the context and prior tokens. This factorization assigns nonzero probability to development bundles not observed as an exact training combination.
- Primary development NLL is the sum of the negative log probability of each eligible positive gap and its destination bundle mark, divided by total eligible gap exposure in minutes. Entry gaps without a valid preceding 5v5 bundle and exit/censored intervals are excluded and reported; no likelihood is invented for them.
- Ten paired traces are generated for each eligible 2021 game-period. For each metric and period, the observed target is the eligible destination-bundle count divided by eligible gap seconds and scaled to a 20-minute rate. CRPS is computed from the ten simulated counts and that observed 20-minute-equivalent rate. Periods without eligible gap exposure are omitted from rate/count scores and counted in coverage.
- The common-random-number seed is derived from `(paired experiment version, game ID, period, replicate)` and shared across A0/A1; candidate/model version is recorded as metadata rather than included in the seed key.
- “Development exposure quarantined for state ambiguity” is the union of regulation clock seconds in intervals with unresolved/duplicate shift personnel plus one-second windows around PBP event clocks marked missing, conflicting, or ambiguous by Event-State v3, divided by total eligible 2021 regulation clock seconds. Report non-5v5 time and usable 5v5 gap exposure separately; they are not conflated with ambiguity.
- Paired bootstrap resamples whole game IDs, retaining all three regulation periods and both candidates together. Use 2,000 replicates with seed `20261027` for this experiment. Lower NLL/CRPS is better.

All outputs remain conditional fixed-strength research traces. These definitions do not establish complete-period or full-game legality, team tactical causality, player behavior, or NHL predictive skill.
