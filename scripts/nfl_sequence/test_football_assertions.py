"""Classification and evidence-envelope tests for the Football Realism Assertion Suite."""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from football_assertions import (FootballAssertionError, classify_failure, failure_envelope,
                                 unresolved_transition_envelope)


class FailureClassification(unittest.TestCase):
    def test_the_five_suite_failure_classes_are_distinct(self):
        cases = (
            ('a yardline is outside the legal field', 'ILLEGAL_STATE'),
            ('NONCAUSAL_INFORMATION: a defender read hidden state', 'NONCAUSAL_INFORMATION'),
            ('STAT_ACCOUNTING: player and team points differ', 'STAT_ACCOUNTING'),
            ('unsupported rule: onside kick', 'UNSUPPORTED_RULE'),
            ('DISTRIBUTION_WARNING: pass rate differs', 'DISTRIBUTION_WARNING'),
        )
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(classify_failure(message), expected)

    def test_play_failure_envelope_includes_decision_states_and_source_hashes(self):
        play = {
            'sequence': 2,
            'event_type': 'run',
            'state_before': {'down': 3, 'yardline_100': 40},
            'outcome': {'yards_gained': 4, 'turnover': False},
            'state_after': {'down': 4, 'yardline_100': 36},
        }
        record = {'drives': [{'index': 1, 'plays': [
            {'sequence': 1, 'event_type': 'run', 'state_before': {}, 'outcome': {}, 'state_after': {}}, play]}]}
        decision = {'intent': 'run', 'action': 'inside_zone'}
        failure = failure_envelope(
            AssertionError('drive 1 play 2 violates legal spot progression'),
            seed=91, game_id='2025_01_AAA_BBB', record=record, decisions=[{}, decision],
            source_artifact_hashes={'reducer_sha256': 'a' * 64})

        self.assertEqual(failure['schema'], 'lp.nfl.football-realism-assertion-failure.v1')
        self.assertEqual(failure['failure_class'], 'ILLEGAL_STATE')
        self.assertEqual(failure['game_id'], '2025_01_AAA_BBB')
        self.assertEqual(failure['seed'], 91)
        self.assertEqual(failure['play_index'], 2)
        self.assertEqual(failure['state_before'], play['state_before'])
        self.assertEqual(failure['decision'], decision)
        self.assertEqual(failure['outcome']['event_type'], 'run')
        self.assertEqual(failure['state_after'], play['state_after'])
        self.assertIn('legal spot progression', failure['violated_assertion'])
        self.assertEqual(failure['source_artifact_hashes']['reducer_sha256'], 'a' * 64)

    def test_drive_level_failure_resolves_terminal_play_evidence(self):
        play = {
            'sequence': 7, 'event_type': 'run',
            'state_before': {'down': 4, 'yardline_100': 3},
            'outcome': {'yards_gained': 2, 'touchdown': False},
            'state_after': {'down': 4, 'yardline_100': 1},
        }
        record = {'drives': [{'index': 4, 'plays': [play]}]}
        decision = {'intent': 'run', 'participants': {'rusher': 'RB1'}}
        decisions = [{} for _ in range(6)] + [decision]
        failure = failure_envelope(
            AssertionError('drive 4 scoring attribution disagrees with its terminal'),
            seed=92, record=record, decisions=decisions)

        self.assertEqual(failure['play_index'], 7)
        self.assertEqual(failure['decision'], decision)
        self.assertEqual(failure['state_before'], play['state_before'])
        self.assertEqual(failure['outcome']['event_type'], 'run')
        self.assertEqual(failure['state_after'], play['state_after'])

    def test_unsupported_transition_keeps_explicit_unresolved_state_and_provenance(self):
        record = {
            'drives': [{'plays': [{'sequence': 1}, {'sequence': 2}]}],
            'blocked_attempt': {
                'drive_index': 2, 'blocker': 'blocked kick outcome is ambiguous',
                'state_at_drive_start': {'quarter': 2, 'clock': 300, 'yl': 40},
                'plays_before_block': [{'state_after': {'quarter': 2, 'clock_seconds': 280, 'yardline_100': 35}}],
            },
        }
        failure = unresolved_transition_envelope(
            record, seed=93, game_id='2025_01_AAA_BBB', source_artifact_hashes={'fixture_sha256': 'd' * 64})

        self.assertEqual(failure['failure_class'], 'UNSUPPORTED_RULE')
        self.assertEqual(failure['status'], 'unresolved')
        self.assertEqual(failure['play_index'], 4)
        self.assertEqual(failure['state_before'], record['blocked_attempt']['plays_before_block'][0]['state_after'])
        self.assertEqual(failure['outcome']['blocker'], record['blocked_attempt']['blocker'])
        self.assertEqual(failure['state_after']['status'], 'unresolved')
        self.assertEqual(failure['source_artifact_hashes']['fixture_sha256'], 'd' * 64)

    def test_embedded_slc_decision_context_is_preserved_when_play_generation_raises(self):
        context = {
            'game_id': '2025_01_AAA_BBB', 'seed': 17, 'play_index': 1,
            'state_before': {'down': 2, 'yardline_100': 50},
            'decision': {'qb_action': 'scramble'},
            'outcome': {'event_type': 'pass_complete', 'yards_gained': 12},
            'state_after': {'down': 1, 'yardline_100': 38},
            'source_artifact_hashes': {'playcall_artifact_sha256': 'b' * 64},
        }
        error = AssertionError(f'ILLEGAL_STATE: scramble mismatch; context={context!r}')
        failure = failure_envelope(error, seed=17)

        self.assertEqual(failure['failure_class'], 'ILLEGAL_STATE')
        self.assertEqual(failure['game_id'], context['game_id'])
        self.assertEqual(failure['play_index'], 1)
        self.assertEqual(failure['decision'], context['decision'])
        self.assertEqual(failure['outcome'], context['outcome'])
        self.assertEqual(failure['state_before'], context['state_before'])
        self.assertEqual(failure['state_after'], context['state_after'])
        self.assertEqual(failure['source_artifact_hashes'], context['source_artifact_hashes'])

    def test_typed_context_survives_without_repr_parsing_and_resolves_game_id(self):
        context = {
            'play_index': 1, 'state_before': {'down': 1}, 'decision': {'intent': 'run'},
            'outcome': {'event_type': 'run'}, 'state_after': {'down': 2},
            'source_artifact_hashes': {'engine_sha256': 'c' * 64},
        }
        error = FootballAssertionError('ILLEGAL_STATE', 'fixture', context=context)
        failure = failure_envelope(
            error, seed=23, game_id='unknown',
            record={'pregame_snapshot': {'schedule': {'game_id': '2025_02_BBB_CCC'}}})

        self.assertEqual(classify_failure(error), 'ILLEGAL_STATE')
        self.assertEqual(error.context['violated_assertion'], 'fixture')
        self.assertEqual(failure['violated_assertion'], 'fixture')
        self.assertEqual(failure['game_id'], '2025_02_BBB_CCC')
        self.assertEqual(failure['play_index'], 1)
        self.assertEqual(failure['decision'], context['decision'])
        self.assertEqual(failure['source_artifact_hashes'], context['source_artifact_hashes'])


if __name__ == '__main__':
    unittest.main()
