# Phase 2: weekly playbook evolution

Inventory date: 2026-11-03. This analysis measures observed run/pass signatures by offense team and week. A signature is equality of recorded source fields; none is labeled as an exact play or concept.

## Reproduction

Run from the research worktree. This command rebuilds the full team-week grid, signature-frequency dataset, and aggregate JSON manifest. The dev DB is opened read-only with SQLite `query_only` enabled.

```bash
python3 research/nfl-playbook-ancestry/phase2_weekly_evolution.py --db /root/legendarypicks/backend/data/picks.dev.db --out-dir research/nfl-playbook-ancestry
```

The outputs are [the weekly team dataset](phase2_weekly_evolution_dev_2026-11-03.csv), [raw signature usage](phase2_signature_usage_dev_2026-11-03.csv.gz), the [stationary-null weekly curves](phase2_stationary_null_weekly_2026-11-03.csv), the [early/late null contrasts](phase2_stationary_null_early_late_2026-11-03.csv), and the [JSON manifest](phase2_weekly_evolution_dev_2026-11-03.json).

## Coverage

The dataset includes only regular-season PBP `run` and `pass` rows with `posteam` present. It uses exact PBP game/play keys to attach participation and FTN fields, with null values distinguished from absent source joins.

| Season | Run/pass rows | Team-weeks with plays | PBP coverage |
|---|---:|---:|---|
| 2022 | 33,770 | 542 | Weeks 1–18 |
| 2023 | 33,957 | 544 | Weeks 1–18 |
| 2024 | 33,470 | 544 | Weeks 1–18 |
| 2025 | 32,941 | 544 | Weeks 1–18 |
| 2026 | 14,910 | 242 | Weeks 1–8 |
| **Total** | **149,048** | **2,416** | 32 teams |

The 2,560-row team-season-week grid includes **144 zero-play team-weeks**, primarily bye weeks. The long-form signature table has **180,502 team-week-signature rows** across four families. Historical participation joins cover 134,138/134,138 run/pass rows; FTN joins cover 134,044/134,138. Neither source has 2026 per-play rows.

## Measurements

Four exact raw signature families are counted independently:

- **Action:** PBP `play_type`, `run_gap`, `run_location`, and `pass_location`.
- **Presentation:** source join states, raw `offense_formation` and `offense_personnel`, PBP `shotgun` and `no_huddle`, plus FTN motion/play-action/no-huddle fields.
- **Chart tags:** FTN screen-pass, RPO, trick-play, and QB-sneak fields.
- **Combined:** nested raw values from those three families.

For each team-week and family, the dataset records frequencies, number of distinct signatures, signatures and rows first seen since the previous team-week observations, entropy, HHI, top-signature share, Jensen–Shannon divergence (JSD) versus the prior cumulative catalog and previous observed team-week, and a Good–Turing singleton estimate of unseen mass. Week 1 same-season novelty is null because there is no same-season prior catalog; week 1 is compared with available prior-season action history instead.

Cross-season matching uses only the action family. Formation/personnel source encodings vary between seasons, so raw presentation signatures are compared only within season. No outcomes such as yards gained or air yards enter signature identity.

## Findings

Action descriptors are a small, coarse vocabulary: teams use about **10.5 distinct action signatures per week**. Their average same-season novel-row share drops from **1.82% in weeks 2–3**, to **0.19% in weeks 4–8**, **0.063% in weeks 9–13**, and **0.012% in weeks 14–18** (2022–25 team-week means). Mean action JSD against the prior cumulative distribution falls from **0.092 bits** in weeks 2–3 to **0.060 bits** in weeks 14–18. The prior-season action catalog already contains every week-1 action signature for all **128 team-seasons from 2023 through 2026**; the week-1 previous-season open-set loss averaged **3.233 bits/play** for 2023–25. These are raw descriptor results and do not establish concept novelty or playbook stabilization.

### Stationary-order null for signatures

For 2022–25, **2,000 permutations** jointly shuffled each team's complete game-week packages across that team's played-week labels. Each package retains the game-level counters for all four families, so the null preserves pooled signature frequencies by family, game and play counts, and cross-family co-occurrence. We compared weeks 2–3 with weeks 14–18 for novel-row share, Jensen–Shannon divergence (JSD) against the cumulative catalog, and JSD against the previous played week. The weekly output also reports the observed curve, null mean, 95% permutation interval, and permutation p-value for each family and week. The seed is **20261103**; the early/late table gives results for **128 paired team-seasons** and Holm-adjusts the 12 family-by-metric tests.

| Signature family | Metric | Observed early−late | Null mean (95% permutation interval) | Raw p | Holm p |
|---|---|---:|---:|---:|---:|
| Action | Novel-row share (pp) | 1.81 | 2.28 (1.82–2.74) | .043 | .344 |
| Action | Cumulative-catalog JSD (bits) | .0315 | .0326 (.0270–.0385) | .676 | 1.000 |
| Action | Previous-week JSD (bits) | .0015 | −.0000 (−.0080–.0081) | .697 | 1.000 |
| Presentation | Novel-row share (pp) | 22.98 | 28.07 (24.93–31.24) | .002 | .024 |
| Presentation | Cumulative-catalog JSD (bits) | .0434 | .0921 (.0640–.1230) | .003 | .030 |
| Presentation | Previous-week JSD (bits) | .0350 | .0005 (−.0358–.0408) | .086 | .602 |
| Chart tags | Novel-row share (pp) | 1.76 | 1.92 (1.60–2.26) | .338 | 1.000 |
| Chart tags | Cumulative-catalog JSD (bits) | .0077 | .0100 (.0069–.0130) | .135 | .810 |
| Chart tags | Previous-week JSD (bits) | .0002 | .0000 (−.0041–.0042) | .939 | 1.000 |
| Combined | Novel-row share (pp) | 34.87 | 38.88 (36.51–41.13) | .002 | .024 |
| Combined | Cumulative-catalog JSD (bits) | .0648 | .0916 (.0735–.1102) | .005 | .045 |
| Combined | Previous-week JSD (bits) | .0169 | .0002 (−.0216–.0228) | .147 | .810 |

For presentation and combined signatures, the observed early-to-late gaps in novelty and cumulative-catalog JSD are **smaller** than the stationary-order null; these four contrasts survive Holm adjustment. No previous-week JSD contrast survives adjustment, and action and chart-tag contrasts are consistent with the null. Thus the calendar ordering differs from a stationary shuffle for some bundled source fields, but the measured pattern is not evidence of a general playbook stabilization. These signatures are field tuples, not designed plays or concepts.

Finer raw signatures remain much less stable. For 2022–25, mean presentation-signature novelty declines from **33.9%** in weeks 2–3 to **10.9%** in weeks 14–18. Combined-signature novelty declines from **65.0%** to **30.2%**. Those values show continued changes in observed presentations and chart tags; they cannot distinguish a new concept from a changed look or a previously observed signature used in new circumstances.

The expanding action model’s open-set log loss averaged **3.284 bits/play** in weeks 2–3, **3.228** in weeks 4–8, **3.203** in weeks 9–13, and **3.203** in weeks 14–18, evaluated on 2023–25. The fixed previous-season baseline averaged **3.173**, **3.208**, **3.217**, and **3.214** bits/play in those periods. The previous-season baseline predicts better early; the expanding current-season model catches up and is slightly better from weeks 9 onward.

Across 128 paired team-seasons in complete 2022–25 seasons, weeks 2–3 open-set loss exceeded weeks 14–18 loss by **0.070 bits/play** on average; a 4,000-replicate franchise-cluster bootstrap 95% interval is **0.045 to 0.096**. On 2023–25 team-weeks, predictive entropy for the expanding model rises slightly from **3.139 bits** in weeks 2–3 to **3.174 bits** in weeks 14–18. These forecast and entropy results are separate from the stationary-order test; none identifies concepts or play designs.

## Limits and interpretation

The open-set forecast uses a Dirichlet prior with alpha 0.5 over previously observed exact action signatures plus one aggregate “unseen signature” bucket. Its loss evaluates known-versus-unseen descriptor prediction; it does not predict which unseen signature will appear. Novelty means first observed in the available dataset at that signature level, not new to the team’s playbook or to the league.

The raw combined family remains high-cardinality because it includes formation, personnel, and charting fields. The 2026 presentation and chart-tag signatures lack participation and FTN data: their low distinct counts and novelty rates are coverage effects and must not be compared with 2022–25. Only the PBP action family supports the same field coverage in 2026. External-source checks are now itemized by status and scope in the [Phase 3–6 evidence table](phase3_6_external_evidence_2026-11-03.csv); the unidentified NFL.com citation remains unverified.
