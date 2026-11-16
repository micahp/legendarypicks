"""Tests for nfl_sim_scores.py and nfl_sim's "history" scores option. Synthetic pool, no dev DB
(tie_rate and build use a disposable SQLite schedule)."""
import os
import random
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_sim as ns  # noqa: E402
import nfl_sim_scores as nss  # noqa: E402
import test_nfl_sim as tsim  # noqa: E402


def synthetic_pool():
    """Rows spread over expected margin and total, each with an actual score. Expected margin m
    from -14 to 14; the actual result follows the sign of m most of the time, and every 7th game
    is a tie so the tie class is never empty."""
    rows = []
    i = 0
    for season in (2010, 2011, 2012):
        for m in range(-14, 15):
            for tot in (38, 44, 50):
                i += 1
                eh, ea = (tot + m) / 2.0, (tot - m) / 2.0
                if i % 7 == 0:
                    hs = as_ = 17 + (i % 4) * 3
                elif (m >= 0) == (i % 5 != 0):
                    hs, as_ = 24 + i % 10, 17 + i % 6
                else:
                    hs, as_ = 13 + i % 6, 27 + i % 9
                rows.append({"season": season, "week": 2, "game_id": "g%d" % i, "eh": eh,
                             "ea": ea, "hs": hs, "as_": as_, "spread": None, "total": None})
    return rows


class Sampler(unittest.TestCase):
    def setUp(self):
        self.rows = synthetic_pool()
        self.s = nss.HistorySampler(self.rows, 25, 0.01)
        self.pairs = {(r["hs"], r["as_"]) for r in self.rows}

    def test_k_outside_the_grid_is_refused(self):
        with self.assertRaises(ValueError):
            nss.HistorySampler(self.rows, 30, 0.01)

    def test_empty_outcome_class_is_refused(self):
        no_ties = [r for r in self.rows if r["hs"] != r["as_"]]
        with self.assertRaises(ValueError):
            nss.HistorySampler(no_ties, 25, 0.01)

    def test_neighbours_have_the_drawn_outcome_and_are_k_long(self):
        for outcome in nss.OUTCOMES:
            pairs = self.s.pairs(3.0, 44.0, outcome)
            self.assertEqual(len(pairs), min(25, int(self.s.masks[outcome].sum())))
            self.assertTrue(all(nss.outcome_of(h, a) == outcome for h, a in pairs))

    def test_neighbours_are_the_nearest_of_their_class(self):
        idx = self.s.neighbours(10.0, 50.0, "A")
        d = self.s.dist
        zm = (10.0 - d.m_mean) / d.m_sd
        zt = (50.0 - d.t_mean) / d.t_sd
        dist = (d.zm - zm) ** 2 + (d.zt - zt) ** 2
        cls = [i for i in range(len(self.rows)) if self.s.masks["A"][i]]
        worst_in = max(dist[i] for i in idx)
        best_out = min(dist[i] for i in cls if i not in set(idx.tolist()))
        self.assertLessEqual(worst_in, best_out)

    def test_split_keeps_the_conditional_win_probability(self):
        # P(tie) = t, P(home) = (1 - t) p: home share of decisive draws equals p.
        rng = random.Random(5)
        p, t = 0.7, 0.01
        n = 200000
        got = {"H": 0, "A": 0, "T": 0}
        for _ in range(n):
            got[self.s.outcome(p, rng.random())] += 1
        self.assertAlmostEqual(got["T"] / n, t, delta=0.0015)
        self.assertAlmostEqual(got["H"] / (got["H"] + got["A"]), p, delta=0.004)

    def test_draws_are_real_integer_pool_scores(self):
        rng = random.Random(9)
        p, table = self.s.game_table(-4.0, 41.0)
        for _ in range(2000):
            h, a = self.s.draw(rng, p, table)
            self.assertIsInstance(h, int)
            self.assertIn((h, a), self.pairs)

    def test_conditional_pair_probability_sums_to_one_over_neighbours(self):
        probs, denom = self.s.cond_pair_probability(2.0, 44.0, "H")
        self.assertAlmostEqual(sum(probs.values()), 1.0)
        self.assertGreater(denom, 25)


def schedule_db(seasons, ties_in=None):
    tmp = tempfile.TemporaryDirectory()
    con = sqlite3.connect(os.path.join(tmp.name, "s.db"))
    con.execute("CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, week INT, "
                "home_team TEXT, away_team TEXT, home_score INT, away_score INT)")
    for s in seasons:
        for g in range(100):
            tie = ties_in and s in ties_in and g == 0
            con.execute("INSERT INTO nfl_schedule VALUES (?,?,?,?,?,?,?,?)",
                        ("%d_%d" % (s, g), s, "REG", 2, "A", "B", 20, 20 if tie else 17))
    return tmp, con


class TieRate(unittest.TestCase):
    def test_rate_uses_earlier_seasons_only(self):
        tmp, con = schedule_db(range(2010, 2014), ties_in={2011, 2013})
        try:
            rate, ties, games = nss.tie_rate(con, 2013)      # 2010-2012: one tie in 300
            self.assertEqual((ties, games), (1, 300))
            self.assertAlmostEqual(rate, 1 / 300.0)
        finally:
            con.close()
            tmp.cleanup()

    def test_missing_season_is_refused(self):
        tmp, con = schedule_db([2010, 2012])
        try:
            with self.assertRaises(ValueError):
                nss.tie_rate(con, 2013)
        finally:
            con.close()
            tmp.cleanup()

    def test_build_never_pools_the_target_season(self):
        tmp, con = schedule_db(range(2010, 2014), ties_in={2010})
        try:
            rows = synthetic_pool() + [dict(r, season=2013) for r in synthetic_pool()]
            s = nss.build(con, 2013, 25, rows=rows)
            self.assertEqual(s.info["pool_games"], len(synthetic_pool()))
            self.assertEqual(s.info["pool_seasons"], [2010, 2012])
            with self.assertRaises(ValueError):                 # 2012 missing from the pool
                nss.build(con, 2013, 25, rows=[r for r in rows if r["season"] != 2012])
        finally:
            con.close()
            tmp.cleanup()


def history_league(tie_rate=0.003):
    inp = tsim.league()
    inp["remaining_totals"] = [44.0] * len(inp["remaining"])
    return ns.attach_history(inp, nss.HistorySampler(synthetic_pool(), 25, tie_rate))


class SimHistory(unittest.TestCase):
    def test_placeholder_is_still_the_default_and_unchanged(self):
        self.assertEqual(ns.DEFAULT_SCORES, "placeholder")
        games = ns.simulate_games(tsim.league(), random.Random(1))
        self.assertTrue(all(h + a == 40.0 for _, _, _, h, a in games))

    def test_unknown_option_is_refused(self):
        inp = tsim.league()
        inp["scores"] = "normal"
        with self.assertRaises(ValueError):
            ns.simulate_games(inp, random.Random(1))

    def test_history_games_are_integer_real_scores(self):
        inp = history_league()
        pairs = {(r["hs"], r["as_"]) for r in synthetic_pool()}
        games = ns.simulate_games(inp, random.Random(2))
        self.assertEqual(len(games), len(inp["remaining"]))
        for _, _, _, h, a in games:
            self.assertIsInstance(h, int)
            self.assertIn((h, a), pairs)
        self.assertGreater(len({h + a for _, _, _, h, a in games}), 5)

    def test_history_run_passes_sanity_and_strong_team_still_leads(self):
        out = ns.run(history_league(), 300, seed=3)
        self.assertTrue(ns.sanity(out, tsim.CONF_OF))
        self.assertGreater(out["teams"]["N0a"]["p_playoffs"], 0.9)
        self.assertLess(out["teams"]["N3b"]["p_playoffs"], 0.5)   # baseline 7 of 8 = 0.875

    def test_win_rate_follows_the_normal_probability(self):
        # Home win share of decisive simulated games, for a game with expected margin +6.
        inp = history_league()
        inp["remaining"] = [(1, "A0a", "A0b", False, 6.0)] * 4000
        inp["remaining_totals"] = [44.0] * 4000
        games = ns.simulate_games(inp, random.Random(4))
        dec = [g for g in games if g[3] != g[4]]
        p = nss.phi(6.0 / 13.295)
        self.assertAlmostEqual(sum(1 for g in dec if g[3] > g[4]) / len(dec), p, delta=0.025)

    def test_every_game_a_tie_still_seeds(self):
        # A season where almost every simulated game is a tie: the seeding engine must still
        # produce a valid field (ties as half wins everywhere), not crash.
        out = ns.run(history_league(tie_rate=0.999), 50, seed=5)
        self.assertTrue(ns.sanity(out, tsim.CONF_OF))

    def test_hot_update_uses_the_integer_drawn_margin(self):
        inp = history_league()
        inp["remaining"] = inp["remaining"][:3]
        inp["remaining_totals"] = inp["remaining_totals"][:3]
        rng = random.Random(6)
        games = ns.simulate_games(inp, rng, k=0.1)
        # Replay by hand: same rng stream, deltas from integer margins.
        rng = random.Random(6)
        s, deltas = inp["sampler"], {}
        for (wk, h, a, _, em), tot, g in zip(inp["remaining"], inp["remaining_totals"], games):
            e = em + deltas.get(h, 0.0) - deltas.get(a, 0.0)
            o = s.outcome(s.p_home(e), rng.random())
            pairs = s.pairs(e, tot, o)
            hs, as_ = pairs[rng.randrange(len(pairs))]
            self.assertEqual((hs, as_), (g[3], g[4]))
            deltas = ns.hot_update(deltas, h, a, (hs - as_) - e, 0.1)
        out = ns.run(inp, 20, k=0.1, seed=7)
        self.assertEqual(out["n"], 20)

    def test_attach_requires_totals(self):
        inp = tsim.league()
        with self.assertRaises(ValueError):
            ns.attach_history(inp, nss.HistorySampler(synthetic_pool(), 25, 0.003))



class WinsCountTiesHalf(unittest.TestCase):
    """wins_mean and the win percentiles count a tie as half a win, for both score options."""

    def played_tie(self, inp):
        inp = dict(inp)
        inp["played"] = [(1, "A0a", "A0b", 17.0, 17.0)]
        return inp

    def check(self, inp, seed):
        rng = random.Random(seed)
        _, wins, _ = ns.one_run(inp, rng)
        games = ns.simulate_games(inp, random.Random(seed))
        teams = __import__("nfl_standings").build(inp["tmap"], games)
        for code in ("A0a", "A0b"):
            t = teams[code]
            self.assertGreaterEqual(t.ties, 1)
            self.assertEqual(wins[code], t.wins + 0.5 * t.ties)

    def test_placeholder_counts_a_played_tie_half(self):
        self.check(self.played_tie(tsim.league()), 3)

    def test_history_counts_a_played_tie_half(self):
        self.check(self.played_tie(history_league()), 4)

    def test_wins_mean_includes_the_half(self):
        inp = tsim.league()
        inp["played"] = [(1, "A0a", "A0b", 17.0, 17.0)]
        inp["remaining"] = []
        out = ns.run(inp, 5, seed=1)
        self.assertEqual(out["teams"]["A0a"]["wins_mean"], 0.5)
        self.assertEqual(out["teams"]["A0a"]["wins_p10"], 0.5)
        self.assertEqual(out["teams"]["A1a"]["wins_mean"], 0)

    def test_placeholder_without_ties_is_unchanged(self):
        # No ties possible: integer win counts, exactly as before the change.
        out = ns.run(tsim.league(), 50, seed=9)
        for t in out["teams"].values():
            self.assertIsInstance(t["wins_p10"], int)


if __name__ == "__main__":
    unittest.main()
