# Historical Madden ratings: validation status and research report (2026-10-23)

## Status

- **Dataset: not validated.** The strict audit passes 23 checks and fails 7. The League Station
  cross-check fails on 475 rows with no same-release match. A failing check stays a failure until
  the archive passes it.
- **Training: not run.** Blocked by three things: the dataset is not validated, the source-rights
  assessment was skipped at your instruction, and no release is verified as a launch-day snapshot.
- **Model feasibility: not assessed.** It depends on the three blockers above.
- **Gridiron Physics ratings: unchanged.**

Archive reviewed: `/root/nfl-ratings-data/madden_ratings_1992-2027.zip`, sha256
`2d03823348b4c4e3c138e384eab19efb1644105aa4be7d2c7355ec4d2667d568` (updated 02:16, 2026-10-23).

## 1. Producer's changes: checked against the archive

| Claim | Measured | Result |
|---|---|---|
| OVR on 58,345 rows; 8,142 site-calculated (1992-1996, 1998-2000) | 58,345; 50,203 EA-published; 8,142 flagged `site_calculated = OVR`, only in those years | confirmed |
| `(player_id, madden_release, dupe_seq)` is unique | 0 duplicate keys; 40 player-releases with 2 rows, one with 3 | confirmed. The README's "0/1" note is incomplete: one key has `dupe_seq` 0, 1 and 2 |
| Team slugs lowercased, 0 mixed case | 0 slugs with two casings | confirmed |
| 453 rows with no team | 453 blank, all `player_page` | confirmed |
| "33 distinct slugs" | 32 non-blank slugs (33 only if blank is counted) | differs by one |
| coverage.json: 0 of 60 attribute counts disagree | 60 of 60 match | confirmed |
| CSV vs SQLite: 0 cell differences | 0 differences across 58,743 rows (compared in row order) | confirmed |
| zip vs out/: 0 stale entries | all 36 `by_year` slices equal the long-CSV slice (new check `zip.by_year_matches_long`) | confirmed |
| Live spot-check: 20 players, 84 seasons, 0 mismatches | not reproduced; no live fetch was made | unverified |
| "Team counts 32 from 2002" (2002 release) | 2002 has 31 teams; 32 from 2003 | the README's own claim is off by one release |

The README still says "× 73 columns" in its contents table. The file has 70, and the README's own
numbers say 70. That is a failing check (`readme.column_count`) until the README is corrected.

## 2. Audit: 23 pass, 7 fail

Failing (exit 1):

| Check | Measured |
|---|---|
| `readme.column_count` | README says 73; file and README numbers say 70 |
| `attr.range_0_99` | 11 cells equal to 100, all in 1997 (e.g. TAK, CTH, PBK, RBK, AWR) |
| `keys.stints_differ_by_team` | 1 player-release has two rows on one team: Mike Williams, 2013, seahawks, `dupe_seq` 0 and 1 |
| `team.no_blank` | 453 player-page rows with no team |
| `team.32_franchises_2003_2027` | 2027 has 30 teams; Giants and Jets are absent |
| `identity.name_is_person_only` | 24 player_ids (42 rows) carry position or team text in the name |
| `presence.no_collapse_vs_neighbours` | 2010: 12.2 cells per row vs 38.4 and 37.1 either side; 2012: 16.5 vs 37.1 and 37.6 |

Cross-check (`scripts/madden/crosscheck_leaguestation.py`, exit 1): 475 of 1,888 League Station rows
have no same-release archive match. 321 of those names exist under another release and 220 one
release away. 154 names do not appear in the archive at all, for example Benjamin Watson (rated 87
in Madden 08 on League Station).

## 3. Attribute crosswalk: 35 of 35 Gridiron ratings covered

Full table: `docs/research/madden-attribute-crosswalk.csv`. Built by
`scripts/madden/attribute_crosswalk.py`.

- 34 Gridiron ratings are mapped directly, by exact or renamed source column. RET is mapped only
  partially, from KRN (kick returns), which is not the same measurement.
- Route-running (SRR, MRR, DRR), run and pass blocking splits (RBP, RBF, PBP, PBF) and the
  individual throw-accuracy depth columns (TAS, TAM, TAD) are not combined into any Gridiron rating.
- Meanings are name-level for PRC and POW. They are not checked against a publisher glossary.

### TAC versus THA: not mapped

The earlier candidate (TAC to THA) fails on the archive:

| Test | Result |
|---|---|
| TAC and THA on the same row | 0 rows, out of 1,693 TAC cells |
| TAC against mean(TAS, TAM, TAD) | r = 0.904, but TAC runs 12.8 points above the mean on average |
| Exact TAC equal to TAS, TAM or TAD | 2.7% to 4.9% |
| TAC by POS in 2012 | 68 rows: QB 66, K 31, P 25 (counts overlap; rows are per player-release) |
| THA against mean(TAS, TAM, TAD), team-page rows | 55 rows, r = 0.876, offset +1.2 |

THA behaves like a throw-accuracy composite on the team pages. TAC does not. It sits on a different
scale and carries kicker and punter values, so mapping it to THA would be forcing the crosswalk. TAC
stays candidate-only and is not mapped.

## 4. Identity: reconciliation

Tiers from `scripts/madden/identity_crosswalk.py`, matched on normalized name only:

| Tier | Players |
|---|---|
| high: unique NFL name and position match | 11,237 |
| review: homonym, position resolved (one compatible) | 701 |
| review: homonym, unresolved | 244 |
| review: position mismatch | 191 |
| review: shared gsis | 4 |
| unresolved: no NFL name match | 193 |

Of the 193 unresolved, 24 are the malformed-name IDs. The other 169 have no name match.

Precision proxy (`scripts/madden/identity_precision_check.py`): for 24,486 high-tier player-seasons
in 2013-2025, matched players appear in the snap-count table 87.4% of the time. Shuffled pairings
appear 43.0% of the time. The gap is a signal, not a precision estimate.

Stripping the suffix from the 24 malformed names gives a unique NFL match for only one of them. The
rest are still homonyms. The names need repair at the source, and each homonym needs a team or
position check before it can be accepted.

## 5. Leakage audit

Release dates, sources and the test details are in `docs/research/MADDEN-PUBLICATION-EVIDENCE-2026-10-23.md`.
In summary:

- **Release dates** are verified from the Wikipedia article for 2000, 2005 (year only), 2009-2021,
  2026 and 2027. They are missing for 1992-1999 and 2022-2024. The 2025 label conflicts: "early
  September 2024" against an Aug 16, 2024 snippet.
- **Post-launch updates** are confirmed for Madden 26 and Madden 27 by Operation Sports (opened) and
  Yahoo Sports (opened, dated 2026-09-18).
- **Update test** (`scripts/madden/publication_update_test.py`): of 29 reported changes, the 2027 archive
  matches the old value for 18, the new value for 0, neither value for 6, and 5 players are absent.
  The archive does not show the 18 September update for the players it covers.
- **Calculated OVR**: 8,142 rows (1992-1996, 1998-2000) carry a site-computed overall, not an EA
  rating. Any model that treats OVR as an EA value must exclude them.
- **Within-release stints**: 40 player-releases have two or more rows, and all 40 differ in at least one
  attribute within the same release. A value that changes inside one release is a leakage question, not
  a team-change artifact. It is not explained yet.
- **Rule**: a row labelled L covers season S = L-1 and is pregame-eligible only if its release date is
  before season S kickoff and its snapshot is verified as launch-day. Snapshot status is `unverified`
  for every release, so no release is pregame-eligible.

## 6. Training-ready schema (draft; no training data built)

Built now, in the derived directory (`/root/nfl-ratings-data/derived-v2/normalized_ratings.csv`), one
row per source row:

| Column | Meaning |
|---|---|
| `row_id`, `player_id`, `player_name`, `slug` | source identity (names are still unrepaired) |
| `madden_release`, `nfl_season`, `season_source` | label; season = label - 1; `derived_release_minus_1` where the source season is blank |
| `dupe_seq`, `key_duplicate` | stint sequence; flag for rows in a multi-row player-release |
| `team_raw`, `team_norm`, `team_missing` | team as published; lowercased; blank flag |
| `POS`, `pos_primary`, `pos_group` | Madden position; primary token; group (QB, RB, WR, TE, OL, DL, LB, DB, K, P, ST) |
| `source`, `site_calculated`, `ovr_present` | page type; OVR computed by the site; OVR present |
| `attr_present_count` | non-blank attribute cells in the row |
| 60 attribute columns | source ratings, as published |

Planned, not yet built (each needs a dependency first):

| Column | Depends on |
|---|---|
| `identity_tier`, `gsis_id` | identity repair for the 24 malformed names; homonym review |
| `release_date`, `release_date_status` | date sources for 1992-1999, 2022-2025 |
| `snapshot_status` (`unverified`, `launch_verified`, `post_update`) | a per-release snapshot test; none exists yet |
| `pregame_eligible` | `snapshot_status` and release date |
| `ovr_source` (`EA`, `site_calculated`, `none`) | derived from `site_calculated` |
| NFL production, draft and combine joins | identity resolution; not started |

## 7. Source rights

**Not assessed**, as you instructed. Until it is, the archive stays isolated, and nothing derived
from it goes into a commercially intended model. The League Station preview, used here only for
validation, carries its own licence terms: personal and non-commercial use, and no automated
extraction. Its use stays validation-only until the rights step is done.

## 8. Model feasibility

**Not run.** The three blockers in Status all apply. The historical-versus-simple-baseline comparison
stays deferred until the dataset passes validation and the rights are settled.

## 9. Open items for the producer

1. Correct the README contents table from "× 73 columns" to 70.
2. Mike Williams 2013 (seahawks, two rows, `dupe_seq` 0 and 1): explain why one team has two rows.
3. The 40 within-release stint pairs: confirm whether the rating values legitimately differ, and
   which snapshot each stint row came from.
4. Repair the 24 malformed names (`Name POS - Team` and similar), and say which rows the change touches.
5. 453 blank-team rows: confirm they are truly unknown, not backfilled.
6. 2027 release: 30 teams. Giants and Jets are absent; 5 players checked in section 5 are absent too.
7. 1997: 11 cells equal to 100. Confirm whether the cap is real or a scrape artifact.
8. 2010 and 2012: player-page attribute presence collapses. Confirm the source template for those years.
9. Give the exact snapshot date for each release so the leakage rule can be applied.

## Commits

- `3471b583`: audit scripts and crosswalks
- `18c397cf`: preliminary QA checkpoint with strict failures
- `a4b13713`: publication-date evidence and the update test
- this commit: rerun on the updated archive, spec correction, final report
