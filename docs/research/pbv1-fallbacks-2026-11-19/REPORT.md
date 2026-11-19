# PBV1 fallback decisions: what data was missing

Scope: 2,000 PBV1 game records for IND at HOU (1,000 pbv1-off seeds and 1,000 pbv1-on seeds), read from the batch outputs on the fast host. Every game has fallbacks. Counts are fallback events, not decisions.

## Totals

| Bucket | What was missing | Events | Share |
|---|---|---|---|
| 1. Label has no matching historical row | No row in this situation cell with the drawn label | 744,227 | 88.3% |
| 2. Exact yardline | No historical rows at this exact yardline | 37,324 | 4.4% |
| 3. Player or target history | No history for this player or target in this cell | 25,943 | 3.1% |
| 4. Kick share | Historical kick share for this situation not modelled | 22,519 | 2.7% |
| 5. Streak | No rows for the current streak | 6,734 | 0.8% |
| 6. Coverage, formation, down, field | No rows for this coverage, formation, down/distance or field zone | 5,431 | 0.6% |
| 7. Earlier play | No earlier play of this type in this game | 338 | <0.1% |
| 8. Playbook | No playbook row for the category | 1 | <0.1% |
| **Total** | | **842,517** | |

About 422 fallback events per game. The pbv1-off and pbv1-on arms match: 422 and 421 per game.

## Bucket 1 detail: label category missing

| Group | Categories | Labels | Events |
|---|---|---|---|
| Player role | A, B, C | RB/WR/TE/Other; RB/QB/WR_TE/Other; guard/tackle/end | 26,955 |
| Play shape | D, E | short/deep; left/middle/right | 54,163 |
| Binary flag | F, G, H, I | yes/no (four flags) | 211,260 |
| Alignment or count | J, K, L, M, N | S/U/P; L/M/R; 0/1/2/3+; <=5/6/7/8+; 3-4/5+ | 451,849 |

Per category: A 15,810; B 1,632; C 9,513; D 16,946; E 37,217; F 84,487; G 27,129; H 52,387; I 47,257; J 103,207; K 94,986; L 72,769; M 122,925; N 57,962.

## Reading

- Most missing data is in the label filter, not in the player or yardline tables. The source table has no row for many label combinations in a cell.
- The alignment and count labels (J to N) are 61% of label misses. The binary flags (F to I) are 28%.
- PBV1 does not change the fallback rate. The source table, not the PBV1 package, sets it.

Source: `pbv1_fallbacks.py` and `pbv1_cats.py` on the fast host (`/tmp/claude-0/`). Input folders: `current/out/runs/pbv1-off`, `current/out/runs/pbv1-on`, `current/out-pbv1on-rest/runs/pbv1-on`.
