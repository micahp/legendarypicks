# NBA league gate report, 2026-11-12

Result: NBA does NOT pass the league gate on dev. 13 checks pass. 5 are UNVERIFIED. 0 FAIL.
Command: `python3 -m audit_league_stats --db data/picks.dev.db --league nba --quiet`
Code: `dev` at `81d57909`. Prod is unchanged and has none of the data below.

## What is in dev

- `players.nba_id` is now `players.hoopr_id` (dev and prod, v10.1.5).
- NBA.com roster snapshot 1607 (523 players, 30 teams).
- 44 name and team ESPN links, checked by birth date against NBA.com. 57 earlier links.
- 54 new inactive identities. 1 duplicate (William Kyle III) merged into id 63170.
- 169 recovered logs for 43 of the 44 links, plus 50 logs for the new identities. All are preseason.
- NBA.com ids in `player_source_ids`: 746.
- Resolver, roster sync and Gate G changes, with tests. Roster sync keeps the union of the ESPN and NBA.com rosters active.

## Gate G: published identity (UNVERIFIED)

- Identity: 638 of 644 used players verified. 647 ids checked. 0 wrong pairings.
- Participation: 597 of 597 players with minutes verified.
- Not verified (6): Damari Monsanto, Guillermo Diaz Graham, Mike Sharavjamts, Aaron Nkrumah, Quincy Acy, Cris Carroll.
- None of the 6 has minutes this season. Five were ESPN "did not play" or dressed with no minutes. They are not on NBA.com box scores.
- Carroll is held for a different reason: ESPN birth date 2004-01-04 against NBA.com 2003-03-29.

## Gate B: position content (UNVERIFIED for 4 positions)

- Pass: C, F, G. Groups Guard, Forward, Center pass on 494 to 499 real logs.
- UNVERIFIED, thin sample (need 30): PF 2, SF 4, SG 3 qualifying logs.
- UNVERIFIED, no logs: PG. The 29 PG rows are old inactive rows with ESPN position names. None was on a roster snapshot or has a log.
- No threshold was lowered. No log was added.

## Decisions needed from Micah

1. Does participation coverage count toward the Gate G pass? Today identity is strict.
2. Gate B: positions are NOT collapsed to G/F/C. PG, SG, SF and PF stay as positions. Box-score stat coverage is validated on the groups with enough logs (Guard, Forward, Center: 494 to 499 real logs each). A granular position with too few logs defers to its group (`defer_to_group` in the spec) only when that group PASSES. The result line says so. Missing stats in a granular position still FAIL. A thin group keeps the granular position UNVERIFIED. No threshold was lowered and no log was added.
3. London Lions: the resolver holds any player from ESPN team 134478. They are not added to the NBA table.
4. Queue: 182 stale rows removed from dev `unresolved_players`. Each matched an existing player by id and name. Audit file: `docs/audit/audit_unresolved_stale_nba_20261112.csv`. No player or log was deleted. 30 NBA rows remain: KJ Martin (2, name alias), Jae Crowder and Quincy Acy (2 owners each), 15 London, Maxwell Lewis, 10 blank keys. Prod queue is unchanged.
