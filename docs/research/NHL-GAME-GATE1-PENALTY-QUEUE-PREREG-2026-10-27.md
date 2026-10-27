# NHL Gate 1: Queued Third-Penalty Repair Preregistration

- **Date:** 2026-10-27
- **Branch:** `research/nhl-gate1-penalty-queue-2026-10-27`
- **Base:** `eee7b84d669d6e46f54c608b39c19971d9c6de88`
- **Scope:** Rule 26.1/26.2 queue service for one third concurrent manpower penalty; structural validation only.
- **Status:** Frozen before implementation and rerun.

## Question

Can the v0.2b simulator represent one queued third MIN/MAJ penalty and its later service/release without omitting the penalty, corrupting manpower, or weakening the independent Gate 1 validator, on the same fixed 2021 diagnostic sample that exposed four queued-service quarantines?

This is not a predictive-model comparison, candidate-selection exercise, adoption test, or Gate 1 threshold change. The same-clock ambiguous penalty case remains quarantined and out of scope.

## Source rule and evidence boundary

Apply the 2021–22 NHL Official Rules, Rule 26.1 and 26.2: the third offender goes to the penalty bench while a substitute may keep the team at no fewer than three skaters; the third penalty clock starts when one of the first two penalties expires. Under Rule 26.2, expiration and a player's eligibility to return are distinct transitions: return is ordered by expiration, may occur during play only when the team is entitled to more than four players, and otherwise waits for a stoppage. Same-time returns requiring captain-designated order are unsupported and must remain explicitly quarantined.

Official rules source: <https://media.nhl.com/site/asset/public/ext/2021-22/2021-22Rules.pdf>.

The 4,876-game GameCenter/shift archive is retained as context, but its penalty event timestamps, nominal durations, and shift endpoints do not provide a canonical penalty-clock service or release record. Apparent overlap candidates are not treated as exact Rule 26 fixtures. The four fixed generated records are the debugging cases; hand-authored tests exercise the declared state transitions and illegal counterexamples.

## Frozen population and baseline

Use the unchanged 120-record diagnostic population: 2021 eligible target indices `0, 258, 516, 775, 1033, 1291`, 20 draws per target, with the existing mapping and seed rule:

```text
seed = 202610260001 + target_index * 100 + zero_based_draw_index
```

Use only the existing 2019/2020 model-training population, forward-only 2021 pregame history, and hash-verified GameCenter PBP/box-score/shift artifacts. Preserve all 120 seed attempts, including errors and quarantines. Write generated outputs only to a new `/root/lp-data/` directory.

Frozen projected-roster baseline: 115/120 structural PASS and five penalty quarantines. Four are third-concurrent service cases:

| Seed | Game | Period / clock | Side | Active manpower penalties before candidate |
|---:|---:|---|---|---:|
| 202610260017 | 2021020001 | P3 15:22 | away | 2 |
| 202610285820 | 2021020262 | P2 04:48 | home | 2 |
| 202610363311 | 2021021050 | P1 16:31 | home | 2 |
| 202610389108 | 2021021179 | P1 01:57 | away | 2 |

Seed `202610285818` (`2021020262`, P2 11:01) is the distinct same-clock ambiguity and must remain quarantined. Do not change its input, event, or status to improve the result.

## Candidate behavior, frozen

1. Keep active service, queued service, and expired-but-not-yet-released players as distinct ledger states.
2. A third noncoincidental MIN/MAJ is recorded as a penalty; its clock remains stopped until an earlier same-team active manpower penalty expires or is otherwise fully ended by an applicable rule transition.
3. The queued offender remains barred from the ice while a substitute preserves legal manpower, with the three-skater floor maintained.
4. On service start, record an explicit event at the exact triggering game-clock second. Expiration does not imply immediate player return when Rule 26.2 delays it.
5. Permit an expired player's return during play only when the team is entitled to more than four players; otherwise emit an explicit release at the first modeled stoppage. Preserve expiration order. If a same-time return order is required and unavailable, fail closed with a quarantine/error.
6. Support at most one queued manpower penalty at a time. A second unsupported queued assessment, simultaneous expiry/order ambiguity, or unresolved queue transition remains visible as quarantine/error; never convert it silently to a stoppage.
7. Keep the existing same-clock penalty pairing quarantine unchanged.

## Frozen tests and acceptance criteria

### State and event tests

- Third penalty assessment queues without starting its timer; the assessed player is barred; active manpower remains capped at two penalty units and at least three skaters.
- The queue starts exactly when one earlier active penalty ends; its full duration begins at that clock.
- Expiration, service start, and Rule 26.2 release are separately represented and independently replayable.
- If the entitled on-ice count remains four or fewer, release waits until a modeled stoppage; if it exceeds four, the next eligible return follows expiration order.
- A power-play goal that fully ends an earlier minor starts the queued service at that game-clock second and resolves the expired player's return at the goal stoppage. A first segment of a double minor does not start queued service.
- Unsupported second queue and ambiguous same-clock return ordering fail closed.
- Existing non-queued penalty, double-minor, coincidental, manpower, restart, and fixed-seed behavior remains covered.

### Same-seed full-game rerun

- Generate and retain all 120 records on the unchanged seeds and inputs.
- Resolve the four listed queued-service quarantines with legal penalty, clock, personnel, and restart records.
- Preserve seed `202610285818` as the only unchanged penalty quarantine; it must not be counted as a pass.
- Introduce no new native validation errors, independent hard failures, silent omissions, or dropped seeds.
- Keep all existing score, SOG, player, goalie, clock, period, overtime/shootout, and shift-ledger accounting checks unchanged.
- Confirm deterministic byte-identical canonical output for the same frozen input and seed.
- Report per-check PASS/FAIL/QUARANTINED/NOT_ASSESSED counts, all failing seeds, elapsed runtime, and hashes. Do not report predictive scores as evidence for this structural repair.

Any criterion not met is reported as failure. Do not alter validator thresholds, reduce the sample, retune event probabilities, or claim full-rule assessment. The 120 draws remain clustered diagnostics across six fixed matchups, not a season-wide estimate.

## Guardrails

- Research-only isolated branch; do not modify production forecasts, databases, frozen Phase 2A results, or Gridiron Physics.
- Do not use target-game outcomes, target-game actual lineups, actual goalie starters, shifts, the exposed 2022 season, ESPN, or newly acquired sources as pregame inputs.
- Keep raw and generated full-game records outside Git.
- Do not change Gate 1 acceptance criteria; one same-clock quarantine means Gate 1 remains partial.
- Commit the preregistration before implementation and the fixed-population run. No push is part of this preregistration.
