# NHL JC-DIAG7: out-of-sample value of pair identity

Source base: a7b50ffc3d597f8e7d89a5a23826e37b7107891a. Correction commit: f7be2a19d3860ff17156c0c3d0de6d411424a782. Preregistration commit: 596089cb00cf6ed64f8d11fde319cfb8786a9a60.
Branch: research/nhl-multi-agent-movement-2026-10-23.

## Population and identity boundary

Ten inspected development games, 200 rollout starts (172 with +45 scoring support), 2,164 +45 within-team pair observations, 142 EqualTeam starts, and 311 eligible team cells. Image Id remains ordinal, not seconds; there is no independent tracking sample.

The source player objects expose history, id, jersey, raw_id, team, x, and y. The id-like values are scoped track identifiers; none is verified as a stable cross-game athlete or pair key. Cross-game athlete identity is unverified, so track-ID collisions were not joined across games. B and C used the registered fallback to A for unseen pairs; Q2 is non-estimable where stable cross-game identity is required. For the preregistered training-only variance components, repeated pairs were grouped by game-period-team and sorted track IDs across starts; this generic variance grouping was never used to match a held-out identity.

## Provenance gate

Gate: **PASS**; pinned artifact hashes 22/22; DIAG6 value checks 16/16; inherited DIAG6 source hashes 17/17; inherited reassertions 41/41.

| Artifact | Path | Expected SHA-256 | Actual SHA-256 | Status |
|---|---|---|---|---|
| diag6_result | research/nhl-multi-agent-movement-2026-10-23/results/jc-diag6-distance-conditioned-2026-10-23-v1.json | 8dfe2f551727484e43c612c5e2ede85ce0d237f4f479edb89e7ad1e5e59c62ed | 8dfe2f551727484e43c612c5e2ede85ce0d237f4f479edb89e7ad1e5e59c62ed | PASS |
| diag6_corrected_report | docs/research/NHL-JC-DIAG6-REPORT-2026-10-23.md | cf72e2646e00a3da27ccff849f96e9e00cbb2f22bfd12433b4f9feba03d67e45 | cf72e2646e00a3da27ccff849f96e9e00cbb2f22bfd12433b4f9feba03d67e45 | PASS |
| diag6_evaluator | research/nhl-multi-agent-movement-2026-10-23/diagnose_distance_conditioned_persistence.py | 71e162ffa625fde1067413913d3a0ff9b63c1c64e657a24684efd73d289f1c37 | 71e162ffa625fde1067413913d3a0ff9b63c1c64e657a24684efd73d289f1c37 | PASS |
| diag6_preregistration | docs/research/NHL-JC-DIAG6-PREREG-2026-10-23.md | f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48 | f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48 | PASS |
| diag7_preregistration | docs/research/NHL-JC-DIAG7-PREREG-2026-10-23.md | e5644b1a65098ffa070cf81bbdd8e46978558358ca74696276936124823aab99 | e5644b1a65098ffa070cf81bbdd8e46978558358ca74696276936124823aab99 | PASS |
| DIAG6_source:jc_results | research/nhl-multi-agent-movement-2026-10-23/results/joint-coherence-jc-2026-10-23-v1.json | 0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c | 0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c | PASS |
| DIAG6_source:fold_models | research/nhl-multi-agent-movement-2026-10-23/results/fold_models-bc91d1610de5.json | 194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a | 194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a | PASS |
| DIAG6_source:movement_comparison | research/nhl-multi-agent-movement-2026-10-23/results/movement_comparison-bc91d1610de5.json | 1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8 | 1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8 | PASS |
| DIAG6_source:scenario_archive | research/nhl-multi-agent-movement-2026-10-23/results/scenario_archive-bc91d1610de5.json.gz | a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce | a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce | PASS |
| DIAG6_source:rollout_starts | /root/lp-research-data/nhl-multi-agent-movement-2026-10-23/rollout_starts.json.gz | 07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de | 07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de | PASS |
| DIAG6_source:jc_diag_results | research/nhl-multi-agent-movement-2026-10-23/results/jc-attribution-jcdiag-2026-10-23-v1.json | f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c | f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c | PASS |
| DIAG6_source:jc_diag2_preregistration | docs/research/NHL-JC-DIAG2-PREREG-2026-10-23.md | 2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234 | 2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234 | PASS |
| DIAG6_source:jc_diag2_results | research/nhl-multi-agent-movement-2026-10-23/results/jc-diag2-pair-persistence-2026-10-23-v1.json | 54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed | 54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed | PASS |
| DIAG6_source:jc_diag3_preregistration | docs/research/NHL-JC-DIAG3-PREREG-2026-10-23.md | 96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de | 96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de | PASS |
| DIAG6_source:jc_diag3_results | research/nhl-multi-agent-movement-2026-10-23/results/jc-diag3-pair-shrink-2026-10-23-v1.json | e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd | e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd | PASS |
| DIAG6_source:jc_diag4_preregistration | docs/research/NHL-JC-DIAG4-PREREG-2026-10-23.md | 66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0 | 66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0 | PASS |
| DIAG6_source:jc_diag4_results | research/nhl-multi-agent-movement-2026-10-23/results/jc-diag4-additive-offset-2026-10-23-v1.json | cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947 | cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947 | PASS |
| DIAG6_source:jc_diag4_evaluator | research/nhl-multi-agent-movement-2026-10-23/diagnose_additive_offset.py | 2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a | 2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a | PASS |
| DIAG6_source:jc_diag5_preregistration | docs/research/NHL-JC-DIAG5-PREREG-2026-10-23.md | 18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70 | 18b0d649eff4fd43a6250f0dba3297acdc89f5f1950aea5365c370db9bf6fd70 | PASS |
| DIAG6_source:jc_diag5_results | research/nhl-multi-agent-movement-2026-10-23/results/jc-diag5-delta-persistence-2026-10-23-v1.json | 9510d70d418c09da63a6218077b8c1e2b7cc9a11e3b7ed82e63a5457c1039099 | 9510d70d418c09da63a6218077b8c1e2b7cc9a11e3b7ed82e63a5457c1039099 | PASS |
| DIAG6_source:jc_diag5_evaluator | research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py | 2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742 | 2e4c38da94253c24b45d499bdca2bfe74520c204420d22043b386ffe061d8742 | PASS |
| DIAG6_source:jc_diag6_preregistration | docs/research/NHL-JC-DIAG6-PREREG-2026-10-23.md | f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48 | f4d9ba3340895804f346795c479f4171e37aae5ef44570f149cf3efdb0206d48 | PASS |

All frozen DIAG6 values and the full DIAG6 upstream source chain were reasserted before Q1–Q3.

## Q1. Held-out pair-delta scores

Outer leave-one-game-out scoring. A is the stored DIAG6 distance-only prediction. B adds a training-only variance-component-shrunk pair residual; C adds the unshrunk training pair residual and is only an overfit control. Metrics use identical pair rows and equal game weighting. Gaussian sigma uses inner leave-one-game-out training residuals.

| Candidate | Variant | MAE (ft) | RMSE (ft) | Mean Gaussian log score | Residual SD (ft) |
|---|---|---:|---:|---:|---:|
| M1 | A | 1.99955 | 2.59060 | -2.37518 | 2.55475 |
| M1 | B | 1.99955 | 2.59060 | -2.37518 | 2.55475 |
| M1 | C | 1.99955 | 2.59060 | -2.37518 | 2.55475 |
| M1 | B_minus_A MAE difference | 0.0000 [0.0000, 0.0000] |  |  |  |
| M1 | B_minus_A RMSE difference |  | 0.0000 [0.0000, 0.0000] |  |  |
| M1 | B_minus_A log-score difference |  |  | 0.00000 [0.00000, 0.00000] |  |
| M1 | C_minus_A MAE difference | 0.0000 [0.0000, 0.0000] |  |  |  |
| M1 | C_minus_A RMSE difference |  | 0.0000 [0.0000, 0.0000] |  |  |
| M1 | C_minus_A log-score difference |  |  | 0.00000 [0.00000, 0.00000] |  |
| M1 | B relative RMSE improvement | 0.000 [0.000, 0.000]% | materiality lower bound above 5.0%: False |  |  |

| M2 | A | 2.01946 | 2.61361 | -2.38426 | 2.57948 |
| M2 | B | 2.01946 | 2.61361 | -2.38426 | 2.57948 |
| M2 | C | 2.01946 | 2.61361 | -2.38426 | 2.57948 |
| M2 | B_minus_A MAE difference | 0.0000 [0.0000, 0.0000] |  |  |  |
| M2 | B_minus_A RMSE difference |  | 0.0000 [0.0000, 0.0000] |  |  |
| M2 | B_minus_A log-score difference |  |  | 0.00000 [0.00000, 0.00000] |  |
| M2 | C_minus_A MAE difference | 0.0000 [0.0000, 0.0000] |  |  |  |
| M2 | C_minus_A RMSE difference |  | 0.0000 [0.0000, 0.0000] |  |  |
| M2 | C_minus_A log-score difference |  |  | 0.00000 [0.00000, 0.00000] |  |
| M2 | B relative RMSE improvement | 0.000 [0.000, 0.000]% | materiality lower bound above 5.0%: False |  |  |

### Per-game held-out scores

Each game is evaluated only by its outer fold. Pair counts are common to A/B/C.

| Candidate | Game | Pairs | A MAE | B MAE | C MAE | A RMSE | B RMSE | C RMSE | A log score | B log score | C log score |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 | 2025-10-11.Team.A.@.Team.D | 186 | 2.2749 | 2.2749 | 2.2749 | 2.8803 | 2.8803 | 2.8803 | -2.4923 | -2.4923 | -2.4923 |
| M1 | 2025-10-17.Team.F.@.Team.L | 158 | 2.0077 | 2.0077 | 2.0077 | 2.5477 | 2.5477 | 2.5477 | -2.3545 | -2.3545 | -2.3545 |
| M1 | 2025-10-24.Team.B.@.Team.A | 274 | 2.4733 | 2.4733 | 2.4733 | 3.2141 | 3.2141 | 3.2141 | -2.6595 | -2.6595 | -2.6595 |
| M1 | 2025-10-24.Team.E.@.Team.D | 238 | 1.4484 | 1.4484 | 1.4484 | 1.9520 | 1.9520 | 1.9520 | -2.1656 | -2.1656 | -2.1656 |
| M1 | 2025-10-28.Team.C.@.Team.A | 243 | 2.0299 | 2.0299 | 2.0299 | 2.6250 | 2.6250 | 2.6250 | -2.3842 | -2.3842 | -2.3842 |
| M1 | 2025-10-29.Team.G.@.Team.L | 220 | 1.7374 | 1.7374 | 1.7374 | 2.2848 | 2.2848 | 2.2848 | -2.2628 | -2.2628 | -2.2628 |
| M1 | 2025-11-02.Team.D.@.Team.A | 227 | 1.7990 | 1.7990 | 1.7990 | 2.3004 | 2.3004 | 2.3004 | -2.2679 | -2.2679 | -2.2679 |
| M1 | 2025-11-16.Team.H.@.Team.K | 166 | 2.3055 | 2.3055 | 2.3055 | 2.8772 | 2.8772 | 2.8772 | -2.4908 | -2.4908 | -2.4908 |
| M1 | 2025-11-19.Team.I.@.Team.K | 249 | 1.9823 | 1.9823 | 1.9823 | 2.5506 | 2.5506 | 2.5506 | -2.3556 | -2.3556 | -2.3556 |
| M1 | 2025-11-28.Team.J.@.Team.K | 203 | 1.9373 | 1.9373 | 1.9373 | 2.4491 | 2.4491 | 2.4491 | -2.3185 | -2.3185 | -2.3185 |
| M2 | 2025-10-11.Team.A.@.Team.D | 186 | 2.2612 | 2.2612 | 2.2612 | 2.8660 | 2.8660 | 2.8660 | -2.4834 | -2.4834 | -2.4834 |
| M2 | 2025-10-17.Team.F.@.Team.L | 158 | 2.0572 | 2.0572 | 2.0572 | 2.5796 | 2.5796 | 2.5796 | -2.3668 | -2.3668 | -2.3668 |
| M2 | 2025-10-24.Team.B.@.Team.A | 274 | 2.5385 | 2.5385 | 2.5385 | 3.2759 | 3.2759 | 3.2759 | -2.6868 | -2.6868 | -2.6868 |
| M2 | 2025-10-24.Team.E.@.Team.D | 238 | 1.4625 | 1.4625 | 1.4625 | 2.0011 | 2.0011 | 2.0011 | -2.1828 | -2.1828 | -2.1828 |
| M2 | 2025-10-28.Team.C.@.Team.A | 243 | 2.0367 | 2.0367 | 2.0367 | 2.6292 | 2.6292 | 2.6292 | -2.3857 | -2.3857 | -2.3857 |
| M2 | 2025-10-29.Team.G.@.Team.L | 220 | 1.7157 | 1.7157 | 1.7157 | 2.2617 | 2.2617 | 2.2617 | -2.2580 | -2.2580 | -2.2580 |
| M2 | 2025-11-02.Team.D.@.Team.A | 227 | 1.7865 | 1.7865 | 1.7865 | 2.2815 | 2.2815 | 2.2815 | -2.2642 | -2.2642 | -2.2642 |
| M2 | 2025-11-16.Team.H.@.Team.K | 166 | 2.3435 | 2.3435 | 2.3435 | 2.9277 | 2.9277 | 2.9277 | -2.5109 | -2.5109 | -2.5109 |
| M2 | 2025-11-19.Team.I.@.Team.K | 249 | 1.9999 | 1.9999 | 1.9999 | 2.5689 | 2.5689 | 2.5689 | -2.3628 | -2.3628 | -2.3628 |
| M2 | 2025-11-28.Team.J.@.Team.K | 203 | 1.9930 | 1.9930 | 1.9930 | 2.5102 | 2.5102 | 2.5102 | -2.3413 | -2.3413 | -2.3413 |

### Pair support and shrinkage audit

| Candidate | Held-out pairs | B unseen/zero-weight | B nonzero weight | C unseen | C mean used |
|---|---:|---:|---:|---:|---:|
| M1 | 2164 | 2164 | 0 | 2164 | 0 |
| M2 | 2164 | 2164 | 0 | 2164 | 0 |

Variance components use the preregistered one-way random-intercept method-of-moments estimator. The table reports its training-only SSW, SSB, denominator, within variance, and tau²; grouping is game-period-team plus sorted track IDs across starts and is never used for held-out identity matching.

| Candidate | Outer heldout game | Variance status | N rows | J groups | Repeated groups | SSW | SSB | Between denominator | Within variance | tau² |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| M1 | 2025-10-11.Team.A.@.Team.D | estimated | 1978 | 1920 | 58 | 250.264 | 12733 | 1976.94 | 4.31489 | 2.25235 |
| M1 | 2025-10-17.Team.F.@.Team.L | estimated | 2006 | 1952 | 54 | 240.935 | 13297.3 | 2004.95 | 4.46176 | 2.29056 |
| M1 | 2025-10-24.Team.B.@.Team.A | estimated | 1890 | 1846 | 44 | 172.262 | 11508.6 | 1888.95 | 3.91505 | 2.26861 |
| M1 | 2025-10-24.Team.E.@.Team.D | estimated | 1926 | 1869 | 57 | 247.76 | 13410.9 | 1924.94 | 4.34666 | 2.74883 |
| M1 | 2025-10-28.Team.C.@.Team.A | estimated | 1921 | 1865 | 56 | 211.846 | 12683.5 | 1919.94 | 3.78296 | 2.93344 |
| M1 | 2025-10-29.Team.G.@.Team.L | estimated | 1944 | 1886 | 58 | 249.093 | 13171.4 | 1942.94 | 4.29471 | 2.61249 |
| M1 | 2025-11-02.Team.D.@.Team.A | estimated | 1937 | 1890 | 47 | 225.217 | 13143.8 | 1935.95 | 4.79186 | 2.1137 |
| M1 | 2025-11-16.Team.H.@.Team.K | estimated | 1998 | 1942 | 56 | 250.679 | 12927.7 | 1996.94 | 4.4764 | 2.12274 |
| M1 | 2025-11-19.Team.I.@.Team.K | estimated | 1915 | 1875 | 40 | 154.052 | 12792.1 | 1913.96 | 3.8513 | 2.91268 |
| M1 | 2025-11-28.Team.J.@.Team.K | estimated | 1961 | 1909 | 52 | 240.268 | 13106.7 | 1959.95 | 4.62053 | 2.18919 |
| M2 | 2025-10-11.Team.A.@.Team.D | estimated | 1978 | 1920 | 58 | 257.545 | 13006.1 | 1976.94 | 4.44043 | 2.26864 |
| M2 | 2025-10-17.Team.F.@.Team.L | estimated | 2006 | 1952 | 54 | 248.057 | 13526.9 | 2004.95 | 4.59365 | 2.27669 |
| M2 | 2025-10-24.Team.B.@.Team.A | estimated | 1890 | 1846 | 44 | 175.174 | 11655.3 | 1888.95 | 3.98122 | 2.28166 |
| M2 | 2025-10-24.Team.E.@.Team.D | estimated | 1926 | 1869 | 57 | 254.305 | 13622.3 | 1924.94 | 4.46149 | 2.74723 |
| M2 | 2025-10-28.Team.C.@.Team.A | estimated | 1921 | 1865 | 56 | 219.398 | 12933.2 | 1919.94 | 3.91782 | 2.93257 |
| M2 | 2025-10-29.Team.G.@.Team.L | estimated | 1944 | 1886 | 58 | 256.07 | 13452.1 | 1942.94 | 4.41501 | 2.64022 |
| M2 | 2025-11-02.Team.D.@.Team.A | estimated | 1937 | 1890 | 47 | 232.495 | 13420.1 | 1935.95 | 4.9467 | 2.10529 |
| M2 | 2025-11-16.Team.H.@.Team.K | estimated | 1998 | 1942 | 56 | 258.065 | 13135.3 | 1996.94 | 4.60831 | 2.09848 |
| M2 | 2025-11-19.Team.I.@.Team.K | estimated | 1915 | 1875 | 40 | 158.119 | 13029.6 | 1913.96 | 3.95298 | 2.93723 |
| M2 | 2025-11-28.Team.J.@.Team.K | estimated | 1961 | 1909 | 52 | 247.463 | 13300.5 | 1959.95 | 4.75891 | 2.1534 |

## Q2. Distance-matched pair-identity concordance

Pair observations by frozen distance bin:

| Bin | Home pairs | Away pairs | Total | Verified pair keys seen in at least two games |
|---:|---:|---:|---:|---:|
| 1 | 269 | 272 | 541 | 0 |
| 2 | 249 | 292 | 541 | 0 |
| 3 | 268 | 273 | 541 | 0 |
| 4 | 278 | 263 | 541 | 0 |

| Candidate | Q2 status | Within-pair sign agreement | Different-pair sign agreement | Difference [95%] | Within-pair Spearman | Different-pair Spearman | Difference [95%] | Eligible game-pair cells |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| M1 | not_estimable_no_verified_cross_game_pair_keys | NA | NA | NA | NA | NA | NA | 0 |
| M2 | not_estimable_no_verified_cross_game_pair_keys | NA | NA | NA | NA | NA | NA | 0 |

Q2 has no estimable concordance values because the frozen source has no verified cross-game pair identity. No derangements or Q2 bootstrap intervals were run because eligible support was zero. Numeric track-ID collisions were not treated as identity matches.

## Q3. Materiality and support

The preregistered materiality bar is 5.0% relative RMSE reduction, approximately 0.15 ft at the frozen +45 delta SD of about 3.03 ft.

| Candidate | B−A relative RMSE improvement [95%] | A-vs-B residual spread reduction [95%] | Per-game support identical |
|---|---:|---:|---|
| M1 | 0.000 [0.000, 0.000]% | 0.00000 [0.00000, 0.00000] | True |
| M2 | 0.000 [0.000, 0.000]% | 0.00000 [0.00000, 0.00000] | True |

| Held-out game | Pair count | Bin 1 | Bin 2 | Bin 3 | Bin 4 | Outer training bin counts |
|---|---:|---:|---:|---:|---:|---|
| 2025-10-11.Team.A.@.Team.D | 186 | 42 | 44 | 50 | 50 | {'1': 499, '2': 497, '3': 491, '4': 491} |
| 2025-10-17.Team.F.@.Team.L | 158 | 32 | 34 | 49 | 43 | {'1': 509, '2': 507, '3': 492, '4': 498} |
| 2025-10-24.Team.B.@.Team.A | 274 | 73 | 56 | 70 | 75 | {'1': 468, '2': 485, '3': 471, '4': 466} |
| 2025-10-24.Team.E.@.Team.D | 238 | 86 | 58 | 51 | 43 | {'1': 455, '2': 483, '3': 490, '4': 498} |
| 2025-10-28.Team.C.@.Team.A | 243 | 43 | 68 | 60 | 72 | {'1': 498, '2': 473, '3': 481, '4': 469} |
| 2025-10-29.Team.G.@.Team.L | 220 | 53 | 54 | 54 | 59 | {'1': 488, '2': 487, '3': 487, '4': 482} |
| 2025-11-02.Team.D.@.Team.A | 227 | 64 | 71 | 44 | 48 | {'1': 477, '2': 470, '3': 497, '4': 493} |
| 2025-11-16.Team.H.@.Team.K | 166 | 39 | 45 | 39 | 43 | {'1': 502, '2': 496, '3': 502, '4': 498} |
| 2025-11-19.Team.I.@.Team.K | 249 | 61 | 50 | 64 | 74 | {'1': 480, '2': 491, '3': 477, '4': 467} |
| 2025-11-28.Team.J.@.Team.K | 203 | 48 | 61 | 60 | 34 | {'1': 493, '2': 480, '3': 481, '4': 507} |

Support collapses: none.

## Decision

Registered reading applied (verbatim):

> Q1 interval includes zero → the pair-identity line closes: no correction, no labels, and the DIAG2–DIAG6 persistence is recorded as a descriptive property of the ten inspected games only. Q2 may contradict; if it does, report "structure present, immaterial out of sample" and do not narrate a winner.

The pair-identity line closes on these ten inspected development games: the Q1 B−A interval includes zero, and Q2 has no estimable verified cross-game pair identities; no correction prototype or label program is justified. Record DIAG2–DIAG6 persistence as a descriptive property of these ten games only.

This is a leave-one-game-out comparison within the same ten inspected development games, not an independent later-game evaluation. Track IDs are local; no cross-game player-pair interpretation is supported.

## Reproduction

Gate-only: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag7_oos_pair_value.py --gate-only
Full run: OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_jc_diag7_oos_pair_value.py
Checks: git diff --check; ast.parse; deterministic rerun to /tmp/jc-diag7-oos-pair-value-repeat.json with --no-report; cmp against the committed result.

Primary runtime: 25.124 seconds. Evaluator SHA-256: 199d0f759fbc0642f027f89b6167cb23abe951ce69690c2db15fc7e6b5e85dd2. Result SHA-256: fa0d853a39cc33591e1157896572c40a58e374270cf26603cd56850ae6311dce; byte count: 76326.
