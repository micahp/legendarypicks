# SLC V2 event expansion: reuse inventory

**Branch:** `research/slc-v2-event-expansion-2026-11-24`
**Frozen base:** `8a1d984229cdc20f5ad076ebd81edc7f1be90c75` (`Require overtime in every full game; retire the regulation-only switch`)
**Week 11 evidence:** `docs/research/week11-1k-batch-2026-11-22/REPORT.md` pins the V2 portable package to source commit `8a1d9842`.
**Status:** inventory was completed before implementation. The frozen `e1_drive`, reducer, RNG path, and released V2 artifacts remain untouched. This branch now contains an isolated typed event contract, fail-closed transition/stat adapters, and opt-in switch identities. It does not yet admit new historical rows or run a full game with expanded events.

This work expands V2's supported event vocabulary while retaining V2's sampled conditional play architecture and existing predictive layers. CEG is a source of canonical event data, transition evidence, and evaluated component research; its generated-game architecture and team terms are not being substituted for V2.

## Guardrails for the expansion

- Leave the frozen V2 reference, play-call layers, team adjustments, and RNG behavior unchanged when every expansion switch is off.
- Give each mechanism its own opt-in configuration field and hash contribution. `EventExpansionSwitches` now defines these identities and hashes; the batch/runtime config is not yet wired to them.
- Keep unsupported or ambiguous source rows excluded with a named reason. A row becomes eligible only after its event class, legal enforcement, next possession, clock effect, score, and statistics are representable.
- Compare one switch at a time against the same frozen V2 build, inputs, RNG protocol, and seed IDs. Preserve V2's existing named streams so one mechanism does not shift unrelated draws.
- Do not add team-strength multipliers or use CEG as a replacement engine. The 2025 CEG evaluation is a realism reference, not evidence that CEG forecasts better than frozen V2.
- Coordinate shared reducer and rules contracts before changing them. CEG Phase 5/backlog documents unresolved native reducer and attribution behavior; V1 Complete has a diverged reducer/stat path and a standalone live-dropback path. Keep those implementations isolated and coordinate typed event facts and common rule vectors instead of copying reducers. A V2-local additive `ceg-play-2` record now preserves the `ceg-play-1` API; CEG reviewed the contract direction, but the local file has not yet been merged into a shared contract or V1 Complete.

## Current V2 boundary

At the frozen base, `scripts/nfl_sequence/e1_drive.py::classify` excludes live penalties, turnover touchdowns, turnovers without a clean new-offense snap, punts without a clean receiving-team snap, and malformed clock transitions. Its event vocabulary and `scripts/nfl_sequence/reducer.py` cover ordinary run/pass/sack, interception/fumble possession changes, punts, field-goal attempts, and blocked kicks. The reducer does not accept a return endpoint or penalty enforcement as a first-class generated play.

The frozen E1 loader's `COLUMNS` list includes only a penalty boolean for penalty data; it does not load foul side/type/yards, `td_team`, return yards/returner, or the fumble recovery facts needed for these additions. Some fields exist in CEG's timing-separated tables, but the Phase 1 projection omits several raw columns: `return_touchdown`, fumble recovery player/yards, penalty player, and lateral-return facts. These columns are present in the raw 2025 PBP parquet, so a V2 reference-builder extension can preserve them from the source with a pinned hash instead of pretending the current canonical projection contains them. CEG's `penalty_yards` is an observed assessed result, not a safe nominal rule-yard input near the goal line; CEG backlog E13 must be resolved before those rows feed enforcement. `regulation_only=True` is solely a reference-pool filter: it must keep overtime plays out of the regulation pool while the full-game engine continues into its required overtime pool.

There is partial lower-level support that should not be mistaken for end-to-end support: `game_state.py` can record an explicitly supplied defensive touchdown in its overtime outcome path, and V2 already requires an overtime reference for full-game runs. Neither fact makes an excluded return row sampleable or proves return yards, recovery location, player attribution, and score reconciliation work through the ordinary V2 drive path.

CEG's `scripts/nfl_sequence/ceg_contract.py` supplied the typed-record design, not a replacement sampler. A local version-2 contract now adds explicit scoring, penalty, clock, possession/recovery, kick, role, and provenance facts while preserving the version-1 API. General scrimmage possession spots use the offense-at-snap frame; kick records explicitly use the kicking-team frame and convert to the receiving-team frame at possession change. V2 would populate the record from its selected historical row and retain its own conditional weights, row selection, and named RNG streams; CEG would continue using its generator.

The Phase 1 CEG waterfall recomputes exclusions with V2's classifier. Across 2022–2026 it reports 3,075 live-penalty rows, 1,106 overtime rows, 1,099 punts without a clean receiving-team snap, 431 turnovers without a clean new-offense snap, 220 turnover touchdowns, 64 negative clock runoffs, and 33 rows without a same-quarter next snap. The counts are an inventory of excluded rows, not a license to enable them wholesale.

## CEG Phases 1–7 reuse inventory

| Phase | Existing work | Reuse for V2 expansion | Boundary |
|---|---|---|---|
| 1: canonical dataset and waterfall | Timing-separated decision, label, post-play, and people tables; source manifests, event denominators, missingness, and the V2 exclusion waterfall. | Canonical classification fields and season/game/play joins for penalties, returns, possession, and audits. | Tables/artifacts are stored outside Git under `/root/slc-ceg-data`; V2 must package/hash its own fitted inputs. Preserve unknown labels and source cutoffs. |
| 2: scrimmage distributions | Conditional intent, dropback event, throwaway, air-yard, target/catch, YAC, and run-yard components with chronological holdouts. | Reuse event definitions, denominator discipline, and held-out evaluation where an added return or event outcome needs a conditional empirical distribution. | Do not substitute CEG's generator/distributions for V2's fitted reference rows and existing SLC layers. |
| 3: clock and timeouts | Clock component comparisons, timeout opportunity modeling, out-of-bounds clock rules, and a generated-drive harness. | Reuse timing evidence/tests for penalty no-play effects, returns, and OT transitions. | V2's current runoff and game-state stack remains the control; no clock model replacement is included here. |
| 4: special teams, fouls, returns, overtime | K1–K12 event tables/models for kickoffs, punts, field goals, tries, fouls, INT/fumble returns, and OT fourth downs, with 2025/2026 holdouts. | Primary source for the event taxonomy, conditional candidate distributions, and component scores referenced in sections 1–6 below. | Some components did not beat their prior; enforcement uses simplified/prior rules in places. Reuse each component only after its own validation and legal V2 transition. |
| 5: full-game runtime | Parameter-only artifact, offline execution, and a complete generated-game loop exercising kickoffs, punts/returns, fouls, scoring, and OT. | Reuse the offline-runtime test pattern, drive checks, and boundary scenarios. | It is a distinct generator and its own report documents simplified penalties and defensive return scoring outside the native reducer. Do not replace V2 with CEG. |
| 6: team-strength terms | Team-level adjustments were evaluated on component and drive outcomes. | No model component is proposed for V2 from this phase. | User requirement forbids new strength multipliers; these terms stay CEG-only and do not enter the expansion. |
| 7: full-game evaluation | 300/300 realism games and 1,160/1,160 forecast games completed; realism was close for several event rates, while points/TD/FG were 0.87 of 2025. On Week 11, frozen V2 home-win Brier was 0.205 versus CEG 0.245. | Reuse the separation of full-game legality, distributional realism, and predictive evaluation; use frozen V2 as forecast comparator. | These results do not authorize promoting CEG components wholesale or imply that matching marginal realism improves V2 prediction. |

## Mechanism inventory

## Implementation status on this branch

| Area | Research implementation now present | Still required before sampling new rows |
|---|---|---|
| Typed event facts | V2-local `ceg-play-2` records and strict validation; V1 contract API retained. | Review/coordinate the shared contract with CEG and V1 Complete; build the hash-pinned raw-to-canonical row adapter. |
| INT/fumble/sack returns | Scrimmage adapter handles explicit INT return/touchback, defensive score/safety, fumble recovery, retained fumble, and sack identity using the frozen reducer for ordinary transitions. | Recover source turnover/fumble spots and ordered events; add score/try/kickoff restart integration, game/player-stat merge, and full-game tests. |
| Penalties | Exact source-label mapping and nominal-yard validation feed explicit single-foul facts into V1.7 enforcement; stats require its actual enforced-yard result. | Occurrence/ruling inputs, timeout separation, offsetting/terminal/spot-foul coverage, special-teams enforcement, clock and game integration. |
| Punts | Explicit return, negative return, return TD, touchback, and no-advance receiving/kicking-team muff recoveries have a bounded adapter; all these endpoints require `punt_return_events` and kick-frame conversion is tested. | Muff advancement and muff/blocked-kick return-TD attribution are named unsupported; join classified source facts and player roles; route blocked punts through the existing block path; integrate possession/clock/stats and test full drives. |
| Overtime/fourth down and other terminals | An explicit interception touchback has a named transition under `turnover_terminal_events`; kneel and spike records are separately gated by their own switches. Dedicated identities and config hashes exist. | No new OT/fourth-down policy, kickoff, try, timeout, or full kneel/spike clock/stat behavior is wired. Retain current V2 OT and fourth-down behavior as the control. |
| Ablations and live defaults | The frozen-control identity explicitly has every expansion disabled; the expanded runtime enables all rule-transition switches by default. | The batch CLI is not wired to the expansion identity, and unsupported generated events still fail closed with named blockers. |

The focused branch suite has 60 passing tests covering the contract, independent switch identity, bounded transitions, penalty label mapping/enforcement, and accounting. These are component tests, not V2-versus-legacy parity or a full-game acceptance gate. No frozen `e1_drive`, `reducer`, `slc_engine`, RNG, or `game_stats` implementation has been edited, and no additional historical row is enabled.

### 1. Interception returns and defensive touchdowns

**Existing implementation**

- V2 samples interceptions as turnover events. The classifier drops an interception row when the source marks the play as a touchdown, and its ordinary turnover result only has the new offense's next-snap spot.
- The game-state ledger can score a supplied `defense_touchdown` in its overtime rule path, but the ordinary E1 classifier/reducer path does not construct the return or its endpoint.
- Player and team accounting records interceptions and turnovers; there is no complete V2 returner, return-yard, defensive-TD, try, and restart path for these sampled rows.

**Reusable research and code**

- CEG Phase 1 separates pre-snap decisions, play/outcome labels, post-play transitions, and people. The canonical rows include interception, `td_team`, return yards, and next possession/spot. See CEG `ceg_event_tables.py`, `ceg_waterfall.py`, and `PHASE1-DATASET-AUDIT.md`.
- CEG Phase 4 `ceg_special.py` builds `K11_int_return` and scores interception-return distributions. On the 2025 holdout it improves log loss over the prior by 0.031 per opportunity (95% interval -0.051 to -0.009). This is reusable as evidence and a conditional distribution design, not a reason to import the CEG generator.
- `docs/SIMULATION-LEARNINGS.md` section 2 identifies defensive return touchdowns as a known V2 realism gap; historical scoring is materially underrepresented and return yards were effectively absent in the saved comparison.

**Remaining gaps**

- Derive the interception catch/turnover spot consistently from the source, then represent return gain, out-of-bounds/dead-ball endpoint, touchdown, and possession. Do not use the next snap alone as the return model when a TD or period end prevents one.
- Carry explicit scoring team, returner identity, interception credit, return yards, touchdown credit, try, kickoff/restart, and overtime consequences into the existing ledger and box score.
- The research adapter distinguishes an explicitly sourced interception touchback at dead-ball spot 0 from a return safety and requires the defense's restart spot. The raw row builder and full restart accounting are not wired.
- Resolve missing/ambiguous endpoints by named exclusion. Keep the return distribution censored at the goal line and separate return TDs from ordinary return-yard outcomes.

**Required tests**

- Classify ordinary interception, return ending in field, pick-six, return out of bounds, period-ending return, and unresolved endpoint distinctly.
- Exercise the reducer/game path through possession flip, scoring team, 6 points, correct try/restart, overtime rule, returner and defense statistics, and full team/player reconciliation.
- Verify impossible spots and unknown scoring teams fail closed.
- Score return-yard and TD distributions on a chronological holdout; compare each enabled switch against frozen V2 on identical seed IDs.

**Proposed switch:** `interception_returns`.

### 2. Pre-snap and live-ball penalties

**Existing implementation**

- The frozen V2 base's `e1_drive.COLUMNS` reads only the boolean `penalty` field. `classify` rejects a live flagged play, but the ordinary play record does not carry penalty phase, committing team/type, yards, disposition, or enforcement spot. Pre-snap `no_play` fouls are outside its play vocabulary. The reducer has no penalty transition.
- V2 already contains the original V1.7 `penalty_fit.py`, `penalty_sampler.py`, `penalty_enforcement.py`, and `penalty_transition.py` modules and focused tests. They are disabled and do not make the game loop penalty-aware.
- The current V1.7 combined branch (`547e9a29`) adds `penalty_game.py`, `penalty_rulings.py`, `penalty_scrimmage_kick.py`, and `penalty_train.py`; it also revises the copied fit/sampler/enforcement/transition modules. The frozen V2 copy predates those additions and fixes. V1.7's implementation remains research-only and must be reviewed file by file before selective porting.

**Reusable research and code**

- `docs/research/SLC-V2-INHERITS-V1.7-PENALTY-CORE-2026-11-12.md` defines the intended boundary: share the foul catalog and rules core, but enable a penalty-aware V2 only with explicit controller, state, clock, and statistics integration.
- V1.7's 16-foul model distinguishes pre-snap and live-ball phases and has an explicit ruling/enforcement path. It does not model every multi-foul, spot-foul, or special-teams exception; unknown and unsupported cases are intended to fail closed.
- The later V1.7 `PenaltyGameController` cleanly separates a sampled foul from explicit adjudication. `PinnedPenaltyRulingBook` requires a seed/opportunity/type-matched ruling, including clock administration; missing rulings fail. `ResearchPenaltyRulingPolicy` is explicitly synthetic and marks assumptions unverified, so it is mechanics-only and must not supply forecasts. `penalty_scrimmage_kick.py` supports a bounded set of 2026 punt/field-goal enforcement cases and rejects unresolved timing, election, PSK spots, and multi-foul cases. `penalty_train.py` accepts externally audited opportunity JSONL and explicitly does not adjudicate raw PBP. These are selective ports, not a complete NFL foul engine.
- CEG Phase 1 has canonical penalty opportunity/event facts: phase, type, committing side, reported yards, first-down flag, and next-snap state. It reports 15,900 penalty rows (11,770 no-play and 4,130 live-play). The raw 2025 parquet includes a `penalty_player_id`, but Phase 1's `PEOPLE` projection does not retain it. The PBP does not supply a verified foul spot, so the next snap is evidence for a rules-based result, not the enforcement algorithm.
- CEG Phase 4's 2025 held-out scores improve over its prior for pre-snap occurrence (-0.007 log loss), live-foul occurrence (-0.010), and penalty type (-0.145). Its pre-snap transition check matches next-snap yardline for 11,338 of 11,393 rows (99.5%). CEG's game harness still simplifies accepted/declined/offsetting and spot-foul cases; these metrics validate components, not a complete penalty engine.

**Remaining gaps**

- Extend the frozen reference build inputs to include canonical penalty labels and their source hashes/cutoffs. Current V2 play rows do not contain the fields needed to fit or classify penalties.
- Add pre-snap and live-ball penalties as separate optional mechanisms. A pre-snap foul is a no-play state transition with correct clock/down handling; a live-ball foul requires a ruling against the sampled play result, and may nullify/retain it or award a new series.
- Port the later V1.7 controller/rulings/scrimmage-kick code selectively. The prototype maps known source labels, checks nominal yards against the 2026 rules table, and credits actual enforced yards from the rules result. It still lacks a forecast-safe ruling source, special-teams controller, and full clock/stat integration. Verify rule-era differences, half-distance, goal-line enforcement, automatic first downs, loss of down, accepted/declined/offsetting decisions, and timeout separation.
- Unknown/multiple fouls, unsupported foul types, missing spots, or unverified dispositions must remain named failures. Do not turn them into `NO_FOUL` or silently include their source rows.
- Keep raw/nominal rule yards separate from actual enforced yards. In a backend-venv read of the 2025 raw PBP, 179 unnecessary-roughness rows included `penalty_yards` values other than 15 (including 14, 12, 10, 9, 7, and 6). CEG's review found the same issue at larger support: applying half-distance again to these values double-enforces near-goal fouls. Backlog E13 must provide nominal foul yards and a spot for spot-foul categories; the V2 stats adapter credits actual yards only from a rules-enforcement result.
- Split timeout `no_play` rows from pre-snap fouls before sampling; the Phase 1 audit explicitly found both recorded as no-play events.

**Required tests**

- Pre-snap: false start, delay, defensive neutral-zone/encroachment, half-distance, goal line, replayed down, unchanged scrimmage counters, correct clock, and no play-result draw.
- Live-ball: accepted/declined/offsetting, offensive and defensive enforcement, automatic first down, loss of down, spot/after-play foul, nullified versus retained result, and run/dropback/kick contexts.
- Reject unsupported multi-foul/ruling/spot cases by name; prove timeouts are not classified as fouls.
- Verify foul occurrence/type inputs are cutoff-pinned and all eligible no-foul opportunities are represented; score pre-snap, live-ball, and type components on chronological holdouts.
- Confirm each disabled penalty switch produces exact frozen V2 results; test pre-snap and live-ball switches independently through full-game statistics and reconciliation.

**Proposed switches:** `pre_snap_penalties`, `live_ball_penalties`.

### 3. Fumble returns and own-end-zone recovery

**Existing implementation**

- V2 treats a lost fumble as a turnover at the next clean offensive snap. The single event does not preserve whether it was a sack fumble, where it was recovered, who recovered it, or how far the defense returned it.
- The frozen V2 reducer has no `fumble_return`/`defense_touchdown` play event. Its ordinary turnover contract cannot distinguish a defensive touchdown, safety, touchback, same-team recovery, or a new-possession spot.

**Reusable research and code**

- PR #49, merged as `a716c649` with head `54329ad8`, adds a fail-closed own-end-zone resolver and tests in `reducer.py`, `recovery_model.py`, `recovery_endpoint.py`, and `test_own_end_zone_scenarios.py` / `test_forced_state_defensive_touchdown.py`. It distinguishes defensive recovery touchdown, offensive own-end-zone safety, and unresolved recovery rather than guessing. PR #49 is **not an ancestor of this frozen V2 base**, so its changes need a selective, reviewed port.
- The PR #49 audit (`docs/research/own-end-zone-recovery-2026-11-16/AUDIT.md` and `ENDPOINT.md`) supplies recovery-location and post-recovery endpoint evidence. Its primary modern own-goal-line sample is small (2010–2025: 68 fumbles); the audit records unparsed descriptions and says kick recoveries are outside that pool. Treat its rare-event estimates as limited-support evidence.
- CEG Phase 4 constructs `K12_fumble_return` from fumble spot, return yards, team, and touchdown labels. Its 2025 holdout result for fumble-return log loss is inconclusive (216 returns; interval crosses zero). Use the event classification and denominator, not a claim of predictive improvement.
- V1.7 has a separate goal-line geometry filter and forced state tests. These provide useful safety checks, but a filter is not a replacement for modeled recovery and endpoint transitions.

**Remaining gaps**

- Separate fumble occurrence/loss from recovery role, recovery spot, live continuation, return, dead-ball spot, safety, touchback, and defensive TD. Preserve sack-fumble identity for sack/TFL and fumble statistics.
- Use PR #49's geometry and recovery evidence selectively. The current adapter consumes explicit recovery facts; it does not draw the PR #49 RecoveryModel or add a new recovery distribution. Unknown recovery remains an explicit block.
- Add player return/recovery attribution and make team turnover, points, drive ending, try, and restart totals reconcile.

**Required tests**

- Forced-state matrix for offense/defense recovery in field and both end zones; fumbler/teammate recovery; return TD; safety; touchback; out-of-bounds; fourth-down and two-minute restrictions; and unknown recovery.
- Sack-fumble tests preserve sacks, fumbles lost, recovery/return, defensive score, and player/team box-score totals.
- Verify the goal-line geometry filter never manufactures a legal outcome and the recovery model refuses unsupported endpoints by name.
- Matched-seed tests show disabled behavior equals frozen V2; enabled fumble returns differ only through this mechanism.

**Proposed switches:** `fumble_returns`, `own_end_zone_recovery` (separate so field returns can be evaluated without goal-line recovery behavior).

### 4. Sack-probability suppression and sack fumbles

**Existing implementation**

- Sacks are in V2's dropback outcome cells. `e2_reference.py` defines the opt-in `restore_sack_mass` ablation; `slc_playcall.py` traces the substitution. It is off in the frozen full-stack baseline.
- V2's classifier tests `fumble_lost` before `sack`; a sack-fumble can therefore enter the generic fumble-turnover path and lose its sack identity.
- V1.7 has a separate goal-line geometry filter for incompatible sack-fumble source rows. V2's full-stack classifier does not yet have a complete sack-fumble recovery/attribution transition.

**Reusable research**

- The 2025 held-out V2 sack/turnover audit (`slc-sack-turnover-funnel-2026-11-11/README.md`) found that offense-only, defense-only, and combined team event weights all worsened overall held-out five-class log loss. Do not add strength multipliers as a sack correction.
- The three-seed C2 probability trace (`slc-c2-probability-trace-2026-11-11/README.md`) found mean sack probability falling from 6.49% at the exact-cell stage to 2.25% after the full stack; coverage and decision-label weighting account for most of that reduction in this one matchup. The sample is small, and the trace lacks situation fields needed for reliable stratification.
- The saved 40-game generated-context audit found about 6.4% historical base sack probability on generated states while full-stack realized sacks were 2.0–3.3%. It rules against state mix as the only explanation, but does not identify the exact responsible stage. The audit explicitly leaves attribution open.
- `restore_sack_mass` is already a matched ablation mechanism. Preserve it as an experiment; do not promote it solely from the small trace.

**Remaining gaps**

- Re-run probability attribution on reproducible frozen inputs, including exact and sparse-backoff paths, with down/distance/field/score, source cell, active layers, weights, and fallback reasons.
- Decide whether to alter an existing V2 probability stage only after the no-draw held-out score identifies the suppressing stage. Keep any correction independently switchable and separate from the existing team-strength layers.
- Add a distinct sack-fumble event/recovery path; a probability adjustment does not resolve the ball, possession, score, or statistics.

**Required tests**

- Exact-cell and backoff probability tests for every stage and default profile; verify probabilities normalize and the off variant is byte-for-byte V2 behavior.
- Matched-seed comparisons for `restore_sack_mass` and any later suppression correction, with RNG v2 named-stream manifests and the same frozen input hashes.
- Historical held-out proper scores by situation and team-game cluster; report support and uncertainty.
- Full-game sack-fumble tests for sack/TFL, fumble, recovery, return, own-goal-line result, possession, clock, and box-score reconciliation.

**Proposed switches:** retain existing `restore_sack_mass`; add separate `sack_probability_correction` only if a scored correction is justified, and `sack_fumble_transitions` for legal outcome handling.

### 5. Punt return touchdowns, muffs, and possession transitions

**Existing implementation**

- V2 only classifies a punt when the next source snap is a clean receiving-team run/pass with a usable yardline. Punt TDs, muffs, kicking-team recovery without a clean next snap, and punt rows affected by fouls are excluded.
- The V2 reducer has an ordinary punt transition and blocked-kick outcomes, but not a punt return endpoint or muff/return fumble event. Existing blocked-kick handling should remain a separate path.

**Reusable research and code**

- CEG Phase 1 has a special-teams opportunity view with punt result, return yards, next possession, touchdown, touchback, and block labels.
- CEG Phase 4 `K4_punt` classifies legal outcomes as receiving start spot, touchback, blocked kick, return TD, or kicking-team recovery. It covers all 99 punt spots with legal outcome probabilities. The C component did not beat B in the 2025 held-out result (interval reaches zero); this is a reusable event schema and prior, not proof that the richer estimator is better.
- CEG Phase 5's game harness exercises punt return TDs and uses the reducer, but its own status report says the reducer still lacks a native defensive scrimmage TD and the harness scores it from a generated-play layer. It is not a ready-made V2 reducer port.

**Remaining gaps**

- Distinguish punt return, touchback, blocked punt, muff/recovery by either team, dead-ball spot, return TD, and unresolved/period-ending play. Do not label every next-possession mismatch as a muff.
- Record punt attempt, returner, return yards, fumble/lost-fumble, scorer, restart, and clock consistently. Ensure the kicking team recovering beyond the line and receiving team recovery follow the correct possession-relative spot.
- Keep blocked punts on the existing blocked-kick rules contract; do not route them through ordinary punt-return outcomes.

**Required tests**

- Forced-state matrix for ordinary return, touchback, return TD, receiving-team muff recovered by return team, muff recovered by kicking team, kick-team recovery, blocked punt, punt penalty, and quarter expiration.
- Validate possession-relative yardlines, scoring team, returner stats, team punt/turnover totals, clock, kickoff, and game completion.
- Confirm a source row with unknown possession or muff classification remains excluded with a named reason.
- Score the punt outcome distribution across all legal spots and a chronological holdout; run one-switch matched seeds.

**Proposed switch:** `punt_return_events` (blocked-punt behavior remains its existing independent mechanism).

### 6. Overtime play coverage and fourth-down decisions

**Existing implementation**

- The frozen V2 release lineage requires overtime dependencies and sends a regulation tie to overtime. `game_state.py` has overtime possession, scoring, terminal, and validation paths; the overtime reference is distinct from the regulation pool.
- `e1_drive.py` applies a fixed `0.9` field-goal-attempt share on eligible overtime fourth downs. That is the specific policy gap; it is not evidence that the base overtime runtime lacks overtime support.
- The Phase 1 CEG waterfall reports 1,106 overtime rows excluded from V2's regulation pool for 2022–2026. This is expected pool separation, but the dedicated overtime pool needs an event-coverage audit before new categories are enabled there.

**Reusable research**

- CEG Phase 4 scored 93 overtime fourth downs (2022–2025): 48 punts and 25 field goals. Its phase-2 intent model scored log loss 0.555 against 1.014 for the fixed V2 0.9 rule. Use this as evidence to retire the constant and as a held-out test design; keep V2's own model configuration and scoring architecture.
- CEG Phase 3 has clock/timeout and overtime context work; Phase 4 and Phase 5 exercise possession and special-teams transitions under overtime. Phase 7's full-game evaluation provides realism diagnostics but says CEG does not forecast as well as frozen V2 on the examined Week 11 set.

**Remaining gaps**

- Replace the hard-coded 0.9 policy only behind a dedicated V2 switch, using a supported V2-native context-conditioned action model over go/punt/field goal. Preserve the actual overtime rules and current full-game dependency preflight.
- Audit dedicated overtime reference coverage for turnovers, returns, penalties, punt endings, field-goal eligibility, play/clock cutoffs, and the correct rule era. Do not mix overtime source rows into regulation draws.
- Ensure any action policy receives only pre-decision context and handles unsupported cells without hidden fallback.

**Required tests**

- All overtime drive outcomes, first-possession and sudden-death rules, 2025+ both-possession rules, touchdown/return touchdown, try logic, field-goal feasibility, and clock expiration.
- Fourth-down action probability and legality tests for go/punt/field goal across overtime states; held-out action log loss/calibration against the fixed 0.9 baseline.
- Verify regulation behavior and regulation reference hashes remain unchanged when the overtime action switch is off.
- Same-seed full-game comparisons through overtime, including completion, score, possession, and stats.

**Proposed switch:** `overtime_fourth_down_policy`.

### 7. Other exclusions in the CEG waterfall

**Existing implementation and reusable evidence**

- The 2022–2026 V2 classifier exclusions are enumerated above and in CEG Phase 1 `waterfall.json`. The 431 turnover rows without a clean next snap need a cause classification; they must not be merged into the 220 turnover-touchdown rows.
- CEG Phase 1 reports that kickoffs and tries are already handled by V2's other tables. Its 2025 pre-classifier rows also include 4,538 `no_play` rows, 433 kneels, 79 spikes, 128 two-point attempts, and 1,378 administrative rows. `no_play` combines penalties and timeouts and must be split by event meaning before any use. Scrambles are already kept by the V2 stack.
- Negative clock runoffs (64) and missing same-quarter next snaps (33) are source-clock / boundary gaps, not football event categories. Keep them excluded until the clock/event contract resolves their status.

**Remaining gaps and required tests**

- Triage the 431 turnover/no-next-snap rows by verified terminal: touchdown, safety, touchback, period expiry, source error, penalty, or unresolved endpoint. The typed adapter now handles an explicitly evidenced interception touchback; add only categories with their own legal transition and stat contract.
- Separate no-play pre-snap penalties from timeouts. Validate timeout state and clock independently; a timeout must not become a penalty or an extra scrimmage play.
- Treat kneels and spikes as separate play classes with correct participation, clock, downs, passing statistics, and end-of-half decision behavior. Keep administrative rows out of the simulated play vocabulary.
- Preserve named accounting for all exclusions. Tests must assert that each candidate row is either mapped to exactly one legal generated-event class or rejected with an explicit reason, never silently dropped or enabled by removing a filter.

**Proposed switches:** `turnover_terminal_events`, `kneel_events`, `spike_events`, and `timeout_decisions` (with penalties controlled only by their own switches). Timeouts are separate between-snap decisions, not `no_play` play outcomes. Clock-boundary/source-error handling is not an event switch and remains fail-closed.

## Shared event-record proposal for coordination

This is the local `ceg-play-2` extension reviewed by the CEG agent in commits `bcabeb61` and `f985ba33` on `research/slc-ceg-2026-11-24`. The version-1 API remains available and unchanged. The local contract has since incorporated the reviewed details and validator corrections; its adapters remain research-only and are not wired into the frozen V2 runner:

1. **Explicit yardline frame:** scrimmage possession spots use the offense-at-snap frame and are converted when possession changes. Kick event spots use the explicitly documented kicking-team frame, with conversion to receiving-team coordinates after a punt return.
2. **Possession is a fact:** `how` is limited to `kept`, `interception`, or `fumble_recovery`. Turnover on downs and scoring are rules results, not generator assertions.
3. **Penalty enforcement uses raw facts:** carry foul phase/type/side, nominal rule yards before half-distance, and an optional `foul_spot`. The rules engine applies half-distance and next-down state; credited penalty yards come from the resulting enforcement record, not the nominal input.
4. **Automatic first down has evidence:** the rules table lists foul types where first down is deterministic. For the other types, the record carries the observed/modeled flag and provenance.
5. **Play and foul are separate:** preserve the play outcome when a foul is declined. Disposition (`accepted`, `declined`, `offsetting`, or `unknown`) is an explicit decision; an accepted foul does not erase the underlying play facts from the record.
6. **Scoring is typed:** replace `touchdown_team` with `Scoring(kind, team)` for touchdown, field goal, or safety. Rules compute/validate points. Tries are a separate record kind.
7. **Kicks are covered:** define a typed kick result for punt, field goal, and kickoff, including distance/result and the associated possession/return facts. This keeps punt TDs, muffs, blocked outcomes, touchbacks, and field-goal results inside the same event contract.
8. **Clock:** total runoff is required. Live/dead split values are optional but must be present together. Timeout decisions remain separate events.
9. **Player role values are tri-state:** distinguish no such player, an existing but unmodelled slot, and a named player ID. Never assign statistics to an unmodelled slot. Include interceptor, sacker, kick/punt returner, fumbler, recoverer, and passer/rusher/receiver; tackler is optional.
10. **One provenance type:** retain generator/version/components/draw keys and add optional source-row identity/hash for V2 historical sampling.
11. **Unknown sequences fail closed:** laterals and multiple recoveries remain named rejections until the contract represents ordered sequences.
12. **Enforcement basis is explicit:** if `foul_spot` is absent, enforce from the previous spot plus raw assessed yards. Use a foul spot only when the foul's rule specifies spot enforcement; CEG will emit no spot.
13. **Unknown ruling is a rejection:** do not default an unknown disposition to accepted. A pre-snap foul marks the play void and carries no play facts.
14. **Kicks use kick-relative roles:** name kicking and receiving teams explicitly, and express kick spots in the kicking team's direction at the kick. The validator checks which team has the ball after a kick and the corresponding goal-line endpoint. A receiving-team punt return into the kicking team's own goal ends at yardline 100 in this frame; convert the receiving team's next-snap spot before using the ordinary drive reducer.
15. **Version and validation are mandatory:** use contract version `ceg-play-2`; validate every record before the rules adapter sees it. Invalid facts produce a named rejection, never silent repair. The validator also preserves blocked-kick recoveries, negative return yardage, retained-fumble spots, and optional-but-validated clocks; designed runs require a rusher, punt kick-team recovery is represented as a muff, kick safety cases are explicitly unsupported, and interception touchbacks require an explicit restart spot.

V2-specific invariant: V2 populates the shared record from its selected historical row and retains its conditional weights, row selection, and named RNG streams. CEG continues using its own generator. With all expansion switches off, V2 output records and RNG behavior must remain byte-for-byte identical to the frozen base. No new row class is admitted until the complete legal transition and tests exist.

## Promotion gates for any enabled mechanism

1. Unit tests cover event classification, rule enforcement, reducer output, scoring/possession, clock, and attribution.
2. Integration tests run full drives and games with each mechanism forced into boundary cases; all records pass game and player/team reconciliation.
3. Each switch-off result reproduces the frozen V2 baseline for the same seed IDs and frozen input hashes. Each switch-on run records its distinct model/config hash and uses the same RNG protocol and seeds.
4. Historical component scores use chronological holdouts, explicit denominators, source hashes, support counts, and uncertainty. Rare/ambiguous classes stay excluded where evidence is insufficient.
5. Shared rules/reducer changes are reviewed against V1 Complete and CEG contracts before implementation. V1, V1.5, V1.6, V1.7, released V2, and PBV1 artifacts remain untouched.

## Source index

- Week 11 frozen model mapping: `docs/research/week11-1k-batch-2026-11-22/REPORT.md`.
- V2 historical classifier: `scripts/nfl_sequence/e1_drive.py`; reducer: `scripts/nfl_sequence/reducer.py`; game/OT rules: `scripts/nfl_sequence/game_state.py`; statistics: `scripts/nfl_sequence/game_stats.py`.
- V2 sack audits: `docs/research/slc-v2-conditional-outcome-audit-2026-11-10/README.md`, `docs/research/slc-sack-turnover-funnel-2026-11-11/README.md`, `docs/research/slc-c2-probability-trace-2026-11-11/README.md`; ablation: `scripts/nfl_sequence/e2_reference.py` and `scripts/nfl_sequence/slc_playcall.py`.
- V1.7 penalty core and later integration: `docs/research/SLC-V2-INHERITS-V1.7-PENALTY-CORE-2026-11-12.md`; frozen V2 copies `penalty_fit.py`, `penalty_sampler.py`, `penalty_enforcement.py`, `penalty_transition.py`; later V1.7 branch additions `penalty_game.py`, `penalty_rulings.py`, `penalty_scrimmage_kick.py`, `penalty_train.py` and corresponding tests.
- PR #49 own-end-zone recovery: merge commit `a716c649`, head `54329ad8`; `docs/research/own-end-zone-recovery-2026-11-16/` and `recovery_model.py`, `recovery_endpoint.py`, reducer/game tests on its source branch.
- CEG Phases 1–7: `research/slc-ceg-2026-11-24` (Phase 7 report commit `6b3bc79f`; Phase 1–4 files are linked from that branch's `README.md`). Relevant sources: `ceg_event_tables.py`, `ceg_waterfall.py`, `ceg_phase2.py`, `ceg_clock.py`, `ceg_special.py`, and `ceg_game.py`. CEG data tables and fitted artifacts live outside Git under `/root/slc-ceg-data`; they are research inputs, not V2 runtime dependencies.
- Shared `ceg-play-2` review: CEG commits `bcabeb61` and `f985ba33`, `docs/research/slc-ceg-2026-11-24/CONTRACT-REVIEW-ceg-play-2.md`; CEG accepted the target after the listed clarifications. The actual shared code/interface still needs V1 Complete coordination before it is added or changed.
- V2 event-expansion prototype: `scripts/nfl_sequence/ceg_contract.py`, `event_expansion.py`, `event_expansion_rules.py`, `event_expansion_stats.py`, and `penalty_event_mapping.py`. These modules are research-only and are not imported by `e1_drive` or the full-game runner.
- Cross-project learnings: `docs/SIMULATION-LEARNINGS.md`, especially the documented separation of realistic event mechanics, statistical realism, and predictive accuracy.
