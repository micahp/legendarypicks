# NHL JC-DIAG5: candidate-minus-M0 delta persistence

**Base:** `1dcd616906ee39ff46d4d117bd93ff627b24687e`. **Preregistration commit:** `f4791c943d1d769bc1b429ef384ef9c0e90c6a4a`.
**Branch:** `research/nhl-multi-agent-movement-2026-10-23`.

## 1. Population and boundary

Same frozen population as DIAG4: 10 development games, leave-one-whole-game-out predictions, 200 rollout starts (172 group-scored at +45), 2,164 +45 within-team pairs (1,064 Home / 1,100 Away), 142 EqualTeam +45 start/team cells; horizons are ordinal Image Id increments, **not seconds**; no independent tracking population; pairs and starts are not independent — every interval is the same 10-whole-game cluster bootstrap, 10,000 draws, seed 20261024, equal game weight, one matrix shared across all estimates.

No positions, identities, outcomes, or labels were added. The comparison uses only the frozen development arrays and read-only derived values. Horizons remain ordinal observations.

## 2. Registered interpretation (Q5; fixed before results)

Pair-specific residual structure would remain a live descriptive explanation only if at least one of M1 or M2 has a positive +15→+45 corrected-delta observed-minus-null gap whose whole-game 95% interval is entirely above zero, and that candidate's two adjacent-transition point gaps are also positive. The pattern that closes this line is that neither candidate meets that primary rule, especially when the candidate-only DIAG4 series remains above its null: that combination is consistent with structure shared with M0 surviving in the candidate series but cancelling in the delta. In that case, explicitly state that a pair-intent label program is not justified by these results. Any other pattern is mixed/inconclusive under this preregistration. No outcome changes a threshold or gate.

## 3. Provenance gate

Gate: **PASS**. Named source hashes: 10/10; DIAG4 frozen assertions: 18/18; re-run DIAG4 checks: 22/22.

| Input | Expected SHA-256 | Actual SHA-256 | Status |
|---|---|---|---|
| jc_results | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` | `0bec6b2ad5430ee080b357b745c9c4f811bb80005aadfd52911e05d601b3624c` | PASS |
| fold_models | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` | `194bae36e356186d50ae2a12afca557f616584bdf96baa2bbc2ffc0b555fd81a` | PASS |
| movement_comparison | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` | `1f38c1c83b454558d8a48e285a3478f899b3dcc94a4dbc7e9028805de171cbf8` | PASS |
| scenario_archive | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` | `a036d9edd981905646f5efce0b0c340b3fcd7bacaef8037b18e9350395fcacce` | PASS |
| rollout_starts | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` | `07d8523d9e8d89748981f326cce92d3bcedb899feea51b5bc12caa8e04a2a5de` | PASS |
| jc_diag_results | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` | `f47910cde7e09865299667c1c2a6603d9c749e48fb1fed3e3eec0c7da5752e8c` | PASS |
| jc_diag2_results | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` | `54dbb4e6322dc240ac42910f3c69bab9dfcd781c89e234fa2161d8068b8ed3ed` | PASS |
| jc_diag3_results | `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd` | `e2003ce0f3702f0d94d2915c512b74320ff4f2aed04b3af5137a3d01286051fd` | PASS |
| jc_diag4_preregistration | `66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0` | `66dd39e8b48e266c7b06bf751921234f04f8b696e8f752117030f2766e05e1a0` | PASS |
| jc_diag4_results | `cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947` | `cf9681fa36416ce56996b66c1179c7f17a30a4ed544a0b07b5cd59d896cdc947` | PASS |
| jc_diag2_preregistration | `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234` | `2c0e395badf81de7df0ee488e2bc0f4fa239400ae6d6b077594007c08206d234` | PASS |
| jc_diag3_preregistration | `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de` | `96a933c0e0bdff517e84c3598896a4d6dc0dccea358958dd8409f72d3b1789de` | PASS |
| diag4_evaluator | `2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a` | `2be67e32762b43ed3cfcfaab69c0297e185c254d241c68255b7361a9d921e56a` | PASS |

All 22 DIAG4 post-compute checks were recalculated in memory from the frozen arrays and compared with both their registered DIAG2/DIAG3 values and the frozen DIAG4 JSON. No DIAG4 output was written.

## Q1. Delta level and spread

Delta is candidate pair-distance error minus the M0 error on the same pair. EqualTeam summaries give equal Home/Away weight within start, equal starts within game, then equal games. Pair spread is pair-weighted.

| Horizon | Model | Group | Equal-game mean [95% whole-game interval], ft | Per-game values, G1–G10, ft | Eligible cells / EqualTeam starts |
|---:|---|---|---:|---|---:|
| +15 | M1 | EqualTeam | -1.2354 [-1.3167, -1.1534] | -1.455, -1.135, -1.019, -1.057, -1.162, -1.295, -1.313, -1.357, -1.350, -1.211 | 332 / 160 |
| +15 | M1 | Home | -1.2376 [-1.3057, -1.1704] | -1.302, -1.257, -1.193, -1.069, -1.180, -1.289, -1.414, -1.393, -1.164, -1.115 | 332 / 160 |
| +15 | M1 | Away | -1.1917 [-1.3377, -1.0567] | -1.607, -1.012, -0.846, -0.974, -1.166, -1.300, -1.206, -1.138, -1.565, -1.103 | 332 / 160 |
| +15 | M2 | EqualTeam | -1.2367 [-1.3180, -1.1535] | -1.453, -1.163, -1.040, -1.015, -1.166, -1.297, -1.321, -1.356, -1.346, -1.211 | 332 / 160 |
| +15 | M2 | Home | -1.2269 [-1.2896, -1.1637] | -1.294, -1.222, -1.236, -1.089, -1.168, -1.301, -1.392, -1.339, -1.146, -1.083 | 332 / 160 |
| +15 | M2 | Away | -1.2041 [-1.3530, -1.0626] | -1.611, -1.104, -0.843, -0.874, -1.187, -1.293, -1.241, -1.184, -1.575, -1.130 | 332 / 160 |
| +30 | M1 | EqualTeam | -2.8491 [-3.0368, -2.6613] | -3.479, -2.773, -2.240, -2.607, -2.605, -3.029, -2.956, -2.956, -2.926, -2.918 | 320 / 149 |
| +30 | M1 | Home | -2.8474 [-2.9825, -2.7043] | -3.136, -2.987, -2.406, -2.688, -2.711, -2.976, -3.106, -3.062, -2.641, -2.762 | 320 / 149 |
| +30 | M1 | Away | -2.7668 [-3.0468, -2.5047] | -3.684, -2.559, -2.014, -2.392, -2.735, -3.071, -2.827, -2.513, -3.242, -2.630 | 320 / 149 |
| +30 | M2 | EqualTeam | -2.8618 [-3.0474, -2.6759] | -3.477, -2.855, -2.272, -2.550, -2.637, -3.046, -2.963, -2.981, -2.919, -2.918 | 320 / 149 |
| +30 | M2 | Home | -2.8487 [-2.9803, -2.7137] | -3.121, -3.037, -2.462, -2.699, -2.710, -3.009, -3.082, -3.020, -2.617, -2.730 | 320 / 149 |
| +30 | M2 | Away | -2.7873 [-3.0672, -2.5169] | -3.689, -2.674, -2.013, -2.272, -2.792, -3.070, -2.863, -2.590, -3.254, -2.657 | 320 / 149 |
| +45 | M1 | EqualTeam | -4.4352 [-4.7838, -4.1083] | -5.729, -4.444, -3.360, -3.975, -4.337, -4.409, -4.539, -4.447, -4.657, -4.455 | 311 / 142 |
| +45 | M1 | Home | -4.4558 [-4.6614, -4.2191] | -5.059, -4.696, -3.596, -4.405, -4.612, -4.398, -4.587, -4.654, -4.230, -4.322 | 311 / 142 |
| +45 | M1 | Away | -4.2364 [-4.6869, -3.8464] | -5.920, -4.191, -3.091, -3.820, -4.201, -4.381, -4.306, -3.787, -4.722, -3.947 | 311 / 142 |
| +45 | M2 | EqualTeam | -4.4559 [-4.7959, -4.1277] | -5.716, -4.569, -3.400, -3.927, -4.380, -4.429, -4.566, -4.470, -4.649, -4.454 | 311 / 142 |
| +45 | M2 | Home | -4.4653 [-4.6673, -4.2357] | -5.022, -4.788, -3.646, -4.459, -4.612, -4.436, -4.563, -4.629, -4.204, -4.293 | 311 / 142 |
| +45 | M2 | Away | -4.2697 [-4.7205, -3.8718] | -5.926, -4.349, -3.098, -3.741, -4.271, -4.380, -4.380, -3.851, -4.732, -3.969 | 311 / 142 |

| Horizon | Model | Pair count | Mean | SD | Min | Q1 | Median | Q3 | Max |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| +15 | M1 | 2542 | -1.146 | 1.038 | -4.921 | -1.803 | -1.094 | -0.470 | 2.798 |
| +15 | M2 | 2542 | -1.148 | 1.088 | -5.334 | -1.832 | -1.127 | -0.448 | 2.798 |
| +30 | M1 | 2329 | -2.656 | 2.160 | -10.823 | -4.015 | -2.492 | -1.162 | 5.051 |
| +30 | M2 | 2329 | -2.671 | 2.196 | -11.273 | -4.054 | -2.546 | -1.151 | 5.051 |
| +45 | M1 | 2164 | -4.035 | 3.018 | -16.333 | -5.916 | -3.736 | -1.888 | 6.063 |
| +45 | M2 | 2164 | -4.058 | 3.045 | -16.735 | -5.952 | -3.842 | -1.893 | 6.063 |

### +45 delta residual variance decomposition

| Model | Between-start variance | Within-start variance | Between-start share | Eligible starts / games |
|---|---:|---:|---:|---:|
| M1 | 2.70583 | 7.19291 | 0.2734 | 142 / 10 |
| M2 | 2.64499 | 7.35985 | 0.2644 | 142 / 10 |

### LOOG team×horizon delta offsets

Offsets are the equal-game mean of the other nine game-level team cell means and are repeated across the held-out game's starts.

| Held-out game | Team | Horizon | M1 offset, ft | M2 offset, ft |
|---|---|---:|---:|---:|
| 2025-10-11.Team.A.@.Team.D | Home | +15 | -1.23050 | -1.21947 |
| 2025-10-11.Team.A.@.Team.D | Home | +30 | -2.81529 | -2.81834 |
| 2025-10-11.Team.A.@.Team.D | Home | +45 | -4.38878 | -4.40345 |
| 2025-10-11.Team.A.@.Team.D | Away | +15 | -1.14553 | -1.15887 |
| 2025-10-11.Team.A.@.Team.D | Away | +30 | -2.66485 | -2.68716 |
| 2025-10-11.Team.A.@.Team.D | Away | +45 | -4.04938 | -4.08566 |
| 2025-10-17.Team.F.@.Team.L | Home | +15 | -1.23543 | -1.22749 |
| 2025-10-17.Team.F.@.Team.L | Home | +30 | -2.83190 | -2.82777 |
| 2025-10-17.Team.F.@.Team.L | Home | +45 | -4.42909 | -4.42945 |
| 2025-10-17.Team.F.@.Team.L | Away | +15 | -1.21164 | -1.21521 |
| 2025-10-17.Team.F.@.Team.L | Away | +30 | -2.78980 | -2.79986 |
| 2025-10-17.Team.F.@.Team.L | Away | +45 | -4.24153 | -4.26086 |
| 2025-10-24.Team.B.@.Team.A | Home | +15 | -1.24262 | -1.22588 |
| 2025-10-24.Team.B.@.Team.A | Home | +30 | -2.89638 | -2.89165 |
| 2025-10-24.Team.B.@.Team.A | Home | +45 | -4.55141 | -4.55634 |
| 2025-10-24.Team.B.@.Team.A | Away | +15 | -1.23016 | -1.24425 |
| 2025-10-24.Team.B.@.Team.A | Away | +30 | -2.85046 | -2.87334 |
| 2025-10-24.Team.B.@.Team.A | Away | +45 | -4.36374 | -4.39980 |
| 2025-10-24.Team.E.@.Team.D | Home | +15 | -1.25633 | -1.24230 |
| 2025-10-24.Team.E.@.Team.D | Home | +30 | -2.86508 | -2.86524 |
| 2025-10-24.Team.E.@.Team.D | Home | +45 | -4.46153 | -4.46604 |
| 2025-10-24.Team.E.@.Team.D | Away | +15 | -1.21591 | -1.24078 |
| 2025-10-24.Team.E.@.Team.D | Away | +30 | -2.80843 | -2.84462 |
| 2025-10-24.Team.E.@.Team.D | Away | +45 | -4.28272 | -4.32837 |
| 2025-10-28.Team.C.@.Team.A | Home | +15 | -1.24404 | -1.23352 |
| 2025-10-28.Team.C.@.Team.A | Home | +30 | -2.86250 | -2.86401 |
| 2025-10-28.Team.C.@.Team.A | Home | +45 | -4.43851 | -4.44902 |
| 2025-10-28.Team.C.@.Team.A | Away | +15 | -1.19462 | -1.20601 |
| 2025-10-28.Team.C.@.Team.A | Away | +30 | -2.77026 | -2.78684 |
| 2025-10-28.Team.C.@.Team.A | Away | +45 | -4.24039 | -4.26956 |
| 2025-10-29.Team.G.@.Team.L | Home | +15 | -1.23189 | -1.21870 |
| 2025-10-29.Team.G.@.Team.L | Home | +30 | -2.83310 | -2.83087 |
| 2025-10-29.Team.G.@.Team.L | Home | +45 | -4.46228 | -4.46854 |
| 2025-10-29.Team.G.@.Team.L | Away | +15 | -1.17971 | -1.19423 |
| 2025-10-29.Team.G.@.Team.L | Away | +30 | -2.73299 | -2.75592 |
| 2025-10-29.Team.G.@.Team.L | Away | +45 | -4.22038 | -4.25744 |
| 2025-11-02.Team.D.@.Team.A | Home | +15 | -1.21805 | -1.20858 |
| 2025-11-02.Team.D.@.Team.A | Home | +30 | -2.81868 | -2.82274 |
| 2025-11-02.Team.D.@.Team.A | Home | +45 | -4.44128 | -4.45444 |
| 2025-11-02.Team.D.@.Team.A | Away | +15 | -1.19009 | -1.20002 |
| 2025-11-02.Team.D.@.Team.A | Away | +30 | -2.76004 | -2.77893 |
| 2025-11-02.Team.D.@.Team.A | Away | +45 | -4.22876 | -4.25739 |
| 2025-11-16.Team.H.@.Team.K | Home | +15 | -1.22031 | -1.21447 |
| 2025-11-16.Team.H.@.Team.K | Home | +30 | -2.82357 | -2.82958 |
| 2025-11-16.Team.H.@.Team.K | Home | +45 | -4.43380 | -4.44712 |
| 2025-11-16.Team.H.@.Team.K | Away | +15 | -1.19771 | -1.20627 |
| 2025-11-16.Team.H.@.Team.K | Away | +30 | -2.79491 | -2.80920 |
| 2025-11-16.Team.H.@.Team.K | Away | +45 | -4.28633 | -4.31620 |
| 2025-11-19.Team.I.@.Team.K | Home | +15 | -1.24583 | -1.23593 |
| 2025-11-19.Team.I.@.Team.K | Home | +30 | -2.87032 | -2.87444 |
| 2025-11-19.Team.I.@.Team.K | Home | +45 | -4.48091 | -4.49435 |
| 2025-11-19.Team.I.@.Team.K | Away | +15 | -1.15023 | -1.16287 |
| 2025-11-19.Team.I.@.Team.K | Away | +30 | -2.71399 | -2.73550 |
| 2025-11-19.Team.I.@.Team.K | Away | +45 | -4.18251 | -4.21832 |
| 2025-11-28.Team.J.@.Team.K | Home | +15 | -1.25126 | -1.24297 |
| 2025-11-28.Team.J.@.Team.K | Home | +30 | -2.85690 | -2.86187 |
| 2025-11-28.Team.J.@.Team.K | Home | +45 | -4.47069 | -4.48445 |
| 2025-11-28.Team.J.@.Team.K | Away | +15 | -1.20158 | -1.21237 |
| 2025-11-28.Team.J.@.Team.K | Away | +30 | -2.78195 | -2.80176 |
| 2025-11-28.Team.J.@.Team.K | Away | +45 | -4.26859 | -4.30303 |

## Q2. Corrected delta persistence

The +45 delta level is strongly negative on the registered signed-error scale (see Q1), so Q2 removes the other-nine-game team×horizon level before computing persistence.

Observed, permutation-null, and paired-gap intervals use equal games and the shared whole-game bootstrap matrix. A positive gap is called above the null only when its entire 95% interval is positive.

| Transition | Model | Observed share [95%] | Null [95%] | Gap [95%] | EqualTeam starts | Cells / zero-mass cells | Exclusions |
|---|---|---:|---:|---:|---:|---:|---|
| plus15_to_plus45 | M1 | 0.9440 [0.9128, 0.9698] | 0.5580 [0.5205, 0.5962] | 0.3860 [0.3464, 0.4273] | 103 | 311 / 56 | {"fewer_than_three_common_pairs": 33} |
| plus15_to_plus45 | M2 | 0.9148 [0.8830, 0.9469] | 0.5588 [0.5181, 0.5980] | 0.3560 [0.3190, 0.3942] | 105 | 311 / 51 | {"fewer_than_three_common_pairs": 33} |
| plus15_to_plus30 | M1 | 0.9647 [0.9369, 0.9857] | 0.5570 [0.5185, 0.5970] | 0.4077 [0.3658, 0.4502] | 109 | 320 / 51 | {"fewer_than_three_common_pairs": 24} |
| plus15_to_plus30 | M2 | 0.9355 [0.9071, 0.9632] | 0.5597 [0.5165, 0.6015] | 0.3758 [0.3348, 0.4167] | 110 | 320 / 51 | {"fewer_than_three_common_pairs": 24} |
| plus30_to_plus45 | M1 | 0.9911 [0.9816, 0.9974] | 0.5836 [0.5432, 0.6250] | 0.4075 [0.3664, 0.4480] | 102 | 309 / 56 | {"fewer_than_three_common_pairs": 35} |
| plus30_to_plus45 | M2 | 0.9911 [0.9818, 0.9975] | 0.5835 [0.5433, 0.6247] | 0.4077 [0.3674, 0.4483] | 104 | 309 / 51 | {"fewer_than_three_common_pairs": 35} |

## Q3. M0, candidate-only, and delta comparison

All three rows use the same fixed development population and the registered within-cell null. Candidate-only rows are re-derived with DIAG4's frozen LOOG team×horizon correction; delta rows use the Q2 delta correction.

| Transition | Series | Observed [95%] | Null [95%] | Gap [95%] | EqualTeam starts | Descriptive result |
|---|---|---:|---:|---:|---:|---|
| plus15_to_plus45 | M0 raw | 0.7630 [0.7271, 0.8025] | 0.4782 [0.4524, 0.5111] | 0.2848 [0.2542, 0.3256] | 122 | above null interval |
| plus15_to_plus45 | M1 candidate-only, DIAG4 correction | 0.7821 [0.7425, 0.8219] | 0.5064 [0.4753, 0.5420] | 0.2757 [0.2384, 0.3112] | 119 | above null interval |
| plus15_to_plus45 | M2 candidate-only, DIAG4 correction | 0.7822 [0.7412, 0.8230] | 0.5086 [0.4779, 0.5437] | 0.2736 [0.2331, 0.3115] | 119 | above null interval |
| plus15_to_plus45 | M1 candidate-minus-M0 delta | 0.9440 [0.9128, 0.9698] | 0.5580 [0.5205, 0.5962] | 0.3860 [0.3464, 0.4273] | 103 | above null interval |
| plus15_to_plus45 | M2 candidate-minus-M0 delta | 0.9148 [0.8830, 0.9469] | 0.5588 [0.5181, 0.5980] | 0.3560 [0.3190, 0.3942] | 105 | above null interval |
| plus15_to_plus30 | M0 raw | 0.8541 [0.8358, 0.8703] | 0.4950 [0.4705, 0.5260] | 0.3591 [0.3340, 0.3824] | 127 | above null interval |
| plus15_to_plus30 | M1 candidate-only, DIAG4 correction | 0.8858 [0.8550, 0.9176] | 0.5280 [0.4908, 0.5699] | 0.3579 [0.3274, 0.3869] | 124 | above null interval |
| plus15_to_plus30 | M2 candidate-only, DIAG4 correction | 0.8853 [0.8496, 0.9197] | 0.5301 [0.4924, 0.5728] | 0.3552 [0.3253, 0.3839] | 124 | above null interval |
| plus15_to_plus30 | M1 candidate-minus-M0 delta | 0.9647 [0.9369, 0.9857] | 0.5570 [0.5185, 0.5970] | 0.4077 [0.3658, 0.4502] | 109 | above null interval |
| plus15_to_plus30 | M2 candidate-minus-M0 delta | 0.9355 [0.9071, 0.9632] | 0.5597 [0.5165, 0.6015] | 0.3758 [0.3348, 0.4167] | 110 | above null interval |
| plus30_to_plus45 | M0 raw | 0.9055 [0.8800, 0.9291] | 0.5084 [0.4831, 0.5353] | 0.3971 [0.3778, 0.4197] | 121 | above null interval |
| plus30_to_plus45 | M1 candidate-only, DIAG4 correction | 0.9075 [0.8796, 0.9350] | 0.5267 [0.4874, 0.5659] | 0.3808 [0.3550, 0.4082] | 118 | above null interval |
| plus30_to_plus45 | M2 candidate-only, DIAG4 correction | 0.9115 [0.8876, 0.9343] | 0.5288 [0.4894, 0.5690] | 0.3828 [0.3563, 0.4092] | 118 | above null interval |
| plus30_to_plus45 | M1 candidate-minus-M0 delta | 0.9911 [0.9816, 0.9974] | 0.5836 [0.5432, 0.6250] | 0.4075 [0.3664, 0.4480] | 102 | above null interval |
| plus30_to_plus45 | M2 candidate-minus-M0 delta | 0.9911 [0.9818, 0.9975] | 0.5835 [0.5433, 0.6247] | 0.4077 [0.3674, 0.4483] | 104 | above null interval |

On the primary +15→+45 transition, M0 raw, both DIAG4-corrected candidate series, and both corrected candidate-minus-M0 deltas are above their within-start nulls by the registered interval rule. M1 delta gap 0.3860 [0.3464, 0.4273]; M2 delta gap 0.3560 [0.3190, 0.3942]. The delta series therefore retains pair-linked persistence after cancellation against M0; the observed pattern is not explained solely by a component shared with M0. This comparison does not identify its cause.


## Q4. Symmetry, zero mass, hand checks, distance

### Sign flip, primary transition

| Direction | Model | Observed [95%] | Null [95%] | Gap [95%] | EqualTeam starts |
|---|---|---:|---:|---:|---:|
| d | M1 | 0.9440 [0.9128, 0.9698] | 0.5580 [0.5205, 0.5962] | 0.3860 [0.3464, 0.4273] | 103 |
| d | M2 | 0.9148 [0.8830, 0.9469] | 0.5588 [0.5181, 0.5980] | 0.3560 [0.3190, 0.3942] | 105 |
| minus_d | M1 | 0.9590 [0.9327, 0.9792] | 0.5689 [0.5131, 0.6178] | 0.3901 [0.3379, 0.4530] | 112 |
| minus_d | M2 | 0.9393 [0.9103, 0.9657] | 0.5540 [0.5021, 0.6005] | 0.3853 [0.3366, 0.4474] | 112 |

Both sign orientations have positive gap intervals for M1 and M2; the observed persistence is not unique to the negative orientation of the delta.

Exact zeros and zero negative-mass pairs:

- M1: +15 exact zero 0/2542; +30 0/2329; +45 exact zero 0/2164; +45 zero negative mass 156/2164.
- M2: +15 exact zero 0/2542; +30 0/2329; +45 exact zero 0/2164; +45 zero negative mass 161/2164.

Hand-check rows (candidate − M0 asserted):

- M1: `2025-10-11.Team.A.@.Team.D | 2025-10-11.Team.A.@.Team.D|P1|101135 | Away | ['2025-10-11.Team.A.@.Team.D|P1|Away|2525', '2025-10-11.Team.A.@.Team.D|P1|Away|2527']`; M0 `9.613033667602`, candidate `-0.252692132793`, delta `-9.865725800396` ft; assert `True`.
- M2: `2025-10-11.Team.A.@.Team.D | 2025-10-11.Team.A.@.Team.D|P1|101135 | Away | ['2025-10-11.Team.A.@.Team.D|P1|Away|2525', '2025-10-11.Team.A.@.Team.D|P1|Away|2531']`; M0 `10.769964338775`, candidate `3.113632255903`, delta `-7.656332082872` ft; assert `True`.

### Fixed DIAG4 cutoff-distance bins

The edges were held at the DIAG4 values; no bin was refit. The candidate-only comparison is the frozen DIAG4 residual using its already-fitted coefficients.

| Model | Bin | Pair count | Δ mean [95%] ft | DIAG4 candidate residual mean [95%] ft |
|---|---:|---:|---:|---:|
| M1 | 1 | 537 | -2.1366 [-2.3893, -1.9224] | 1.7907 [1.5594, 2.0205] |
| M1 | 2 | 531 | -3.2930 [-3.6614, -2.8931] | 0.9256 [0.5043, 1.3651] |
| M1 | 3 | 531 | -4.6185 [-4.9068, -4.3954] | -0.1221 [-0.3827, 0.1030] |
| M1 | 4 | 532 | -6.4563 [-6.7555, -6.0863] | -1.6641 [-1.9925, -1.2880] |
| M2 | 1 | 537 | -2.1567 [-2.4252, -1.9253] | 1.7860 [1.5337, 2.0336] |
| M2 | 2 | 531 | -3.3224 [-3.6917, -2.9183] | 0.9151 [0.4939, 1.3586] |
| M2 | 3 | 531 | -4.6409 [-4.9233, -4.4299] | -0.1224 [-0.3764, 0.0904] |
| M2 | 4 | 532 | -6.5273 [-6.8311, -6.1433] | -1.7096 [-2.0350, -1.3262] |
- M1 bin-4-minus-bin-1 signed gradient: delta -4.3197 ft; frozen DIAG4 candidate residual -3.4549 ft; delta magnitude is **amplified**.
- M2 bin-4-minus-bin-1 signed gradient: delta -4.3706 ft; frozen DIAG4 candidate residual -3.4956 ft; delta magnitude is **amplified**.

## Decision

The registered +15→+45 corrected-delta gap rule is met by M1, M2; each also has positive point gaps on both adjacent transitions. Candidate-minus-M0 persistence remains after cancellation against M0 in these ten development games. This does not identify a behavioral mechanism or warrant changing the research workflow.

This is a descriptive comparison of ten previously inspected development games. No production state or frozen input was changed. Image Id is ordinal, not validated elapsed time; cross-game athlete identity and independent-game coverage remain unresolved.

## Reproduction

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py --gate-only
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 /usr/bin/python3 research/nhl-multi-agent-movement-2026-10-23/diagnose_delta_persistence.py --output /tmp/jc-diag5-delta-persistence-repeat.json --no-report
cmp research/nhl-multi-agent-movement-2026-10-23/results/jc-diag5-delta-persistence-2026-10-23-v1.json /tmp/jc-diag5-delta-persistence-repeat.json
```
