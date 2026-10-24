# Snap-anchored cohort reconciliation, per play (2026-10-24)

Two cohorts were built for weeks 1–5 of the 2022 BDB2025 mirror:

- **LP** (`docs/research/bdb2025-snap-anchored-cohort-v1.csv`, commit 91ec2c29 on `research/nfl-snap-anchored-benchmark-2026-10-24`):
  9,456 plays, 9,289 eligible, 167 excluded.
- **Gridiron Codex pass** (`docs/research/bdb2025-snap-all-player-manifest-v1.csv`, commit 1c74b8b0 on `research/nfl-tracking-feasibility-2026-10-23`):
  9,388 included rows. The file has no per-play exclusion reasons.

## Per-play join on (game_id, play_id)

| Set | Plays |
| --- | ---: |
| LP eligible | 9,289 |
| Gridiron included | 9,388 |
| In both | 9,289 |
| LP eligible, not in Gridiron | 0 |
| Gridiron included, not LP eligible | 99 |
| LP plays, not in Gridiron | 68 |

## The 99 Gridiron-only plays

All 99 are LP plays excluded for `blank_formation` (`offenseFormation` is the literal string `NA`). By `plays.csv` flags,
92 are quarterback kneels (`qbKneel = 1`) and 7 are quarterback spikes (`qbSpike = TRUE`). In `playDescription`, 91 of the 92
kneel-flagged plays mention a kneel and the remaining one does not, and all 7 spike plays mention a spike. These flags do not establish that no other kick-type play is in the set; that was not separately checked.
They are kept as a **separate, labelled stratum**, not as part of the movement benchmark.

## The 68 plays absent from the Gridiron manifest

| LP exclusion reason | Plays |
| --- | ---: |
| `history_incomplete` (fewer than five frames before the snap) | 27 |
| `blank_formation` (not in the Gridiron manifest) | 24 |
| `snap_definition_disagreement` (`snap_direct`, no `ball_snap`) | 17 |
| **Total** | **68** |

Together with the 99 above, the 167 LP exclusions are fully accounted for: 123 blank-formation (24 absent from Gridiron,
99 kept), 27 history-incomplete, 17 snap-definition. The Gridiron manifest does not record why these 68 are absent, so
their reasons are inferred from LP's reasons, not from its file.

## Canonical cohort

- **Canonical movement cohort: the 9,289 LP-eligible plays** (prereg commit 4bb5add1). It applies the blank-formation
  rule (E1), the SNAP frame cross-check, and the input window as pre-registered.
- **Stratum: the 99 blank-formation plays**, kept for kick-type or special-teams analysis, reported separately.
- Movement results must not pool the stratum with the canonical cohort.

## Remaining wording differences (not in these plays)

- Gridiron requires 22-player presence at +10 frames as an input condition. LP counts it as scoring presence only. No
  LP-eligible play fails the +10 condition, so the two agree on the eligible set.
- Gridiron's manifest has no per-play exclusion reasons. LP's has one per play.
