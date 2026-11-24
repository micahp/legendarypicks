# SLC-CEG Phase 0: historical-row dependency audit

Date: 2026-11-24. Plan: `docs/research/SLC-CONDITIONAL-EVENT-GENERATION-PLAN.md`. Audited code: the v2 engine at
`8a1d9842` (`scripts/nfl_sequence/`), which v2, pbv1 and pbv1-off run. v1, v1.5 and v1.6 share the same structure; their
differences are noted where they matter. No model was fitted and no engine code was changed.

## Result

- **The seam is one call.** Every scrimmage snap goes through `e1_drive.simulate`, which asks the sampler for
  `(event, row, runoff, spot)` and passes `event, yards, spot` to `reducer.apply_play`. The historical `row` is used after
  that only for its identity (`game_id`, `play_id`) and a few fields. A conditional generator can return the same tuple
  with a generated row, and the reducer, clock, statistics and validation stay as they are.
- **The row is a carrier for more than yards.** Through `(game_id, play_id)`, the game-state code looks up the source
  play's air yards, yards after catch, timeout and timeout team, and out-of-bounds flag
  (`game_state.participants_for`). The clock runoff also comes from the row's next snap. So "generate the yards" is not
  enough: the generator must also produce air yards, YAC, a clock runoff, a timeout and an out-of-bounds flag, or the
  statistics and clock lose them.
- **Some plays can never be drawn in v2,** because the pool builder (`e1_drive.classify`) drops their rows: penalties
  (every pre-snap foul and 3,075 live-play fouls, 2022 to 2026), turnovers returned for a touchdown (220), and overtime
  plays (1,106, regulation-only pool). So a v2 game has no penalties and no defensive scrimmage touchdowns. That is a
  realism gap, not only a sparse-cell risk. *Corrected 2026-11-24 by the Phase 1 waterfall:* last plays of a quarter are
  kept (only 33 plays lack a next snap), and scrambles are kept when `include_qb_scrambles` is on, as in the QB-decision
  stack. See `PHASE1-DATASET-AUDIT.md` section 3.
- **17 dependency sites** (D1 to D17 below). 12 draw a historical row or record at runtime, 4 use count tables or fixed
  shares (D2, D8, D13, D17), and 1 is left out entirely (D16, penalties). The 99 week 11 failures come from 6 of them:
  D2, D3, D6, D8, D10 and D12.

## The game lifecycle and where history enters

| Step | Code | Historical dependency |
|---|---|---|
| Coin toss, kick or receive | `game_state.play_game` (seeded `choice(['A','B'])`, `choice(['receive','defer'])`) | none |
| Opening and second-half kickoff | `_Game._kick` | row from `kickoff_pool` (spot and runoff) |
| Each snap: cell | `e1_drive.simulate` | `pool[(down, distance bucket, field bucket)]`, refuse below `MIN_POOL` 50 |
| Each snap: play call | `slc_playcall.sample` | intent shares from the play-call artifact cell (`entry['base']`), score-clock conditioned |
| Each snap: participants | `pre_event.choose` | roster shares (`share_distributions`, prior season), no history rows |
| Each snap: outcome | `slc_playcall.sample` (outcome, backoff, row weights) | a row from the cell, or from a backoff level |
| Punt | `_resolve_special_teams`, then reducer | the row's next-snap spot; blocked-punt rate table |
| Field goal | `_resolve_special_teams` | distance model or bucket counts; blocked-kick records |
| Missed field goal | `_missed_field_goal_transition` | record from `missed_field_goal_pool` |
| Blocked kick | `_sample_blocked_kick(_by_category)` | audited blocked-kick records |
| Turnover | reducer with the row's spot | the row's next-snap spot for the new offense |
| Clock | `e1_drive.simulate`, `_record_clock_transitions` | the row's runoff; or the research clock model |
| Timeouts | `_apply_timeouts`, `_TimeoutSamplingGuard` | the row's timeout flag and team |
| Two-minute warning | `two_minute_stop` | none (rule) |
| Touchdown try | `_try_after_touchdown` | try count tables; optional try policy |
| Safety free kick | `_Game._kick('safety_free_kick')` | row from `safety_kick_pool` |
| Overtime | `_begin_overtime`, then the same drive loop | toss seeded; choice model (2025 observed share); 4th-down kick share fixed at 0.9 |

`_observed_overtime_drive` (whole observed overtime drives) is defined but not called at `8a1d9842`. `overtime_pool` only
switches overtime on.

## Dependency matrix

Week 11 failures are from `docs/research/week11-rerun-preflight-2026-11-23/seed_completion.json` on
`fix/roster-preflight-2026-11-22` (v1 56, v1.5 41, v1.6 2). "Replace with" names the simplest conditional baseline (arm B
or C). Every replacement must keep the reducer's legal-state checks.

### D1. Scrimmage cell and floor

- **Code:** `e1_drive.simulate`, `pool[e0.pool_key(down, ydstogo, yardline_100)]`, `MIN_POOL = 50`;
  `e1_drive.build_pool` / `classify`.
- **Method:** the cell is every classified 2022 to 2025 play with the same down, distance bucket and field bucket. A cell
  under 50 rows stops the seed unless `allow_sparse_cells`.
- **Labels used:** play type, yards gained, sack, interception, fumble lost, complete pass, next snap.
- **Failures:** none in week 11 with the fixes on (`allow_sparse_cells` is on with `run_scramble_backoff`).
- **Replace with:** no cell. The state is model input.
- **Constraint:** down 1 to 4, distance 1 to 99, field 1 to 99.
- **Test:** synthetic states across every (down, distance, field, quarter, clock) combination complete without a refusal.

### D2. Play call (intent)

- **Code:** `slc_playcall.sample` (keys and `rng.choices` at lines 566, 654, 674), `historical_cell_dropback_probability`.
- **Method:** shares of run, dropback, punt, field goal, kneel, spike in the artifact cell for the state, reweighted by
  score-clock, team tendency, formation, labels.
- **Labels:** play type by intent, `xpass` available.
- **Existing models:** nflverse `xpass` (dropback probability from down, distance, field, score, time, timeouts);
  `nfl_proe_feature.py`; the 4th-down go-rate work (rejected as a team prior, see Failed experiments).
- **Failures:** `no_supported_scrimmage_intent_in_cell`, `playcall_no_run_outcomes_in_cell` (v1 8, v1.5 3).
- **Replace with:** multinomial logistic P(intent | down, distance, field, score differential, time, timeouts), league
  level (arm B), then situational terms (arm C). 4th down: P(go, punt, FG) as its own model.
- **Constraint:** FG only within the feasibility ceiling; kneel and spike only when legal; punt and FG on any down are
  legal but rare before 4th.
- **Test:** per-play log loss against the artifact cell shares, chronological (tune 2025, test 2026).

### D3. Scramble versus designed run class

- **Code:** `slc_playcall.sample` lines 704 to 712.
- **Method:** after the QB-decision layer picks scramble or not, only rows of that class in the cell can be drawn.
- **Failures:** `qb_scramble_source_rows_missing` (v1 23, v1.5 14), `non_scramble_run_source_rows_missing` (v1 10,
  v1.5 14). The largest single failure class.
- **Replace with:** P(scramble | dropback, down, distance, field, QB) and a separate scramble-yards distribution.
- **Constraint:** a scramble credits QB rushing, never a target.

### D4. Scrimmage outcome and yards

- **Code:** `slc_playcall.sample` lines 782 to 792 (transition key, then a row); `_backoff_candidates`,
  `_materialized_backoff_candidates` (levels exact cell 10, down and field 25, down and distance 25, field zone 50,
  league intent 50).
- **Method:** draw an event class, then one historical row, whose `yards_gained` is the result.
- **Labels:** event class, yards gained, touchdown.
- **Existing models:** none fitted as a distribution; the backoff is the de facto smoother.
- **Replace with:** by intent, P(event class | state) (run: gain, fumble lost; dropback: complete, incomplete, sack,
  interception, sack fumble), then a yards distribution per class conditioned on field position. Start with a smoothed
  discrete distribution over -20 to +99 truncated to the field, then compare a mixture or skew-t (Journal of Sports
  Analytics 2023) with a touchdown mass.
- **Constraint:** gains never exceed the yards to the goal line; losses never pass the own goal line (the reducer refuses
  both); a sack has yards at most 0.
- **Test:** event log loss and yardage CRPS per opportunity; drive-level realism.

### D5. Air yards and YAC

- **Code:** `game_state.participants_for` reads `air_yards` and `yards_after_catch` from the source play.
- **Replace with:** for a completion, P(air yards | state, receiver position), then YAC given air yards, with the sum
  equal to the generated yards. For an incompletion, air yards only.
- **Constraint:** air plus YAC equals yards gained; attribution follows `game_stats`.

### D6. Turnover spot and sack fumbles

- **Code:** `reducer.apply_play` with the row's `spot` (the new offense's next snap); in v1.6 the separate
  `sack_fumble_lost` event uses the row's yardage (2 week 11 failures; fixed in `cf8fd47b` with the geometry filter).
- **Method:** the spot is copied from the source game, at a different field position.
- **Replace with:** P(return yards | turnover type, spot of the turnover), applied from the generated spot. Defensive
  touchdown as a mass at the end zone.
- **Constraint:** spots 1 to 99 or a touchdown; a fumble behind the own goal line resolves to a safety or a touchdown,
  never a refusal (the V1.7 resolver, PR #49, is the rule reference).

### D7. Punt result

- **Code:** `e1_drive.classify` (punt spot = receiving team's next snap), `_resolve_special_teams` (blocked rate).
- **Replace with:** P(net punt yards | punt spot), touchback mass, block rate, return-touchdown mass.
- **Constraint:** receiving spot 1 to 99 or a touchdown.

### D8. Field goal result

- **Code:** `_resolve_special_teams`; `long_field_goal_feasibility` distance model, else bucket counts with
  `MIN_KICK_N`.
- **Failures:** `thin_kick_cell:field_goal:50+` (v1 2, before the fixes).
- **Existing model:** the long field goal distance model (keep).
- **Replace with:** the distance model everywhere (P(made | distance)); a block rate.

### D9. Missed field goal next spot

- **Code:** `_missed_field_goal_transition`, `missed_field_goal_pool`, `MIN_KICK_N` fallback to all buckets.
- **Failures:** `missed_field_goal_return_pool_unavailable` possible; none in week 11.
- **Replace with:** the rule spot (`missed_field_goal_spot`) plus a small return-adjustment distribution.

### D10. Blocked kicks

- **Code:** `_sample_blocked_kick`, `_sample_blocked_kick_by_category` (audited records); reducer `apply_blocked_kick`.
- **Failures:** `blocked_kick_receiving_return_outside_field` (v1 5, v1.5 5), `blocked_kick_kicking_recovery_outside_field`
  (v1 3, v1.5 1), `blocked_kick_outcome_unresolved` (v1 4, v1.5 3).
- **Replace with:** P(recovery side | kick type) and a recovery-and-return distribution in yards from the kick spot.
  This is rare: use a documented population prior and record it as such.

### D11. Kickoffs

- **Code:** `_Game._kick`, `kickoff_pool` (`build_kickoff_pool`), regime filter (`regime_kickoffs`).
- **Replace with:** P(touchback, return spot, onside, recovery | kickoff rule regime). The 2025 to 2026 kickoff rule
  makes the regime a required input.

### D12. Safety free kick

- **Code:** `_Game._kick('safety_free_kick')`, `safety_kick_pool` (46 records); `safety_free_kick_not_modelled` (v1 1, v1.5 1).
- **Replace with:** the kickoff model with a free-kick flag.

### D13. Tries

- **Code:** `_try_after_touchdown`, `kicks['extra_point']`, `kicks['two_point']`, optional `try_policy`.
- **Existing model:** the context-conditioned two-point decision model (2025 Brier 0.04256 against 0.08362
  unconditional, `docs/STRATEGY-GRANULAR-PREDICTION-MODELS-2026-10-26.md` section 2). Keep.
- **Replace with:** that decision model plus P(made | kind) by rule regime.

### D14. Clock runoff

- **Code:** `e1_drive.classify` (runoff = this snap's game seconds minus the next snap's), the optional research clock
  model (`clock_d`, `ref.clock_model`).
- **Existing model:** the PBP conditional clock model (week 5 holdout median absolute error 6.19 s against 15.99 s,
  `docs/evidence/e3/PBP-CONDITIONAL-CLOCK-MODEL-WEEKS1-5-2026-10-24.md`). Reuse.
- **Replace with:** P(runoff | event class, in-bounds, clock state, score, timeouts).

### D15. Timeouts and out of bounds

- **Code:** `_apply_timeouts`, `_TimeoutSamplingGuard` (`timeout_sampling_guard_rejected_source_row`,
  `timeout_limit_exceeded`); `out_of_bounds` from the source play.
- **Replace with:** P(timeout by offense or defense | clock, score, timeouts left), P(out of bounds | event class).

### D16. Penalties

- **Code:** `e1_drive.classify` drops penalty plays; `_drive_body` blocks `penalty_not_modelled`. The V1.7 penalty layer
  (`feature/slc-v1.7-penalty-model-2026-11-12`) models them for v1.7 only.
- **Replace with (phase 4):** P(penalty, type | play class), with enforcement by the V1.7 shared rules core.

### D17. Overtime decisions

- **Code:** `_begin_overtime` (choice model, observed 2025 share), `OVERTIME_FOURTH_DOWN_KICK_SHARE = 0.9` (fixed).
- **Replace with:** the D2 4th-down model with an overtime flag, replacing the fixed 0.9.

### Player selection (no history rows; keep)

`pre_event.choose`, `share_distributions.game_shares`, `formation_layer.choose`, `decision_layer.draw` draw from fitted
shares and the roster, not from rows. Keep them. The step 1 result on `research/slc-v1-conditional-opportunity-2026-11-23`
(in-season usage with a cross-team prior: per-opportunity log loss 1.910 to 1.614 on 2026) is the first candidate to
replace the prior-season-only share (plan arm D).

## Previous experiments to not repeat

| Experiment | Result | Source |
|---|---|---|
| Historical team strength on transitions | Worse than the league situation cell: 2025 log loss 2.0576 against 1.9920; 2026 2.0450 against 1.9811 | `docs/research/slc-transition-walk-forward-2026-11-10/README.md` |
| Current-season team blends (N0 2, 4, 8) | Better than historical strength, still worse than the league cell | same |
| Offense-only and defense-only outcome conditioning | League cell 0.5404 beats offense-only 0.5456 (2025) | `slc-v2-conditional-outcome-audit-2026-11-10` |
| Corrected matchup on penalty and sack rows | League 0.5185 beats matchup 0.5313 (2026) | `slc-v2-penalty-opportunities-2026-11-10` |
| P1 team tempo prior | Rejected: worse than the league baseline in 2024 | `SLC-V2-M4-M7-DECISIONS-2026-11-02.md` |
| P1 team 4th-down go rate prior | Rejected: no gain over the coach-era prior | same |
| P3 defensive matchup | Rejected: no outcome beats the baseline; TE and RB receiving worse in 2023 | `slc-v2-p3-defense-2026-11-02/REPORT.md` |
| v2 workload | Worse than v1.5 on carries, targets, receptions, receiving yards | `SLC-V2-VS-V15-RESULTS-2026-11-04.md` |
| QB decision layer, pass or scramble | 2025 log-score gain not significant (-0.00099, interval spans 0) | `SLC-LAYER-CALIBRATION-AUDIT-2026-10-29.md` |
| PBV1 personnel package | Label only: no reader, no effect on any output | `docs/research/pbv1-off-audit-2026-11-23/` on `fix/roster-preflight-2026-11-22` |

The common lesson: team and matchup terms added to a situation cell have lost to the plain league situation baseline.
CEG starts from league-level conditional models and adds a team term only when it wins on chronological validation.

## Event-generation interface

A provider replaces `contextual_sampler.sample` at the existing seam and keeps its return contract.

```text
EventProvider (versioned; one manifest names the component versions)
  model_id, version, manifest_sha256
  play_call(state, context, rng) -> {intent, probabilities}
  scrimmage(state, intent, participants, rng) -> GeneratedPlay
  special_teams(kind, state, rng) -> GeneratedKick          # punt, field goal, kickoff, free kick, blocked kick
  try_after_touchdown(state, rng) -> {kind, made}
  timeout(state, rng) -> {team or None}

GeneratedPlay  (what e1_drive and game_state read today)
  event        one of e1.EVENTS
  yards        integer, legal for the state
  spot         new offense's spot for a turnover or punt, else None
  runoff       clock seconds to the next snap
  facts        {air_yards, yards_after_catch, out_of_bounds, timeout, timeout_team, touchdown}
  sampled_from {generator: model_id@version, draw_id}   # replaces the source (game_id, play_id)
  probabilities  the distribution the draw came from, for the decision log
```

`game_state.participants_for` reads `facts` from `GeneratedPlay` instead of looking up the source play. That is the one
change outside the provider, and it is behind the provider switch, so the frozen samplers run unchanged.

The portable pack stores the fitted parameters, not play rows. Test: build a CEG pack, delete `ref.pool`, the kickoff,
safety, missed field goal and blocked kick pools from the loaded reference, and complete games.

## Migration order and acceptance tests

| Order | Scope | Done when |
|---|---|---|
| 0 | This audit; frozen baselines reproduce | the 5 frozen packs give the same CIN at WAS seeds 300001 to 300003 as the week 11 batch (see Baseline reproduction) |
| 1 | Event tables 2022 to 2026 from nflverse play-by-play, cutoff-safe, with the denominators of the strategy doc section 7 | counts reconcile with nflverse play totals per game |
| 2 | D2, D3, D4, D5, D6 (scrimmage), league level (arm B) | the 97 v1 and v1.5 week 11 failure states and a synthetic state grid complete with no refusal; event log loss reported against the cell shares |
| 3 | D14, D15 clock and timeouts (reuse the clock model) | drive durations and plays per game match 2025 within the realism gates |
| 4 | D7 to D13, D16, D17 special teams, tries, penalties, overtime | every lifecycle step in the table above runs from a model |
| 5 | Full game with all row pools removed from the pack | complete games; validation passes |
| 6 | Arms C and D | each term beats arm B chronologically |
| 7 | Walk-forward against arm A (frozen v2) and the market | the five scorecards of the plan section 12 |

## Baseline reproduction

The frozen v1, v1.5, v1.6, v2 and pbv1 packs (`/root/runs/week-11/inputs/models/portable-models-2026-11-19/`) are rerun
on CIN at WAS seeds 300001 to 300003 with the pre-rules-fix registry (`/root/runs/week-11/frozen-runtime`) and compared
with the week 11 batch outputs. **Result: all five reproduce exactly** (identical outcomes and box scores, same pack hashes); `baseline_reproduction.json`.
