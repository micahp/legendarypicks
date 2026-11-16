# E2 successor: gate review request

**Phase:** E2 successor, regulation-only sequence engine. Gate review of the scoped research milestone.

**Engine commit:** `dfef3e8e40ab9702c1f021ff726e3959d6f9d63b`. **Previous evidence head:** `04a3752d95e62a0364cd8c80d5f003f76fb03beb`.
The commit that adds this file is not written in it: a commit cannot record its own hash. Read it with `git log --diff-filter=A --format=%H -- docs/evidence/e2-successor/GATE-REVIEW-REQUEST-E2-SUCCESSOR.md`.

**Branch:** `feat/nfl-sequence-e2-successor-2026-10-24`. Frozen E2 reference `a442dcd7` is untouched.
`valid_full_game` is false for every record. The exact source tree is pinned as `79a65db640e587798f2a067853a3ba8f723aadfbb10e3021cddb3c92ec08c117`; its producer files are dirty.

## Scope

Regulation only. The sampling pool excludes overtime (1,214 rows in 2022-2025). Two-minute-warning crossings are marked at
the actual post-down clock, as Rule 3 Section 41 specifies, but clock running/stopped state and explicit restart transitions
remain unsupported under clock_start_stop. A sampled penalty blocks
the game. Timeouts and missed-field-goal returns are guarded, and
onside kicks and the exception coin toss are refused. No guarded or blocked game is described as a complete game. The claim
is consistency under the modelled rules, not a complete legal NFL game.

## Tests

- Engine suite (`scripts/nfl_sequence`): 148 run, 0 failures, 0 errors. OK.
- Evidence suite (`scripts/nfl_sequence/evidence_e2`): 60 run, 0 failures, 0 errors. OK.

## 300-seed survey (engine dfef3e8e)

- Validated by validate_game: 300 of 300.
- Reached regulation end under the simulation: 288, all guarded (`regulation_end_guarded`).
- Complete model-scoped regulation candidates: 0. Independent model-scoped candidates: 0.
- `valid_full_game=true`: 0. Every record is `legal_game_state_first_piece`; none is a pregame full-game contract payload.
- Legal under the modelled rules: 300 of 300.
- Blocked: 12, each with a named reason (11 overtime, 1 rare kick outcome).
- Blocked, guarded or tied described as complete: 0, 0.
- Matrix FAIL rows: 0. Try findings: 0.
- Drive index (blocker 3): 0 drives and 0 play states carry a wrong index, of 87740 play states checked on 300 seeds.
- Matches the frozen survey on 281 of 300 seeds.

## Blocker status

| blocker | status | where |
|---|---|---|
| 1 try rates from publisher fields | closed | `try-rates-publisher-vs-success.json`, `measure_kick_outcomes.py` |
| 2 missed field goal, Rule 11-4-2 | award closed; touch exception guarded | matrix R11, `MissedFieldGoalBoundaries` |
| 3 drive_index | closed on the successor corpus; the archived fixture still carries the 23 findings by design | `drive_index_check.py`, `test_drive_index_corpus.py`, survey summary |
| 4 toss sampling | closed | `toss-sampling-300.json` |
| 5 penalties | blocked, not modelled; a sampled penalty blocks the game | `UNMODELLED-TRANSITIONS-300-2026-10-24.md` |
| 5 clock start/stop and two-minute warning | crossing marker checked; explicit stopped/running state and restart transitions guarded | matrix R15, `TwoMinuteWarning` |
| 5 timeouts | guarded; each stop is explicit (`timeout_stop`) and validated | matrix R14, `TimeoutStop` |
| 6 overtime and rare kick outcomes | scoped out; never complete | survey scope counts, R07, R21 |
| 7 shared-v1 residuals | documented, nine, each guarded; not conformant | `shared-v1-residuals.json`, mapping below |

## Shared-v1 mapping, reviewer ten to our nine

We do not have the reviewer's list of ten. It is not in the repository, and the handoff (`HANDOFF-E2-REVIEW-2026-10-24.md` section 3) says it was never located. The mapping below uses the three sources that can be reproduced: the LP check, Gridiron's record-level audit, and Gridiron's v1 document audit. Each item the three report is shown, with the one of our nine it collapses to. We ask the reviewer for the list of ten, so that each item can be matched line by line.

| our residual | LP check id | Gridiron text | guard test |
|---|---|---|---|
| `V-duration-seconds` | V-duration-seconds | None | `test_shared_v1_residuals.Guards.test_duration_guard_fires` |
| `V-mode` | V-mode | Gridiron: "mode is not pregame_full_game" | `test_shared_v1_residuals.Guards.test_mode_guard_fires` |
| `V-teams-unresolved` | - | Gridiron: "missing real home/away team identities" | `test_shared_v1_residuals.Guards.test_teams_guard_fires` |
| `V-unresolved-as_of_utc` | V-unresolved-as_of_utc | Gridiron: "missing or invalid top-level as_of_utc before scheduled_kickoff_utc" | `test_shared_v1_residuals.Guards.test_as_of_guard_fires` |
| `V-unresolved-game_id` | V-unresolved-game_id | Gridiron: "missing stable game_id" | `test_shared_v1_residuals.Guards.test_game_id_guard_fires` |
| `V-unresolved-roster_snapshot_id` | V-unresolved-roster_snapshot_id | Gridiron: "missing eligible roster snapshot" | `test_shared_v1_residuals.Guards.test_roster_guard_fires` |
| `V-unresolved-scheduled_kickoff_utc` | V-unresolved-scheduled_kickoff_utc | Gridiron: "missing or invalid top-level as_of_utc before scheduled_kickoff_utc" | `test_shared_v1_residuals.Guards.test_kickoff_guard_fires` |
| `V-unresolved-snapshot_hash` | V-unresolved-snapshot_hash | None | `test_shared_v1_residuals.Guards.test_snapshot_guard_fires` |
| `V-valid-full-game` | - | Gridiron: "record.valid_full_game is not true" | `test_shared_v1_residuals.Guards.test_valid_guard_fires` |

Collapsing rules, stated so the arithmetic can be checked:

1. The Gridiron time line, "missing or invalid top-level as_of_utc before scheduled_kickoff_utc", names two fields. It maps to `V-unresolved-as_of_utc` and `V-unresolved-scheduled_kickoff_utc`, which the LP check reports separately. It is one coalesced claim about two fields, counted once in our nine.
2. `missing stable game_id`, `mode is not pregame_full_game` and `missing eligible roster snapshot` each map to one LP id.
3. `missing model_version` and `missing rules_version` were in Gridiron's record-level audit before the stamp commit (`bd5f3383`). Both are closed by the stamps, so they are not among the nine.
4. `V-unresolved-snapshot_hash` and `V-duration-seconds` are reported by the LP check only.
5. `missing real home/away team identities` and `record.valid_full_game is not true` are reported by Gridiron only.

Count: the union of the three reproducible sources is 9 residuals after the stamp commit. Before the stamp commit it was eleven, and the stamps close two of them. The reviewer's ten cannot be reconciled from this repository, so it is not claimed to match. The list is requested.

## Artifacts

In `docs/evidence/e2-successor/`:

- `EVIDENCE-E2-SUCCESSOR-2026-10-24.md`
- `GRIDIRON-POPULATION-300-2026-10-24.json`
- `MISMATCH-300-SUCCESSOR-2026-10-24.json`
- `MISMATCH-300-SUCCESSOR-2026-10-24.md`
- `PROVENANCE-2026-10-24.json`
- `RULE-TRACEABILITY-MATRIX-2026-10-24.json`
- `RULE-TRACEABILITY-MATRIX-2026-10-24.md`
- `SOURCE-SEMANTICS-AUDIT-2026-10-24.md`
- `SURVEY-300-SUCCESSOR-2026-10-24.md`
- `UNMODELLED-TRANSITIONS-300-2026-10-24.md`
- `VERSION-DEFINITIONS-2026-10-24.md`
- `e2-game-envelope-seed1-successor.json`
- `e2-game-seed1-successor.v1.json`
- `gridiron-adapter-proof-13b18faa.json`
- `gridiron-adapter-proof-de64ae12.json`
- `kick-distance-offset.json`
- `legality-survey-300-summary.json`
- `legality-survey-300.csv`
- `overtime-rows-evaluation.json`
- `seed1-game-successor.json`
- `seed1-stats-recomputed-successor.json`
- `shared-v1-residuals.json`
- `toss-sampling-300.json`
- `try-rates-publisher-vs-success.json`
- `unmodelled-transitions-300.json`

In `docs/evidence/e3/`:

- `docs/evidence/e3/CLOCK-BASELINE-B-2026-10-24.md`
- `docs/evidence/e3/THREE-MODEL-CLOCK-COMPARISON-2026-10-24.md`
- `docs/evidence/e3/TRACKING-COVERAGE-STEP1-2026-10-24.md`
- `docs/evidence/e3/clock-decomposition-v1/MANIFEST.json`
- `docs/evidence/e3/clock-decomposition-v1/clock-baseline-B-runoffs.csv`
- `docs/evidence/e3/clock-decomposition-v1/clock-baseline-B.schema.json`
- `docs/evidence/e3/clock-decomposition-v1/clock-decomposition.csv`
- `docs/evidence/e3/clock-decomposition-v1/clock-decomposition.schema.json`
- `docs/evidence/e3/inputs/e3-clock-decomposition-2026-10-24.csv`
- `docs/evidence/e3/inputs/nflverse-2022-w1-9-flags.csv`
- `docs/evidence/e3/three-model-clock-comparison-2026-10-24.json`
- `docs/evidence/e3/tracking-coverage-v1/e3-tracking-coverage-2026-10-24.json`
- `docs/evidence/e3/tracking-coverage-v1/e3-tracking-join-pairs-2026-10-24.csv`

## Open defects

1. **Blocker 3, the archived fixture.** `docs/fixtures/e2/regression/lp-e2-game-seed1-5fcaa6bc.json` carries the 23 drives and 280 play states. It is kept unmodified by design, and a test asserts its counts.
2. **E1 standalone output.** `e1_drive.simulate` writes `drive_index` 1 on every play. The game engine overwrites it. A consumer that reads raw E1 states must not treat them as game indices.
3. **Shared-v1 residuals.** Nine remain. Each is guarded, none is fixed, and the contract is unchanged.
4. **Clock lifecycle, penalties and timeouts.** Two-minute crossings are detected at the actual post-down clock, but explicit clock running/stopped and restart state is guarded. A penalty blocks the game. Team timeout counts are charged from observed flags; their stoppage timing remains inside the sampled runoff.
5. **Missed field goal touch exception.** Rule 11-4-2 (1) and (2) are not modelled. The table records makes and misses, not touches.
6. **Kickoff clock.** Uncapped observed runoff, a documented deviation. The five-second cap is printed for field goals only. The unsuccessful-kick clause of note 5 is unsupported (matrix R24).
7. **Overtime and rare kick outcomes.** 11 and 1 seeds blocked. Overtime is excluded from the sampling pool.
8. **Coverage gaps.** R10 (safety game-level test) and R20 (attacks_x100 direct test) are pinned gaps.
9. **Gridiron viewer.** The viewer refuses guarded records by design (`requireCompleteRegulation`). Validation-only accepts them.
10. **Rule-source labeling.** `docs/rules/NFL-2026-GAME-STATE-RULES.md` on Legendary Picks `origin/dev` is a versioned engineering contract derived from the published NFL rules, not the official rulebook. The official 2026 rulebook remains authoritative; this gate pins the LP contract separately from the rulebook citations.
11. **E3 is out of this gate.** The E3 clock baseline and tracking coverage are separate artifacts, reported separately.
12. **Reviewer's `_apply_timeouts` defect.** Not reproduced: on a flagged play `state_before` carries the pre-call count. The gap the review named was the missing explicit stop, now recorded as `timeout_stop` with the clock stop and the restart. `validate_game`, which passes on all 300 seeds, checks the count continuity and the stop record.

## The three asks

These are the decisions this request needs. The request did not list them, so they are stated here as the reviewer's asks.

1. Accept or reject the guarded status as the correct treatment of a regulation end with an unmodelled transition. Under it,
   `complete_regulation` is false for every seed, and `regulation_end_reached` carries the simulation fact.
2. Supply the reviewer's list of ten shared-v1 violations, so the mapping above can be completed line by line.
3. The kickoff clock stays uncapped as a documented deviation (Rule 4, Section 3, Article 1). Decide whether the missed field goal touch exception (Rule 11-4-2 (1) and (2)) is modelled or scoped out. It stays guarded until decided.

Rule 1 of the printed rulebook ends at Section 5. The citation "Rule 1-6-2" was given in review; it appears in this package only as a note that it was not used.

