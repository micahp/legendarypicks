# 2026 source reconciliation (D1, read-only)

Opened under D1 of `docs/research/PLAYCALL-DECISIONS-2026-11-02.md`, after freeze commit `9bbb2af6` and access entry 13 in
`docs/research/HOLDOUT-EXPOSURE-RECORD-2026.md`. Source files: `pbp_2026.csv.gz` (weeks 1-6) and `pbp_2026_week7.csv.gz`
(weeks 1-7, merged and de-duplicated on game_id and play_id, REG only). Nothing here is used for fitting, tuning, features,
thresholds, or arm ranking.

Definitions follow the frozen baseline (`docs/research/playcall-baseline-2022-2025/README.md`).

## Table

See `reconciliation_table.csv`. Summary:

- Reproduced: J.Williams carries per game (15.71) and Mi.Wilson targets per game (9.43, ID 00-0038559).
- Not reproduced: DAL run plays per game (computed 23.00; cited 22.86, which is 160/7). J.Williams carry share (68.3%
  computed; cited 68.7%, which matches a 160-run denominator). Mi.Wilson target share (computed 24.3% on receiver-recorded
  passes; cited 23.3%, which no tested denominator reproduces).
- Population mismatch: the audit's 2025 holdout reference uses 16 games. Our 2025 baseline uses 17 REG games. They must not
  be compared as the same population.

## Open items from this reconciliation

- The one-play difference in DAL runs: not identified. Candidates to check against the audit's own script: scramble
  handling and whether any run play is excluded as a penalty or no-play. Requires the audit's script, which is not in the
  audit folder.
- The Wilson target-share denominator: not identified. The cited 23.3% implies about 283 targets for ARI.
- Name mapping: "Michael Wilson" in the audit is Mi.Wilson (ID 00-0038559). Confirm against the audit's own player key.
