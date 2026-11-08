# Sunday noon games: 100 seeds each, 2026-11-08

Seven matchup batches ran on the fast host using `slc-v2` at `8007ebf99f0fd6c98d4fd7676b998efec00eb388`, RNG v2, the `v1_full_stack` profile, the five ordinary blocker fixes and seeds 1–100. Every process exited 0. The input was the read-only application database and the frozen snapshots in `/tmp/bench/snapshots/`; the launcher and raw output remain at `/root/ot-sim-out/slc-v2-100-noon-2026-11-08/` on the fast host. This is not a run of the `--slc-v2` lineup configuration.

| Matchup | Valid completed | Overtime | Accounting reconciled | Clock reconciled |
|---|---:|---:|---:|---:|
| CLE–NO | 100/100 | 4 | 100/100 | 100/100 |
| DAL–IND | 100/100 | 4 | 100/100 | 100/100 |
| DEN–CAR | 100/100 | 4 | 100/100 | 100/100 |
| DET–MIA | 100/100 | 3 | 100/100 | 100/100 |
| LA–WAS | 100/100 | 6 | 100/100 | 100/100 |
| NYG–PHI | 100/100 | 1 | 100/100 | 100/100 |
| NYJ–KC | 100/100 | 4 | 100/100 | 100/100 |

All 700 requested seed IDs occurred exactly once, with no reported validation failures. All 700 exported box scores passed their accounting and modeled clock reconciliation checks. Reconciliation does not independently establish model realism or complete player snap accounting.

Each snapshot's as-of time was **4:16:59 p.m. Central on Saturday, November 7**, not the 90-minute game-day cutoff. All 26,800 exported player rows report unknown roster eligibility. These results do not establish official game-day availability. Source coverage fallbacks remain present; these runs are not an ablation or a calibration study.

[results.json](results.json) preserves each seed's status and score, the source snapshot identity, per-game reconciliation and eligibility counts, and SHA-256 hashes of each full batch, seed ledger and box-score export. Raw files and launcher are not included here; their hashes were calculated on the fast host during this export. The source database is mutable and is not pinned by a complete file hash in this report.
