# SLC v2 gate report: Milestone 2 and the gate to Milestone 3, 2026-11-02

Status: research report. No SLC default change. No simulator run. No production database write. No deployment. No 2025 or 2026 result read for development or selection. The 2025 retrospective fold is reported only where the owner ruling asks for it, and it is labelled. Nothing is committed.

## 1. Summary

| Item | Result | Status |
|---|---|---|
| Owner rulings applied (M3 freeze amendment, PBV1 package code, 2025 depth adapter, injury history, NGS, P1 scope) | Done. See section 9. | Met |
| 2025 depth-chart adapter (ruling B) | Built, 25 tests passing, all 1,088 2025 regular-season states at or before their cutoff | Met, with the `dt` caveat |
| Time-safe availability matrix (ruling D) | Written, four classes applied to every candidate source | Met, with two unverified timings |
| Coaching-source investigation (ruling P1) | Bounded search done; no coordinator or play-caller source for 2022 to 2024 | Met as a finding; coordinators unavailable |
| Historical PBV1 package sampler (ruling E) | Pre-registered, evaluated on 2023, 2024 and 2025 (retrospective) | Met; passes the spec's rule under a stated reading of criterion (c) |
| P1 team play-calling | Evaluated; in-season gain significant both seasons | Partly met: tempo and fourth-down aggression not evaluated |
| P2 player usage | Evaluated; gain over prior-only significant both seasons | Met for target share; snap share not evaluated |
| P3 defensive matchup | Evaluated; not adopted | Not met: no outcome beats baseline in both seasons |
| Provenance manifests for every historical forecast (paste G) | Written for P1, P2, P3 and the depth states; PBV1 needs none (pre-season training membership) | Met |
| Gate to Milestone 3 | Features and manifests exist for P1 and P2; P3 failed | **Partially met** |

## 2. Depth-chart adapter coverage (`slc-v2-depth-adapter-2026-11-02/`)

- Source: nflverse `depth_charts_2025.parquet`, 554,215 rows, SHA-256 `14f74185b3c2c48df234ced284ba3596bda3333d0b2a8df40841f68cd34539fa`. 221 dated snapshots shared by all 32 teams. Loads fall at about 07:15 UTC; median gap 24 hours.
- Coverage: 272 regular-season games, both teams, both horizons: 1,088 states, all `ok`. Zero states withheld by the series guard; zero states with no snapshot before cutoff. Every snapshot is at or before its cutoff (checked in the output).
- Staleness at the cutoff (hours): early median 9.7; final median 9.8, maximum 17.7.
- Identity over all states (early / final): GSIS 38,366 / 39,191; unmatched 73 / 69; ambiguous 0 / 0; ESPN-unique 0 / 0. Duplicate identity is common by design (one player listed in several depth roles); duplicate slots are zero.
- Unknown roles: zero in the selected states.
- Limits: offense appears only as the `3WR 1TE` group in this file. `dt` semantics are not documented by the publisher; the working assumption is that `dt` is the load time, which makes the cutoff check conservative (a snapshot is only excluded, never read early). Depth is not injury status (ruling C).

## 3. Time-safe feature availability matrix

Full matrix: `SLC-V2-TIME-SAFE-AVAILABILITY-MATRIX-2026-11-02.md`. Key rules:

- Play-by-play and the weekly player logs: class U (publisher silent on timing). Used for in-season inputs only with a stated 10-hour lag after scheduled kickoff. This is an assumption and is recorded in every manifest.
- Participation and FTN charting, 2023 onward: class H within season. The nflreadr participation page states they are provided after all postseason games; the timing sentence sits under the FTN heading, so the placement is recorded as an open item.
- Snap counts (PFR): class U. Training label only until verified.
- Injury reports: usable only when `date_modified` is at or before the cutoff. Otherwise excluded and counted (ruling C).
- Head coach: carried from the team's latest usable earlier game; the target game's schedule row is never read for the coach (ruling P1).
- Coordinators, market lines before 2026, roster snapshots, NGS separation: no usable history on this box.

## 4. Coaching-source findings

- **Coaching seed workbook** (`coaching-seed-2026-11-02/`, five CSVs, audit in `SLC-V2-COACHING-SEED-AUDIT-2026-11-02.md`): 64 team-season rows for 2025 and 2026, marked as directory seeds and not game-level verified. No 2025 play-caller is filled in. The one 2025 play-caller split is Cleveland (Stefanski weeks 1 to 9, Rees weeks 10 to 18), sourced to a team news page. The People Index (120 names) is provisional.
- **SportsDataverse coach loaders** (fetched from the docs pages): `load_nfl_coach_tendencies` gives season-by-team head-coach rows from 2002 to 2026, with no coordinator rows and no effective dates; it is derived from the same nflverse schedule coach field, so it is not an independent check. `load_nfl_coach_careers` gives one row per head coach.
- **drafthistory 2025 team leaders**: HC, OC, DC and special-teams coordinators per team, as of the season start, no source named.
- **The Analyst (2025 play-callers, May 20, 2025)**: twelve new offensive play-callers with titles and remarks; no designation of who calls plays, no source.
- **gridironexperts 2026 list**: unavailable. Four fetches returned empty; the list is unchecked.
- **Finding**: no verified historical coordinator or play-caller source exists on this box for 2022 to 2024. Team tendencies and the head-coach carry are the only P1 inputs.

## 5. Historical PBV1 evaluation

Spec: `PBV1-SAMPLER-SPEC-2026-11-02.md` (pre-registered). Report: `pbv1-sampler-2026-11-02/REPORT.md`. Primary K = 20, package_comparable (RB+FB), 133,262 regular-season scrimmage plays.

| Fold | Role | Sampler minus marginal (95% CI) | Sampler minus unshrunk cell (95% CI) | Unsupported: sampler / unshrunk | Package TV |
|---|---|---|---|---|---:|
| Fit 2022, score 2023 | development | +0.0594 (+0.0536 to +0.0652) | -0.00033 (-0.00065 to -0.00001) | 8 / 181 | 0.027 |
| Fit 2022 to 2023, score 2024 | development | +0.0667 (+0.0614 to +0.0721) | -0.00037 (-0.00058 to -0.00017) | 4 / 71 | 0.032 |
| Fit 2022 to 2024, score 2025 | previously exposed, retrospective | +0.0691 (+0.0627 to +0.0752) | +0.00007 (-0.00015 to +0.00032) | 8 / 49 | 0.049 |

Reading: the sampler beats the marginal distribution on every fold. It is very slightly less likely than the unshrunk cell where the cell can score, but it covers almost every play and the unshrunk cell does not. Package mix drifts in 2025 (11 personnel predicted 0.631, observed 0.588; 12 and 13 personnel higher than predicted). Named players and workloads are not evaluated (ruling E).

Decision rule: (a) and (b) met. (c) met under the reading that the retrospective fold's comparison is the marginal one (the spec does not name it). Owner to confirm the reading. The 2022 fullback coding is inferred, not labelled; RB-only sensitivity moves the TV distance up to 0.098 in 2023.

## 6. P1, P2 and P3 results and feature examples

Development seasons 2023 and 2024 only. Intervals are game-clustered, 10,000 draws, seed 20261102.

**P1 team pass share** (`slc-v2-p1-team-2026-11-02/REPORT.md`, 544 team-games per season). Improvement over the league baseline: 2023 +0.00029 (interval includes zero); 2024 +0.00110 (+0.00040 to +0.00181). Improvement over the coach-era prior with no in-season update: 2023 +0.00066 (+0.00013 to +0.00118); 2024 +0.00088 (+0.00031 to +0.00147). The coach-era prior does not reliably beat the team prior (the sign flips).

Example (manifest row): GB, 2024 week 12 game `2024_12_SF_GB`. Coach carried from usable games (`Matt LaFleur`, source `usable_game`). Prior: coach-era, 0.58958. Games used: 10. Estimate 0.52989. Observed 0.37313. Latest used kickoff 2024-11-17 18:00 UTC; cutoff 2024-11-24 20:25 UTC; check passed.

**P2 target share** (`slc-v2-p2-usage-2026-11-02/REPORT.md`, 17,788 and 18,112 targets). Improvement over the prior-only estimate: 2023 +0.00039 (+0.00036 to +0.00043); 2024 +0.00046 (+0.00041 to +0.00051). Improvement over the position-mean baseline: about +0.00115 in both seasons.

Example (`p2_examples.json`): WR `00-0033251`, 2023 game `2023_10_ATL_ARI`. Usable games: 8. Observed mean 0.0379. Prior (own, prior season): 0.0418. Estimate 0.0392. Observed 0.0323. Position-mean baseline 0.1351. Cutoff 2023-11-12 20:05 UTC.

**P3 defensive matchup** (`slc-v2-p3-defense-2026-11-02/REPORT.md`): **not adopted.** No outcome beats the league baseline in both seasons with an interval above zero. Receiving TE and receiving RB are significantly worse than the baseline in 2023 (-0.55 and -0.73 squared error, intervals below zero). Opponent adjustment is not consistently helpful.

Example (manifest row, shown for the audit trail, not as a forecast to use): KC defense, BUF offense, 2024 week 11 game `2024_11_KC_BUF`, receiving WR. Games used: 9. Prediction 7.43 yards per target. Observed 9.13. Opponent strength from 2023 pass yards per attempt. Cutoff 2024-11-17 20:25 UTC; check passed.

**P1 and P3 open items:** tempo and fourth-down aggression (P1) and volume forecasting, touchdown rates and a pre-registered variant (P3) are not evaluated.

## 7. Provenance manifests

| Forecast set | File | Rows | Late violations |
|---|---|---:|---:|
| 2025 depth-chart states (early and final horizons) | `slc-v2-depth-adapter-2026-11-02/outputs/depth_coverage_2025.csv` | 1,088 | 0 (every snapshot at or before cutoff) |
| P2 player target share, 2023 and 2024 | `slc-v2-p2-usage-2026-11-02/outputs/p2_forecast_manifest.csv` | 35,900 | 0 |
| P1 team pass share, 2023 and 2024 | `slc-v2-p1-team-2026-11-02/outputs/p1_forecast_manifest.csv` | 1,088 | 0 |
| P3 defensive matchup, 2023 and 2024 | `slc-v2-p3-defense-2026-11-02/outputs/p3_forecast_manifest.csv` | 5,417 | 0 |

Each manifest row carries the cutoff, the games used, the latest used kickoff, the lag, and the check that the latest used kickoff plus the lag is at or before the cutoff. PBV1 is a package-level training-season comparison (fit on earlier seasons, score the next season) and has no weekly cutoff; its manifest is the training-season membership in the code.

## 8. Scope checks

- Development seasons 2023 and 2024 only; the 2025 retrospective fold is reported once, for PBV1, as the spec requires. No 2026 result read. The 2025 depth file contains 2026 snapshot times; they are excluded by the cutoff rule for every 2025 state.
- No SLC default change. No simulator run. No archived 10K batch rerun. No production database write (all reads use read-only connections). No deployment.
- Commits: none. Working tree has new untracked files and one modified inventory file.

## 9. Owner rulings applied, and what they changed

- **M3 freeze**: amendment recorded (`PLAYCALL-M3-FREEZE-AMENDMENT-1-2026-11-02.md`). Current and parent `playbook_prior.py` give identical `load()` output for 2023, 2024 and 2025 cutoffs; 14 consumer tests pass; the original hash and the bootstrap settings are preserved in the record.
- **PBV1 package code**: RB+FB for cross-season comparison, RB-only retained for SLC, 2022 fullback coding uncertainty preserved and reported.
- **2025 depth charts**: adapter built with temporal, identity, duplicate and staleness rules, tested, and run on 2025 games.
- **Injury history**: early-cutoff states excluded unless the last modification is at or before the cutoff; counted.
- **NGS separation**: deferred; no separation feature is presented.
- **P1 scope**: head coach plus observed team tendencies; no claim that the head coach called plays.

## 10. Owner decisions and open items

1. **Criterion (c) reading** for PBV1 (retrospective fold compared against the marginal, as read here). Confirm.
2. **`dt` semantics** for the depth snapshots. Not documented by the publisher. The conservative assumption is recorded.
3. **Play-by-play and player-log publication timing.** Not stated by the publisher. The 10-hour lag is an assumption. A sensitivity with a longer lag is not yet run.
4. **Participation and FTN timing wording.** The publisher places the postseason timing sentence under the FTN heading. Confirm which fields it governs.
5. **P3**: not adopted. A pre-registered variant (new K or a multi-season prior) would be needed before reconsideration. The owner decides whether to pursue it.
6. **P1 tempo and aggression**: to build and evaluate.
7. **Coaching structural breaks**: not modelled yet. The Cleveland 2025 split is the only candidate and is unverified at game level.
8. **Coordinators**: no historical source. Still open.
9. **Gridironexperts 2026 list**: unreachable from this box.
10. **Milestone 4 (predictive ablation)** and **Milestone 5 (integration)**: not started.

## 10a. Addendum: Milestones 3 to 7 (same day)

- **P1 tempo and fourth-down go rate** are now evaluated. Tempo is worse than the league baseline in 2024 (interval below zero) and gives no in-season gain over the coach-era prior. Go rate gives no gain in either season. Both are REJECT and are not carried to 2025.
- **P2 snap share** is skipped: the published weekly logs carry `off_pct` for 0 rows in 2023 and 29% of regular-season rows in 2024. The 0.95 coverage rule blocks it. Category INCONCLUSIVE.
- **Milestone 6 (2025 retrospective), frozen candidates only:** P1 pass share +0.00121 over its comparator (interval +0.00060 to +0.00185), and P2 target share +0.00041 over its prior-only estimate (interval +0.00038 to +0.00045). Both are ADOPT (research). The frozen code and rules are in `SLC-V2-M6-FREEZE-2026-11-02.md`.
- **Milestone 4 and 7 records:** `SLC-V2-M4-M7-DECISIONS-2026-11-02.md`.
- **Milestone 5 and prospective 2026 are blocked** on owner decisions (freeze amendment for pinned simulator files, comparator choice, compute budget, and authorization for prospective 2026 snapshots). See `SLC-V2-M5-M6-PROSPECTIVE-BLOCKERS-2026-11-02.md`.
- The 2025 coach-era and team comparators are identical in 2025 (no head coach worked for two teams in 2024), so the coach-era prior's own value is not tested there.

## 11. Files

- `slc-v2-depth-adapter-2026-11-02/`: `depth_adapter.py`, `build_coverage.py`, `test_depth_adapter.py`, `REPORT.md`, `outputs/depth_coverage_2025.csv`.
- `pbv1-sampler-2026-11-02/`: `pbv1_sampler.py`, `pbv1_eval.py`, `test_pbv1_sampler.py`, `REPORT.md`, `outputs/`. Spec: `PBV1-SAMPLER-SPEC-2026-11-02.md`.
- `slc-v2-p1-team-2026-11-02/`, `slc-v2-p2-usage-2026-11-02/`, `slc-v2-p3-defense-2026-11-02/`: each with component, evaluation, tests (11, 13 and 9 passing), `REPORT.md` and `outputs/`.
- `SLC-V2-TIME-SAFE-AVAILABILITY-MATRIX-2026-11-02.md`, `SLC-V2-COACHING-SEED-AUDIT-2026-11-02.md`, `coaching-seed-2026-11-02/`, `PLAYCALL-M3-FREEZE-AMENDMENT-1-2026-11-02.md`, `playcall-m3-freeze-amendment-1-2026-11-02/`.
