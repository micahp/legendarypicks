import csv
import gzip
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from scripts.nfl_sequence import build_player_workload_reference as workload


def _write_csv(path, fields, rows):
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def _source_fixture(root, *, participation_rows, pbp_rows):
    for season in workload.SEASONS:
        pbp_path = root / f'pbp_{season}.csv.gz'
        with gzip.open(pbp_path, 'wt', encoding='utf-8', newline='') as handle:
            fields = ('game_id', 'play_id', 'season_type', 'play_type', 'qb_kneel', 'qb_spike')
            writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            if season == 2022:
                writer.writerows(pbp_rows)
        participation_path = root / f'pbp_participation_{season}.csv'
        _write_csv(participation_path,
                   ('nflverse_game_id', 'play_id', 'possession_team', 'offense_players', 'offense_positions'),
                   participation_rows if season == 2022 else [])


class HistoricalParticipationTests(unittest.TestCase):
    def test_only_joined_offensive_scrimmage_snaps_define_eligibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _source_fixture(root,
                            pbp_rows=[
                                {'game_id': '2022_01_TST_OPP', 'play_id': '1', 'season_type': 'REG',
                                 'play_type': 'pass', 'qb_kneel': '0', 'qb_spike': '0'},
                                {'game_id': '2022_01_TST_OPP', 'play_id': '2', 'season_type': 'REG',
                                 'play_type': 'field_goal', 'qb_kneel': '0', 'qb_spike': '0'},
                                {'game_id': '2022_01_TST_OPP', 'play_id': '3', 'season_type': 'REG',
                                 'play_type': 'qb_kneel', 'qb_kneel': '1', 'qb_spike': '0'},
                            ],
                            participation_rows=[
                                {'nflverse_game_id': '2022_01_TST_OPP', 'play_id': '1',
                                 'possession_team': 'TST', 'offense_players': 'QB1;RB1',
                                 'offense_positions': 'QB;RB'},
                                {'nflverse_game_id': '2022_01_TST_OPP', 'play_id': '2',
                                 'possession_team': 'TST', 'offense_players': 'K1',
                                 'offense_positions': 'K'},
                                {'nflverse_game_id': '2022_01_TST_OPP', 'play_id': '3',
                                 'possession_team': 'TST', 'offense_players': 'QB1',
                                 'offense_positions': 'QB'},
                                {'nflverse_game_id': '2022_01_TST_OPP', 'play_id': '4',
                                 'possession_team': '', 'offense_players': '', 'offense_positions': ''},
                            ])

            positions = {}
            counts = Counter()
            eligible, position_votes, team_votes = workload._load_historical_participation(
                root, positions, counts)

            self.assertEqual(eligible['2022_01_TST_OPP'], {'QB1', 'RB1'})
            self.assertNotIn(('2022_01_TST_OPP', 'K1'), position_votes)
            self.assertEqual(positions[('2022_01_TST_OPP', 'QB1')], 'QB')
            self.assertEqual(team_votes[('2022_01_TST_OPP', 'QB1')]['TST'], 2)
            self.assertEqual(counts['participation_scrimmage_rows_joined_2022'], 2)
            self.assertEqual(counts['participation_non_scrimmage_rows_excluded_2022'], 1)
            self.assertEqual(counts['participation_empty_rows_without_pbp_match_2022'], 1)

    def test_populated_participation_without_pbp_match_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _source_fixture(root,
                            pbp_rows=[],
                            participation_rows=[{'nflverse_game_id': '2022_01_TST_OPP', 'play_id': '9',
                                                 'possession_team': 'TST', 'offense_players': 'QB1',
                                                 'offense_positions': 'QB'}])
            with self.assertRaisesRegex(ValueError, 'populated participation key has no regular-season PBP row'):
                workload._load_historical_participation(root, {}, Counter())

    def test_participation_position_alignment_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _source_fixture(root,
                            pbp_rows=[{'game_id': '2022_01_TST_OPP', 'play_id': '1', 'season_type': 'REG',
                                       'play_type': 'run', 'qb_kneel': '0', 'qb_spike': '0'}],
                            participation_rows=[{'nflverse_game_id': '2022_01_TST_OPP', 'play_id': '1',
                                                 'possession_team': 'TST', 'offense_players': 'QB1;RB1',
                                                 'offense_positions': 'QB'}])
            with self.assertRaisesRegex(ValueError, 'offense_players/offense_positions length mismatch'):
                workload._load_historical_participation(root, {}, Counter())


if __name__ == '__main__':
    unittest.main()
