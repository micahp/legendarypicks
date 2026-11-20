# SLC play selection: preliminary call-site audit

Status: **incomplete**. This is a source inspection and review of existing smoke-game records, not the requested per-function execution trace or a parity-controlled experiment. The analysis below inspects `/root/lp-slc-v2` at `b521cce9`; it must not be assumed identical to each pinned package. No counterfactual has been measured.

## Pinned engine call-site inventory

The following ranges were extracted from the actual git objects named by the portable registry, independently of the working checkout. They identify code that can execute, not proof that every branch executed in a particular game. Paths are relative to `scripts/nfl_sequence/` in each commit.

| Variant | Commit | `slc_engine.play` | `slc_playcall.sample` | `pre_event.choose` | Distinction |
| --- | --- | --- | --- | --- | --- |
| V1 | `58ef3861e5f3cc4006ab627102e55bd432ab399d` | 304–341 | 366–672 | 108–333 | Established contextual stack. |
| V1.5 | `2eab8a89efffad23c00a1d451ac80e856579ac5a` | 352–389 | 373–679 | 108–333 | Season team/down adjustment is present in `_dropback_probability` (363–371). |
| V1.6 | `1bb3bd50c4df5896e4d693245e48329c20c63254` | 366–407 | 446–882 | 109–336 | Sample contains fourth-down intent resolution and probability-stage tracing. |
| V1.7 | `1ca59e0d038b594b87c0dd5b4c78b0711b022043` | 373–414 | 447–894 | 109–336 | Penalty handling is an additional game-loop mechanism; its sample includes exact historical integer checks. |
| Legacy V2, PBV1 on/off | `8a1d984229cdc20f5ad076ebd81edc7f1be90c75` | 436–487 | 421–916 | 121–373 | Optional field, PBV1, kicker and transition-strength paths; policy is determined by the registered variant and build arguments. |

The pinned legacy V2/PBV1 commit itself has the field/PBV1 precedence described below: `pre_event.py:149` advances the field, line 361 draws formation, line 364 draws PBV1 and line 368 overwrites personnel with the field grouping. This confirms the conflict at the pinned call sites when both inputs are active; it does not show that the current PBV1 label-only bundle enables the field.

## Observed call-site order

On the inspected V2 branch, `PlayCallSampler.sample()` in `scripts/nfl_sequence/slc_playcall.py` evaluates field-goal feasibility, retrieves the historical cell and computes kick share. `_dropback_probability()` calculates a score/clock probability; current-season team/down, score, team-streak and league-streak shifts can adjust it. A kick or run/dropback intent is drawn. The participant chooser invokes `pre_event.choose()`.

For a scrimmage intent with the corresponding inputs enabled, `pre_event.choose()` advances the participation field and selects eligible players; draws decision labels and QB decisions; draws formation; draws PBV1; and draws coverage. The actual guards, fallbacks and order are in `scripts/nfl_sequence/pre_event.py:121`. This sequence is conditional: absent tables, kicks, scrambles and other state change which functions execute.

The ordinary event path multiplies base weights by optional formation, coverage, streak, label, team, transition and player effects before a draw. Two-stage/conditional pass labels and sparse backoff take different branches; the backoff branch does not apply all the ordinary-path lifts. Following the event draw, the code filters historical candidates by QB/scramble status, formation, coverage, streak, labels, QB target role and exact yardline, with per-stage fallback where implemented; player and transition weights can then determine the row. `game_state`, `e1_drive` and `game_stats` apply transitions and statistics afterward.

## Findings and recommendations

| Function or mechanism | Effect and evidence | Initial disposition |
| --- | --- | --- |
| `point_splits.adjust`, `streak_splits.shift_for` | Multiple log-odds adjustments act on the same run/pass decision. | Keep baseline; isolate team and league streak separately and measure incremental held-out calibration. Overlap is a hypothesis. |
| `decision_layer.draw`, `_label_lift`, decision row filter | Labels affect event weights and can narrow the already selected event's rows. Label lifts use a geometric mean, not a simple product. | Isolate `--slc-disable-layer decision_row_filter` first, keeping label effects enabled. Compare candidate support, outcomes and full-game distributions. |
| Formation, coverage and streak lifts and filters | The same sampled context can affect both event weighting and row eligibility. Empty matches fall back. | Instrument each stage; test row filtering and event lifts separately before considering removal. |
| `_outcome_weight`, transition strength, `player_outcomes.event_weight` and `row_weight` | Optional team and player effects can apply at event and row stages; transition strength has its own branch. | Isolate effects and interactions. The proposed semantic V2 strength mechanism needs an explicit replacement test for legacy team ratios. |
| `pbv1.draw`, `_advance_lineup`, `Field.advance` | In the inspected combined path the field chooses grouping and players first. Formation and PBV1 draw later; PBV1 overwrites formation personnel, then the field grouping overwrites PBV1's personnel. | Treat as a conflict with the requested personnel-first PBV1+HE philosophy. Verify on the exact experiment commit and isolate a distinct coupled variant; do not change label-only PBV1 behavior. |
| State transitions, clock, scoring and validation | Rules and legal game completion. | Required invariant; retain and verify independently. |

## Version ownership hypotheses

These are intended responsibilities, not verified per-play function inventories. `I` means inherited candidate, `O` intended owner, `E` experimental candidate, and `R` required invariant. A mechanism is not certified merely because it appears in this table.

| Mechanism | V1 | V1.5 | V1.6 | V1.7 | Semantic V2.0 | PBV1 + HE |
| --- | --- | --- | --- | --- | --- | --- |
| Historical contextual sequence | O | I | I | I | I, subject to replacement | I, subject to lineup ownership |
| Current-season adaptation | — | O | I | I | I | I if selected |
| Sacks, turnovers, yardage, third/fourth downs | I | I | O | I | I | I if selected |
| Penalty occurrence and enforcement | R rules | R rules | R rules | O | I | I if selected |
| Opponent-adjusted offense/defense strength | — | — | — | — | O | E if selected |
| PBV1 package and HE player entry | — | — | — | — | — | O; combined ordering under review |
| Football legality and full-game validation | R | R | R | R | R | R |

The legacy `--slc-v2` participation/RNG configuration is a separate identity from semantic V2.0. The portable registry's PBV1 is label-only and does not establish PBV1+HE coupling.

## Existing records and missing evidence

**V1.7 real play, seed 300001:** The portable runner's new `--decisions-out` option captured 144 decisions for a completed WAS–NYG game using the pinned V1.7 package. On its first play, Washington faced first-and-10 at its own 25. The selected intent and event were run. The event-stage fumble probability changed from 0.00421941 in the exact outcome rows to 0.00412914 after formation, 0.00372323 after league streak, 0.00305492 after decision-label lifts, 0.00131983 after team weights, and 0.00107598 after player weights. Seven labels matched the subsequently filtered source rows; category J did not. Exact-distance support was 12,036; the event-stage pool contained 12,087 rows. These are sequential conditional probabilities, not isolated effects or evidence of predictive improvement. The trace does not report candidate counts after each filter or the disabled-filter counterfactual. The full record is on the data host at `/root/tnf-batch/walkforward/portable-models-2026-11-19/audit-v17-decisions.jsonl`.

WAS–NYG seed `300001` smoke records exist on the data host under `/root/tnf-batch/walkforward/portable-models-2026-11-19/` for V1, V1.7, V2 and PBV1 on/off. Their first plays have recorded state, event and source-cell counts. V2 and PBV1 records additionally expose named random-stream hashes. They do not provide a complete ordered function trace, per-filter before/after counts, probability changes or disabled-function counterfactuals. These records cannot establish function ownership or parity. V1.5 and V1.6 need equivalent play-level evidence located or produced.

Before drawing causal conclusions, instrument the exact pinned code for each variant and retain frozen inputs, source hashes, seed IDs, stream identities, call order, stage weights, candidate counts and fallback reasons. Capture counterfactuals through paired runs with a separate experiment identity and configuration hash. A changed state can make subsequent draws incomparable even with named streams. Semantic V2.0 and PBV1+HE require identified implementations and pinned configurations before they can be traced.
