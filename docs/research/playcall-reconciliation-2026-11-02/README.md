# 2026 Weeks 1-7 reconciliation (D1, read-only)

Opened under D1 of `docs/research/PLAYCALL-DECISIONS-2026-11-02.md`, after freeze commit `9bbb2af6` and access entry 13 in
`docs/research/HOLDOUT-EXPOSURE-RECORD-2026.md`. Source files: `pbp_2026.csv.gz` (weeks 1-6) merged with
`pbp_2026_week7.csv.gz` (week 7), de-duplicated on game_id and play_id, REG games only. Script: `reconcile.py`.
Nothing here is used for fitting, tuning, features, thresholds, or arm ranking.

## Result

Every figure cited in the source audit (`docs/research/ari-dal-player-tail-audit-v5-2026-10-30/REVIEW.md`) reproduces
exactly, once the audit's own flag definitions are used. The audit's definitions are in
`scripts/nfl_sequence/build_player_workload_reference.py`:

- Team rush attempts: `rush_attempt == 1` and `two_point_attempt != 1` (lines 86-88 and 363). Includes kneels and spikes.
- Team pass attempts: `pass_attempt == 1`, `sack != 1`, `two_point_attempt != 1` (lines 360-361 and 365-375).
- Targets: pass attempts with `receiver_player_id` recorded (line 770 documents the rule).
- Carries: rush attempts with `rusher_player_id` recorded.

An earlier version of this reconciliation used `play_type` instead of these flags. That is why it showed differences
(161 runs, 296 passes). Those differences are explained below and are not errors in the audit.

## Definitions used

- REG game: season_type = REG, week 1-7. 7 games for DAL and ARI. Per game: count / 7.
- Team rush attempts: rush_attempt = 1 and two_point_attempt != 1.
- Team pass attempts: pass_attempt = 1, sack != 1, two_point_attempt != 1.
- Targets: team pass attempts with receiver_player_id recorded.
- Carries: team rush attempts with rusher_player_id recorded.

## Results (see reconciliation_table.csv)

| Quantity | Definition | Value | Audit |
| --- | --- | --- | --- |
| DAL rush attempts per game | rush attempts / 7 | 160 / 7 = 22.86 | 22.86 (reproduced) |
| J.Williams carries per game | his carries / 7 | 110 / 7 = 15.71 | 15.71 (reproduced) |
| J.Williams carry share | 110 / 160 | 68.75%, shown as 68.7% | 68.7% (reproduced) |
| Mi.Wilson targets per game (ID 00-0038559) | his targets / 7 | 66 / 7 = 9.43 | 9.43 (reproduced) |
| Mi.Wilson target share | 66 / 283 pass attempts | 23.3% | 23.3% (reproduced) |

## Gaps between definitions (explained, not errors)

- Play-type definition of DAL runs gives 161, not 160. The extra play is a two-point conversion rush (week 7, play 3083),
  which the audit excludes.
- Pass-attempt flag gives 298 for ARI, not 296. Two QB spikes (week 3, play 4641; week 5, play 2460) are flagged
  `pass_attempt = 1`. The audit's denominator keeps them, so 283 includes 2 spikes. Excluding them gives 66 / 281 = 23.5%.

## Alternative denominators, for comparison only

- Target share with sacks included (pass_attempt = 1, not two-point): 66 / 298 = 22.1%.
- Target share over pass plays by play_type with sacks included: 66 / 296 = 22.3%. This is the value written in the
  earlier draft of this reconciliation.
- Target share over receiver-recorded pass plays (the frozen baseline convention): 66 / 272 = 24.3%.

The audit's 23.3% uses the builder's definition with sacks excluded. The alternatives are listed so that the choice is
visible, not so that one of them replaces the audit's definition.

## Population mismatch (not compared)

The audit's 2025 holdout reference (J.Williams 15.75 carries per game) uses 16 games. The 2025 baseline in this
repository uses 17 REG games, 252 carries, 14.82 per game. These are different populations and are not compared.
