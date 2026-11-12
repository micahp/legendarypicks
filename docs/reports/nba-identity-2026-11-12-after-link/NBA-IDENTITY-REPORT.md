# NBA identity report

Generated 2026-11-12 15:54 UTC from `picks.dev.db`. Read-only. No rows were changed.

## players, league = nba

| Measure | Count |
|---|---|
| Rows | 929 |
| Active | 521 |
| With ESPN ID | 731 |
| With NBA ID (hoopR) | 541 |
| With both IDs | 390 |
| With neither ID | 47 |
| Duplicate ESPN IDs (more than one row) | 0 |
| Duplicate NBA IDs (more than one row) | 0 |

## unresolved_players, league = nba

| Measure | Count |
|---|---|
| Parked rows | 212 |
| ESPN ID now in players | 82 |
| ESPN ID still missing from players | 130 |

## Files

- `players_nba.csv`: every NBA row, with its IDs.
- `unresolved_nba.csv`: every parked row, with `espn_id_now_in_players`.
  `times_seen` counts repeated failed resolution attempts. It is not a
  count of missing games. The queue stores no game ID, date, or stats.
