# E2 successor evidence package (2026-10-24)

Branch `feat/nfl-sequence-e2-successor-2026-10-24`. Engine commit `75962ffe5fca9eddee9b49ff377031c5075e2c16` (the record's
`model_version`). Frozen `a442dcd7` is untouched. `valid_full_game` is false for every record.

## Survey outcome, 300 seeds (final engine)

| measure | count |
|---|---:|
| seeds | 300 |
| validate_game passed | 300 |
| reached regulation end under the simulation | 288 |
| regulation end, guarded by an unmodelled transition (status `regulation_end_guarded`) | 288 |
| complete game (`complete_game`) | 0 |
| legal complete game (independent checker) | 0 |
| legal under the modelled rules (checker) | 300 |
| blocked (each with a named reason) | 12 |
| blocked, guarded or tied described as complete | 0 |
| matrix FAIL rows | 0 |
| try findings | 0 |
| matches the frozen survey (`a442dcd7`, unmodified) on status, blocker, regulation end and FAIL rows | 281 of 300 |

Blocked seeds: 11 by `overtime_not_modelled` (scope reason `overtime`) and 1 by `thin_kick_cell:field_goal:50+` (scope reason
`rare kick outcome`). The same 12 seeds were blocked in the previous survey at `5af1746d`, and no seed changed status or FAIL
count with the kickoff-clock change. Per-seed table: `SURVEY-300-SUCCESSOR-2026-10-24.md`.

## Parts

| part | file | what it shows |
|---|---|---|
| provenance | `PROVENANCE-2026-10-24.json` | fix and engine SHAs, model and rules versions, contract hash `ae7b8a30…`, engine and evidence file hashes, output hashes |
| version stamps | `VERSION-DEFINITIONS-2026-10-24.md` | `model_version` = the engine commit; `rules_version` = `7f0578bf…` (SHA-256 of the RULE_FILES producer map) |
| seed-1 record | `seed1-game-successor.json` | regenerated from the committed engine: `regulation_end_guarded`, `complete_game` false, `valid_full_game` false |
| seed-1 statistics | `seed1-stats-recomputed-successor.json` | team and player statistics recomputed from the plays, all matching the stored block |
| survey | `legality-survey-300.csv`, `legality-survey-300-summary.json`, `SURVEY-300-SUCCESSOR-2026-10-24.md` | counts above, per-seed rows, blocked reasons |
| unmodelled transitions (blocker 5) | `UNMODELLED-TRANSITIONS-300-2026-10-24.md`, `unmodelled-transitions-300.json` | every type, its count across the 300 seeds, its printed rule heading, its treatment, and 15 negative fixtures with test names |
| shared-v1 residuals (blocker 7) | `shared-v1-residuals.json` | nine residuals, each traced to its source, with the guard test that fires for it |
| try rates (blocker 1) | `try-rates-publisher-vs-success.json` | extra-point and two-point rates from the publisher fields, against the success flag on the same rows |
| missed field goal (blocker 2) | `RULE-TRACEABILITY-MATRIX-2026-10-24.md` row R11 | Rule 11-4-2 (a) and (b) with boundary tests at kick spots 19, 20, 21 and 99; the touch exception is guarded |
| overtime (blocker 6) | `overtime-rows-evaluation.json` | 1,214 overtime rows in the window, 0 in the regulation-only pools, 862 entries in the unrestricted E1 pool, reported separately |
| toss (blocker 4) | `toss-sampling-300.json` | winner A 153 / B 147, choice receive 155 / defer 145; both sides sampled |
| rule traceability | `RULE-TRACEABILITY-MATRIX-2026-10-24.md` / `.json` | 23 rules mapped to transitions and tests; article text read for the verified rows; gaps pinned (R10, R20) |
| kick distance | `kick-distance-offset.json` | the publisher offset on 4,325 field-goal rows, and the ruling that the engine keeps +17 |
| source semantics | `SOURCE-SEMANTICS-AUDIT-2026-10-24.md` | publisher fields, penalty and two-minute scope, overtime pool, toss, kick table, timeouts |
| Gridiron integration | `e2-game-envelope-seed1-successor.json`, `e2-game-seed1-successor.v1.json`, `gridiron-adapter-proof-de64ae12.json`, `gridiron-adapter-proof-13b18faa.json` | the viewer refuses this guarded seed, as it should; structural validation accepts it with 0 findings, 6 record-level and 6 v1 violations |
| E3 clock baseline | `../e3/CLOCK-BASELINE-B-2026-10-24.md`, `../e3/clock-decomposition-v1/MANIFEST.json` | model B adopted; weeks 6-9 burned, with the holdout timeline |
| E3 tracking coverage, step 1 | `../e3/TRACKING-COVERAGE-STEP1-2026-10-24.md`, `../e3/tracking-coverage-v1/` | 16,124 tracked plays; identifier match 16,124; verified 15,768; complete drives 106 (every play) and 2,059 (scrimmage); complete games 0 and 1 |

## Blocker status

- **Blocker 1 (try records and rates):** closed. Records carry the publisher field and no success flag. The printed rates use
  only publisher fields. In this window the success flag agrees with the publisher on every good, failed and two-point try; it
  differs only on blocked extra points, which it counts as misses.
- **Blocker 2 (missed field goal, Rule 11-4-2):** closed for the award. The spot is the spot of the kick, or the receivers' own 20
  when the kick spot is inside it, with boundary tests. The receivers' touch exception (1) and (2) is not modelled and is guarded:
  `missed_field_goal_return` makes the game guarded, so it is never a complete game.
- **Blocker 3:** not located in the record this package was built from. No status is claimed for it.
- **Blocker 4 (toss sampling):** closed. Both winners and both choices are sampled across the 300 seeds.
- **Blocker 5 (penalties and two-minute warning):** guarded, not modelled. A penalty blocks the game. A two-minute crossing makes the
  game guarded. Each guard has negative fixtures, listed in `UNMODELLED-TRANSITIONS-300-2026-10-24.md`.
- **Blocker 6 (overtime and rare kick outcomes):** scoped out explicitly. 11 seeds are blocked as overtime and 1 as a rare kick
  outcome. The adversarial overtime test (R07) refuses a tied game described as complete.
- **Blocker 7 (shared v1):** documented, not fixed. Nine residuals remain. Seven come from the LP contract check and two from
  Gridiron's audit only. Each has a guard test. None is cleared by an invented value, and the contract is unchanged.
  `pregame_full_game` conformance is not claimed.

## Kickoff clock

A kickoff that fits in the clock is charged its runoff in full. One that does not fit expires the quarter: the clock is set to
zero explicitly and the overrun is recorded. Nothing clamps a clock, and validate_game refuses a negative clock.

The made-field-goal cap of five seconds is not applied to kickoffs. It is printed for field goals only (Rule 11-4-2 note 5). Rule
4 Section 3 Article 1 starts the clock after a free kick only when the ball is legally touched, so the observed kickoff runoff
includes time that no source records. Applying the cap would invent a value.

## Tests

- Engine suite (`scripts/nfl_sequence`): 127 OK, including the three fixture tests.
- Evidence suite (`scripts/nfl_sequence/evidence_e2`): 50 OK.

## Known limits

Two-minute warning and penalties are guarded, not modelled. Timeout stoppage time is inside the observed runoff. The receivers'
touch exception to a missed field goal is not modelled. Overtime is excluded from the sampling pool, and a tied game is blocked.
`duration_seconds` is null for all 141 plays of seed 1. The published kick table includes overtime kicks.
