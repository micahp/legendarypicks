import random

import pytest

import football_assertions
import game_state as gs
import slc_playcall as slc
from test_game_state import PERIOD_END_OVERTIME, StaticPool, kickoff_pool, ref
from test_slc_playcall import STATE, blank_artifact, cell
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
