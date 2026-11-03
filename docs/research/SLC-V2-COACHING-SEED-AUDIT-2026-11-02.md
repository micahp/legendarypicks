# Coaching seed audit (SLC v2, P1), 2026-11-02

Status: audit of a starter workbook. Research only. The workbook is not a verified per-game coaching ledger, and its own read-me says so. Nothing here is a model input yet.

Input: `doc_9b9edbc441c2_nfl_coaching_2025_2026_research_seed.xlsx`, SHA-256 `9be1238dc8ea9455b5993efb73667f1f3206920ef449dadfc536da54ae0ce56e`, 20,316 bytes. The file is in the Hermes document cache, not in the repository.

Holdout note. Two sample rows printed while I read the header of `Verified Role Changes` were 2026 rows (DEN play-caller stints). I did not use them in any analysis. The 2026 staff rows (32) are counted here and not read. This audit uses 2025 rows and the sheet structure only.

## 1. Sheets and counts

| Sheet | Rows | What it holds | Status in the file |
|---|---:|---|---|
| `2025-26 Staff Seed` | 64 (2025: 32, 2026: 32) | Head coach, OC, DC, and offensive and defensive play-caller columns per team-season | "Season directory seed; NOT game-level verified" (all 64) |
| `People Index` | 120 | Provisional person names with team-season roles | "Provisional name match; stable person ID and career tenure not yet verified" (all 120) |
| `Verified Role Changes` | 4 (2025: 2, 2026: 2) | Play-caller stints with week ranges and evidence URLs | Stated as verified; evidence is a team news page |
| `Integration Contract` | 8 entities | Intended schema: coach, staff_stint, playcalling_stint, game_staff, coaching_observation, coach_profile, evaluation, 2026 sealed boundary | Design only |
| `Sources and Read Me` | 2 columns | Purpose, scope, sources, caveats | Read in full |

## 2. 2025 content that could support P1

- **Staff directory, 2025 (32 teams).** HC, OC and DC per team, sourced to the drafthistory 2025 team-leaders page. I fetched that page separately; its 2025 coordinator list matches the seed's 2025 rows for the team I compared (ARI: Gannon, Petzing, Rallis). The page states no data source and says the staff are "as of the 2025 season start". Directory only.
- **Play-caller columns, 2025: 0 of 32 filled** for offense and for defense. No 2025 play-caller is recorded in the staff sheet.
- **Verified role changes, 2025 (Cleveland only, 2 rows).** Kevin Stefanski as offensive play-caller for weeks 1 to 9, then Tommy Rees for weeks 10 to 18. Evidence is a Cleveland Browns news page. This is the only 2025 play-calling split in the workbook, and the only candidate structural break for P1. The workbook does not verify it at game level.

## 3. What the workbook cannot support

- **2022 to 2024 coordinators and play-callers:** absent. The workbook covers 2025 and 2026 only.
- **Game-level assignments:** absent. The read-me says per-game stints must be backfilled before use.
- **Person identity:** the People Index names are provisional name matches. No stable person ID exists.
- **Play-calling responsibility from team output:** the read-me says observed output alone cannot establish who called each play, and warns against causal claims without verified responsibility.

## 4. Use in P1

- Head coach per game stays on the nflverse schedule, which covers 2010 to 2026 with no missing rows. That source is a published row, not a seed.
- Offensive and defensive coordinators: 2025 directory only, unverified. No development use before 2025.
- Play-caller: observed team tendencies are the primary P1 signal. The Cleveland 2025 split is a structural-break test case, not a verified ledger.
- Coaching changes are modelled as structural breaks in team tendencies, not as the head coach's personal calls.

## 5. Open items

1. The Cleveland 2025 role change needs a game-level check against observed play-calling (breaks at week 10).
2. Historical coordinators for 2022 to 2024: the nflverse schedule has no coordinator fields. A source remains open.
3. The drafthistory and gridironexperts pages are directory sources. The gridironexperts page returned no content on repeated fetches, so its 2026 list is unchecked.
4. SportsDataverse coach loaders (fetched from the docs pages named in the read-me; the earlier wiki and module checks did not find them):
   - `load_nfl_coach_tendencies` (ESPN release `espn_nfl_coach_tendencies`): one row per season, team and head coach, 2002 to 2026 published, 2005 thin. Season aggregates only, no per-game rows and no effective dates. `role` is always HC; coordinator rows are not published yet. Coaches are assigned game by game from the nflverse schedule home and away coach fields, so this is derived from the same source as our schedule column and is not an independent check on who coached.
   - `load_nfl_coach_careers`: one row per head coach, summed from the tendencies release, with `first_season` and `last_season` only. Not a per-season source.
   - The gridironexperts 2026 list returned no content on repeated fetches, so it is still unchecked.
