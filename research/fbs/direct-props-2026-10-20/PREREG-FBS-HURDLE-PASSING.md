# PRE-REGISTRATION — FBS passing hurdle (DRAFT, UNSIGNED)

**Status: DRAFT. Not approved. Nothing has been fitted, tuned, or run.** This
document exists so Micah can sign or reject the design *before* any code touches
it. It is not a result and it authorises no work.

Branch `research/fbs-direct-props-2026-10-20`. Parent evidence:
`COHORT.md` (commit `9b3ab91e`) — on the pregame-definable starting-QB cohort the
committed model is beaten by the plain trailing-5 baseline
(`crps_baseA`), on both passing attempts (+0.144 [+0.028, +0.261]) and passing
yards (+4.014 [+2.363, +5.665]). This draft specifies the fix that failure points
at. The rushing markets are out of scope here.

---

## 1. Question

Does a **hurdle** (two-part) structure beat the plain trailing-5 baseline on the
**pregame-definable starting-QB cohort**, on a paired proper score, **out of
time**?

Scope: passing attempts and passing yards only.

## 2. Population

**Evaluation set** — 2025 out-of-sample `pregame_known` rows, exactly as defined
in `COHORT.md` and produced by `cohort_analysis.py`:

| market | eval rows | athletes | games |
|---|---:|---:|---:|
| passing attempts | 1,175 | 106 | 716 |
| passing yards | 1,146 | 102 | 714 |

Membership rule (unchanged from the committed cohort): athlete's **2024**
season volume ≥ the top-quartile threshold, **or** — for athletes with no 2024
volume — strictly-trailing 2025 cumulative volume before the target game ≥ the
same threshold. Evaluated over **all** rows of qualifying athletes, zeros
included.

**Fitting seasons** — strictly earlier than every evaluation row: priors fit on
2018–2023; any hyper-parameter grid selected on 2024 CRPS only; priors and
dispersion refit on 2018–2024 before 2025 is scored. No 2025 row enters fitting
in any form.

## 3. Baselines

Both are already committed per-row in `predictions_<market>.csv`; no refitting:

- **`crps_baseA`** — raw trailing-5 fixed-spread (`baseline_A_trailing5_fixed`).
  *The passing claim lives or dies on this baseline.*
- **`crps_baseB`** — position-league pool (`baseline_B_position_league`).

## 4. Primary metric

- **Primary:** paired ΔCRPS = `CRPS_hurdle − CRPS_baseA`, negative = hurdle
  better. 90% bootstrap CI **clustered on `game_id`**, 10,000 resamples, fixed
  seed `20261020`.
- **Secondary (reported, not decisive):** cov50 = [q25, q75], cov80 = [q10, q90],
  cov90 = [q05, q95]; `sd_ratio` (predictive SD / residual SD); MAE; bias.
- **Prohibited:** no accuracy, no AUC, no hit-rate, no market/ROI claim anywhere.

## 5. Decision rule (signed in advance)

- **ADOPT** only if the 90% CI upper bound of ΔCRPS `< 0` against **both**
  baselines **and** every week-block delta `< 0` (blocks 1–6, 7–12, 13+).
- **PROVISIONAL** if every point delta is negative but a CI spans zero, or a
  single week block flips.
- **REJECT** otherwise.

A **REJECT on passing closes the passing projection page**; it says nothing about
the rushing page, which stands on its own `pregame_known` result.

## 6. Leakage assertion

Every feature for a target game uses **only rows strictly before that game**
(participation history and volume history). The 2024 volume cut stays exactly as
committed. **No full-season quantity** may enter membership or features.

Code-level enforcement (must be present and must fail the run if violated):

```
assert max_source_ns < target_kickoff_ns            # per target row
assert not any(row.season == target_season and row.week >= target_week)  # no target/future week
```

and for the participation/usage split, assert that the trailing participation
rate and trailing usage mean for a row are computed from `shift(1)` cumulative
windows within `athlete_id`, identical to the existing `_excl_trailing`
convention (`run_direct_props.py`), never including the current row.

## 7. What does NOT change

- No edit to `RESULTS.md` verdicts.
- No gate, no promotion rule, no deployment.
- No threshold in `params.json` is touched by this document.
- No frozen/prospective forecast is created.
- No page ships off the back of this document alone; a page requires an ADOPT
  under §5 *and* a separate product decision.

## 8. Open design choices — UNRESOLVED (structure-changing; Micah decides)

Per the standing rule, these are listed rather than chosen. **Do not fit until
each is decided**, because each changes model structure, not just a number:

1. **Participation model form.** (a) logistic on the trailing participation rate;
   (b) empirical trailing participation frequency with smoothing; (c) a
   zero-inflated NB on the count directly. These are different models with
   different calibration behaviour.
2. **Independence vs coupling.** Whether stage-2 usage is modelled independently
   of participation (as the current count × rate Monte Carlo treats count and
   rate), or coupled through a shared latent.
3. **Trailing window.** Keep the committed `WINDOW = 5`, or a different window
   for the participation stage.
4. **Shrinkage.** Reuse the committed `k = 0.25` shrinkage on the conditional
   usage mean, refit it, or drop it in favour of the participation stage carrying
   the zero mass.
5. **Efficiency stage.** Whether the yards efficiency (rate) stage is unchanged
   from the committed model, or also conditioned on participation.
6. **Dispersion refit grid.** The committed `SPREAD_R_GRID` / `SPREAD_ESD_MULT`
   are reused as-is, or a new grid is registered here before fitting.

If any of these cannot be decided from the existing committed design, that is the
signal to stop — not to pick a default and proceed.

## 9. Signature

```
APPROVED BY MICAH: ______________________________   (date / initials)
```

Left blank deliberately. This draft may not be signed by the agent.
