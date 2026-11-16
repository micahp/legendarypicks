# Safety free kicks from the observed table: evidence (2026-10-26)

## What changed

A safety with time left on the clock was blocked as not modelled. It is now a free kick drawn from the observed 2022–2025 safety-kick table (`docs/fixtures/e2/safety_kick_outcomes_2022_2025.csv`, built by `scripts/nfl_sequence/build_safety_kick_outcomes.py`). The table holds 57 regular-season safeties: 46 usable kicks with the receiving team's spot and clock runoff, and 11 refusals. The ordinary kickoff pool is never used for a safety. A safety at a Q1/Q3 end with no clock left still blocks.

## Control: the code change alone is neutral

Run with `--no-safety-table` (table off, new code). All 300 pinned seeds reproduce the stored baseline `docs/evidence/e2-try-policy/validity-300-unconditional.csv` exactly. `reference_sha256` is `0e4fb1b3…` and `run_snapshot_sha256` is `44a19b2d…`, both identical to the baseline. Valid 245, blocked 42, tied 13.

## Treatment: the table is a new input, so the seeds are re-keyed

Run with the table on. Valid 261, blocked 24, tied 15. `reference_sha256` is `2aee728e…` and `run_snapshot_sha256` is `f61b780c…`. The model seed is `sha256(seed:snapshot_digest)`, so adding the table changes every seed's draws. All 300 rows differ from the baseline.

**This is not a paired comparison.** The seed-by-seed diff cannot show which seeds the correction affected. Coverage is compared as independent Monte Carlo.

| | valid / 300 | 95% Wilson |
|---|---|---|
| baseline (table absent) | 245 | 0.769–0.856 |
| treatment (table on) | 261 | 0.827–0.903 |

The difference is 16 games (5.3 percentage points). Intervals overlap at the edges and this is one 300-seed cohort, so it is a coverage gain, not a precise effect size.

## Where the 23 safety-blocked seeds went

Of the 23 baseline seeds blocked on a safety, 21 are now valid and 2 are blocked on other rules (one blocked-kick recovery outside the field, one unclassified blocked field goal). No treatment run has a safety blocker.

Other blockers moved because the draws were re-keyed: overtime ties 13 → 15, unclassified blocked field goals 13 → 15, and one new blocked punt (guarded penalty, fumble or review).

## Limits

- The pool is thin: 46 kicks, all coded `kickoff` in the source. Receiving spot median 65, runoff median 6 seconds, sampled uniformly.
- The window is 2022–2025 only, the engine's regulation window. Earlier seasons are not in the raw files used here.
- A safety at a Q1/Q3 end with no clock left still blocks. No such case arose in this cohort.
- The pool is not checked against published safety-kick statistics, and the 2026 touchback rule was not checked against each historical regime.
- Overtime and blocked-kick classification remain open.

## Pre-existing failures, not from this branch

On the experiment HEAD (`3424f1a4`), `evidence_e2/test_shared_v1_residuals.py::Guards::test_valid_full_game_cannot_be_claimed_while_a_rule_is_unsupported` and `evidence_e2/test_traceability.py::Resolution::test_every_transition_test_and_citation_resolves` already fail. They fail on this branch with the same messages.

## Files

- `validity-300-unconditional-control.{csv,json}`: table off (`--no-safety-table`)
- `validity-300-unconditional-treatment.{csv,json}`: table on
- `compare-control-vs-baseline.txt`, `compare-treatment-vs-baseline.txt`: `scripts/nfl_sequence/compare_safety_arm.py` output
