# SLC-CEG: conditional event generation, status after Phases 0 to 8

Branch `research/slc-ceg-2026-11-24`, based on the v2 engine (`8a1d9842`). Plan: `../SLC-CONDITIONAL-EVENT-GENERATION-PLAN.md`.
No frozen SLC version, V1 Complete or Gridiron was changed. Each scored phase (2, 3, 4, 6, 7) was pre-registered and
committed before it was scored.

## In one paragraph

CEG replaces "find a similar historical play" with "draw the next event from fitted conditional distributions". It now
plays complete, legal NFL games from a 2 MB parameter-only artifact with every data source blocked, never refuses a state
(0 refusals on the scrimmage state grid, on all 25 week 11 scrimmage failure cells, and on every punt and field-goal
state), and reproduces most per-game statistics within 6% (fouls are 22% short). It
scores 13% too little, and it cannot yet forecast games: with only two small team terms it is close to a coin on
winners. The architecture is done; team strength is the open research question.

## Phases

| phase | report | outcome |
|---|---|---|
| 0 dependency audit | `PHASE0-DEPENDENCY-AUDIT.md` | 17 historical dependencies; the five frozen packs reproduce week 11 exactly |
| 1 event dataset | `PHASE1-DATASET-AUDIT.md` | 225,829 plays from raw nflverse, before any SLC filter; counts reconcile with nflverse stats (2,898 of 2,900 team-weeks exact on pass attempts); FTN charting, participation and snap counts as separate sources |
| 2 scrimmage | `PHASE2-SCRIMMAGE-REPORT.md` | arm C beats B on 6 of 11 components in 2025 (play call -0.39 per play); C-FTN wins nowhere; 0 refusals |
| 3 clock and timeouts | `PHASE3-CLOCK-REPORT.md` | C beats B on every clock component; ties Model D on runoff while separating live time, dead-ball time and timeouts; overtime clock rules measured and applied |
| 4 special teams, tries, penalties | `PHASE4-SPECIAL-TEAMS-REPORT.md` | C beats B on 7 of 12; kickoffs need in-season regime adaptation (-0.365); v2's overtime 0.9 field-goal rule loses by 0.46 per play |
| 5 runtime | `PHASE5-RUNTIME-REPORT.md` | full games with every data read blocked |
| 6 differentiation | `PHASE6-DIFFERENTIATION-REPORT.md` | two team terms beat C (small); arm D confirmed (-0.348 per opportunity against v1's share) |
| 7 evaluation | `PHASE7-EVALUATION-REPORT.md` | realism mostly within 6%, points 0.87; week 11 home-win Brier 0.245 (market 0.183); week 12 frozen |
| 8 team strength | `PHASE8-TEAM-STRENGTH-REPORT.md` | yardage team shifts count per play but are not useful at drive level (E8 minus C -0.12, n.s.); offense ranking r 0.19 against 0.67 for a simple points-per-drive baseline; per-play tuning over-shrinks teams |

Open work: `ENGINEERING-BACKLOG.md` (E1 to E12), led by team strength on the scoring components, player attribution in
the runtime (arm D), and the regression and GAM challengers.

## Corrections found by the checks, all fixed before reporting

- Phase 1: timeouts are `no_play` rows in nflverse (first build missed 9,660); spikes count as pass attempts.
- Phase 3: timeouts-remaining already subtracts the next timeout; an index misalignment put the out-of-bounds window
  on the wrong rows (found by the pre-registered sensitivity check).
- Phase 4: the first penalty design leaked the label; amended before scoring.
- Phase 7: the generator allowed field goals beyond the drive loop's ceiling; aligned to `field_goal_feasibility`.
- Phase 0 audit: last plays of quarters and scrambles are kept by v2 (corrected by the Phase 1 waterfall).

## Data and artifacts (not in git)

Inputs `/root/slc-ceg-data/raw-2026-11-24/`; tables `/root/slc-ceg-data/phase1-2026-11-24/`; artifacts
`/root/slc-ceg-data/artifacts/`; game runs `/root/slc-ceg-data/phase7/`. Hashes are in each phase's manifest or commit.
