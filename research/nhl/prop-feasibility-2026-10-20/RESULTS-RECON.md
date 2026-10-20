# NHL per-player outcome reconciliation

This is an outcome-quality audit only. It contains no fitting, forecast, ROI, threshold, keep-rule, or market test.
The boxscore outcomes are from NHL GameCenter `playerByGameStats`; the comparison rows join only by numeric `playerId`.

## Sampling and coverage

- Canonical frame: 4,876 regular-season games, start seasons 2018–2022, through 2022-11-27; frame SHA256 `336d8a8d055febd742dbf31ce7a613bd2e47c2cd8fbc7a8d956fc8967ba47b1c`.
- Sample: 300 games, 60 per season block, seed `20261020`, sorted-game-id input; sample game-id SHA256 `0cd5fd97f61d2e945395b7e2b8238746dc3cad5c818fae746f1629c40149222a`.
- Anchor game `2018020160` was forced into the 2018–19 block by drawing 59 additional games there; other blocks draw 60 uniformly from their game-id-sorted frame.
- Games requested: 300; fetched and cached: 300; failed: 0.
- Player-rows compared: 10,786 shared skater rows; 2 archive-only and 10 official-only rows are listed separately. Goalies: 645 shared rows; 0 archive-only and 556 official-only. Among official-only goalie rows, 555 have zero saves, shots against, and goals against.
- Every failed request is reported below as FAILED and is excluded from player-missing counts. No failed requests are expected in a complete sample.

The final block is a partial 2022–23 slice: the canonical frame contains 343 games through November 27, 2022, not a full season. The SBR predecessor archive contains 339 of those games; this audit samples from all canonical games in the declared frame.

## Skater SOG agreement

- Exact agreement: 10,759/10,798 union player-rows = 99.639%. On shared rows only: 10,759/10,786 = 99.750%.
- Games with at least one row mismatch (including one-sided player rows): 20/300 = 6.667%. Games with 2+ mismatching player-rows: 13.
- Signed diff is archived SOG minus official SOG. Histogram on shared rows: neg3=0, neg2=1, neg1=11, zero=10759, pos1=15, pos2=0, pos3=0, abs_2plus=1, abs_gt3=0.
- Swap analysis among numeric mismatches: 9 equal-size opposite-sign swap pairs cover 18 player-rows; 9 mismatching players remain outside a pair; 8 mismatch games are entirely explained by pairs; 6 have another shape.
- Residual mismatch shape: 9 shared-row numeric mismatches remain after swap pairing, plus 2 archive-only and 10 official-only player-rows.

## Goalie outcome agreement

- A goalie row is exact only when saves, shotsAgainst, and goalsAgainst all agree. Exact: 633/1,201 union rows = 52.706%; shared rows only = 98.140%.
- The official `.goalies` arrays include 555 official-only rows with all three fields zero; 555 also have official `toi=00:00`. These are retained as one-sided entries per the parsing specification and are non-appearing goalie slots.
- Official-only nonzero goalie rows: 1. game_id=2019020951 season=2019-20 player_id=8479188 saves=8 shotsAgainst=10 goalsAgainst=2 toi=28:41
- Games with at least one goalie-row mismatch: 298/300 = 99.333%; games with 2+ mismatching goalie rows: 259.
- Signed field diff is archived minus official. For each field the histogram includes exact signed bins −3 through +3, an absolute 2+ count, and an absolute >3 overflow count. Swap pairs use equal-size opposite-sign field diffs within the same game.

| Field | -3 | -2 | -1 | 0 | +1 | +2 | +3 | abs 2+ | abs >3 | swap pairs | other mismatch players |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Saves | 0 | 1 | 3 | 638 | 2 | 0 | 1 | 2 | 0 | 0 | 7 |
| Shots against | 0 | 1 | 4 | 633 | 6 | 0 | 1 | 2 | 0 | 1 | 10 |
| Goals against | 0 | 0 | 1 | 640 | 4 | 0 | 0 | 0 | 0 | 1 | 3 |

## Per-season coverage and agreement

| Season block | Games fetched | Skater shared rows | SOG exact / union | Games with SOG mismatch | SOG swap pairs | Goalie shared rows | Official-only zero goalie rows | Nonzero goalie rows | Goalie exact / union | Games with goalie mismatch |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018-19 | 60/60 | 2160 | 2150/2160 (99.537%) | 5/60 | 5 | 129 | 111 | 0 | 126/240 (52.500%) | 58/60 |
| 2019-20 | 60/60 | 2160 | 2148/2160 (99.444%) | 7/60 | 4 | 126 | 114 | 1 | 119/241 (49.378%) | 60/60 |
| 2020-21 | 60/60 | 2150 | 2146/2159 (99.398%) | 5/60 | 0 | 132 | 108 | 0 | 130/240 (54.167%) | 60/60 |
| 2021-22 | 60/60 | 2156 | 2155/2159 (99.815%) | 3/60 | 0 | 131 | 109 | 0 | 131/240 (54.583%) | 60/60 |
| 2022-23 slice | 60/60 | 2160 | 2160/2160 (100.000%) | 0/60 | 0 | 127 | 113 | 0 | 127/240 (52.917%) | 60/60 |
| TOTAL | 300/300 | 10786 | 10759/10798 (99.639%) | 20/300 | 9 | 645 | 555 | 1 | 633/1201 (52.706%) | 298/300 |

## Impact without a model

This is a data-quality demonstration, not a model and not a market test. Each base rate is a constant over the paired player-games with both archived and official outcomes. Each Brier score evaluates that constant on the official over/under outcome. A side flip is an archived-versus-official over/under disagreement; missing one-sided player rows are disclosed above and are not imputed into this paired denominator.

| Market stat | Line | Paired player-games | Archived base rate | Official base rate | Archived constant Brier on official | Official constant Brier on official | Side flips | Flip share |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SOG | 0.5 | 10786 | 76.358% | 76.349% | 0.180573 | 0.180573 | 5 | 0.046% |
| SOG | 1.5 | 10786 | 47.237% | 47.228% | 0.249232 | 0.249232 | 9 | 0.083% |
| SOG | 2.5 | 10786 | 25.839% | 25.848% | 0.191670 | 0.191670 | 7 | 0.065% |
| SOG | 3.5 | 10786 | 13.147% | 13.137% | 0.114115 | 0.114115 | 1 | 0.009% |
| SAVES | 20.5 | 645 | 77.209% | 77.364% | 0.175122 | 0.175119 | 1 | 0.155% |
| SAVES | 24.5 | 645 | 60.465% | 60.465% | 0.239048 | 0.239048 | 0 | 0.000% |
| SAVES | 28.5 | 645 | 39.070% | 39.070% | 0.238053 | 0.238053 | 0 | 0.000% |

## Verdict

The verdict is computed by the signed rule in the audit brief. A random sample of 60 games per block estimates agreement only for these observed games; it cannot certify every game in the archive or establish performance in future seasons. In particular, the earlier 2-of-36 anchor-game discrepancy is not by itself a population estimate; it is retained here as a required sample game.
- **NOT_SETTLEMENT_GRADE.** At least one signed settlement-grade or correction condition fails. The lowest-cost official import is one NHL GameCenter boxscore request for each of the 4,876 games in this canonical frame (4,876 sequential requests total; 300 sampled responses are already cached, so 4,576 additional requests remain). Import playerId plus SOG for forwards/defense and playerId plus saves, shotsAgainst, goalsAgainst, and goalie toi for goalies so zero-minute backup slots can be distinguished; retain raw gzip responses under this artifact's cache/ and write a normalized research-only player-game CSV beside the results. Do not start that import in this task.
- Decision measurements: SOG union exact agreement is 99.639% (passes the 99.5% floor); 13 games have 2+ skater mismatches (fails the zero-game condition); maximum listed side-flip share is 0.155% (passes both caps). The correction rule still fails: 9 shared numeric SOG mismatches are outside swap pairs, with 2 archive-only and 10 official-only skater rows.

## Failed requests

- None.

## Reproducibility

- Run offline: `/root/lp-goalie-research/.venv/bin/python research/nhl/prop-feasibility-2026-10-20/recon.py`.
- The default run makes no network requests and requires all 300 committed `.json.gz` cache files plus the read-only canonical CSV and DuckDB source paths embedded in `recon.py`.
- Pinned measurement digest (the three CSV artifacts): `13386d4311c7393334c26097b2aa8832a1c10a19a9d05b33ad0372e0907d3d48`.
- The script exits nonzero if the canonical frame hash, sample hash, schema, row identity, cache completeness, or pinned CSV measurement digest changes.
