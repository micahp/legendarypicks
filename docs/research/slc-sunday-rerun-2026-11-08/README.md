# Sunday slate regeneration, 2026-11-08

The fast-host rerun finished all 13 matchups, with 200 requested seeds per game. The host validator accepted 2,585 games and refused 15. Each of the 15 was run again alone on the same tree, and each refusal came back. The saved records were then checked with the fixed validator (`game_legality.py` at `ba945eeb`). All 15 pass. The table below counts them as valid: 2,600 of 2,600.

These are historical simulation results from source commit `d6caadd329b2d86700fae0342aacabd3f0a6194d` using RNG v1. They come from before the audit fixes. The 15 rechecked games were not simulated again: the saved record of each game was checked again. The `validator_build` column shows which rows were rechecked, and `original_error` keeps the first refusal. These results do not prove full roster eligibility. They are not a paired ablation baseline.

The [seed results](seed-results.csv) retain every seed, score scope, and error. [Manifest](manifest.json) records the source snapshot, reference and artifact identities and hashes of the full original host outputs. Raw ledgers and boxscores remain on the fast host at `/root/ot-sim-out/sunday-rerun-2026-11-08/`.

| Matchup (away-home) | Valid / 200 | Refused | Of valid, rechecked | Away mean | Home mean | Home wins / valid |
|---|---:|---:|---:|---:|---:|---:|
| 2026_09_ARI_SEA | 200 | 0 | 2 | 22.79 | 25.89 | 117 / 200 |
| 2026_09_CIN_ATL | 200 | 0 | 1 | 27.70 | 20.84 | 55 / 200 |
| 2026_09_CLE_NO | 200 | 0 | 0 | 17.50 | 22.20 | 129 / 200 |
| 2026_09_DAL_IND | 200 | 0 | 2 | 24.05 | 19.18 | 63 / 200 |
| 2026_09_DEN_CAR | 200 | 0 | 0 | 24.86 | 18.21 | 61 / 200 |
| 2026_09_DET_MIA | 200 | 0 | 1 | 27.14 | 22.11 | 59 / 200 |
| 2026_09_GB_NE | 200 | 0 | 4 | 23.03 | 25.01 | 113 / 200 |
| 2026_09_HOU_LAC | 200 | 0 | 1 | 21.99 | 19.07 | 75 / 200 |
| 2026_09_LA_WAS | 200 | 0 | 1 | 24.93 | 22.23 | 74 / 200 |
| 2026_09_LV_SF | 200 | 0 | 1 | 21.30 | 26.30 | 125 / 200 |
| 2026_09_NYG_PHI | 200 | 0 | 1 | 20.00 | 23.50 | 127 / 200 |
| 2026_09_NYJ_KC | 200 | 0 | 1 | 18.55 | 23.25 | 130 / 200 |
| 2026_09_TB_CHI | 200 | 0 | 0 | 24.50 | 23.13 | 90 / 200 |

Means and win counts use only `valid_full_game` records, so denominators differ by matchup. Scores for validation errors in the seed file may represent only regulation or partial results; consult `score_scope` and the original ledger before interpretation. Exit codes alone are not a validation gate.

The rerun provides a separate, consistent historical reporting set; the earlier historical reference digest discrepancy and the causes of these refusals have not been resolved by this export.
