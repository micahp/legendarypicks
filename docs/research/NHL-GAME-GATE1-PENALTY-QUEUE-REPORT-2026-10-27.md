# NHL Gate 1: Queued Third-Penalty Repair Report

- **Date:** 2026-10-27
- **Branch:** `research/nhl-gate1-penalty-queue-2026-10-27`
- **Base:** `eee7b84d669d6e46f54c608b39c19971d9c6de88`
- **Preregistration commit:** `c2edec5f32a27c0f8eeb85db72c5739770603d60`
- **Scope:** One queued third concurrent manpower penalty under 2021–22 Rules 26.1/26.2; structural validation only.
- **Decision:** Four preregistered queue quarantines resolved. One same-clock ambiguity remains quarantined. Gate 1 remains **PARTIAL**.

## Result

The simulator now represents one queued third noncoincidental minor or major penalty as a distinct service state. The third penalty is recorded at assessment, its clock remains stopped, and the player remains barred from the ice. When an earlier same-team penalty expires, the simulator records the exact-time expiration and queued service start separately. It then records the expired player's return only when the modeled Rule 26.2 condition allows it; otherwise return waits for a modeled stoppage.

The independent validator reconstructs active, queued, and expired-but-not-returned penalties separately. It checks the service-start event, exact clock, deferred-return marker, manpower, and barred-player status. Unsupported additional queues and ambiguous ordering fail closed. The same-clock ambiguity was not modified.

## Paired 120-game diagnostic

The frozen population has six 2021 target games and 20 draws per target, with seeds `202610260001 + target_index * 100 + draw_index`. The final run paired to the frozen baseline on all 120 seeds, target games, draw indices, and pregame snapshot hashes: **zero pairing mismatches**.

| Measure | Frozen baseline | Queue repair | Change |
|---|---:|---:|---:|
| Generated games | 120 | 120 | 0 |
| Native generation/validation errors | 0 | 0 | 0 |
| Independent structural PASS | 115 | 119 | +4 |
| Penalty/manpower PASS | 115 | 119 | +4 |
| Penalty/manpower quarantines | 5 | 1 | -4 |
| Independent projected-roster accounting PASS | — | 120 | — |
| Independent projected-roster accounting findings | — | 0 | — |

The four formerly quarantined third-penalty cases now pass both native and independent validation:

| Seed | Game | Assessment → queued service start | Expired-player return |
|---:|---:|---|---|
| `202610260017` | `2021020001` | event 352, second 3322 → event 355, second 3377 | event 358, at stoppage |
| `202610285820` | `2021020262` | event 158, second 1488 → event 166, second 1552 | event 178, at stoppage |
| `202610363311` | `2021021050` | event 121, second 991 → event 124, second 1003 | event 132, when entitled during play |
| `202610389108` | `2021021179` | event 14, second 117 → event 19, second 135 | event 29, at stoppage |

The remaining quarantine is the preregistered same-clock case, seed `202610285818` (game `2021020262`, event 197). It remains classified `QUARANTINED` because available evidence does not resolve the required penalty ordering. It is not counted as a pass.

Across the full run, 11 structural check categories passed on all 120 records. Penalty/manpower passed on 119 and remained quarantined on one. Four checks were `NOT_ASSESSED` on all 120 records: line-change legality, goalie-transition timing, geometry/officiating, and actual dressed-lineup eligibility. No game received `full_rule_assessed`; this repair does not establish complete rule compliance.

An additional independent projected-roster accounting pass recomputed all 120 records and found no player/team/goalie/shift accounting discrepancies. Fixed-seed smoke replay produced byte-identical canonical JSON on both runs (SHA-256 `56b510f2437d37b9c61bf20429decb707916abde66c68339e8c309eeb9129f6c`).

## Implementation and verification

Changes are confined to the research simulator's penalty ledger and event replay, its independent Gate 1 validator and diagnostic runner, and focused unit tests. The runner records the preregistration commit and frozen branch base in its output metadata. Generated game records remain outside Git.

Verification commands and results:

```text
python3 -m py_compile \
  research/nhl/statistical-full-game-v0.2b/game_state.py \
  research/nhl/statistical-full-game-v0.2b/nhl_game_state_sim.py \
  research/nhl/statistical-full-game-v0.2b/tests/test_simulator_state.py \
  research/nhl/game-rules-gate1/validator.py \
  research/nhl/game-rules-gate1/run_diagnostic_sample.py \
  research/nhl/game-rules-gate1/tests/test_validator.py
```

Passed: `py_compile`; `git diff --check`; 49 simulator state tests (`python3 -m unittest discover -s research/nhl/statistical-full-game-v0.2b/tests -p 'test_*.py'`); 25 independent Gate 1 validator tests (`python3 -m unittest discover -s research/nhl/game-rules-gate1/tests -p 'test_*.py'`); and the fixed-seed reproducibility smoke. The full diagnostic run generated all 120 requested records in 92.041 seconds of wall time, with 34.438 seconds fitting and median game runtime 0.439 seconds.

Final output is stored outside the repository at:
`/root/lp-data/nhl-game-rules-gate1-2026-10-27-penalty-queue-120-v4/`.

| Artifact | SHA-256 |
|---|---|
| `games.jsonl` | `c813882996a545fc1dbd090781ba661d1db46725f8e70422233947ed6cedfc01` |
| `failures.jsonl` | `4a5dfcc78e621f401fb9c377eae261d81417288d65d9fb195cdf7e95d54ae897` |
| `summary.json` | `c29d04260dfbc070e94a141651653305c617bf7b7a6402490f1c5cac64ba05e4` |

## Boundaries and remaining work

- This is a structural rules repair, not predictive-model evaluation or candidate selection.
- No acceptance threshold or Gate 1 status was changed. The remaining ambiguity keeps Gate 1 partial.
- The 120 draws are clustered across six fixed matchups and are not a season-wide estimate.
- Puck/player geometry, official lineup eligibility, explicit line-change events, and legal goalie bench windows remain unassessed because the simulated record does not contain the required evidence.
- No production forecasts, databases, frozen Phase 2A artifacts, or Gridiron Physics files were changed.

The rule interpretation follows the 2021–22 NHL Official Rules, Rules 26.1/26.2: [official rulebook PDF](https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf). The report and preregistration do not claim that GameCenter timestamps independently identify canonical penalty clocks for historical source fixtures.
