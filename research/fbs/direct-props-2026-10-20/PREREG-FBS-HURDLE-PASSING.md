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
are unchanged. What changes: the model structure (§6), the cohort's membership rule
(§2.2), the cohort's labelling (§2.3), and the evidence status of 2025 (§9).

**Revision 3 (2026-10-20).** Review amendments, still documentation only. §2.2 is
restated so that membership is a property of the **target row's season** rather than
of a run — the revision-2 wording applied one cut to a whole training block, which
would itself have leaked for 2018–2022 rows — and gains an explicit 2018 boundary
rule (`n_unclassifiable_2018`). §7 gains the matching assertions. §9 gains a
definition of "frozen" that excludes retrospective reconstruction from the 2026
confirmation. Population, baselines, metric, decision rule, bootstrap settings and
recorded results are untouched again.

**Revision 4 (2026-10-20).** Documentation only. §6.1/§6.4 now separate the two
priors explicitly: the **participation** prior `p_prior` is
`P(pass_attempts > 0 | cohort member)` estimated over cohort-eligible box-score
appearances **including zero-attempt ones**, while the **conditional volume** prior
is estimated **from positive-attempt games only**. Both follow §2.2 row by row;
missing box-score records stay unknown in both. §7 gains the matching row-set
assertions. Nothing else changes.

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

### 2.2 Membership is a property of the row's season — the look-ahead fix

That legitimacy does **not** extend backwards. At the point where a
hyper-parameter is selected on **2024** CRPS the 2024 season is not finished, so
full-season 2024 volume is future information for a 2024 target. Using the 2024 cut
to classify 2024 rows is look-ahead leakage, and revision 1 did not rule it out.

**The cut belongs to the target row's season, never to the run.** A row in season
`S` is classified by season **S−1** full-season volume, with the top-quartile
threshold recomputed on `S−1`; if the athlete has no volume in `S−1`, the fallback
is strictly-trailing volume within `S` before that game, measured against that same
`S−1` threshold. Applied across every season the protocol touches:

| target rows | cut season | threshold | fallback for no prior-season volume |
|---|---|---|---|
| 2025 evaluation (scoring) | 2024 | top quartile **on 2024** (the committed cut) | strictly-trailing 2025 before the target game |
| 2024 — grid selection, `p_prior` for selection | 2023 | top quartile **on 2023** | strictly-trailing 2024 before the target game |
| 2023 | 2022 | on 2022 | strictly-trailing 2023 |
| 2022 | 2021 | on 2021 | strictly-trailing 2022 |
| 2021 | 2020 | on 2020 | strictly-trailing 2021 |
| 2020 | 2019 | on 2019 | strictly-trailing 2020 |
| 2019 | 2018 | on 2018 | strictly-trailing 2019 |
| 2018 | **none available** | — | **unclassifiable** — boundary rule below |

**Boundary rule at 2018.** The Phase-5 cache begins at 2018, so 2018 rows have no
`S−1 = 2017` volume and therefore no cut. They are **not** silently classified, not
assigned a 2018 threshold, and not dropped from everything:

- 2018 rows are **excluded from every cohort-conditioned quantity** — both priors of
  §6.4 (`p_prior` and the conditional volume prior), and any
  top-quartile-conditioned average.
- 2018 rows **remain** in unconditional quantities (position-level dispersion, the
  unconditional training likelihood).
- The count and volume are reported as `n_unclassifiable_2018`, per market,
  alongside `n_missing_history`.

Nothing carries forward across seasons: the threshold is **seasonal** and is
recomputed from that season's own volume distribution. Applying a 2024 threshold, or
2024 membership, to a 2024 row is exactly the leak this section exists to prevent.

Any prior conditioned on "high prior volume" — **either** prior in §6.4, the
participation rate used in §6.1 and the conditional volume prior — is estimated with
**the membership of each contributing row**, never with one cut applied to a whole
training block. The `p_prior` entering the 2024 grid selection is therefore estimated
from 2018–2023 games using the **2019–2023** memberships (2018 excluded per the
boundary rule); the `p_prior` used to score 2025 is estimated from 2018–2024 games
using the **2019–2024** memberships. For 2025 target rows, strictly prior 2025
participation history is allowed as a **feature** (§6.1, `s` and `n`) and must not
fit, select or re-estimate any parameter.

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
   2018–2023) and — per §2.2 — 2024 rows classified by **2023** volume, never by
   2024 volume, with 2018 rows carrying no cohort membership at any step.
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
- `p_prior` = the **participation prior**: `P(pass_attempts > 0 | pregame
  high-prior-volume QB cohort)`, training-only. It is estimated over historical
  **cohort-eligible box-score appearances, positive and zero attempts alike** — a
  dressed quarterback with zero attempts is an `H = 0` observation and belongs in
  both the numerator and the denominator. It is **not** estimated from
  positive-attempt games alone; that row set belongs to the *conditional volume*
  prior, a different estimand with a different denominator (§6.4). Membership of
  every contributing row follows §2.2 — that row's own `S−1` cut, with 2018 excluded
  as unclassifiable.

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

### 6.4 Shrinkage — two priors, two row sets; `k` selected on 2024 rows, 2023 cut

The all-appearance `k = 0.25` and the all-appearance position mean are **retired**
for this model: they are the mechanism that produced the under-prediction
`COHORT.md` measured. They are replaced by **two distinct priors**, and conflating
them is the error this section exists to prevent — they answer different questions
over different row sets:

| prior | estimand | rows used | zero-attempt appearances | rows absent from the box score |
|---|---|---|---|---|
| **participation prior** `p_prior` (§6.1) | `P(pass_attempts > 0 \| cohort member)` | historical **cohort-eligible box-score appearances** | **included, as `H = 0`**, in numerator and denominator | **excluded — unknown, not zero** (§2.5) |
| **conditional volume prior** (this section) | positive pass-attempt counts among users | historical **cohort-eligible appearances with `pass_attempts > 0`** | excluded — they are not observations of the count | **excluded — unknown, not zero** (§2.5) |

- The **conditional passing-attempt volume prior is estimated from positive-attempt
  games only.** It never sees a zero-attempt appearance, because a zero-attempt
  appearance is not a draw from the conditional-on-usage count distribution.
- The **participation prior is the opposite**: it is estimated over all
  cohort-eligible box-score appearances, zero-attempt ones included. It cannot be
  estimated from positive-attempt games alone — doing so would make `p_prior ≈ 1`
  by construction and delete the hurdle's zero mass.
- Both priors follow §2.2 **row by row**: each contributing row is classified by its
  own `S−1` volume cut and its own season's threshold, 2018 rows are excluded as
  unclassifiable, and nothing is estimated with a cut drawn from a later season.
- The conditional-volume shrinkage is preregistered as a grid
  `k ∈ {0, 0.25, 0.5, 1, 2}`, selected on **2024** CRPS only, with 2024 rows
  classified from **2023** volume (§2.2).
- An athlete with no positive-attempt history takes the **training-only conditional
  volume prior built from positive-attempt games** — not the participation prior —
  and the number of rows doing so is reported explicitly (`n_missing_history`)
  instead of being absorbed silently.

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
rule in §2.2 — the 2024 cut applies to **2025 targets only**; every target row in an
earlier season uses its own strictly prior season. **No full-season quantity** may
enter membership or features at a point where that season is not yet complete.

Code-level enforcement (must be present and must fail the run if violated):

```
assert max_source_ns < target_kickoff_ns            # per target row
assert not any(row.season == target_season and row.week >= target_week)  # no target/future week

# membership: the cut season is always the target row's own S-1
assert cut_season == target_season - 1 or cut_season is None   # None => unclassifiable, never classified
assert cut_season is None or threshold_season == cut_season    # threshold recomputed on its own season
assert not any(r.season == 2018 and r.cohort_member for r in cohort_rows)  # 2018: no S-1 data

# the two priors in 6.4 use different, non-interchangeable row sets
assert all(r.pass_attempts > 0 for r in volume_prior_rows)          # conditional volume prior: users only
assert all(r.has_box_score_row for r in participation_prior_rows)   # p_prior: unknown rows never enter
assert len(set(volume_prior_rows) - set(participation_prior_rows)) == 0

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

**What "frozen" has to mean for that sample**, so it cannot later be reinterpreted
as reconstruction: a forecast is frozen only if it was written to an immutable
artifact **before the target kickoff**, carrying its own as-of cutoff, model
version, data-version fingerprint and — where the simulation is involved — its
sampler seed, and was never recomputed afterwards. A forecast re-derived after the
fact from stored box scores, backfilled rows or the final fitted parameters is a
**retrospective reconstruction** and is **not eligible**: not as confirmation of
this design, and not as evidence in any later product decision. The same applies to
a 2026 row whose input snapshot was captured after its kickoff, or whose identity or
market mapping was resolved only after the game. No such artifact exists yet, and
this document creates none (§8).

## 10. Signature

```
APPROVED BY MICAH: ______________________________   (date / initials)
```

Left blank deliberately. This draft may not be signed by the agent, and revision 2
— which adopts the DECISION doc's six proposed choices into the design — is still
only a proposal. **No fitting run, tuning run, or production code change starts
until Micah fills this line in.** Until then this file is documentation.
