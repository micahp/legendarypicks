# Historical Madden ratings: validation status and research report (2026-10-23)

## Status

- **Dataset: strict audit passes; cross-check still open.** The audit passes 29 checks, waives 3 accepted
  exceptions and fails 0 (exit 0). The League Station cross-check was last run on the 03:36 bundle and fails on
  474 rows with no same-release match. That result is not waived.
- **Training: not run.** Blocked by three things: the cross-check gap, the source-rights assessment (skipped at your
  instruction), and no release verified as a launch-day snapshot (snapshot status is `unverified` for every release).
- **Model feasibility: not assessed.** It depends on the three blockers above.
- **Gridiron Physics ratings: unchanged.**

Archive reviewed: `/root/nfl-ratings-data/madden_ratings_1992-2027.zip`, sha256
`dc854cd21bf06f7c265ea8330477b353bd7491f41479edfa4f332f7a1e3eb842` (04:06 local, 2026-10-23). Earlier bundles
(`a12eb4…`, `642777…`, `9bfd71…`) are superseded. Ratings and published team values are identical across the
03:36, 03:58 and 04:06 bundles.

## 1. Bundle history

| Bundle | Change |
|---|---|
| `a12eb4…` (02:41) | 70 columns. Team blanks, 2027 at 30 teams, malformed names corrected in the producer's build |
| `642777…` (03:36) | 71 columns with `value_flags` and `out/source_limits.json`. 129 blank team cells filled (2027 Giants and Jets; free-agent `fa` rows). No rating changed |
| `9bfd71…` (03:58) | 73 columns: added `team_inferred` (93 rows) and `team_inferred_ambiguous` (20 rows) |
| `dc854c…` (04:06) | `team_inferred` withdrawn: 71 columns. Signal file carries a career-team warning. Register no longer points consumers at the inferred field |

Withdrawal reason (producer, and confirmed here): `team_inferred` took a player's career team and filled blank
cells with it. It was wrong for mid-career moves. The Binn case: the 2011 depth chart places him at Denver, while the
site files him under San Diego for his whole career. Of the 6 inferred teams that could be checked against NFL
depth-chart data, 2 agreed and 4 disagreed.

## 2. Audit: 29 pass, 3 waived, 0 fail

Accepted exceptions are in `docs/research/madden-audit-exceptions.json`. Each waiver is bound to the measured values
it was accepted for. If a rebuild changes them, the check fails again.

| Waived check | Measured | Accepted by |
|---|---|---|
| `attr.range_0_99` | 11 cells at 100, all Madden 1997; `value_flags` lists the same cells | user, 2026-10-23 |
| `team.no_blank` | 325 blank rows, all `player_page`, all with ratings; 324 sole rows per player-release, 1 shared (Mike Williams 2013) | user, 2026-10-23 (re-accepted at 325) |
| `presence.no_collapse_vs_neighbours` | 2010 and 2012 attribute density; Stafford 2010 player page has 12 populated cells | user, 2026-10-23 |

Passing checks that cover the bundle changes:

- `team_inferred.withdrawn`: the column is absent, the signal file carries the career-team warning, and the register
  does not refer to the inferred field.
- `register.counts_match_rows`: the register's published counts match the rows (blank teams, free-agent rows,
  out-of-range cells, duplicate player-releases, 2027 franchises, 2027 teamless rows).
- `spec.column_count` and `readme.column_count`: both state 71 columns, matching the file.
- `zip.by_year_matches_long`: all 36 year slices equal the long CSV.

Other passing checks: the documented key `(player_id, madden_release, dupe_seq)` is unique; OVR counts (58,345
present; 50,203 EA-published; 8,142 calculated for 1992-1996 and 1998-2000); no malformed names; franchise count 32
for 2003-2027 (`fa` is a free-agent marker, not a franchise); coverage counts; CSV-vs-SQLite match.

Not run: the producer's scripts shipped in the archive (`audit_bundle.py`, `verify_blanks.py`, `verify_evidence.py`,
`harvest_blank_signals.py`, `build_*`). Reading them is permitted; running them is not, since the archive is untrusted
input. The producer reports they pass from a clean extraction.

## 3. Attribute crosswalk: 35 of 35 Gridiron ratings covered

Full table: `docs/research/madden-attribute-crosswalk.csv`, built by `scripts/madden/attribute_crosswalk.py`.

- 34 Gridiron ratings are mapped directly, by exact or renamed source column. RET is mapped only partially, from KRN
  (kick returns).
- Route-running (SRR, MRR, DRR), the run and pass blocking splits (RBP, RBF, PBP, PBF) and the accuracy depth columns
  (TAS, TAM, TAD) are not combined into any Gridiron rating.
- PRC and POW carry name-level meanings, not checked against a publisher glossary.

### TAC versus THA: not mapped

| Test | Result |
|---|---|
| TAC and THA on the same row | 0 rows |
| TAC against mean(TAS, TAM, TAD) | r = 0.904, but TAC runs 12.8 points above the mean on average |
| Exact TAC equal to TAS, TAM or TAD | 2.7% to 4.9% |
| TAC in 2012 | 124 cells: QB 66, K 31, P 25, other 2 |
| TAC presence by era | populated in 1992-2018, not only 1992-2004 |
| THA against mean(TAS, TAM, TAD), team-page rows | 55 rows, r = 0.876, offset +1.2 |

THA tracks the depth average on the team pages. TAC sits on a different scale and carries kicker and punter values, so
mapping it to THA would force the crosswalk. TAC stays unmapped.

## 4. Identity

Tiers from `scripts/madden/identity_crosswalk.py`, built on the earlier bundle. Names are unchanged across bundles
(`identity.name_is_person_only` passes with 0 malformed names).

| Tier | Players |
|---|---|
| high: unique NFL name and position match | 11,237 |
| review: position mismatch | 192 |
| review: homonym, position resolved | 717 |
| review: homonym, unresolved | 251 |
| review: shared gsis | 4 |
| unresolved: no NFL name match | 169 |

Precision proxy (`scripts/madden/identity_precision_check.py`): for 24,486 high-tier player-seasons in 2013-2025,
matched players appear in the snap-count table 87.4% of the time, against 43.0% for shuffled pairings. That gap is a
signal, not a precision estimate.

Blank-team rows and identity: 52 of the 325 blank rows have no high-tier identity link. Only 7 can be placed from local
NFL data (2012 label, depth chart). For the rest, the local database has no team source for their season: depth charts
start in 2010 and snap counts in 2013, and most blank rows fall in seasons 2004-2008.

## 5. Leakage audit

Release dates and sources are in `docs/research/MADDEN-PUBLICATION-EVIDENCE-2026-10-23.md`.

- **Release dates** are verified from the Wikipedia article for 2000, 2005 (year only), 2009-2021, 2026 and 2027. They
  are missing for 1992-1999 and 2022-2024. The 2025 label conflicts: "early September 2024" against an Aug 16, 2024
  snippet.
- **Post-launch updates** are confirmed for Madden 26 and Madden 27 by Operation Sports (opened) and Yahoo Sports
  (opened, dated 2026-09-18).
- **Update test** (`scripts/madden/publication_update_test.py`): of 29 reported changes, the 2027 archive matches the old
  value for 18, the new value for 0, neither for 6, and 5 players are absent. The archive does not show the 18
  September update for the players it covers.
- **Calculated OVR**: 8,142 rows (1992-1996, 1998-2000) carry a site-computed overall, not an EA rating. Any model
  that treats OVR as an EA value must exclude them.
- **Within-release stints**: 40 player-releases have two or more rows, and all 40 differ in attributes within the same
  release. A value that changes inside one release is a leakage question, not a team-change artifact. It is not
  explained yet.
- **Rule**: a row labelled L covers season S = L-1 and is pregame-eligible only if its release date is before season S
  kickoff and its snapshot is verified as launch-day. No release is verified, so none is pregame-eligible.

## 6. Training-ready schema (draft; no training data built)

Built in the derived directory (`/root/nfl-ratings-data/derived-v6/normalized_ratings.csv`), one row per source row.

| Column | Meaning |
|---|---|
| `row_id`, `player_id`, `player_name`, `slug` | source identity |
| `madden_release`, `nfl_season`, `season_source` | label; season = label - 1; `derived_release_minus_1` where the source season is blank |
| `dupe_seq`, `key_duplicate` | stint sequence; flag for rows in a multi-row player-release |
| `team_raw`, `team_norm`, `team_missing` | published team; lowercased; blank flag. `fa` is a free-agent marker, not a team |
| `POS`, `pos_primary`, `pos_group` | Madden position; primary token; group |
| `source`, `site_calculated`, `value_flags`, `ovr_present` | page type; OVR computed by the site; cells outside 0-99; OVR present |
| `attr_present_count` | non-blank attribute cells in the row |
| 60 attribute columns | source ratings, as published |

Planned, not yet built: `identity_tier` and `gsis_id` (homonym review), `release_date` and `release_date_status`,
`snapshot_status` (`unverified`, `launch_verified`, `post_update`), `pregame_eligible`, `ovr_source` (`EA`,
`site_calculated`, `none`), and the NFL production, draft and combine joins. Season team for blank rows is not planned
in the schema; the register advises joining on `player_id`.

## 7. Source rights

**Not assessed**, as you instructed. Until it is, the archive stays isolated, and nothing derived from it goes into a
commercially intended model. The League Station preview, used only for validation, carries its own licence terms:
personal and non-commercial use, and no automated extraction.

## 8. Model feasibility

**Not run.** The blockers in Status all apply.

## 9. Open items

1. **League Station cross-check: 474 rows.** Last run on the 03:36 bundle. Re-run on the current bundle, then decide
   whether the gap is a documented source difference or a coverage gap to fix.
2. **The `fa` marker** is a team value in 23 rows. Decide whether it stays as a team slug or moves to a separate flag.
3. **Stafford's 2010 team-page value** (10 cells) is not in the archive and cannot be checked here.
4. **Within-release stints**: confirm whether the rating values legitimately differ for the 40 stint pairs.
5. **Exact snapshot dates** for each release, so the leakage rule can be applied.
6. **Merge reconciliation**: the producer's spec edits on `dev` and this branch's spec correction still need a manual
   merge.

## Commits

- `3471b583`: audit scripts and crosswalks
- `18c397cf`: preliminary QA checkpoint with strict failures
- `a4b13713`: publication-date evidence and the update test
- `dd629f62`: rerun on the first updated bundle, spec correction, report
- `1a5be11d`: rerun on the rebuilt bundle, corrected TAC figures, updated report
- `24262b65`: accepted exceptions bound to measured values
- `16325b16`: 03:36 bundle and the register cross-check
- `f0f5f0bd`: 03:58 bundle with team_inferred bookkeeping
- `318fc95a`: 04:06 bundle; team.no_blank re-accepted at 325; this report
