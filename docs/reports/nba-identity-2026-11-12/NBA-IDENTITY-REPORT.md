# NBA identity report

Generated 2026-11-12 12:59 UTC from `picks.dev.db`. Read-only. No rows were changed.

## players, league = nba

| Measure | Count |
|---|---|
| Rows | 929 |
| Active | 521 |
| With ESPN ID | 674 |
| With NBA ID (hoopR) | 541 |
| With both IDs | 333 |
| With neither ID | 47 |
| Duplicate ESPN IDs (more than one row) | 0 |
| Duplicate NBA IDs (more than one row) | 0 |

## unresolved_players, league = nba

| Measure | Count |
|---|---|
| Parked rows | 212 |
| ESPN ID now in players | 17 |
| ESPN ID still missing from players | 195 |

## Files

- `players_nba.csv`: every NBA row, with its IDs.
- `unresolved_nba.csv`: every parked row, with `espn_id_now_in_players`.
