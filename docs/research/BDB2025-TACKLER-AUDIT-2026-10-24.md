# 2022-season Big Data Bowl tracking: tackler identity and event alignment (2026-10-24)

**Status:** audit and handoff. Research only. No production change. The data is an unofficial GitHub copy (see `NFL-TRACKING-FEASIBILITY-2026-10-23.md`). Permitted use is user-reported, not verified. Bulk tracking stays outside git. This commit holds code, this report, and a 49-play manifest of identifiers, frame numbers and derived geometry.

## 1. Label semantics

| Field | Level | What the data shows | Authority |
| --- | --- | --- | --- |
| tracking `event` = `tackle` | frame | Every play with a tackle has exactly 23 rows tagged `tackle` at one frame: 22 players plus the football. Checked in all nine weeks (1,205, 1,131, 1,197, 1,193, 1,182, 1,062, 1,055, 1,075 and 946 plays). | Frame timing only. The `nflId` on an event row does not identify the tackler. |
| `event` = `first_contact` | frame | Broadcast the same way. Up to two frames per play (week 1: 1,255 frame keys on 1,253 plays). | Timing only. |
| `event` = `out_of_bounds` | frame | Broadcast the same way. | Ending type. |
| `soloTackle`, `tackleAssist`, `assistedTackle` (`player_play.csv`) | player | Mutually exclusive on every row. Season counts: solo 8,809; tackleAssist 5,476; assistedTackle 1,468. | Authoritative for credit in this copy. Not documented: the repository has no data dictionary, so the difference between tackleAssist and assistedTackle is unverified. Both are treated as assists. |
| Missed tackle | none | No field in `player_play.csv` or `plays.csv`. | No authoritative label. Not inferred from text. |
| Ball carrier | none in tracking | Inferred from `player_play.csv` (`hadRushAttempt` or `hadPassReception`, offense). Cross-check: distance from the football to the carrier at the tackle frame, median 0.23 yd. 4.2% of single-carrier plays exceed 2 yd. | Inferred. |
| `playDescription` (`plays.csv`) | play | Keyword cross-check only ("tackled", "pushed ob"). | Not a label. |

## 2. Reconciliation of the three categories

| Category | Plays | Explanation | Status |
| --- | ---: | --- | --- |
| A: tackle event and solo/assist label | 10,000 | 9,813 have a single carrier. 187 have none: 112 incomplete passes and 75 sacks. 4 A plays also have a `qb_sack` event. 49 A plays have no `ball_snap` event, so no snap frame. Tackle timing: median 4.7 s after the snap (p10 3.4 s, p90 6.9 s; range 1.1 to 43.2 s). 8 plays are more than 15 s after the snap. | Carrier and snap gaps are reported and excluded from development, not filled. |
| B: tackle event, no label | 46 | No out-of-bounds, sack or "tackled" text. 14 have no single carrier. Of the 31 with one, the nearest defender is within 1 m at the event frame in 55%. | Unresolved: either a missing per-player credit or a tackle event without a credit. Kept as ambiguous. |
| C: label, no tackle event | 2,242 | 1,624 have an `out_of_bounds` event. 527 have a `qb_sack` event. Union 2,150. Of the 1,256 C plays whose description says "pushed ob", 1,255 have an out-of-bounds event. No A play has an out-of-bounds event. | Strong pattern, inferred: out-of-bounds endings and sacks appear to carry their own events and not the tackle event. The publisher does not confirm this. The pattern is not complete: 66 A plays also say "pushed ob" in their description but carry a tackle event and no out-of-bounds event. Unresolved. |
| C remainder | 92 | 49 runs, 31 blank pass results, 7 sacks, 4 completions, 1 incomplete. In 79 of the 92 a credited defender is within 1 m of the carrier at some frame. | Unresolved. Plausible genuine tackles without a tackle event. |

No events were created to match the counts. Each difference is listed with its reason, and the unexplained ones are kept.

Timing: the tackle frame precedes the last tracked frame by a median of 4 frames (0.4 s). Tracking ends shortly after the tackle for most plays. The completeness check on the cohort found contiguous frames with all 22 players and the ball present at every frame.

## 3. Individual tacklers

Scope: the 9,813 A plays with a single carrier, 13,127 credited-defender rows. Join: `gameId`, `playId`, `nflId`, with `nflId` matched against the tracking rows at the tackle frame.

- **Identity:** all 13,127 credited defenders are tracked at the tackle frame. No missing identities among single-carrier plays. The 187 no-carrier plays were not evaluated for credited identity.
- **Distance, credited defender to carrier, at the tackle frame:** median 0.76 m (p10 0.30, p90 1.85, p99 4.53). 65.9% are within 1.0 m. 3.4% are beyond 3 m and 0.72% beyond 5 m. Maximum 32.75 m.
- **Closing speed** (single-frame difference, positive means closing): median −0.42 m/s. Closing in 28% of rows, p90 0.59 m/s. One frame is a weak measure of contact, so it is not used as a criterion.
- **Approach angle** (defender heading against bearing to carrier): median 65.5°. 34.6% at or below 45° (heading at the carrier). 14.6% at or above 135° (moving away at the frame).
- **Relative position** (defender bearing measured from the carrier's motion direction): median 138°. 53% behind the carrier's motion, 9% ahead. Most credited defenders are pursuing from behind or from the side.
- **Multiple credit:** one defender on 6,669 plays, two on 3,321, three on 9, four on 1.
- **Nearest defender disagrees with the credit:** on 6,363 plays a credited defender is the nearest defender at the tackle frame. On 3,450 none is. On those 3,450, the best credited defender is a median 0.47 m farther than the nearest (p10 0.07, p90 1.9). 1,566 credited defenders are within 1 m, and the nearest defender is within 1 m on 2,917. This mostly reflects several defenders in the contact range, not an obvious mislabel.
- **Examples:** 2022091100 play 2114 (visual cohort V5): credited defender 53469 at more than 3 m, football 2 yd from the carrier. 2022091101 play 2723 (V6): tackle event with no carrier label, incomplete pass.

## 4. Cohorts

Nothing here has been scored or tuned on. The rules below are fixed for this version.

**Exploratory visual cohort (week 1, n = 9).** Chosen at random with seed 20261024, one play per category, including the ambiguous cases on purpose. Use for inspection only:

| Label | Play (game, play) | Identity status |
| --- | --- | --- |
| V1 solo tackle, typical geometry | 2022091111, 878 | high |
| V2 tackleAssist, typical | 2022091103, 4279 | high |
| V3 assistedTackle, typical | 2022091100, 3379 | high |
| V4 two credited defenders | 2022091106, 2384 | high |
| V5 credited defender beyond 3 m | 2022091100, 2114 | medium |
| V6 tackle event, no carrier label | 2022091101, 2723 | excluded |
| V7 event only, no credit | 2022091110, 844 | excluded |
| V8 label only, out-of-bounds ending | 2022091200, 3216 | excluded |
| V9 label only, unexplained | 2022091100, 212 | excluded |

**Development sample (weeks 2–5, n = 40, 33 games, at most two per game).** Drawn at random from the eligible pool. Eligibility for A plays requires all of:
- a single carrier;
- every credited defender tracked at the tackle frame;
- the closest credited defender within 3 m;
- the football within 2 yd of the carrier;
- the tackle within 15 s of the snap;
- no sack event;
- not an incomplete pass;
- a snap event present.

Season exclusions by primary reason, out of 10,000 A plays: eligible 9,065; football more than 2 yd from carrier 389; credited defender beyond 3 m 309; no single carrier 187; no valid snap or tackle order 46; sack event 2; more than 15 s after snap 2.

**Holdout (weeks 6–9, 56 games).** Not sampled. Reserved for a later preregistered evaluation. Nothing from it has been looked at for this audit.

## 5. Manifest v1

`docs/research/bdb2025-observed-tackle-manifest-v1.csv`: 49 rows (40 development, 9 exploratory). Identity confidence: 44 high, 1 medium, 4 excluded.

Fields: game, play, week, split, snap frame, first-contact frames, tackle frame, out-of-bounds frame, first and terminal tracked frames, frame count and completeness, contiguity, play direction, coordinate units (yards; x 0–120, y 0–53.3), carrier ID and status, credited IDs and flag types, credited count, credited minimum distance at the tackle frame, nearest defender ID, football-to-carrier distance, pre-snap input cutoff (frames at or before the snap frame), outcome-label provenance, identity confidence, exclusion reasons, and inclusion flag. Terminal frame is a median of 4 frames after the tackle frame.

## 6. Limits

- The data is an unofficial copy. Permitted use is user-reported.
- Credit is a label. The data does not show who initiated contact, and the tackle frame does not prove contact.
- The difference between tackleAssist and assistedTackle is undocumented.
- The carrier is inferred, and the football check is only a cross-check.
- Velocities are finite differences at 10 Hz. Single-frame closing speed is noisy.
- The explanations for out-of-bounds and sack labels are inferred from the pattern, not confirmed by the publisher.
- 49 A plays have no snap event. Not resolved.
- No model has been run. The development sample is not scored.

## 7. Reproduce

```sh
python3 scripts/fetch_bdb2025_week.py tracking_week_N.csv   # weeks 1-9, pinned LFS hashes
python3 scripts/profile_bdb2025_weeks.py                    # play counts and label reconciliation
python3 scripts/bdb2025/qb_sack_scan.py                     # qb_sack plays
for w in 1 2 3 4 5 6 7 8 9; do python3 scripts/bdb2025/audit_tacklers.py $w; done
python3 scripts/bdb2025/cohort_build.py                     # eligibility, cohorts, selection
python3 scripts/bdb2025/manifest_build.py                   # manifest v1
```

Outside git: `/root/nfl-tracking-data/bdb2025/audit/` holds the per-week audit CSVs, the 12,288-row eligibility table with reasons, `cohort_selection.json` and `qb_sack_plays.json`.
