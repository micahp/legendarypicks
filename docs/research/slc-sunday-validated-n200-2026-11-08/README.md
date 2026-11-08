# Sunday 200-seed matchup table, validated counts, 2026-11-08 slate

Built from the host ledgers `2026_09_<game>-n50.seeds.jsonl` (seeds 1-50) and `-s51-n150.seeds.jsonl` (seeds 51-200), on the executed build in `slc-sunday-smoke-2026-11-08/executed-code.patch`. Built by `summarize_n200.py`, which is copied here.

Read the counts as follows. `validated_complete` is the number of games the validator accepted. It is the only number a distribution is computed from. `refused_validator` counts games the validator refused under the **pre-fix** code (the build that ran the batch). `refused_pre_fix_now_pass` counts the subset of those whose saved record passes the **current** validator (`b251b667`). Those games are **not** in the medians or bands. They are not re-admitted, because the batch has not been rerun on the fixed validator and determinism is not yet settled.

| game | validated of 200 | refused pre-fix | of which pass current validator |
|---|---|---|---|
| ARI_SEA | 198 | 2 | 2 (196, 197) |
| CIN_ATL | 198 | 2 | 0 |
| CLE_NO | 199 | 1 | 0 |
| DAL_IND | 199 | 1 | 0 |
| DEN_CAR | 198 | 2 | 0 |
| DET_MIA | 198 | 2 | 0 |
| GB_NE | 196 | 4 | 4 (64, 96, 100, 190) |
| HOU_LAC, LA_WAS, LV_SF, NYG_PHI, NYJ_KC, TB_CHI | 200 | 0 | 0 |

Five matchups still carry unresolved refusals (CIN_ATL, CLE_NO, DAL_IND, DEN_CAR, DET_MIA). Under the owner's rule, these are not validated. Two more (ARI_SEA, GB_NE) carry refusals that the fixed validator now passes. Those seeds need a rerun on the fixed validator before they count.

The n=50 table (`slc-sunday-pass50-2026-11-08/matchup-table-n50.csv`) is unchanged. Its games are complete for every seed in 1-50, so it needs no relabel.
