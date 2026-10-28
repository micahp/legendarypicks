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

k = 20 is the lowest. By category (k = 20 team prior, league prior in brackets, category TVD):

| Category | Team | League | Category | Team | League |
|---|---|---|---|---|---|
| A target role | 0.0716 | 0.0831 | G play action | 0.0423 | 0.0465 |
| B carrier role | 0.0451 | 0.0550 | H motion | 0.0408 | 0.0582 |
| C run gap | 0.0769 | 0.0945 | I blitz | 0.0368 | 0.0388 |
| D pass depth | 0.0244 | 0.0295 | J QB alignment | 0.0596 | 0.0998 |
| E pass location | 0.0465 | 0.0462 | K ball hash | 0.0375 | 0.0372 |
| F shotgun | 0.0476 | 0.0795 | L backfield count | 0.0443 | 0.0643 |
| | | | M box count | 0.0865 | 0.0844 |
| | | | N pass rushers | 0.0301 | 0.0394 |

The team prior is better on 11 of 14 categories. The largest gains are J (QB alignment), F (shotgun), L (backfield count)
and H (motion). It is slightly worse on E (pass location), K (ball hash) and M (box count), by 0.0003 to 0.0021.

Frozen prior: refit on all of 2025, Weeks 1 to 18, with k = 20.
SHA-256 of the frozen prior tables: `ed70a4af286fc5f08fdc85f984bd4897fba0c0e9317c731be8fd914e36416f5c`.
2025 universe: 32,813 scrimmage plays (regular season, pass or run, with down, distance and yard line).

## What is not in this run

- No Madden ratings. No NGS, which was withdrawn from the spec (section 11), and no tracking.
- No 2026 data has been used to choose anything. The 2026 stage loads only Weeks 1 to 7 and refuses to run twice.

## The 2026 test

Run once, on 2026 Weeks 1 to 7, with the frozen prior and k = 20. Result recorded below.
