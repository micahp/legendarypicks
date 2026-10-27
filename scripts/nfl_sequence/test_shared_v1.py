"""Tests for the shared-contract projection and its checker (shared_v1.py), with negative fixtures.

Run: python3 -m unittest scripts/nfl_sequence/test_shared_v1.py The checker works from the document alone. Each negative
test breaks one contract rule and expects its violation ID.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import game_state as gs  # noqa: E402
import shared_v1 as sv  # noqa: E402
from test_game_state import StaticPool, kickoff_pool, certain_kicks, ref  # noqa: E402

# Violations that the source cannot supply. A clean projection has exactly these and no others.
UNSOURCED = {'V-mode', 'V-unresolved-game_id', 'V-unresolved-scheduled_kickoff_utc', 'V-unresolved-as_of_utc',
             'V-unresolved-snapshot_hash', 'V-unresolved-roster_snapshot_id', 'V-duration-seconds'}


TEST_STAMPS = {'model_version': 'test-model', 'rules_version': 'test-rules'}  # fixed values: the tests do not need a clean tree


def played(**stamps):
    rec = gs.play_game(1, ref(StaticPool('run', 80, 20), kickoff_pool()), winner_choice='receive', max_drives=2)
    return {**rec, **stamps}


def document():
    return sv.build_document(played(**TEST_STAMPS))


def ids(doc):
    return {v['id'] for v in sv.check_document(doc)}


class Stamps(unittest.TestCase):
    """The document takes its two version fields from the record. A record without them is refused, not given a label."""

    def test_the_document_carries_the_record_stamps(self):
        doc = document()
        self.assertEqual((doc['model_version'], doc['rules_version']), ('test-model', 'test-rules'))

    def test_a_record_without_its_version_stamps_is_refused(self):
        # The engine stamps every record it writes, so the refusal is tested on a record with the stamps taken off.
        rec = played()
        rec.pop('model_version', None)
        rec.pop('rules_version', None)
        with self.assertRaises(KeyError):
            sv.build_document(rec)


class Projection(unittest.TestCase):
    def test_a_clean_projection_has_only_the_unsourced_violations(self):
        self.assertEqual(ids(document()), UNSOURCED)

    def test_events_are_numbered_and_ids_match_the_simulation(self):
        doc = document()
        self.assertEqual([p['sequence'] for p in doc['plays']], list(range(1, len(doc['plays']) + 1)))
        self.assertTrue(all(p['id'] == f"{doc['simulation_id']}:{p['sequence']}" for p in doc['plays']))

    def test_the_kickoff_and_the_try_are_plays_in_the_contract_vocabulary(self):
        kinds = [p['event_type'] for p in document()['plays']]
        self.assertIn('kickoff', kinds)
        self.assertIn('extra_point', kinds)
        self.assertTrue(set(kinds) <= set(sv.EVENT_VOCABULARY))


class NegativeFixtures(unittest.TestCase):
    def test_an_event_outside_the_vocabulary_fails(self):
        doc = document()
        doc['plays'][0]['event_type'] = 'bogus_event'
        self.assertIn('V-event-vocabulary', ids(doc))

    def test_a_state_missing_a_required_field_fails(self):
        doc = document()
        del doc['plays'][0]['state_before']['yardline_100']
        self.assertIn('V-state-fields', ids(doc))

    def test_an_id_that_does_not_match_the_simulation_fails(self):
        doc = document()
        doc['plays'][0]['id'] = 'some-other-sim:1'
        self.assertIn('V-id', ids(doc))

    def test_a_team_stat_that_is_not_the_sum_of_the_plays_fails(self):
        doc = document()
        doc['summary']['team_stats']['A']['plays'] += 1
        self.assertIn('V-team-stats', ids(doc))

    def test_a_player_stat_that_is_not_the_sum_of_the_plays_fails(self):
        doc = document()
        doc['summary']['player_stats'] = {'x': {'passing': {'att': 99}}}
        self.assertIn('V-player-stats', ids(doc))

    def test_a_valid_full_game_claim_fails(self):
        doc = document()
        doc['summary']['valid_full_game'] = True
        self.assertIn('V-valid-claim', ids(doc))

    def test_a_missing_provenance_label_fails(self):
        doc = document()
        del doc['provenance']['routes']
        self.assertIn('V-prov-routes', ids(doc))

    def test_a_final_score_that_disagrees_with_the_last_state_fails(self):
        doc = document()
        doc['summary']['home_score'] += 3
        self.assertIn('V-final-score', ids(doc))


if __name__ == '__main__':
    unittest.main()
