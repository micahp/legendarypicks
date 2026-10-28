import subprocess
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contextual_pool as cp  # noqa: E402
import e1_drive as e1  # noqa: E402
import e2_reference as er  # noqa: E402
import holdout  # noqa: E402
import pregame_context as pc  # noqa: E402
import pregame_snapshot as ps  # noqa: E402
import replay_evaluation as rev  # noqa: E402
import simulate_pregame_batch as batch  # noqa: E402


class HoldoutSeason(unittest.TestCase):
    def test_reference_seasons_exclude_the_holdout(self):
        self.assertEqual(e1.POOL_SEASONS, (2022, 2023, 2024, 2025))
        self.assertEqual(er.KICKOFF_SEASONS, (2022, 2023, 2024, 2025))
        self.assertLess(max(e1.POOL_SEASONS), e1.HOLDOUT_SEASON)

    def test_loaders_return_no_2026_rows_and_refuse_the_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'pbp.sqlite3')
            con = sqlite3.connect(db)
            con.execute(f"CREATE TABLE nfl_pbp ({', '.join(e1.COLUMNS)})")
            for season in (2025, 2026):
                con.execute('INSERT INTO nfl_pbp (game_id, play_id, season, week) VALUES (?, ?, ?, ?)',
                            (f'g{season}', 1, season, 1))
            con.commit()
            con.close()
            self.assertEqual({row['season'] for row in e1.load(db)}, {2025})
            with self.assertRaises(ValueError):
                e1.load(db, eligible_before=(2026, 5))
            with self.assertRaises(ValueError):
                e1.load_seasons(db, (2025, 2026))


class EveryReadPathRefusesTheHoldout(unittest.TestCase):
    def test_guard_refuses_the_holdout_and_passes_earlier_seasons(self):
        holdout.refuse_if_holdout(2025, 'test')
        with self.assertRaises(ValueError):
            holdout.refuse_if_holdout(2026, 'test')
        with self.assertRaises(ValueError):
            holdout.refuse_if_holdout(2027, 'test')

    def test_pregame_context_refuses_a_2026_matchup_before_any_table_is_read(self):
        matchup = {'game_id': '2026_05_AAA_BBB', 'season': 2026, 'week': 5, 'game_type': 'REG',
                   'home_team': 'AAA', 'away_team': 'BBB', 'scheduled_kickoff_utc': '2026-10-11T16:00:00Z'}
        with self.assertRaises(ValueError) as caught:
            pc._require_matchup(matchup, '2026-10-11T12:00:00Z')
        self.assertIn('holdout', str(caught.exception))

    def test_contextual_pool_refuses_2026_rows_before_any_query(self):
        rows = [{'season': 2026, 'week': 1, 'posteam': 'AAA', 'defteam': 'BBB'}]
        with self.assertRaises(ValueError) as caught:
            cp.build_source_ratings(None, rows, ratings_backend=object())
        self.assertIn('holdout', str(caught.exception))

    def test_baseline_v1_refuses_2026_without_opening_the_database(self):
        snapshot = {'as_of': '2026-10-11T12:00:00Z', 'schedule': {
            'game_id': '2026_05_AAA_BBB', 'season': 2026, 'week': 5, 'game_type': 'REG',
            'home_team': 'AAA', 'away_team': 'BBB'}}
        self.assertEqual(batch._baseline_v1('/nonexistent/picks.db', snapshot)['status'], 'unavailable')

    def test_pregame_snapshot_refuses_a_2026_game_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / 'schedule.sqlite3')
            con = sqlite3.connect(db)
            con.execute('CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, game_type TEXT, week INTEGER, '
                        'gameday TEXT, gametime TEXT, away_team TEXT, home_team TEXT, location TEXT, source TEXT, '
                        'ingested_at TEXT)')
            con.execute("INSERT INTO nfl_schedule VALUES ('2026_08_AAA_BBB', 2026, 'REG', 8, '2026-10-29', '20:15', "
                        "'AAA', 'BBB', 'Home', 'test', '2026-10-01 00:00:00')")
            con.commit()
            con.close()
            with self.assertRaises(ValueError) as caught:
                ps.build(db, '2026_08_AAA_BBB', '2026-10-28T12:00:00Z', allow_unverified_current_schedule_exploratory=True)
            self.assertIn('holdout', str(caught.exception))

    def test_replay_evaluation_refuses_a_2026_forecast_payload(self):
        with self.assertRaises(ValueError) as caught:
            rev.forecast_from_batch({'pregame_snapshot': {'schedule': {'season': 2026}}, 'summary': {}})
        self.assertIn('holdout', str(caught.exception))

    def test_run_pinned_validity_refuses_a_2026_target_at_the_command_line(self):
        script = HERE / 'run_pinned_validity.py'
        result = subprocess.run([sys.executable, str(script), '--target-season', '2026', '--policy', 'unconditional',
                                 '--out', '/nonexistent/x.csv', '--summary', '/nonexistent/x.json'],
                                capture_output=True, text=True, timeout=300)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('holdout', result.stderr)

    def test_overtime_check_refuses_before_reading_its_source(self):
        script = HERE / 'build_overtime_choice_model.py'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'model.csv'
            result = subprocess.run([sys.executable, str(script), '--out', str(out)],
                                    capture_output=True, text=True, timeout=300)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('holdout', result.stderr)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
