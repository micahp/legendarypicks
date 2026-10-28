# Decision model v1: 2025 validation and frozen prior (2026-10-27)

Status: validation on 2025 only. The frozen spec is `NFL-DECISION-MODEL-SPEC-2026-10-27.md` (committed `e0ba3e59`, with
the section 11 NGS layer withdrawn). The code is `scripts/nfl_sequence/splits/decision_model.py`. This document is
committed before the one 2026 test run. The 2026 result is added below once it has been run.

## Chosen shrinkage weight

Training: 2025 regular season, Weeks 1 to 9 (16,245 plays). Validation: Weeks 10 to 18 (16,568 plays). Headline is the
mean total-variation distance over categories A to N (lower is better). Team prior against league prior, same plays.

| Prior | Headline A to N | Headline A to I |
|---|---|---|
| k = 5 | 0.0507 | 0.0496 |
| k = 20 (chosen) | 0.0493 | 0.0480 |
| k = 80 | 0.0511 | 0.0500 |
| League prior (no team) | 0.0612 | 0.0590 |

k = 20 is the lowest. The team prior beats the league prior on every category except D (pass depth) and K (hash),
where they are close. The largest gains are on A (target role), J (QB alignment), C (run gap) and M (box count).

Frozen prior: refit on all of 2025, Weeks 1 to 18, with k = 20.
SHA-256 of the frozen prior tables: `ed70a4af286fc5f08fdc85f984bd4897fba0c0e9317c731be8fd914e36416f5c`.
2025 universe: 32,813 scrimmage plays (regular season, pass or run, with down, distance and yard line).

## What is not in this run

- No Madden ratings. No NGS, which was withdrawn from the spec (section 11), and no tracking.
- No 2026 data has been used to choose anything. The 2026 stage loads only Weeks 1 to 7 and refuses to run twice.

## The 2026 test

Run once, on 2026 Weeks 1 to 7, with the frozen prior and k = 20. Result recorded below.
