import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import team_box_build as tbb  # noqa: E402

PLAY = dict(game_id='G1', play_id=0, posteam=None, defteam=None, qtr=1, down=1, ydstogo=10, yardline_100=50,
            game_seconds_remaining=3000, play_type='run', epa=None, success=None, yards_gained=0, complete_pass=0,
            touchdown=0, pass_attempt=0, rush_attempt=0, passing_yards=0, rushing_yards=0, pass_touchdown=0,
            rush_touchdown=0, interception=0, fumble=0, fumble_lost=0, sack=0, two_point_attempt=0, penalty=0,
            penalty_team=None, series_result=None, drive=1)


def play(**kw):
    return dict(PLAY, **kw)


def base(team, opponent, points_for):
    return dict(game_id='G1', season=2020, week=1, game_type='REG', team=team, opponent=opponent, home_away='home',
                points_for=points_for, points_against=None, result=None)


class PenaltyNulls(unittest.TestCase):
    def test_yards_are_null_where_the_penalty_table_has_no_rows(self):
        pen = {('G1', 'KC'): 15}
        self.assertIsNone(tbb.penalty_yards_for(2026, ('G1', 'KC'), pen, {2015, 2016}))
        self.assertIsNone(tbb.penalty_yards_for(2012, ('G1', 'KC'), pen, {2015, 2016}))

    def test_yards_are_zero_only_where_the_table_covers_the_season(self):
        self.assertEqual(tbb.penalty_yards_for(2016, ('G1', 'KC'), {}, {2016}), 0)
        self.assertEqual(tbb.penalty_yards_for(2016, ('G1', 'KC'), {('G1', 'KC'): 15}, {2016}), 15)

    def test_flag_count_is_null_without_play_penalty_flags(self):
        self.assertIsNone(tbb.penalty_flags_for(2026, {2015}, 0))
        self.assertEqual(tbb.penalty_flags_for(2015, {2015}, 2), 2)


class OffensivePointsPerDrive(unittest.TestCase):
    def test_defensive_and_extra_point_points_are_not_offense(self):
        # Team A throws an interception, B returns it for a touchdown and kicks the extra point (7 points to B).
        # B then kicks a field goal on its only drive (3 points). B scored 10 in total, 3 on offense.
        plays = [
            play(play_id=1, posteam='A', defteam='B', play_type='pass', pass_attempt=1, interception=1, touchdown=1,
                 drive=1, qtr=2),
            play(play_id=2, posteam='B', defteam='A', play_type='extra_point', success=1, drive=2, qtr=2),
            play(play_id=3, posteam='B', defteam='A', play_type='field_goal', series_result='Field goal', drive=3,
                 qtr=3),
        ]
        teams, _ = tbb.process_game(plays, fumble_lost_available=True)
        self.assertEqual(teams['B']['st_pts'], 7)
        row = tbb.finish('B', teams['B'], base('B', 'A', 10), True, 0)
        self.assertEqual(row['drives'], 1)
        self.assertEqual(row['points_per_drive'], 3.0)

    def test_a_safety_is_counted_once_per_drive(self):
        # The safety result repeats on every play of its drive. Team B is credited with 2 points, once.
        plays = [
            play(play_id=1, posteam='A', defteam='B', play_type='run', rush_attempt=1, drive=1, qtr=1,
                 series_result='Safety'),
            play(play_id=2, posteam='A', defteam='B', play_type='run', rush_attempt=1, drive=1, qtr=1,
                 series_result='Safety'),
            play(play_id=3, posteam='C', defteam='B', play_type='run', rush_attempt=1, drive=2, qtr=1),
        ]
        teams, _ = tbb.process_game(plays, fumble_lost_available=True)
        self.assertEqual(teams['B']['st_pts'], 2)

    def test_offensive_points_are_unchanged_without_special_teams_scoring(self):
        plays = [
            play(play_id=1, posteam='C', defteam='D', play_type='run', rush_attempt=1, rush_touchdown=1, touchdown=1,
                 drive=1, qtr=1),
            play(play_id=2, posteam='C', defteam='D', play_type='extra_point', success=1, drive=2, qtr=1),
        ]
        teams, _ = tbb.process_game(plays, fumble_lost_available=True)
        self.assertEqual(teams['C'].get('st_pts', 0), 0)
        row = tbb.finish('C', teams['C'], base('C', 'D', 7), True, 0)
        self.assertEqual(row['points_per_drive'], 7.0)


if __name__ == '__main__':
    unittest.main()
