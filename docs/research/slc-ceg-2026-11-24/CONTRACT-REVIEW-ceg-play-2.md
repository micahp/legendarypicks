# Review: the proposed `ceg-play-2` record, from the CEG side

Date: 2026-11-24. Reviewed: `docs/research/SLC-V2-EVENT-EXPANSION-INVENTORY-2026-11-24.md`, section "Shared
event-record proposal for coordination" (V2 branch `research/slc-v2-event-expansion-2026-11-24`). Against:
`ceg_contract.py` (`ceg-play-1`), the CEG generator, harness and game loop, and the Phase 9 drive test.

## Verdict

CEG agrees with the direction: one typed record that both models populate, with scoring and foul enforcement
decided by the shared rules. Phase 9 needs no contract change. Eleven points to settle before implementation;
1 to 5 change what CEG emits.

## Points

1. **One yardline frame for every spot.** `ceg-play-1` states `dead_ball_yardline_100` from the offense's direction
   at the snap. The proposal adds turnover, recovery and dead-ball spots. All of them should use that one frame; the
   rules adapter flips it for the new offense. Today the CEG harness does the flip itself (`100 - dead`). That moves
   into the adapter.
2. **Possession states facts, not rules results.** `Possession.how` in `ceg-play-1` includes `downs` and `score`.
   Those are rules outcomes, so the generator should not assert them. Keep `kept`, `interception` and
   `fumble_recovery`. Let the rules derive turnover on downs and the score.
3. **Foul enforcement by the rules needs the raw yardage.** CEG draws the foul type (K9), its side and phase (K8a,
   K8b), and the yards from that type's observed list. It models no foul spot. So spot fouls such as pass interference
   are a yardage draw, not a spot. The record should carry `yards_assessed` (before half-distance) beside the optional
   `foul_spot`, and the rules should apply half-distance and the down. Today `ceg_game.PenaltyProvider` computes
   `penalty_after` itself, and `e1_drive` uses it without the reducer. With this record, that code goes to the rules.
4. **Automatic first down is not always fixed by the type in nflverse coding.** CEG samples it per type from the
   observed rate (`first_down_rate`). The rules table should list the types where it is deterministic. For the others,
   the record should carry the flag as a stated fact with its provenance (a source row for V2, a sampled draw for CEG).
5. **Disposition is a decision, not a play fact.** Accepted, declined and offsetting are choices made after the play.
   For a declined foul, the record must keep both the play facts and the foul. CEG now replaces the whole play with an
   accepted foul (a stated simplification). The record should hold the play and the foul separately, plus a decision
   field (from the source row for V2; from a model, or "accepted" stated as a prior, for CEG).
6. **`Scoring` replaces `touchdown_team`.** CEG will migrate the generator, harness, game loop and the Phase 9 tally
   (they read `touchdown_team` and `possession.team`). Store the kind and the team, and let the rules compute the
   points, or validate that the points match the kind. Tries (extra point, two-point, defensive two-point return) should
   be their own record kind, not a flag on the scrimmage play.
7. **Kicks are not in the proposal.** `ceg-play-1` returns a punt or a field-goal attempt as a bare event. The CEG game
   loop resolves it with K4 and K5 outside the contract. If V2 wants typed kick outcomes (distance, touchback, block,
   return, muff, made or missed), `ceg-play-2` should either define a kick record or state that kicks are a separate
   record. Leaving it open would put special teams back outside the typed path.
8. **Clock: allow a split that is unknown.** CEG fills live seconds and dead-ball seconds separately (Phase 3). A
   historical V2 row knows only the total runoff. Make `runoff_seconds` required, and `live_seconds` and
   `dead_ball_seconds` optional together. Keep `TimeoutDecision` as its own record. Note: at runtime, CEG's clock is
   drawn by the clock object inside `e1_drive`, not stored in the play. Filling `Clock` in the record is CEG work
   (backlog E10).
9. **Player roles: unfilled is not the same as none.** CEG emits role slots (`slot:passer`) because arm D is not in
   the runtime yet. The record should tell apart "no such player on this play", "a player exists but is not modelled"
   (a slot) and a named player. The recorder must not credit statistics to a slot. Add the roles the recorder will
   need: interceptor, sacker, kick and punt returner. Tackler should be optional, since CEG does not model it.
10. **Provenance: one shape for both.** `ceg-play-1` has `Provenance(generator, version, components, draw_ids)`. Add
    the source-row identity and hash as optional fields of that same class, so V2 and CEG records stay one type.
11. **Laterals and multiple recoveries** cannot be one recovery. They should be a named rejection, as the proposal
    says for unknown classes, until a sequence field is designed.

## What CEG keeps unchanged

The generator and its probabilities; the team terms (Phase 6, 8 and 9 hooks are internal to the generator); and the
field names and meanings that the Phase 9 tally reads: `event`, `yards_gained`, `yards_after_catch`, `possession.team`.

## What CEG will do once the record is agreed

Emit `ceg-play-2` from `ceg_generator`. Move the foul enforcement out of `PenaltyProvider` into the shared rules.
Drop the harness's own possession flip. Fill `Clock` from the CEG clock. All of this goes on the CEG branch behind the
existing `generates_events` path. No frozen model changes.
