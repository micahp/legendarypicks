"""Tests for nfl_epa_model.py and the v2 projection path. Synthetic plays, no network.

Each test plants something a wrong model would miss: a team whose pass offense is better and
rush offense is not, plays from a later week that must not move an earlier fit, a neutral site
that must carry no home term, and a conversion whose true a, b, h are known.
"""
import os
import random
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_epa_model as em  # noqa: E402

TEAMS = ["AAA", "BBB", "CCC", "DDD"]


def synth_plays(weeks=6, plays_per_side=60, pass_edge=None, seed=7):
    """(week, game_id, posteam, defteam, home, pass_attempt, epa) for a round robin."""
    pass_edge = pass_edge or {"AAA": 0.25}
    rng = random.Random(seed)
    rows = []
    for wk in range(1, weeks + 1):
        for i, home in enumerate(TEAMS):
            for away in TEAMS:
                if home == away:
                    continue
                gid = "w%d_%s_%s" % (wk, home, away)
                for off, dfn in ((home, away), (away, home)):
                    for k in range(plays_per_side):
                        is_pass = 1 if k % 5 < 3 else 0
                        mean = pass_edge.get(off, 0.0) if is_pass else 0.0
                        rows.append((wk, gid, off, dfn, home, is_pass, mean + rng.gauss(0, 0.4)))
    return rows


class Ratings(unittest.TestCase):
    def test_planted_pass_offense_ranks_first_on_pass_only(self):
        r = em.fit(synth_plays(), TEAMS)
        best_pass = max(TEAMS, key=lambda t: r.off["pass"][t])
        self.assertEqual(best_pass, "AAA")
        self.assertGreater(r.off["pass"]["AAA"] - max(r.off["pass"][t] for t in TEAMS[1:]), 0.15)
        self.assertLess(abs(r.off["rush"]["AAA"]), 0.08)

    def test_pace_and_pass_rate_come_from_the_plays(self):
        r = em.fit(synth_plays(), TEAMS)
        self.assertAlmostEqual(r.plays_pg["BBB"], 60.0)
        self.assertAlmostEqual(r.pass_rate["BBB"], 36 / 60)

    def test_prior_pulls_a_thin_fit(self):
        rows = synth_plays(weeks=1, plays_per_side=5)
        prior = em.fit(synth_plays(pass_edge={"BBB": 0.4}), TEAMS)
        r = em.fit(rows, TEAMS, prior=em.shrink(prior), lam=1e6)
        self.assertAlmostEqual(r.off["pass"]["BBB"], prior.off["pass"]["BBB"] * (2 / 3), places=3)


class Leakage(unittest.TestCase):
    def test_plays_query_never_reads_the_week_being_projected(self):
        tmp = tempfile.TemporaryDirectory()
        con = sqlite3.connect(os.path.join(tmp.name, "t.db"))
        con.execute("CREATE TABLE nfl_pbp (season INT, week INT, game_id TEXT, posteam TEXT, "
                    "defteam TEXT, home_team TEXT, pass_attempt INT, rush_attempt INT, epa REAL)")
        for wk, gid, pos, dfn, home, pa, epa in synth_plays(weeks=4):
            con.execute("INSERT INTO nfl_pbp VALUES (2026,?,?,?,?,?,?,?,?)",
                        (wk, gid, pos, dfn, home, pa, 1 - pa, epa))
        # Plant an absurd week 4: if it leaks, AAA's pass rating explodes.
        con.execute("UPDATE nfl_pbp SET epa = 50 WHERE week = 4 AND posteam = 'AAA'")
        con.commit()
        rows = em.plays(con, 2026, before_week=4)
        self.assertEqual({r[0] for r in rows}, {1, 2, 3})
        r = em.fit(rows, TEAMS)
        self.assertLess(r.off["pass"]["AAA"], 1.0)
        con.close()
        tmp.cleanup()


class Conversion(unittest.TestCase):
    def test_calibrate_recovers_known_a_b_h(self):
        rng = random.Random(3)
        obs = []
        for _ in range(400):
            p = rng.uniform(-10, 10)
            side = rng.choice([1, -1, 0])
            obs.append((p, side, 22.0 + 0.7 * p + 2.0 * side * 0.5 + rng.gauss(0, 0.5)))
        a, b, h = em.calibrate(obs)
        self.assertAlmostEqual(a, 22.0, delta=0.15)
        self.assertAlmostEqual(b, 0.7, delta=0.02)
        self.assertAlmostEqual(h, 2.0, delta=0.15)


class NeutralSite(unittest.TestCase):
    """Builds the real v2 projector (lock_nfl_epa.build) from a synthetic two-season DB."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute("CREATE TABLE nfl_pbp (season INT, week INT, game_id TEXT, posteam TEXT, "
                         "defteam TEXT, home_team TEXT, pass_attempt INT, rush_attempt INT, "
                         "epa REAL)")
        self.con.execute("CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, "
                         "week INT, home_team TEXT, away_team TEXT, location TEXT, "
                         "home_score REAL, away_score REAL, spread_line REAL, total_line REAL)")
        rng = random.Random(11)
        for season, weeks in ((2025, 8), (2026, 4)):
            for wk, gid, pos, dfn, home, pa, epa in synth_plays(weeks=weeks, plays_per_side=20,
                                                                seed=season):
                self.con.execute("INSERT INTO nfl_pbp VALUES (?,?,?,?,?,?,?,?,?)",
                                 (season, wk, "%d_%s" % (season, gid), pos, dfn, home, pa, 1 - pa,
                                  epa))
            for wk in range(1, weeks + 1):
                for h in TEAMS:
                    for a in TEAMS:
                        if h != a:
                            self.con.execute(
                                "INSERT INTO nfl_schedule VALUES (?,?,'REG',?,?,?,'Home',?,?,1,44)",
                                ("%d_w%d_%s_%s" % (season, wk, h, a), season, wk, h, a,
                                 20 + rng.randint(0, 14) + (7 if h == "AAA" else 0),
                                 20 + rng.randint(0, 14) + (7 if a == "AAA" else 0)))
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def test_neutral_game_differs_from_home_by_exactly_h(self):
        import lock_nfl_epa as le
        project, info = le.build(self.con, 2026, 4)
        ph, pa, p_neutral = project("AAA", "BBB", True)
        qh, qa, p_home = project("AAA", "BBB", False)
        self.assertAlmostEqual((qh - qa) - (ph - pa), info["h"])
        self.assertAlmostEqual(ph + pa, qh + qa)       # home field moves the margin, not the total
        self.assertTrue(0.0 < p_neutral < 1.0)

    def test_build_never_reads_the_week_being_locked(self):
        import lock_nfl_epa as le
        _, before = le.build(self.con, 2026, 4)
        self.con.execute("UPDATE nfl_pbp SET epa = 50 WHERE season = 2026 AND week = 4")
        self.con.execute("UPDATE nfl_schedule SET home_score = 99 WHERE season = 2026 AND week = 4")
        self.con.commit()
        _, after = le.build(self.con, 2026, 4)
        self.assertEqual((before["a"], before["b"], before["sigma"]),
                         (after["a"], after["b"], after["sigma"]))


if __name__ == "__main__":
    unittest.main()
