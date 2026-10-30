import csv
import gzip
import tempfile
import unittest
from collections import Counter, defaultdict
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

    def test_team_rush_denominator_keeps_attempt_without_rusher_id(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'pbp.csv'
            fields = ('season_type', 'week', 'game_id', 'play_id', 'posteam', 'play_type', 'pass_attempt',
                      'sack', 'two_point_attempt', 'rush_attempt', 'qb_kneel', 'qb_spike', 'qtr',
                      'quarter_seconds_remaining', 'down', 'ydstogo', 'yardline_100', 'score_differential',
                      'away_score', 'home_score', 'game_date', 'home_team', 'away_team')
            _write_csv(path, fields, [{'season_type': 'REG', 'week': '1', 'game_id': '2022_01_TST_OPP',
                                       'play_id': '1', 'posteam': 'TST', 'play_type': 'no_play',
                                       'pass_attempt': '0', 'sack': '0', 'two_point_attempt': '0',
                                       'rush_attempt': '1', 'qb_kneel': '0', 'qb_spike': '0', 'qtr': '1',
                                       'quarter_seconds_remaining': '900', 'down': '1', 'ydstogo': '10',
                                       'yardline_100': '75', 'score_differential': '0', 'away_score': '0',
                                       'home_score': '0', 'game_date': '2022-09-11', 'home_team': 'TST',
                                       'away_team': 'OPP'}])
            team_games = defaultdict(lambda: Counter(plays=0, pass_attempts=0, sacks=0, rush_attempts=0,
                                                       qb_rush_attempts=0, nonqb_rush_attempts=0,
                                                       unassigned_rush_attempts=0, qb_kneels=0, qb_spikes=0))
            situational = {'team': Counter(), 'player': Counter()}
            workload._ingest_pbp(path, 2022, players={}, roster_2026={}, eligible={}, positions={},
                                 player_games={}, team_games=team_games, game_context={},
                                 situational=situational, source_counts=Counter(), game_keys=set())

            stats = team_games[('2022_01_TST_OPP', 'TST')]
            self.assertEqual(stats['rush_attempts'], 1)
            self.assertEqual(stats['unassigned_rush_attempts'], 1)
            self.assertEqual(sum(situational['team'].values()), 1)


if __name__ == '__main__':
    unittest.main()
