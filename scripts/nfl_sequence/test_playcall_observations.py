import gzip
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import playcall_observations as pco  # noqa: E402


def NO_SCORES(season):
    return {}


def play(**overrides):
    row = {column: None for column in pco.COLUMNS}
    row.update({'game_id': '2012_01_AAA_BBB', 'play_id': 1, 'season': 2012, 'week': 1, 'posteam': 'AAA', 'defteam': 'BBB',
                'home_team': 'BBB', 'away_team': 'AAA', 'qtr': 1, 'down': 1, 'ydstogo': 10, 'yardline_100': 50,
                'game_seconds_remaining': 3000, 'play_type': 'run', 'yards_gained': 4, 'pass_attempt': 0,
                'rush_attempt': 1, 'qb_dropback': 0, 'sack': 0, 'qb_scramble': 0, 'two_point_attempt': 0,
                'shotgun': 0, 'no_huddle': 0, 'touchdown': 0, 'interception': 0, 'fumble_lost': 0,
                'complete_pass': None})
    row.update(overrides)
    return row


def database(rows):
    tmp = tempfile.TemporaryDirectory()
    path = str(Path(tmp.name) / 'pbp.sqlite3')
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE nfl_pbp ({', '.join(pco.COLUMNS)})")
    for row in rows:
        con.execute(f"INSERT INTO nfl_pbp ({', '.join(pco.COLUMNS)}) VALUES ({', '.join('?' for _ in pco.COLUMNS)})",
                    [row[c] for c in pco.COLUMNS])
    con.commit()
    con.close()
    return tmp, path


class Classification(unittest.TestCase):
    def test_designed_run_and_pass_are_their_own_intents(self):
        self.assertEqual(pco.classify(play())[0], 'run')
        self.assertEqual(pco.classify(play(play_type='pass', pass_attempt=1, rush_attempt=0, complete_pass=1))[0],
                         'dropback')

    def test_sacks_and_scrambles_stay_dropbacks_with_their_outcome_flags(self):
        sack = pco.observation(play(play_type='pass', pass_attempt=0, rush_attempt=0, sack=1, yards_gained=-7))
        scramble = pco.observation(play(play_type='run', rush_attempt=1, qb_scramble=1, yards_gained=6))
        self.assertEqual((sack['intent'], sack['sack']), ('dropback', 1))
        self.assertEqual((scramble['intent'], scramble['scramble']), ('dropback', 1))

    def test_kneel_spike_and_two_point_are_separate_intents(self):
        self.assertEqual(pco.classify(play(play_type='qb_kneel'))[0], 'kneel')
        self.assertEqual(pco.classify(play(play_type='qb_spike'))[0], 'spike')
        self.assertEqual(pco.classify(play(play_type='pass', two_point_attempt=1))[0], 'two_point')

    def test_fourth_down_decisions_are_recorded_by_state(self):
        self.assertEqual(pco.classify(play(down=4, play_type='punt'))[1], 'punt')
        self.assertEqual(pco.classify(play(down=4, play_type='field_goal'))[1], 'field_goal')
        self.assertEqual(pco.classify(play(down=4, play_type='run'))[1], 'go_for_it')
        self.assertIsNone(pco.classify(play(down=3, play_type='punt'))[1])

    def test_a_missing_play_type_stays_unknown_and_is_not_guessed(self):
        self.assertEqual(pco.classify(play(play_type=None))[0], 'unknown')


class ExactState(unittest.TestCase):
    def test_exact_fields_are_kept_and_missing_values_stay_missing(self):
        obs = pco.observation(play(down=None, ydstogo=None, yardline_100=None, game_seconds_remaining=None, qtr=None))
        self.assertIsNone(obs['down'])
        self.assertIsNone(obs['ydstogo'])
        self.assertIsNone(obs['game_seconds_remaining'])
        self.assertIsNone(obs['seconds_in_quarter'])
        self.assertFalse(obs['two_minute_window'])

    def test_quarter_boundary_and_seconds_in_quarter(self):
        q2_end = pco.observation(play(qtr=2, game_seconds_remaining=1800))
        q3_start = pco.observation(play(qtr=3, game_seconds_remaining=1800))
        self.assertEqual(q2_end['seconds_in_quarter'], 0)
        self.assertEqual(q3_start['seconds_in_quarter'], 900)

    def test_two_minute_window_is_end_of_half_only(self):
        self.assertTrue(pco.observation(play(qtr=2, game_seconds_remaining=1800 + 120))['two_minute_window'])
        self.assertFalse(pco.observation(play(qtr=2, game_seconds_remaining=1800 + 121))['two_minute_window'])
        self.assertTrue(pco.observation(play(qtr=4, game_seconds_remaining=120))['two_minute_window'])
        self.assertFalse(pco.observation(play(qtr=1, game_seconds_remaining=100))['two_minute_window'])

    def test_goal_to_go_comes_from_the_verified_raw_flag_not_distance(self):
        scores = {'posteam_score': 7, 'defteam_score': 0, 'score_differential': 7, 'goal_to_go': 1}
        self.assertTrue(pco.observation(play(yardline_100=8), scores)['goal_to_go'])
        second_and_two = play(down=2, ydstogo=2, yardline_100=8)
        self.assertFalse(pco.observation(second_and_two, {**scores, 'goal_to_go': 0})['goal_to_go'])

    def test_goal_to_go_is_unknown_without_the_raw_flag(self):
        self.assertIsNone(pco.observation(play(yardline_100=8))['goal_to_go'])
        self.assertEqual(pco.observation(play(yardline_100=8))['goal_to_go_status'], 'unavailable')

    def test_red_zone_is_kept_separate_from_goal_to_go(self):
        scores = {'posteam_score': 3, 'defteam_score': 0, 'score_differential': 3, 'goal_to_go': 0}
        obs = pco.observation(play(yardline_100=15), scores)
        self.assertTrue(obs['red_zone'])
        self.assertFalse(obs['goal_to_go'])
        self.assertFalse(pco.observation(play(yardline_100=25))['red_zone'])

    def test_overtime_is_flagged_and_has_no_regulation_clock(self):
        obs = pco.observation(play(qtr=5, game_seconds_remaining=400))
        self.assertTrue(obs['overtime'])
        self.assertIsNone(obs['seconds_in_quarter'])

    def test_score_differential_is_explicitly_unavailable(self):
        obs = pco.observation(play())
        self.assertIsNone(obs['score_differential'])
        self.assertEqual(obs['score_status'], 'unmatched_in_raw')


class CutoffAndHoldout(unittest.TestCase):
    def setUp(self):
        self.rows = [play(game_id='2012_05_AAA_BBB', play_id=1, season=2012, week=5),
                     play(game_id='2012_06_AAA_BBB', play_id=1, season=2012, week=6),
                     play(game_id='2012_07_AAA_BBB', play_id=1, season=2012, week=7)]
        self.tmp, self.db = database(self.rows)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_cutoff_excludes_its_own_week_and_later_games(self):
        before = [o['game_id'] for o in pco.observations(self.db, cutoff=(2012, 6), scores=NO_SCORES)]
        self.assertEqual(before, ['2012_05_AAA_BBB'])

    def test_a_later_game_cannot_change_an_earlier_observation(self):
        with_later = {o['game_id']: o for o in pco.observations(self.db, cutoff=(2012, 7), scores=NO_SCORES)}
        without_later = {o['game_id']: o for o in pco.observations(self.db, cutoff=(2012, 6), scores=NO_SCORES)}
        self.assertEqual(with_later['2012_05_AAA_BBB'], without_later['2012_05_AAA_BBB'])

    def test_the_holdout_season_is_refused_before_any_query(self):
        with self.assertRaises(ValueError) as caught:
            list(pco.observations(self.db, last_season=2026))
        self.assertIn('holdout', str(caught.exception))

    def test_older_pbp_without_ftn_or_ngs_is_still_observed(self):
        rows = list(pco.observations(self.db, first_season=2010, last_season=2012, scores=NO_SCORES))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r['provenance']['source'] == 'nfl_pbp' for r in rows))


class PreplayScores(unittest.TestCase):
    def test_a_matched_play_carries_exact_pre_play_scores_and_their_difference(self):
        obs = pco.observation(play(), {'posteam_score': 14, 'defteam_score': 7, 'score_differential': 7})
        self.assertEqual((obs['posteam_score_pre'], obs['defteam_score_pre'], obs['score_differential']), (14, 7, 7))
        self.assertEqual(obs['score_status'], 'pre_play_nflverse_raw')

    def test_a_trailing_team_has_a_negative_difference(self):
        obs = pco.observation(play(), {'posteam_score': 3, 'defteam_score': 10, 'score_differential': -7})
        self.assertEqual(obs['score_differential'], -7)

    def test_a_no_play_row_drops_its_scores_because_they_are_not_pre_play_state(self):
        obs = pco.observation(play(play_type='no_play', rush_attempt=0), {'posteam_score': 14, 'defteam_score': 7})
        self.assertIsNone(obs['score_differential'])
        self.assertEqual(obs['score_status'], 'excluded_no_play_row')

    def test_an_empty_raw_score_is_missing_not_zero(self):
        obs = pco.observation(play(), {'posteam_score': None, 'defteam_score': 7})
        self.assertIsNone(obs['score_differential'])
        self.assertEqual(obs['score_status'], 'raw_score_missing')

    def test_the_raw_file_is_refused_unless_its_checksum_is_the_pinned_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pbp_2012.csv.gz'
            with gzip.open(path, 'wt', newline='') as f:
                f.write('game_id,play_id,season_type,week,posteam_score,defteam_score,score_differential,goal_to_go\n')
                f.write('2012_05_AAA_BBB,1,REG,5,14,7,7,1\n')
            real = pco.sha256(path)
            scores = pco.load_pre_play_scores(path, real)
            self.assertEqual(scores[('2012_05_AAA_BBB', 1)], {'posteam_score': 14, 'defteam_score': 7,
                                                              'score_differential': 7, 'goal_to_go': 1})
            with self.assertRaises(ValueError):
                pco.load_pre_play_scores(path, '0' * 64)

    def test_observations_join_scores_on_game_and_play(self):
        rows = [play(game_id='2012_05_AAA_BBB', play_id=1, season=2012, week=5),
                play(game_id='2012_05_AAA_BBB', play_id=2, season=2012, week=5)]
        tmp, db = database(rows)
        try:
            joined = {('2012_05_AAA_BBB', 1): {'posteam_score': 21, 'defteam_score': 14, 'score_differential': 7}}
            out = {o['play_id']: o for o in pco.observations(db, first_season=2012, last_season=2012,
                                                             scores=lambda s: joined)}
            self.assertEqual(out[1]['score_differential'], 7)
            self.assertEqual(out[2]['score_status'], 'unmatched_in_raw')
        finally:
            tmp.cleanup()


class ScoreFlags(unittest.TestCase):
    def test_a_flagged_play_keeps_its_score_and_is_labelled(self):
        scores = {'posteam_score': 7, 'defteam_score': 0, 'score_differential': 7, 'goal_to_go': 0}
        obs = pco.observation(play(), scores, score_flag='unexplained_single_side')
        self.assertEqual(obs['score_status'], 'flagged_continuity_exception')
        self.assertEqual(obs['score_differential'], 7)
        self.assertEqual(obs['score_flag'], 'unexplained_single_side')

    def test_an_unflagged_play_is_unchanged(self):
        scores = {'posteam_score': 7, 'defteam_score': 0, 'score_differential': 7, 'goal_to_go': 0}
        obs = pco.observation(play(), scores)
        self.assertEqual(obs['score_status'], 'pre_play_nflverse_raw')
        self.assertIsNone(obs['score_flag'])

    def test_observations_apply_the_flag_to_the_matching_play_only(self):
        rows = [play(game_id='2012_05_AAA_BBB', play_id=1, season=2012, week=5),
                play(game_id='2012_05_AAA_BBB', play_id=2, season=2012, week=5)]
        tmp, db = database(rows)
        try:
            joined = {('2012_05_AAA_BBB', 1): {'posteam_score': 7, 'defteam_score': 0, 'score_differential': 7,
                                               'goal_to_go': 0},
                      ('2012_05_AAA_BBB', 2): {'posteam_score': 7, 'defteam_score': 0, 'score_differential': 7,
                                               'goal_to_go': 0}}
            out = {o['play_id']: o for o in pco.observations(db, first_season=2012, last_season=2012,
                                                             scores=lambda s: joined,
                                                             flags={('2012_05_AAA_BBB', 2): 'offense_3.0_field_goal'})}
            self.assertEqual(out[1]['score_status'], 'pre_play_nflverse_raw')
            self.assertEqual(out[2]['score_status'], 'flagged_continuity_exception')
        finally:
            tmp.cleanup()

    def test_the_committed_flag_file_has_one_row_per_flagged_play(self):
        flags = pco.load_score_flags()
        self.assertEqual(len(flags), 121)
        self.assertTrue(set(flags.values()) <= {'unexplained_single_side', 'both_sides_changed',
                                                'stale_repeat_of_state_before_previous_play'}
                        | {l for l in flags.values() if l.startswith(('offense_', 'defense_'))})


if __name__ == '__main__':
    unittest.main()
