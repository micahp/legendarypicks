# SLC-CEG Phase 5: full games with no historical rows at run time

Date: 2026-11-24. Code: `scripts/nfl_sequence/ceg_game.py` (build, run), with the drive-loop switches in
`e1_drive.py` (`generates_events`, the `penalty` event) and the Phase 3 harness provider and clock (`ceg_harness.py`).
Artifact (not in git): `/root/slc-ceg-data/artifacts/ceg-sel-2026w11.pkl`, 1,981,005 bytes.

## Result

**The exit gate passes: complete games run with every data source blocked.** The runner loads the artifact, then makes
pandas' file readers and `sqlite3.connect` raise, then plays. 20 of 20 games completed, every drive checked by
`e1_drive.check_drive`, no halt, no refusal.

## What runs

- **The artifact is parameters only.** Fitted count tables, k values and small published value lists (kickoff runoffs,
  penalty yards by type, first-down-by-penalty rates, onside and kicking-team-recovery spots, the touchback spot). An audit
  walks the whole artifact and refuses if any pandas object is inside. It is a pickle, not yet the plan's JSON artifact
  format (backlog E1).
- **Composition:** scrimmage BC-selective (Phase 2), the CEG clock with timeouts and out of bounds (Phase 3, arm C), and
  Phase 4 special teams by its selective rule: C for the onside choice, the try choice, both foul models and the penalty
  type; the regime-adapted kickoff result for 2026 through week 10 (touchback 0.191, start at the 65); B for punts and
  field goals.
- **Game loop:** coin toss; kickoffs (onside, recovery, result, kick-return touchdown); drives through
  `e1_drive.simulate`; tries; field goals (made, missed: the opponent at the spot of the kick or its 20; blocked: the
  opponent at the line, a prior); safeties and the free kick; punts with touchbacks and return touchdowns; pre-snap and
  live fouls enforced with the half-distance rule and first downs at each type's observed rate; halftime with timeouts
  reset to 3; overtime with 10 minutes, 2 timeouts each, and the possession rule by season (from 2025 both teams
  possess, measured from the data: an opening-drive touchdown ended 5 of 6 overtime games in 2024 and 0 of 9 in 2025 and
  2026); defensive and return touchdowns scored by the game loop.
- **Rules interface:** every play goes through the v2 reducer, the CEG clock, the quarter, halftime, regulation and
  overtime logic of the drive loop, and `check_drive`.

## First realism read (20 games, not an evaluation)

Points 36.7 per game (NFL about 45), about 67 plays per team-game including 5.2 enforced fouls, 295 yards, 3.7 punts,
2.15 sacks, 0.8 interceptions, 1 overtime game and 1 tie. Scoring is low. Phase 7 measures realism on a larger run
against 2025.

## Simplifications, stated

- Penalties: a live foul replaces the play (offense: back from the line, down replayed; defense: forward from the line,
  first down at the type's rate). Spot fouls, declined fouls and offsetting fouls are not modelled. A pre-snap foul takes
  no clock.
- Kickoff runoff, onside and kicking-team-recovery spots, blocked kick spots and the free kick start are published-value
  priors, not evaluated components.
- No player attribution: the role slots of the generated play are not filled (the existing `pre_event` chooser would do
  this; backlog E10).
- The reducer still has no defensive scrimmage touchdown; the game loop scores it from the generated play (backlog E4).
