import random
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e1_drive as e1  # noqa: E402
import playcall_model as pm  # noqa: E402
import slc_playcall as slc  # noqa: E402
import slc_engine as se  # noqa: E402

TEAMS = {'AAA': 0, 'BBB': 1}
SIZES = {'down_dist': 24, 'field': 5, 'score': 15, 'clock': 8, 'score_clock': 120, 'down_field': 20}


def blank_artifact(intercept, teams=('AAA', 'BBB'), blocks=None):
    sizes = dict(SIZES, team_down=4 * len(teams))
    blocks = blocks or {g: [0.0] * n for g, n in sizes.items()}
    artifact = {'artifact_id': slc.ARTIFACT_ID, 'reference_season': 2026, 'recency_tau': 3.0, 'fit_seasons': [2010],
                'primary_plays_only': True, 'penalties': {}, 'fit_iterations': 0, 'plays': 0, 'frame_sha256': 'test',
                'teams': list(teams), 'intercept': intercept, 'blocks': blocks, 'bucket_maps': {}, 'season_effect': 'test'}
    artifact['sha256'] = slc._sha(artifact)
    return artifact


def cell(events_and_types):
    rows = []
    for i, (event, play_type) in enumerate(events_and_types):
        row = {'game_id': '2025_01_AAA_BBB', 'play_id': i, 'season': 2025, 'down': 1, 'ydstogo': 10, 'yardline_100': 50,
               'play_type': play_type, 'posteam': 'AAA'}
        rows.append((event, row, 6.0, 52))
    return rows


STATE = {'quarter': 2, 'clock': 500, 'down': 1, 'togo': 10, 'yl': 50, 'score_diff': 0}


class Layer(unittest.TestCase):
    def test_a_tampered_artifact_is_refused(self):
        artifact = blank_artifact(0.0)
        artifact['intercept'] = 5.0
        with self.assertRaises(ValueError):
            slc.PlayCallLayer(artifact)

    def test_the_layer_gives_the_same_probability_as_the_fitted_model(self):
        frame = synthetic_frame()
        penalties = {g: 10.0 for g in pm.GROUP_NAMES}
        artifact = slc.freeze(frame, penalties, 3.0, 2026)
        layer = slc.PlayCallLayer(artifact)
        design = pm.Design(frame)
        rows = np.arange(len(frame))
        prep = pm.prepare(design, rows, pm.GROUP_NAMES)
        weights = pm.recency_weights(frame.a['season'], 2026, 3.0)
        beta, _ = pm.fit_prepared(design, prep, frame.a['y'].astype(float), weights, penalties)
        expected = pm.modelled_probability(design, prep['cols'], beta, frame.teams, 1, 2, 'opp_side', 7, 'q3', team='AAA')
        self.assertAlmostEqual(layer.p_dropback(1, 2, 40, 7, 3, 300, 'AAA'), expected, places=9)

    def test_a_trailing_team_late_in_the_half_is_more_likely_to_throw(self):
        frame = synthetic_frame(score_effect=True)
        layer = slc.PlayCallLayer(slc.freeze(frame, {g: 10.0 for g in pm.GROUP_NAMES}, 3.0, 2026))
        trailing = layer.p_dropback(2, 6, 40, -7, 4, 90, 'AAA')
        leading = layer.p_dropback(2, 6, 40, 7, 4, 90, 'AAA')
        self.assertGreater(trailing, leading)

    def test_an_unknown_team_adds_no_team_effect(self):
        layer = slc.PlayCallLayer(blank_artifact(0.0, blocks=dict(
            {g: [0.0] * n for g, n in SIZES.items()}, team_down=[0.0] * 4 + [3.0] * 4)))
        self.assertAlmostEqual(layer.logit(1, 10, 50, 0, 1, 500, 'ZZZ'), layer.logit(1, 10, 50, 0, 1, 500))


class Sampler(unittest.TestCase):
    def test_missing_team_outcome_support_is_recorded_as_a_fallback(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)),
                                      side_teams={'A': 'AAA', 'B': 'BBB'})

        class MissingTendency:
            def ratio(self, side, team, _cell, _event):
                raise ValueError(f'no prior sample for {side}:{team}')

        sampler.team_outcomes = MissingTendency()
        weight = sampler._outcome_weight('pass_complete', 'A', 'B', ('situation',))
        self.assertEqual(weight, 1.0)
        self.assertEqual(sampler._current_team_outcome_fallbacks, [
            'no_prior_sample:offense:AAA:pass_complete',
            'no_prior_sample:defense:BBB:pass_complete',
        ])

    def test_a_near_certain_dropback_draws_only_dropback_outcomes(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('run', 'run'), ('pass_complete', 'pass'), ('pass_incomplete', 'pass'), ('sack', 'pass')])
        rng = random.Random(1)
        drawn = {sampler.sample(rng, pool, 'A', 'B', state=STATE)[0] for _ in range(200)}
        self.assertEqual(drawn, {'pass_complete', 'pass_incomplete', 'sack'})
        self.assertTrue(all(d['intent'] == 'dropback' for d in sampler.decisions))

    def test_a_near_certain_run_draws_only_runs(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(-30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('run', 'run'), ('pass_complete', 'pass')])
        rng = random.Random(1)
        drawn = {sampler.sample(rng, pool, 'A', 'B', state=STATE)[0] for _ in range(200)}
        self.assertEqual(drawn, {'run'})

    def test_the_play_is_chosen_before_the_outcome_and_every_decision_is_recorded(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('run', 'run'), ('pass_complete', 'pass')])
        event, row, runoff, spot = sampler.sample(random.Random(2), pool, 'A', 'B', state=STATE)
        decision = sampler.decisions[-1]
        self.assertEqual(decision['event'], event)
        self.assertEqual(decision['source']['game_id'], row['game_id'])
        self.assertEqual(decision['artifact_sha256'], sampler.layer.artifact['sha256'])
        self.assertEqual(decision['state']['team'], 'AAA')
        self.assertAlmostEqual(decision['p_dropback'], 0.5, places=6)

    def test_pregame_player_sampling_excludes_unmodeled_lateral_rows(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)),
                                      side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('pass_complete', 'pass'), ('pass_complete', 'pass')])
        pool[1][1].update(lateral_receiver_player_id='LATERAL1', lateral_receiving_yards=-4)
        sampler.participant_chooser = lambda *_: {
            'passer': {'gsis_id': 'AQB1'}, 'receiver': {'gsis_id': 'AWR1'},
        }

        event, row, _runoff, _spot = sampler.sample(random.Random(3), pool, 'A', 'B', state=STATE)

        self.assertEqual(event, 'pass_complete')
        self.assertEqual(row['play_id'], 0)
        self.assertEqual(sampler.decisions[-1]['source_row_filter_policy'], 'exclude_unmodeled_lateral_transfers')
        self.assertEqual(sampler.decisions[-1]['lateral_source_rows_excluded_from_situation_cell'], 1)

    def test_reference_pool_filter_joins_lateral_facts_by_source_play_id(self):
        pool = {('cell',): cell([('pass_complete', 'pass'), ('run', 'run'), ('pass_complete', 'pass')])}
        participants = {
            ('2025_01_AAA_BBB', 0): {
                'lateral_receiver_player_id': 'LATERAL1', 'lateral_receiving_yards': 0,
            },
            ('2025_01_AAA_BBB', 1): {
                'lateral_rusher_player_id': 'LATERAL2', 'lateral_rushing_yards': -3,
            },
        }

        filtered, evidence = se.exclude_unmodeled_lateral_rows(pool, participants)

        self.assertEqual([sample[1]['play_id'] for sample in filtered[('cell',)]], [2])
        self.assertEqual(evidence, {
            'policy': 'exclude_unmodeled_lateral_transfers',
            'rows_excluded': 2,
            'rows_excluded_by_event': {'pass_complete': 1, 'run': 1},
        })

    def test_player_outcome_backoff_excludes_unmodeled_lateral_rows(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)),
                                      side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('pass_complete', 'pass') for _ in range(12)])
        pool[0][1]['lateral_receiver_player_id'] = 'LATERAL1'
        pool[0][1]['lateral_receiving_yards'] = -4
        sampler.participant_chooser = lambda *_: {
            'passer': {'gsis_id': 'AQB1'}, 'receiver': {'gsis_id': 'AWR1'},
        }
        sampler.source_pool = {'cell': pool}

        candidates, fallback = sampler._backoff_candidates(STATE, 'dropback', False)

        self.assertEqual(fallback, 'exact_cell')
        self.assertEqual(len(candidates), 11)
        self.assertTrue(all(not sampler._has_lateral(sample[1]) for sample in candidates))
        self.assertEqual(sampler._backoff_lateral_rows_excluded, 1)

    def test_changing_only_the_selected_receiver_preserves_the_outcome_and_rng_stream(self):
        """Share-driven participant draws use an independent stream; outcomes ignore the selected identity."""
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('pass_complete', 'pass'), ('pass_complete', 'pass'), ('pass_incomplete', 'pass')])
        for sample, yards in zip(pool, (5, 23, 0)):
            sample[1]['yards_gained'] = yards

        paired_results = []
        paired_rng_states = []
        for shares in ({'AWR1': 1.0, 'AWR2': 0.0}, {'AWR1': 0.0, 'AWR2': 1.0}):
            participant_rng = random.Random(773)

            def choose_participant(_intent, _offense, _state):
                receiver = participant_rng.choices(tuple(shares), weights=tuple(shares.values()), k=1)[0]
                return {'passer': {'gsis_id': 'AQB1'}, 'receiver': {'gsis_id': receiver}}

            sampler.participant_chooser = choose_participant
            rng = random.Random(912)
            event, row, _runoff, _spot = sampler.sample(rng, pool, 'A', 'B', state=STATE)
            paired_results.append((event, row['game_id'], row['play_id'], row['yards_gained'],
                                   row['pre_event']['receiver']['gsis_id']))
            paired_rng_states.append(rng.getstate())
            self.assertFalse(sampler.decisions[-1]['player_outcomes_conditioned'])

        self.assertEqual(paired_results[0][:4], paired_results[1][:4])
        self.assertNotEqual(paired_results[0][4], paired_results[1][4])
        self.assertEqual(paired_rng_states[0], paired_rng_states[1])

    def test_player_outcome_table_makes_the_selected_player_affect_event_sampling(self):
        """The opt-in outcome table is the sampler path that turns player identity into a scoring input."""
        event_counts = {'pass_complete': 100, 'pass_incomplete': 100}
        outcome_table = {
            'base_events': {'qb': event_counts, 'receiver': event_counts, 'rusher': {}},
            'event_counts': {
                'qb': {'AQBGOOD': {'pass_complete': 100}, 'AQBBAD': {'pass_incomplete': 100}},
                'receiver': {'AWRGOOD': {'pass_complete': 100}, 'AWRBAD': {'pass_incomplete': 100}},
                'rusher': {},
            },
            'base_results': {'qb': {}, 'receiver': {}, 'rusher': {}},
            'row_stats': {},
        }
        pool = cell([('pass_complete', 'pass'), ('pass_incomplete', 'pass')])
        good = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        bad = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        good.player_outcome_table = outcome_table
        bad.player_outcome_table = outcome_table
        good.participant_chooser = lambda *_: {'passer': {'gsis_id': 'AQBGOOD'}, 'receiver': {'gsis_id': 'AWRGOOD'}}
        bad.participant_chooser = lambda *_: {'passer': {'gsis_id': 'AQBBAD'}, 'receiver': {'gsis_id': 'AWRBAD'}}

        good_completions = 0
        bad_completions = 0
        draws = 200
        for seed in range(draws):
            good_event = good.sample(random.Random(seed), pool, 'A', 'B', state=STATE)[0]
            bad_event = bad.sample(random.Random(seed), pool, 'A', 'B', state=STATE)[0]
            good_completions += good_event == 'pass_complete'
            bad_completions += bad_event == 'pass_complete'

        self.assertGreater(good_completions, bad_completions + 100)
        self.assertTrue(all(d['player_outcomes_conditioned'] for d in good.decisions + bad.decisions))

    def test_receiver_only_outcomes_ignore_qb_identity_and_condition_on_receiver_identity(self):
        event_counts = {'pass_complete': 100, 'pass_incomplete': 100}
        outcome_table = {
            'base_events': {'qb': event_counts, 'receiver': event_counts, 'rusher': {}},
            'event_counts': {
                'qb': {'AQBGOOD': {'pass_complete': 100}, 'AQBBAD': {'pass_incomplete': 100}},
                'receiver': {'AWRGOOD': {'pass_complete': 100}, 'AWRBAD': {'pass_incomplete': 100}},
                'rusher': {},
            },
            'base_results': {'qb': {}, 'receiver': {}, 'rusher': {}},
            'row_stats': {},
        }
        pool = cell([('pass_complete', 'pass'), ('pass_incomplete', 'pass')])

        def sampler(passer, receiver):
            result = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
            result.player_outcome_table = outcome_table
            result.player_outcome_roles = ('receiver',)
            result.participant_chooser = lambda *_: {'passer': {'gsis_id': passer}, 'receiver': {'gsis_id': receiver}}
            return result

        good_receiver_good_qb = sampler('AQBGOOD', 'AWRGOOD')
        good_receiver_bad_qb = sampler('AQBBAD', 'AWRGOOD')
        bad_receiver_good_qb = sampler('AQBGOOD', 'AWRBAD')
        outcomes_by_seed = [[], [], []]
        for seed in range(200):
            for result, target in zip((good_receiver_good_qb, good_receiver_bad_qb, bad_receiver_good_qb), outcomes_by_seed):
                target.append(result.sample(random.Random(seed), pool, 'A', 'B', state=STATE)[0])

        self.assertEqual(outcomes_by_seed[0], outcomes_by_seed[1])
        self.assertGreater(outcomes_by_seed[0].count('pass_complete'),
                           outcomes_by_seed[2].count('pass_complete') + 100)
        self.assertTrue(all(d['player_outcome_roles'] == ['receiver']
                            for d in good_receiver_good_qb.decisions))

    def test_qb_target_role_filters_source_rows_and_records_its_available_probabilities(self):
        pool = cell([('pass_complete', 'pass'), ('pass_complete', 'pass')])
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.qb_decision_table = {'row_target_roles': {
            (pool[0][1]['game_id'], pool[0][1]['play_id']): 'WR',
            (pool[1][1]['game_id'], pool[1][1]['play_id']): 'TE',
        }}
        sampler.participant_chooser = lambda *_: {
            'passer': {'gsis_id': 'AQB1', 'pos_abb': 'QB'},
            'receiver': {'gsis_id': 'AWR1', 'pos_abb': 'WR'},
            'qb_decision': {'action': 'pass', 'target_role': 'WR', 'target_role_history_n': 30,
                            'target_role_probabilities': {'WR': 0.75, 'TE': 0.25}},
        }

        _event, row, _runoff, _spot = sampler.sample(random.Random(3), pool, 'A', 'B', state=STATE)

        self.assertEqual(row['play_id'], 0)
        self.assertTrue(sampler.decisions[-1]['qb_target_role_conditioned'])
        self.assertEqual(sampler.decisions[-1]['qb_target_role'], 'WR')
        self.assertEqual(sampler.decisions[-1]['qb_target_role_probabilities'], {'WR': 0.75, 'TE': 0.25})
        self.assertIsNone(sampler.decisions[-1]['qb_target_role_fallback'])

    def test_missing_source_rows_for_the_chosen_qb_role_fall_back_and_are_countable(self):
        pool = cell([('pass_complete', 'pass')])
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(100.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        sampler.qb_decision_table = {'row_target_roles': {
            (pool[0][1]['game_id'], pool[0][1]['play_id']): 'TE',
        }}
        sampler.participant_chooser = lambda *_: {
            'passer': {'gsis_id': 'AQB1', 'pos_abb': 'QB'},
            'receiver': {'gsis_id': 'AWR1', 'pos_abb': 'WR'},
            'qb_decision': {'action': 'pass', 'target_role': 'WR', 'target_role_history_n': 2,
                            'target_role_probabilities': {'WR': 1.0}},
        }

        _event, row, _runoff, _spot = sampler.sample(random.Random(3), pool, 'A', 'B', state=STATE)

        self.assertEqual(row['play_id'], 0)
        self.assertEqual(row['pre_event']['receiver']['pos_abb'], 'WR')
        self.assertFalse(sampler.decisions[-1]['qb_target_role_conditioned'])
        self.assertEqual(sampler.decisions[-1]['qb_target_role_fallback'],
                         'no_target_identity_match_in_event_cell')
        self.assertEqual(se.summary(sampler.decisions)['qb_target_role_fallbacks'], 1)

    def test_a_missing_intent_in_the_cell_fails_closed(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(30.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        with self.assertRaises(e1.SamplingUnavailable):
            sampler.sample(random.Random(3), cell([('run', 'run')]), 'A', 'B', state=STATE)

    def test_missing_state_fails_closed(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        with self.assertRaises(e1.SamplingUnavailable):
            sampler.sample(random.Random(4), cell([('run', 'run'), ('pass_complete', 'pass')]), 'A', 'B')
        with self.assertRaises(e1.SamplingUnavailable):
            sampler.sample(random.Random(4), cell([('run', 'run'), ('pass_complete', 'pass')]), 'A', 'B',
                           state=dict(STATE, score_diff=None))

    def test_kick_outcomes_keep_their_historical_share_and_are_marked_as_a_fallback(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('punt', 'punt'), ('run', 'run'), ('pass_complete', 'pass')])
        rng = random.Random(5)
        for _ in range(600):
            sampler.sample(rng, pool, 'A', 'B', state=STATE)
        kicks = [d for d in sampler.decisions if d['intent'] == 'kick']
        self.assertTrue(0.28 < len(kicks) / 600 < 0.39)  # one punt in three cell rows
        self.assertTrue(all(d['fallback'] for d in kicks))

    def test_infeasible_field_goal_is_removed_without_forcing_a_punt(self):
        sampler = slc.PlayCallSampler(slc.PlayCallLayer(blank_artifact(0.0)), side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('field_goal_attempt', 'field_goal'), ('punt', 'punt'), ('run', 'run'),
                     ('pass_complete', 'pass')])
        state = dict(STATE, down=4, yl=54)
        rng = random.Random(103)
        events = set()
        for _ in range(400):
            event, _row, _runoff, _spot = sampler.sample(rng, pool, 'A', 'B', state=state)
            events.add(event)

        self.assertNotIn('field_goal_attempt', events)
        self.assertIn('punt', events)
        self.assertIn('run', events, 'go-for-it by run remains available after the field goal is filtered')
        self.assertIn('pass_complete', events, 'go-for-it by pass remains available after the field goal is filtered')
        self.assertTrue(all(not decision['field_goal_feasibility']['eligible'] for decision in sampler.decisions))

    def test_batch_decision_summary_preserves_all_situational_dimensions(self):
        decision = {
            'intent': 'kick', 'outcome_intent': 'kick', 'event': 'field_goal_attempt',
            'state': {'team': 'AAA', 'quarter': 4, 'clock': 90, 'down': 4, 'togo': 2,
                      'yardline_100': 15, 'score_diff': -7},
        }
        rows = se.summary([decision])['situational_decision_counts']

        self.assertEqual(rows, [{
            'team': 'AAA', 'quarter': 4, 'down': 4, 'distance_bucket': 'd1_2',
            'field_bucket': 'red_zone', 'score_bucket': 'dn7', 'clock_bucket': 'q4_2min',
            'action': 'field_goal', 'count': 1,
        }])


class Sensitivity(unittest.TestCase):
    def _layer(self):
        blocks = {g: [0.0] * n for g, n in SIZES.items()}
        blocks['team_down'] = [0.0] * 8
        blocks['score'][pm.SCORE_BUCKETS.index('dn7')] = 1.0   # trailing by 7
        blocks['score'][pm.SCORE_BUCKETS.index('up7')] = -1.0  # leading by 7
        blocks['clock'][pm.CLOCK_BUCKETS.index('q4_2min')] = 0.5
        return slc.PlayCallLayer(blank_artifact(0.0, blocks=blocks))

    def _dropback_share(self, sampler, pool, state, draws=2000):
        sampler.decisions.clear()
        rng = random.Random(7)
        for _ in range(draws):
            sampler.sample(rng, pool, 'A', 'B', state=state)
        return sum(d['intent'] == 'dropback' for d in sampler.decisions) / draws

    def test_changing_score_or_clock_changes_the_probability_and_the_observed_mix(self):
        layer = self._layer()
        trailing_late = dict(STATE, quarter=4, clock=90, score_diff=-7)
        leading_late = dict(STATE, quarter=4, clock=90, score_diff=7)
        trailing_early = dict(STATE, quarter=4, clock=900, score_diff=-7)
        p = {name: layer.p_dropback(s['down'], s['togo'], s['yl'], s['score_diff'], s['quarter'], s['clock'], 'AAA')
             for name, s in (('trailing_late', trailing_late), ('leading_late', leading_late),
                             ('trailing_early', trailing_early))}
        self.assertGreater(p['trailing_late'], p['leading_late'])   # score changed, clock held
        self.assertGreater(p['trailing_late'], p['trailing_early'])  # clock changed, score held
        sampler = slc.PlayCallSampler(layer, side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('run', 'run'), ('pass_complete', 'pass')])
        share = {name: self._dropback_share(sampler, pool, s)
                 for name, s in (('trailing_late', trailing_late), ('leading_late', leading_late),
                                 ('trailing_early', trailing_early))}
        self.assertGreater(share['trailing_late'], share['leading_late'] + 0.2)
        self.assertGreater(share['trailing_late'], share['trailing_early'] + 0.05)

    def test_the_play_type_is_drawn_before_the_outcome_is_drawn(self):
        layer = self._layer()
        sampler = slc.PlayCallSampler(layer, side_teams={'A': 'AAA', 'B': 'BBB'})
        pool = cell([('run', 'run'), ('pass_complete', 'pass')])

        calls = []

        class Recording(random.Random):
            # random.choices draws through random() internally, so only the sampler's own first draw is the intent
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

        sampler.sample(Recording(3), pool, 'A', 'B', state=dict(STATE, quarter=4, clock=90, score_diff=-7))
        self.assertEqual(calls, ['intent', 'outcome_type', 'outcome_row'])
        decision = sampler.decisions[-1]
        self.assertEqual(decision['intent'] == 'dropback', decision['event'] != 'run')


def synthetic_frame(seed=11, n=4000, score_effect=False):
    rng = np.random.default_rng(seed)
    season = rng.integers(2010, 2026, n)
    score = rng.integers(0, 15, n)
    if score_effect:
        p = np.where(score < 7, 0.8, 0.3)
    else:
        p = 0.3 + 0.4 * (score > 7)
    arrays = {'season': season, 'team': rng.integers(0, 2, n), 'down': rng.integers(0, 4, n),
              'dist': rng.integers(0, 6, n), 'field': rng.integers(0, 5, n), 'score': score, 'clock': rng.integers(0, 8, n),
              'y': (rng.random(n) < p).astype(np.int64), 'flagged': np.zeros(n, dtype=bool),
              'game': np.zeros(n, dtype=np.int64)}
    return pm.Frame(arrays, TEAMS)


if __name__ == '__main__':
    unittest.main()
