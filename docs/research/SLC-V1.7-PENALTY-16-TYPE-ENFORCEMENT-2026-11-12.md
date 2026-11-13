# V1.7: 16-type penalty enforcement contract (shared by later models)

**Implementation:** `scripts/nfl_sequence/penalty_enforcement.py`  
**Bridge:** `scripts/nfl_sequence/penalty_transition.py`  
**Model taxonomy:** `scripts/nfl_sequence/penalty_fit.py:CATEGORIES`  
**Rules reference:** [Official 2026 NFL Rulebook](https://operations.nfl.com/rules-officiating/2026-nfl-rulebook), Rules 4, 7, 8, 12, and 14.

The rule registry asserts at module import that the enforcement and model catalogs have the **same 16 side/type pairs**. A new model label without an enforcement entry fails immediately.

## Supported model labels

| Phase | Committing team | Foul | Enforcement for a legal supported scrimmage state |
| --- | --- | --- | --- |
| Pre-snap | Offense | False start | 5 yards, no snap, same down |
| Pre-snap | Offense | Delay of game | 5 yards, no snap, same down |
| Pre-snap | Defense | Encroachment | 5 yards, no snap, first down if sticks reached |
| Pre-snap | Defense | Neutral zone infraction | 5 yards, no snap, first down if sticks reached |
| Live | Offense | Offensive holding | 10 previous spot on passing downs; run requires actual foul spot |
| Live | Offense | Offensive pass interference | 10 yards previous spot, replay down |
| Live | Offense | Illegal block | **Requires** official subtype `in_back` or `above_waist`, plus foul spot; 10 yards from spot |
| Live | Offense | Intentional grounding | Loss of down; passer's release spot or 10 yards behind previous spot, whichever is less advantageous, with own-goal-line exception |
| Live | Offense | Illegal formation | 5 yards previous spot, replay down |
| Live | Offense | Illegal shift | 5 yards previous spot, replay down |
| Live | Offense | Illegal motion | 5 yards previous spot, replay down |
| Live | Defense | Defensive holding | 5 yards previous spot, automatic first |
| Live | Defense | Defensive pass interference | Foul spot and first down; defensive end-zone cases spot at 1 or half-distance |
| Live | Defense | Illegal contact | 5 yards previous spot, automatic first, dropbacks only |
| Live | Defense | Roughing passer | 15 previous spot if incomplete; 15 from end of completed pass/run if complete; automatic first |
| Live | Defense | Offside | 5 yards previous spot, replay down (decline preserves completed free play) |

**Field positioning:** supports half-distance to either goal including half-yard spots. Goal-to-go chains use the new spot instead of always resetting to 10. Fourth-down intentional grounding can award possession to the explicitly named opponent. Accepted roughing after a complete pass retains the completed play; ordinary accepted fouls nullify the play. Returned `Enforcement` includes `play_counts`, `replay_down`, `automatic_first_down`, `loss_of_down`, `turnover_on_downs`, `clock_action`, `enforcement_spot` and `safety` metadata.

## Inputs the caller may not guess

- **DPI:** actual foul spot (including 0 for defensive end zone).
- **Intentional grounding:** actual QB release spot; behind LOS and sometimes loss of possession.
- **Offensive holding on a run:** actual block/holding spot.
- **Illegal block:** actual foul spot **and** a verified subtype. The model's generic `illegal_block` event is not enough by itself to distinguish 10-yard blocks from various 15-yard personal fouls. Unknown block subtype fails closed.
- **Roughing passer:** complete/incomplete pass outcome; end-of-run enforcement for completed passes.
- **Fourth-down grounding:** defending team ID to assign possession following loss of down.

The rules implementation must **never** invent the missing variables from event labels, historical means, or seed hashes.

## Explicitly not integrated/unsupported

This extends **single-foul scrimmage enforcement**, not the full NFL officiating and game-stat engine. It still does not decide whether a sampled foul should be accepted/declined, combine offsetting/multiple fouls, apply clock/runoff/timeout administration, adjust scoring/safety/free-kick transitions, preserve appropriate return-penalty possessions, or handle scrimmage-kick-specific rules. A safety from intentional grounding thrown in the offense's own end zone is recognized as requiring scoring integration and **does not silently become an ordinary loss of down**. Kick-specific variants of `illegal_formation` likewise remain excluded until modeled distinctly.

Invalid phase/play class, missing spot facts, unsupported scoring/possession changes and ambiguous illegal blocks raise an explicit exception. These are intentional non-coverage boundaries, not successful enforcement simulations.

## Version inheritance

- **V1.5/V1.6:** existing frozen semantics stay unchanged.
- **V1.7:** this is the authoritative implementation after merge to `feature/slc-v1.7-penalty-model-2026-11-12`. Do not duplicate 16-rule tables in `penalty_transition.py` or the game state engine.
- **V2 and subsequent:** use the same `penalty_enforcement.py` rules interface **by bringing the V1.7 release forward into V2's implementation**. An existing V2 branch without the imported code does **not** acquire it automatically. Re-run the full 16-label coverage suite and penalties-OFF V1.6/V2 parity before enabling the layer in new model profiles.
- Rule changes from later seasons require an explicit versioned ruleset, not silent edits to the 2026 frozen tables.

## Tests

Run:

```bash
PYTHONPATH=scripts/nfl_sequence python -m unittest -v \
  test_penalty_fit test_penalty_sampler test_penalty_train \
  test_penalty_enforcement test_penalty_transition
```

Required: exact catalog parity; accepted fixture for **every** label; source-dependent fail-closed paths; pre-snap, live run/dropback, goal-to-go, half-distance, DPI in end zone, grounding loss of down, fourth-down turnover, and roughing after a catch. These tests are pure-Python and independent of unfinished historical penalty training.

**V1.7 release gate remains open:** this enforcement code is not a fitted penalty model, a full-game implementation, or evidence of calibrated penalty rates.
