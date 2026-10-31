"""Input preflight tests for the frozen SLC research artifacts."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playbook_crosscheck  # noqa: E402
import source_preflight  # noqa: E402


class PlaybookTargetTeamAliases(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        entries = []
        for team in ('LA', 'WAS'):
            output = f'{team}-2025.json'
            path = self.root / output
            path.write_text(json.dumps({
                'team_id': team,
                'offense': {'observed_plays': [{'play_type': 'run'}]},
            }))
            entries.append({
                'team': team,
                'season': 2025,
                'output': output,
                'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        (self.root / 'build_manifest.json').write_text(json.dumps({'team_seasons': entries}))

    def test_schedule_aliases_match_canonical_playbook_teams(self):
        with mock.patch.object(playbook_crosscheck, 'PLAYBOOKS', str(self.root)):
            errors, _ = source_preflight._playbook_errors(2026, ('LA', 'WAS'))

        self.assertFalse(any('playbook prior is missing target-game teams' in error for error in errors), errors)

    def test_unmapped_target_team_still_fails_preflight(self):
        with mock.patch.object(playbook_crosscheck, 'PLAYBOOKS', str(self.root)):
            errors, _ = source_preflight._playbook_errors(2026, ('XYZ',))

        self.assertTrue(any("playbook prior is missing target-game teams ['XYZ']" in error for error in errors), errors)


if __name__ == '__main__':
    unittest.main()
