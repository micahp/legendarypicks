"""Simulator tests against the committed 2010-2021 model: determinism, resume, observation, playbook seam."""
import copy
import json
import os

import pytest

from nfl_sequence.events import Event
from nfl_sequence.model import StatModel
from nfl_sequence.playbook import CALLS, PlaybookError, checked_weights
from nfl_sequence.rules import RulesError
from nfl_sequence.simulate import (
    MAX_EVENTS,
    Simulator,
    checkpoint,
    derive_seed,
    restore,
    script,
    validate_script,
)

MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


@pytest.fixture(scope="module")
def model():
    return StatModel.load(os.path.join(MODELS, "nfl-seq-v0.1-main.json"))


def make_sim(model, playbook=None, home="BUF", away="KC"):
    return Simulator(model, game_id="2030_01_%s_%s" % (away, home), home_team=home, away_team=away, season=2030, snapshot_hash="test-snapshot", playbook=playbook)


def test_derived_seeds_are_stable_and_distinct_per_trial():
    assert derive_seed("g", "s", "v", 1) == derive_seed("g", "s", "v", 1)
    assert derive_seed("g", "s", "v", 1) != derive_seed("g", "s", "v", 2)
    assert derive_seed("g", "s", "v", 1) != derive_seed("g", "t", "v", 1)


def test_same_seed_gives_the_same_play_log(model):
    sim = make_sim(model)
    first = script(sim.start(7).advance())
    second = script(sim.start(7).advance())
    assert first["plays"] == second["plays"]
    assert first["final_score"] == second["final_score"]


def test_different_seeds_give_different_games(model):
    sim = make_sim(model)
    scores = {(script(sim.start(seed).advance())["final_score"]["home"]) for seed in range(20)}
    assert len(scores) > 3


def test_every_trial_is_a_legal_final_game(model):
    sim = make_sim(model)
    for seed in range(60):
        doc = script(sim.start(seed).advance())
        assert doc["valid_full_game"], (seed, doc["validation_problems"])
        assert doc["result"] in ("home", "away", "tie")
        assert doc["plays"][0]["state_before"]["phase"] == "kickoff"


def test_checkpoint_round_trips_through_json_and_resumes_identically(model):
    sim = make_sim(model)
    uninterrupted = sim.start(99).advance()
    partial = sim.start(99)
    for _ in range(40):
        event, call = partial._draw_event()
        partial._apply(event, call, provenance="simulated")
    saved = json.loads(json.dumps(checkpoint(partial)))
    resumed = restore(sim, saved).advance()
    assert resumed.plays == uninterrupted.plays


def test_restore_refuses_a_checkpoint_from_different_inputs(model):
    sim = make_sim(model)
    saved = checkpoint(sim.start(5))
    other = make_sim(model, home="DEN")
    with pytest.raises(ValueError):
        restore(other, saved)


def legal_observation(run):
    """A legal event for whatever phase the run is in, marked as observed."""
    state = run.state
    if state.phase == "kickoff":
        return Event("kickoff", offense=state.kicking, elapsed=5, touchback=True, provenance="observed")
    if state.phase == "try":
        return Event("extra_point", offense=state.offense, made=True, elapsed=0, provenance="observed")
    return Event("run", offense=state.offense, yards=3, elapsed=20, provenance="observed")


def test_observing_an_event_does_not_change_the_earlier_prediction(model):
    sim = make_sim(model)
    prediction = sim.start(11)
    for _ in range(10):
        event, call = prediction._draw_event()
        prediction._apply(event, call, provenance="simulated")
    before = copy.deepcopy(prediction.plays)
    observed = prediction.observe(legal_observation(prediction))
    assert prediction.plays == before
    assert len(observed.plays) == len(before) + 1
    assert observed.plays[-1]["provenance"] == "observed"


def test_observed_events_must_be_marked_observed_and_legal(model):
    sim = make_sim(model)
    run = sim.start(3)
    with pytest.raises(ValueError):
        run.observe(Event("kickoff", offense=run.state.kicking, elapsed=5, touchback=True, provenance="simulated"))
    with pytest.raises(RulesError):
        run.observe(Event("punt", offense=run.state.kicking, yards=40, elapsed=5, provenance="observed"))  # kickoff is pending
    assert run.plays == []


def test_a_neutral_playbook_matches_running_with_none(model):
    from nfl_sequence.playbook import NeutralPlaybook

    plain = script(make_sim(model).start(21).advance())
    neutral = script(make_sim(model, playbook=NeutralPlaybook()).start(21).advance())
    assert plain["plays"] == neutral["plays"]


class NoPassPlaybook:
    name = "test-no-pass"
    version = "v1"

    def call_weights(self, state, team):
        return {"pass": 0.0}

    def participants(self, state, team, call):
        return {}


def test_playbook_weights_tilt_the_calls_without_touching_legality(model):
    sim = make_sim(model, playbook=NoPassPlaybook())
    doc = script(sim.start(31).advance())
    assert doc["summary"]["calls"].get("pass", 0) == 0
    assert doc["valid_full_game"]


def test_invalid_playbook_weights_are_refused():
    with pytest.raises(PlaybookError):
        checked_weights({"sprint": 1.0})
    with pytest.raises(PlaybookError):
        checked_weights({"run": -1.0})
    with pytest.raises(PlaybookError):
        checked_weights({call: 0.0 for call in CALLS})


def test_the_validator_catches_a_reconciliation_break(model):
    doc = script(make_sim(model).start(41).advance())
    tampered = copy.deepcopy(doc)
    tampered["plays"][3]["outcome"]["points_home"] += 3
    problems = validate_script(tampered)
    assert any("reconcile" in problem for problem in problems)
    header = copy.deepcopy(doc)
    header["final_score"]["home"] += 3
    assert any("final_score" in problem for problem in validate_script(header))


def test_the_validator_catches_a_broken_state_chain(model):
    doc = script(make_sim(model).start(42).advance())
    tampered = copy.deepcopy(doc)
    tampered["plays"][5]["state_before"]["yardline_100"] = 1
    assert any("previous state_after" in problem for problem in validate_script(tampered))


def test_a_run_that_cannot_finish_is_stopped_not_padded(model):
    sim = make_sim(model)
    run = sim.start(51)
    run.plays = [{"provenance": "simulated"}] * MAX_EVENTS
    from nfl_sequence.simulate import SimulationError

    with pytest.raises(SimulationError):
        run.advance()
