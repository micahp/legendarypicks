# Model D out-of-bounds clock restart audit

Date: 2026-10-30

Branch: `research/event-driven-clock-2026-10-30`, based on `research/lp-event-integration` at `704661c0`.

## Rule applied

For a runner out of bounds, the game clock restarts on the next snap after the two-minute warning in Q2 and inside the final five minutes in Q4. At other regulation times, it restarts on the referee's ready signal. A change of possession takes precedence. The classifier also preserves the existing precedence for scores, kicks, turnovers, and incomplete passes.

This threshold is documented in the local [NFL 2026 game-state rules contract](../../rules/NFL-2026-GAME-STATE-RULES.md) and checked against [NFL Rule 4-3-2(a)](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook) and the [official 2022 rulebook](https://operations.nfl.com/media/5kvgzyss/2022-nfl-rulebook-final.pdf). The official rulebooks control if the engineering summary differs.

## Pinned-data audit

The audit reads regular-season weeks 1–18 for 2022–2025 from the four raw nflverse parquet files. Each parquet SHA-256 is checked against the pinned play-extras manifest before any rows are counted. The generated play-extras CSV and its priority-labeled category totals are also checked against that manifest.

| Measure | Rows |
| --- | ---: |
| Out-of-bounds rows | 16,269 |
| Out-of-bounds rows also marked timeout | 70 |
| Q4 out-of-bounds rows at 2:01–4:59 | 791 |
| Those rows classified as `oob_snap` | 731 |

For the remaining 60 rows in that Q4 window, event precedence assigned 37 kick, 20 turnover, two incomplete-pass, and one score classifications. These classes already represent the relevant clock consequence or take precedence over the runner OOB rule. There are 105 OOB rows outside the modelled regulation state, excluded from Model D's regulation classification.

## Limits

This is a rule-classification and input-provenance audit. It does not validate Model D's fitted runoff distributions, timeout behavior, penalties, overtime, or full-game clock accuracy. Seasons 2022–2025 are the audited training window; no 2026 holdout data was read.

## Reproduction and artifacts

Run from this worktree:

```sh
/root/.venvs/nfl-parquet/bin/python scripts/nfl_sequence/audit_oob_clock_restart.py \
  --out docs/evidence/e3/oob-clock-restart-audit-2026-10-30.json
```

The machine-readable report records SHA-256 values for all four parquet files, the play-extras CSV and manifest, the local rules reference, `clock_d.py`, and the audit script. It also records the yearly row counts and the manifest consistency checks.
