# NFL playbook evolution and ancestry: Phases 3–6

Inventory date: 2026-11-03. This report completes the requested measurements for coaching continuity, postseason usage, the Seahawks case, and chronological distribution forecasts. The output measures source-field signatures; it does not identify exact play designs or concepts.

## Reproduction

Run from the research worktree. This one command rebuilds the Phase 3–6 CSVs and JSON manifest. It reads the dev SQLite database in read-only mode and uses the pinned local nflverse Parquet snapshot for postseason rows and regular-season score differential. It does not write to the database.

```bash
python3 research/nfl-playbook-ancestry/phase3_6_analysis.py \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --raw-pbp-dir /root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp \
  --out-dir research/nfl-playbook-ancestry
```

The run produced the [manifest](phase3_6_analysis_dev_2026-11-03.json), [walk-forward scores](phase6_model_comparison_2026-11-03.csv), [postseason team results](phase4_postseason_team_2026-11-03.csv), and [Seahawks segment results](phase5_seahawks_segment_summary_2026-11-03.csv). The script checks uniqueness of regular and postseason game/play keys and fails if the postseason exact-key join changes row cardinality.

## Source coverage

| Segment | Run/pass rows | Notes |
|---|---:|---|
| 2022 regular season | 33,770 | dev DB |
| 2023 regular season | 33,957 | dev DB |
| 2024 regular season | 33,470 | dev DB |
| 2025 regular season | 32,941 | dev DB |
| 2026 regular season | 14,910 | dev DB through Week 8 |
| **Regular total** | **149,048** | 32 teams |
| 2022 postseason | 1,660 | raw PBP; 13 games |
| 2023 postseason | 1,643 | raw PBP; 13 games |
| 2024 postseason | 1,580 | raw PBP; 13 games |
| 2025 postseason | 1,691 | raw PBP; 13 games |
| **Postseason total** | **6,574** | 52 games |

Participation joins cover **6,574/6,574** postseason run/pass rows. FTN charting joins cover **6,566/6,574**. For 2022–25 regular-season score-state matching, raw PBP score differential exact-joins to **134,138/134,138** dev DB run/pass rows. These figures come from the command above; season-level counts are in the manifest.

## Phase 3: coaching continuity — partial

The local schedule has **1,359 regular-season game rows** with head-coach fields for these seasons. Joining the schedule by game ID and team covers **149,048/149,048** regular run/pass rows and produces **160 team-seasons**. Six team-seasons have more than one head-coach value in the observed games. Among the 128 team-seasons with a prior-season comparison, 101 keep the same primary head coach and 27 change.

The available signal is too coarse to establish concept carryover. Every changed-head-coach team-season reuses all of its prior-season four-field action descriptors; the same is true for the mean under continuous head coaches (99.6% of unique descriptors, 100.0% of rows). Mean action-distribution total variation is 9.29% after a primary head-coach change and 8.65% with continuity. This small descriptive gap does not show that coaching continuity determines play identity or frequency. Results and each team-season are in [the head-coach table](phase3_head_coach_team_season_2026-11-03.csv) and [continuity summary](phase3_hc_continuity_summary_2026-11-03.csv).

League-wide offensive-coordinator and play-caller timelines are absent from these data, so they are not imputed from job titles. Seattle has a source-checked timeline: Ryan Grubb in 2024, Klint Kubiak in 2025, and Brian Fleury in 2026. Seattle's official Week 1 story identifies Grubb as coordinator and says he will call plays in his first regular-season NFL game; the Seahawks announced Kubiak as 2025 coordinator, with regional reporting identifying him as play caller; the 2026 Seahawks staff reporting names Fleury as coordinator and a Week 1 NFL.com/The Athletic account identifies his first regular-season game as play caller. Dates, links and confidence notes are in the [staff timeline](phase3_seahawks_offensive_staff_timeline_2026-11-03.csv).

Seven observed head-coach franchise-move rows are listed in [the move table](phase3_hc_franchise_moves_2026-11-03.csv). Their action-signature overlap is 100% in this small descriptor vocabulary; it cannot establish that a coach imported a concept.

## Phase 4: postseason — descriptor-level results complete; concept identity unresolved

Across **56 playoff team-seasons**, 595/6,574 postseason rows (**9.05%**) have a four-field PBP action signature not observed for that team in its regular season. These 595 rows correspond to **43 team-season/signature combinations**; they are not 43 new plays or concepts. Mean within-team action-distribution total variation between regular season and postseason is 0.158. First-observed signatures are listed with their recorded fields in [the signature file](phase4_first_observed_action_signatures_2026-11-03.csv).

Of 6,574 postseason rows, **5,974 (90.9%)** use an action descriptor observed again for the same team in the next regular season. For 2025 playoffs, the next-season search stops after **2026 Weeks 1–8**, so the 1,485/1,691 reuse count is only a lower-bound observation at that cutoff. Per-season novelty and reuse rates are in the [team table](phase4_postseason_team_2026-11-03.csv).

For an opponent/game-state comparison, 1,662 postseason rows (**25.3%**) have a regular-season comparison cell for the same season, offense, opponent, down, distance bucket and score-margin bucket. In these matched rows, the playoff run rate is **42.8%**, versus **44.5%** after standardizing the regular-season rate to the observed playoff contexts, a descriptive difference of **−1.7 percentage points**. Most postseason plays have no same-opponent/state support in the regular sample; this is not a causal estimate and does not adjust for defensive personnel or play sequence.

The measured playoff catalog covers raw action, formation, personnel, motion and play-action fields where charting joins exist. First-observed action signatures, usage shifts and next-season reuse remain execution-descriptor results. No result is labeled “new concept,” “tendency breaker,” or “same design” without film/chart annotations.

## Phase 5: Seahawks case — measured use and workload, not named concepts

The exact raw action catalog contains 12 signatures in both 2024 and 2025 regular seasons, 12 in 2025 postseason, and 11 in 2026 Weeks 1–8. All 12 2024 signatures also occur in 2025; all 12 2025 regular signatures occur in the postseason; all 11 2026 early-season signatures occur in 2025 Weeks 1–8. These are exact matches on `play_type`, `run_gap`, `run_location` and `pass_location`; they do not show that the underlying route/run designs are identical. [Matched examples and row counts](phase5_seahawks_exact_action_matches_2026-11-03.csv) preserve the raw descriptors.

The participation and chart-tag measurements reproduce the main Seattle personnel shift described by Sharp Football Analysis, subject to a different source and denominator:

| Seattle segment | Run/pass rows | 3+ WR | 2+ TE | Play action among charted pass rows | Motion |
|---|---:|---:|---:|---:|---:|
| 2024 regular | 1,018 | 79.5% | 20.3% | 18.4% (648 passes) | 43.3% |
| 2025 regular | 997 | 45.4% | 42.8% | 25.1% (506 passes) | 57.2% |
| 2025 postseason | 188 | 45.2% | 48.1% | 26.8% (97 passes) | 61.7% |

The 2026 PBP cohort has **501** Seattle run/pass rows through Week 8, but no per-play participation or FTN charting. PBP alone shows 51.7% shotgun and 3.4% no-huddle in those rows. These are not directly comparable to the participation/FTN columns above. The Sharp article reports 78% to 44% for 3+ WR, 21% to 43% for 2+ TE, and 19% to 28% play action from 2024 to 2025; the local personnel shares are close. The local play-action field is a share of pass rows with a non-null FTN tag, while the article's published statistic is a dropback rate, so the two play-action estimates should not be treated as identical.

For a calendar-matched player comparison, 2025 Weeks 1–8 and 2026 Weeks 1–8 have receiver IDs for 183/204 and 251/279 pass rows, respectively. Among rows with a receiver ID, Jaxon Smith-Njigba accounts for **38.3% (70 targets)** in the 2025 slice and **35.5% (89)** in the 2026 slice. In 2026 the shares are Rashid Shaheed 12.4% (31), Cooper Kupp 12.0% (30), AJ Barner 13.5% (34), and Tory Horton 6.8% (17). The player snap-count source gives Smith-Njigba **76.2%** of Seattle's offensive snaps in 2025 Weeks 1–8 and **85.0%** in 2026 Weeks 1–8. These counts show the concentration of recorded targets and snaps; they cannot establish route quality or whether an opportunity was created by a particular concept. Full target and snap rows are in the [target file](phase5_seahawks_targets_2026-11-03.csv) and [snap-share file](phase5_seahawks_player_snap_share_2026-11-03.csv).

The cited qualitative sources are now checked with scope caveats. Sharp's **2026-08-31** preview reports the personnel/play-action changes. The Seahawks' **2026-07-30** article describes Fleury's continuity and shared Shanahan background. NFL.com/The Athletic's **2026-09-11** Week 1 account describes Smith-Njigba backfield alignments, Barner's under-center package and an unbalanced formation. Seattle Sports' related secondary-receiver article was published **October 19**, not October 22; the October 22 article discusses Seattle's ineffective rushing attack and its effect on the passing offense. Field Gulls' **2025-12-24** All-22 article offers qualitative sequencing interpretations. These are linked and graded in the [external evidence table](phase3_6_external_evidence_2026-11-03.csv); none was used to assign a play-concept label.

## Phase 6: predictive evaluation — PASS for source-field distributions; workload simulation not evaluated

All test cutoffs are chronological and stop before the target team-game. Forecasts start at Week 2. Models are (1) previous-season static, (2) current-season expanding, (3) last four team games, and (4) adaptive exponentially weighted history with a fixed four-team-game half-life. Dirichlet smoothing uses alpha 0.5. The run/pass, action-signature, formation and personnel-group distributions are scored separately. Personnel is normalized to the recorded RB/TE/WR counts; raw offensive-line counts are not treated as a play identity. Formation cross-season scoring starts in 2024 because the 2022 source vocabulary differs from 2023 onward. The 2026 formation/personnel cohorts are unavailable.

| Family | Test rows | Previous season | Expanding current season | Last 4 games | Adaptive, 4-game half-life |
|---|---:|---:|---:|---:|---:|
| Run/pass | 107,523 | 0.9851 | 0.9860 | 0.9880 | **0.9827** |
| Four-field action signature | 107,523 | 3.2025 | 3.2176 | 3.2341 | **3.1944** |
| Formation | 94,524* | 1.2730* | **1.1365** | 1.1401 | 1.1834* |
| RB/TE/WR personnel group | 90,968 | 1.8808 | 1.5187 | **1.5148** | 1.5459 |

Metric is mean log loss in bits per held-out row; lower is better. `*` Previous-season and adaptive formation figures use 2024–25 only (62,581 rows) to avoid the 2022/2023 source-label break. Model-specific denominators and weeks are in [the comparison CSV](phase6_model_comparison_2026-11-03.csv).

Paired 2,000-replicate franchise-cluster bootstrap intervals compare each model with expanding current season. The adaptive model improves action-signature log loss by **0.0232 bits/play** (95% CI: **0.0210–0.0254** lower) and run/pass by **0.00330 bits/play** (95% CI: **0.00225–0.00436** lower). Last-four-games action loss is 0.0165 bits/play worse (95% CI: 0.0146–0.0184). For personnel, last-four and expanding are statistically unresolved (difference −0.0039; CI −0.0102 to 0.0024); the previous-season baseline is 0.362 bits/play worse (CI 0.245–0.495). Formation's adaptive improvement versus expanding is unresolved (−0.0044; CI −0.0106 to +0.0011). Full intervals are in [the bootstrap file](phase6_franchise_bootstrap_2026-11-03.csv).

Run/pass calibration is reported with multiclass Brier score. Signature novelty uses the probability assigned to an aggregate “unseen descriptor” bucket; it does not predict the identity of the unseen signature. For action signatures, expanding history predicts 0.18% unseen rows against 0.31% observed; the [novelty calibration file](phase6_novelty_calibration_2026-11-03.csv) contains bin-level predicted and observed rates. This is calibration of descriptor novelty only.

No closed-loop player-workload simulation was run. The worktree instruction forbids changing SLC model code; moreover 2026 lacks per-play participation, so this data cannot evaluate counterfactual player workloads from 2026 play distributions. Observed snap counts above are descriptive outcomes, not a closed-loop forecast.

## Phase outcomes

| Phase | Result |
|---|---|
| 3 Coaching continuity | **Partial.** Head coaches measured league-wide; coordinator/play-caller tenure only source-checked for Seattle. |
| 4 Postseason | **Pass at execution-descriptor level.** Concept-level postseason novelty and reuse remain unresolved. |
| 5 Seahawks | **Partial.** Personnel, chart tags, targets, snaps and raw action matches measured; concepts remain unresolved. |
| 6 Predictive evaluation | **Pass for source-field forecasts.** Closed-loop workload impact not evaluated. |

The project is complete as a reproducible measurement pass. Exact play ancestry, imported concepts and closed-loop player-workload gains remain **not demonstrated**. No SLC model code, `main`, or `dev` was changed.
