# 2026 Weeks 1–7 SLC input readiness

Audit date: 2026-10-29. Model checkout: `research/slc-decision-layer-2026-10-29` at `0df4ad60f1b43b11b922c5ce96ed1f2069683f94`.

This audit covers all 107 regular-season games in Weeks 1–7. It checks whether the exact schedule, depth-chart, roster and injury source versions were published before each game’s cutoff; whether both teams have a complete frozen-roster candidate; whether starter identities resolve; and whether injury data covers both teams. It does not substitute Week 8 inputs.

## Readiness

| Week | Games | Cutoff-valid | Exploratory reconstruction | Refused |
|---:|---:|---:|---:|---:|
| 1 | 16 | 0 | 12 | 4 |
| 2 | 16 | 0 | 12 | 4 |
| 3 | 16 | 0 | 13 | 3 |
| 4 | 16 | 0 | 13 | 3 |
| 5 | 15 | 7 | 1 | 7 |
| 6 | 14 | 10 | 0 | 4 |
| 7 | 14 | 11 | 0 | 3 |
| **Total** | **107** | **28** | **51** | **28** |

There are 42 Week 5–7 games with recorded Legendary Picks lock timestamps: 28 pass the source and roster checks, and 14 are refused. The other 65 games have no recorded LP lock (Weeks 1–4, plus TB–DAL in Week 5); complete rows in that group are labeled exploratory because their original forecast cutoff cannot be verified.

“Cutoff-valid” here means the official dated archive versions were publicly published before the recorded LP lock and the required source/roster checks pass. It does **not** mean an LP capture was acquired and frozen at that historical time. The files were downloaded retrospectively. The matrix records archive publication times and hashes separately from local capture evidence; no contemporaneous capture timestamp is claimed.

## Main refusal causes

The 28 refused games fail at least one required input check. The most common gap is a missing team-level injury-report row (32 team-game occurrences). Other failures include absent team depth-chart coverage, an incomplete 28-role starter set (including missing NT, LS or PK roles), and one unresolved canonical player identity. The exact per-game reasons, role gaps, roster row counts and hashes are in `readiness_matrix.csv` and `readiness_matrix.json`.

An absent injury-report row is not treated as a healthy roster. The [nflreadr injury dictionary](https://nflreadr.nflverse.com/articles/dictionary_injuries.html) defines injury-report status as a player’s status for a game; the weekly injury feed is therefore required to support availability decisions.

## Sources and provenance

The audit uses official weekly nflverse archived releases, with source publication timestamps and SHA-256 hashes in `archive_manifest.json`:

- [2026-09-03 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-09-03)
- [2026-09-10 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-09-10)
- [2026-09-17 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-09-17)
- [2026-09-24 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-09-24)
- [2026-10-01 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-10-01)
- [2026-10-08 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-10-08)
- [2026-10-15 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-10-15)
- [2026-10-22 archive](https://github.com/nflverse/nflverse-data-archives/releases/expanded_assets/archive-2026-10-22)

`readiness_matrix.csv` is the per-game review sheet. `schedule_observed_utc` is the archive asset’s publication timestamp, not a historical LP acquisition timestamp. `depth_published_utc`, `roster_published_utc` and `injury_published_utc` are the corresponding archive publication times. The `*_sha256` values pin the exact source assets. The nested home/away roster fields show team, source depth time, row counts, starter-role count, canonical-ID gaps and eligibility promotions. `cutoff_utc` is the recorded LP lock when present; otherwise `audit_boundary_utc` is kickoff minus one second and the game remains exploratory.

The input timing is supported by official dated releases; it is not a substitute for the committed simulator’s stricter capture contract. `pregame_capture.py` requires a manifest proving the file was acquired no later than cutoff, as well as source/depth timestamps at or before cutoff. No such Weeks 1–7 capture manifests or cutoff-specific availability snapshots were found in this checkout. This audit therefore does not bypass that gate or present a retrospective download as a contemporaneous capture.

## Simulation gate

No paired SLC v1 versus S0 smoke or large batch was started. The smoke is blocked for two implementation/provenance reasons:

1. The committed batch runner has no named `v1_full_stack` profile. It accepts individual layer flags and records them, but does not resolve and fail closed on the complete profile, its incompatible alternatives, or the profile’s configuration hash.
2. The inputs above are archival reconstructions, not contemporaneous capture manifests accepted by the current pregame loader. Weeks 1–7 availability snapshots and per-cutoff frozen streak-context files are also absent. The Week 8 streak file is not used.

The 28 cutoff-valid games are candidates for an explicitly labeled archival-reconstruction smoke after a dedicated archived-source input path and a fail-closed full-stack profile are available. They are not ready for the current prospective-capture runner. Do not launch 10K historical runs until that path, the profile manifest, and a paired-seed box-score reconciliation smoke pass. Preserve Weeks 1–4 and TB–DAL Week 5 as exploratory only, and keep all 28 refused games excluded.

## Files

- `readiness_matrix.csv` — 107 per-game records with timestamps, provenance hashes, roster coverage and reasons.
- `readiness_matrix.json` — same records as structured JSON.
- `readiness_summary.json` — counts, game IDs, refusal causes, model version and smoke gate.
- `archive_manifest.json` — official archive publication timestamps and source hashes.
