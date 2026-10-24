# E2 successor: repairs after the gate (2026-10-24)

Base: `a442dcd7` (the E2 evidence package, accepted by the gate as a scoped completed-regulation milestone). That commit and its
branch, `feat/nfl-sequence-e2-kickoffs-2026-10-24`, are frozen. Every change here is on `feat/nfl-sequence-e2-successor-2026-10-24`,
in the worktree `/root/lp-nfl-e2-successor`. `valid_full_game` is still false on every record: the successor's unsupported-rule list
is never empty, so the flag cannot be set.

## Repairs, in order

| commit | repair | basis |
| --- | --- | --- |
| `5984b767` | The kick spot is separated from the snap position. A field goal's published yardline_100 is the snap; the holder stands 7 yards behind it, so the kick is taken from snap + 7 (capped at 99). The 20 exception applies to the kick spot. | The holder offset (`HOLDER_OFFSET = 7`) is an **authored** placement value, not a measured one. The rules matrix carries its own copy and checks the offset itself. The make-rate cells stay keyed on the published snap position. |
| `44375397` | A timeout is a transition. The count before a play is written to `state_before`, the charge only to `state_after`. A timeout is a clock stop: the clock moves by the sampled runoff alone, and the next play restarts from the clock and counts the flagged play leaves. | Engine code. The pre-repair engine fails the count test (0 != 1) and the restart test (1 != 2). The clock guard passes on both, as it should. |
| `21b153f2` | A made field goal takes the kick itself, at most five seconds of clock. The state, the drive's end clock and the game clock follow the charge, so the kickoff starts from the charged clock. A missed kick keeps its observed runoff. | **Measured**: on the published nfl_pbp, 2022-2025, the clock from a made kick's snap to the next snap has a median of 4 s and is at most 5 s on 98.9% of 3,682 made kicks. The cap is `KICK_DURATION_SECONDS = 5`. The matrix has a row for it. |
| `2a351a84` | The legality fixture split is pinned by a test, and the corrections to the frozen evidence are recorded. | The evidence says 14 tests: 2 positive and 12 negative fixtures. No passage says "fourteen negative fixtures". The split is now asserted (`FixtureSplit`). The note is `docs/evidence/e2/CORRECTIONS-2026-10-24.md`. |
| `c80d2816` | A regulation-only candidate does not sample overtime rows. The reference loader defaults to regulation-only and records the exclusions. | **Measured**: the dev table holds 1,214 overtime rows in 2022-2025, including 470 passes and 348 runs. The pool keys on down, distance and field, not quarter, so it took them. Removing them takes 862 entries out of the pool (138,235 to 137,373). `regulation_only=False` reproduces the accepted E2 pool. The published kick table is not filtered: its rates include the overtime kicks (46 overtime field-goal rows and 4 overtime extra-point rows, by play type), which is disclosed. |
| `108a1afe` | The three clock models on the same plays: A (current sampled runoff), B (PBP-conditional), C (tracking-informed). | See `docs/evidence/e3/THREE-MODEL-CLOCK-COMPARISON-2026-10-24.md`. |

## Tests

- Engine suite: **94 tests, OK** (`python3 -m unittest discover -s scripts/nfl_sequence -p 'test_*.py'`).
- Evidence suite: **15 tests, OK** (`python3 -m unittest discover -s scripts/nfl_sequence/evidence_e2 -p 'test_*.py'`).
- New tests: kick spot and the 20 exception on the kick spot (snap 14 gives 79, not 80), an engine test where snap and kick spot differ,
  and a matrix negative fixture; timeout count written once in `state_after`, clock stop and restart, and a flagged versus an unflagged game
  that differ only in counts; made-kick charge (5 s for a long runoff, 3 s for a short one), the kickoff starting from the charged clock,
  a missed kick unchanged, and a matrix negative fixture; the regulation-only pool; the fixture split.

## Repaired engine, 300 seeds (`docs/evidence/e2/successor-legality-survey-300*`)

| | successor | accepted E2 (`a442dcd7`) |
| --- | ---: | ---: |
| complete regulation | **288** | 293 |
| blocked | **12** (11 overtime tie, 1 thin 50+ field-goal cell) | 7 (5 overtime, 2 thin cell) |
| independent legality checker: legal | **300 of 300** | 300 of 300 |
| matrix FAIL rows | **0** | 0 |
| blocked seeds marked complete | 0 | 0 |

Against the frozen survey, 19 seeds differ: 11 complete games become overtime ties; 5 overtime-blocked games finish in regulation; 2
thin-cell blocks clear; 1 complete game becomes a thin-cell block. These are path effects. The made-kick clock charge and the timeout
state change the game clock on those plays, and the regulation-only pool changes which outcomes are sampled. The overtime tie rate is the
one to watch: the successor ties more regulation games.

## What this does not repair

- **Kickoffs still clamp at zero.** `_kick` in the engine draws a kickoff runoff and clamps it. The clock is not fully event-driven.
- **Timeouts, penalties and the two-minute warning are still unmodelled** (the guards say so). The timeout transition is a state fix,
  not a stoppage model.
- **The missed-kick spot rule (Rule 11-4-2) is cited from the review and is not in the repository.** The holder offset is authored.
- **The kick table includes overtime kicks.** Filtering it would change the published rates; it is disclosed, not changed.
- **Clock generation.** The three-model comparison shows the B and C models are closest on the clock, and no model is calibrated at the
  quarter level: the mean absolute error per quarter is 56 to 57 s, with the median near zero. Per the review, clock generation needs
  redesign into an event-driven subsystem. This branch does not build that subsystem.

## Gate

No promotion. This branch does not change `valid_full_game`, the frozen fixtures, the frozen survey, or any production prediction. The
successor is for re-review.
