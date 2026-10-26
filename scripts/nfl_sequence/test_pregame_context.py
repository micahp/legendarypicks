import sqlite3
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pregame_context as pc  # noqa: E402


class FakeRatingsBackend:
    @staticmethod
    def teams_in_season(_con, _season):
        return ['AAA', 'BBB', 'CCC', 'DDD']

    @staticmethod
    def prior_for_season(_con, _season, **_kwargs):
        return {'AAA': (1.0, -1.0), 'BBB': (-1.0, 1.0), 'CCC': (0.5, 0.5), 'DDD': (-0.5, -0.5)}

    @staticmethod
    def fit_for_week(_con, _season, _week, **_kwargs):
        fit = SimpleNamespace(o={'AAA': 4.0, 'BBB': -1.0, 'CCC': 0.5, 'DDD': -0.5},
                              d={'AAA': -2.0, 'BBB': 1.0, 'CCC': 0.5, 'DDD': -0.5})
        return fit, 2


def add_game(con, game_id, season, week, home, away, home_score, away_score, gameday):
    con.execute('INSERT INTO nfl_schedule VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (game_id, season, week, 'REG', home, away, home_score, away_score, 'Home', gameday))
    for team in (home, away):
        con.execute('INSERT INTO nfl_pbp VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (game_id, 1, team, 'pass', 1, 0, 8, 0.4, 0, 0))
        con.execute('INSERT INTO nfl_pbp VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (game_id, 2, team, 'run', 0, 1, 4, -0.1, 0, 0))


class PregameContext(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.execute('CREATE TABLE nfl_schedule (game_id TEXT, season INTEGER, week INTEGER, game_type TEXT, '
                         'home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER, '
                         'location TEXT, gameday TEXT)')
        self.con.execute('CREATE TABLE nfl_pbp (game_id TEXT, play_id INTEGER, posteam TEXT, play_type TEXT, '
                         'pass_attempt INTEGER, rush_attempt INTEGER, yards_gained REAL, epa REAL, '
                         'penalty INTEGER, two_point_attempt INTEGER)')
        add_game(self.con, '2025_01_AAA_BBB', 2025, 1, 'AAA', 'BBB', 24, 10, '2025-09-07')
        add_game(self.con, '2025_01_CCC_DDD', 2025, 1, 'CCC', 'DDD', 14, 20, '2025-09-07')
        add_game(self.con, '2025_02_AAA_CCC', 2025, 2, 'AAA', 'CCC', 21, 20, '2025-09-14')
        add_game(self.con, '2025_02_BBB_DDD', 2025, 2, 'BBB', 'DDD', 17, 13, '2025-09-14')
        add_game(self.con, '2026_01_AAA_BBB', 2026, 1, 'AAA', 'BBB', 35, 10, '2026-09-06')
        # A completed same-week row is deliberately present; a Week 2 snapshot must not see it.
        add_game(self.con, '2026_02_AAA_DDD', 2026, 2, 'AAA', 'DDD', 10, 20, '2026-09-13')

    def tearDown(self):
        self.con.close()

    def matchup(self, week):
        return {'game_id': f'2026_{week:02d}_AAA_DDD', 'season': 2026, 'week': week, 'game_type': 'REG',
                'home_team': 'AAA', 'away_team': 'DDD', 'location': 'Home',
                'scheduled_kickoff_utc': f'2026-09-{6 + 7 * (week - 1):02d}T16:00:00Z'}

    def test_weekly_context_uses_prior_weeks_and_never_current_week_results(self):
        week1 = pc.build_from_connection(self.con, self.matchup(1), '2026-09-06T12:00:00Z',
                                         ratings_backend=FakeRatingsBackend)
        week2 = pc.build_from_connection(self.con, self.matchup(2), '2026-09-13T12:00:00Z',
                                         ratings_backend=FakeRatingsBackend)
        home1 = week1['teams']['home']
        home2 = week2['teams']['home']
        self.assertEqual(home1['record_before_game']['games'], 0)
        self.assertEqual(home2['record_before_game']['wins'], 1)
        self.assertEqual(home2['recent_form']['last_3']['game_ids'][-1], '2026_01_AAA_BBB')
        self.assertNotIn('2026_02_AAA_DDD', home2['recent_form']['last_3']['game_ids'])
        self.assertNotEqual(home1['opponent_adjusted']['offense_points_rating'],
                            home2['opponent_adjusted']['offense_points_rating'])
        self.assertEqual(week2['source_manifest']['availability']['classification'], 'chronological_filter_only')

    def test_context_hash_is_repeatable_and_pins_both_input_slices(self):
        args = (self.con, self.matchup(2), '2026-09-13T12:00:00Z')
        one = pc.build_from_connection(*args, ratings_backend=FakeRatingsBackend)
        two = pc.build_from_connection(*args, ratings_backend=FakeRatingsBackend)
        self.assertEqual(one['context_sha256'], two['context_sha256'])
        self.assertEqual(one['source_manifest']['schedule_input'], two['source_manifest']['schedule_input'])
        self.assertEqual(one['source_manifest']['play_by_play_input'], two['source_manifest']['play_by_play_input'])
        self.assertGreater(one['source_manifest']['play_by_play_input']['rows'], 0)

    def test_verified_starter_is_carried_only_with_full_depth_provenance(self):
        snapshot = {'snapshot_sha256': 'a' * 64, 'roster_snapshot_id': 'roster-1',
                    'roster_snapshot_source': {'full_depth_roster_sha256': 'b' * 64},
                    'rosters': {'home': {'players': [{'player_id': 11, 'gsis_id': 'QB1', 'pos_abb': 'QB',
                                                     'pos_rank': 1, 'starter': True, 'jersey_number': 15}]},
                                'away': {'players': []}}}
        context = pc.build_from_connection(self.con, self.matchup(2), '2026-09-13T12:00:00Z', snapshot,
                                           ratings_backend=FakeRatingsBackend)
        personnel = context['teams']['home']['personnel']
        self.assertEqual(personnel['status'], 'verified_full_depth')
        self.assertEqual(personnel['starting_qb']['jersey_number'], 15)

    def test_cutoff_must_be_timezone_aware_and_before_kickoff(self):
        with self.assertRaisesRegex(ValueError, 'timezone'):
            pc.build_from_connection(self.con, self.matchup(2), '2026-09-13T12:00:00',
                                     ratings_backend=FakeRatingsBackend)
        with self.assertRaisesRegex(ValueError, 'precede scheduled kickoff'):
            pc.build_from_connection(self.con, self.matchup(2), '2026-09-13T17:00:00Z',
                                     ratings_backend=FakeRatingsBackend)


if __name__ == '__main__':
    unittest.main()
