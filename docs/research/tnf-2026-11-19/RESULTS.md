# TNF 2026-11-19, IND at HOU: family batch and player prop comparison

Status: v2 is complete. The corrected v1 runs (validity without the verified-snapshot gate) were still running when this
was compiled. Their rows below are partial and will be updated when they finish.

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
| v1 | 100 | 0 of 100 | 24.82 | 23.2 | 0.56 |
| v1.5 | 100 | 0 of 100 | 24.76 | 22.43 | 0.58 |
| v1.6 | 100 | 0 of 100 | 23.83 | 22.71 | 0.52 |
| v1.7 | 100 | 0 of 100 | 25.03 | 23.29 | 0.57 |
| v1.5-vfg | 24 | in progress | 26.17 | 24.54 | 0.583 |
| v1.6-vfg | 54 | in progress | 25.74 | 24.76 | 0.537 |
| v1.7-vfg | 57 | in progress | 24.26 | 22.56 | 0.632 |

- v2 is the only family member with full-game validity: 100 of 100.
- The original v1 family runs score regulation only. Their 0 valid games come from the verified-snapshot gate, which
  this snapshot does not meet.
- The corrected v1 runs remove that gate, so they can produce valid full games. They are in progress.

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

Full comparison: `prop-comparison-v2.json`. Summary by model: `summary-by-model.json`.

## Known gaps

- No injury reports in this snapshot.
- The Oracle snapshot does not carry the starter flags or full-depth roster. The roster resolver output for November 18
  (Miami and Buffalo) was not used for this game.
- The kicker table is a derived scratch file.
- The raw seed files stay on the fast host. They are compressed there, not in git.
