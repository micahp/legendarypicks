# SLC play-selection execution audit

The paired traces below follow a real WAS–NYG opening snap through each sampled function and historical-row filter. Source inspection covers additional branches that this snap did not exercise. The package commit in each trace identifies the implementation that ran.

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

The coupled research implementation at `63997fc5` incorporates `0df3d629`. In that code, `pre_event.choose` draws PBV1 at line 152 and passes the package as `group_override` to `_advance_lineup` at line 155. The resulting group is already available to `Field.advance` when it selects players. Formation still draws separately at line 367. Keep the package override in this lineage and isolate formation conditioning if testing its additional effect. The old ordering on the portable pin cannot establish a defect in the coupled implementation.

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
| `pbv1.draw`, `_advance_lineup`, `Field.advance` | In the inspected combined path the field chooses grouping and players first. Formation and PBV1 draw later; PBV1 overwrites formation personnel, then the field grouping overwrites PBV1's personnel. | Treat as a conflict with the requested personnel-first PBV1+HE philosophy. Preserve the label-only package. Use the coupled research lineage for personnel-first experiments. |
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
| PBV1 package and HE player entry | — | — | — | — | — | O on coupled research lineage |
| Football legality and full-game validation | R | R | R | R | R | R |

The legacy `--slc-v2` participation/RNG configuration is a separate identity from semantic V2.0. The portable registry's PBV1 is label-only and does not establish PBV1+HE coupling.

## Existing records and missing evidence

**V1.7 real play, seed 300001:** The portable runner's new `--decisions-out` option captured 144 decisions for a completed WAS–NYG game using the pinned V1.7 package. On its first play, Washington faced first-and-10 at its own 25. The selected intent and event were run. The event-stage fumble probability changed from 0.00421941 in the exact outcome rows to 0.00412914 after formation, 0.00372323 after league streak, 0.00305492 after decision-label lifts, 0.00131983 after team weights, and 0.00107598 after player weights. Seven labels matched the subsequently filtered source rows; category J did not. Exact-distance support was 12,036; the event-stage pool contained 12,087 rows. These are sequential conditional probabilities, not isolated effects or evidence of predictive improvement. The trace does not report candidate counts after each filter or the disabled-filter counterfactual. The full record is on the data host at `/root/tnf-batch/walkforward/portable-models-2026-11-19/audit-v17-decisions.jsonl`.

The full-game smoke records and paired first-snap traces answer different questions. Only the smoke records include downstream clock, scoring and statistics. Only the paired traces below isolate a function-level intervention.

Semantic V2.0 has a joint opponent-adjusted strength component prototype documented in `SLC-OPPONENT-ADJUSTED-CAPABILITY-PROTOTYPE-2026-11-11.md`. The registry lacks an executable semantic V2.0 game configuration. On the data host, `wf_jobs.py` defines HE using B-field with current-season entry weighting, and HSP using C-field PBV1 with snap counts. Neither job defines the requested combined PBV1+HE model. The combined research experiment can be exercised separately on the coupled code with both flags explicitly enabled. An installed portable identity would require a registry entry pinning that configuration.

## Paired first-snap experiments

The [trace files](slc-play-selection-audit/) record the first call to the pinned sampler on WAS–NYG, seed 300001. The research runner forks each arm before starting the game so both inherit the same fitted state and RNG plan. The experimental arm sets the pinned sampler's `decision_filter` switch to false. Each file records the package digest, snapshot digest, engine commit, RNG manifest, switch and configuration digest.

The `calls` array lists executed Python call edges in order of first occurrence. Each entry gives caller, caller line, callee module, callee, callee definition line and invocation count. The `changes` array gives the executed sampler line followed by candidate count, dropback probability, current label category and current event weight after that line. Null means the local variable had no value there. The `decision` object contains the pinned engine's final decision and its probability stages where implemented. This trace covers play selection through source-row sampling. Transitions after the selected row require a full-game record.

In V1.5 both arms selected a run. Sequential label filtering changed the sampled historical play from 2023 SEA–TEN play 1359 to 2025 NYJ–BUF play 2104. Keep the original V1.5 control and isolate this filter when evaluating conditional yards and clock runoff. This comparison measures a source-row substitution on one snap. Predictive calibration requires held-out observations.

### Opponent-adjusted strength component

For 2025 NYG–WAS play 88, Washington faced second down and gained a short run. I refit the research run model on 38,983 plays from 815 games in 2022–2024. The source hashes for all four seasons matched the archived evaluator output, as did the fitted model digest. On that pre-play context, `CapabilityModel.predict` called `_softmax`. The short-run probability was 0.646737 with the league baseline, 0.654978 with offense alone, 0.607014 with defense alone and 0.615531 with both. All four vocabulary-wide distributions and the call counts are in the [component trace](slc-play-selection-audit/opponent-strength-component.json).

Keep the joint offense/defense predictor as the owner of conditional event probabilities in the semantic strength experiment. Replace the corresponding legacy team event ratio at integration and evaluate yardage separately. This component conditions on an observed run intent. It has no play-call RNG, source-row draw or game-state transition.

### V1.6 materialized-history fallback

The earlier V1.6 package reached a sparse source cell and attempted a SQLite lookup during execution. The compiler now freezes the variant-specific support groups, and the runner resolves candidate IDs from those groups before the pinned sampler restores source-pool order. Rebuilt package `28358756` completed seed 300001 with the offline guards active. Washington won 41–24 in regulation, and the runner classified the game as valid. The [full-game result](slc-play-selection-audit/v1.6-full-game.json) records the source commit, snapshot hash and fitted-reference hash. This test exercised the previously failing seed. Promotion still requires the separate multi-game legacy parity gate.

## V1.6 source results (added after the first push)

Status: still incomplete. These results come from the v1.6 source at commit `1bb3bd50`, not from the v1.6 pack. The pack rebuild is still running.

Inputs: WAS at NYG snapshot (`docs/research/walkforward-2026/snapshots/w10/2026_10_WAS_NYG.json`), the local parity database (sha256 `266db021...`), and the week-9 streak file with team codes translated (WAS to WSH, LA to LAR; values unchanged). Engine: `v1_full_stack`.

### One-play trace, seed 300001

Files: `slc-play-selection-audit/v1.6-source-trace-control.json` and `v1.6-source-trace-filter-off.json`.

| Run | Chosen event | Function calls | Sampler changes |
|---|---|---|---|
| Control (row filter on) | run | 124 | 41 |
| Filter off | run | 124 | 21 |

The filter changes the sampler's step count, not the chosen play, on this one play. One play is not evidence of a general effect.

### 50-seed comparison, seeds 300001 to 300050

File: `slc-play-selection-audit/v1.6-source-50seed-summary.json`.

| Run | Valid games | Mean total | Mean home margin | Home win share | Fallbacks per game |
|---|---|---|---|---|---|
| Control (row filter on) | 50 of 50 | 50.3 | +1.6 | 62% | 379.2 |
| Filter off | 50 of 50 | 46.7 | -3.2 | 36% | 34.0 |

Reading: the filter removes most fallbacks, as designed. Turning it off moved the mean home margin by about 5 points and the home win share by about 26 points. With 50 seeds that is about 1.7 standard errors. The runs were not paired in this summary, and the sample is small. Do not treat this as a finding until the 1,000-seed runs are done.

### Still open

- v1.6 pack rebuild (running; needed for the pack-based trace).
- v1.6 rows in the ownership matrix.
- Per-version execution graph.
- 1,000-seed runs with the row filter on and off.
