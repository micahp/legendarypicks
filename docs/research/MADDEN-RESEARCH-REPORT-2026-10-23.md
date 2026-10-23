# Historical Madden ratings: validation status and research report (2026-10-23)

## Status

- **Dataset: not validated, one audit failure.** The strict audit passes 28 checks, waives 2 accepted exceptions
  and fails 1: `team.no_blank`, now 325 rows, which no longer matches the 454 that was accepted. Re-accepting it is
  a decision for you.
- **Cross-check:** the League Station comparison was not re-run on this bundle in this pass. Its last result
  (474 rows with no same-release match) is recorded in `docs/research/data/madden-leaguestation-crosscheck.json`
  and is not waived.
- **Training: not run.** Blocked by three things: the dataset is not validated, the source-rights assessment was
  skipped at your instruction, and no release is verified as a launch-day snapshot.
- **Gridiron Physics ratings: unchanged.**

Archive reviewed: `/root/nfl-ratings-data/madden_ratings_1992-2027.zip`, sha256
`642777736edf9edc791c51207f1781f445166ac8ba463e1f7e23b8ef4726e758` (03:36 local, 2026-10-23). Previous bundles:
`2d0382…` and `a12eb4…`, both superseded.

## 1. This bundle: what changed and what was checked

Schema: 71 columns. `dupe_seq` and `site_calculated` were already present. `value_flags` is new and sits in the
identity block. The bundle also ships `out/source_limits.json`, a register of known limits. That file is treated as
data and was not run. `source_limits.py` is also in the archive, and it was not executed.

| Claim | Measured | Result |
|---|---|---|
| 71 columns, 58,743 rows | 71; 58,743 | confirmed |
| `value_flags` on 10 rows, 11 cells at 100, all 1997 | 10 rows, 11 cells, all 1997 (`TAK=100`, `CTH=100`, ...) | confirmed |
| Register: 325 blank teams (324 sole rows, 1 shared) | 325 blank; the shared row is Mike Williams 2013 | confirmed |
| Register: 23 free-agent rows | 23 rows with team `fa` | confirmed |
| Register: 2027 complete, 32 franchises, no teamless 2027 rows | 32 franchises in 2027; 0 blank 2027 rows | confirmed. This replaces the earlier "30 teams" finding |
| Register: 40 duplicate player-releases | 40 | confirmed |
| Ratings unchanged from the previous bundle | 0 of 60 attribute cells differ across 58,743 rows | confirmed |
| 129 rows that were blank now carry a team | 129 rows changed from blank: 2027 Giants and Jets rows, plus `fa` rows | confirmed; source of the new values not verified here |
| Mike Williams 2013: blank 78 OVR, Seahawks 76 OVR | `''` 78 and `seahawks` 76 | confirmed |

Team agreement with the snapshot, for the 512 starters matched to Madden 27: on this bundle 509 agree, none are blank,
and 3 disagree. Kayshon Boutte (2027 row NE, snapshot HOU) and Atonio Mafi (LV, snapshot TEN) were already on the list
under the previous bundle. Lucas Patrick is new: his 2027 row is now NYG, and the snapshot has him at WSH. That row was
blank before, so the newly filled team values can conflict with the snapshot. The 129 changed rows were not checked
against an independent source beyond the snapshot.

## 2. Audit: 28 pass, 2 waived, 1 fail

Accepted exceptions are in `docs/research/madden-audit-exceptions.json`. Each waiver is bound to the measured values it
was accepted for.

| Check | Status | Note |
|---|---|---|
| `attr.range_0_99` | waived | 11 cells at 100, all 1997. The bundle's `value_flags` lists the same cells |
| `team.no_blank` | **fail** | 325 blank rows, not 454. The waiver does not match; re-acceptance needed |
| `presence.no_collapse_vs_neighbours` | waived | 2010 and 2012. Stafford's 2010 player page has 12 populated cells |

Newly passing, and what the checks now cover:

- `register.counts_match_rows`: six counts in the archive's own register are compared with the rows: blank teams,
  free-agent rows, out-of-range cells, duplicate player-releases, 2027 franchises and 2027 teamless rows. All match.
- `spec.column_count`: now checks every column count stated in the spec, not only one wording. The spec says 71.
- `team.32_franchises_2003_2027`: counts franchise slugs only. `fa` is a free-agent marker, not a team. Under the
  earlier wording, 2003 looked like it had 33 teams because of `fa`.
- The 2027 waiver is removed. It no longer applies: 2027 now has 32 franchises.

Other passing checks: schema and identity columns (11), the documented key `(player_id, madden_release, dupe_seq)`,
the stint sequence, same-team stints (0), malformed names (0), OVR counts (58,345 present; 50,203 EA-published;
8,142 calculated), the by-year slices, team casing, coverage counts, and the CSV-vs-SQLite match.

## 3. Attribute crosswalk: 35 of 35 Gridiron ratings covered

Full table: `docs/research/madden-attribute-crosswalk.csv`, built by `scripts/madden/attribute_crosswalk.py`.

- 34 Gridiron ratings are mapped directly, by exact or renamed source column. RET is mapped only partially, from KRN
  (kick returns), which is not the same measurement.
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

Identity tiers were built from the earlier bundle. Names are unchanged in this bundle (`identity.name_is_person_only`
passes with 0 malformed names), so the tiers still apply.

| Tier | Players |
|---|---|
| high: unique NFL name and position match | 11,237 |
| review: position mismatch | 192 |
| review: homonym, position resolved | 717 |
| review: homonym, unresolved | 251 |
| review: shared gsis | 4 |
| unresolved: no NFL name match | 169 |

Precision proxy (`scripts/madden/identity_precision_check.py`): for 24,486 high-tier player-seasons in 2013-2025,
matched players appear in the snap-count table 87.4% of the time, against 43.0% for shuffled pairings. The gap is a
signal, not a precision estimate.

## 5. Leakage audit

Release dates and sources are in `docs/research/MADDEN-PUBLICATION-EVIDENCE-2026-10-23.md`.

- **Release dates** are verified from the Wikipedia article for 2000, 2005 (year only), 2009-2021, 2026 and 2027. They
  are missing for 1992-1999 and 2022-2024. The 2025 label conflicts: "early September 2024" against an Aug 16, 2024
  snippet.
- **Post-launch updates** are confirmed for Madden 26 and Madden 27 by Operation Sports (opened) and Yahoo Sports
  (opened, dated 2026-09-18).
- **Update test** (`scripts/madden/publication_update_test.py`): of 29 reported changes, the 2027 archive matches the old
  value for 18, the new value for 0, neither for 6, and 5 players are absent. The archive does not show the 18 September
  update for the players it covers.
- **Calculated OVR**: 8,142 rows (1992-1996, 1998-2000) carry a site-computed overall, not an EA rating. Any model that
  treats OVR as an EA value must exclude them.
- **Within-release stints**: 40 player-releases have two or more rows, and all 40 differ in attributes within the same
  release. A value that changes inside one release is a leakage question, not a team-change artifact. It is not
  explained yet.
- **Rule**: a row labelled L covers season S = L-1 and is pregame-eligible only if its release date is before season S
  kickoff and its snapshot is verified as launch-day. Snapshot status is `unverified` for every release, so no release
  is pregame-eligible.

## 6. Training-ready schema (draft; no training data built)

Built in the derived directory (`/root/nfl-ratings-data/derived-v4/normalized_ratings.csv`), one row per source row. This
audit's normalized output carries the identity block, and `value_flags` is in the identity block of the source.

| Column | Meaning |
|---|---|
| `row_id`, `player_id`, `player_name`, `slug` | source identity |
| `madden_release`, `nfl_season`, `season_source` | label; season = label - 1; `derived_release_minus_1` where the source season is blank |
| `dupe_seq`, `key_duplicate` | stint sequence; flag for rows in a multi-row player-release |
| `team_raw`, `team_norm`, `team_missing` | team as published; lowercased; blank flag. `fa` means free agent, not a team |
| `POS`, `pos_primary`, `pos_group` | Madden position; primary token; group |
| `source`, `site_calculated`, `value_flags`, `ovr_present` | page type; OVR computed by the site; cells outside 0-99; OVR present |
| `attr_present_count` | non-blank attribute cells in the row |
| 60 attribute columns | source ratings, as published |

Planned, not yet built: `identity_tier` and `gsis_id` (homonym review), `release_date` and `release_date_status`,
`snapshot_status` (`unverified`, `launch_verified`, `post_update`), `pregame_eligible`, `ovr_source` (`EA`,
`site_calculated`, `none`), and the NFL production, draft and combine joins.

## 7. Source rights

**Not assessed**, as you instructed. Until it is, the archive stays isolated, and nothing derived from it goes into a
commercially intended model. The League Station preview, used only for validation, carries its own licence terms:
personal and non-commercial use, and no automated extraction.

## 8. Model feasibility

**Not run.** The blockers in Status all apply.

## 9. Open items

1. **Re-accept or reject `team.no_blank` at 325 rows.** The register says these are rows where no team exists on the
   site. Its explanation is consistent with the data, but the 129 rows that changed were not checked independently.
2. **The free-agent marker `fa`** is now a team value in 23 rows. Decide whether to keep it as a team slug or to set
   those rows to blank with a separate flag.
3. **Stafford's 2010 team-page value** (10 cells) is not in the archive and cannot be checked here.
4. **League Station cross-check** was not re-run on this bundle. Its last result (474 rows) stands.
5. **Within-release stints**: confirm whether the rating values legitimately differ for the 40 stint pairs.
6. **Exact snapshot dates** for each release, so the leakage rule can be applied.
7. **Merge reconciliation**: the producer's spec edits on `dev` and this branch's spec correction still need a manual merge.

## Commits

- `3471b583`: audit scripts and crosswalks
- `18c397cf`: preliminary QA checkpoint with strict failures
- `a4b13713`: publication-date evidence and the update test
- `dd629f62`: rerun on the first updated bundle, spec correction, report
- `1a5be11d`: rerun on the rebuilt bundle, corrected TAC figures, updated report
- `24262b65`: accepted exceptions bound to measured values
- this commit: the 03:36 bundle, the register cross-check, the franchise-only team check, and the report
