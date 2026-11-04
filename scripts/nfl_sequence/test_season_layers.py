"""SLC V1.5 every-layer blend: the weight rule, the count blend, the key mapping, and V1 unchanged with no current season."""
import datetime as dt
import sys
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytz

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import season_layers as sl  # noqa: E402

CUTOFF = dt.datetime(2026, 10, 25, 15, 30, tzinfo=pytz.utc)


def evidence(team_games, game_ids=('g1',), n0=4.0):
    return sl.Evidence(2026, CUTOFF, 'target', game_ids, team_games, n0=n0)


class Weight(unittest.TestCase):
    def test_the_weight_on_history_is_n0_over_n0_plus_games(self):
        ev = evidence({'AAA': 7, 'BBB': 0})
        self.assertAlmostEqual(ev.team_weight('AAA'), 4 / 11)
        self.assertEqual(ev.team_weight('BBB'), 1.0)
        self.assertEqual(ev.team_weight('ZZZ'), 1.0)  # a team with no available game keeps its history

    def test_league_games_are_the_mean_games_per_team(self):
        self.assertEqual(evidence({'AAA': 7, 'BBB': 5}).league_games(), 6)

    def test_the_holdout_season_needs_a_cutoff(self):
        with self.assertRaises(ValueError):
            sl.Evidence(2026, None, 'target', ('g1',), {})


class CountBlend(unittest.TestCase):
    def test_shares_follow_the_weights_and_the_total_is_pooled(self):
        out = sl.blend_counts(Counter(run=30, dropback=70), Counter(run=6, dropback=4), 0.25)
        self.assertAlmostEqual(sum(out.values()), 110)
        self.assertAlmostEqual(out['run'] / 110, 0.25 * 0.3 + 0.75 * 0.6)

    def test_no_current_counts_keep_the_history_object(self):
        hist = Counter(run=3)
        self.assertIs(sl.blend_counts(hist, Counter(), 0.5), hist)

    def test_no_history_takes_the_current_counts(self):
        self.assertEqual(sl.blend_counts(Counter(), Counter(run=2, dropback=1), 0.5), Counter(run=2, dropback=1))

    def test_a_category_seen_only_this_season_enters_at_its_weight(self):
        out = sl.blend_counts(Counter(a=10), Counter(b=10), 0.75)
        self.assertAlmostEqual(out['b'] / 20, 0.25)

    def test_keyed_blend_counts_each_kind_of_key(self):
        stats = Counter()
        out = sl.blend_keyed({('AAA', 1): Counter(x=4), ('BBB', 1): Counter(x=1)},
                             {('AAA', 1): Counter(y=4), ('CCC', 1): Counter(y=2)}, lambda key: 0.5, stats)
        self.assertEqual(stats, Counter(blended=1, season_only=1, history_only=1))
        self.assertEqual(out[('BBB', 1)], Counter(x=1))
        self.assertEqual(out[('CCC', 1)], Counter(y=2))
        self.assertAlmostEqual(out[('AAA', 1)]['x'], 4.0)


class ShiftBlend(unittest.TestCase):
    def test_current_season_keys_are_mapped_through_the_team_code(self):
        hist = {'shift': {(0, 1): 0.2, (1, 1): -0.4}}
        season = {'shift': {(0, 1): 1.0, (1, 1): 0.0}}  # in the season frame BBB is index 0 and AAA is index 1
        out, info = sl.blend_shifts(hist, season, {'AAA': 0, 'BBB': 1}, {'BBB': 0, 'AAA': 1},
                                    lambda code: {'AAA': 0.5, 'BBB': 0.25}[code])
        self.assertAlmostEqual(out['shift'][(0, 1)], 0.5 * 0.2 + 0.5 * 0.0)  # AAA took its own current shift
        self.assertAlmostEqual(out['shift'][(1, 1)], 0.25 * -0.4 + 0.75 * 1.0)
        self.assertEqual(info['shifts_blended'], 2)

    def test_a_team_without_history_is_not_given_a_key(self):
        out, _ = sl.blend_shifts({'shift': {(0, 1): 0.2}}, {'shift': {(0, 1): 1.0}}, {'AAA': 0}, {'NEW': 0}, lambda c: 0.5)
        self.assertEqual(out['shift'], {(0, 1): 0.2})


class NoCurrentSeason(unittest.TestCase):
    def test_every_table_is_left_as_it_was(self):
        tables = {name: object() for name in ('team_outcomes', 'role_table', 'decision_table', 'playbook_table',
                                              'qb_decision_table', 'player_outcome_table', 'share_table', 'point_shifts',
                                              'streak_shifts', 'streak_league')}
        sampler = SimpleNamespace(season_team_down=None, score_clock_playcalling_enabled=True, **tables)
        manifest = sl.apply(SimpleNamespace(contextual_sampler=sampler), 'unused.db', evidence({}, game_ids=()))
        for name, table in tables.items():
            self.assertIs(getattr(sampler, name), table)
        self.assertIsNone(sampler.season_team_down)
        self.assertEqual(manifest['layers'], {})
        self.assertIs(sampler.season_blend_manifest, manifest)


class Shares(unittest.TestCase):
    def test_blended_base_shares_still_sum_to_one_per_team(self):
        table = {'base': {'receive': {('AAA', 'p1'): 0.6, ('AAA', 'p2'): 0.4, ('BBB', 'p9'): 1.0}}}
        counts = {'AAA': {'p2': 3, 'p3': 1}}
        import share_distributions as sd
        real = sd.team_game_counts
        sd.team_game_counts = lambda db, season, role, evidence=None: ({}, counts)
        try:
            out, info = sl.adapt_shares(table, 'unused.db', evidence({'AAA': 4}))
        finally:
            sd.team_game_counts = real
        base = out['base']['receive']
        self.assertAlmostEqual(sum(v for (t, _p), v in base.items() if t == 'AAA'), 1.0)
        self.assertAlmostEqual(base[('AAA', 'p3')], 0.5 * 0.25)  # w = 4 / 8
        self.assertEqual(base[('BBB', 'p9')], 1.0)
        self.assertEqual(info['teams_blended'], {'receive': 1})


if __name__ == '__main__':
    unittest.main()
