import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pregame_batch  # noqa: E402
import simulate_pregame_batch as batch  # noqa: E402


class BatchAggregation(unittest.TestCase):
    def test_batch_receiver_only_flag_is_opt_in_and_requires_player_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / 'snapshot.json'
            artifact = Path(tmp) / 'artifact.json'
            snapshot.write_text('{}')
            artifact.write_text('{}')
            common = ['--snapshot-file', str(snapshot), '--games', '1', '--seed-start', '1', '--out', 'out.json',
                      '--playcall-artifact', str(artifact)]
            with patch.object(batch, 'run_batch') as run_batch:
                batch.main(common + ['--playcall-player-outcomes', '--playcall-player-outcomes-receiver-only'])
            self.assertTrue(run_batch.call_args.args[0].playcall_player_outcomes_receiver_only)

            with patch.object(batch, 'run_batch') as run_batch:
                with self.assertRaises(SystemExit):
                    batch.main(common + ['--playcall-player-outcomes-receiver-only'])
            run_batch.assert_not_called()

    def test_player_template_keeps_full_depth_backup_roles(self):
        snapshot = {
            'rosters': {
                'home': {'team': 'SEA', 'players': [
                    {'gsis_id': 'sea-rb1', 'player_name': 'RB One', 'pos_abb': 'RB', 'pos_rank': 1,
                     'group': '3WR 1TE', 'starter': True},
                    {'gsis_id': 'sea-rb2', 'player_name': 'RB Two', 'pos_abb': 'RB', 'pos_rank': 2,
                     'group': '3WR 1TE', 'starter': False},
                    {'gsis_id': 'sea-rb1', 'player_name': 'RB One', 'pos_abb': 'KR', 'pos_rank': 1,
                     'group': 'Special Teams', 'starter': False},
                ]},
                'away': {'team': 'KC', 'players': []},
            },
        }
        players = batch._player_template(snapshot)
        self.assertFalse(players['sea-rb2']['starter'])
        self.assertEqual(players['sea-rb2']['position'], 'RB')
        self.assertEqual(players['sea-rb1']['position'], 'RB')
        self.assertEqual(len(players['sea-rb1']['roster_roles']), 2)
        self.assertEqual(len(players), 2)

    def test_player_template_labels_legacy_depth_chart_roles_without_inventing_a_group(self):
        snapshot = {'rosters': {
            'home': {'team': 'SF', 'players': [{'gsis_id': 'sf-qb', 'player_name': 'QB',
                                                  'pos_abb': 'QB', 'pos_rank': 1}]},
            'away': {'team': 'WSH', 'players': []},
        }}
        players = batch._player_template(snapshot)
        self.assertEqual(players['sf-qb']['roster_roles'][0]['group'], 'unclassified')
        self.assertTrue(players['sf-qb']['starter'])

    def test_all_seeds_are_retained_and_ties_are_in_regulation_distribution(self):
        rows = [
            {'seed': 1, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 10, 'away_points': 7},
            {'seed': 2, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 7, 'away_points': 10},
            {'seed': 3, 'status': 'blocked', 'blocker': 'overtime_not_modelled', 'valid_full_game': False,
             'complete_game': False, 'regulation_end_reached': True, 'tied_at_regulation_end': True,
             'home_points': 14, 'away_points': 14},
            {'seed': 4, 'status': 'blocked', 'blocker': 'thin_pool_cell', 'valid_full_game': False,
             'complete_game': False, 'regulation_end_reached': False, 'tied_at_regulation_end': False,
             'home_points': 3, 'away_points': 3},
        ]
        report = pregame_batch.summarize_outcomes(rows, 4, home_market_margin=0, market_total=17)
        self.assertEqual(report['requested_games'], 4)
        self.assertEqual(len(report['outcomes']), 4)
        self.assertEqual(report['valid_full_games'], 2)
        self.assertEqual(report['tied_at_regulation_end'], 1)
        self.assertEqual(report['blocked_before_regulation_end'], 1)
        self.assertEqual(report['valid_full_game_distribution']['scores']['home']['mean'], 8.5)
        self.assertEqual(report['valid_full_game_distribution']['home_minus_away']['mean'], 0)
        self.assertEqual(report['regulation_end_reached_distribution']['sample_games'], 3)
        self.assertAlmostEqual(report['regulation_end_reached_distribution']['win_probability']['tie'], 1 / 3, places=4)
        self.assertEqual(report['blocker_counts'], {'overtime_not_modelled': 1, 'thin_pool_cell': 1})

    def test_market_pushes_and_missing_valid_samples_are_explicit(self):
        rows = [
            {'seed': 10, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 20, 'away_points': 17},
            {'seed': 11, 'status': 'complete_regulation', 'valid_full_game': True, 'complete_game': True,
             'regulation_end_reached': True, 'tied_at_regulation_end': False, 'home_points': 20, 'away_points': 17},
        ]
        report = pregame_batch.summarize_outcomes(rows, 2, home_market_margin=3, market_total=37)
        settlement = report['valid_full_game_distribution']['market_settlement']
        self.assertEqual(settlement['spread_push_probability'], 1)
        self.assertEqual(settlement['total_push_probability'], 1)
        self.assertEqual(report['valid_full_game_distribution']['most_frequent_exact_score']['probability'], 1)

        blocked = [{'seed': 4, 'status': 'blocked', 'blocker': 'missing_pool', 'valid_full_game': False,
                    'complete_game': False, 'regulation_end_reached': False,
                    'tied_at_regulation_end': False, 'home_points': 0, 'away_points': 0}]
        report = pregame_batch.summarize_outcomes(blocked, 1)
        self.assertEqual(report['valid_full_game_distribution']['sample_games'], 0)
        self.assertEqual(report['valid_full_game_distribution']['scores'], None)

    def test_refuses_missing_or_duplicate_seed_rows(self):
        with self.assertRaisesRegex(ValueError, 'explicit seed outcomes'):
            pregame_batch.summarize_outcomes([], 1)
        with self.assertRaisesRegex(ValueError, 'unique integer seed'):
            pregame_batch.summarize_outcomes([{'seed': 3}, {'seed': 3}], 2)

    def test_regulation_tie_is_not_misreported_as_a_partial_game(self):
        result = batch._record_outcome(12, {
            'status': 'blocked', 'blocker': 'overtime_not_modelled', 'tied': True,
            'regulation_end_reached': False, 'final_quarter': 4, 'final_clock_seconds': 0,
            'complete_game': False, 'valid_full_game': False, 'points': {'A': 24, 'B': 24},
        })
        self.assertTrue(result['regulation_end_reached'])
        self.assertTrue(result['tied_at_regulation_end'])
        self.assertIsNone(result['final_tie'])
        self.assertEqual(result['score_scope'], 'regulation_end_only')

    def test_overtime_final_tie_is_not_misclassified_as_a_regulation_tie(self):
        result = batch._record_outcome(13, {
            'status': 'complete_overtime', 'blocker': None, 'tied': True,
            'regulation_end_reached': True, 'final_quarter': 5, 'final_clock_seconds': 0,
            'complete_game': True, 'valid_full_game': True, 'points': {'A': 24, 'B': 24},
        })

        self.assertFalse(result['tied_at_regulation_end'])
        self.assertTrue(result['final_tie'])
        report = pregame_batch.summarize_outcomes([result], 1)
        self.assertEqual(report['valid_full_games'], 1)
        self.assertEqual(report['tied_at_regulation_end'], 0)
        self.assertEqual(report['final_ties'], 1)

    def test_v1_lock_after_the_simulation_cutoff_is_exploratory(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'locks.db'
            con = sqlite3.connect(db)
            con.executescript('''
                CREATE TABLE game_projections (run_id TEXT, model_version TEXT, proj_home REAL, proj_away REAL,
                    proj_margin REAL, proj_total REAL, p_home_win REAL, locked_at TEXT, home TEXT, away TEXT,
                    season INTEGER, week INTEGER, league TEXT, game_id TEXT, locked INTEGER);
                CREATE TABLE model_runs (run_id TEXT, status TEXT, model TEXT, started_at TEXT, params_json TEXT);
                CREATE TABLE nfl_schedule_versions (game_id TEXT, season INTEGER, game_type TEXT, week INTEGER,
                    gameday TEXT, gametime TEXT, away_team TEXT, home_team TEXT, location TEXT, source TEXT,
                    observed_at TEXT);
            ''')
            con.execute('INSERT INTO game_projections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('r1', 'nfl-v1 frozen', 21.0, 17.0, 4.0, 38.0, 0.61,
                         '2025-10-11T12:00:00Z', 'A', 'B', 2025, 5, 'nfl', '2025_05_A_B', 1))
            con.execute('INSERT INTO model_runs VALUES (?, ?, ?, ?, ?)',
                        ('r1', 'ok', 'nfl-ratings-v1', '2025-10-11T11:59:00Z', '{}'))
            con.execute('INSERT INTO nfl_schedule_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('2025_05_A_B', 2025, 'REG', 5, '2025-10-11', '12:00', 'B', 'A', 'Home',
                         'test fixture', '2025-10-10 10:00:00'))
            con.commit()
            con.close()

            snapshot = {'as_of': '2025-10-11T11:00:00Z', 'schedule': {
                'game_id': '2025_05_A_B', 'season': 2025, 'week': 5, 'game_type': 'REG',
                'home_team': 'A', 'away_team': 'B',
                'scheduled_kickoff_utc': '2025-10-11T16:00:00Z'}}
            later = batch._baseline_v1(str(db), snapshot)
            self.assertEqual(later['status'], 'exploratory_later_lock')
            self.assertFalse(later['comparable_at_snapshot_cutoff'])
            self.assertGreater(later['snapshot_cutoff_offset_seconds'], 0)

            snapshot['as_of'] = '2025-10-11T12:00:00Z'
            aligned = batch._baseline_v1(str(db), snapshot)
            self.assertEqual(aligned['status'], 'available')
            self.assertTrue(aligned['comparable_at_snapshot_cutoff'])

    def test_enabled_layers_without_runtime_counters_fail_closed(self):
        manifest = {'enabled_layers': {'new_layer': True}, 'layers': {}}

        with self.assertRaisesRegex(RuntimeError, 'no runtime counter'):
            batch._execution_verification([], manifest)

    def test_disabled_layer_without_runtime_counter_does_not_block_report(self):
        manifest = {'enabled_layers': {'future_layer': False}, 'layers': {}}

        report = batch._execution_verification([], manifest)

        self.assertEqual(report['layers']['future_layer'], {
            'enabled': False, 'runtime_applications': 0, 'status': 'not_enabled'})

    def test_disabled_layer_with_runtime_applications_fails_closed(self):
        manifest = {'enabled_layers': {'fixed_player_target_carry_shares': False}, 'layers': {}}
        outcomes = [{'playcall': {'layer_execution': {'fixed_player_target_carry_shares': 1}}}]

        with self.assertRaisesRegex(RuntimeError, 'disabled SLC layers reported runtime applications'):
            batch._execution_verification(outcomes, manifest)

    def test_fixed_share_application_is_reported_as_executed_when_enabled(self):
        manifest = {'enabled_layers': {'fixed_player_target_carry_shares': True}, 'layers': {}}
        outcomes = [{'playcall': {'layer_execution': {'fixed_player_target_carry_shares': 1}}}]

        report = batch._execution_verification(outcomes, manifest)

        self.assertEqual(report['layers']['fixed_player_target_carry_shares'], {
            'enabled': True, 'runtime_applications': 1, 'status': 'executed'})

    def test_uses_latest_v1_lock_at_or_before_cutoff_when_a_later_lock_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'locks.db'
            con = sqlite3.connect(db)
            con.executescript('''
                CREATE TABLE game_projections (run_id TEXT, model_version TEXT, proj_home REAL, proj_away REAL,
                    proj_margin REAL, proj_total REAL, p_home_win REAL, locked_at TEXT, home TEXT, away TEXT,
                    season INTEGER, week INTEGER, league TEXT, game_id TEXT, locked INTEGER);
                CREATE TABLE model_runs (run_id TEXT, status TEXT, model TEXT, started_at TEXT, params_json TEXT);
                CREATE TABLE nfl_schedule_versions (game_id TEXT, season INTEGER, game_type TEXT, week INTEGER,
                    gameday TEXT, gametime TEXT, away_team TEXT, home_team TEXT, location TEXT, source TEXT,
                    observed_at TEXT);
            ''')
            for run_id, locked_at, home_points in (
                    ('r-before', '2025-10-11T10:00:00Z', 21.0),
                    ('r-after', '2025-10-11T12:00:00Z', 25.0)):
                con.execute('INSERT INTO game_projections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            (run_id, 'nfl-v1 frozen', home_points, 17.0, home_points - 17.0,
                             home_points + 17.0, 0.61, locked_at, 'A', 'B', 2025, 5, 'nfl',
                             '2025_05_A_B', 1))
                con.execute('INSERT INTO model_runs VALUES (?, ?, ?, ?, ?)',
                            (run_id, 'ok', 'nfl-ratings-v1', locked_at, '{}'))
            con.execute('INSERT INTO nfl_schedule_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('2025_05_A_B', 2025, 'REG', 5, '2025-10-11', '12:00', 'B', 'A', 'Home',
                         'test fixture', '2025-10-10 10:00:00'))
            con.commit()
            con.close()

            snapshot = {'as_of': '2025-10-11T11:00:00Z', 'schedule': {
                'game_id': '2025_05_A_B', 'season': 2025, 'week': 5, 'game_type': 'REG',
                'home_team': 'A', 'away_team': 'B',
                'scheduled_kickoff_utc': '2025-10-11T16:00:00Z'}}
            result = batch._baseline_v1(str(db), snapshot)
            self.assertEqual(result['status'], 'available')
            self.assertEqual(result['run_id'], 'r-before')
            self.assertEqual(result['projected_home_points'], 21.0)

    def test_hash_pinned_schedule_timestamp_allows_exploratory_later_lock_report_without_history_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'locks.db'
            con = sqlite3.connect(db)
            con.executescript('''
                CREATE TABLE game_projections (run_id TEXT, model_version TEXT, proj_home REAL, proj_away REAL,
                    proj_margin REAL, proj_total REAL, p_home_win REAL, locked_at TEXT, home TEXT, away TEXT,
                    season INTEGER, week INTEGER, league TEXT, game_id TEXT, locked INTEGER);
                CREATE TABLE model_runs (run_id TEXT, status TEXT, model TEXT, started_at TEXT, params_json TEXT);
            ''')
            con.execute('INSERT INTO game_projections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('r1', 'nfl-v1 frozen', 21.0, 17.0, 4.0, 38.0, 0.61,
                         '2025-10-11T12:00:00Z', 'A', 'B', 2025, 5, 'nfl', '2025_05_A_B', 1))
            con.execute('INSERT INTO model_runs VALUES (?, ?, ?, ?, ?)',
                        ('r1', 'ok', 'nfl-ratings-v1', '2025-10-11T12:00:00Z', '{}'))
            con.commit()
            con.close()

            snapshot = {'as_of': '2025-10-11T11:00:00Z', 'schedule': {
                'game_id': '2025_05_A_B', 'season': 2025, 'week': 5, 'game_type': 'REG',
                'home_team': 'A', 'away_team': 'B', 'location': 'Home', 'gameday': '2025-10-11',
                'ingested_at': '2025-10-10 10:00:00', 'scheduled_kickoff_utc': '2025-10-11T16:00:00Z'}}
            result = batch._baseline_v1(str(db), snapshot)
            self.assertEqual(result['status'], 'exploratory_later_lock')
            self.assertEqual(result['run_id'], 'r1')
            self.assertFalse(result['comparable_at_snapshot_cutoff'])
            self.assertTrue(result['schedule_provenance']['verified'])
            self.assertEqual(result['schedule_provenance']['source'], 'hash_pinned_snapshot_schedule_version')

    def test_pre_cutoff_v1_lock_is_retained_as_exploratory_when_schedule_version_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'locks.db'
            con = sqlite3.connect(db)
            con.executescript('''
                CREATE TABLE game_projections (run_id TEXT, model_version TEXT, proj_home REAL, proj_away REAL,
                    proj_margin REAL, proj_total REAL, p_home_win REAL, locked_at TEXT, home TEXT, away TEXT,
                    season INTEGER, week INTEGER, league TEXT, game_id TEXT, locked INTEGER);
                CREATE TABLE model_runs (run_id TEXT, status TEXT, model TEXT, started_at TEXT, params_json TEXT);
            ''')
            con.execute('INSERT INTO game_projections VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                        ('r1', 'nfl-v1 frozen', 21.0, 17.0, 4.0, 38.0, 0.61,
                         '2025-10-11T10:00:00Z', 'A', 'B', 2025, 5, 'nfl', '2025_05_A_B', 1))
            con.execute('INSERT INTO model_runs VALUES (?, ?, ?, ?, ?)',
                        ('r1', 'ok', 'nfl-ratings-v1', '2025-10-11T10:00:00Z', '{}'))
            con.commit()
            con.close()

            snapshot = {'as_of': '2025-10-11T11:00:00Z', 'schedule': {
                'game_id': '2025_05_A_B', 'season': 2025, 'week': 5, 'game_type': 'REG',
                'home_team': 'A', 'away_team': 'B', 'location': 'Home', 'gameday': '2025-10-11',
                'ingested_at': '2025-10-26 10:00:01', 'scheduled_kickoff_utc': '2025-10-11T16:00:00Z'}}
            result = batch._baseline_v1(str(db), snapshot)
            self.assertEqual(result['status'], 'exploratory_schedule_unverified')
            self.assertEqual(result['run_id'], 'r1')
            self.assertFalse(result['comparable_at_snapshot_cutoff'])
            self.assertFalse(result['schedule_provenance']['verified'])
            self.assertLessEqual(result['snapshot_cutoff_offset_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
