# SLC v2 lineup participation: acceptance criteria

Status: written before implementation, 2026-11-02. Branch `pbv1-integration-2026-11-02`. The control arm is the existing
simulator, unchanged. The new mechanism sits behind the flag `lineup_participation` and is off by default.

## Scope

Play calling is formal, not run/dropback. The offense calls a formal play: formation, personnel package, play type and concept
(`formal_playcall.py`). The defense calls a formal defensive call: personnel, coverage, man or zone and pass rushers. The
lineup layer puts the called personnel on the field and assigns the carrier and targets from those on-field players.

Built so far (this increment): `formal_playcall.py` with its tests (`test_formal_playcall.py`, 19 passing). It reproduces the
published DET 2025 playbook's formation counts and five-lineman personnel counts exactly, and it keeps the 82 plays the playbook
leaves out (81 six-lineman plays and one fake punt).

To build: the lineup layer as a standalone module (`lineup_participation.py`): complete 11-player offensive lineups with
continuity, eligible-player selection, carrier and target choice from the on-field players, scramble tracking, and a workload
ledger. Also the situation table for formal plays and the defensive call table.

Out, to be done at integration: wiring into `pre_event.chooser` and `game_state`, the run report, historical validation at snap,
drive, game, team and player levels, the 2026 evaluation, and any 10K run. Each is named in the last section.

## Acceptance criteria

AC1. A lineup has exactly 11 offensive players. Each has a group: QB, RB, FB, TE, WR or OL. There is one QB on the field unless the
play is an explicit QB-as-receiver or Wildcat case, which the classifier marks.

AC2. A package is valid when it has 11 players, at least one QB and between 5 and 7 OL. A 6-OL or 7-OL formation is valid. It is
never excluded for convenience. Every 2025 unusual snap is classified in `SLC-V2-LINEUP-INVESTIGATION-2026-11-02.md`.

AC3. Continuity: when the requested package equals the current lineup's counts and no voluntary leave occurs, the lineup does not
change. No player enters and none leaves.

AC4. Minimal substitution: moving from one package to another changes only the players the new counts require. Incumbents that
still fit the new counts stay on the field. Surplus players leave; deficit slots are filled.

AC5. Eligibility: an entrant comes only from the eligible roster (the snapshot's active players). A missing group with no eligible
player raises `ShortRoster`. Nothing is filled silently.

AC6. A carrier or target is chosen only from players on the field. A backup QB who is not on the field never carries or throws.

AC7. A scramble (QB rush on a pass intent) is counted separately from a designed QB run.

AC8. Determinism: the same inputs and seed give the same lineups, entrants, leavers and selections.

AC9. Snap share per player equals his simulated snaps divided by the team's simulated offensive snaps. The team snap total is the
number of plays the lineup was built for.

AC10. Formal play calling: the offense's formal play (formation, personnel, play type, concept) is drawn from a table keyed by the
team and the situation (down, distance, field). The table is fitted only from seasons before the evaluation season. A cell with
too little support falls back to the league table for the same situation, and the fallback is recorded. The published playbook
classes must be reproduced before a fitted table is used (`test_formal_playcall.py`).

AC11. Formal defensive calls: the defense's call (personnel, coverage, man or zone, pass rushers) is drawn from the same kind of
table, keyed by the offense's formal play, and its fallbacks are recorded in the same way.

AC12. A six-lineman or special-teams-personnel play is kept as its own class, never dropped or relabelled as invalid for
convenience. Invalid means a defensive label in the offense or a personnel total other than eleven, and it keeps its reason.

AC13 (integration, not this increment). With the flag off the engine output is byte-identical to the control. With it on, the
same seed replays identically.

## Tests

`scripts/nfl_sequence/test_lineup_participation.py`: single-snap tests for AC1, AC2, AC5, AC6 and AC7; drive tests for AC3, AC4,
AC8 and AC9; a table test for AC10.
