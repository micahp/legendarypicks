# TNF 2026-11-19, IND at HOU: family batch and player prop comparison

Status: complete. All 100 seeds finished for all nine runs.

## Inputs

- Snapshot: built by Oracle, as of 2026-11-17T12:00:00Z. Kickoff 2026-11-20T01:15:00Z, checked against the NFL scoreboard.
  The snapshot's evaluation block marks 3 inputs unverified.
- Streak file: Oracle, 150 completed regular-season games before the cutoff.
- Snap counts: Oracle, 2026 weeks 1 to 10 from nflverse.
- Play-by-play for the v2 scoring: nflverse 2026, weeks 1 to 10 (sha256 32334d4a...).
- Kicker table: extended through week 11 from the roster files. A derived working file; it is not committed.
- Frozen database: sha256 e997951b... (copy of dev made 2026-11-18).
- Seeds 300001 to 300100 (100 per model). Run on the fast host.

## Results by model (100 seeds)

| model | games done | valid full games | home mean | away mean | home win rate |
|---|---|---|---|---|---|
| v2-pbp-2026-11-17 | 100 | 100 of 100 | 22.12 | 18.34 | 0.63 |
| v1-vfg | 100 | 100 of 100 | 23.45 | 21.43 | 0.51 |
| v1.5-vfg | 100 | 100 of 100 | 24.06 | 24.38 | 0.51 |
| v1.6-vfg | 100 | 100 of 100 | 26.81 | 25.83 | 0.52 |
| v1.7-vfg | 100 | 100 of 100 | 25.08 | 23.62 | 0.57 |
| v1 | 100 | 0 of 100 | 24.82 | 23.2 | 0.56 |
| v1.5 | 100 | 0 of 100 | 24.76 | 22.43 | 0.58 |
| v1.6 | 100 | 0 of 100 | 23.83 | 22.71 | 0.52 |
| v1.7 | 100 | 0 of 100 | 25.03 | 23.29 | 0.57 |

- v2 and the corrected v1 family (validity without the verified-snapshot gate) all score 100 of 100 valid full games.
- The original v1 family runs score regulation only. Their 0 valid games come from the verified-snapshot gate, which this
  snapshot does not meet. The corrected runs are on branches feat/v1*-valid-full-games-2026-11-18, not pushed.

## Player prop comparison (v2, 100 seeds)

- Method: `prop_compare.py`. For each priced line, the model's over probability is the share of seeds with a stat above
  the line. The market's is the vig-free implied over probability. Stats are summed from the passing, rushing and
  receiving lines.
- 656 priced lines (182 unique player, market and line). Mean absolute edge 0.246.
- The biggest gaps are not market edges. They come from the model's usage:
  - David Montgomery (HOU RB): 4.2 rush attempts and 15.8 rushing yards a game on average. His rushing lines sit near 55
    yards, so the model says about 3 percent over.
  - Anthony Gould and Deion Burks (IND WR): 0.1 to 0.6 targets a game. Their receiving lines expect about 2 receptions.
- The simulation output leaves the starter and roster-status fields empty for these players. The workload inputs look
  incomplete. Treat these gaps as input problems until they are checked.

Full comparison: `prop-comparison-v2.json` (v2) and `prop-comparison-v1-vfg.json` (corrected v1). Summary by model: `summary-by-model.json`.

Corrected v1 (v1-vfg): 656 lines, mean absolute edge 0.271. The largest gaps are the same kind as v2: low usage for
Seth McGowan, Laquon Treadwell and David Montgomery in the simulation, not market edges.

## Known gaps

- No injury reports in this snapshot.
- The Oracle snapshot does not carry the starter flags or full-depth roster. The roster resolver output for November 18
  (Miami and Buffalo) was not used for this game.
- The kicker table is a derived scratch file.
- The raw seed files stay on the fast host. They are compressed there, not in git.
