# Sunday slate regeneration, 2026-11-08

The fast-host rerun finished all 13 matchups, with 200 requested seeds per game. Its ledgers contain 2,585 valid completed games and 15 validation errors. All 13 launcher exit codes were zero; individual seed failures remain excluded from the valid-game summaries below.

These are historical simulation results from source commit `d6caadd329b2d86700fae0342aacabd3f0a6194d` using RNG v1. They predate the subsequent audit fixes, including the roster-eligibility and blocked-kick validator changes. They are not evidence of full roster eligibility and are not a paired ablation baseline. No failed seed has been revalidated or readmitted here.

The [seed results](seed-results.csv) retain every seed, score scope, and error. [Manifest](manifest.json) records the source snapshot, reference and artifact identities and hashes of the full original host outputs. Raw ledgers and boxscores remain on the fast host at `/root/ot-sim-out/sunday-rerun-2026-11-08/`.

| Matchup (away-home) | Valid / 200 | Validation errors | Away mean | Home mean | Home wins / valid |
|---|---:|---:|---:|---:|---:|
| 2026_09_ARI_SEA | 198 | 2 | 22.83 | 25.86 | 115 / 198 |
| 2026_09_CIN_ATL | 199 | 1 | 27.71 | 20.79 | 54 / 199 |
| 2026_09_CLE_NO | 200 | 0 | 17.50 | 22.20 | 129 / 200 |
| 2026_09_DAL_IND | 198 | 2 | 24.15 | 19.18 | 62 / 198 |
| 2026_09_DEN_CAR | 200 | 0 | 24.86 | 18.21 | 61 / 200 |
| 2026_09_DET_MIA | 199 | 1 | 27.18 | 22.12 | 59 / 199 |
| 2026_09_GB_NE | 196 | 4 | 23.06 | 24.91 | 110 / 196 |
| 2026_09_HOU_LAC | 199 | 1 | 22.02 | 19.11 | 75 / 199 |
| 2026_09_LA_WAS | 199 | 1 | 24.96 | 22.25 | 74 / 199 |
| 2026_09_LV_SF | 199 | 1 | 21.30 | 26.33 | 125 / 199 |
| 2026_09_NYG_PHI | 199 | 1 | 20.03 | 23.48 | 126 / 199 |
| 2026_09_NYJ_KC | 199 | 1 | 18.59 | 23.21 | 129 / 199 |
| 2026_09_TB_CHI | 200 | 0 | 24.50 | 23.13 | 90 / 200 |

Means and win counts use only `valid_full_game` records, so denominators differ by matchup. Scores for validation errors in the seed file may represent only regulation or partial results; consult `score_scope` and the original ledger before interpretation. Exit codes alone are not a validation gate.

The rerun provides a separate, consistent historical reporting set; the earlier historical reference digest discrepancy and the causes of these refusals have not been resolved by this export.
