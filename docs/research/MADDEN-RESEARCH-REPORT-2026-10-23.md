# Historical Madden ratings: validation status and research report (2026-10-23)

## Status

- **Dataset: not validated.** The strict audit passes 26 checks, waives 4 accepted exceptions and fails 0.
  The League Station cross-check still fails on 474 rows with no same-release match. That failure is not
  waived. A waiver applies only to the exact measured values it was accepted for (section 2).
- **Training: not run.** Blocked by three things: the dataset is not validated, the source-rights assessment
  was skipped at your instruction, and no release is verified as a launch-day snapshot.
- **Model feasibility: not assessed.** It depends on the three blockers above.
- **Gridiron Physics ratings: unchanged.**

Archive reviewed: `/root/nfl-ratings-data/madden_ratings_1992-2027.zip`, sha256
`a12eb4d90a7886bdbb39554ac445e93a5af52700e196a919d2dac201a95f2958` (rebuilt 02:41, 2026-10-23).

## 1. Producer's claims: checked against the archive

Rebuild, from the earlier message:

| Claim | Measured | Result |
|---|---|---|
| 70 columns; README and repo spec say 70 | 70; both agree | confirmed |
| Mike Williams 2013: blank team 78 OVR, Seahawks 76 OVR | rows `''` 78 and `seahawks` 76 | confirmed |
| 454 blank teams; 106 of them are 2027 | 454; 2027 has 106 | confirmed |
| 0 mixed-case team slugs | 0 | confirmed |
| 0 stale zip entries | 36 of 36 `by_year` files equal the long-CSV slice | confirmed |
| 0 of 60 attribute-count disagreements | 60 of 60 | confirmed |
| 0 CSV-vs-SQLite cell differences | 0 across 58,743 rows | confirmed |
| 40 duplicate keys, all with distinct `dupe_seq` | 40 player-releases, `dupe_seq` 0..n-1 | confirmed |
| Jr. and hyphenated names survive | `Ken Norton Jr.`, `Devin Bush Sr.`, `Le-Lo Lang`, `Ki-Jana Carter` present | confirmed |
| 105 player IDs had junk names | 24 player-ID names changed between bundles | **not confirmed** |
| Identity join rises above 11,237 | high tier stays at 11,237 | **not confirmed** (section 4) |
| 33 slugs → 32 non-blank | 32 non-blank | confirmed |
| 2002: 31 teams; 32 from 2003 | 2002 has 31 teams | confirmed as measured |
| TAC is the site's generic accuracy label for 1992-2004 | TAC also populated for 2005-2018 | **incomplete** |

Follow-up message on the four documented failures:

| Claim | Measured | Result |
|---|---|---|
| 11 cells at 100 in 10 rows, all 1997 | 11 cells, 10 distinct rows, all 1997 | confirmed |
| 453 of the 454 blank rows are the only row for their player-release | 453 sole rows | confirmed |
| Giants and Jets account for the 2027 blank rows (60 players) | 60 of 106 blank 2027 rows had Giants or Jets in 2026. The other 46 are not explained | consistent; **46 open** |
| Stafford 2010 player page has 12 cells | 12 | confirmed. The team-page value (10 cells) is not in the archive, so unverified |
| 2010/2012 collapse is the source's shape | producer's HTML count, not re-read here | unverified |
| `value_flags` column and `out/source_limits.json` in this build | **not in this bundle.** The file's sha256 is unchanged and the zip has no `source_limits.json` and no `value_flags` column | **cannot verify** |

The `value_flags` and `source_limits.json` claims cannot be checked until the build that contains them is
placed at the archive path. The audit runs on the bundle above, which does not have them.

## 2. Audit: 26 pass, 4 waived, 0 fail

Accepted exceptions are in `docs/research/madden-audit-exceptions.json`. Each waiver is bound to the measured
values it was accepted for. If a rebuild changes them, the check fails again. A test with a wrong count
(453 instead of 454) confirmed the failure. Each waived check still prints as `WAIVED` with its reason.

| Waived check | Measured value it covers | What is verified here |
|---|---|---|
| `attr.range_0_99` | 11 cells equal 100, all 1997 | 11 cells in 10 rows, all 1997 |
| `team.no_blank` | 454 blank rows, all `player_page` | 453 are sole rows for their player-release |
| `team.32_franchises_2003_2027` | 2027 has 30 teams | 60 of 106 blank 2027 rows had Giants or Jets in 2026 |
| `presence.no_collapse_vs_neighbours` | 2010 and 2012 | Stafford 2010: 12 cells on the player page |

Passing, including the checks the rebuild touched: schema and README column count, the documented key, the
stint sequence, same-team stints (now 0), malformed names (now 0), OVR counts and calculated-flag values, the
by-year slices, team casing, coverage counts, and the CSV-vs-SQLite match.

Cross-check (`scripts/madden/crosscheck_leaguestation.py`, exit 1, not waived): 474 of 1,888 League Station rows
have no same-release archive match. 321 names exist under another release and 220 one release away. 154 names
do not appear in the archive at all, for example Benjamin Watson (rated 87 in Madden 08).

## 3. Attribute crosswalk: 35 of 35 Gridiron ratings covered

Full table: `docs/research/madden-attribute-crosswalk.csv`, built by `scripts/madden/attribute_crosswalk.py`.

- 34 Gridiron ratings are mapped directly, by exact or renamed source column. RET is mapped only partially,
  from KRN (kick returns), which is not the same measurement.
- Route-running (SRR, MRR, DRR), the run and pass blocking splits (RBP, RBF, PBP, PBF) and the individual
  accuracy depth columns (TAS, TAM, TAD) are not combined into any Gridiron rating.
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

THA tracks the depth average on the team pages. TAC sits on a different scale and carries kicker and punter
values, so mapping it to THA would force the crosswalk. TAC stays unmapped.

## 4. Identity

Tiers from `scripts/madden/identity_crosswalk.py` on the rebuilt names, matched on normalized name only:

| Tier | Players | Change from previous bundle |
|---|---|---|
| high: unique NFL name and position match | 11,237 | none |
| review: position mismatch | 192 | +1 |
| review: homonym, position resolved | 717 | +16 |
| review: homonym, unresolved | 251 | +7 |
| review: shared gsis | 4 | none |
| unresolved: no NFL name match | 169 | -24 |

The 24 names repaired in this bundle moved from unresolved into review tiers. None reached the high tier: each
now matches a shared NFL name, so it needs a team or position check before it can be accepted.

Precision proxy (`scripts/madden/identity_precision_check.py`, unchanged): for 24,486 high-tier player-seasons in
2013-2025, matched players appear in the snap-count table 87.4% of the time, against 43.0% for shuffled
pairings. The gap is a signal, not a precision estimate.

## 5. Leakage audit

Release dates, sources and test details are in `docs/research/MADDEN-PUBLICATION-EVIDENCE-2026-10-23.md`.

- **Release dates** are verified from the Wikipedia article for 2000, 2005 (year only), 2009-2021, 2026 and 2027.
  They are missing for 1992-1999 and 2022-2024. The 2025 label conflicts: "early September 2024" against an
  Aug 16, 2024 snippet.
- **Post-launch updates** are confirmed for Madden 26 and Madden 27 by Operation Sports (opened) and Yahoo Sports
  (opened, dated 2026-09-18).
- **Update test** (`scripts/madden/publication_update_test.py`, unchanged on this bundle): of 29 reported changes,
  the 2027 archive matches the old value for 18, the new value for 0, neither for 6, and 5 players are absent. The
  archive does not show the 18 September update for the players it covers. The producer reads this as consistent
  with a partial 2027 release, which I cannot check from this side.
- **Calculated OVR**: 8,142 rows (1992-1996, 1998-2000) carry a site-computed overall, not an EA rating. Any model
  that treats OVR as an EA value must exclude them.
- **Within-release stints**: 40 player-releases have two or more rows, and all 40 now differ by team. All 40 also
  differ in at least one attribute within the same release. A value that changes inside one release is a leakage
  question, not a team-change artifact. It is not explained yet.
- **Rule**: a row labelled L covers season S = L-1 and is pregame-eligible only if its release date is before season
  S kickoff and its snapshot is verified as launch-day. Snapshot status is `unverified` for every release, so no
  release is pregame-eligible.

## 6. Training-ready schema (draft; no training data built)

Built in the derived directory (`/root/nfl-ratings-data/derived-v3/normalized_ratings.csv`), one row per source row:

| Column | Meaning |
|---|---|
| `row_id`, `player_id`, `player_name`, `slug` | source identity (names repaired in this bundle; homonym matching still open) |
| `madden_release`, `nfl_season`, `season_source` | label; season = label - 1; `derived_release_minus_1` where the source season is blank |
| `dupe_seq`, `key_duplicate` | stint sequence; flag for rows in a multi-row player-release |
| `team_raw`, `team_norm`, `team_missing` | team as published; lowercased; blank flag |
| `POS`, `pos_primary`, `pos_group` | Madden position; primary token; group (QB, RB, WR, TE, OL, DL, LB, DB, K, P, ST) |
| `source`, `site_calculated`, `ovr_present` | page type; OVR computed by the site; OVR present |
| `attr_present_count` | non-blank attribute cells in the row |
| 60 attribute columns | source ratings, as published |

Planned, not yet built:

| Column | Depends on |
|---|---|
| `identity_tier`, `gsis_id` | homonym review for the 24 repaired names and the other homonyms |
| `release_date`, `release_date_status` | date sources for 1992-1999 and 2022-2025 |
| `snapshot_status` (`unverified`, `launch_verified`, `post_update`) | a per-release snapshot test; none exists yet |
| `pregame_eligible` | `snapshot_status` and release date |
| `ovr_source` (`EA`, `site_calculated`, `none`) | derived from `site_calculated` |
| `value_flags` | the build that contains it; not in this bundle |
| NFL production, draft and combine joins | identity resolution; not started |

## 7. Source rights

**Not assessed**, as you instructed. Until it is, the archive stays isolated, and nothing derived from it goes into a
commercially intended model. The League Station preview, used here only for validation, carries its own licence
terms: personal and non-commercial use, and no automated extraction. Its use stays validation-only until the rights
step is done.

## 8. Model feasibility

**Not run.** The three blockers in Status all apply. The historical-versus-simple-baseline comparison stays deferred
until the dataset passes validation and the rights are settled.

## 9. Open items

1. **Place the build that has `value_flags` and `out/source_limits.json`** at the archive path, or tell me where it
   is. The audit cannot check those claims on this bundle.
2. **46 blank 2027 rows not explained** by the Giants and Jets pages. Confirm whether they are also empty pages.
3. **Stafford 2010 team-page value** (10 cells). It is not in the archive, so it cannot be checked here.
4. **League Station cross-check: 474 rows.** Decide whether this is a source difference to document, or a coverage
   gap to fix. It is not waived.
5. **Homonym review**: the 24 repaired names and the other homonyms need a team or position check before they can be
   accepted as high-tier.
6. **Within-release stints**: confirm whether the rating values legitimately differ for the 40 stint pairs, and which
   snapshot each stint row came from.
7. **Exact snapshot dates** for each release, so the leakage rule can be applied.
8. **Merge reconciliation**: the producer pushed doc edits to `dev` at `7be1ed7f`, and this branch also corrects
   `docs/MADDEN-RATINGS-DATASET-1992-2027.md`. Those two edits will conflict on merge; resolve them by hand.

## Commits

- `3471b583`: audit scripts and crosswalks
- `18c397cf`: preliminary QA checkpoint with strict failures
- `a4b13713`: publication-date evidence and the update test
- `dd629f62`: rerun on the first updated bundle, spec correction, report
- `1a5be11d`: rerun on the rebuilt bundle, corrected TAC figures, updated report
- this commit: accepted exceptions with measured-value binding, the follow-up checks, and the report update
