import datetime as dt
import math
import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import current_season_adapt as adapt  # noqa: E402
import e1_drive as e1  # noqa: E402
import team_season_adapt as tsa  # noqa: E402
import team_tendency as tt  # noqa: E402
from test_team_tendency import NEUTRAL, SKEWED, game_rows, pool_from  # noqa: E402


def historical():
    return tt.build_from_pool(pool_from(SKEWED, season=2025), 2026, cutoff=(2026, 1))


def schedule_row(game_id, gameday, gametime, season=2026):
    return {'game_id': game_id, 'season': season, 'week': 1, 'gameday': gameday, 'gametime': gametime}


class KickoffAndCutoff(unittest.TestCase):
    def test_kickoff_uses_eastern_time_and_the_dst_change(self):
        self.assertEqual(tsa.kickoff_utc('2026-10-29', '13:00'), dt.datetime(2026, 10, 29, 17, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(tsa.kickoff_utc('2026-11-01', '13:00'), dt.datetime(2026, 11, 1, 18, 0, tzinfo=dt.timezone.utc))

    def test_cutoff_is_ninety_minutes_before_kickoff(self):
        kickoff = tsa.kickoff_utc('2026-11-08', '13:00')
        self.assertEqual(tsa.cutoff_utc(kickoff), kickoff - dt.timedelta(minutes=90))

    def test_a_game_counts_only_after_ten_hours_from_its_kickoff(self):
        target = tsa.kickoff_utc('2026-11-08', '13:00')
        cutoff = tsa.cutoff_utc(target)
        rows = [schedule_row('done_early', '2026-11-01', '13:00'),       # 18:00Z; available 04:00Z Nov 2, before cutoff
                schedule_row('sunday_same_day', '2026-11-08', '09:30'),  # 14:30Z; available Nov 9 00:30Z, after cutoff
                schedule_row('target', '2026-11-08', '13:00')]
        available, undated = tsa.available_games(rows, 2026, cutoff, target_game_id='target')
        self.assertEqual(available, ['done_early'])
        self.assertEqual(undated, [])

    def test_a_result_available_exactly_at_the_cutoff_counts(self):
        target = tsa.kickoff_utc('2026-11-08', '13:00')
        cutoff = tsa.cutoff_utc(target)
        exact = cutoff - dt.timedelta(hours=tsa.AVAILABILITY_LAG_HOURS)
        rows = [schedule_row('boundary', exact.astimezone(tsa.EASTERN).strftime('%Y-%m-%d'),
                             exact.astimezone(tsa.EASTERN).strftime('%H:%M'))]
        available, _ = tsa.available_games(rows, 2026, cutoff, target_game_id='target')
        self.assertEqual(available, ['boundary'])

    def test_an_undated_game_is_excluded_and_listed(self):
        cutoff = tsa.cutoff_utc(tsa.kickoff_utc('2026-11-08', '13:00'))
        rows = [schedule_row('no_time', '2026-11-01', None)]
        available, undated = tsa.available_games(rows, 2026, cutoff, target_game_id='target')
        self.assertEqual((available, undated), ([], ['no_time']))

    def test_no_cutoff_for_the_holdout_season_is_refused(self):
        with self.assertRaisesRegex(ValueError, 'holdout'):
            tsa.available_games([], 2026, None, target_game_id='target')


class Blend(unittest.TestCase):
    def test_no_current_plays_returns_the_historical_object(self):
        hist = historical()
        adapted, diagnostics = tsa.adapt(hist, [])
        self.assertIs(adapted, hist)
        self.assertEqual(diagnostics['plays'], 0)

    def test_teams_without_current_plays_keep_their_historical_ratios_exactly(self):
        hist = historical()
        adapted, _ = tsa.adapt(hist, game_rows(1, 2026, 'AAA', 'CCC', ['run', 'pass']))
        self.assertEqual(adapted.ratios['offense']['BBB'], hist.ratios['offense']['BBB'])
        self.assertEqual(adapted.ratios['defense']['DDD'] if 'DDD' in adapted.ratios['defense'] else {},
                         hist.ratios['defense'].get('DDD', {}))

    def test_blended_share_follows_the_formula_and_sums_to_one(self):
        hist = historical()
        rows = game_rows(1, 2026, 'AAA', 'CCC', ['run', 'run', 'pass', 'run'])
        adapted, diagnostics = tsa.adapt(hist, rows, n0=4.0, focus_teams=('AAA',))
        cname = tt.cell_name(tt.cell_key(rows[0]))
        shares = hist.league_shares[cname]
        pool, _ = e1.build_pool(rows)  # V1's classifier: the count the blend uses, which can be below the number of rows
        season_counts = Counter(event for cell in pool.values() for event, _r, _u, _s in cell)
        n = sum(season_counts.values())
        self.assertGreater(n, 0)
        for event, ls in shares.items():
            hist_share = hist.ratios['offense']['AAA'][cname].get(event, 1.0) * ls
            season_share = (season_counts.get(event, 0) + tt.PRIOR_STRENGTH * ls) / (n + tt.PRIOR_STRENGTH)
            expected = (4.0 * hist_share + n * season_share) / (4.0 + n)
            self.assertAlmostEqual(adapted.ratios['offense']['AAA'][cname][event] * ls, expected, places=12, msg=event)
        total = sum(adapted.ratios['offense']['AAA'][cname][e] * ls for e, ls in shares.items())
        self.assertTrue(math.isclose(total, 1.0, rel_tol=1e-12))
        self.assertAlmostEqual(diagnostics['focus']['offense:AAA:' + cname]['weight_on_history'], 4 / (4 + n))

    def test_more_current_plays_give_the_season_more_weight(self):
        hist = historical()
        cname = tt.cell_name(tt.cell_key(game_rows(1, 2026, 'AAA', 'CCC', ['run'])[0]))
        _, few = tsa.adapt(hist, game_rows(1, 2026, 'AAA', 'CCC', ['run'] * 4), focus_teams=('AAA',))
        _, many = tsa.adapt(hist, game_rows(1, 2026, 'AAA', 'CCC', ['run'] * 24), focus_teams=('AAA',))
        few_n = few['focus']['offense:AAA:' + cname]['n']
        many_n = many['focus']['offense:AAA:' + cname]['n']
        self.assertLess(few_n, many_n)
        self.assertAlmostEqual(few['focus']['offense:AAA:' + cname]['weight_on_history'], 4 / (4 + few_n))
        self.assertAlmostEqual(many['focus']['offense:AAA:' + cname]['weight_on_history'], 4 / (4 + many_n))
        self.assertLess(many['focus']['offense:AAA:' + cname]['weight_on_history'],
                        few['focus']['offense:AAA:' + cname]['weight_on_history'])

    def test_a_team_with_no_history_starts_from_the_league_share(self):
        hist = historical()
        adapted, diagnostics = tsa.adapt(hist, game_rows(1, 2026, 'NEW', 'CCC', ['run', 'pass']))
        self.assertNotIn('NEW', hist.ratios['offense'])
        self.assertIn('NEW', adapted.ratios['offense'])
        self.assertGreaterEqual(diagnostics['cells_without_history'], 1)

    def test_the_adaptation_is_deterministic(self):
        hist = historical()
        rows = game_rows(1, 2026, 'AAA', 'CCC', ['run', 'pass', 'run'])
        first, _ = tsa.adapt(hist, rows)
        second, _ = tsa.adapt(hist, rows)
        self.assertEqual(first.manifest['sha256'], second.manifest['sha256'])
        self.assertEqual(first.ratios, second.ratios)

    def test_the_historical_object_is_not_mutated(self):
        hist = historical()
        before = {side: {team: {c: dict(e) for c, e in cells.items()} for team, cells in teams.items()}
                  for side, teams in hist.ratios.items()}
        tsa.adapt(hist, game_rows(1, 2026, 'AAA', 'CCC', ['run', 'pass']))
        self.assertEqual(hist.ratios, before)

    def test_the_historical_prior_weight_matches_the_predeclared_default(self):
        self.assertEqual(adapt.DEFAULT_N0, 4.0)


if __name__ == '__main__':
    unittest.main()
