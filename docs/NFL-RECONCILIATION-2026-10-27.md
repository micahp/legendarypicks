# NFL reconciliation report: team box score, stadium capacity, attendance (2026-10-27)

Status: research, dev only. No production table, forecast, simulator default or frozen game-info snapshot is changed.
The 2026 season is the sealed holdout. Week 8 snapshots and their IDs are untouched.

Stores (outside the repo, rebuilt in this pass as new versioned files; the earlier files are kept for comparison):

| Store | Path | Schema |
|---|---|---|
| Team box score, revised | `/root/lp-snapshots/nfl-splits/team-box-2026-10-27-rev2/team_box.sqlite` | `lp-nfl-team-box-2` |
| Team splits, revised | `/root/lp-snapshots/nfl-splits/team-splits-2026-10-27-rev2/team_splits.sqlite` | `lp-nfl-team-splits-2` |
| Team box score, previous | `/root/lp-snapshots/nfl-splits/team-box-2026-10-27/team_box.sqlite` | `lp-nfl-team-box-1` |
| Team splits, previous | `/root/lp-snapshots/nfl-splits/team-splits-2026-10-27/team_splits.sqlite` | `lp-nfl-team-splits-1` |

Tests: 39 pass (`test_team_box.py` 6, `test_team_splits.py` 31 with the new capacity and attendance cases, `test_s0_baseline.py` 2).

## 1. Team box score: metric status

Each metric carries its definition, source, coverage and status. "Verified" means it reconciles to an independent source
at the stated rate and is safe for descriptive splits. "Provisional" means it reconciles well but has a known gap.
"Unresolved" means the definition or the source disagreement is not settled, so it must not be used as a model feature.

| Metric | Definition | Independent check | Coverage | Result | Status |
|---|---|---|---|---|---|
| Points against final score | Derived scoring events (section 3) | Schedule final score | 2010 to 2026 regular season | 8,376 of 8,564 exact (97.8%) | Schedule score authoritative. Derived points provisional |
| Passing yards | Yards on pass plays, sacks excluded | Player game logs | 2010 to 2026 | 8,563 of 8,564 (99.99%) | Verified |
| Net passing yards | Pass yards less sack yards | ESPN team box | 2025 | 543 of 544 (99.8%) | Verified |
| Passing attempts | Pass plays excluding sacks and two-point passes, spikes included | Player game logs | 2010 to 2026 | 8,560 of 8,564 (99.95%) | Verified |
| Rushing yards | Rush plays plus kneels | Player game logs | 2010 to 2026 | 8,539 of 8,564 (99.7%) | Verified |
| Rushing attempts | Rush plays plus QB kneels | Player game logs (carries) | 2010 to 2026 | 8,146 of 8,564 (95.1%) | Provisional. Section 4 |
| Carries | As above | nflverse team totals | 2025 to 2026 | 720 of 758 (95.0%) | Provisional |
| Turnovers | Interceptions plus fumbles lost | ESPN team box | 2025 | 523 of 544 (96.1%) | Provisional |
| Total offensive plays | Pass and run plays, kneels and spikes included | ESPN team box | 2025 | 442 of 544 (81.3%) | Unresolved. Section 4 |
| First downs | Gained distance or TD, plus penalty first downs | ESPN team box | 2025 | 366 of 544 (67.3%) | Unresolved. Section 4 |
| Total yards | Yards on pass and run plays | ESPN team box | 2025 | 490 of 544 (90.1%) | Unresolved (not yet diagnosed) |
| Penalty yards | Flagged penalty yards on the team | Penalty table | 2015 to 2025 only | Null outside those seasons | Verified where present |
| Possession seconds | Game clock at each drive start | None | 2010 to 2026 | Not validated | Unresolved |

Not stored and therefore null at all times: punt yards, return yards, accepted, declined and offsetting penalties.
The play data flags a penalty but does not record acceptance or decline (checked: `nfl_pbp_penalty` has no such column).

## 2. Fixes applied in this pass

| # | Problem | Fix | Effect (revised store against previous) |
|---|---|---|---|
| 1 | 2026 penalty yards were set to 0 where the penalty table has no rows | Null where the penalty table has no rows for the season (2026 and 2010 to 2014) | 214 team-games of 2026 moved from 0 to null |
| 2 | 2026 flagged penalties were 0 where the play data has no penalty flags | Null where the play data has no penalty flags for the season (2026) | 214 team-games moved from 0 to null |
| 3 | First downs excluded penalty first downs where the penalty table is absent, which understates them | Null where the penalty table is absent (2010 to 2014 and 2026) | 2,774 team-games moved from a value to null |
| 4 | Points per drive divided the team's total points by drives, so defensive and return touchdowns counted as offense | Points per drive = (schedule final score less points the derived events credit to defense and special teams) / drives. Null when that split is negative | 1,523 team-games changed. Mean among changed rows 2.53 to 1.86. 2 rows are null (inconsistent split) |
| 5 | A safety was counted on every play of its drive, because the series result repeats | Counted once per drive | Derived points now match the schedule in 8,170 of 8,350 comparable team-games (97.8%), up from 7,995 (95.7%). This is the only change to derived points |

Revision 3 (store `team-box-2026-10-27-rev3`) restores the penalty fields for 2010 to 2014 and 2026 from the validated nflverse extract. Fixes 1 to 3 above are therefore superseded for those seasons: penalty yards, flagged penalties and penalty first downs are populated there, and the nulls apply only where neither source covers a season (none now). Rev3 changes no value for 2015 to 2025 and leaves the reconciliation table unchanged.

Points per drive is now offensive points per drive. A defensive touchdown with its extra point no longer appears in the
offense's rate. Tests: `test_team_box.py` (penalty nulls, defensive and extra point, safety counted once).

## 3. Derived scoring

The derived total is the sum of: offensive touchdown 6, defensive or return touchdown 6 to the scoring team (with its
extra point), field goal 3, extra point 1, two-point 2, safety 2 to the defense once per drive. The schedule's final
score is authoritative in every output. Of the 180 remaining comparable mismatches, the causes are not yet classified.

## 4. Mismatch diagnostics (2025 unless stated)

Hypotheses were tested against the play data. Each one was either ruled out or left unverifiable from the stored fields.

- **Total offensive plays.** Ours minus ESPN: 0 in 442 games, +1 in 80, +2 in 17, +3 in 3, +4 in 1, -1 in 1.
  - Kneels and spikes: ruled out. Removing them makes the mismatch worse (ESPN already counts them).
  - Cause not found. Candidates: ESPN excludes some no-play or penalty-only events we count. Not verifiable here.
- **First downs.** Ours minus ESPN: 0 in 366 games, +1 in 131, +2 in 30, +3 in 9, +4 in 2, -1 in 6.
  - Penalty first downs: needed. Removing them moves most games below ESPN, so ESPN includes them.
  - Remaining +1 to +4: possibly declined penalties, which we credit as first downs. The stored data has no accepted or declined flag, so this cannot be confirmed or corrected. First downs stay unresolved, and the upper-bound caveat remains.
- **Rushing attempts.** From 2021 to 2026 the team-game matches exactly in 2,746 of 2,932 cases. Ours is one higher in 176, two higher in 9, and one lower in 1.
  - Not yet tested against kneels or scrambles. The kneel test above was run on total plays, not on rush attempts. Next step: compare the +1 cases with the team's QB kneels and scrambles in the play data.

## 5. Capacity: definitions and resolution

The capacity history is now a set of reconciled stadium-season pieces. Every row carries a status, a confidence and a
generated note with the measured evidence. Lookups use only statuses `ok` and `flagged`.

| Status | Meaning | Used in lookups |
|---|---|---|
| `ok` | No reported attendance above the figure, and the 2026 snapshot agrees within 2% if it covers 2026 | Yes |
| `flagged` | Used, with the reason: attendance above the figure in one covered season, or the 2026 snapshot differs by more than 2% | Yes |
| `contradicted` | Reported attendance above the figure by more than 2% in two or more covered seasons (2015 to 2025) | No |
| `excluded_text` | The source says the figure is not the permanent seating for these seasons | No |
| `unresolved` | No verified figure for the stadium-season. Left explicitly unknown | No |
| `undated` | A figure with no year range (kept for the venue comparison) | No |
| `no_figure` | The page states no NFL capacity (Los Angeles Memorial Coliseum) | No |

Tolerance (2%) is a choice made here, not a published standard. Reported attendance can exceed permanent seating, so one
season above a figure is treated as a conflict to flag, not as proof.

Counts after this pass: ok 141, flagged 4, contradicted 6, excluded_text 2, unresolved 3, undated 27, no_figure 1.

### Arrowhead Stadium

| Years | Figure | Status | Basis |
|---|---|---|---|
| 2010 to 2018 | 76,416 | ok | Wikipedia lists 76,416 from 2010 to present. Not confirmed by a season-specific source. Reported attendance 2015 to 2018 is consistent (peaks 76,404 to 77,550) |
| 2019 to 2021 | unknown | unresolved | No verified figure. Reported attendance peaks fall from 77,550 (2018) to 73,680 (2019). That suggests a change near 2019 but does not date it |
| 2022 | 72,936 | ok (confidence provisional) | Tennessee Titans game preview for the 6 Nov 2022 game at GEHA Field lists capacity 72,936. One game source. Reported attendance 2022 peaks at 73,586 (within 2%) |
| 2023 to 2025 | unknown | unresolved | 73,426 (2026 snapshot) could not be sourced in any search. Wikipedia and 2024 to 2025 coverage cite 76,416. Attendance peaks 73,611 to 73,754 |
| 2026 | unknown | unresolved | Snapshot 73,426, no established source. Wikipedia gives 69,045 for the 2026 World Cup configuration |

The reviewer-supplied figure of 73,426 for 2023 to 2025 and the 2018 Fact Book citation could not be confirmed in this pass.
Both are recorded as such. Treat the 2018 and 2010 to 2018 row as provisional.

### EverBank Stadium, 2026

Event capacity for the 2026 renovation season is 42,507, including 1,260 standing-room tickets (Jaguars 2026 stadium
update, Feb 2026; quoted in a search result, page not fetched in full). The row is `excluded_text`, because it is not
permanent seating. The stadium website's 42,465 is a documented source conflict that was not checked here. An Aug 2026
report of temporary seating added for 2026 is not yet checked, so 42,507 may change. The old 69,132 snapshot figure is not used for 2026.

### Snapshot against page: the 15 disagreements

The 2026 snapshot (30 venues) differs from the figure in effect for 2026 in 15 venues. Each is classified below. "Within 2%"
means no evidence picks a side.

| Venue | Snapshot | Figure in effect | Class | Note |
|---|---|---|---|---|
| M&T Bank Stadium | 71,008 | 70,745 | Date difference | 71,008 is the 2007 to 2020 figure |
| Raymond James Stadium | 65,890 | 69,218 (excluded from 2023) | Date difference | 65,890 is the 2013 to 2015 figure. 69,218 is the 2022 temporary-seat figure |
| EverBank Stadium | 69,132 | 42,507 (event, 2026) | Renovation and definition | Verified event capacity with standing room |
| Acrisure Stadium | 68,984 | 68,400 | Within 2% | One season above the figure (2025) |
| Cleveland Browns Stadium | 67,895 | 67,431 | Within 2% | Attendance peaks 1.1% above the figure |
| Lumen Field | 69,000 | 68,740 (undated) | Within 2% | Undated figure, not used |
| SoFi Stadium | 70,000 | 70,240 | Within 2% | Figure contradicted for 2021 onward by attendance, so not used in lookups |
| U.S. Bank Stadium | 66,655 | 66,202 (undated) | Within 2% | Undated figure, not used |
| Arrowhead Stadium | 73,426 | unknown | Unresolved conflict | Section above |
| Allegiant Stadium | 66,000 | 65,000 (undated) | Unresolved conflict | Undated |
| Gillette Stadium | 66,829 | 64,628 (2023 to 2026) | Unresolved conflict | 2023 to 2025 peak attendance 64,686 is consistent with the page figure |
| Hard Rock Stadium | 65,326 | 64,767 (contradicted) | Unresolved conflict | Attendance above the figure in seven seasons (peak 78,610). Not used in lookups |
| Lincoln Financial Field | 69,596 | 67,594 (undated) | Unresolved conflict | Undated. Page note also gives 68,324 for the 2026 World Cup only |
| Lucas Oil Stadium | 67,000 | 65,000 (undated) | Unresolved conflict | Attendance above 65,000 by more than 2% in six seasons. Undated, not used |
| Soldier Field | 62,500 | 63,000 (undated) | Unresolved conflict | Undated |

Counts: date difference 2, renovation and definition 1, within 2% 5, unresolved 7.

### Coverage impact

Dated capacity for tier A team-games, 2015 to 2026: 3,510 under the previous history, 2,470 under the revised one (-1,040).
Most of the loss is Arrowhead 2019 to 2021 and 2023 to 2026, the contradicted buildings (FedExField 2015 to 2020 and 2022 to 2024,
Hard Rock, State Farm from 2015, SoFi from 2021, EverBank 2018 to 2025, Raymond James from 2023) and the 2026 event
capacities. A stadium-season with no reconciled figure is `no_dated_capacity`. It is not filled from a neighbouring season.

## 6. Attendance: definitions and statuses

| Field | Definition | Use |
|---|---|---|
| `attendance_raw` | The count as the source reports it (ESPN scoreboard, post-game), before any exclusion | Audit only |
| `attendance_status` | `reported`: a positive count. `reported_zero`: the source reports 0. `suspect`: flagged in the database; value dropped. `missing`: no count in a collected season. `not_collected`: no source row (2010 to 2014 and 2026) | Retrospective |
| `attendance` | The count when status is `reported` or `reported_zero`; null otherwise | Retrospective |
| `attendance_bin`, `attendance_share_bin` | Built only when status is `reported` | Retrospective |
| Attendance share | Reported attendance divided by the dated capacity for the building and season. Only when that capacity has status `ok` or `flagged` | Retrospective |

Reported attendance is announced attendance. It is tickets distributed or counted, not turnstile entries, and it is not
physical crowd density. Turnstile attendance is not collected anywhere in the stores and is always null.

Counts, tier A team-games: reported 5,742; reported_zero 306 (all 2020, 153 games); suspect 8 (4 games); missing 0 for 2015
to 2025; not_collected 2,884 (2010 to 2014 and 2026). Previously zero was dropped as missing. A reported zero is now kept as zero.
Whether each 2020 zero is a verified crowd of zero is not established: the source reports 0, and that is all this pass records.

An attendance share above 100% is kept and binned as `100pct_plus`. It is a data-quality question to investigate, not an
error to remove. Existing examples come from standing-room and temporary seating.

## 7. Cutoff-safe queries

`team_box_query.py --before YYYY-MM-DD` restricts the situation games and both baselines to games whose game date is before
that date. The cutoff is day-level, so a game on the same day is excluded. Example, Buffalo dome games before 2024-09-01: 15
of 19 total. Box scores and scores are postgame results. The query does not make them pregame information. Publication times
for weather, officials and availability are not stored.

## 8. Open items

1. Arrowhead 2019 to 2026 and EverBank 2026 need a primary source. Candidates: the club's media guides, NFL Record and Fact Book editions for 2019 to 2025, and the stadium operator.
2. First downs and total plays need the declined-penalty and ESPN-definition question answered from a source that records acceptance.
3. Rushing attempts need the exact nflverse carries definition (QB scrambles and kneels) checked against a published file.
4. Total yards (90.1% against ESPN, 2025) is not yet diagnosed.
5. Derived points: 180 remaining mismatches to classify.
6. nflverse play-by-play backfill for punt, return and penalty detail: blocked until the license of that release is read from the nflverse-data repository (see the S0 audit).
