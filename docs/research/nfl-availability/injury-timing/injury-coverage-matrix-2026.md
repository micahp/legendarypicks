# Injury input coverage matrix

Generated 2026-10-27T08:22:58.121738+00:00. Cutoffs are the proposed rules in the brief, not verified publication times. A horizon is verified only with a capture at or before its cutoff and within 6 hours of it.

## Historical inputs (not verified in any case)
| horizon | 2024 timestamp-proxy | 2024 retrospective | 2024 unverifiable | 2025 (nfl_hist_injuries) |
|---|---|---|---|---|
| early | 0.0% | 100.0% | 0 | unverifiable: 100% (date_modified null) |
| practice | 5.1% | 94.9% | 0 | unverifiable: 100% |
| final | 98.7% | 1.3% | 0 | unverifiable: 100% |
| pregame | 100.0% | 0.0% (1 row, Van Noy) | 0 | unverifiable: 100% |

2024 figures: regular season, mapped weekdays (n = 5,736 latest rows), from injury_pit_audit_2024.md. Timestamp-proxy means the latest stored version was modified before the cutoff; publication timing is not established, so it is not leakage-free evidence.

## Verified prospective inputs (2026 season, append-only capture store)
| horizon | verified | not verified | pending (cutoff in future) | unmapped weekday |
|---|---|---|---|---|
| early | 0 | 107 | 157 | 8 |
| practice | 0 | 106 | 158 | 8 |
| final | 0 | 106 | 158 | 8 |
| pregame | 0 | 107 | 165 | 0 |

Capture runs in store: 2 successful, first at 2026-10-27 08:22:07+00:00, last at 2026-10-27 08:22:29+00:00.

## Final-report horizon detail (first 40 games)
| week | game type | weekday | cutoff (UTC) | status | last capture before cutoff |
|---|---|---|---|---|---|
| 1 | REG | Thursday | 2026-09-10 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Sunday | 2026-09-12 13:00:00+00:00 | not verified | none |
| 1 | REG | Monday | 2026-09-13 13:00:00+00:00 | not verified | none |
| 2 | REG | Thursday | 2026-09-17 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Sunday | 2026-09-19 13:00:00+00:00 | not verified | none |
| 2 | REG | Monday | 2026-09-20 13:00:00+00:00 | not verified | none |
| 3 | REG | Thursday | 2026-09-24 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |
| 3 | REG | Sunday | 2026-09-26 13:00:00+00:00 | not verified | none |

## Reading the matrix
- Verified prospective coverage is zero for every horizon until captures run on a schedule that brackets each cutoff. A single manual capture verifies nothing about earlier cutoffs.
- The historical columns cannot be verified. They can be used only as timestamp-proxy or retrospective inputs, and only with the caveats above.
- Models may not be fitted or promoted on these inputs until the verified column carries real coverage.
