# NHL Gate 1 Transition Hardening: Preregistration

- **Date:** 2026-10-26
- **Branch:** `research/nhl-gate1-transition-hardening-2026-10-26`
- **Dev base:** `28f521f33a574bfb8f720cc9f972a5f9919d3883`
- **Generator baseline:** `research/nhl-game-state-v02b-2026-10-25` at `60c428ad`
- **Rules contract:** `NHL-GAME-RULES-VALIDITY-SPEC-2026-10-26.md`
- **Scope:** structural transition repair and independent diagnostic only

## Question

Do explicit rule-driven restarts and complete same-clock penalty state make the
v0.2b emitted records pass the supported independent Gate 1 checks on the same
fixed 2021 development sample that exposed restart and manpower failures?

This is not a predictive-model comparison, candidate selection, adoption test,
or gate change. The existing alpha2/v0.2b baseline, Phase 2A artifacts, prior
Gate 1 sample, prior report, and 2021 paired-score results remain unchanged.

## Frozen sample

Use the six target games at eligible 2021 indices `0, 258, 516, 775, 1033,
1291` from the previously audited population of 1,292 games. Generate exactly
20 seeds per target, for 120 full-game records. Preserve the prior deterministic
seed rule:

```text
seed = 202610260001 + target_index * 100 + zero_based_draw_index
```

The target mapping, source history cutoff, training population, shift manifest,
and independent validator are the same as the original Gate 1 diagnostic. Use
only the 2019/2020 training population and forward-only 2021 pregame history.
Do not use target-game results, actual lineups, actual goalie starters, shifts,
2022, the NHL databases, ESPN, or any new source acquisition.

The new generated records, failures, summary, and re-audit outputs must be
written to a new `/root/lp-data/` directory. Never overwrite the original
120-game sample or its re-audit.

## Candidate changes under test

1. Require a center-ice faceoff at period start and after a non-terminal goal.
   Prefer an existing donor faceoff only when it is at the exact required clock;
   otherwise generate a faceoff from the current simulated on-ice players and
   update faceoff totals and latent possession.
2. Require faceoffs after generated penalties and stoppages before later live
   play. When the event record has no zone state, leave the non-center faceoff
   location explicitly unassessed.
3. Emit a Boolean coincidental-penalty classification for every generated
   penalty. Pair only the matching simultaneous opposite-team penalties
   supported by the simulator's existing penalty ledger.
4. Order exact-clock penalty-expiration events before same-clock personnel
   transitions; include explicit goalie-pulled state on generated goalie
   substitution events.

No other event rates, conversion probabilities, model parameters, source
eligibility rules, or predictive score metrics are tuned in this experiment.

## Frozen checks and success criteria

### Required correctness checks

- Existing simulator-state unit tests pass, including explicit restart
  accounting and expiry-before-goalie-change ordering tests.
- Existing independent Gate 1 validator tests pass unchanged. The validator
  remains independent of simulator transition/state code.
- A fixed input/seed game is byte-identical after canonical JSON serialization.
- All 120 generated full-game records are retained. No failed seed or native
  validation error is dropped.
- Independent `restart_sequence` hard failures are zero across the 120 records.
- Independent `penalty_and_manpower` hard failures are zero across the 120
  records. `NOT_ASSESSED` and `QUARANTINED` remain separately reported and do
  not count as passes.
- Event order, clocks, terminal state, goals, SOG, player totals, goalie totals,
  and shift-ledger accounting remain reconciled by the native and independent
  validators.

Failure of any criterion is reported as a failure. Do not weaken the validator,
change the sample, remove failing seeds, or adjust thresholds after seeing the
result. Correctness and legality outputs are not optimized for predictive
metrics.

### Required reporting

Report generation coverage and failures; native versus independent validation;
status counts for every check; event-level penalty/restart failures;
`NOT_ASSESSED` and `QUARANTINED` counts; fixed-seed reproducibility; per-game
runtime and total elapsed time; output hashes; and whether all six requested
transition families remain covered by source-backed or deliberately invalid
fixtures. Distinguish the 120 diagnostic draws from an independent population
sample: they are clustered within six fixed matchups and are not a season-wide
failure-rate estimate.

Do not report Brier, CRPS, winner probabilities, or other forecast performance
as evidence for this structural repair. Do not claim `full_rule_assessed`:
lineup eligibility, legal non-center faceoff locations, on-ice line changes,
goalie-pull timing, geometry-dependent calls, and other rules remain outside the
available evidence.

## Data and operations boundary

- Use the existing hash-verified NHL GameCenter PBP, box-score, and shift
  manifests. Use existing official-source fixtures; do not fetch ESPN or contact
  a provider.
- Databases remain read-only and are not needed by this historical run.
- Raw and generated full-game JSON remains outside Git.
- Run sequentially at reduced priority after checking `uptime`, `free -h`, and
  active processes. Do not start below the runner's 1.5 GiB available-memory
  floor. Recheck resource state during the run.
- Commit the preregistration before the 120-game candidate run. Commit code,
  tests, and the report locally on the isolated research branch. No push,
  production change, or Gridiron change is authorized here.
