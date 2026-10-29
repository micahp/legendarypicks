# SLC reference cutoff verification, 2026-10-29

Run: `scripts/nfl_sequence/audit_reference_cutoff.py` on the research branch at the model commit used for the Week 8 forecasts
(`ad7e26d9`). Database: `picks.dev.db` (read-only). Artifact: `SLC-PLAYCALL-ARTIFACT-v1.json`.

## Result

All checks pass at each cutoff. Each source advances with the cutoff, and no row at or after the cutoff is loaded.

| Cutoff | Play pool rows | Participant facts | Missed-FG pool | Last pool season |
|---|---|---|---|---|
| 2024 week 1 | 69,606 | 94,556 | 247 | 2023 week 18 |
| 2025 week 1 | 103,820 | 141,830 | 393 | 2024 week 18 |
| 2026 week 1 | 137,373 | 188,282 | 513 | 2025 week 18 |

Also checked at all three cutoffs: blocked-kick records, the safety-kick pool and the overtime-drive pool (each non-empty and
cutoff-filtered), and the kick table, whose buckets are rebuilt from the cutoff.

## What this does not establish

- The overtime choice rate is the Beta(1,1) prior (0.5) at every cutoff. The play-by-play records no toss-winner choice, so no
  observed rate exists. This is a stated limit, not a leak.
- Every 2026 forecast uses the 2022 to 2025 pool, so the 2026 outcomes are not in the engine. A prior-season team tendency
  would need its own cutoff audit before use.
- `COHORT_UNSAFE_SOURCES` in `e2_reference.py` is empty. That is consistent with this audit, but it is the code's own claim.
  The audit script is the independent check.

## Earlier concern, resolved

The reference previously loaded pinned fixtures whose seasons ran through 2025, which would leak into 2024 and 2025 evaluations.
Each such source now has a cutoff path, and the audit confirms each one is filtered by the cutoff.
