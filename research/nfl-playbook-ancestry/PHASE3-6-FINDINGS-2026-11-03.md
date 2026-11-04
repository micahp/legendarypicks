# Corrected findings: NFL playbook evolution and ancestry

Inventory date: 2026-11-03. This report supersedes the earlier Phase 3–6 interpretation where its results differ. All play signatures below are source-field descriptors. They do not identify designed plays or concepts.

## Reproduction

Run these commands from the research worktree. Phase 2 opens the dev DB read-only. Phase 3–6 also reads the pinned local PBP parquet snapshot for postseason plays and score differential.

```bash
python3 research/nfl-playbook-ancestry/phase2_weekly_evolution.py \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --out-dir research/nfl-playbook-ancestry
```

```bash
python3 research/nfl-playbook-ancestry/phase3_6_analysis.py \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --raw-pbp-dir /root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp \
  --out-dir research/nfl-playbook-ancestry
```

These commands produced the JSON manifests, tables, and metrics linked below. Run the regression suite with:

```bash
python3 -m unittest discover -s research/nfl-playbook-ancestry -p 'test_*.py' -v
```

## Confirmed descriptive results

### Data and joins

The Phase 3–6 command counted **149,048 regular-season run/pass rows** across 2022–2026 (2026 through Week 8) and **6,574 postseason rows** across 52 games. All postseason rows retain one row after exact game/play joins; participation matches **6,574/6,574** and FTN charting **6,566/6,574**. Source joins and coverage are in the [manifest](phase3_6_analysis_dev_2026-11-03.json).

### Seattle usage and snap denominators

Seattle's recorded personnel and chart-tag trends remain descriptive:

| Segment | Run/pass rows | 3+ WR | 2+ TE | Play action among tagged pass rows | Motion |
|---|---:|---:|---:|---:|---:|
| 2024 regular | 1,018 | 79.5% | 20.3% | 18.4% (648 passes) | 43.3% |
| 2025 regular | 997 | 45.4% | 42.8% | 25.1% (506 passes) | 57.2% |
| 2025 postseason | 188 | 45.2% | 48.1% | 26.8% (97 passes) | 61.7% |

Snap denominators were reconstructed per game by intersecting integer totals consistent with each player's `offense_snaps` and `offense_pct`, treating rounded half-point boundaries conservatively. All **52/52** Seattle segment-games produced one denominator. Across these Seattle games the reconciled total equaled the largest individual snap count; this verifies the reviewed denominator for this team and sample, rather than assuming that maximum is generally the team total.

The matched Weeks 1–8 JSN comparison is **326/428 = 76.2%** of Seattle offensive snaps in 2025 and **448/527 = 85.0%** in 2026. Annual regular-season 2025 is **829/1,064 = 77.9%**. The per-game reconciliation audit and regenerated player table are [here](phase5_seahawks_snap_denominator_audit_2026-11-03.csv) and [here](phase5_seahawks_player_snap_share_2026-11-03.csv). 2026 participation and FTN tags are unavailable, so only the PBP and weekly snap-count comparisons extend into 2026.

### Postseason usage under opponent and game-state controls

Each playoff row is matched only when the same season, offense, opponent, down, distance bucket, and score-margin bucket occurs in the regular season. Rows missing a required control and rows without a regular-season comparison cell are reported separately. Rates below are standardized to the matched playoff contexts; categorical results use total variation (TV) between playoff and standardized regular-season distributions.

| Attribute | Eligible playoff rows | Matched | Unsupported rows / distinct contexts | Incomplete controls | Matched result |
|---|---:|---:|---:|---:|---|
| Run/pass | 6,574 | 1,660 | 4,886 / 1,517 | 28 | Run: 42.8% vs 42.1% regular (+0.7 pp); TV 0.007 |
| Personnel (parseable RB/TE/WR) | 6,372 | 1,618 | 4,730 / 1,488 | 24 | TV 0.054 |
| Formation | 6,568 | 1,660 | 4,880 / 1,516 | 28 | TV 0.022 |
| Motion | 6,566 | 1,660 | 4,886 / 1,517 | 20 | 47.0% vs 48.1% regular (−1.1 pp) |
| Shotgun | 6,574 | 1,660 | 4,886 / 1,517 | 28 | 75.4% vs 73.4% regular (+2.0 pp) |
| Play action (tagged passes only) | 3,832 | 863 | 2,954 / 1,186 | 15 | 19.7% vs 27.6% regular (−7.9 pp) |

These are descriptive comparisons on small supported subsets, not causal estimates. The earlier **44.5%** standardized run-rate figure used a smoothed baseline and retained unknown game-state cells. The corrected figures above require every control and use the empirical regular-season distribution. Per-season rows and category distributions are in the [context-adjusted summary](phase4_postseason_context_adjusted_summary_2026-11-03.csv) and [category table](phase4_postseason_context_adjusted_categories_2026-11-03.csv).

### Coaching continuity

Schedule joins cover **149,048/149,048** regular run/pass rows and yield 160 team-seasons. Six have more than one head-coach value in observed games; among 128 team-seasons with a prior-season comparison, 101 retain the same primary head coach and 27 change. League-wide offensive-coordinator and play-caller tenure is unavailable. The measured four-field action-signature overlap cannot establish concept carryover. The external evidence table preserves claim-level verification status; unverified claims are not used as play labels.

## Predictive results

Phase 6 tests stop before each target team-week and compare models only on common team-season-week evaluation groups within each family. Lower log loss is better.

| Family | Matched test rows | Team-week groups / team-seasons | Previous season | Current season expanding | Last 4 games | Adaptive 4-game half-life |
|---|---:|---:|---:|---:|---:|---:|
| Run/pass | 107,523 | 1,746 / 128 | 0.9851 | 0.9860 | 0.9880 | **0.9827** |
| Four-field action descriptor | 107,523 | 1,746 / 128 | 3.2025 | 3.2176 | 3.2341 | **3.1944** |
| Formation | 62,581 | 1,024 / 64 | 1.2730 | 1.1878 | 1.1932 | **1.1834** |
| RB/TE/WR personnel | 90,968 | 1,536 / 96 | 1.8808 | 1.5187 | **1.5148** | 1.5459 |

Scores are bits per held-out row. The formation comparison is limited to 2024–25: the 2022 formation vocabulary differs from 2023 onward, and formation/participation data are absent in 2026. Personnel covers 2023–25 because its per-play inputs are absent in 2026. Run/pass and action descriptors cover 2023–26. The [matched comparison](phase6_matched_model_comparison_2026-11-03.csv) lists the identical test population per family/model; paired franchise-cluster intervals use that same population ([intervals](phase6_franchise_bootstrap_2026-11-03.csv)).

The best history length differs by attribute. Relative to expanding current-season data, adaptive weighting improves run/pass loss by **0.00330 bits/play** (95% CI improvement 0.00225–0.00436) and action-descriptor loss by **0.02323** (0.02102–0.02543). For personnel, last-four and expanding are unresolved (difference −0.00392; CI −0.01018 to +0.00244), while the previous-season model is worse by **0.3620** (CI +0.2446 to +0.4950). Formation's adaptive difference is unresolved (−0.00436; CI −0.01064 to +0.00106). These results do not support one universal historical weighting rule.

Among 107,523 walk-forward run/pass targets, participation and FTN joins each cover 94,524 (**87.9%**); non-null formation covers 94,367 (**87.8%**); parseable RB/TE/WR personnel covers 90,968 (**84.6%**); and play-action tags cover 54,305 pass rows (**50.5%** of all run/pass targets). Per-play participation and FTN charting are absent in 2026. Coverage counts and limits are in the manifest. The model predicts source-field distributions only; no closed-loop workload simulation was run.

## Unsupported play-identity claims

The four-field action signature (`play_type`, `run_gap`, `run_location`, `pass_location`) is an execution descriptor. For Seattle it yields only about a dozen signatures per season; overlap between regular-season and playoff catalogs does **not** show that the same designed play was called. Across four postseasons, **595/6,574 rows (9.05%)** have an action descriptor not seen for that team in its regular season; this is not a new-concept rate. Formation, personnel, motion, shotgun, and play-action comparisons describe usage, not ancestry. No exact play names or concept labels were inferred.

## Remaining requirements for actual concept ancestry

Concept ancestry remains unresolved. It requires play-level labels tied to the source game/play key, with provenance and confidence: at minimum, annotated All-22 or equivalent charting that identifies run scheme, route combinations, assignments/reads, and presentation changes. A labeled sample needs independent review and adjudication before matching concepts across formations, seasons, teams, or coaches. Stable play-caller/coordinator lineage and explicit unknown/unmatched states are needed to study imported concepts. The current source fields support descriptive personnel and formation distributions now; they cannot reconstruct every designed play.

The four-phase summary and exact generated tables are linked from the [Phase 2 report](PHASE2-WEEKLY-EVOLUTION-2026-11-03.md) and the [analysis manifest](phase3_6_analysis_dev_2026-11-03.json). No SLC simulation code or shared branch was changed.
