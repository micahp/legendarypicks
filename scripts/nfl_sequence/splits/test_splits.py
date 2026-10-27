import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import layer  # noqa: E402
import splits_query as q  # noqa: E402


class Clock(unittest.TestCase):
    def test_window_boundaries(self):
        self.assertEqual(layer.window_of(13 * 60), 'early')
        self.assertEqual(layer.window_of(14 * 60 + 29), 'early')
        self.assertEqual(layer.window_of(14 * 60 + 30), 'late_afternoon')
        self.assertEqual(layer.window_of(19 * 60 + 59), 'late_afternoon')
        self.assertEqual(layer.window_of(20 * 60), 'primetime')

    def test_kickoff_utc_follows_daylight_time(self):
        # 2026-11-01 is the day clocks go back, so 13:00 ET that afternoon is EST (UTC-5).
        self.assertEqual(layer.kickoff_utc('2026-11-01', '13:00'), '2026-11-01T18:00:00Z')
        self.assertEqual(layer.kickoff_utc('2026-10-25', '13:00'), '2026-10-25T17:00:00Z')

    def test_venue_local_clock(self):
        minutes, hhmm = layer.local_clock('2026-11-01T18:00:00Z', layer.pytz.timezone('America/Denver'))
        self.assertEqual((minutes, hhmm), (11 * 60, '11:00'))


class Usage(unittest.TestCase):
    def test_unique_leader_wins(self):
        self.assertEqual(layer.pick_by_usage(['a', 'b'], {'a': 4, 'b': 2}), 'a')

    def test_tie_at_the_top_is_unresolved(self):
        self.assertIsNone(layer.pick_by_usage(['a', 'b'], {'a': 3, 'b': 3}))

    def test_no_usage_is_unresolved(self):
        self.assertIsNone(layer.pick_by_usage(['a', 'b'], {}))


class Status(unittest.TestCase):
    def test_logged_with_snaps_is_played(self):
        row = (None,) * 10 + (50, 'nfl_snap_counts') + (None,) * 16
        self.assertEqual(layer.classify('g', 'BUF', 2025, 3, 'x', row, {}, {})[0], 'played')

    def test_logged_with_zero_snaps_is_not_played(self):
        row = (None,) * 10 + (0, 'nfl_snap_counts') + (None,) * 16
        self.assertEqual(layer.classify('g', 'BUF', 2025, 3, 'x', row, {}, {})[0], 'absent_no_reason')

    def test_inactive_label_is_officially_inactive(self):
        reasons = {('g', 'BUF', 'x'): ('inactive_no_report', None)}
        self.assertEqual(layer.classify('g', 'BUF', 2024, 3, 'x', None, reasons, {})[0], 'officially_inactive')

    def test_injury_out_is_injured(self):
        reasons = {('g', 'BUF', 'x'): ('injury_out', 'Out')}
        self.assertEqual(layer.classify('g', 'BUF', 2024, 3, 'x', None, reasons, {})[0], 'injured')

    def test_historical_report_is_injured(self):
        hist = {(2019, 3, 'BUF', 'x'): ('Questionable', 'Did Not Participate In Practice')}
        self.assertEqual(layer.classify('g', 'BUF', 2019, 3, 'x', None, {}, hist)[0], 'injured')

    def test_absent_with_no_reason_is_not_called_healthy(self):
        status, reason, _snaps = layer.classify('g', 'BUF', 2019, 3, 'x', None, {}, {})
        self.assertEqual((status, reason), ('absent_no_reason', 'no_reason_on_record'))

    def test_availability_says_played_without_a_log_is_flagged(self):
        reasons = {('g', 'BUF', 'x'): ('played', None)}
        self.assertEqual(layer.classify('g', 'BUF', 2024, 3, 'x', None, reasons, {}),
                         ('absent_no_reason', 'availability_says_played_but_no_log', None))


class Weather(unittest.TestCase):
    def game(self, roof, temp, wind):
        return {'roof': roof, 'temp': temp, 'wind': wind}

    def test_dome_is_neither_match_nor_missing(self):
        self.assertEqual(q._weather_ok(self.game('dome', None, None), {'wind_min': 15}), (False, False))

    def test_outdoor_without_wind_is_missing(self):
        self.assertEqual(q._weather_ok(self.game('outdoors', 40, None), {'wind_min': 15}), (False, True))

    def test_wind_threshold(self):
        self.assertEqual(q._weather_ok(self.game('outdoors', 40, 16), {'wind_min': 15}), (True, False))
        self.assertEqual(q._weather_ok(self.game('outdoors', 40, 12), {'wind_min': 15}), (False, False))

    def test_wilson_interval_needs_games(self):
        self.assertIsNone(q._wilson(0, 0))
        low, high = q._wilson(5, 10)
        self.assertTrue(0 < low < 0.5 < high < 1)


SCHEMA_ROWS = dict(home_away='home', division=0, gameday='2025-10-05', weekday='Sunday', gametime_et='13:00',
                   kickoff_utc='2025-10-05T17:00:00Z', window_et='early', window_venue='early', window_body='early',
                   venue_state='CA', venue_tz='America/Los_Angeles', venue_source='nfl_game_context',
                   team_home_tz='America/Los_Angeles', international=0, stadium='X', roof='outdoors', surface='grass',
                   temp=60.0, wind=5.0, referee='Ref A', attendance=1, broadcast='CBS', plays=60, yards=350,
                   pass_att=30, completions=20, pass_yds=250, rush_att=25, rush_yds=100, epa_per_play=0.05,
                   success_rate=0.45, sacks_taken=2, interceptions=1, fumbles_lost=0, turnovers=1, penalties=5,
                   penalty_yards=40)


def team_game(game_id, team, opponent, week, pf, pa, **overrides):
    row = dict(SCHEMA_ROWS, game_id=game_id, season=2025, week=week, game_type='REG', team=team, opponent=opponent,
               points_for=pf, points_against=pa, result='W' if pf > pa else ('L' if pf < pa else 'T'))
    row.update(overrides)
    return row


class QueryOnSyntheticLayer(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.executescript(layer.SCHEMA)
        rows = [
            team_game('2025_01_BUF_NYJ', 'BUF', 'NYJ', 1, 30, 10, home_away='home'),
            team_game('2025_01_NYJ_BUF', 'NYJ', 'BUF', 1, 10, 30, home_away='away'),
            team_game('2025_02_BUF_MIA', 'BUF', 'MIA', 2, 20, 24, home_away='home', roof='dome', temp=None, wind=None,
                      weekday='Monday', window_et='primetime'),
            team_game('2025_02_MIA_BUF', 'MIA', 'BUF', 2, 24, 20, home_away='away', roof='dome', temp=None, wind=None,
                      weekday='Monday', window_et='primetime'),
            team_game('2025_03_BUF_KC', 'BUF', 'KC', 3, 27, 27, home_away='home', wind=None, referee='Ref B'),
            team_game('2025_03_KC_BUF', 'KC', 'BUF', 3, 27, 27, home_away='away', wind=None, referee='Ref B'),
        ]
        cols = list(rows[0])
        self.con.executemany(f"insert into team_game ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                             [[r[c] for c in cols] for r in rows])
        self.con.execute("insert into game_official values ('2025_03_BUF_KC', 'Referee', 'Ref B', 'Referee')")
        self.con.execute("insert into team_role (game_id, season, week, team, role, gsis_id, player_name, identified_by,"
                         " tie, candidates, status, status_reason, snaps) values "
                         "('2025_01_BUF_NYJ', 2025, 1, 'BUF', 'QB', 'qb1', 'Q', 'depth_chart_week', 0, 1, 'played',"
                         " 'nfl_snap_counts', 60)")
        self.con.execute("insert into team_role (game_id, season, week, team, role, gsis_id, player_name, identified_by,"
                         " tie, candidates, status, status_reason, snaps) values "
                         "('2025_02_BUF_MIA', 2025, 2, 'BUF', 'QB', 'qb1', 'Q', 'depth_chart_week', 0, 1, 'injured',"
                         " 'availability:injury_out', NULL)")

    def test_team_split_lists_exact_games_and_marks_thin(self):
        out = q.team_splits(self.con, 'BUF', {'seasons': (2025, 2025), 'game_type': 'REG'}, baselines=False)
        self.assertEqual(out['split']['n'], 3)
        self.assertEqual(out['split']['game_ids'], ['2025_01_BUF_NYJ', '2025_02_BUF_MIA', '2025_03_BUF_KC'])
        self.assertEqual(out['split']['warning'], 'thin')
        self.assertEqual((out['split']['wins'], out['split']['losses'], out['split']['ties']), (1, 1, 1))

    def test_role_not_played_filter(self):
        out = q.team_splits(self.con, 'BUF', {'roles': {'QB': ['not_played']}}, baselines=False)
        self.assertEqual(out['split']['game_ids'], ['2025_02_BUF_MIA'])

    def test_teammate_did_not_play_counts_only_seasons_he_was_on_the_team(self):
        # wr1 logs the 2025 week 1 game only. He is on BUF's 2025 roster, so week 2 counts as a game without him.
        self.con.execute("insert into player_game (game_id, season, week, game_type, team, opponent, home_away, "
                         "player_id, gsis_id, player_name, snaps, snap_source, targets) values "
                         "('2025_01_BUF_NYJ', 2025, 1, 'REG', 'BUF', 'NYJ', 'home', 1, 'wr1', 'W', 55, 'x', 6)")
        played = q.team_splits(self.con, 'BUF', {'seasons': (2025, 2025), 'player_played': ('wr1', True)},
                               baselines=False)
        absent = q.team_splits(self.con, 'BUF', {'seasons': (2025, 2025), 'player_played': ('wr1', False)},
                               baselines=False)
        self.assertEqual(played['split']['game_ids'], ['2025_01_BUF_NYJ'])
        self.assertEqual(absent['split']['game_ids'], ['2025_02_BUF_MIA', '2025_03_BUF_KC'])

    def test_wind_filter_counts_missing_outdoor_values_and_excludes_domes(self):
        out = q.team_splits(self.con, 'BUF', {'wind_min': 3}, baselines=False)
        self.assertEqual(out['split']['game_ids'], ['2025_01_BUF_NYJ'])
        self.assertEqual(out['missing_classification']['weather']['game_ids'], ['2025_03_BUF_KC'])

    def test_referee_filter_uses_official_rows(self):
        out = q.team_splits(self.con, 'BUF', {'referee': 'Ref B'}, baselines=False)
        self.assertEqual(out['split']['game_ids'], ['2025_03_BUF_KC'])
        out = q.team_splits(self.con, 'BUF', {'referee': 'Ref C'}, baselines=False)
        self.assertEqual(out['split']['n'], 0)
        self.assertEqual(out['split']['warning'], 'empty')

    def test_baselines_are_present(self):
        out = q.team_splits(self.con, 'BUF', {'seasons': (2025, 2025)})
        self.assertEqual(out['baseline_team_all_games']['n'], 3)
        self.assertEqual(out['baseline_league']['n'], 6)
        self.assertEqual(out['split']['shrinkage'], 'none (raw)')


if __name__ == '__main__':
    unittest.main()
