import random
import sys
import types
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import game_state as gs  # noqa: E402
import pre_event as pe  # noqa: E402
import decision_layer  # noqa: E402
import qb_decisions as qbd  # noqa: E402
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

    def test_a_backup_qb_cannot_receive_without_an_entry_mechanism(self):
        ordinary = pe.choose(SNAPSHOT, 'home', 'dropback', seed=7, index=0,
                             trick_passer_rate=0, qb_receiver_rate=1)
        self.assertEqual(ordinary['passer']['gsis_id'], 'AQB1')
        self.assertNotEqual(ordinary['receiver']['gsis_id'], 'AQB2')

        packaged = pe.choose(SNAPSHOT, 'home', 'dropback', seed=7, index=0,
                             trick_passer_rate=0, qb_receiver_rate=1, qb_receiver_package=True)
        self.assertEqual(packaged['passer']['gsis_id'], 'AQB1')
        self.assertEqual(packaged['receiver']['gsis_id'], 'AQB2')

        trick = pe.choose(SNAPSHOT, 'home', 'dropback', seed=7, index=0,
                          trick_passer_rate=1, qb_receiver_rate=1)
        self.assertNotEqual(trick['passer']['pos_abb'], 'QB')
        self.assertEqual(trick['receiver']['gsis_id'], 'AQB1')

    def test_a_rostered_backup_qb_cannot_take_a_designed_run_without_becoming_qb1(self):
        shares = {'receive': {}, 'carry': {('AAA', 'AQB2'): 100.0}}
        for seed in range(100):
            chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=seed, index=0, player_shares=shares)
            self.assertNotEqual(chosen['rusher']['gsis_id'], 'AQB2')

        replaced = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {
            **SNAPSHOT['rosters']['home'],
            'injury_report': {'players': [{'gsis_id': 'AQB1', 'report_status': 'Out'}]}}}}
        promoted = pe.choose(replaced, 'home', 'run', seed=7, index=0, player_shares=shares)
        self.assertEqual(promoted['rusher']['gsis_id'], 'AQB2')

    def test_dirichlet_carry_share_cannot_select_a_backup_qb_while_qb1_is_active(self):
        share_table = {
            'phi': {'receive': 24.0, 'carry': 8.0},
            'base': {'receive': {}, 'carry': {('AAA', 'AQB2'): 1.0}},
        }
        for seed in range(100):
            chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=seed, index=0, share_table=share_table)
            self.assertNotEqual(chosen['rusher']['gsis_id'], 'AQB2')

        replaced = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {
            **SNAPSHOT['rosters']['home'],
            'injury_report': {'players': [{'gsis_id': 'AQB1', 'report_status': 'Out'}]}}}}
        promoted = pe.choose(replaced, 'home', 'run', seed=7, index=0, share_table=share_table)
        self.assertEqual(promoted['rusher']['gsis_id'], 'AQB2')

    def test_a_missing_starting_qb_fails_closed(self):
        broken = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {**SNAPSHOT['rosters']['home'], 'players': [
            p for p in SNAPSHOT['rosters']['home']['players'] if p['gsis_id'] != 'AQB1']}}}
        with self.assertRaises(ValueError):
            pe.choose(broken, 'home', 'dropback', seed=7, index=0)

    def test_qb_specific_target_role_is_drawn_before_the_outcome_and_honors_availability(self):
        cell = qbd.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        table = {
            'qb_cell': {('AAA', 'AQB1', cell): Counter({'pass': 100})},
            'team_cell': {('AAA', cell): Counter({'pass': 100})},
            'league_cell': {cell: Counter({'pass': 100})},
            'target_qb_cell': {('AAA', 'AQB1', cell): Counter({'WR': 100})},
            'target_team_cell': {('AAA', cell): Counter({'WR': 100})},
            'target_league_cell': {cell: Counter({'WR': 100})},
            'scramble_cells': set(), 'row_target_roles': {},
        }
        snapshot = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {
            **SNAPSHOT['rosters']['home'],
            'injury_report': {'players': [{'gsis_id': 'AWR1', 'report_status': 'Out'}]}}}}
        chosen = pe.choose(snapshot, 'home', 'dropback', 7, 0, state=STATE, qb_decision_table=table)
        self.assertEqual(chosen['qb_decision']['target_role'], 'WR')
        self.assertEqual(chosen['receiver']['gsis_id'], 'AWR2')
        self.assertEqual(chosen['labels']['A'], 'WR')

    def test_available_role_with_no_historical_probability_uses_and_records_fallback(self):
        cell = qbd.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        table = {
            'qb_cell': {('AAA', 'AQB1', cell): Counter({'pass': 100})},
            'team_cell': {('AAA', cell): Counter({'pass': 100})},
            'league_cell': {cell: Counter({'pass': 100})},
            'target_qb_cell': {('AAA', 'AQB1', cell): Counter({'Other': 100})},
            'target_team_cell': {('AAA', cell): Counter({'Other': 100})},
            'target_league_cell': {cell: Counter({'Other': 100})},
            'scramble_cells': set(), 'row_target_roles': {},
        }
        snapshot = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {
            **SNAPSHOT['rosters']['home'],
            'injury_report': {'players': [
                {'gsis_id': 'ARB1', 'report_status': 'Out'},
                {'gsis_id': 'AWR1', 'report_status': 'Out'},
                {'gsis_id': 'ATE1', 'report_status': 'Out'},
            ]}}}}

        chosen = pe.choose(snapshot, 'home', 'dropback', 7, 0, state=STATE, qb_decision_table=table)

        self.assertEqual(chosen['qb_decision']['target_role'], 'WR')
        self.assertEqual(chosen['qb_decision']['target_role_probabilities'], {'WR': 1.0})
        self.assertEqual(chosen['qb_decision']['target_role_fallback'], 'no_model_mass_for_available_roles')
        self.assertEqual(chosen['receiver']['gsis_id'], 'AWR2')

    def test_qb_scramble_is_a_pre_event_run_and_a_ruled_out_qb_is_skipped(self):
        cell = qbd.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        table = {
            'qb_cell': {('AAA', 'AQB1', cell): Counter({'scramble': 100})},
            'team_cell': {('AAA', cell): Counter({'scramble': 100})},
            'league_cell': {cell: Counter({'scramble': 100})},
            'target_qb_cell': {}, 'target_team_cell': {}, 'target_league_cell': {},
            'scramble_cells': {cell}, 'row_target_roles': {},
        }
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', 7, 0, state=STATE, qb_decision_table=table)
        self.assertEqual(chosen['passer']['gsis_id'], 'AQB1')
        self.assertEqual(chosen['rusher']['gsis_id'], 'AQB1')
        self.assertEqual(chosen['qb_decision']['action'], 'scramble')
        self.assertNotIn('receiver', chosen)

        snapshot = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {
            **SNAPSHOT['rosters']['home'],
            'injury_report': {'players': [{'gsis_id': 'AQB1', 'report_status': 'Out'}]}}}}
        chosen = pe.choose(snapshot, 'home', 'dropback', 7, 0, state=STATE, qb_decision_table=table)
        self.assertEqual(chosen['passer']['gsis_id'], 'AQB2')
        self.assertEqual(chosen['rusher']['gsis_id'], 'AQB2')
        self.assertEqual(chosen['qb_decision']['action'], 'scramble')

    def test_designed_run_role_uses_the_active_qbs_historical_style(self):
        decision_cell = decision_layer.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        qb_cell = qbd.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        decision_table = {
            'league': {category: {} for category in decision_layer.CATS},
            'team': {category: {} for category in decision_layer.CATS},
            'k': decision_layer.K,
        }
        decision_table['league']['B'][decision_cell] = Counter({'QB': 50, 'RB': 50})
        decision_table['team']['B'][('AAA', decision_cell)] = Counter({'QB': 80, 'RB': 20})
        qb_table = {
            'qb_run_player_cell': {('AAA', 'AQB1', qb_cell): Counter({'qb': 0, 'other': 100})},
            'qb_run_team_cell': {('AAA', qb_cell): Counter({'qb': 40, 'other': 60})},
            'qb_run_league_cell': {qb_cell: Counter({'qb': 30, 'other': 70})},
            'qb_run_player_all': {('AAA', 'AQB1'): Counter({'qb': 0, 'other': 100})},
            'qb_run_team_all': {'AAA': Counter({'qb': 40, 'other': 60})},
            'qb_run_league_all': Counter({'qb': 30, 'other': 70}),
        }
        shares = {'receive': {}, 'carry': {('AAA', 'AQB1'): 1.0, ('AAA', 'ARB1'): 100.0}}
        outputs = [pe.choose(SNAPSHOT, 'home', 'run', seed=i, index=0, state=STATE,
                             player_shares=shares, decision_table=decision_table,
                             qb_decision_table=qb_table, qb_run_role_style_enabled=True)
                   for i in range(1200)]

        styles = [out['qb_run_role_style'] for out in outputs]
        self.assertTrue(all(style['adjusted'] for style in styles))
        self.assertTrue(all(style['adjusted_qb_probability'] < style['base_qb_probability'] for style in styles))
        qb_rate = sum(out['labels']['B'] == 'QB' for out in outputs) / len(outputs)
        self.assertAlmostEqual(qb_rate, styles[0]['adjusted_qb_probability'], delta=0.04)
        for out in outputs:
            if out['labels']['B'] == 'QB':
                self.assertEqual(out['rusher']['gsis_id'], 'AQB1')
            else:
                self.assertNotEqual(out['rusher']['gsis_id'], 'AQB1')

        control = pe.choose(SNAPSHOT, 'home', 'run', seed=0, index=0, state=STATE,
                            player_shares=shares, decision_table=decision_table,
                            qb_decision_table=qb_table, qb_run_role_style_enabled=False)
        self.assertNotIn('qb_run_role_style', control)

    def test_unavailable_backup_qb_cannot_receive_a_qb_style_run_adjustment(self):
        decision_cell = decision_layer.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        qb_cell = qbd.cell_of(STATE['down'], STATE['togo'], STATE['yl'])
        decision_table = {
            'league': {category: {} for category in decision_layer.CATS},
            'team': {category: {} for category in decision_layer.CATS},
            'k': decision_layer.K,
        }
        decision_table['league']['B'][decision_cell] = Counter({'QB': 50, 'RB': 50})
        decision_table['team']['B'][('AAA', decision_cell)] = Counter({'QB': 80, 'RB': 20})
        qb_table = {
            'qb_run_player_cell': {('AAA', 'AQB2', qb_cell): Counter({'qb': 0, 'other': 100})},
            'qb_run_team_cell': {('AAA', qb_cell): Counter({'qb': 40, 'other': 60})},
            'qb_run_league_cell': {qb_cell: Counter({'qb': 30, 'other': 70})},
            'qb_run_player_all': {('AAA', 'AQB2'): Counter({'qb': 0, 'other': 100})},
            'qb_run_team_all': {'AAA': Counter({'qb': 40, 'other': 60})},
            'qb_run_league_all': Counter({'qb': 30, 'other': 70}),
        }
        shares = {'receive': {}, 'carry': {('AAA', 'AQB2'): 100.0, ('AAA', 'ARB1'): 1.0}}
        for seed in range(100):
            chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=seed, index=0, state=STATE,
                               player_shares=shares, decision_table=decision_table,
                               qb_decision_table=qb_table, qb_run_role_style_enabled=True)
            self.assertNotEqual(chosen['rusher']['gsis_id'], 'AQB2')

    def test_rostered_out_and_doubtful_players_are_excluded_without_the_qb_model(self):
        snapshot = {**SNAPSHOT, 'rosters': {**SNAPSHOT['rosters'], 'home': {
            **SNAPSHOT['rosters']['home'],
            'injury_report': {'players': [
                {'gsis_id': 'AQB1', 'report_status': 'Out'},
                {'gsis_id': 'AWR1', 'report_status': 'Out'},
                {'gsis_id': 'AWR2', 'report_status': 'Doubtful'},
                {'gsis_id': 'ARB1', 'report_status': 'Out'},
            ]}}}}
        for seed in range(20):
            dropback = pe.choose(snapshot, 'home', 'dropback', seed=seed, index=0)
            rush = pe.choose(snapshot, 'home', 'run', seed=seed, index=1)
            self.assertEqual(dropback['passer']['gsis_id'], 'AQB2')
            self.assertNotIn(dropback['receiver']['gsis_id'], {'AWR1', 'AWR2'})
            self.assertNotEqual(rush['rusher']['gsis_id'], 'ARB1')


class DirichletPopulationInvariants(unittest.TestCase):
    def test_a_trick_passer_does_not_shrink_the_game_level_receiver_population(self):
        import share_distributions as sd_mod
        calls = []
        play_populations = []
        receiver_candidates = []
        real = sd_mod.game_shares
        real_choose = pe._by_game_share

        def counting(table, team, game_id, eligible, role, seed_text, group='all'):
            if role == 'receive':
                calls.append(tuple(eligible))
            return real(table, team, game_id, eligible, role, seed_text, group=group)

        def recording_candidates(candidates, table, team, role, game_id, seed_text, draw,
                                 cache=None, population=None, group='all'):
            if role == 'receive':
                receiver_candidates.append(tuple(sorted(p['gsis_id'] for p in candidates)))
                play_populations.append(tuple(sorted(p['gsis_id'] for p in population)))
            return real_choose(candidates, table, team, role, game_id, seed_text, draw,
                               cache=cache, population=population, group=group)

        players = SNAPSHOT['rosters']['home']['players']
        receivers = [p for p in players if p['pos_abb'] in pe.player_shares_positions('receive')]
        share_table = {
            'phi': {'receive': 10.0},
            'base': {'receive': {('AAA', p['gsis_id']): 1 / len(receivers) for p in receivers}},
        }
        cache = {}
        passers = set()
        play_passers = []
        with patch.object(sd_mod, 'game_shares', side_effect=counting), \
             patch.object(pe, '_by_game_share', side_effect=recording_candidates):
            for index in range(40):
                chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=index,
                                   player_shares={'receive': {}, 'carry': {}}, share_table=share_table,
                                   share_cache=cache, trick_passer_rate=1.0, qb_receiver_rate=0.0)
                passer_id = chosen['passer']['gsis_id']
                passers.add(passer_id)
                play_passers.append(passer_id)
                self.assertNotEqual(chosen['receiver']['gsis_id'], passer_id)

        expected_population = tuple(sorted(p['gsis_id'] for p in receivers))
        self.assertGreater(len(passers), 1)
        self.assertTrue(passers <= set(expected_population))
        self.assertEqual(calls, [expected_population])
        self.assertEqual(play_populations, [expected_population] * 40)
        self.assertEqual(len(receiver_candidates), 40)
        self.assertTrue(all(passer not in candidates for passer, candidates in
                            zip(play_passers, receiver_candidates)))


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
