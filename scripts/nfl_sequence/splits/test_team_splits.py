import sqlite3
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import team_splits_build as b  # noqa: E402
import team_splits_query as q  # noqa: E402

CURRENT = {'Highmark Stadium': 60108, 'Lambeau Field': 81441, 'Paycor Stadium': 65515}


class Bins(unittest.TestCase):
    def test_capacity_boundaries(self):
        self.assertEqual(b.capacity_bin(64999), 'under_65k')
        self.assertEqual(b.capacity_bin(65000), '65k_to_69k')
        self.assertEqual(b.capacity_bin(70000), '70k_plus')

    def test_attendance_boundaries(self):
        self.assertEqual(b.attendance_bin(59999), 'under_60k')
        self.assertEqual(b.attendance_bin(60000), '60k_to_74k')
        self.assertEqual(b.attendance_bin(75000), '75k_plus')
        self.assertIsNone(b.attendance_bin(None))

    def test_temperature_and_wind_only_outdoors(self):
        self.assertEqual(b.temp_bin(39.9, 'outdoors'), 'under_40F')
        self.assertEqual(b.temp_bin(40, 'open'), '40F_to_59F')
        self.assertEqual(b.temp_bin(80, 'outdoors'), '80F_plus')
        self.assertEqual(b.temp_bin(70, 'dome'), 'not_outdoors')
        self.assertIsNone(b.temp_bin(70, None))
        self.assertIsNone(b.temp_bin(None, 'outdoors'))
        self.assertEqual(b.wind_bin(9.9, 'outdoors'), 'under_10mph')
        self.assertEqual(b.wind_bin(10, 'outdoors'), '10_to_14mph')
        self.assertEqual(b.wind_bin(15, 'outdoors'), '15_to_19mph')
        self.assertEqual(b.wind_bin(20, 'outdoors'), '20mph_plus')
        self.assertEqual(b.wind_bin(25, 'closed'), 'not_outdoors')


class Buildings(unittest.TestCase):
    def test_rename_of_the_same_building_maps_to_current(self):
        self.assertEqual(b.canonical_building('Heinz Field', dict(CURRENT, **{'Acrisure Stadium': 68984})),
                         'Acrisure Stadium')

    def test_rebuilt_stadium_is_not_mapped_to_the_new_listing(self):
        # Buffalo's 2016 to 2025 building is not the 2026 Highmark Stadium listed at 60,108.
        self.assertIsNone(b.canonical_building('New Era Field', CURRENT))
        self.assertIsNone(b.canonical_building('Ralph Wilson Stadium', CURRENT))
        self.assertEqual(b.canonical_building('Highmark Stadium', CURRENT), 'Highmark Stadium')

    def test_moves_to_another_building_stay_unmapped(self):
        self.assertIsNone(b.canonical_building('Qualcomm Stadium', CURRENT))
        self.assertIsNone(b.canonical_building('Georgia Dome', CURRENT))

    def test_alias_target_must_be_a_current_listing(self):
        self.assertIsNone(b.canonical_building('Paul Brown Stadium', {'Lambeau Field': 81441}))


def row(team='BUF', season=2024, result='W', pf=24, pa=20, **extra):
    base = {'game_id': f'{season}_x_{team}', 'tier': 'A', 'season': season, 'team': team, 'opponent': 'NE',
            'result': result, 'points_for': pf, 'points_against': pa, 'weekday': 'Sunday', 'home_away': 'home',
            'stadium_canonical': 'Highmark Stadium', 'stadium': 'Highmark Stadium', 'officials': [],
            'referee': 'R1', 'roof': 'outdoors', 'temp_bin': '60F_to_79F', 'wind_bin': '10_to_14mph',
            'window_et': 'early', 'window_venue': None, 'window_body': None, 'kickoff_et': '13:00',
            'game_type': 'REG', 'attendance_bin': None, 'capacity_bin': '65k_to_69k', 'division': None,
            'international': None, 'surface': 'grass', 'opponent_name': None, 'gameday': f'{season}-09-08'}
    base.update(extra)
    return base


class Levels(unittest.TestCase):
    def test_unknown_condition_is_not_a_level(self):
        self.assertEqual(b.levels_of('window_venue', row()), [])
        self.assertEqual(b.levels_of('weekday', row(weekday=None)), [])

    def test_official_is_a_level_for_each_name(self):
        self.assertEqual(b.levels_of('official', row(officials=['A', 'B'])), ['A', 'B'])
        self.assertEqual(b.levels_of('official', row(officials=[])), [])

    def test_season_and_all_are_always_known(self):
        self.assertEqual(b.levels_of('season', row(season=2011)), ['2011'])
        self.assertEqual(b.levels_of('all', row()), ['all_games'])


class Metrics(unittest.TestCase):
    def test_points_in_wins_and_losses(self):
        rows = [row(result='W', pf=30, pa=10), row(result='L', pf=17, pa=24), row(result='W', pf=20, pa=17)]
        m = b.metrics(rows)
        self.assertEqual((m['n'], m['wins'], m['losses']), (3, 2, 1))
        self.assertEqual(m['pf_in_wins_mean'], 25.0)
        self.assertEqual(m['pf_in_losses_mean'], 17.0)
        self.assertEqual(m['pa_in_losses_mean'], 24.0)

    def test_sample_flags(self):
        self.assertEqual(b.metrics([row()] * 2)['sample_flag'], 'very_thin')
        self.assertEqual(b.metrics([row()] * 5)['sample_flag'], 'thin')
        self.assertIsNone(b.metrics([row()] * 8)['sample_flag'])

    def test_game_ids_are_exact_and_unique(self):
        m = b.metrics([row(game_id='g1'), row(game_id='g1'), row(game_id='g2')])
        self.assertEqual(m['game_ids'], ['g1', 'g2'])


class Splits(unittest.TestCase):
    def test_coverage_counts_unknown_games_as_missing(self):
        rows = [row(season=2012, window_venue=None), row(season=2016, window_venue='late_afternoon')]
        splits, coverage = b.build_splits(rows)
        cov = {c['dimension']: c for c in coverage if c['scope'] == 'all' and c['team'] == 'BUF'}
        self.assertEqual((cov['window_venue']['n_known'], cov['window_venue']['n_missing']), (1, 1))
        self.assertEqual(cov['window_venue']['seasons_known_from'], 2016)

    def test_margin_delta_is_against_the_team_overall_in_the_same_scope(self):
        rows = [row(result='W', pf=30, pa=10, weekday='Sunday'), row(result='L', pf=10, pa=20, weekday='Monday')]
        splits, _ = b.build_splits(rows)
        sunday = [s for s in splits if s['dimension'] == 'weekday' and s['level'] == 'Sunday'][0]
        # Team margin is (20 + -10) / 2 = 5. Sunday is the 20-point win alone, so the delta is 15.
        self.assertEqual(sunday['delta_margin_vs_team'], 15.0)

    def test_scope_separates_the_tiers(self):
        rows = [row(season=2015), dict(row(season=1985), tier='B', weekday='Sunday', window_et=None)]
        splits, _ = b.build_splits(rows)
        a = [s for s in splits if s['scope'] == 'tier_a' and s['dimension'] == 'all'][0]
        bb = [s for s in splits if s['scope'] == 'tier_b' and s['dimension'] == 'all'][0]
        self.assertEqual((a['n'], bb['n']), (1, 1))


class EloRows(unittest.TestCase):
    def setUp(self):
        self.dev = sqlite3.connect(':memory:')
        self.dev.execute('create table nfl_elo_538 (date text, season text, neutral text, playoff text, team1 text, '
                         'team2 text, score1 text, score2 text)')
        self.dev.executemany('insert into nfl_elo_538 values (?,?,?,?,?,?,?,?)', [
            ('1966-09-11', '1966', '0', '0', 'OAK', 'BUF', '24', '17'),
            ('1972-01-02', '1971', '1', '1', 'BAL', 'OAK', '10', '7'),
            ('2015-09-13', '2015', '0', '0', 'GB', 'SEA', '1', '2'),
        ])

    def test_pre_2010_only_and_weekday_from_date(self):
        rows = b.elo_rows(self.dev)
        self.assertEqual({r['season'] for r in rows}, {1966, 1971})
        self.assertEqual(rows[0]['weekday'], 'Sunday')

    def test_oakland_maps_to_las_vegas_and_home_is_team1(self):
        rows = b.elo_rows(self.dev)
        oak = [r for r in rows if r['team'] == 'LV' and r['season'] == 1966][0]
        self.assertEqual((oak['home_away'], oak['points_for'], oak['result']), ('home', 24, 'W'))
        buf = [r for r in rows if r['team'] == 'BUF' and r['season'] == 1966][0]
        self.assertEqual((buf['home_away'], buf['opponent'], buf['points_for']), ('away', 'LV', 17))

    def test_neutral_and_playoff_flags(self):
        rows = b.elo_rows(self.dev)
        neutral = [r for r in rows if r['season'] == 1971]
        self.assertTrue(all(r['home_away'] == 'neutral' and r['game_type'] == 'PLAYOFF' for r in neutral))


class Query(unittest.TestCase):
    def test_combined_conditions_intersect(self):
        rows = [row(game_id='g_sun_early', season=2020, weekday='Sunday', window_et='early', result='W', pf=27, pa=20),
                row(game_id='g_sun_late', season=2021, weekday='Sunday', window_et='late_afternoon', result='L',
                    pf=13, pa=31),
                row(game_id='g_mon', season=2021, weekday='Monday', window_et='primetime', result='W', pf=21, pa=7)]
        db = sqlite3.connect(':memory:')
        db.executescript(b.SCHEMA)
        cols = [c[1] for c in db.execute('pragma table_info(team_game_row)')]
        db.executemany(f"insert into team_game_row ({','.join(cols)}) values ({','.join('?' * len(cols))})",
                       [tuple(r.get(c) for c in cols) for r in rows])
        result = q.combined(db, 'BUF', [('weekday', 'Sunday'), ('window_et', 'early')])
        self.assertEqual(result['n'], 1)
        self.assertEqual(result['wins'], 1)
        self.assertEqual(result['games'][0]['game_id'], 'g_sun_early')


if __name__ == '__main__':
    unittest.main()
