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
2. Gate B: group the detailed positions into Guard, Forward, Center, or normalize the old PG, SG, SF, PF rows.
3. Keep London Lions players (14 ids, ESPN team 134478) out of the NBA table?
4. Retire the 185 stale rows in `unresolved_players` (the id is now owned)? Needs approval to delete.

## Held items

- `unresolved_players` has 212 rows: 185 stale, 15 London Lions, 11 blank key, 1 Rotowire key (6575, likely Walter Clayton Jr.).
- NBA.com and ESPN rosters disagree for some players (Lanier, Tomlin, Evans, Diop are on NBA.com only). Per-source status is derivable from the newest `roster_snapshots` row per source. No new field is needed.
- Wrightsell: ESPN id 5460427 is an empty ESPN stub kept as `espn_id_alias_unconfirmed`. A reported 1999 birth year is unverified.

## Before prod

Prod needs the identity data migrated with approval. The gate must pass first. Remove the `nba_id` fallback reads only after both DBs are migrated and API tests pass.
Disk is about 2.6 GB free, so a full prod backup is not possible now.

## Update: decisions applied (branch `fix/nba-gate-decisions`, not on dev)

Result on dev DB after the change: 14 pass, 0 UNVERIFIED, 0 FAIL.

1. Gate G: players who played (minutes above zero) block. Zero-minute and roster-only ids are reported, not blocking. A wrong id pairing still FAILs. An orphan log still blocks.
2. Gate B: canonical positions are G, F, C (and the Guard, Forward, Center groups). PG, SG, SF, PF are source labels and are no longer checked. No threshold was lowered.
3. London Lions: the resolver holds any player from ESPN team 134478. They are not added to the NBA table.
4. Queue: 182 stale rows removed from dev `unresolved_players`. Each matched an existing player by id and name. Audit file: `backend/data/audit_unresolved_stale_nba_20261112.csv` (local, not committed). No player or log was deleted. 30 NBA rows remain: KJ Martin (2, name alias), Jae Crowder and Quincy Acy (2 owners each), 15 London, Maxwell Lewis, 10 blank keys. Prod queue is unchanged.
