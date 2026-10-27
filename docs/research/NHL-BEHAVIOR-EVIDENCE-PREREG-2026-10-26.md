# NHL Behavior Evidence Audit: Preregistration

- **Date:** 2026-10-26
- **Branch:** `research/nhl-behavior-evidence-2026-10-26`
- **Base:** `9501768f1410484d8be235fe0700f710f5ec189e`
- **Scope:** source audit, train-only empirical estimates, chronological 2021 diagnostic, and a bounded penalty/manpower correction.
- **Not in scope:** model selection for adoption, changing a validity gate, production forecasts, historical result backfilling, or physical simulation.

## Why this code and these measurements are needed

No published source provides the required joined, per-game conditional distributions for this generator. The official NHL rulebook is the authority for deterministic transitions; archived GameCenter play-by-play, box scores, and shift charts are the observations for empirical behavior. A reproducible extractor is needed so reported values come from source records and can be independently rechecked. Legendary Picks database tables are inventoried read-only for current input coverage, but are not substitutes for the historical training corpus.

## Frozen population and source boundary

- **Training:** eligible regular-season games with start seasons 2019 and 2020.
- **Development:** eligible regular-season games with start season 2021. These games are used once for chronological diagnostics, not for tuning or candidate selection.
- **Excluded:** 2018 remains chronology/source-quality quarantined; 2022 is exposed historical evidence and is excluded from fitting and validation here.
- **Eligibility:** use the frozen v0.1 corpus contract: hash-verified GameCenter PBP, independently verified GameCenter box score with matching game/team identity and reconciled score/SOG, legal monotonic event clocks, complete regulation periods, and all existing quality checks. Report every listed, eligible, and quarantined game with reason.
- **Shifts:** accept only game rows in the pinned hardened shift manifest whose compressed body size/hash and `total == len(data)` reconcile. Report payload and join coverage separately from manifest HTTP status.
- **Database:** inspect `/root/legendarypicks/backend/data/picks.dev.db` with SQLite read-only mode. Do not use mutable current/future tables as historical 2019/20 or 2021 features. Historical features must be reconstructed from earlier eligible games only.
- **No target leakage:** for each 2021 target date, any rolling/team/player estimate must use only eligible games completed strictly before that date. Withhold all same-date target results until the date's entire group is scored. Do not use target box scores, actual lineup/goalie starts, shift charts, or in-game events as pregame inputs.
- **No acquisition:** use only the checked-in source manifests and existing local raw archives. No ESPN requests, provider contact, or new data fetches.

Pinned archive manifests:

| Asset | SHA-256 |
|---|---|
| GameCenter PBP | `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990` |
| Independent box scores | `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2` |
| Shift charts | `deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5` |

Use the 2021–22 official NHL rulebook SHA pinned in the Gate 1 rules contract for the 2021 development sample. Do not transfer a rule across seasons without verifying the applicable edition.

## Frozen event definitions and estimates

All event rates use regulation-plus-overtime game clock unless explicitly identified as shootout. Report numerator, denominator/exposure, eligible games, missing fields, and 95% game-cluster bootstrap intervals (2,000 resamples, seed `20261026`). For a binary conditional rate, use a train-only hierarchical estimate `(y + 20 * p_parent) / (n + 20)`; for an event rate, use the corresponding Gamma-Poisson shrinkage with 20 parent-equivalent game exposures. A zero-support cell falls back to its parent. Report sparse cells and their support; do not combine distinct rule states to manufacture sample size.

Conditional breakdowns are one-axis-at-a-time: period/time remaining, pre-event score state, home/away, observed manpower state, event/shot type, and recorded zone. Cross-products are descriptive only when counts support them. Report cells with fewer than 100 opportunities as sparse; do not fit an independent cell parameter from them.

| Behavior | Observations and definitions |
|---|---|
| Penalties/manpower | PBP `penalty` events; event clock/order; `typeCode`, `duration`, `eventOwnerTeamId`, committed/served player IDs; subsequent `situationCode`; shift intervals and active-player counts. Separate recorded penalty classes from rule-derived service, expiration, coincidental cancellation, and manpower. Identify overlapping opposing penalties by their observed intervals; do not declare coincidental solely because two records share a rounded second. |
| Faceoffs | Winner/loser player IDs, event owner/team, zone/coordinates, period, clock, score, and observed `situationCode`. Report win rates and next-PBP-event mix; additionally report a winner-team shot attempt before the next faceoff and within 30 game-clock seconds. Label this as an event-sequence proxy, not continuous possession or a causal puck-control label. |
| Shifts and substitutions | Shift `playerId`, `teamId`, `period`, `startTime`, `endTime`, `duration`, `typeCode`, event fields; join players by NHL ID to PBP `rosterSpots`. Measure duration, interval overlap, active personnel, and change counts. Do not infer forward line/pair assignment or coaching intent when not recorded. |
| Goalie pulls/returns | Decode PBP goalie-presence and skater-count fields only after checking them against shift-derived on-ice personnel and `goalieInNetId`. Count verified empty-net intervals and transitions by score/time. A shift ending alone is not evidence of a pull. |
| Shooting | Ordinary attempts are `goal`, `shot-on-goal`, `missed-shot`, and `blocked-shot`; exclude shootout attempts and keep penalty shots separate where the record identifies them. Estimate attempt-event rates by team-time exposure, attempt→SOG (`goal` + `shot-on-goal`), and SOG→goal. Describe coordinates/type/zone coverage by event class. Do not treat a blocked-shot coordinate as a verified release location. |
| Stoppages/restarts | `stoppage` reason and ordered next faceoff type/zone/clock; penalty/goal restarts separately. Frequencies estimate observed calls and restarts; they do not adjudicate unrecorded whistles or geometric offside/icing. |
| Overtime/shootout | Game-level regulation ties, OT starts/duration/goal termination, SO occurrence, attempt outcomes/order, and early termination. Estimate occurrence/outcome rates on training only; implement clock and termination mechanics from the applicable rulebook. Do not count the shootout decider as a player goal or goalie goal against. |

For the 2021 development check, freeze training estimates and report calibration/count error against the corresponding unconditioned 2019/20 parent rate. Do not select behavior definitions, shrinkage, or candidate parameters from 2021 results. This is a development diagnostic, not an adoption evaluation.

## Penalty/manpower correction test

The prior independent validator and simulator disagree on regulation manpower when both teams have active, noncoincidental manpower penalties. The audit must resolve the cases with the pinned NHL Rule 19 tables and real PBP/situation-code/shift evidence before changing code. Expected cases to encode as separate regression tests:

1. One noncoincidental active minor on one team: 4-on-5.
2. Matching coincidental penalties: no manpower reduction from the pair.
3. Opposing noncoincidental penalties with overlapping service intervals: reduce each penalized team independently (for the common one-each regulation case, 4-on-4).
4. Goal/early release, double-minor segment, expiration, and penalty-box return remain consistent with the active ledger.
5. Regular-season overtime penalty states follow the edition-specific overtime table; do not reuse the regulation formula.
6. Unsupported penalty combinations fail closed or are explicitly quarantined.

The fix may change the research v0.2b ledger and its duplicate internal audits only. The independent Gate 1 validator remains separate. Re-run its fixed 120-record diagnostic only as a clustered structural check, not as a population estimate. Preserve all seeds and report every status; do not alter the gate or suppress failures.

## Evaluation and deliverables

1. Reproducible source/DB coverage inventory, including manifest/body hashes and eligibility/quarantine reasons.
2. Training-only conditional behavior tables plus once-scored 2021 diagnostics and game-cluster uncertainty.
3. Actual penalty-overlap sequences with source game/event IDs, observed strength-code and shift reconciliation, limitations, and regression coverage.
4. Corrected regulation manpower logic, regression tests, and unchanged independent validator audit results.
5. An explicit coverage matrix stating what can be fit, what is deterministic under the rulebook, and what remains unobserved.

All outputs must be generated by committed scripts from the local immutable archives. Commit only compact derived summaries and source references; keep raw PBP, box-score, shift, and game-record bodies outside Git. Do not push without Micah.
