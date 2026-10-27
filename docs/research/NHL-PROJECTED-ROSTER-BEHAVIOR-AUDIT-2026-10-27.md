# NHL projected-roster and behavior evidence audit

Date: 2026-10-27  
Scope: reconcile the 120-seed Gate 1 runs, audit projected-roster accounting and goalie transitions, and preserve unsupported penalty states. The Gate 1 acceptance threshold is unchanged.

## Paired-run comparison

| Run | Games | Structural PASS | Penalty quarantines (seeds) | OT/SO NOT_ASSESSED (seeds) | Model | Schema |
|---|---:|---:|---|---|---|---|
| Pre-roster | 120 | 109 | 202610285818, 202610285820, 202610389108 | 202610260003, 202610260006, 202610285801, 202610311608, 202610311613, 202610337506, 202610389106, 202610389112 | nhl-game-state-v0.2b-b2 | nhl-statistical-pbp-v0.2b |
| Projected roster v1 | 120 | 115 | 202610260017, 202610285818, 202610285820, 202610363311, 202610389108 | none | nhl-game-state-v0.2b-projected-roster-v1-b2 | nhl-statistical-pbp-v0.2b-projected-roster-v1 |
| Telemetry rerun | 120 | 115 | 202610260017, 202610285818, 202610285820, 202610363311, 202610389108 | none | nhl-game-state-v0.2b-projected-roster-v1-b2 | nhl-statistical-pbp-v0.2b-projected-roster-v2 |

The seed sets match across all three runs: **True**. PBP, box-score and shift-manifest hashes match for the pre-roster and projected-roster runs: **True**. The roster change intentionally changes every pregame snapshot; this is a paired-seed population comparison, not an identical-input counterfactual. The telemetry rerun has unchanged projected snapshots: **True**.

After removing only the three added quarantine metadata fields and normalizing the schema-version bump, simulator records are gameplay-identical to the projected-roster v1 run for every seed: **True**.

Structural PASS rises from 109/120 to 115/120 (+6). The pre-roster run's 11 non-PASS records comprise 3 penalty quarantines and 8 overtime/shootout `NOT_ASSESSED` records because no projected game roster was supplied. In projected-roster v1 those eight checks become PASS within the validator's modeled scope, and no OT/SO check remains `NOT_ASSESSED`; full Rule 84.4 exclusions are still not covered. The original three penalty-quarantine seeds remain; two additional penalty-quarantine seeds appear: 202610260017, 202610363311. The net +6 reflects eight former `NOT_ASSESSED` statuses becoming scoped PASS minus two new penalty quarantines. Since roster snapshots and generated gameplay differ, this is a paired-seed population comparison, not an identical-snapshot causal effect.

## Five penalty quarantines

The telemetry rerun preserves 5 omitted penalty transitions: `{'simultaneous_penalty_transition_requires_explicit_pairing': 1, 'third_concurrent_manpower_penalty_requires_queued_serving': 4}`. Candidate team-side counts are `{'away': 2, 'home': 3}`. Each event below remains an explicit `stoppage` with its unsupported-penalty marker; none is converted into a guessed penalty or manpower update.

| Seed | Game | Event | Clock | Candidate side | Reason | Active units before |
|---:|---:|---|---|---|---|---|
| 202610260017 | 2021020001 | 352 P3 | 15:22 | away | `third_concurrent_manpower_penalty_requires_queued_serving` | `{'away': 2, 'home': 0}` |
| 202610285818 | 2021020262 | 197 P2 | 11:01 | home | `simultaneous_penalty_transition_requires_explicit_pairing` | `{'away': 0, 'home': 1}` |
| 202610285820 | 2021020262 | 158 P2 | 04:48 | home | `third_concurrent_manpower_penalty_requires_queued_serving` | `{'away': 0, 'home': 2}` |
| 202610363311 | 2021021050 | 121 P1 | 16:31 | home | `third_concurrent_manpower_penalty_requires_queued_serving` | `{'away': 0, 'home': 2}` |
| 202610389108 | 2021021179 | 14 P1 | 01:57 | away | `third_concurrent_manpower_penalty_requires_queued_serving` | `{'away': 2, 'home': 0}` |

## Overtime and shootout evidence

The 2021 development archive contains 1,292 eligible games, 278 reaching overtime, 183 ending in overtime, and 95 reaching a shootout. It records 702 shootout attempts and 210 shootout goals. Historical OT/SO data were present; the prior gap was the lack of a game-specific projected-roster input for generated shooter membership checks.

Across the 120 telemetry games, the independent record audit checked 108 generated shootout attempts; projected-team-roster membership is **PASS** with 0 mismatches. This is an internal consistency result, not proof of the actual dressed lineup or complete Rule 84.4 eligibility. NOT_ASSESSED: the generator and independent validator exclude active ten-minute misconduct only; game-misconduct, match-penalty and designated-server exclusions are not represented as a complete checked set.

## Corrected conditional event rates

The prior report's 2019–20 training event-rate fit labeled 26,596 attempts and 227 goals as 5v4, 4,587 attempts and 325 goals as 4v5, and 10,154 penalties as 4v5. The v3 extractor reconciles each PBP situation code against both shift limits, excludes boundary conflicts and missing labels from conditional fitting, and uses the matching source state. These remain descriptive event-state rates, not uniformly pre-decision probabilities when a code matches only the right limit.

| Population | Event | Strength | Events | Exposure (team-min) | Rate / 60 (95% game-cluster CI) |
|---|---|---|---:|---:|---:|
| 2019/20 train | attempt | 5v4 | 26577 | 18077.8 | 88.209 ([86.834, 89.594]) |
| 2019/20 train | attempt | 4v5 | 4192 | 18077.8 | 13.913 ([13.449, 14.387]) |
| 2019/20 train | sog | 5v4 | 14739 | 18077.8 | 48.919 ([47.914, 49.922]) |
| 2019/20 train | sog | 4v5 | 3113 | 18077.8 | 10.332 ([9.942, 10.739]) |
| 2019/20 train | goal | 5v4 | 1925 | 18077.8 | 6.389 ([6.099, 6.670]) |
| 2019/20 train | goal | 4v5 | 260 | 18077.8 | 0.863 ([0.755, 0.965]) |
| 2019/20 train | penalty | 5v4 | 629 | 18077.8 | 2.088 ([1.930, 2.251]) |
| 2019/20 train | penalty | 4v5 | 524 | 18077.8 | 1.739 ([1.579, 1.896]) |
| 2021 development | attempt | 5v4 | 18806 | 11813.5 | 95.514 ([93.979, 96.999]) |
| 2021 development | attempt | 4v5 | 3104 | 11813.5 | 15.765 ([15.141, 16.335]) |
| 2021 development | sog | 5v4 | 10555 | 11813.5 | 53.608 ([52.488, 54.737]) |
| 2021 development | sog | 4v5 | 2282 | 11813.5 | 11.590 ([11.068, 12.086]) |
| 2021 development | goal | 5v4 | 1384 | 11813.5 | 7.029 ([6.653, 7.381]) |
| 2021 development | goal | 4v5 | 196 | 11813.5 | 0.995 ([0.852, 1.136]) |
| 2021 development | penalty | 5v4 | 498 | 11813.5 | 2.529 ([2.318, 2.757]) |
| 2021 development | penalty | 4v5 | 359 | 11813.5 | 1.823 ([1.613, 2.026]) |

Training penalty events at shift boundaries: 13,630; source codes matched the left limit: 11,057, right limit: 300, both: 528; excluded due to conflicts/missing state: 1,745. After exclusions, penalty event counts include 9,175 at 5v5, 629 at 5v4 and 524 at 4v5. The reported previous 10,154 at 4v5 was not a valid conditional label; the corrected extraction retains the evidence boundary and excludes ambiguous events rather than forcing all rows into a manpower bin.

### Rules and evidence interpretation

The pinned [2021–22 NHL Official Rules, Rule 26.1](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf) says a third player penalized while two teammates are serving does not begin serving until one earlier penalty expires; the third offender goes to the penalty bench, and a substitute may keep the team at no fewer than three skaters. Rule 26.2 also governs when the penalized players may return. The current model does not represent that queued service and substitution state, so the third-concurrent cases remain quarantined. It does not have evidence to pair a second penalty sampled at the same game-clock second with an existing penalty; that case remains quarantined as well. The actual synthetic candidate is not an observed penalty from the target game and has no one-to-one historical PBP event ID.

The corrected historical behavior audit is produced separately from this run comparison. It reports source `situationCode` against shift left-limit and right-limit states, excludes unresolved boundary labels from conditional-rate fitting, and retains source game/event identifiers for historical examples. Do not use the projected target-game outcomes as pregame inputs.

## Projected-roster, player-stat and goalie audit

Games checked: 120. Games with independently recomputed roster/event/TOI accounting findings: 0. Goalie-substitution event count: 366.

The audit reconciles event participants and on-ice IDs to projected rosters, team and player goals/shots/faceoffs/penalties/hits/blocks/shootout totals to emitted events, goalie saves/shots/goals to shot events, and player TOI to shift-ledger durations. Goalie identities and active on-ice presence are checked at shot and substitution events. Generated shootout shooter membership is PASS; complete Rule 84.4 exclusion handling remains NOT_ASSESSED. Legal goalie pull/return timing also remains `NOT_ASSESSED`: the records do not encode a validated stoppage or bench-window decision. The projected roster is not proof of the actual dressed target-game lineup.

## Full-population historical behavior audit

The corrected 2019–20 training / 2021 development behavior audit is in `NHL-BEHAVIOR-EVIDENCE-EVENT-STATE-V3-2026-10-27.md`, with its machine-readable counts in the sibling `results/nhl-behavior-evidence-event-state-v3-2026-10-27.json`. It separates event-state attribution, boundary uncertainty, and the matched shot cohorts; event-rate confidence intervals are now reported in the same per-60 units as their point estimates. 2021 is development-only diagnostic evidence, not fresh model-selection data.

## Decision

Roster membership and accounting are supported for the projected roster in this 120-record sample. The two new penalty quarantines are explained by unsupported queued service; all five remain quarantined pending an explicit queue/penalty pairing model and independent transition fixtures. Goalie identity/presence checks are possible, but legal pull/return timing remains unassessed. Gate 1 is **not passed**; no acceptance gate is changed.

### Frozen run provenance

Pre-roster games SHA-256: `296762f6bc87a8f8efcab17178aea6fc4d873d7a798675b8e496898fe645f9bf`  
Projected-roster v1 games SHA-256: `a10e79819367e096d445a836e308625b97a9ff177a88e53efbac6a6a800dfc7b`  
Telemetry rerun games SHA-256: `e7ba7846901387df3c2adf65e88eaf06a597f1e7bca7722d45044f8bdbbcfb59`  
Telemetry rerun summary SHA-256: `bd187c0f84229146822ccebba8f0f159519f7af7a4b613248803a50aabee7136`
