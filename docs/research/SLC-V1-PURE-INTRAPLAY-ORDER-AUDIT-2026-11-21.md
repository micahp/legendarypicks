# V1-Pure intra-play order audit (2026-11-21)

**Gate: FAIL / NOT IMPLEMENTED.** V1-Pure is a stripped *whole-play statistical simulator*. It has **not** been shown to execute the causal order of a real individual play. It retains the V1 E1/E2 engine. A valid full-game flag, a reconciled clock, or a final score is NOT evidence that the internal play's operations were simulated in football order.

## Source-grounded execution ordering (V1 code retained in V1-Pure)

Pinned V1 base: `6895c2e309e9a0de1339fe9829a0bcb21cba9355`. V1-Pure research branch: `research/slc-v1-pure-2026-11-21`.

| Order | Code and lines | Actual behavior |
| --- | --- | --- |
| 1 | `e1_drive.py:250-277` | Context cell and a play sampler select the **whole** event plus an observed source row, runoff and spot. |
| 2 | `slc_playcall.py:366-430`, `pre_event.py:108+` | The sampler selects run/dropback/kick, then its pre-event chooser draws participants (and optional decision labels/formations if enabled). V1-Pure disables the latter filters. |
| 3 | `e1_drive.py:301-305` | Take the historical source row's `yards_gained` and apply a legal boundary cap. |
| 4 | `e1_drive.py:306-309` | **Apply the entire play outcome** using `reducer.apply_play`; downs, ball spot, possession, TD or turnover are immediately resolved. |
| 5 | `e1_drive.py:333-345` | **Only after the reducer** sample or retain the snap-to-next-snap clock runoff. |
| 6 | `e1_drive.py:365-440` | Construct one play record with `state_before`, `event_type`, `outcome` and `state_after`; `decision.concept = None`. |
| 7 | `game_state.py:1419-1476` | Simulate an entire drive, then derive participant attribution, apply timeout flags and create clock-restart metadata. |

`e1_drive.classify` at lines 108–158 **excludes historical plays with penalties** and maps whole PBP plays to compact events (`run`, `pass_complete`, `pass_incomplete`, `sack`, `interception`, `fumble_lost`, `punt`, etc.). `reducer.apply_play` at lines 56–115 only receives `event`, `yards`, `spot`, and optional kick result; no blocking, catch, tackle, pressure or fumble-in-progress state exists. `clock_d.BoundaryClock.draw` at lines 213–252 samples a **snap-to-next-snap interval** given the completed event, not separately the live-ball and dead-ball phases. The timeout attribution in `game_state.py:981-1015` comes from the sampled source play and is applied after a drive is simulated, not chosen in a distinct pre-snap decision state.

This code is valid as a research **discrete end-of-play state generator** for its supported subset. The implementation cannot establish the right order of operations *inside a play*, because those intermediate operations are not represented.

## V1-Pure first-snap status

The earlier pushed V1 first-snap record `docs/research/slc-play-selection-audit/v1-control.json` (on the portable branch, source `58ef3861`) uses seed 300001 and a different snapshot from the pushed V2 single-game export. It shows first down, Q1 15:00, intent run, source event run, and an entire historical source row selected after probability weighting/filtering. It is **not** a new V1-Pure game and **not** a matched V1/V2 intra-play trace. The first-pass V1-Pure launcher's config removes optional conditioning only; it does not create the missing intra-play states.

## What would actually count as proof

An explicit phase-separated event contract for at least the following:

1. Before snap: game state, substitutions/personnel, an actual called play where modeled, alignment, any dead-ball timeout or penalty; the play call precedes the visible pre-snap look. **PBV1 is the playbook workstream**; distinguish a modeled package from a validated full named play.
2. Snap: possession of the ball, ball motion, live game clock, and legality; a false start or other dead-ball foul cannot be implemented as a sampled complete run.
3. Live-ball sequence: ball transfer or QB dropback, pressure/blocking interaction, handoff/throw/catch or incompletion, runner advancement, loss of possession and recovery/return where relevant. Any process not modeled must be explicitly marked `unmodeled`, not silently implied by a final outcome.
4. Dead-ball boundary: whistle, dead-ball spot, live-ball length, fouls and enforcement, possession/downs, and clock stop/restart; no next-snap decision occurs before this state commits.
5. Next-snap state: exact invariants for offense, defense, spot, first-down/goal-to-go, clock, timeout count, score and statistics. Replay **observed** sequences against successive historical PBP states, with a source-tagged mismatch report, on multiple held-out games.

Distinguish two distinct gates:
- **Boundary-transition parity:** Given an externally fixed actual play event, verify the reducer produces the recorded **next-play** state. This is achievable with good PBP fields, and the repository has relevant unit/replay tests.
- **Intra-play causal fidelity:** Verify **intermediate** events in the right order using play-level charting/film/tracking or a rules-specified simulator with dedicated tests. Ordinary PBP start/end fields cannot by themselves certify this. No such evidence is present for V1-Pure.

Passing one gate does not imply passing the other.

## Audit of existing tests

`test_e1_transitions.py` exercises legal boundary and quarter behavior using synthetic rows.
`test_clock_d_replay.py` tests historical clock runoff and clock stop classification.
`test_game_state.py` tests many game-state and timeouts/clock cases.
`test_replay_evaluation.py` concerns forecast/score replay evaluation, not physical or causal within-play execution.
These tests protect important components, but do not assert an ordered series of within-play events and therefore cannot pass this gate.

## Release status

- V1-Pure **research baseline:** permitted to run and report as a simplified end-of-play generator.
- V1-Pure **football-ordered execution:** **NOT IMPLEMENTED / must not be claimed**.
- V1.8 **pre-snap coaching / timeout concept:** separate and unvalidated, not a V2 feature.
- V2-Pure: separately owned by the other workstream. No claim here about its completed play fidelity.
