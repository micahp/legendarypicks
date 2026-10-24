"""Tests for the version stamps (versions.py). Git is replaced by a fake, so these tests do not depend on the working tree.

Run: python3 -m unittest scripts/nfl_sequence/test_versions.py
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import versions  # noqa: E402

SHA = 'c131fda249dcf9af642dd6ba267905e88803a74a'


def fake_git(status='', head=SHA):
    def run(*args):
        return status if args[0] == 'status' else head
    return run


class RulesVersion(unittest.TestCase):
    def test_is_a_sha256_digest_of_the_scoped_file_map(self):
        self.assertRegex(versions.rules_version({'a': 'x'}), r'^[0-9a-f]{64}$')

    def test_a_changed_file_hash_changes_it(self):
        base = {'scripts/nfl_sequence/game_state.py': 'a' * 64, 'scripts/nfl_sequence/e1_drive.py': 'b' * 64}
        changed = {**base, 'scripts/nfl_sequence/e1_drive.py': 'c' * 64}
        self.assertNotEqual(versions.rules_version(base), versions.rules_version(changed))

    def test_the_order_of_the_map_does_not_matter(self):
        one = {'x': '1', 'y': '2'}
        two = {'y': '2', 'x': '1'}
        self.assertEqual(versions.rules_version(one), versions.rules_version(two))

    def test_the_scope_is_the_envelope_producer_set(self):
        self.assertEqual(versions.RULE_FILES, (
            'scripts/nfl_sequence/game_state.py', 'scripts/nfl_sequence/rules_matrix.py',
            'scripts/nfl_sequence/e1_drive.py', 'scripts/nfl_sequence/shared_v1.py'))


class ModelVersion(unittest.TestCase):
    def test_a_dirty_engine_file_refuses_to_stamp(self):
        with mock.patch.object(versions, '_git', fake_git(status=' M scripts/nfl_sequence/game_state.py')):
            with self.assertRaises(RuntimeError):
                versions.stamp({'seed': 1})

    def test_a_clean_tree_stamps_the_last_engine_commit_and_the_rules_hash(self):
        with mock.patch.object(versions, '_git', fake_git()), \
                mock.patch.object(versions, 'rules_version', return_value='d' * 64):
            stamped = versions.stamp({'seed': 1})
        self.assertEqual(stamped, {'seed': 1, 'model_version': SHA, 'rules_version': 'd' * 64})
        self.assertRegex(stamped['model_version'], r'^[0-9a-f]{40}$')

    def test_model_version_is_the_engine_commit_not_an_evidence_commit(self):
        # The git call names ENGINE_FILES only, so a commit that touches no engine file cannot change the value.
        calls = []

        def spy(*args):
            calls.append(args)
            return '' if args[0] == 'status' else SHA

        with mock.patch.object(versions, '_git', spy):
            versions.model_version()
        log = [c for c in calls if c[0] == 'log'][0]
        self.assertEqual(log[-len(versions.ENGINE_FILES):], versions.ENGINE_FILES)

    def test_research_stamp_pins_dirty_source_without_weakening_release_stamp(self):
        snapshot = {'base_model_version': SHA, 'source_file_sha256': {'engine.py': 'a' * 64},
                    'source_tree_sha256': 'b' * 64, 'producer_file_sha256': {'rules.py': 'c' * 64},
                    'producer_worktree_dirty': True}
        with mock.patch.object(versions, 'source_snapshot', return_value=snapshot):
            stamped = versions.research_stamp({'seed': 1})
        self.assertEqual(stamped['model_version'], SHA)
        self.assertEqual(stamped['research_source'], snapshot)
        self.assertEqual(stamped['rules_version'], versions.rules_version(snapshot['producer_file_sha256']))


if __name__ == '__main__':
    unittest.main()
