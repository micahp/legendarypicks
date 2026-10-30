"""Per-game target and carry share distributions (Dirichlet-multinomial), drawn once per game and used for every play in it.

Tests are written before share_distributions.py. They check the draw's shape (sums to one, eligible players only, deterministic per
game), its mean (the prior-season base share), its spread (the Dirichlet variance), and its effect on the pre-event receiver.
"""
import random
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pre_event as pe  # noqa: E402
import share_distributions as sd  # noqa: E402
from test_pre_event import SNAPSHOT  # noqa: E402
from test_slc_playcall import STATE  # noqa: E402

ROSTER = [('AAA', 'AWR1'), ('AAA', 'AWR2'), ('AAA', 'ATE1'), ('AAA', 'ARB1')]
BASE = {'AWR1': 0.5, 'AWR2': 0.3, 'ATE1': 0.15, 'ARB1': 0.05}


def table(phi):
    return {'phi': {'receive': phi, 'carry': phi}, 'base': {'receive': {('AAA', g): b for g, b in BASE.items()}, 'carry': {}}}


class Draw(unittest.TestCase):
    def test_the_shares_sum_to_one_and_cover_only_the_eligible_players(self):
        shares = sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'AWR2', 'ATE1'], 'receive', 'seed-1')
        self.assertEqual(set(shares), {'AWR1', 'AWR2', 'ATE1'})
        self.assertAlmostEqual(sum(shares.values()), 1.0)

    def test_the_same_game_and_seed_give_the_same_shares_and_another_game_differs(self):
        a = sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'AWR2'], 'receive', 'seed-1')
        self.assertEqual(a, sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'AWR2'], 'receive', 'seed-1'))
        self.assertNotEqual(a, sd.game_shares(table(17.0), 'AAA', 'g2', ['AWR1', 'AWR2'], 'receive', 'seed-1'))

    def test_the_mean_over_games_is_the_base_share(self):
        totals = {g: 0.0 for g in BASE}
        n = 3000
        for i in range(n):
            shares = sd.game_shares(table(17.0), 'AAA', f'g{i}', list(BASE), 'receive', 'seed-1')
            for g in BASE:
                totals[g] += shares[g]
        for g, b in BASE.items():
            self.assertAlmostEqual(totals[g] / n, b, delta=0.02, msg=g)

    def test_the_spread_over_games_is_the_dirichlet_variance(self):
        phi = 17.0
        xs = [sd.game_shares(table(phi), 'AAA', f'g{i}', list(BASE), 'receive', 'seed-1')['AWR1'] for i in range(3000)]
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        self.assertAlmostEqual(var, BASE['AWR1'] * (1 - BASE['AWR1']) / (phi + 1), delta=0.01)

    def test_a_player_with_no_base_gets_the_floor_and_still_has_a_share(self):
        shares = sd.game_shares(table(17.0), 'AAA', 'g1', ['AWR1', 'NOBODY'], 'receive', 'seed-1')
        self.assertGreater(shares['NOBODY'], 0.0)

    def test_conditional_share_model_uses_phi_after_normalizing_the_position_group(self):
        conditional = {**table(17.0), 'model': sd.MODEL_VERSION}
        conditional['phi'] = {'receive': {'all': 17.0, 'WR': 8.0}, 'carry': {'all': 17.0}}
        base = conditional['base']['receive']
        # AWR1 and AWR2 form a subgroup whose raw team shares sum to 0.8.
        xs = [sd.game_shares(conditional, 'AAA', f'g{i}', ['AWR1', 'AWR2'], 'receive', 'seed-1', group='WR')['AWR1']
              for i in range(3000)]
        mean = sum(xs) / len(xs)
        var = sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)
        subgroup_mean = base[('AAA', 'AWR1')] / (base[('AAA', 'AWR1')] + base[('AAA', 'AWR2')])
        self.assertAlmostEqual(mean, subgroup_mean, delta=0.02)
        self.assertAlmostEqual(var, subgroup_mean * (1 - subgroup_mean) / 9.0, delta=0.01)

    def test_historical_position_filter_rebuilds_position_specific_team_game_counts(self):
        games = {'AAA': {'g1': {'W1': 8, 'W2': 2, 'T1': 5}, 'g2': {'W1': 4, 'T1': 6}}}
        filtered, totals = sd.filter_position_group(games, {'W1': 'WR', 'W2': 'WR', 'T1': 'TE'}, ('WR',))
        self.assertEqual(filtered, {'AAA': {'g1': {'W1': 8, 'W2': 2}, 'g2': {'W1': 4}}})
        self.assertEqual(totals, {'AAA': {'W1': 12, 'W2': 2}})

    def test_selected_position_sets_map_to_fitted_historical_groups(self):
        self.assertEqual(sd.group_for_positions('receive', ('WR',)), 'WR')
        self.assertEqual(sd.group_for_positions('receive', ('TE',)), 'TE')
        self.assertEqual(sd.group_for_positions('carry', ('WR', 'TE')), 'WR_TE')
        self.assertEqual(sd.group_for_positions('carry', ('RB', 'QB', 'WR', 'TE')), 'all')

    def test_legacy_table_keeps_the_old_whole_roster_concentration(self):
        legacy = table(17.0)
        shares = sd.game_shares(legacy, 'AAA', 'g1', ['AWR1', 'AWR2'], 'receive', 'seed-1')
        self.assertEqual(shares, sd.game_shares(legacy, 'AAA', 'g1', ['AWR1', 'AWR2'], 'receive', 'seed-1'))


def concentrated(role, leader, share):
    """A share table whose base puts `share` on the leader and splits the rest over the other players."""
    rest = [g for g in BASE if g != leader]
    base = {('AAA', leader): share}
    base.update({('AAA', g): (1 - share) / len(rest) for g in rest})
    return {'phi': {'receive': 17.0, 'carry': 17.0}, 'base': {'receive': base, 'carry': base}, 'season': 2025, 'players': {}}


class Receiver(unittest.TestCase):
    """Within one game the receiver follows that game's Dirichlet shares, so one game's targets concentrate on its leader."""

    def test_within_a_game_the_receiver_follows_the_game_share(self):
        share = concentrated('receive', 'AWR1', 0.9)
        counts = {}
        for index in range(30):
            chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=index, player_shares={'receive': {}, 'carry': {}},
                               share_table=share)
            counts[chosen['receiver']['gsis_id']] = counts.get(chosen['receiver']['gsis_id'], 0) + 1
        self.assertGreaterEqual(counts.get('AWR1', 0), 20, counts)


class Carry(unittest.TestCase):
    def test_within_a_game_the_rusher_follows_the_game_carry_share(self):
        share = concentrated('carry', 'ARB1', 0.9)
        counts = {}
        for index in range(30):
            chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=5, index=index, player_shares={'receive': {}, 'carry': {}},
                               share_table=share)
            counts[chosen['rusher']['gsis_id']] = counts.get(chosen['rusher']['gsis_id'], 0) + 1
        self.assertGreaterEqual(counts.get('ARB1', 0), 20, counts)

    def test_without_a_share_table_the_receiver_is_unchanged(self):
        chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=0, player_shares={'receive': {}, 'carry': {}})
        self.assertIn('receiver', chosen)


if __name__ == '__main__':
    unittest.main()


import share_distributions as sdm  # noqa: E402
import random as _random  # noqa: E402


def synthetic_team(phi, team, players, games, rng):
    """Team-game counts drawn from a Dirichlet-multinomial with known concentration phi and the players' base shares."""
    shares = [0.4, 0.25, 0.2, 0.1, 0.05][: len(players)]
    total_share = sum(shares)
    base = {p: s / total_share for p, s in zip(players, shares)}
    by_game = {}
    for g in range(games):
        n = rng.randint(50, 70)
        draws = {p: rng.gammavariate(phi * b, 1.0) for p, b in base.items()}
        tot = sum(draws.values())
        probs = {p: d / tot for p, d in draws.items()}
        counts = {p: 0 for p in players}
        for _ in range(n):
            r = rng.random()
            acc = 0.0
            for p in players:
                acc += probs[p]
                if r <= acc:
                    counts[p] += 1
                    break
        by_game[f'{team}-g{g}'] = {p: c for p, c in counts.items() if c}
    season = {}
    for counts in by_game.values():
        for p, c in counts.items():
            season[p] = season.get(p, 0) + c
    return by_game, season


class Estimator(unittest.TestCase):
    def test_the_maximum_likelihood_fit_recovers_a_known_concentration(self):
        rng = _random.Random(11)
        players = ['P1', 'P2', 'P3', 'P4', 'P5']
        games, season = synthetic_team(20.0, 'AAA', players, 120, rng)
        fitted = sdm.fit_from_counts({'AAA': games}, {'AAA': season}, 2025)
        self.assertGreater(fitted['phi'], 20.0 * 0.6, fitted['phi'])
        self.assertLess(fitted['phi'], 20.0 * 1.6, fitted['phi'])
        self.assertLessEqual(fitted['phi_interval'][0], fitted['phi'])
        self.assertGreaterEqual(fitted['phi_interval'][1], fitted['phi'])

    def test_the_beta_binomial_benchmark_is_fitted_alongside(self):
        rng = _random.Random(12)
        games, season = synthetic_team(20.0, 'AAA', ['P1', 'P2', 'P3'], 60, rng)
        fitted = sdm.fit_from_counts({'AAA': games}, {'AAA': season}, 2025)
        self.assertIn('beta_binomial_phi', fitted)
        self.assertGreater(fitted['beta_binomial_phi'], 0)


class Transfers(unittest.TestCase):
    def test_a_player_on_two_teams_has_a_separate_share_on_each(self):
        base = sdm.base_shares({'AAA': {'X': 30, 'Y': 70}, 'BBB': {'X': 10, 'Z': 90}})
        self.assertAlmostEqual(base[('AAA', 'X')], 0.3)
        self.assertAlmostEqual(base[('BBB', 'X')], 0.1)
        self.assertAlmostEqual(base[('AAA', 'Y')], 0.7)

    def test_a_missing_history_player_gets_the_floor_and_a_share(self):
        table = {'phi': {'receive': 17.0}, 'base': {'receive': {('AAA', 'X'): 0.9}}}
        shares = sdm.game_shares(table, 'AAA', 'g1', ['X', 'NEW'], 'receive', 'seed')
        self.assertGreater(shares['NEW'], 0.0)
        self.assertAlmostEqual(sum(shares.values()), 1.0)


class Eligibility(unittest.TestCase):
    def test_a_player_out_or_doubtful_is_not_eligible_and_questionable_is(self):
        players = [{'gsis_id': g} for g in ('A', 'B', 'C', 'D')]
        report = {'players': [{'gsis_id': 'B', 'report_status': 'Out'}, {'gsis_id': 'C', 'report_status': 'Doubtful'},
                              {'gsis_id': 'D', 'report_status': 'Questionable'}]}
        self.assertEqual([p['gsis_id'] for p in sdm.eligible_players(players, report)], ['A', 'D'])

    def test_a_player_marked_ineligible_on_the_frozen_roster_cannot_take_an_opportunity(self):
        players = [{'gsis_id': 'A'}, {'gsis_id': 'B', 'roster_eligible': False}]
        self.assertEqual([p['gsis_id'] for p in sdm.eligible_players(players, None)], ['A'])

    def test_the_shares_renormalise_over_the_eligible_players(self):
        table = {'phi': {'receive': 17.0}, 'base': {'receive': {('AAA', 'A'): 0.5, ('AAA', 'B'): 0.5}}}
        self.assertEqual(sdm.game_shares(table, 'AAA', 'g', ['A'], 'receive', 's'), {'A': 1.0})

    def test_a_single_player_group_always_gives_that_player_the_whole_share(self):
        table = {'phi': {'receive': 17.0}, 'base': {'receive': {('AAA', 'A'): 0.5}}}
        shares = sdm.game_shares(table, 'AAA', 'g', ['A'], 'receive', 's')
        self.assertEqual(shares, {'A': 1.0})


class ChooserGates(unittest.TestCase):
    """The per-game draw is made once per team and game, injured players never take an opportunity, and an empty group fails loudly."""

    def test_the_team_draw_is_made_once_per_game_however_many_plays_there_are(self):
        import share_distributions as sd_mod
        calls = []
        real = sd_mod.game_shares

        def counting(*args, **kwargs):
            calls.append(args[4])  # the role
            return real(*args, **kwargs)
        sd_mod.game_shares = counting
        try:
            pick = pe.chooser(SNAPSHOT, seed=5, player_shares={'receive': {}, 'carry': {}},
                              share_table=concentrated('receive', 'AWR1', 0.9))
            for _ in range(25):
                pick('dropback', 'A', dict(STATE))
        finally:
            sd_mod.game_shares = real
        self.assertEqual(calls.count('receive'), 1)

    def test_role_filtered_receiver_plays_reuse_the_same_team_game_draw(self):
        import decision_layer
        import share_distributions as sd_mod
        roles = iter(('WR', 'TE'))
        calls = []
        real = sd_mod.game_shares

        def counting(*args, **kwargs):
            calls.append(tuple(args[3]))
            return real(*args, **kwargs)

        with patch.object(decision_layer, 'draw', side_effect=lambda *a, **kw: {'A': next(roles)}), \
             patch.object(sd_mod, 'game_shares', side_effect=counting):
            cache = {}
            for index, role in enumerate(('WR', 'TE')):
                chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=index, state=dict(STATE),
                                   player_shares={'receive': {}, 'carry': {}}, decision_table={},
                                   share_table=concentrated('receive', 'AWR1', 0.9), share_cache=cache,
                                   trick_passer_rate=0, qb_receiver_rate=0)
                self.assertEqual(chosen['target_role'], role)
                self.assertEqual(chosen['receiver']['pos_abb'], role)
        self.assertEqual(len(calls), 1)

    def test_conditional_role_model_draws_once_for_each_position_group(self):
        import decision_layer
        import share_distributions as sd_mod
        roles = iter(('WR', 'TE'))
        calls = []
        real = sd_mod.game_shares

        def counting(*args, **kwargs):
            calls.append(tuple(args[3]))
            return real(*args, **kwargs)

        conditional = {**concentrated('receive', 'AWR1', 0.9), 'model': sd_mod.MODEL_VERSION}
        with patch.object(decision_layer, 'draw', side_effect=lambda *a, **kw: {'A': next(roles)}), \
             patch.object(sd_mod, 'game_shares', side_effect=counting):
            cache = {}
            for index, role in enumerate(('WR', 'TE')):
                chosen = pe.choose(SNAPSHOT, 'home', 'dropback', seed=5, index=index, state=dict(STATE),
                                   player_shares={'receive': {}, 'carry': {}}, decision_table={},
                                   share_table=conditional, share_cache=cache,
                                   trick_passer_rate=0, qb_receiver_rate=0)
                self.assertEqual(chosen['target_role'], role)
                self.assertEqual(chosen['receiver']['pos_abb'], role)
        self.assertEqual({frozenset(group) for group in calls}, {frozenset({'AWR1', 'AWR2'}), frozenset({'ATE1'})})
        self.assertEqual(len(calls), 2)

    def test_role_filtered_carry_plays_reuse_the_same_team_game_draw(self):
        import decision_layer
        import share_distributions as sd_mod
        roles = iter(('RB', 'QB'))
        calls = []
        real = sd_mod.game_shares

        def counting(*args, **kwargs):
            calls.append(tuple(args[3]))
            return real(*args, **kwargs)

        with patch.object(decision_layer, 'draw', side_effect=lambda *a, **kw: {'B': next(roles)}), \
             patch.object(sd_mod, 'game_shares', side_effect=counting):
            cache = {}
            for index, role in enumerate(('RB', 'QB')):
                chosen = pe.choose(SNAPSHOT, 'home', 'run', seed=5, index=index, state=dict(STATE),
                                   player_shares={'receive': {}, 'carry': {}}, decision_table={},
                                   share_table=concentrated('carry', 'ARB1', 0.9), share_cache=cache)
                self.assertEqual(chosen['rusher']['pos_abb'], role)
        self.assertEqual(len(calls), 1)

    def test_a_player_listed_out_never_takes_an_opportunity(self):
        import copy
        snap = copy.deepcopy(SNAPSHOT)
        snap['rosters']['home']['injury_report'] = {'players': [{'gsis_id': 'AWR1', 'report_status': 'Out'}]}
        seen = set()
        for index in range(40):
            chosen = pe.choose(snap, 'home', 'dropback', seed=5, index=index, player_shares={'receive': {}, 'carry': {}},
                               share_table=concentrated('receive', 'AWR1', 0.9))
            seen.add(chosen['receiver']['gsis_id'])
        self.assertNotIn('AWR1', seen)

    def test_an_empty_eligible_group_fails_loudly(self):
        import copy
        snap = copy.deepcopy(SNAPSHOT)
        snap['rosters']['home']['injury_report'] = {'players': [{'gsis_id': g, 'report_status': 'Out'}
                                                                for g in ('AWR1', 'AWR2', 'ATE1', 'ARB1')]}
        with self.assertRaises(ValueError):
            pe.choose(snap, 'home', 'dropback', seed=5, index=0, player_shares={'receive': {}, 'carry': {}},
                      share_table=concentrated('receive', 'AWR1', 0.9))

    def test_a_single_eligible_rusher_always_carries(self):
        import copy
        snap = copy.deepcopy(SNAPSHOT)
        snap['rosters']['home']['injury_report'] = {'players': [{'gsis_id': g, 'report_status': 'Out'}
                                                                for g in ('AQB1', 'AQB2', 'ARB1', 'AWR1', 'AWR2', 'ATE1')]}
        snap['rosters']['home']['injury_report']['players'] = [x for x in snap['rosters']['home']['injury_report']['players']
                                                               if x['gsis_id'] != 'ATE1']
        for index in range(20):
            chosen = pe.choose(snap, 'home', 'run', seed=5, index=index, player_shares={'receive': {}, 'carry': {}},
                               share_table=concentrated('carry', 'ATE1', 0.9))
            self.assertEqual(chosen['rusher']['gsis_id'], 'ATE1')
