import random
from types import SimpleNamespace

import pytest

import football_assertions
import e1_drive
import game_state as gs
import pre_event
import slc_playcall as slc
from test_game_state import PERIOD_END_OVERTIME, StaticPool, kickoff_pool, ref
from test_slc_playcall import STATE, blank_artifact, cell
from test_formation_layer import personnel_first_table
from test_pre_event import SNAPSHOT
from v1_complete_order import STAGES, assert_no_historical_execution, assert_play_order
from v1_complete_roster import participant_validator


def test_order_assertion_requires_all_stages_in_order():
    assert_play_order(STAGES)
    for stages in (STAGES[:-1], ('call',) + STAGES, STAGES[:2] + ('snap',) + STAGES[3:]):
        with pytest.raises(football_assertions.FootballAssertionError, match='v1_complete_play_order'):
            assert_play_order(stages)


def test_playcall_trace_exposes_existing_call_before_personnel():
    sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(-30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
    events = []
    sampler.execution_observer = lambda event, context: events.append(event)
    sampler.participant_chooser = lambda *args: None
    sampler.sample(random.Random(2), cell([('run', 'run')]), 'A', 'B', state=STATE)
    assert events == ['call_selection', 'participant_chooser']
    with pytest.raises(football_assertions.FootballAssertionError, match='v1_complete_play_order'):
        assert_play_order(('call', 'personnel'))


def test_personnel_and_formation_are_selected_before_scrimmage_call():
    sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(-30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
    sampler.personnel_first = True
    sampler.participant_chooser = pre_event.chooser(SNAPSHOT, 7, formation_priors=personnel_first_table())
    events = []
    sampler.execution_observer = lambda event, context: events.append(event)
    sampler.sample(random.Random(2), cell([('run', 'run')]), 'A', 'B', state=STATE)
    assert events == ['personnel_formation', 'call_selection', 'participant_chooser']
    assert sampler.decisions[-1]['personnel'] in ('11', '12')
    assert sampler.decisions[-1]['formation'] in ('SHOTGUN', 'UNDER CENTER')


def test_full_game_wires_drive_trace_in_execution_order():
    reference = ref(StaticPool('run', 0, 20), kickoff_pool(), overtime_pool=[PERIOD_END_OVERTIME])
    events = []
    reference.execution_observer = lambda event, context: events.append((event, context))
    game = gs.play_game(9, reference, winner_choice='receive')
    assert game['status'] == 'complete_overtime'
    names = [event for event, _ in events]
    assert names[0] == 'historical_kickoff_selected'
    start = names.index('play_start')
    assert names[start:start + 5] == ['play_start', 'historical_outcome_selected', 'apply_play',
                                      'apply_clock', 'play_recorded']
    assert names.count('play_start') == names.count('play_recorded')
    assert 'historical_overtime_drive_selected' in names
    for index, name in enumerate(names):
        if name == 'play_start':
            assert names[index:index + 5] == ['play_start', 'historical_outcome_selected', 'apply_play',
                                               'apply_clock', 'play_recorded']


def test_complete_guard_stops_legacy_full_game_at_kickoff():
    reference = ref(StaticPool('run', 0, 20), kickoff_pool())
    reference.execution_observer = assert_no_historical_execution
    with pytest.raises(football_assertions.FootballAssertionError, match='v1_complete_historical_execution'):
        gs.play_game(9, reference, winner_choice='receive', max_drives=1)


def test_chooser_rejects_an_ineligible_player_before_sampling_outcome():
    team = {'schema': 'lp-nfl-resolved-roster-2', 'blocks': [], 'roles': [], 'players': [
        {'gsis_id': 'allowed', 'official_eligible': True, 'membership': 'ACTIVE_ROSTER', 'exclusion_reason': None}]}
    sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(-30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
    sampler.participant_validator = participant_validator({'home': team, 'away': team})
    sampler.participant_chooser = lambda *args: {'rusher': {'gsis_id': 'not-eligible'}}
    with pytest.raises(ValueError, match='v1_complete_roster_ineligible_participant:not-eligible'):
        sampler.sample(random.Random(2), cell([('run', 'run')]), 'A', 'B', state=STATE)
    assert sampler.decisions == []


def test_live_qb_runs_after_snap_and_cannot_fall_back_to_a_historical_outcome():
    sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
    sampler.participant_chooser = lambda *args: {'passer': {'gsis_id': 'qb'}}
    observation = {'seconds': 0, 'qb': {'player_id': 'qb', 'x': 0, 'y': 0},
                   'defenders': [], 'receivers': []}
    sampler.live_qb_model = SimpleNamespace(observations=lambda *_: [observation],
                                            policy=lambda _: {'action': 'throwaway'})
    sampler.live_qb_allowed = {'A': {'qb'}, 'B': set()}
    events = []
    sampler.execution_observer = lambda event, context: events.append(event)
    with pytest.raises(e1_drive.SamplingUnavailable, match='live_qb_outcome_transition_unavailable:throwaway'):
        sampler.sample(random.Random(2), cell([('pass_incomplete', 'pass')]), 'A', 'B', state=STATE)
    assert events == ['call_selection', 'participant_chooser', 'snap', 'live_qb_decision']
    assert sampler.decisions == []


def test_live_dropback_chooser_does_not_select_target_before_snap():
    chooser = pre_event.chooser(SNAPSHOT, 7, live_dropback=True)
    chosen = chooser('dropback', 'A', STATE)
    assert chosen['passer']['pos_abb'] == 'QB'
    assert 'receiver' not in chosen
    assert 'target_role' not in chosen
    assert 'labels' not in chosen
    assert 'qb_decision' not in chosen
