# Madden ratings archive: preliminary QA (2026-10-23)

Archive: `/root/nfl-ratings-data/madden_ratings_1992-2027.zip`, the copy as delivered (not the
repaired archive). Reproduce with `scripts/madden/audit_madden_ratings.py`,
`scripts/madden/crosscheck_leaguestation.py`, `scripts/madden/identity_crosswalk.py`,
`scripts/madden/identity_precision_check.py` and `scripts/madden/attribute_crosswalk.py`.

These checks are deliberately strict. They stay failing until the corrected archive passes.
No defect below has been repaired or hidden.

## Audit: 9 failing checks (exit 1)

| Check | Measured | Expected |
|---|---|---|
| `shape.columns_match_spec` | 68 columns (8 identity + 60 attributes) | 73 per the spec doc |
| `coverage.attribute_counts` | 2 of 60 counts agree with `coverage.json`; OVR 58,743 there vs 50,203 in the CSV | agreement |
| `attr.range_0_99` | 11 cells equal to 100, all in 1997 (e.g. TAK, CTH, PBK, RBK, AWR) | 0-99 |
| `keys.player_release_unique` | 40 `(player_id, madden_release)` keys, 81 rows; all 40 differ by team and by ratings | unique keys |
| `team.case_consistent` | 31 slugs in two casings (e.g. `Patriots` / `patriots`) | one casing |
| `team.no_blank` | 454 player-page rows with blank team | no blanks |
| `team.32_franchises_2003_2027` | 2027 has 30 teams (partial release) | 32 |
| `identity.name_is_person_only` | 24 player_ids (42 rows) carry position or team text in `player_name` | person name only |
| `presence.no_collapse_vs_neighbours` | 1998 (4.4 cells/row vs 10.7/9.7), 2010 (12.2 vs 38.4/37.1), 2012 (16.5 vs 37.1/37.6) | no collapse |

Passing: row count (58,743), per-release row counts, the SQLite copy matching the CSV cell for cell,
12,570 players, OVR present for 50,203 rows (the README figure), no row with OVR, SPEED and AWR all
blank, team-page rows (7,387), position vocabulary fully mapped, and no player_id with two names.

Correction to an earlier figure: an earlier broad name pattern reported 77 player_ids (295 rows)
with position or team text. It matched standalone letters such as the "C" in "C.J. Jones". The
strict pattern above is the one in the script, and it gives 24 player_ids (42 rows).

## League Station cross-check: failing on coverage (exit 1)

- 475 League Station rows (26 editions) have no same-release archive match.
- Of those, 321 names exist in the archive under another release, and 220 exist one release away.
- 154 names do not appear in the archive under any release, for example Benjamin Watson (rated 87
  in Madden 08 on League Station). Raymond Ventrone is also absent.
- Among matched players, attributes agree 77-98% exactly, with mean absolute differences around one
  point. The preview covers only top-rated players, so this is agreement on a biased subset. It does
  not establish that either source matches EA's values.
- `madden-25-2013.csv` is Madden 14, labelled 2014 in the archive. Overlap decides this: 54 matches
  for 2014 against 43 for 2013.

## Identity: preliminary (name plus NFL position, no team or season check)

- 11,237 high-tier, 701 position-resolved homonyms, 244 homonyms needing review, 191 position
  mismatches, 4 shared-gsis collisions, 193 unresolved, out of 12,570 player_ids.
- Precision proxy: for 2013-2025 rated seasons, matched players appear in the snap-count table 87.4%
  of the time, against 43.0% for shuffled pairings. This is a gap, not a precision figure.
- Identity coverage by release is 86-94% high tier. Those rates may move once the malformed names
  are fixed.

## Attribute crosswalk: 35 of 35 Gridiron ratings covered

- TAC to THA is a candidate only. Its agreement with the mean of TAS/TAM/TAD gives r = 0.904, but a
  mean absolute difference of 13.6 against an agreement limit of 5. That limit is my own choice, not a
  published standard. It fails, so THA is not mapped from TAC. The check is rerun on the repaired
  archive, and the mapping is not forced.
- Route-running (SRR/MRR/DRR), run blocking (RBP/RBF) and pass blocking (PBP/PBF) are not combined
  into a Gridiron rating.

## Acceptance for the repaired archive

The final dataset is accepted only if all nine audit checks pass, the League Station coverage check
passes (or each absent row is explained by a documented source difference), and the identity
malformed-name check passes. Anything still failing is reported as a failure, not dropped from the
checks. The 2027 partial release is also a failure, not a warning, until the site publishes all 32
teams.
