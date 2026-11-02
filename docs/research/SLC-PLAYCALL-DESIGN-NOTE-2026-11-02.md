# SLC offense and defense decision design note — 2026-11-02

Status: research design only. No play-calling or workload model changed. No push; this work stays on `research/slc-player-workload-calibration-2026-10-30`.

## Direction and scope

Formalize the existing sequence of football decisions that creates opportunities. Do not add hard player-stat or workload caps. Keep team opportunity generation, player opportunity allocation, and outcome efficiency as separate model questions. This note uses the existing SLC decision layers and records cited for this work.

Data boundary: 2026 is sealed and excluded. 2025 is a known, previously exposed fold; it may be described with its status, but must not be called a fresh test. The support audit uses participation seasons 2016–2025 and FTN charting seasons 2022–2025, with no 2026 rows selected.

## What the layers decide today

| Layer | Current decision | Gap for a formal policy interface |
|---|---|---|
| `slc_playcall.py` / `playcall_model.py` | Selects run/dropback intent from the current situation, using the score-clock play-call artifact when enabled. The pre-event chooser is called after intent and before outcome sampling. | Intent is an offense choice; this is not yet a unified record of the offense's package, eligible participants, and the defense's response. |
| `decision_layer.py` | Draws supported categories A–N by team and down/distance/red-zone cell; labels also lift or filter candidate outcomes. The v1 prior uses the prior season. | Labels are sampled under `posteam`. That means the current defense proxies in categories I (blitzers), M (box count), and N (pass rushers) are keyed to the offense team, not `defteam`. Those labels do not name a defensive call. |
| `formation_layer.py` | Samples offensive formation and a personnel count code by intent, down, and distance, from participation data (2016 onward), with league shrinkage and explicit `UNKNOWN`. | Participation supplies formation/personnel labels at play level, not the player IDs on that package. The package therefore cannot currently constrain the player candidate list. |
| `playbook_prior.py` | Can replace the prior for pass depth, pass location, and run gap using a prior-season playbook artifact. | These are supported play families/labels, not selection of a named NFL play. |
| `defense_layer.py` | Samples a coverage label from defense-team and league priors for dropbacks; uses coverage-conditioned outcome lifts. | Coverage is not conditioned on the full game state here. Missing coverage remains `UNKNOWN`; no named calls are available or proposed. |
| `pre_event.py` | Uses the pregame roster and injury eligibility to select passer, rusher, and/or receiver before drawing the play outcome; it can also draw decision labels. | Formation/personnel is sampled after participant selection in this function. There is no verified historical package-to-player-ID join for on-field eligibility or routes. |
| `slc_config.py` | Exposes v1 layers as options and records enabled layers. | These switches do not define one shared input/output contract for a complete offense/defense decision sequence. |

## Defensive proxy support

Manager decision: coverage, box count, blitzers, and pass rushers are proxies only. Do not require named defensive calls or invent them. The full per-season counts, team support, eligible denominators, source-match counts, unknown/unlabeled counts, and per-file SHA-256 values are in [the support CSV](SLC-PLAYCALL-DEFENSE-PROXY-SUPPORT-2026-11-02.csv).

The audit follows the existing code populations and category mappings. Coverage is counted on PBP `pass` rows with week <= 18 and a known `defteam`, as in `defense_layer.priors`; blank or unmatched coverage is `UNKNOWN`. The FTN proxies follow `decision_layer.load_rows`' scrimmage/down/distance/field filters and `label_row` mappings. Box count applies to that full eligible population; blitzers and pass rushers apply where `pass_attempt == 1`. Zero box counts and pass-rusher counts below three remain explicitly unlabeled, matching the current mapping. FTN was joined for every eligible row in each audited season. PBP, participation, and FTN play keys were unique over the selected seasons; source file rows matched recorded stored rows.

Coverage label support is all `UNKNOWN` in 2016–2017. Labeled coverage categories appear from 2018; the raw categories change in 2023 (including `BLOWN`, `COMBO`, and `COVER_9`). They are preserved as published, without relabeling. The CSV contains a season summary for every category, including zero support, and additional rows by defense team. In 2025 these are descriptive known-fold counts only.

## Proposed per-snap interface

Keep the current game state and deterministic input snapshot as the source of truth. At each scrimmage snap, the research interface should carry:

1. **Input:** current state, offense and defense team IDs, already selected run/dropback intent, eligible pregame roster IDs and availability, cutoff, and pinned source/model provenance.
2. **Offense decisions:** formation/personnel and only the supported offensive labels selected before the outcome. Preserve the current playbook fallback labels as such; do not represent them as named plays.
3. **Player eligibility and selection:** eligible player IDs for the chosen package, then the participant decision. This step is unresolved until a source and stable-ID join map historical packages to players on the field. Do not infer the mapping from position counts or depth-chart order.
4. **Defense response:** supported proxy fields only: coverage, box count, blitzers, and pass rushers, each with source, support, missingness, and fallback recorded. Coverage uses the existing defense-team prior. The other three currently come from offense-keyed decision labels; rekeying them to defense identity requires an explicit, cutoff-safe implementation and validation. No named call field is proposed.
5. **Outcome and trace:** pass the recorded decisions into the existing outcome sampler, then retain the sampled outcome and state transition with the decision record. Record unknowns and fallback reasons rather than silently filling them.

This is an interface proposal, not an adopted model. Current `decision_record` already carries participants, formation/personnel, coverage, labels, and fallback indicators; the common source/support/cutoff record and package-constrained eligible-ID list are not established by the cited code.

## Manager decisions and unresolved inputs

- **Defense:** use existing coverage, box-count, blitzer, and pass-rusher labels as proxies only; no named defensive calls and no invented labels. Seasonal support is reported in the linked CSV.
- **Coach policy:** deferred. Gate 4 remains closed until a dated team/coach join is available and verified. No coach-specific policy is modeled before that gate.
- **Exact package-to-player join question:** Which existing source and dated stable player-ID join maps an offensive personnel package to the players eligible/on the field for that snap? The cited participation records have package labels but no player IDs; the pre-event snapshot has eligible roster IDs but does not establish historical package participation. This is an implementation blocker for package-constrained player choice.
- **Evaluation definition question:** Which outcome and metric should Gate 1 freeze for play-calling comparisons (intent-choice probability score, team opportunity distribution, or both), and what sample unit is authoritative? The cited modules and records do not define one common acceptance metric. Until resolved, do not fit or claim a better policy.

## Seven gates

1. **Freeze definitions and baselines.** Inventory decision labels, support, provenance, current behavior, and the approved evaluation definition. The support CSV completes the defensive-proxy support inventory; the evaluation definition remains open above.
2. **Team opportunity generation.** Measure and improve play/drive volume and run/dropback decisions before changing individual workload allocation.
3. **Player allocation without hard caps.** Add role- and participation-aware choices only when the package-to-player eligibility join is verified; evaluate opportunities and dispersion, not fixed stat ceilings.
4. **Coaching and personnel rotation.** Verify dated team/coach identity and personnel inputs first. Coach-specific policy is deferred; do not pass this gate by assuming a join.
5. **Defensive response.** Use only supported proxy labels, keyed to the responsible defense where the source allows it; evaluate their effect separately from offensive intent.
6. **Fatigue and injuries.** Later work only, as separate mechanisms with independent historical evidence; neither is a correction for excessive workload.
7. **Paired-seed end-to-end evaluation.** Change one mechanism at a time, preserve input pins, compare intermediate opportunities and final outcomes, and keep the work research-only until its gate is met.

## First milestone

**Gate 1, baseline contract:** freeze the exact decision labels, per-season support, missingness, provenance, and approved evaluation definition before fitting a new policy. The defensive-proxy source/support audit is complete in the linked CSV. Gate 1 is not fully closed until the evaluation definition is answered; player-package constraints additionally wait on the package-to-player join. No 2026 data is used, and 2025 is reported only as a known fold.
