# nflverse play-by-play: staged research extract for penalties and returns (2026-10-27)

Status: staged, research only. Not ingested into any database, and no team box score has been rebuilt from it yet.
Nothing in production changed.

## 1. What was staged

- **Source.** nflverse-data release `pbp`, one file per season, `play_by_play_<season>.parquet`
  (`https://github.com/nflverse/nflverse-data/releases/tag/pbp`). 2010 to 2026, 17 files.
- **Staging method.** Each raw file was downloaded to a scratch directory, hashed (sha256), read for 29 columns, and then
  deleted, so the disk was not filled. Only the extract and the manifest were kept.
- **Extract.** `/root/lp-snapshots/nfl-backfill-2026-10-27/extract/penalty_return_<season>.parquet`, 4.3 MB in total.
- **Manifest.** `/root/lp-snapshots/nfl-backfill-2026-10-27/manifest.json`. It holds the source URL, the raw byte count, the
  raw sha256, the row count, the extract sha256, the columns kept and missing, the licence basis and the attribution text.
- **Script.** `scripts/nfl_sequence/splits/stage_nflverse_pbp.py`. Validation: `validate_nflverse_penalty.py`.

Columns kept (29): game and play keys, season, season type, week, teams, posteam, defteam, play type, play deleted, touchdown,
fumble lost, safety, penalty flag, penalty type, penalty team, penalty player, penalty yards, first-down penalty, return team,
return yards, return touchdown, punt attempt, kickoff attempt, punt blocked, touchback, punt returner ID, kickoff returner ID.

Not in the release, so not stored: accepted or declined penalty status, and any other penalty outcome beyond flag, type,
yards and first-down. The 2025 file contains no FTN-prefixed columns. Any FTN-derived content would carry the CC BY-SA 4.0
attribution described in section 4.

## 2. Pinned hashes

| Season | Raw bytes | Rows | Raw sha256 (first 16) | Extract sha256 (first 16) |
|---|---|---|---|---|
| 2010 | 19,059,048 | 46,892 | d2ef9c4073197199 | 12ce263c0e3825c6 |
| 2011 | 19,117,830 | 47,448 | c54753b8137b88da | cf400c70f404c1da |
| 2012 | 19,322,039 | 47,834 | 447b90789104aac7 | 01e639da66f41088 |
| 2013 | 19,521,610 | 48,158 | f454605a1983b394 | df157a206f5a73cc |
| 2014 | 19,360,792 | 47,629 | 54c01408d8f0ff9e | 0d1342323fe398ef |
| 2015 | 19,545,842 | 48,122 | 01b5ae7d06633a2e | 47c80ef3185093dd |
| 2016 | 19,344,382 | 47,651 | 95eba04e2145e3c1 | 9879cc9549ffe872 |
| 2017 | 19,050,401 | 47,245 | 84eacd963c1fdd45 | 4442852aebf847de |
| 2018 | 19,072,097 | 47,109 | 2e6f2dce7c7ebd46 | 8ef4d262584bfa82 |
| 2019 | 19,119,729 | 47,260 | 60c3067017db2d28 | b58b69a53d7fbd17 |
| 2020 | 19,286,459 | 47,705 | 8889f5d8782b5c5d | 2327ecd8d310fb5b |
| 2021 | 20,249,925 | 49,922 | 333ad34378e5339d | 2351bd17c1cc2e50 |
| 2022 | 20,426,548 | 49,434 | 931121d8897779d7 | f02f1394726f25f4 |
| 2023 | 20,534,088 | 49,665 | bd3484731408def6 | 8c41b7db96bd6f67 |
| 2024 | 20,597,560 | 49,492 | 3fd2896bc0b911b6 | 788df1c6521c4de0 |
| 2025 | 20,337,029 | 48,771 | c6ecedd6d678cc37 | b2dba32e15decdc7 |
| 2026 | 7,976,267 | 18,738 | e52903f452ff02fe | 2b33cdec3c731b5f |

The full 64-character hashes are in the manifest.

## 3. Validation against the dev database

Where both sources cover a season (2015 to 2025), every regular-season and postseason team-game with a penalty was compared:
the number of flagged plays, the penalty yards by team, and the penalty first downs by team.

| Season | Team-game penalty rows compared, both sources | Flag counts matching | Yards matching | First-down penalties matching |
|---|---|---|---|---|
| 2015 to 2025 (each season) | 532 to 570 | 100% | 100% | 100% |

Every shared team-game agrees exactly. Team names are mapped LA to LAR and WAS to WSH, as in the team box builder.

Coverage in the extract (regular season):

- Penalty flag non-null for 96.9% to 97.0% of plays in every season. Penalty yards and first-down penalty are non-null for every flagged play.
- 2010 to 2014: 3,097 to 3,382 flagged plays a season. The dev database has no penalty table for these years.
- 2026: 1,570 flagged plays in 107 games. The dev database has no 2026 penalty flags (its `penalty` column is null for every 2026 play).
- Return yards are non-null for about 97% of plays in every season. Punt returner IDs are present for 2.9% to 3.9% of plays. Touchback is non-null for every play.

## 4. Licence basis and attribution

- **Basis.** The user's finding (2026-10-27) that the nflverse release terms permit this research use, and that FTN-derived content is under CC BY-SA 4.0.
  The nflverse-data repository README (699 bytes) contains no licence text, only a pointer. We therefore did not verify the terms against the repository ourselves. Earlier searches found the FTN charting data labelled CC-BY-SA 4.0, with credit to FTN Data via nflverse for 2023 onward, and the nflversedata package labelled CC BY 4.0.
- **Attribution to keep** (also in the manifest): "Play-by-play data from the nflverse project (nflverse-data releases). Please credit nflverse. FTN-derived fields, if any, are CC BY-SA 4.0 and need FTN Data credited through nflverse."
- **Scope.** Research use only. The extract is not redistributed and not ingested into production. If any derived product is shared outside the research, the attribution applies, and any FTN-derived fields keep the ShareAlike term.

## 5. What it changes, and what it does not yet change

Fixes available once the extract is used (not applied in this pass):

- **2010 to 2014 penalty yards and penalty first downs.** Currently null in the team box score (no source in the dev database). The extract supplies them.
- **2026 penalty flags, penalty yards and penalty first downs.** Currently null. The extract supplies them.
- **Punt and return fields.** Return yards, return touchdowns and punt returner IDs for all seasons. Staged, not integrated. They would let derived special-teams points and punt and return yards be checked against the play data.

Not changed in this pass:

- No team box score rebuild from the extract. The reviewer asked for validation before a rebuild, and validation is done for penalties (section 3). The rebuild would be a new store version (for example `team-box-2026-10-27-rev3`), with the previous versions kept.
- No effect on S1 or S2 (`NFL-S1-S2-RESULTS-2026-10-27.md`), which use only final scores, dates, kickoff, rest, travel and division.
- Accepted and declined penalty status is still unavailable from any source checked. First downs therefore keep their unresolved status (`NFL-RECONCILIATION-2026-10-27.md`).

## 6. Next steps

1. Build a team box score rev3 that reads penalty fields from the extract for 2010 to 2014 and 2026 (and keeps the dev database for 2015 to 2025, which matches exactly), then check the first-down and derived-points reconciliations.
2. Validate the return fields against the derived special-teams points on 2015 to 2025, and classify the remaining 180 derived-point mismatches.
3. Before any production use, a separate licence review for that use.
