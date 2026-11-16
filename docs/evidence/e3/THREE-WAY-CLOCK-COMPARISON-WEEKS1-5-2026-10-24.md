# E3 three-way clock comparison: 2022 weeks 1–5

## Result

All three approaches were scored on the same 7,700 PBP play rows and the same 1,619 drives. The target is the same-quarter game-clock delta from the current PBP play stamp to the next PBP row with a non-null `play_type`. This is a published-play clock delta, not an official whistle time or wall-clock duration.

| Approach | MAE (seconds) | Common scored rows | Common drives | Native prediction coverage |
| --- | ---: | ---: | ---: | --- |
| A. E1 sampled runoff | 10.4067 | 7,700 | 1,619 | 9,228 rows predicted; 9,060 resolved-target rows; 1,669 drives |
| B. PBP conditional | 6.1744 | 7,700 | 1,619 | 13,592 rows predicted; 13,246 resolved-target rows; 1,751 drives |
| C. Tracking-informed | 5.9928 | 7,700 | 1,619 | 8,883 rows predicted and target-resolved; 1,635 drives |

The differences are real on this paired sample. A is worse than B by a mean 4.2324 seconds of per-play absolute error; A is worse than C by 4.4139 seconds. C is lower than B by 0.1815 seconds on average, with C lower on 4,129 rows, B lower on 3,311, and 260 ties.

The C result is retrospective: it adds the same play’s future tracking terminal-minus-snap duration and predicts a PBP-clock residual from the other weeks in the fold. That 0.1815-second edge does not establish a prospective clock-prediction gain. B’s PBP-only result is the usable predictive comparison among these three as currently defined.

## Evaluation design

- The source query is restricted to 2022 weeks 1–5. Each week is scored in a leave-one-week-out fold; week 5 trains on weeks 1–4.
- A refits the E1 observed donor pool on the other four development weeks, fixes the held-out play’s observed E1 event and state cell, and takes 100 deterministic donor draws. Its score is the mean absolute error across those draws for each play, then averaged across plays. It is a stochastic baseline, not a point prediction.
- B uses the pinned PBP-only conditional median predictions and fold assignments.
- C adds tracking duration to a same-fold PBP conditional residual median. The target play’s future tracking duration is unavailable before the play ends.
- The headline metric uses the intersection where every model predicts and the PBP target is resolved. Per-model native coverage is listed separately because the supported row sets differ.
- The week-level paired rows and drive counts are in the JSON artifact below.

Weeks 6–9 were already examined in prior E3 work. Therefore weeks 1–5 are development evidence and **none of these results are holdout-validated**.

## Reproduction and pins

```bash
python scripts/bdb/e3_three_way_clock_comparison.py \
  --tracking-timing /root/gridiron-e3-physical-timing-2026-10-24/docs/research/gridiron-e3-physical-timing-2026-10-24.json \
  --output docs/evidence/e3/three-way-clock-comparison-weeks1-5-2026-10-24.json
```

- PBP model artifact SHA-256: `0863a38c022d01a27547f7bcc1ad624bd4f37a90a1d7a16ef684a5c67f2dcf8d`
- Tracking timing artifact SHA-256: `e885fd20be7fe54f429c31f98dff11425538d331e383c90527141dd78754a63b`
- Read-only PBP slice SHA-256: `c1846eb50bb662b07e11f8c70bf7f4c5a65c34e10a2d88bd3413171c7a080eef`
- E1 donor implementation: commit `2248f7e1f9710daa3092104526ab6003a0fc3b18`; source files are separately pinned in the JSON.
- Comparison script SHA-256: `f45d9e9c4f504b247a5d0145532a87d2f827639f73fdf6507264cda5a0e3ea2a`
- Machine-readable result SHA-256: `72914a6def872ae78550f2bab2763d4a32a054e074fc0f974b1dbf3dc50ff85c`

The script also verifies that B’s training weeks are exactly the four weeks outside each held-out fold. It does not query weeks 6–9.
