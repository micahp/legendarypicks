# NHL Statistical Game Generator: Gate 1 Independent Validation

- **Date:** 2026-10-26
- **Branch:** `research/nhl-gate1-validator-2026-10-26`
- **Base:** `bd40781306ae40d7fb33c33b986b7ee0e9c5be52`
- **Rules contract:** [NHL Game Rules and Validity Specification](NHL-GAME-RULES-VALIDITY-SPEC-2026-10-26.md)
- **Validator:** `nhl-independent-gate1-v0.2`

## Finding

The v0.2b simulator did not pass the independent Gate 1 sample. All 120 generated records had at least one recorded restart-sequence failure; 14 also had an assessable penalty/manpower failure. The simulator’s own validator returned success for 119 records and raised one penalty-expiry `ValueError`; the independent audit therefore found structural defects that native validation did not catch.

This was a six-matchup diagnostic sample, not a random or independent population estimate. It does not establish a 2021 season-wide failure rate. The evidence is sufficient to say the sampled generator cannot be described as structurally valid. No rule gate, production forecast, simulator, or frozen Phase 2A artifact was changed.

## Scope and method

The validator reads the emitted event record and imports no simulator or game-state transition code. It does not repair input. It emits a separate `PASS`, `FAIL`, `NOT_ASSESSED`, or `QUARANTINED` status for each check. A missing field remains unassessed. `structural_valid` requires the supported structural checks to pass; `full_rule_assessed` additionally requires evidence for applicable rules that depend on lineups, geometry, and officiating.

The target population was the 1,292 eligible 2021 development games. Six fixed, evenly spaced targets were selected at indices 0, 258, 516, 775, 1033, and 1291. Twenty fixed seeds were generated per target, for 120 total games. Targets were dated 2021-10-12, 2021-11-20, 2022-01-06, 2022-02-19, 2022-03-27, and 2022-05-01. The exact game IDs and all seeds, snapshot hashes, record hashes, and statuses are in [sample-index.json](../../research/nhl/game-rules-gate1/sample-index.json).

The historical adapter used the 2019 and 2020 start seasons for training. The runner required `latest_history_date < target_date`, confirmed that target-game results and lineups were not inputs, and withheld same-date outcomes until all selected same-day targets had been generated. It used no database. The 2021–22 official rulebook was pinned by SHA-256 `17ef416dcb556f510df51efd45451e8d37da80da9e69488f78e3d8771228caa7` ([official NHL rulebook](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf)).

Generation completed 120/120 records with zero generation exceptions. It took 127.967 seconds total: 65.316 seconds for fitting, 56.620 seconds for generation, and 0.446 seconds median per game. The sample was serialized. A repeated fixed-seed smoke run produced byte-identical canonical simulation records. Full game records remain outside Git.

The repeated smoke record hash was `ab0c05b8bfefb11444ea6434b4f9e68156b7934f2dac45149193dd03fad45874`. The original full sample is preserved at `/root/lp-data/nhl-game-rules-gate1-2026-10-26/`; its `games.jsonl` SHA-256 is `d5e26a843defa2016ab03322910fc134450528ae90c433de1d812aa899365c4a`. The independent validator was then corrected to treat an absent penalty-coincidence field as missing evidence, and all 120 unchanged simulation records were re-audited without rerunning Monte Carlo. The re-audit is at `/root/lp-data/nhl-game-rules-gate1-reaudit-2026-10-26/`; its `reaudited-games.jsonl` SHA-256 is `6a6e82840c1baf5469009948cf49dcef3b219547c3ef8fd4ee9d2dc26666f55f` and summary SHA-256 is `8619285056cd8ebbd9b42149aeca3175e35e687753b3a6c9eaa3875750ef1818`.

Input manifest hashes: PBP `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990`; box scores `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2`; shifts `deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5`. Frozen generation code hashes: simulator `b392a221ab4074135dc44b96d02c9efb1c0f8d98121b8852ee9333f5da210766`, `game_state.py` `31426421cd3875129318c81114e2f9dc5187600cf771052d1b9d16fd788f05b4`, historical adapter `f465de98b03de9b808a9ef32adaef7c0c54a30fc5d941f5d48f99d88d9e066a5`, and sample runner `8497b7136ccbcd1b88e52eba8b22c702bb0afcd2baf59ba5189e87391301bb06`. Final validator SHA-256: `91f7161e7f6ec0a4e8d1dd64ca9db2391d6a886bff9571507f7b010104606688`. The committed seed/status index SHA-256 is `93731e7b95d6c0298143502dbe2322cee2edb9b5db0193634a8faa009343503c`.

## Independent-source transition coverage

Four source-backed fixtures were verified against the archived manifest and compressed-body hashes. They establish specific observed transitions; they are not treated as complete rule adjudications.

| Transition | Independent NHL evidence | Boundary |
|---|---|---|
| Goal → center faceoff | GameCenter `2021020001`, 2021-10-12: goal and center faceoff both at P2 00:12 | Confirms one recorded source sequence, not simulator compliance generally. |
| Minor penalty → faceoff | Same game at P2 12:56 | Does not establish penalty service, expiry, manpower, or correct faceoff spot. |
| Shift boundary at faceoff | NHL shift chart records one PIT player off and another on at P2 12:56 | Does not establish complete on-ice lineup or legal bench-window ruling. |
| Shootout early decision | GameCenter `2021020018`, PHI–VAN: tied 4–4 after OT; VAN wins after two paired attempts, official score 5–4 | Confirms an actual early-ending source case; not shooter eligibility or simulator compliance. |

Synthetic positive and deliberately illegal cases cover exact minor expiry, early expiry, double-minor segment handling, major-penalty persistence, legal/illegal line-change participants, goalie pull/return accounting, goal restarts, and early shootout termination. Tests also verify that the validator does not import simulator state logic and does not mutate its input. These controlled cases test the validator’s declared subset; they do not replace real whole-game fixtures.

## Sample results

The game-level counts below are out of 120 records. `NOT_ASSESSED` and `QUARANTINED` are not passes.

| Independent check | PASS | FAIL | NOT_ASSESSED | QUARANTINED |
|---|---:|---:|---:|---:|
| Event schema, order/clock, score/terminal, roster-pool membership, ruleset binding, shift-interval integrity | 120 each | 0 | 0 | 0 |
| Restart sequence | 0 | 120 | 0 | 0 |
| Penalty and manpower | 0 | 14 | 79 | 27 |
| On-ice personnel | 17 | 0 | 103 | 0 |
| Overtime and shootout | 112 | 0 | 8 | 0 |
| Restart location | 0 | 0 | 120 | 0 |
| Line-change legality, goalie-transition legality, dressed-lineup eligibility, geometry/officiating | 0 each | 0 | 120 each | 0 |

Overall, **0/120** records passed the supported structural core, and **0/120** were fully rule-assessed. This is not because geometry-dependent `NOT_ASSESSED` checks were silently treated as failures: they are reported separately. Structural validity is blocked by the restart failures and, where applicable, by penalty/personnel states that the record cannot establish or that contradict the supported rule checks.

### Confirmed transition defects in the emitted records

- The independent restart check found **650 goals**, **88 stoppages**, and **15 penalties** whose recorded sequence did not reach a faceoff before subsequent live play or a valid terminal boundary. Every sampled game had at least one such event. Example: game `2021020001`, seed `202610260001`, event 48 is a regulation goal at P1 elapsed 645 seconds; event 49 is a hit, with no intervening faceoff. The source-backed GameCenter fixture records a goal followed by a same-clock center faceoff, so the check is consistent with an observed NHL sequence.
- These are event-record transition failures under the emitted schema. The generated stoppage records generally lack a cause and faceoff requirement/location, so this audit does not claim to adjudicate every official whistle or the legally correct faceoff dot.
- One generated game, `2021020533` seed `202610337517`, caused the native validator to raise `ValueError: active penalty reached expiry without a preceding expiration event`. The returned record independently shows the penalty still active at its expiry clock and its server on the ice at event 183.
- Fourteen records had a hard penalty/manpower check failure: nine unmatched/early/late expiration findings, one exact expiry without an expiration event, one active penalty server on the ice, and five assessable skater-count mismatches. These are 16 event-level findings across 14 seeds, not 16 independent games.

### Penalty evidence correction

The first validator draft treated an omitted `coincidental` flag as `false` and reported 732 apparent manpower mismatches. Inspection of the preserved records found the field absent from all 819 generated penalty events. Because the record contract requires that classification, those manpower conclusions were not independently supported. Validator v0.2 now reports the missing classification as `NOT_ASSESSED` and suppresses derived manpower conclusions while the active state is ambiguous. The final counts above come from re-auditing the exact same 120 simulation records; the earlier 732 count is superseded and is not used as a legality finding.

After that correction, 79 games had a penalty check `NOT_ASSESSED`, 27 were `QUARANTINED` by unsupported penalty states, and 14 still had a hard `FAIL`. Across event findings, the penalty check contains 536 `NOT_ASSESSED`, 38 `QUARANTINED`, and 16 `FAIL` rows. The 38 quarantine findings comprise 36 explicitly omitted unsupported transitions and two penalty kind/duration combinations outside this validator’s supported table.

## What the evidence does not establish

- All 120 records use a pregame roster pool, not a verified submitted/dressed lineup. Roster-ID membership passing does not prove game eligibility.
- On-ice records omit goalie-pulled state in enough events that personnel assessment is incomplete in 103 games. The shift ledger can reconcile intervals while still failing to prove a legal line change, bench window, or icing restriction.
- Restart locations are absent: 649 applicable restart observations were not assessable. Exact faceoff placement cannot be validated from this generator record.
- Goalie pull/return legality, goalie interference, offside, icing, hand passes, high sticks, out-of-bounds decisions, and other geometry/officiating rules remain unassessed because the record lacks the required positions and official decision evidence.
- Eight overtime/shootout checks are unassessed because the record does not establish the game-dressed shootout-eligible roster. The real two-pair fixture only validates the early-termination comparison case.
- The six targets were selected deterministically, not randomly. Seeds within the same matchup share a pregame snapshot, so a confidence interval over 120 draws would overstate independent game coverage. No season-wide rate or adoption inference is reported.

## Gate 1 decision and boundary

The Gate 1 result for this diagnostic sample is **not passed**: 120/120 records contain a restart-sequence failure, with additional assessable penalty-state failures. The fixed rules contract and its status definitions are unchanged. The immediate implementation work indicated by this audit is to make goal/stoppage restarts explicit and to emit complete penalty classification and expiry state; after those repairs, run the same independent checks on a broader frozen population with preserved failures.

This audit does not establish gameplay causality (Gate 2) or gameplay realism/evidence coverage (Gate 3). It does not select a candidate model, change production behavior, or demonstrate that sampled statistical events were caused by simulated hockey mechanics. Gates 2 and 3 still need separate implementation and measurement protocols.

## Reproduction

The original sample command was:

```bash
python3 research/nhl/game-rules-gate1/run_diagnostic_sample.py \
  --games 6 --draws 20 \
  --output-dir /root/lp-data/nhl-game-rules-gate1-2026-10-26
```

The final validator-only audit, which reuses the unchanged generated records, was:

```bash
python3 research/nhl/game-rules-gate1/reaudit_sample.py \
  --source-dir /root/lp-data/nhl-game-rules-gate1-2026-10-26 \
  --output-dir /root/lp-data/nhl-game-rules-gate1-reaudit-2026-10-26
```

Validation commands:

```bash
python3 -m unittest discover -s research/nhl/game-rules-gate1/tests -v
python3 -m py_compile \
  research/nhl/game-rules-gate1/validator.py \
  research/nhl/game-rules-gate1/run_diagnostic_sample.py \
  research/nhl/game-rules-gate1/reaudit_sample.py \
  research/nhl/game-rules-gate1/tests/test_validator.py
git diff --check
```

The final test suite contains 18 tests, including four hash-verified NHL source fixtures and deliberately invalid synthetic transitions.
