# PRE-REGISTRATION — FBS passing hurdle (DRAFT, UNSIGNED)

**Status: DRAFT. Not approved. Nothing has been fitted, tuned, or run.** This
document exists so Micah can sign or reject the design *before* any code touches
it. It is not a result and it authorises no work. The signature block in §10 stays
blank until Micah signs it explicitly; revising this document is not approval, and
no fitting run may start on the strength of the revision.

**Revision 2 (2026-10-20).** Incorporates the six design choices proposed in
`docs/DECISION-fbs-props-active-cohort-hurdle-2026-10-20.md` (branch
`docs/forecast-first-product-architecture-2026-10-20`, commit `123b3b49`) and its
pre-signature amendment on 2024 cohort membership. Population, baselines, primary
metric, decision thresholds, bootstrap settings and the recorded historical results
are unchanged. What changes: the model structure (§6), the cohort's tuning-time
membership rule (§2.2), the cohort's labelling (§2.3), and the evidence status of
2025 (§9).

Branch `research/fbs-direct-props-2026-10-20`. Parent evidence:
`COHORT.md` (commit `9b3ab91e`) — on the pregame-definable **high-prior-volume QB**
cohort the committed model is beaten by the plain trailing-5 baseline
(`crps_baseA`), on both passing attempts (+0.144 [+0.028, +0.261]) and passing
yards (+4.014 [+2.363, +5.665]). That cohort is *not* a verified-starter cohort
(§2.3). This draft specifies the fix that failure points at. The rushing markets
are out of scope here.

---

## 1. Question

Does a **hurdle** (two-part) structure beat the plain trailing-5 baseline on the
**pregame-definable high-prior-volume QB cohort**, on a paired proper score, **out
of time**?

Scope: passing attempts and passing yards only. **2025 is exploratory for this
design, not an untouched holdout (§9)** — a 2025 win is a necessary condition, not
independent confirmation.

## 2. Population

**Evaluation set** — 2025 out-of-sample `pregame_known` rows, exactly as defined
in `COHORT.md` and produced by `cohort_analysis.py`:

| market | eval rows | athletes | games |
|---|---:|---:|---:|
| passing attempts | 1,175 | 106 | 716 |
| passing yards | 1,146 | 102 | 714 |

### 2.1 Membership rule for the 2025 evaluation rows (unchanged)

Athlete's **2024** season volume ≥ the top-quartile threshold **recomputed on
2024**, **or** — for athletes with no 2024 volume — strictly-trailing 2025
cumulative volume before the target game ≥ that same threshold. Evaluated over
**all** rows of qualifying athletes, zeros included. This cut is unchanged from the
committed cohort and is legitimate for 2025 targets: 2024 is strictly before every
2025 game.

### 2.2 Tuning-time membership — the look-ahead fix (amendment, required)

That legitimacy does **not** extend backwards. At the point where a
hyper-parameter is selected on **2024** CRPS, the 2024 season has not finished, so
full-season 2024 volume is future information. Using the 2024 cut to define
membership for a 2024 selection run is look-ahead leakage, and revision 1 did not
rule it out.

The rule is the **same membership policy shifted to the preceding season**, applied
at every decision point:

| decision point | target rows | prior-season volume cut | fallback for athletes with no prior-season volume |
|---|---|---|---|
| grid selection (§2.4 step 2) | 2024 | **2023** full-season volume, top-quartile threshold recomputed **on 2023** | strictly-trailing 2024 cumulative volume before the target game, against that same 2023 threshold |
| `p_prior` estimation for selection | 2024 games only | **2023** cut, as above | as above |
| refit (§2.4 step 3) and 2025 scoring | 2025 | **2024** full-season volume, threshold recomputed **on 2024** (the committed cut) | strictly-trailing 2025 cumulative volume before the target game |

For any earlier season `S` used as a target in a diagnostic or sensitivity run, the
cut is season **S−1** volume with the threshold recomputed on `S−1`, and the
fallback is strictly-trailing volume within `S` before the target game.

Nothing carries forward across decision points: the threshold is **seasonal** and is
recomputed from that season's own volume distribution. Applying a 2024 threshold, or
2024 membership, to a 2024 selection run is exactly the leak this section exists to
prevent.

Any prior conditioned on "high prior volume" — including `p_prior` in §6.1 — must be
estimated with this chronological eligibility at the step where it is used. The
`p_prior` entering the 2024 grid selection is estimated from 2018–2023 games under
the **2023** cut; the `p_prior` used to score 2025 is estimated from 2018–2024 games
under the **2024** cut. For 2025 target rows, strictly prior 2025 participation
history is allowed as a **feature** (§6.1, `s` and `n`) and must not fit, select or
re-estimate any parameter.

### 2.3 What this cohort is not — not a verified-starter cohort

"High prior volume" is not "will start". The cut is the top quartile of an athlete's
prior-season passing volume, so the cohort **does** contain quarterbacks who were
high-volume starters a season ago and then lost the job, changed school, or are
unavailable for the target game. A quarterback with 2024 volume, an offseason
injury, and no 2025 role is a member on every one of his 2025 rows.

No depth-chart, injury-report, lineup or availability feed enters membership. We do
not hold timestamped pregame starter data, so this document **asserts no starter
designation anywhere**, and revision 1's phrase "starting-QB cohort" is corrected
here: the cohort is *pregame-identifiable high-prior-volume quarterbacks*, not
verified starters. Two consequences are binding:

- The model must carry real zero-usage mass for these athletes — which is why the
  cohort is evaluated over **all** their rows, zeros included, not over their
  positive-usage rows.
- A win here supports "better forecasts for the quarterbacks a user can identify
  before kickoff", **not** "better forecasts for the starting quarterbacks". Any
  downstream sentence that says *starter* needs a timestamped depth chart this
  study does not have.

### 2.4 Fitting, tuning and refit seasons

Unchanged from the committed protocol:

1. **Priors fit on 2018–2023** (`TUNE_SEASONS`).
2. **Hyper-parameter grid selected on 2024 CRPS only**, using `L_tune` (priors from
   2018–2023) and — per §2.2 — **2023** membership, never 2024 membership.
3. **Priors and dispersion refit on 2018–2024** (`TRAIN_SEASONS`), then 2025 is
   scored.
4. **No 2025 row enters fitting, tuning, prior estimation or dispersion selection
   in any form.** 2025 rows appear only as strictly-trailing features for later 2025
   targets.

### 2.5 Missing and unknown rows

Absence from the box score is **not** `H = 0`. A row with no publisher box-score
record is an unknown and is reported as one of: did not dress / DNP, dressed with
zero attempts, or missing data. It is never imputed as a zero and never silently
dropped. The scored denominator stays the committed row set above (1,175 passing
attempts / 1,146 passing yards); anything outside it — DNP, unknown, missing
identity, void — is counted and reported separately with its reason.

## 3. Baselines

Both are already committed per-row in `predictions_<market>.csv`; no refitting:

- **`crps_baseA`** — raw trailing-5 fixed-spread (`baseline_A_trailing5_fixed`).
  *The passing claim lives or dies on this baseline.*
- **`crps_baseB`** — position-league pool (`baseline_B_position_league`).

**Secondary falsification comparators** (reported in full, never decisive — the
signed rule in §5 is decided on `baseA` and `baseB` only):

- **fair conditional-active trailing-5** — the same trailing-5 mean computed only
  from the athlete's *earlier appearances with positive passing attempts*, so the
  hurdle is not credited for beating a baseline that is biased low by its own
  zero-usage appearances.
- **simple pregame hurdle baseline** — the transparent hurdle of §6.1 with default
  parameters and no tuning, so the tuned model has to earn its complexity.

If the hurdle's advantage exists only against `baseA` while the fair
conditional-active comparator beats it, the completion report must say so in the
headline; it does not rewrite §5, it constrains what may be claimed downstream.

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

## 6. Design — the six structure choices (proposed, unsigned)

These are the six choices proposed in the DECISION doc's design recommendations.
Revision 1 listed them as open; they are now written into the design, but writing
them down is **not** a decision by Micah and none of them may be fitted yet.

### 6.1 Participation — smoothed strictly-trailing empirical rate

`H = (pass_attempts > 0)`: the quarterback records at least one pass attempt. Not a
pooled logistic, and not a zero-inflated NB on the count, for this first controlled
test. The probability is the empirical rate

```
p_H = (s + p_prior) / (n + 1)
```

where, for a target row:

- `s` = the athlete's **positive-attempt appearances** among his **last five
  available box-score appearances** strictly before the target game;
- `n` = the number of those available appearances, `n ≤ 5`;
- `p_prior` = a **training-only** high-prior-volume-QB rate (§6.4), estimated with
  the chronological eligibility of §2.2.

Zero-attempt appearances **do** count in `n`: a dressed quarterback who took no snap
is evidence about participation. A row absent from the box score enters neither `s`
nor `n` — it is an unknown (§2.5), not a zero.

### 6.2 Coupling — Bernoulli hurdle × zero-truncated NB, shared count

- Stage 1: `H ~ Bernoulli(p_H)`.
- Stage 2: attempts | `H = 1` ~ **zero-truncated** negative binomial on positive
  counts.
- Stage 3: passing efficiency is sampled **independently of the count, given
  pregame information**, and the **sampled positive count is shared** with the
  passing-yards simulation, so attempts and yards are coherent within a draw.
- The unconditional predictive distribution is the explicit mixture
  `P(Y) = (1 − p_H)·δ₀ + p_H·P(Y | H = 1)`, reported alongside both components.
- Zero and negative passing yards stay possible after a positive attempt count; they
  are not discarded.
- A shared latent correlation between participation and volume is an **additional
  experiment only**, run only if this minimal model fails on the primary metric.

### 6.3 Windows — two windows, both strictly chronological

- **Participation** keeps the committed `WINDOW = 5` (`run_direct_props.py:63`): the
  last five box-score appearances, zero-attempt appearances included in `n`.
- **Conditional count mean** uses the athlete's last **five positive-attempt
  appearances** — a different window over a different row set; appearances with zero
  attempts are excluded here.
- **Efficiency** keeps the committed `EFF_WINDOW = 15` (`run_direct_props.py:64`)
  prior-opportunity window (§6.5).

Every window is computed per athlete, strictly chronologically, from rows strictly
before the target game (`shift(1)` within `athlete_id`, the `_excl_trailing`
convention).

### 6.4 Shrinkage — active-QB priors only; `k` selected on 2024 under the 2023 cut

The all-appearance `k = 0.25` and the all-appearance position mean are **retired**
for this model: they are the mechanism that produced the under-prediction
`COHORT.md` measured. Instead:

- Priors are estimated **only from positive-usage QB games**.
- The conditional-volume shrinkage is preregistered as a grid
  `k ∈ {0, 0.25, 0.5, 1, 2}`, selected on **2024** CRPS only, with 2024 membership
  built from **2023** volume (§2.2).
- An athlete with no positive-attempt history takes the **training-only active-QB
  prior**, and the number of rows doing so is reported explicitly
  (`n_missing_history`) instead of being absorbed silently.
- `p_prior` in §6.1 is that same active-QB cohort rate, estimated per §2.2.

### 6.5 Efficiency — unchanged `EFF_WINDOW = 15` prior-opportunity method

Passing-yards efficiency stays the committed prior-opportunity method: numerator and
denominator are restricted to the athlete's historical games with **positive passing
attempts**, over the last 15 prior opportunities. No new efficiency regression in
this trial. Yards are simulated conditional on the sampled attempt count and the
empirical efficiency, and the report must include an attempts-vs-yards coherence
check (implied yards per attempt from the two marginals against the component
means).

### 6.6 Dispersion — reuse the committed grids, unchanged values

The committed grids are reused **as values**, refit in the new conditional/hurdle
context with pre-2025 data only, under the §2.4 protocol:

- `SPREAD_R_GRID = [0.15, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]`
- `SPREAD_ESD_MULT = [1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0, 4.0]`

If the selected parameter lands on a grid edge, that is reported as a limitation.
The grid is **not** expanded after seeing the 2025 comparison.

## 7. Leakage assertions

Every feature for a target game uses **only rows strictly before that game**
(participation history and volume history). Membership follows the shifted-season
rule in §2.2 — the 2024 cut applies to **2025 targets only**; every pre-2025
decision point uses its own strictly prior season. **No full-season quantity** may
enter membership or features at a point where that season is not yet complete.

Code-level enforcement (must be present and must fail the run if violated):

```
assert max_source_ns < target_kickoff_ns            # per target row
assert not any(row.season == target_season and row.week >= target_week)  # no target/future week

# membership at any decision point: the cut season must precede the target season
assert cut_season < target_season                   # 2024 cut for 2025 rows; 2023 cut for 2024 rows
assert threshold_season == cut_season               # threshold recomputed on its own season

# no 2025 row may fit, tune or estimate anything
assert not any(row.season == 2025 for row in fit_rows)
```

and for the participation/usage split, assert that the trailing participation
rate and trailing usage mean for a row are computed from `shift(1)` cumulative
windows within `athlete_id`, identical to the existing `_excl_trailing`
convention (`run_direct_props.py`), never including the current row.

The runner must emit membership provenance per row — `cut_season`,
`cut_threshold`, `membership_source` (prior-season volume vs strictly-trailing) — so
a reviewer can reconstruct the cut without reading the code.

## 8. What does NOT change

- Population counts, both baselines, the primary metric, the decision thresholds, the
  bootstrap settings and the recorded 2025 deltas: unchanged from revision 1 and from
  `COHORT.md` @ `9b3ab91e`.
- No edit to `RESULTS.md` verdicts, to the committed `predictions_<market>.csv`, or
  to the original all-rows research.
- No gate, no promotion rule, no deployment, no scheduler, no lock issuance.
- No threshold in `params.json` is touched by this document.
- No frozen/prospective forecast is created.
- No page ships off the back of this document alone; a page requires an ADOPT
  under §5 *and* a separate product decision.

## 9. Evidence status — 2025 is exploratory, not a holdout

The 2025 comparison in this document is **exploratory**. The 2025 rows were already
scored to discover the defect (`COHORT.md`), and those results informed every choice
in §6 — the hurdle structure, the active-only priors, the `k` grid, the retirement of
the all-appearance mean. A model designed after seeing 2025 cannot be validated on
2025.

What that means concretely:

- A 2025 win under §5 is a **necessary condition**, not independent confirmation. It
  shows the redesign moved in the intended direction on the data that motivated it.
- **Confirmation requires a fresh forward-only sample**: 2026 forecasts frozen before
  kickoff, outcomes graded after, under this protocol and a later pre-registration.
  That is a separate exercise and is not authorised here.
- The 2025 numbers must be labelled exploratory wherever they appear — in the
  completion report, in every table, and in any downstream summary.
- 2025 rows still may not fit, tune, estimate a prior, or select a dispersion
  parameter (§2.4). "Exploratory" relaxes the *interpretation* of the result, never
  the leakage rule.

## 10. Signature

```
APPROVED BY MICAH: ______________________________   (date / initials)
```

Left blank deliberately. This draft may not be signed by the agent, and revision 2
— which adopts the DECISION doc's six proposed choices into the design — is still
only a proposal. **No fitting run, tuning run, or production code change starts
until Micah fills this line in.** Until then this file is documentation.
