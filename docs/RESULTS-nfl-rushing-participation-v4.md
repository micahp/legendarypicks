# RESULTS: NFL rushing participation v4 — discrete quantile map by tier

Run 2026-10-18 on `feat/nfl-rushing-participation-v4` (from v3 tip d7aaeb77), against the pre-registration
in `docs/SPEC-nfl-rushing-participation-v4.md` (committed `6e0908e3` before any v4 model code).

Reproduce:

```bash
cd backend
LP_DB_PATH=/root/legendarypicks/backend/data/picks.dev.db \
  /root/legendarypicks/backend/venv/bin/python nfl_rushing_quantile_map_v4.py \
    --eval-seasons 2025 2026 --json ../docs/frozen-nfl-rushing-participation-v4.json
```

7 seconds, read-only. Every number below is from that run's JSON or the two read-only audit scripts.

## Verdict: NOT_ADOPTED

**0 of 6 aggregate coverage comparisons pass.** V4 posts the best CRPS of any candidate so far — 1.7710
(2025) and 1.8015 (2026), against B0's 2.0605 and 2.0889 and v2's 1.8785 and 1.8668 — and the best MAE
(2.7104 and 2.7965, against 2.9401 and 2.9972). It still fails on coverage: 0.744 / 0.938 / 0.970 in 2025
and 0.718 / 0.928 / 0.978 in 2026, against 0.50 / 0.80 / 0.90 nominal.

This is the fourth candidate to fail this gate, and **this run also explains why**, with numbers: the
failure is structural in the gate's 50% comparison, not specific to the model. Details below. The verdict
stands exactly as pre-registered and the gate has not been touched.

## Population (identical to v1–v3, restated)

Weeks 3–18, regular season; Spec B candidates who logged for the team in its last three games with carry
mean `m > 0`; RB and FB folded into RB and **gated**, QB **reported and not gated**, WR/TE out. Outcome is
box-score carries, **0 when the player has no box-score row that week**.

| season | candidates | RB (gated) | QB (not gated) | appeared | share of outcomes that are 0 |
|---|---:|---:|---:|---:|---:|
| 2025 (fit 2024) | 2,500 | 1,714 | 786 | 0.746 | **0.379** |
| 2026 (fit 2024–25) | 489 | 349 | 140 | 0.738 | — |

## Anchors as fitted

Seven quantiles (5/10/25/50/75/90/95%) of carries among appeared training candidates, per tier, with the
tier centre used for interpolation in `m`:

| fit window | tier | n | centre | anchors |
|---|---|---:|---:|---|
| 2024 | m<3 | 627 | 1.97 | 0 / 0 / 0 / 1 / 3 / 5 / 6 |
| 2024 | 3≤m<8 | 767 | 4.82 | 0 / 1 / 2 / 5 / 8 / 12 / 14 |
| 2024 | m≥8 | 453 | 11.59 | 4 / 6 / 10 / 14 / 19 / 23 / 25 |
| 2024–25 | m<3 | 1,359 | 1.78 | 0 / 0 / 0 / 1 / 3 / 5 / 7 |
| 2024–25 | 3≤m<8 | 1,420 | 4.83 | 0 / 1 / 2 / 5 / 8 / 12 / 14 |
| 2024–25 | m≥8 | 932 | 11.83 | 4 / 6 / 10 / 14 / 18 / 22 / 25 |

No tier fell back to the pooled anchors; every tier had n ≥ 453.

## 2025 holdout

### All pregame candidates (n = 2,500)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | sd pred | sd obs | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 incumbent | 2.0605 | **2.4030** | 0.543 | 0.818 | 0.909 | 2.9401 | 3.41 | 6.24 | 0.2380 | 0.7833 |
| Zf v2 | 1.8785 | 2.1077 | 0.738 | 0.910 | 0.960 | 2.9399 | 4.39 | 6.24 | 0.1410 | 0.8854 |
| **V4 quantile map** | **1.7710** | 2.7932 | 0.744 | 0.938 | 0.970 | **2.7104** | 3.62 | 6.24 | 0.1485 | 0.8762 |
| V4u reference | 1.9953 | 2.9060 | 0.762 | 0.941 | 0.969 | 2.9612 | 3.76 | 6.24 | 0.2031 | 0.7550 |

Paired CRPS against B0, game-clustered (2,500 items, 240 games): Zf −0.1820 ± 0.0282;
**V4 −0.2895 ± 0.0433**; V4u −0.0652 ± 0.0183.

### RB, gated (n = 1,714)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 2.4085 | 2.5800 | 0.535 | 0.796 | 0.893 | 3.3661 | 0.2174 | 0.8199 |
| **V4** | **2.0852** | 3.2049 | 0.725 | 0.925 | 0.960 | **3.1464** | 0.1472 | 0.8842 |

Paired V4 − B0 **−0.3232 ± 0.0612**.

### QB, reported and not gated (n = 786)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 1.3017 | 2.0170 | 0.560 | 0.864 | 0.944 | 2.0113 | 0.2829 | 0.6829 |
| **V4** | **1.0857** | 1.8955 | 0.785 | 0.968 | 0.992 | **1.7598** | 0.1512 | 0.8633 |

Paired V4 − B0 −0.2160 ± 0.0469.

## 2026 development (fit 2024–2025)

| model | CRPS | log loss | cov50 | cov80 | cov90 | MAE | sd pred | Brier(≥1) | AUC(≥1) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 incumbent | 2.0889 | **2.4412** | 0.491 | 0.812 | 0.896 | 2.9972 | 3.38 | 0.2498 | 0.7591 |
| Zf v2 | 1.8668 | 2.1103 | 0.740 | 0.926 | 0.965 | 2.9959 | 4.64 | 0.1461 | 0.8627 |
| **V4** | **1.8015** | 2.6400 | 0.718 | 0.928 | 0.978 | **2.7965** | 3.74 | 0.1625 | 0.8387 |

Paired (489 items, 48 games): V4 − B0 **−0.2874 ± 0.1206**. RB only (n = 349): V4 − B0 −0.3216 ± 0.1595.

## The gate, as pre-registered: aggregate coverage, all six comparisons

Aggregate coverage on the full pregame population is the gated statistic, named in the SPEC in advance.
Per-tier coverage is reported below as a diagnostic and carries **no adoption weight**.

| season | level | nominal | B0 | V4 | \|B0 err\| | \|V4 err\| | pass |
|---|---:|---:|---:|---:|---:|---:|---|
| 2025 | 50 | 0.50 | 0.543 | 0.744 | 0.043 | 0.244 | **FAIL** |
| 2025 | 80 | 0.80 | 0.818 | 0.938 | 0.018 | 0.138 | **FAIL** |
| 2025 | 90 | 0.90 | 0.909 | 0.970 | 0.009 | 0.070 | **FAIL** |
| 2026 | 50 | 0.50 | 0.491 | 0.718 | 0.009 | 0.218 | **FAIL** |
| 2026 | 80 | 0.80 | 0.812 | 0.928 | 0.012 | 0.128 | **FAIL** |
| 2026 | 90 | 0.90 | 0.896 | 0.978 | 0.004 | 0.078 | **FAIL** |

MAE gate: 2.7104 vs 2.9401 (2025) and 2.7965 vs 2.9972 (2026) — pass, and better than B0 both seasons.

### Per-tier coverage — diagnostic only

| season | tier | B0 50/80/90 | V4 50/80/90 |
|---|---|---|---|
| 2025 | m<3 | 0.612 / 0.915 / 0.946 | **0.820** / 0.961 / 0.972 |
| 2025 | 3≤m<8 | 0.436 / 0.681 / 0.872 | **0.685** / 0.923 / 0.970 |
| 2025 | m≥8 | 0.562 / 0.824 / 0.889 | **0.673** / 0.912 / 0.966 |
| 2026 | m<3 | 0.542 / 0.949 / 0.949 | **0.785** / 0.963 / 0.986 |
| 2026 | 3≤m<8 | 0.424 / 0.645 / 0.843 | **0.738** / 0.954 / 0.971 |
| 2026 | m≥8 | 0.495 / 0.806 / 0.874 | **0.544** / 0.816 / 0.971 |

## Why every candidate fails the 50% comparison — measured, not argued

`backend/audit_nfl_zero_interval_v4.py`, 2025, n = 2,500, true share of zero-carry outcomes **0.379**:

| model | mean P(0) | share of items with q25 = 0 | coverage on those | coverage on the rest | aggregate cov50 |
|---|---:|---:|---:|---:|---:|
| B0 | **0.173** | 24.8% | 0.848 | 0.442 | **0.543** |
| Zf (v2) | 0.333 | 50.0% | 0.892 | 0.584 | 0.738 |
| V4 | 0.301 | 48.4% | 0.880 | 0.616 | 0.744 |
| V4u | 0.269 | 64.0% | 0.843 | 0.618 | 0.762 |

The mechanism is arithmetic. A 50% central interval on a discrete distribution is `[q25, q75]`. When more
than a quarter of the mass sits at zero, `q25 = 0`, and since zero is the minimum outcome the interval
becomes `[0, q75]` — which holds `F(q75) ≈ 0.75` of the mass **by construction**, not 0.50. For roughly
half the population that is exactly what happens, and those items cover at 0.85–0.89. No discrete
distribution with a correctly modelled zero mass can return 0.50 aggregate under this definition.

B0 reaches 0.543 only because it **under-predicts zeros by more than half** — 0.173 against a true 0.379.
Its interval escapes the zero boundary on 75% of items, and there it covers just 0.442. The 0.543 is the
average of 0.848 and 0.442: two errors cancelling.

So the 50% coverage comparison, as written, rewards the model that gets the zero process wrong. Every
candidate that improved the zero layer and the count shape moved to ~0.74 and was rejected for it. This is
the same reason v1 under-covered (it never had the zero mass), v2 and v3 over-covered, and V4 — which fits
the quantiles empirically and has the best CRPS and MAE of the four — lands in the same place.

**This is a report, not a renegotiation.** The gate is unchanged, the verdict is NOT_ADOPTED, and changing
the gate is a decision for Micah, not for this harness.

## The construction's own defect: log loss

V4 wins CRPS and loses log loss badly (2.7932 vs B0's 2.4030 in 2025; 2.6400 vs 2.4412 in 2026). The
piecewise-linear CDF concentrates mass on the anchor values, so an outcome between anchors gets a small
probability and is penalised hard. CRPS rewards being close in distance and tolerates that; log loss does
not. If a quantile map is revisited, it needs a smoothing kernel or integer allocation that spreads mass
across the interval between anchors rather than at its edges.

This is a genuine defect of this candidate independent of the gate, and it is recorded as such.

## Where the workstream stands

| candidate | CRPS 2025 | MAE 2025 | aggregate cov50 | verdict |
|---|---:|---:|---:|---|
| B0 incumbent | 2.0605 | 2.9401 | 0.543 | reference |
| v1 hurdle | 1.9093 | 2.7868 | 0.713 | NOT_ADOPTED |
| v2 ZINB | 1.8785 | 2.9399 | 0.738 | NOT_ADOPTED |
| v3 tiered R | 1.8524 | 2.9400 | 0.750 | NOT_ADOPTED |
| **v4 quantile map** | **1.7710** | **2.7104** | 0.744 | NOT_ADOPTED |

Four candidates, monotonically improving proper scores, one gate that none can pass while the zero mass is
modelled honestly.

**Recommendation for the next step — a decision, not an action.** The evidence says the 50% coverage
comparison cannot be satisfied by a correctly specified zero-inflated model, so continuing to generate
candidates against it will keep producing the same result. The options are:

1. Re-specify the interval: shortest (HPD) intervals instead of central ones, which do not pin at the
   minimum, and re-grade all four candidates on the same data. This is the smallest change and can be done
   retrospectively from the frozen JSONs.
2. Gate on a proper score (CRPS with a clustered interval, plus a calibration slope or PIT histogram) and
   keep coverage as a diagnostic.
3. Accept B0 and stop: it is the best-calibrated model in aggregate, by virtue of being wrong about zeros.

None of these are taken here. v1 remains frozen for prospective confirmation on 2026 weeks 7–18; v2, v3 and
v4 are closed as NOT_ADOPTED. Nothing was merged to dev.

## Provenance

- `backend/audit_nfl_quantile_stability_v4.py` — cross-season quantile stability (read-only).
- `backend/audit_nfl_zero_interval_v4.py` — the zero-boundary diagnostic above (read-only).
- `backend/nfl_rushing_quantile_map_v4.py` — harness; reuses v2's population, participation fit, scoring
  and clustering, and supplies anchors, interpolation and the piecewise-linear CDF.
- `docs/frozen-nfl-rushing-participation-v4.json` — anchors, tier centres, participation parameters, all
  tables, paired comparisons, the six gate checks and the verdict.
- No prod writes; the dev DB was opened read-only. Nothing merged to dev.
