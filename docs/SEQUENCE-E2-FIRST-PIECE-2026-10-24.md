# NFL sequence generator, LP E2 first piece: kickoffs, linkage and the game ledger (2026-10-24)

Branch `feat/nfl-sequence-e2-kickoffs-2026-10-24`, stacked on the E1 head `e621e83e`. Modules:
`scripts/nfl_sequence/game_state.py` (state machine), `scripts/nfl_sequence/test_game_state.py` (12 tests),
`scripts/nfl_sequence/game_survey.py` (300-game survey). The E1 generator and fixtures are unchanged.

**Status: first piece, not a legal game.** The state machine links E1 drives into one game under the normal-game policy,
and it validates every game it produces. No game is valid. Field-goal results and try results are not published, so a
game stops at the first field-goal attempt, and every touchdown leaves its try pending. Nothing is invented to fill
either gap.

## Decision D: the E1 ID scheme stays, as a labelled research profile

E1 keeps `drive_statistical_demo` and its play IDs `e1-seed<seed>:<sequence>`. It is a separate research profile, and
the shared full-game contract (`GRIDIRON-CONTRACT-v1`) is not changed. E2 game records use their own mode,
`legal_game_state_first_piece`, and they do not claim the shared play-ID rule either.

## Normal-game policy (rules file, sections 3 and 7)

- The first-choice captain receives. A `kick` or `defend_goal` choice is refused in normal mode.
- Each team kicks off once per half. The defer path gives the loser the first-half choice and the winner the second-half
  choice. The receive path gives the reverse.
- `validate_half_start` fails closed: exactly two half-start kickoffs, one per team, and the Q3 receiver kicked the Q1
  kickoff. A game blocked before halftime has only the Q1 kickoff, so the two-kickoff check applies only once Q3 starts.
- The exception coin-toss paths (`explicit_exception_scenario`) are not implemented. Asking for them raises an error.

## Linkage rules

| E1 terminal | Next restart in this piece |
| --- | --- |
| `punt`, `turnover`, `turnover_on_downs` | The receiving offense continues from its published spot. No kickoff. |
| `touchdown` | Points: 6, with the try pending. The scoring team kicks off to the other team (`post_score`). |
| `safety` | Points: 2 for the defense. The conceding team kicks the free kick (`safety_free_kick`). |
| `halftime` | Q3 kickoff from the ledger (`half_start`). The clock resets to 15:00. |
| `end_of_regulation` | Game complete. A tie is not valid, because overtime is not modelled. |
| `field_goal_attempt` | Game blocked: `field_goal_result_unpublished`. |

Each restart samples a kickoff from the pool: the receiving team's first run or pass in the same quarter gives the spot,
and the kickoff's clock runoff comes from the published interval. If the restart would cross the quarter end, the game
blocks with `restart_crosses_quarter_end`.

**Kickoff convention in the published data.** On a kickoff row `posteam` is the receiving team, and `defteam` is the
kicking team. This is the reverse of the punt convention, and the pool is built on it. A clean receiving snap was found
for 10,037 kickoffs, and 962 were excluded.

## Orientation

Authored, not sourced, and labelled in every record. The goal-first-half team defends x=0 in Q1. Ends change after Q1
and after Q3, and halftime does not flip ends. The Q3 orientation uses the second-half goal choice.

## Survey (300 seeded games, `scripts/nfl_sequence/game_survey.py --games 300`)

```
games=300 validated=300 valid_full_game=0
status {'blocked': 298, 'complete_regulation': 2}
blocker {'field_goal_result_unpublished': 296, 'restart_crosses_quarter_end': 2, None: 2}
reached the Q3 half-start kickoff: 17 (5.7%)
games with a pending try: 131
drives per game: mean 4.3, max 25
kickoff pool: usable 10037, excluded {'kickoff without a clean receiving snap': 962}
```

Every game passed `validate_game`. The two games that reached regulation were not valid, because a try was pending or the
game was tied.

## Tests

- `python3 -m unittest scripts/nfl_sequence/test_game_state.py`: **12 of 12 pass**. They cover the ledger (refusals, both
  coin-toss paths, the second-half chooser), the half-start validator (same-team refusal, ledger agreement), the kickoff pool
  convention (receiving-team posteam, and exclusion of a kicker's next snap), the post-score kickoff by the scorer, a
  field-goal attempt stopping the game with no invented result, and halftime producing the Q3 kickoff.
- `python3 -m unittest scripts/nfl_sequence/test_e1_transitions.py` (inherited from E1): **10 of 10 pass**.

## Not done (say so plainly)

- **Field-goal results and try results.** These are the blockers. The dev database has no result columns for either
  (checked). Until one of them is sourced or a labelled policy is chosen, no game can be valid.
- **Onside kicks.** Not implemented, and not generated. They are listed as unsupported in every record.
- **Overtime, penalties, timeouts, two-minute warning, exception coin-toss paths.** Not modelled.
- **Player statistics.** Null. No participants are supplied, and none are sampled.
- **Clock realism.** Kickoff time and drive time are the sampled intervals (boundary 2 from E1).
- **Restarts that cross a quarter end.** These block the game. They are not resolved.

## Decision needed

A full legal game needs a policy for field-goal and try results. The options are:

1. Keep the blocker. E2 stays incomplete until a sourced kick-result table exists.
2. A labelled statistical sample for field goals and tries, drawn from an external published kick rate that someone sources
   and records. The record would say `source: external_rate`, and it would still not be a fact about any real game.
3. A labelled authored default. This is allowed only for a clearly hypothetical game, and every record must say so.

Option 2 needs a sourced table, which is not in the dev database. Option 3 is the fastest, but it is authored.
