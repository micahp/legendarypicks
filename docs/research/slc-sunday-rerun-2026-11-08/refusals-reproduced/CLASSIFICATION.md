# The nine new refusals in the 13 x 200 Sunday regeneration, classified

Run: source `d6caadd3`, RNG v1, 15 refusals in 2,600 games (six already classified in `slc-sunday-failures-2026-11-08`). Each of the nine below reproduced when its seed was rerun alone on the same host tree, which confirms the run identity is deterministic. The saved refused records are in `refused-records/`. "Host validator" is the validator in that tree (`d6caadd3`); "current validator" is `game_legality.py` at the commit that adds this file.

| Matchup | Seed | Host validator said | What the play was | Current validator |
|---|---|---|---|---|
| CIN-ATL | 17 | field goal ends the drive but a play follows | blocked field goal, ball live | pass |
| DAL-IND | 82 | field goal ends the drive but a play follows | blocked field goal, ball live | pass |
| DET-MIA | 177 | field goal ends the drive but a play follows | blocked field goal, ball live | pass |
| NYG-PHI | 197 | field goal ends the drive but a play follows | blocked field goal, ball live | pass |
| NYJ-KC | 9 | field goal ends the drive but a play follows | blocked field goal, ball live | pass |
| HOU-LAC | 9 | field goal ends the drive and no kickoff can follow | missed field goal that expires the first half | pass |
| LA-WAS | 146 | field goal ends the drive and no kickoff can follow | missed field goal that expires the first half | pass |
| DAL-IND | 120 | down 1 with no yards gained | blocked punt recovered by the kicking team for a first down at midfield | pass (new rule) |
| LV-SF | 23 | a kickoff follows the last drive | overtime field goal ties 20-20 with 1 second left; the post-score kickoff runs the clock out | pass (new rule) |

## Result

- Seven were the validator being narrower than the engine, in clusters already fixed (blocked field goal is live; a clock-expiring first-half miss takes a halftime kickoff).
- Two were new gaps, fixed in this change: the blocked-kick rules now cover blocked punts as well as field goals, and a clock-expiring post-score kickoff ends an overtime game as it does in the fourth quarter (a tie is legal there).
- None of the nine is an engine defect. All fifteen saved refused records from the slate (these nine plus the six in `slc-sunday-failures-2026-11-08`) pass the current validator.
- The four older overtime-kickoff cases (CLE-NO 29, DEN-CAR 198, DET-MIA 59 and 117) come from the unreproducible 00:20 ledger, not this run, and did not recur here.

These games are not re-admitted to any published table by this file. Re-admission needs the slate rerun on the fixed validator under a labelled identity.
