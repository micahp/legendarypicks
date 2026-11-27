# GB-LAR postgame grades

Graded UTC: 2026-11-26T18:35:00.679957+00:00
Final: LAR 26 - GB 13 (total 39, margin 13).
Pregame lines: LAR spread +2.5; total 43.5. LAR covered; game went under.

## Game forecasts

| Model | Valid | LAR win | LAR cover | Over | Brier win/spread/total | Mean LAR-GB |
|---|---:|---:|---:|---:|---:|---:|
| v1 | 1000 | 57.4% | 50.8% | 74.3% | 0.181/0.242/0.552 | 27.2-25.0 |
| v1.6 | 1000 | 64.0% | 57.6% | 63.4% | 0.130/0.180/0.402 | 26.3-22.0 |
| v2_simplified | 1000 | 59.9% | 54.2% | 61.2% | 0.161/0.210/0.375 | 25.1-22.0 |
| v2_support_aware | 1000 | 60.4% | 54.4% | 37.5% | 0.157/0.208/0.141 | 22.0-18.7 |
| v2_soft_conditioning_partial (partial) | 748 | 58.6% | 53.6% | 57.0% | 0.172/0.215/0.324 | 24.5-21.3 |
| ceg_frozen | 1000 | 54.9% | 48.5% | 45.1% | 0.203/0.265/0.203 | 22.2-20.4 |

## Player props

Probabilities use valid per-seed simulated stats; pushes excluded from Brier/accuracy. Unsupported markets and unmatched players are not scored as zero.

| Model | Graded lines | By-market Brier (non-push) |
|---|---:|---|
| v1 | 538 | interceptions_thrown n=2 Brier 0.420, pass_attempts n=7 Brier 0.444, pass_completions n=8 Brier 0.505, passing_rushing_yards n=28 Brier 0.576, passing_touchdowns n=2 Brier 0.284, passing_yards n=120 Brier 0.570, receiving_yards n=159 Brier 0.247, receptions n=26 Brier 0.308, rush_attempts n=18 Brier 0.254, rushing_receiving_touchdowns n=11 Brier 0.118, rushing_receiving_yards n=40 Brier 0.290, rushing_yards n=84 Brier 0.223, targets n=19 Brier 0.211, total_completions n=2 Brier 0.516, total_passing_attempts n=2 Brier 0.448, total_rush_attempts n=3 Brier 0.259, total_touchdowns n=7 Brier 0.119 |
| v1.6 | 538 | interceptions_thrown n=2 Brier 0.290, pass_attempts n=7 Brier 0.360, pass_completions n=8 Brier 0.392, passing_rushing_yards n=28 Brier 0.436, passing_touchdowns n=2 Brier 0.313, passing_yards n=120 Brier 0.464, receiving_yards n=159 Brier 0.255, receptions n=26 Brier 0.270, rush_attempts n=18 Brier 0.256, rushing_receiving_touchdowns n=11 Brier 0.133, rushing_receiving_yards n=40 Brier 0.334, rushing_yards n=84 Brier 0.235, targets n=19 Brier 0.149, total_completions n=2 Brier 0.379, total_passing_attempts n=2 Brier 0.352, total_rush_attempts n=3 Brier 0.240, total_touchdowns n=7 Brier 0.138 |
| v2_simplified | 538 | interceptions_thrown n=2 Brier 0.254, pass_attempts n=7 Brier 0.653, pass_completions n=8 Brier 0.662, passing_rushing_yards n=28 Brier 0.534, passing_touchdowns n=2 Brier 0.241, passing_yards n=120 Brier 0.558, receiving_yards n=159 Brier 0.293, receptions n=26 Brier 0.288, rush_attempts n=18 Brier 0.474, rushing_receiving_touchdowns n=11 Brier 0.107, rushing_receiving_yards n=40 Brier 0.390, rushing_yards n=84 Brier 0.364, targets n=19 Brier 0.204, total_completions n=2 Brier 0.622, total_passing_attempts n=2 Brier 0.638, total_rush_attempts n=3 Brier 0.486, total_touchdowns n=7 Brier 0.093 |
| v2_support_aware | 538 | interceptions_thrown n=2 Brier 0.236, pass_attempts n=7 Brier 0.594, pass_completions n=8 Brier 0.624, passing_rushing_yards n=28 Brier 0.308, passing_touchdowns n=2 Brier 0.124, passing_yards n=120 Brier 0.355, receiving_yards n=159 Brier 0.269, receptions n=26 Brier 0.292, rush_attempts n=18 Brier 0.444, rushing_receiving_touchdowns n=11 Brier 0.123, rushing_receiving_yards n=40 Brier 0.348, rushing_yards n=84 Brier 0.341, targets n=19 Brier 0.198, total_completions n=2 Brier 0.588, total_passing_attempts n=2 Brier 0.580, total_rush_attempts n=3 Brier 0.454, total_touchdowns n=7 Brier 0.108 |
| v2_soft_conditioning_partial | 538 | interceptions_thrown n=2 Brier 0.221, pass_attempts n=7 Brier 0.645, pass_completions n=8 Brier 0.659, passing_rushing_yards n=28 Brier 0.509, passing_touchdowns n=2 Brier 0.214, passing_yards n=120 Brier 0.538, receiving_yards n=159 Brier 0.283, receptions n=26 Brier 0.284, rush_attempts n=18 Brier 0.455, rushing_receiving_touchdowns n=11 Brier 0.104, rushing_receiving_yards n=40 Brier 0.360, rushing_yards n=84 Brier 0.347, targets n=19 Brier 0.203, total_completions n=2 Brier 0.626, total_passing_attempts n=2 Brier 0.633, total_rush_attempts n=3 Brier 0.451, total_touchdowns n=7 Brier 0.091 |

## Exact seed failures and run errors

- The seed-ledger audit found no invalid outcomes in V1, V1.6, V2 Simplified, V2 Support-Aware or Frozen CEG. Soft Conditioning had 0 invalid outcomes in 801 attempt rows at the 18:39:42 UTC audit; its grade snapshot below includes 748 completed games because the run continued while grading.
- V1 has no failed seed outcomes in its per-seed records. Its 49 overtime seeds omitted from the aggregate counter are: 300032, 300097, 300112, 300121, 300124, 300130, 300137, 300154, 300217, 300232, 300235, 300246, 300250, 300252, 300259, 300264, 300300, 300308, 300309, 300313, 300317, 300344, 300346, 300373, 300419, 300470, 300478, 300528, 300561, 300565, 300574, 300617, 300684, 300715, 300732, 300757, 300759, 300773, 300784, 300841, 300877, 300888, 300890, 300922, 300925, 300978, 300979, 300988, 300993. These are completed games, not failed seeds.
- Frozen V2 failed before a seed started: `EXPERIMENTAL_CONFIG_HASH_MISMATCH`; expected `776d69256c157655db4e493fa2166c9f5f72a18c5b2c11ef272a58b5e0e4a58c`, actual `bc27dc32bcabda3cfa94baca4d69a4ac03bee519b9c5ae984d79cb2a8a778a38`. Full traceback is in the JSON audit.

## Coverage

- V1: 1,000 complete valid-final score rows were graded. Its aggregate counter reports 951; it omits 49 complete overtime rows listed in the seed audit.
- V1.6, V2 Simplified, V2 Support-Aware: 1,000 valid each.
- V2 Soft Conditioning: 748 completed valid games graded from 748 rows; run remained active and had 801 total attempts by the later seed-ledger audit.
- Frozen CEG: 1000 valid; no player-level outputs.
- Frozen V2: 1,000-game job failed before seed execution.
- Player-prop identity joined by normalized name and team due missing RotoWire-to-GSIS mapping.
- Full individual prop lines and source hashes are in /root/runs/week-12/summary/gb-la-postgame-grades-2026-11-26.json.
- Research grade only; production settlement tables unchanged.

Unresolved prop rows: not_in_final_boxscore=105, unsupported:extra_points_made=15, unsupported:field_goals_made=10, unsupported:kicking_points=15, unsupported:longest_pass_completion=10, unsupported:longest_reception=115, unsupported:longest_rushing_attempt=20, unsupported:sacks=75
