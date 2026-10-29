import random
import sys
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_state as gs  # noqa: E402
import pre_event as pe  # noqa: E402
import slc_playcall as slc  # noqa: E402
from test_slc_playcall import STATE, blank_artifact, cell  # noqa: E402


def roster(team, prefix):
    players = [
        {'player_id': 1, 'gsis_id': f'{prefix}QB1', 'player_name': f'{prefix} QB1', 'pos_abb': 'QB', 'pos_rank': 1},
        {'player_id': 2, 'gsis_id': f'{prefix}QB2', 'player_name': f'{prefix} QB2', 'pos_abb': 'QB', 'pos_rank': 2},
        {'player_id': 3, 'gsis_id': f'{prefix}RB1', 'player_name': f'{prefix} RB1', 'pos_abb': 'RB', 'pos_rank': 1},
        {'player_id': 4, 'gsis_id': f'{prefix}WR1', 'player_name': f'{prefix} WR1', 'pos_abb': 'WR', 'pos_rank': 1},
        {'player_id': 5, 'gsis_id': f'{prefix}WR2', 'player_name': f'{prefix} WR2', 'pos_abb': 'WR', 'pos_rank': 2},
        {'player_id': 6, 'gsis_id': f'{prefix}TE1', 'player_name': f'{prefix} TE1', 'pos_abb': 'TE', 'pos_rank': 1},
    ]
    return {'team': team, 'players': players, 'snapshot_at': '2026-10-28T13:58:02Z', 'source': 'test'}


SNAPSHOT = {
    'snapshot_sha256': 'a' * 64,
    'rosters': {'home': roster('AAA', 'A'), 'away': roster('BBB', 'B')},
    'model_reference': {'observed_reference': {
        'receiver_position_usage': {'shares': {'WR': 0.6, 'TE': 0.25, 'RB': 0.15}},
        'runner_position_usage': {'shares': {'RB': 0.9, 'QB': 0.1}},
    }},
}


class Choice(unittest.TestCase):
    def test_a_dropback_names_the_starting_qb_and_a_target_before_any_outcome(self):
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=7, index=0)
        self.assertEqual(chosen['passer']['gsis_id'], 'AQB1')
        self.assertIn(chosen['receiver']['pos_abb'], {'WR', 'TE', 'RB'})
        self.assertEqual((chosen['side'], chosen['team']), ('home', 'AAA'))

    def test_the_same_inputs_give_the_same_players(self):
        first = pe.choose(SNAPSHOT, 'away', 'dropback', seed=7, index=3)
        again = pe.choose(SNAPSHOT, 'away', 'dropback', seed=7, index=3)
        self.assertEqual(first, again)

    def test_a_run_names_a_rusher_and_a_kick_names_nobody(self):
        self.assertIn('rusher', pe.choose(SNAPSHOT, 'home', 'run', seed=7, index=0))
        self.assertIsNone(pe.choose(SNAPSHOT, 'home', 'kick', seed=7, index=0))

    def test_a_missing_starting_qb_fails_closed(self):
        broken = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {**SNAPSHOT['rosters']['home'], 'players': [
            p for p in SNAPSHOT['rosters']['home']['players'] if p['gsis_id'] != 'AQB1']}}}
        with self.assertRaises(ValueError):
            pe.choose(broken, 'home', 'dropback', seed=7, index=0)


class DrawOrder(unittest.TestCase):
    def test_the_participants_are_chosen_after_the_intent_and_before_the_outcome(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        calls = []
        chooser = pe.chooser(SNAPSHOT, seed=7)

        def recording(intent, offense, state=None):
            calls.append('participants')
            return chooser(intent, offense, state)
        sampler.participant_chooser = recording

        class Recording(random.Random):
            def random(self):
                if not calls:
                    calls.append('intent')
                return super().random()

            def choices(self, population, weights=None, **kw):
                calls.append('outcome_type')
                return super().choices(population, weights=weights, **kw)

            def choice(self, seq):
                calls.append('outcome_row')
                return super().choice(seq)

        pool = cell([('run', 'run'), ('pass_complete', 'pass')])
        event, row, runoff, spot = sampler.sample(Recording(3), pool, 'A', 'B', state=dict(STATE, quarter=4, clock=90,
                                                                                         score_diff=-7))
        self.assertEqual(calls, ['intent', 'participants', 'outcome_type', 'outcome_row'])
        self.assertIsNotNone(row['pre_event'])
        self.assertEqual(sampler.decisions[-1]['participants'], pe.ids(row['pre_event']))


class FakeReference(gs.Reference):
    def __init__(self, participants, sampler):
        self.participants = participants
        self.contextual_sampler = sampler


class ParticipantsOfThePlay(unittest.TestCase):
    """The engine reads the pre-event choice. It never re-chooses after the outcome."""
    def _game(self, pre):
        facts = {'play_type': 'pass', 'posteam': 'AAA'}
        ref = FakeReference({('g', 1): facts}, types.SimpleNamespace(participant_chooser=lambda *a: None))
        play = {'event_type': 'pass_complete', 'sequence': 9,
                'outcome': {'sampled_from': {'game_id': 'g', 'play_id': 1}, 'pre_event': pre}}
        return ref, play

    def test_a_completion_uses_the_chosen_passer_and_target(self):
        pre = pe.choose(SNAPSHOT, 'home', 'dropback', seed=7, index=0)
        ref, play = self._game(pre)
        out = ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)
        self.assertEqual(out['passer_id'], pre['passer']['gsis_id'])
        self.assertEqual(out['receiver_id'], pre['receiver']['gsis_id'])
        self.assertEqual(out['attribution'], 'pre_event_selection')

    def test_a_sack_has_a_passer_and_no_target(self):
        pre = pe.choose(SNAPSHOT, 'home', 'dropback', seed=7, index=0)
        ref, play = self._game(pre)
        play['event_type'] = 'sack'
        out = ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)
        self.assertEqual(out['passer_id'], pre['passer']['gsis_id'])
        self.assertIsNone(out['receiver_id'])

    def test_a_pre_event_choice_without_the_needed_role_fails_closed(self):
        ref, play = self._game({'side': 'home', 'team': 'AAA', 'rusher': SNAPSHOT['rosters']['home']['players'][2]})
        with self.assertRaises(ValueError):
            ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)

    def test_a_kick_names_no_participant_on_a_chooser_game(self):
        ref, play = self._game(None)
        play['event_type'] = 'punt'
        out = ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)
        self.assertEqual(out['attribution'], 'no_participant_modelled')
        self.assertIsNone(out['passer_id'])

    def test_a_missing_choice_on_a_chooser_game_fails_closed(self):
        ref, play = self._game(None)
        with self.assertRaises(ValueError):
            ref.participants_for(play, offense_team='A', snapshot=SNAPSHOT, seed=7)


if __name__ == '__main__':
    unittest.main()
