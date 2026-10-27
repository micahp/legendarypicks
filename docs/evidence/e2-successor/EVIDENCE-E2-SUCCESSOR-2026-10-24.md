# E2 successor evidence package (2026-10-24)

Branch `feat/nfl-sequence-e2-successor-2026-10-24`. Engine base commit `dfef3e8e40ab9702c1f021ff726e3959d6f9d63b` (the record's
`model_version`). The dirty producer snapshot is SHA-256 `79a65db640e587798f2a067853a3ba8f723aadfbb10e3021cddb3c92ec08c117`;
its `rules_version` is `5ea4eecd2fa94e24c4efa857c35f2aa20724e37b85e5adb49b69a84de875fb7a`. Frozen `a442dcd7` is untouched.
`valid_full_game` is false for every record.

## Survey outcome, 300 seeds (final engine)

| measure | count |
|---|---:|
| seeds | 300 |
| validate_game passed | 300 |
| reached regulation end under the simulation | 288 |
| regulation end, guarded by an unmodelled transition (status `regulation_end_guarded`) | 288 |
| unguarded complete regulation records | 0 |
| complete game (`complete_game`) | 0 |
| legal complete game (independent checker) | 0 |
| shared-v1 `valid_full_game=true` | 0 |
| legal under the modelled rules (checker) | 300 |
| blocked (each with a named reason) | 12 |
| blocked, guarded or tied described as complete | 0 |
| matrix FAIL rows | 0 |
| try findings | 0 |
| matches the frozen survey (`a442dcd7`, unmodified) on status, blocker, regulation end and FAIL rows | 281 of 300 |

Blocked seeds: 11 by `overtime_not_modelled` (scope reason `overtime`) and 1 by `thin_kick_cell:field_goal:50+` (scope reason
`rare kick outcome`). Compared with the frozen survey, 19 seeds differ. The controlled comparison attributes 6 to the
regulation-only versus all-quarter pool. In 11 more, the all-quarter run matches the frozen status, blocker and regulation-end
outcome, but the current two-minute guard correctly keeps `complete_game=false`; 2 still differ in status or blocker with the
all-quarter pool. See
`MISMATCH-300-SUCCESSOR-2026-10-24.md` for every changed seed. The 300 records have 599 two-minute-warning markers (Q2: 300,
Q4: 299); clock running/stopped state and restart remain guarded. Per-seed table: `SURVEY-300-SUCCESSOR-2026-10-24.md`.

## Parts

| part | file | what it shows |
|---|---|---|
| provenance | `PROVENANCE-2026-10-24.json` | fix and engine SHAs, model and rules versions, contract hash `ae7b8a30…`, engine and evidence file hashes, output hashes |
| version stamps | `VERSION-DEFINITIONS-2026-10-24.md` | `model_version` = the engine base commit; `rules_version` = `5ea4eecd…` (SHA-256 of the RULE_FILES producer map) |
| seed-1 record | `seed1-game-successor.json` | regenerated from the committed engine: `regulation_end_guarded`, `complete_game` false, `valid_full_game` false |
| seed-1 statistics | `seed1-stats-recomputed-successor.json` | team and player statistics recomputed from the plays, all matching the stored block |
| gate review request | `GATE-REVIEW-REQUEST-E2-SUCCESSOR.md` | the request for the gate: phase, SHAs, counts, artifacts, open defects, the shared-v1 mapping, and the three asks |
| drive index (blocker 3) | `drive_index_check.py`, `test_drive_index_corpus.py`, survey summary | 0 drives and 0 play states wrong on 300 seeds; a corrupted index fails the assertion |
| survey | `legality-survey-300.csv`, `legality-survey-300-summary.json`, `SURVEY-300-SUCCESSOR-2026-10-24.md` | counts above, per-seed rows, blocked reasons |
| unmodelled transitions (blocker 5) | `UNMODELLED-TRANSITIONS-300-2026-10-24.md`, `unmodelled-transitions-300.json` | every type, its count across the 300 seeds, its printed rule heading, its treatment, and 17 negative fixtures with test names; 599 warning markers, 77 timeout events, 239 missed-field-goal cases |
| frozen-survey comparison | `MISMATCH-300-SUCCESSOR-2026-10-24.md`, `.json` | 19 changed seeds; 6 pool differences, 11 current two-minute completion guards, 2 status/blocker differences with all-quarter pool |
| shared-v1 residuals (blocker 7) | `shared-v1-residuals.json` | nine residuals, each traced to its source, with the guard test that fires for it |
| try rates (blocker 1) | `try-rates-publisher-vs-success.json` | extra-point and two-point rates from the publisher fields, against the success flag on the same rows |
| missed field goal (blocker 2) | `RULE-TRACEABILITY-MATRIX-2026-10-24.md` row R11 | Rule 11-4-2 (a) and (b) with boundary tests at kick spots 19, 20, 21 and 99; the touch exception is guarded |
| overtime (blocker 6) | `overtime-rows-evaluation.json` | 1,214 overtime rows in the window, 0 in the regulation-only pools, 862 entries in the unrestricted E1 pool, reported separately |
| toss (blocker 4) | `toss-sampling-300.json` | winner A 153 / B 147, choice receive 155 / defer 145; both sides sampled |
| rule traceability | `RULE-TRACEABILITY-MATRIX-2026-10-24.md` / `.json` | 25 rules mapped to transitions and tests; article text read for the verified rows; gaps pinned (R10, R20); R15 is partial and `clock_start_stop` remains unsupported |
| kick distance | `kick-distance-offset.json` | the publisher offset on 4,325 field-goal rows, and the ruling that the engine keeps +17 |
| source semantics | `SOURCE-SEMANTICS-AUDIT-2026-10-24.md` | publisher fields, penalty and two-minute scope, overtime pool, toss, kick table, timeouts |
| Gridiron integration | seed-1 envelope and shared-v1 projection, two pinned older heads, `origin/main` at `72c7a747`; `GRIDIRON-POPULATION-300-2026-10-24.json` | each head accepted all 300 records; 299 passed structural validation, seed 176 had findings, and 38 seeds had football-state findings; see population report |
| LP rules contract | `docs/rules/NFL-2026-GAME-STATE-RULES.md` on `origin/dev` | pinned by Git blob and SHA-256 in provenance; the full-game claim requires pregame identity/as-of/roster evidence and fully represented applicable transitions |
| E3 clock baseline | `../e3/CLOCK-BASELINE-B-2026-10-24.md`, `../e3/clock-decomposition-v1/MANIFEST.json` | model B adopted; weeks 6-9 burned, with the holdout timeline |
| E3 tracking coverage, step 1 | `../e3/TRACKING-COVERAGE-STEP1-2026-10-24.md`, `../e3/tracking-coverage-v1/` | 16,124 tracked plays; identifier match 16,124; verified 15,768; complete drives 106 (every play) and 2,059 (scrimmage); complete games 0 and 1 |

## Blocker status

- **Blocker 1 (try records and rates):** closed. Records carry the publisher field and no success flag. The printed rates use
  only publisher fields. In this window the success flag agrees with the publisher on every good, failed and two-point try; it
  differs only on blocked extra points, which it counts as misses.
- **Blocker 2 (missed field goal, Rule 11-4-2):** closed for the award. The spot is the spot of the kick, or the receivers' own 20
  when the kick spot is inside it, with boundary tests. The receivers' touch exception (1) and (2) is not modelled and is guarded:
  `missed_field_goal_return` makes the game guarded, so it is never a complete game.
- **Blocker 3 (drive_index):** closed on the successor corpus. The 23 known findings are the drives 2 to 24 of the archived
  record `5fcaa6bc` (280 play states). The assertion on 300 seeds finds 0 drives and 0 states wrong, of 87,740 states checked.
  The archived fixture still carries the findings by design. Raw E1 output writes `drive_index` 1 on every play; the game engine
  overwrites it. See `drive-index` in the gate review request.
- **Blocker 4 (toss sampling):** closed. Both winners and both choices are sampled across the 300 seeds.
- **Blocker 5 (clock lifecycle and penalties):** two-minute crossings are marked and independently checked at the actual
  post-down clock (599 markers across 300 records); running/stopped state and explicit restart transitions remain guarded as `clock_start_stop`. Penalties are
  unsupported and a sampled penalty blocks the game. Tests are listed in `UNMODELLED-TRANSITIONS-300-2026-10-24.md`.
- **Blocker 6 (overtime and rare kick outcomes):** scoped out explicitly. 11 seeds are blocked as overtime and 1 as a rare kick
  outcome. The adversarial overtime test (R07) refuses a tied game described as complete.
- **Blocker 7 (shared v1):** documented, not fixed. Nine residuals remain. Seven come from the LP contract check and two from
  Gridiron's audit only. Each has a guard test. None is cleared by an invented value, and the contract is unchanged.
  `pregame_full_game` conformance is not claimed.

## Documented deviations

- **Kickoff clock (uncapped).** A kickoff is charged its observed runoff, with no five-second cap. The cap is printed for field
  goals only (Rule 11-4-2 note 5). Rule 4 Section 3 Article 1 starts the clock after a free kick only when the ball is legally
  touched, so the observed runoff includes stopped time that no source records. Keeping the uncapped runoff overstates kickoff
  time. This is recorded here and in the gate review request. It is not fitted to the data.

## Kickoff clock

A kickoff that fits in the clock is charged its runoff in full. One that does not fit expires the quarter: the clock is set to
zero explicitly and the overrun is recorded. Nothing clamps a clock, and validate_game refuses a negative clock.

The made-field-goal cap of five seconds is not applied to kickoffs. It is printed for field goals only (Rule 11-4-2 note 5). Rule
4 Section 3 Article 1 starts the clock after a free kick only when the ball is legally touched, so the observed kickoff runoff
includes time that no source records. Applying the cap would invent a value.

## Tests

- Engine suite (`scripts/nfl_sequence`): 148 passed.
- Evidence suite (`scripts/nfl_sequence/evidence_e2`): 60 passed.

## Known limits

The two-minute crossing marker is modelled, but the full clock lifecycle is guarded. Penalties are unsupported; timeout stoppage time is inside the observed runoff. The receivers'
touch exception to a missed field goal is not modelled. Overtime is excluded from the sampling pool, and a tied game is blocked.
`duration_seconds` is null for all 141 plays of seed 1. The published kick table includes overtime kicks. The Claude rules-fix branch
`fix/week7-game-state-rules` is at `c32e453d` and is not merged: live `origin/main` remains `72c7a747`, and no PR exists. That branch
does not contain the LP E2 adapter, so it is excluded from the 300-record adapter audit. At each audited head, seed 176 is accepted
but reports kickoff 6 / drive 10 restart-possession validation findings; the independent football-state audit reports restart and
scoring-kick findings on 38 seeds. Adapter acceptance is not legal-game certification.
