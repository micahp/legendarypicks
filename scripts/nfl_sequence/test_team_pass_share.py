"""Equality test: the SLC runtime P1 estimate reproduces the frozen C1 forecasts for every 2025 team-game.

The frozen manifest (docs/research/slc-v2-p1-team-2026-11-02/outputs/p1_forecast_manifest_pass_share_retro2025.csv) was written by
p1_eval.py --retro under the M6 freeze. The runtime is run with the frozen lagged availability rule, which is the only rule the frozen
manifest used. Estimates are rounded to five decimals in the manifest, so they are compared at that precision.
"""
import csv
import datetime as dt
import os
import unittest

import team_pass_share as tp

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
DB = '/root/legendarypicks/backend/data/picks.dev.db'
MANIFEST = os.path.join(ROOT, 'docs', 'research', 'slc-v2-p1-team-2026-11-02', 'outputs',
                        'p1_forecast_manifest_pass_share_retro2025.csv')


class FrozenPassShareEquality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.games = tp.team_games(DB, (2024, 2025))
        cls.sched = tp.schedule(DB, (2024, 2025))
        cls.kickoff_of = {g: v[0] for g, v in cls.sched.items() if v[0] is not None}
        cls.table = tp.Table(cls.games, cls.sched, 2025)
        with open(MANIFEST, encoding='utf-8') as handle:
            cls.rows = list(csv.DictReader(handle))

    def test_manifest_is_the_full_2025_population(self):
        self.assertEqual(len(self.rows), 544)  # 272 games, two team-games each (M6 freeze output)

    def test_every_team_game_matches_the_frozen_forecast(self):
        mismatches, no_history = [], 0
        for row in self.rows:
            cutoff = dt.datetime.fromisoformat(row['cutoff_utc']).replace(tzinfo=None)
            got = self.table.estimate(row['team'], None, cutoff + dt.timedelta(hours=1), tp.usable_lagged_kickoff,
                                      kickoff_of=self.kickoff_of)
            if int(row['games_used']) == 0:
                no_history += 1
                if got is not None:
                    mismatches.append((row['game_id'], row['team'], 'expected no usable game', got))
                continue
            if got is None:
                mismatches.append((row['game_id'], row['team'], 'no runtime estimate', row['estimate']))
                continue
            checks = {
                'estimate': round(got['estimate'], 5) == float(row['estimate']),
                'prior': round(got['prior'], 5) == float(row['prior']),
                'games_used': got['games_used'] == int(row['games_used']),
                'prior_source': got['prior_source'] == row['prior_source'],
                'coach': got['coach'] == row['coach_used'],
                'coach_source': got['coach_source'] == row['coach_source'],
            }
            failed = [name for name, ok in checks.items() if not ok]
            if failed:
                mismatches.append((row['game_id'], row['team'], failed, got))
        self.assertEqual(mismatches, [], f'{len(mismatches)} of {len(self.rows)} rows differ; {no_history} had no usable game')
        self.assertGreater(len(self.rows) - no_history, 400)


class PriorWeeksRule(unittest.TestCase):
    def test_only_earlier_weeks_count(self):
        games = [(2024, 5, 'g24', 'KC', 60, 30), (2025, 1, 'g1', 'KC', 60, 30), (2025, 2, 'g2', 'KC', 60, 36),
                 (2025, 3, 'g3', 'KC', 60, 42)]
        sched = {'g24': (None, {'KC': 'Andy Reid'}), 'g1': (None, {'KC': 'Andy Reid'}),
                 'g2': (None, {'KC': 'Andy Reid'}), 'g3': (None, {'KC': 'Andy Reid'})}
        table = tp.Table(games, sched, 2025)
        got = table.estimate('KC', 3, None, tp.usable_prior_weeks, kickoff_of={})
        self.assertEqual(got['games_used'], 2)  # weeks 1 and 2 only, not week 3 itself
        self.assertEqual(got['coach_source'], 'usable_game')
        self.assertEqual(got['coach'], 'Andy Reid')
        self.assertEqual(got['prior_source'], 'team_prior')  # the coach has one prior-season game, below the 8-game minimum

    def test_no_usable_game_gives_no_estimate(self):
        games = [(2024, 5, 'g24', 'KC', 60, 30), (2025, 1, 'g1', 'KC', 60, 30)]
        sched = {'g24': (None, {'KC': 'Andy Reid'}), 'g1': (None, {'KC': 'Andy Reid'})}
        table = tp.Table(games, sched, 2025)
        self.assertIsNone(table.estimate('KC', 1, None, tp.usable_prior_weeks, kickoff_of={}))


class KickoffRule(unittest.TestCase):
    def test_kickoff_matches_the_frozen_depth_adapter_on_every_2025_game(self):
        import sys
        sys.path.insert(0, os.path.join(ROOT, 'docs', 'research', 'slc-v2-depth-adapter-2026-11-02'))
        import depth_adapter as da
        con = __import__('sqlite3').connect(f'file:{DB}?mode=ro', uri=True, timeout=10)
        try:
            rows = con.execute("SELECT gameday, gametime FROM nfl_schedule WHERE game_type = 'REG' AND season = 2025 "
                               "AND gametime IS NOT NULL").fetchall()
        finally:
            con.close()
        self.assertGreater(len(rows), 270)
        for gameday, gametime in rows:
            _early, final = da.game_horizons(gameday, gametime)
            frozen = (final + dt.timedelta(hours=1)).replace(tzinfo=None)
            self.assertEqual(tp.kickoff_utc(gameday, gametime), frozen, (gameday, gametime))


if __name__ == '__main__':
    unittest.main()
