# NHL Game Gate 1 Transition Hardening: Results

- **Date:** 2026-10-26
- **Branch:** `research/nhl-gate1-transition-hardening-2026-10-26`
- **Development base:** `28f521f33a574bfb8f720cc9f972a5f9919d3883`
- **Rules specification:** upstream commit `bd40781306ae40d7fb33c33b986b7ee0e9c5be52`
- **Generator baseline:** `research/nhl-game-state-v02b-2026-10-25` at `60c428ad`
- **Preregistration:** `313661e662f407779ada533d724006bc36552c12`
- **Independent validator:** `nhl-independent-gate1-v0.2`
- **Result:** restart checks pass on the fixed sample; the preregistered penalty/manpower gate fails.

## Finding

Explicit simulated faceoffs repaired the sampled restart-sequence failures: all
120 records pass the independent restart-sequence and restart-location checks.
The candidate does **not** pass the preregistered Gate 1 criteria. Only 60 of
120 records are structurally valid, 52 records fail the penalty/manpower check,
four penalty cases are quarantined, and three records raise native validation
errors. No record is `full_rule_assessed`.

The dominant confirmed defect is in manpower derivation. The simulator reduces
manpower using the *difference* between each team's active noncoincidental
penalty counts. The independent rule check derives each team's eligible skaters
from that team's active penalty units. For example, when each side has one
active minor, the simulator emits 5v5 while the independent check expects 4v4.
There are 553 such manpower-mismatch findings across 45 records; 453 are this
5v5-versus-4v4 pattern. The relevant code is
[PenaltyLedger.manpower](../../research/nhl/statistical-full-game-v0.2b/game_state.py)
and the independent calculation is in
[validator.py](../../research/nhl/game-rules-gate1/validator.py).

The 11 reported unmatched-expiry findings are all for 600-second misconducts.
The validator quarantines misconduct at the penalty event because it supports
only minors and majors, then later reports the misconduct expiry as unmatched.
These are validator-coverage findings, not independent evidence that the
simulator expired those misconducts at the wrong time. They remain in the
unchanged re-audit counts and must be resolved by an independently specified
validator extension before those expiries can be judged.

Against the original fixed-seed sample, restart-sequence status improved from
120 failing records to zero, and structural validity rose from 0/120 to 60/120.
The penalty result is newly more informative rather than directly comparable:
the original records omitted the coincidental flag, leaving 79 penalty checks
`NOT_ASSESSED` and 27 `QUARANTINED`; this candidate makes the classification
explicit and exposes 52 `FAIL` and 64 `PASS` checks (plus four quarantines).
The new failures are not evidence that this candidate is worse than the
original; they show a defect the original record could not measure.

This is a fixed six-matchup development diagnostic, not a season-wide failure
rate. No predictive metrics were evaluated, no candidate was selected, and no
rule gate was changed.

## Scope and reproducibility

The experiment followed the preregistered six 2021 targets, with 20 fixed seeds
per target. Inputs used 2019/2020 training seasons and forward-only pregame
history; target-game results, actual lineups, starters, shifts, databases, ESPN,
and new sources were not used. Seeds followed the frozen mapping
`202610260001 + target_index * 100 + draw_index`. The six selected targets were:

| Target index | Game ID | Date |
|---:|---|---|
| 0 | `2021020001` | 2021-10-12 |
| 258 | `2021020262` | 2021-11-20 |
| 516 | `2021020599` | 2022-01-06 |
| 775 | `2021020533` | 2022-02-19 |
| 1033 | `2021021050` | 2022-03-27 |
| 1291 | `2021021179` | 2022-05-01 |

All 120 full records were generated with zero generation exceptions. The run
took 110.309 seconds total: 48.610 seconds for model fitting, 58.872 seconds
for game generation, and 0.433 seconds median per game. A fixed-seed smoke
record was byte-identical after canonical JSON serialization on repetition
(seed `202610260001`, record SHA-256
`9ad661e121d54bfd6c7ecaf7e356aadb137973c3076ec190744302dc93b92202`).

The first full-run attempt stopped at seed `202610285809` after 28 completed
records when the runner's memory guard observed 1.44 GiB available. Those
partial outputs remain preserved separately and were not combined with the
complete sample. The complete rerun used a new output directory and retained
all 120 deterministic seeds. The partial attempt contains 28 generated records
and 17 preserved native or independent failure rows; its `games.jsonl` SHA-256
is `0e3b34430065408d50f754246b24e39508572a633674d3b42e52f8e7de6f259d` and its
`failures.jsonl` SHA-256 is
`9076e5cbeee234af89f294abc747e5226b3ac176cb396a34d0d2145b8d902a17`.

Generated games and re-audit artifacts remain outside Git:

- Complete sample: `/root/lp-data/nhl-game-rules-gate1-transition-hardening-full-2026-10-26/`
- Independent re-audit: `/root/lp-data/nhl-game-rules-gate1-transition-hardening-reaudit-2026-10-26/`
- Preserved memory-aborted attempt: `/root/lp-data/nhl-game-rules-gate1-transition-hardening-2026-10-26/`
- Reproducibility smoke: `/root/lp-data/nhl-game-rules-gate1-transition-hardening-smoke-2026-10-26/`

Input manifest hashes were PBP `d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990`,
box scores `0ba44bcebefecb0a8eefbea995e8f5370583600eec77d0be12be574f308d71a2`,
and shifts `deba1a38d9f9c969139dc15ac57e7085988c05bcab36db43bd87fe5805f1c6f5`.
The pinned ruleset is the 2021–22 rulebook, SHA-256
`17ef416dcb556f510df51efd45451e8d37da80da9e69488f78e3d8771228caa7`.

| Artifact | SHA-256 |
|---|---|
| Complete `games.jsonl` | `8637cbfbd56a8438db08c1da93bba618a5e520868cd7e2abcc6fd2becbf133fb` |
| Complete `failures.jsonl` | `9151b74827c83081cb040f45c984b94c0bf9775ddee02be32ec660421a8a128b` |
| Generation `summary.json` | `b039a70de4d2f75f4360989c5cfac910da9db0315b7334c51de5be201372e408` |
| Re-audited records | `08f81d121980163ec048d8f36af44618d196498faab7424b15aef7420e181a1c` |
| Re-audit `summary.json` | `280f8d586103faf9c002294add55ec77ca165047dd791f69678392cc43b40a87` |
| Re-audit sample index | `28cc4872a306fc34792b4af41ff0c3d73b14be810ec9b33da363c0c14695bec3` |

Code hashes used by the completed sample: simulator `ab99f0a9dd3e1902fa2df56997320eba9339735e3838c6a080d5509cbf7301fe`,
`game_state.py` `31426421cd3875129318c81114e2f9dc5187600cf771052d1b9d16fd788f05b4`,
historical adapter `f465de98b03de9b808a9ef32adaef7c0c54a30fc5d941f5d48f99d88d9e066a5`,
runner `8497b7136ccbcd1b88e52eba8b22c702bb0afcd2baf59ba5189e87391301bb06`,
and validator `91f7161e7f6ec0a4e8d1dd64ca9db2391d6a886bff9571507f7b010104606688`.

## Independent re-audit

The independent validator was run after generation against the frozen records;
the simulation was not repeated or altered during re-audit.

| Check | PASS | FAIL | NOT_ASSESSED | QUARANTINED |
|---|---:|---:|---:|---:|
| Event schema | 120 | 0 | 0 | 0 |
| Event order and clock | 120 | 0 | 0 | 0 |
| Score and terminal state | 120 | 0 | 0 | 0 |
| Roster-pool membership | 120 | 0 | 0 | 0 |
| On-ice personnel identity | 120 | 0 | 0 | 0 |
| Shift interval integrity | 120 | 0 | 0 | 0 |
| Restart sequence | 120 | 0 | 0 | 0 |
| Restart location | 120 | 0 | 0 | 0 |
| Penalty and manpower | 64 | 52 | 0 | 4 |
| Overtime and shootout | 112 | 0 | 8 | 0 |
| Line-change legality | 0 | 0 | 120 | 0 |
| Goalie-transition state | 0 | 0 | 120 | 0 |
| Dressed-lineup eligibility | 0 | 0 | 120 | 0 |
| Geometry and officiating | 0 | 0 | 120 | 0 |
| Ruleset binding | 120 | 0 | 0 | 0 |

Overall, 60/120 records are structurally valid and 60/120 have at least one
structural or native validation failure. The three native `ValueError`s report
penalty-manpower mismatches at event 315 (`2021020001`, seed `202610260005`),
event 357 (`2021020001`, seed `202610260007`), and event 138 (`2021020599`, seed
`202610311606`). Native validation passed for 117 records.

The penalty/manpower findings contain:

- **553** derived-manpower mismatches in **45** records. The largest pattern
  (453 findings) is actual 5v5 versus independently expected 4v4 while both
  goalies remain in net. Other mismatches include stacked penalties and
  goalie-pulled states.
- **11** unmatched-expiry findings in 11 records. Each follows a 600-second
  misconduct event that the independent validator quarantines as unsupported;
  the validator then cannot match its later expiry.
- **4** quarantine findings: three penalty transitions explicitly omitted by
  the generator's supported subset and one misconduct kind/duration outside the
  validator's supported table.

The fixed sample has 20 seeds for each of six matchups. These are clustered
simulation draws over six preselected games, not 120 independent historical
games. No confidence interval or season-wide failure-rate interpretation is
claimed.

## Transition fixture coverage and remaining evidence gaps

The 18 independent-validator unit tests passed. Four official-source examples
remain available from the [prior Gate 1 audit](NHL-GAME-GATE1-VALIDATION-REPORT-2026-10-26.md): goal then center faceoff, penalty
then faceoff, a shift boundary at faceoff time, and a shootout ending after two
paired rounds. Synthetic positive and deliberately invalid tests cover all six
requested transition families. This fixture coverage validates the checker
subset; it does not establish that the generated games obey each rule.

| Transition family | Sample result | Remaining limit |
|---|---|---|
| Goal → center faceoff | Restart sequence and center location pass in 120/120. | Does not validate unrelated non-center faceoff locations. |
| Minor/double-minor/major service, expiry, manpower | Independent check fails in 52 records; four more are quarantined. | Simulator manpower uses net penalty difference. Misconduct is not modeled by the independent validator. |
| Line change | Synthetic legal/illegal cases pass. | Generated records contain no explicit incoming/outgoing line-change events; 120/120 are `NOT_ASSESSED`. |
| Goalie pull/return | Synthetic accounting cases pass. | Legal stoppage/bench windows are absent; 120/120 are `NOT_ASSESSED`. |
| Regulation → OT → shootout and early termination | 112 pass; 8 are `NOT_ASSESSED`. | The game-dressed shootout-eligible lineup and Rule 84.4 exclusions are absent. |
| Unsupported/contradictory event | Deliberately invalid cases are rejected by the independent validator tests. | These synthetic cases do not measure how often the generator reaches such a state. |

None of the games is `full_rule_assessed`. PBP-derived event records do not
contain player/puck trajectories or the officials' evidence for offside,
icing, goalie interference, and other geometry-dependent decisions. The
pregame roster pool also does not prove the submitted dressed lineup. A
`NOT_ASSESSED` result remains unknown, not a pass.

## Tests and decision

Commands run successfully:

```bash
python3 -m unittest discover -s research/nhl/statistical-full-game-v0.2b/tests -p 'test_*.py' -v
python3 -m unittest discover -s research/nhl/game-rules-gate1/tests -p 'test_*.py' -v
python3 -m py_compile research/nhl/statistical-full-game-v0.2b/nhl_game_state_sim.py research/nhl/statistical-full-game-v0.2b/game_state.py
git diff --check
```

Results: 37 simulator/game-state/data tests passed; 18 independent Gate 1
validator tests passed; both Python modules compiled; the diff check passed.
These tests did not cover balanced active noncoincidental minors in
`PenaltyLedger.manpower`, which is the main newly measured defect.

The restart repair is supported by the frozen development diagnostic. The
overall candidate remains **not passed** under the preregistered criteria and
is not selected for adoption. The next research slice should separately
preregister: (1) per-team penalty-unit manpower accounting, including the
special overtime table; (2) independent validation of misconduct service and
expiry as a non-manpower penalty; and (3) an expanded transition sample after
those fixes. Keep the rules gate and production forecasts unchanged.

## Reproduction

The complete run and validator-only re-audit were:

```bash
python3 research/nhl/game-rules-gate1/run_diagnostic_sample.py \
  --games 6 --draws 20 \
  --output-dir /root/lp-data/nhl-game-rules-gate1-transition-hardening-full-2026-10-26

python3 research/nhl/game-rules-gate1/reaudit_sample.py \
  --source-dir /root/lp-data/nhl-game-rules-gate1-transition-hardening-full-2026-10-26 \
  --output-dir /root/lp-data/nhl-game-rules-gate1-transition-hardening-reaudit-2026-10-26
```

The complete sample and re-audit data are local external artifacts, not Git
files. The prior Gate 1 report, rule specification, original sample, Phase 2A
results, production forecasts, databases, and Gridiron repository were not
modified.
