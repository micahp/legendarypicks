# NFL sequence engine v0.1: integration contract

Status: implemented, research only. Module: `backend/nfl_sequence/`. Version `nfl-seq-v0.1`, rules
`nfl-2026-regular-season-approx-v0.1`. Scope and event vocabulary follow
[GRIDIRON-CONTRACT-v1.md](GRIDIRON-CONTRACT-v1.md) (which stays byte-identical in both repositories and is not
edited here). Pipeline design: [SPEC-nfl-pregame-play-sequence-generator-v1.md](SPEC-nfl-pregame-play-sequence-generator-v1.md).
Measured results: [RESULTS-nfl-sequence-v0.1-2026-10-22.md](RESULTS-nfl-sequence-v0.1-2026-10-22.md).

This engine **predicts**. It consumes no actual game result, roster, tackler or end spot. Its
statistical baseline is learned from published nflverse play-by-play for 2010 to 2021. It is never a
recording of what happened, and every script it writes says so.

## Who owns what

| Part | Owner | Where |
| --- | --- | --- |
| Game state, event vocabulary, legal transitions, clock, periods, overtime | this engine | `state.py`, `events.py`, `rules.py` |
| Play-call and outcome distributions | this engine (trained, `nfl-seq-v0.1-*.json`) | `model.py`, `nflverse.py`, `train.py` |
| Team tilt on play calls | **playbook agent** | implements `Playbook` in its own module |
| Seeds, runs, checkpoints, observation, script output, validation | this engine | `simulate.py` |
| Interface and rendering | interface agent | consumes script JSON; never edits engine state |
| Historical reconstruction (one-step replay of recorded plays) | this engine, labelled as reconstruction | `reconstruct.py` |

## 1. Playbook interface (for the playbook agent)

A playbook is any object with these members. The engine only ever calls them through the seam in
`playbook.py`, so a team configuration can be swapped without touching the reducer or the model.

```python
class Playbook(Protocol):
    name: str      # stable id, e.g. "patriots-2026-v1"; it is written into every script
    version: str   # your config version; also written into every script

    def call_weights(self, state: Mapping[str, object], team: str) -> Mapping[str, float]: ...
    def participants(self, state: Mapping[str, object], team: str, call: str) -> Mapping[str, Optional[str]]: ...
```

- `state` is the **public state** (section 3), not an engine object. Do not rely on any other field.
- `team` is the offense's team code (for example `"NE"`), for the side that has the ball in a scrimmage state.
- `call_weights` returns non-negative multipliers over `CALLS = ("run", "pass", "punt", "field_goal", "kneel", "spike")`.
  - Missing keys mean `1.0`. Unknown keys raise `PlaybookError`. Non-finite or negative values raise.
  - All weights zero raises. The engine **never** clips or silently repairs your output.
  - Weights multiply the league-average baseline for that situation and renormalise. They do **not** set
    probabilities directly and do not change outcomes, yardage, clock, scores or legality.
- `participants` returns roster ids, or `{}` when you have no roster. In v0.1 the engine does not yet
  consume participants; they are recorded as `null`. Never guess a name; use a reviewed id or return `{}`.
- Calls are deterministic per seed. A playbook must be a pure function of its inputs. No clocks, no I/O in the hot path.

Neutral reference: `NeutralPlaybook` (name `neutral-mock`, version `v0`) returns no tilt. A run with it is
identical to a run with no playbook. The test `test_a_neutral_playbook_matches_running_with_none` holds that.

Extension not yet built, and why: a team's **ratings** (strength priors) are not consumed. A rating that
moves yardage or completion would be an outcome tilt, which needs its own validation against held-out
games before it is allowed in. Proposed for v0.2, not implemented.

## 2. Input: how a run starts

```python
from nfl_sequence.model import StatModel
from nfl_sequence.simulate import Simulator, derive_seed, script, validate_script

model = StatModel.load("backend/nfl_sequence/models/nfl-seq-v0.1-main.json")
sim = Simulator(
    model,
    game_id="2026_07_DEN_SEA",       # stable scheduled-game key, nflverse style
    home_team="DEN", away_team="SEA",
    season=2026,
    snapshot_hash=pregame_snapshot_hash,  # caller-supplied hash of the frozen pregame inputs
    playbook=my_playbook,              # optional; default is NeutralPlaybook
)
run = sim.start(derive_seed(sim.game_key, pregame_snapshot_hash, "nfl-seq-v0.1", trial_index)).advance()
doc = script(run)                      # the complete play script, validated
assert doc["valid_full_game"], doc["validation_problems"]
```

- `snapshot_hash` must be computed only from pregame inputs. It must not depend on any result.
  The evaluation uses a hash of `(game_id, season, home, away, model version)`.
- Seeds come from `derive_seed(game_key, snapshot_hash, model_version, trial)`. The same inputs give the
  same script, byte for byte. Different trials give different plausible games.
- The opening kickoff and the overtime coin toss are drawn from the same seeded stream.

## 3. Public state (what the playbook and the interface see)

Every play record carries `state_before` and `state_after` with this shape:

| Field | Meaning |
| --- | --- |
| `quarter` | 1 to 4, or 5 for overtime |
| `clock_seconds` | seconds remaining in **this period** |
| `phase` | `kickoff`, `scrimmage`, `try` or `final` |
| `offense_team`, `defense_team` | team codes with the ball (null on kickoffs) |
| `kicking_team` | team kicking off (set on kickoffs only) |
| `home_score`, `away_score` | cumulative points before or after the play |
| `down`, `yards_to_go` | null outside scrimmage |
| `yardline_100` | **offense-relative**: yards from the offense's spot to the opponent's goal (1 to 99) |
| `home_timeouts`, `away_timeouts` | always 3 in v0.1; timeouts are not modelled (see section 7) |
| `drive_index` | increments on every new possession, including kickoffs |
| `result` | `home`, `away` or `tie` once final |

Use `yardline_100`, never an absolute field position. The conversion to a physical x coordinate is the
renderer's job (see the contract's "Physics conversion" section).

## 4. Output: the play script

`script(run)` returns one JSON document:

```json
{
  "schema_version": "1.0",
  "mode": "pregame_full_game",
  "simulation_id": "nfl-seq-main-<seed>-<digest12>",
  "game_id": "...", "model_version": "nfl-seq-v0.1", "model_variant": "main",
  "rules_version": "nfl-2026-regular-season-approx-v0.1",
  "seed": 123, "snapshot_hash": "...",
  "teams": {"home": "...", "away": "..."},
  "playbook": {"name": "...", "version": "..."},
  "provenance": {
    "outcomes": "sampled_statistical_baseline",
    "participants": "not_modeled",
    "motion": "not_produced",
    "observed_events": 0,
    "label": "HYPOTHETICAL MODEL SIMULATION"
  },
  "unsupported_mechanics": ["penalties", "two_point_tries", "...": "..."],
  "result": "home", "final_score": {"home": 24, "away": 20},
  "plays": [ { "sequence": 1, "id": "<simulation_id>:1", "event_type": "kickoff",
               "provenance": "simulated",
               "state_before": { }, "decision": {"call": null, "playbook": "...", "playbook_version": "..."},
               "outcome": {"yards": 0, "elapsed": 5, "made": null, "touchback": true, "return_yards": 0,
                           "fumble_lost": false, "points_home": 0, "points_away": 0, "drive_ended": true},
               "derived": [], "state_after": { } } ],
  "summary": {"plays": 0, "calls": {}, "points": {}, "drives": 0, "punts": 0, "...": 0},
  "validation_problems": [],
  "valid_full_game": true
}
```

- `event_type` is one of the input kinds in section 5. `derived` lists the kinds the reducer emitted for that
  play (`period_end`, `safety`, `game_end`).
- `decision.call` is set only for simulated plays. Observed plays have `null`.
- `provenance` on each play is `simulated` or `observed`. The top-level `provenance.label` is always
  `HYPOTHETICAL MODEL SIMULATION`. Do not present a script as observed NFL play-by-play.
- `valid_full_game` is true only when the game reached `final` **and** `validate_script` returns no problems.
  Never render a score from a script where it is false.

`validate_script(doc)` checks: the sequence is contiguous; each `state_before` equals the previous `state_after`;
game time never moves backwards; scores never decrease; the last state is final and matches `final_score` and
`result`; and play points sum to the final score.

## 5. Event vocabulary

Supported inputs (the reducer accepts these and nothing else):

| Kind | Phase it needs | Fields used |
| --- | --- | --- |
| `kickoff` | kickoff | `touchback`, `return_yards` (signed; relative to the receiving team's 25) |
| `run`, `pass_complete`, `pass_incomplete`, `interception`, `sack`, `qb_scramble`, `kneel`, `spike` | scrimmage | `yards`, `fumble_lost`, `return_yards` (interception) |
| `punt` | scrimmage | `yards` (gross), `return_yards` |
| `field_goal` | scrimmage | `made` |
| `extra_point` | try | `made` |

Refused, with `UnsupportedMechanic`: `penalty`, `two_point_try`, `fumble` (as a standalone event). A lost fumble
is a flag on the play that caused it. Derived only, never accepted as input: `period_end`, `game_end`, `safety`.
An event from the wrong side, in the wrong phase, or in a final game raises `RulesError` and leaves the state unchanged.

## 6. Live-data adapter: initialise and update without corrupting predictions

A real event can be attached to a run as an observation. The rules are:

- `run.observe(event)` requires `event.provenance == "observed"`. It returns a **new** run. The original run and every
  play in it are unchanged. The test `test_observing_an_event_does_not_change_the_earlier_prediction` pins this.
- An observed event is validated by the same reducer as a simulated one. An event the state cannot take raises and
  nothing is recorded, so a bad feed cannot silently alter a state.
- A run can be checkpointed at any point: `checkpoint(run)` returns JSON (state, plays, RNG state). `restore(sim, data)`
  rebuilds it for the same simulator inputs and continues identically. Restoring for different inputs is refused.
- Observed plays carry `provenance: "observed"`, and `top-level provenance.observed_events` counts them. The rest of the
  game after an observation is still labelled as a simulation.

What the adapter must **not** do: write observed outcomes into a checkpoint that is then presented as the pregame
prediction, or start a simulation from a post-kickoff state while labelling it pregame. The engine cannot detect that
misuse; the caller must label it.

## 7. Unsupported mechanics (reported, not hidden)

The engine does not model these. Each is listed in every script's `unsupported_mechanics` and measured in the results.

- **Penalties.** Never generated. Penalty rows are 6.49% of the 94,556 regular-season rows in 2022 to 2023 (8.02% of the 76,470 run, pass and no-play rows). They are excluded from training. Source: `denominators` in [RESULTS](RESULTS-nfl-sequence-v0.1-2026-10-22.md).
- **Two-point tries.** Every try is an extra point. 9.45% of conversion attempts (246 of 2,602 in 2022 to 2023; the other 2,356 are extra points). Source: [RESULTS](RESULTS-nfl-sequence-v0.1-2026-10-22.md).
- **Timeouts and challenges.** Never called. The public state reports 3 for each side. The clock is set only by the
  empirical run-off per play type.
- **Participants and rosters.** `participants` is `null`. No passer, receiver or rusher is named.
- **Interception and fumble return yards.** Sampled as zero (the event carries `return_yards`, but the engine does not yet sample it).
  A pick-six or fumble-return touchdown therefore never happens. This is the largest measured reducer gap.
- **Kickoff return spot.** Sampled from the observed receiving spot (an implied return from the 25). nflverse's own
  `return_yards` on kickoffs does not measure from the 25 consistently, so the historical reconstruction keeps that
  convention and reports the gap.
- **Regular-season overtime.** Approximated: 10 minutes; each team one possession; a first-possession touchdown ends the game; a tie is final.
- **Clock.** Runoff comes from the empirical gap between consecutive plays within a period. The two-minute warning and late-half
  clock management are not modelled beyond the quarter bin.
- **Missed field-goal spot and blocked kicks.** A miss gives the ball at the line of scrimmage; blocks are not generated.
- **Team strength.** The engine is team-agnostic apart from the playbook's call weights. Game-level scoring therefore reflects league
  scoring, not a team's quality. Measured on the held-out seasons, winner accuracy is 0.494 (95% CI 0.453 to 0.532) against a coin flip of 0.5 and an always-home rate of 0.558; the main variant's Brier score is worse than the base-rate forecast. This is the honest limit of v0.1. See [RESULTS](RESULTS-nfl-sequence-v0.1-2026-10-22.md).

## 8. Model artifacts

`backend/nfl_sequence/models/`: `nfl-seq-v0.1-main.json` (decisions condition on down, distance, field, score and quarter),
`nfl-seq-v0.1-state_transition.json` (decisions condition on down, distance and field only), and
`nfl-seq-v0.1-frequency.json` (decisions ignore the situation). `manifest.json` records the training seasons (2010 to 2021),
the SHA-256 of each source parquet, row counts, and every skip reason. Physical tables (field goals, punts, kickoffs, clock)
are identical across variants. Training never reads the held-out seasons.

Rebuild from the nflverse archive (needs pyarrow; run from `backend/` with `--train-seasons 2010-2021`):

```
python -m nfl_sequence.train --source-dir <dir with play_by_play_YYYY.parquet> --train-seasons 2010-2021 --out-dir nfl_sequence/models
```

## 9. Rendering obligations (for the interface agent)

- Label every script **HYPOTHETICAL MODEL SIMULATION**, with the model version, variant, seed and playbook name.
- Render a final score only when `valid_full_game` is true. Otherwise show the gap, not a made-up total.
- Show the `unsupported_mechanics` list, or a link to it, next to any play view. Do not present timeouts,
  penalties or player names as if they were modelled.
- Do not depict a return touchdown or a pick-six as simulated; the engine does not produce them in v0.1.
- Historical reconstruction (replaying recorded plays) must be a separate surface with its own label.

## 10. Reproducing

```
cd backend
/root/legendarypicks/backend/venv/bin/python -m pytest nfl_sequence -q
/root/legendarypicks/backend/venv/bin/python -m nfl_sequence.evaluate --source-dir <parquet dir> \
    --model-dir nfl_sequence/models --test-seasons 2022-2023 --trials 100 \
    --schedule-db <sqlite with nfl_schedule> --out <json>
```

Tests use only the committed models and hand-built rows; they need no parquet and no network.
