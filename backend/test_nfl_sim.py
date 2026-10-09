"""Tests for nfl_sim.py on a synthetic 16-team league with known strengths. No database.

The sanity assertions of spec 6.3 are run on every output. The hot update is checked on its own.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import nfl_sim as ns  # noqa: E402

TMAP = {}
DIVS = {"AFC": ["AFC East", "AFC North", "AFC South", "AFC West"],
        "NFC": ["NFC East", "NFC North", "NFC South", "NFC West"]}
for conf, divs in DIVS.items():
    for i, d in enumerate(divs):
        TMAP["%s%d%s" % (conf[0], i, "a")] = (conf, d)
        TMAP["%s%d%s" % (conf[0], i, "b")] = (conf, d)
STRENGTH = {c: 0.0 for c in TMAP}
STRENGTH["N0a"] = 12.0          # a planted strong team
STRENGTH["N3b"] = -12.0         # a planted weak team
CONF_OF = {c: v[0] for c, v in TMAP.items()}


def league(strength=STRENGTH, sigma=13.295):
    remaining = []
    week = 0
    for conf in ("AFC", "NFC"):
        members = sorted(c for c in TMAP if CONF_OF[c] == conf)
        for i, h in enumerate(members):
            for a in members[i + 1:]:
                week += 1
                remaining.append((1 + week % 18, h, a, False, strength[h] - strength[a]))
    return {"season": 2026, "through_week": 0, "fit": None, "played": [], "remaining": remaining,
            "tmap": TMAP, "sigma": sigma}


class Output(unittest.TestCase):
    def test_sanity_holds_on_a_synthetic_league(self):
        out = ns.run(league(), 300, k=0.0, seed=7)
        self.assertTrue(ns.sanity(out, CONF_OF))

    def test_strong_team_makes_playoffs_weak_team_does_not(self):
        out = ns.run(league(), 300, k=0.0, seed=7)
        self.assertGreater(out["teams"]["N0a"]["p_playoffs"], 0.9)
        # 7 of 8 teams per conference make it, so the baseline is 0.875. A team 12 points worse
        # than every opponent still gets in sometimes (ties at the cut), but far less often.
        self.assertLess(out["teams"]["N3b"]["p_playoffs"], 0.5)

    def test_same_seed_reproduces_exactly(self):
        a = ns.run(league(), 200, k=0.0, seed=3)
        b = ns.run(league(), 200, k=0.0, seed=3)
        self.assertEqual(a["teams"], b["teams"])

    def test_different_seed_moves_odds_only_a_little(self):
        a = ns.run(league(), 2000, k=0.0, seed=11)
        b = ns.run(league(), 2000, k=0.0, seed=12)
        worst = max(abs(a["teams"][t]["p_playoffs"] - b["teams"][t]["p_playoffs"]) for t in TMAP)
        self.assertLess(worst, 0.06)  # Monte Carlo noise at n=2000, not the spec's 1.5 points

    def test_sanity_catches_a_broken_output(self):
        out = ns.run(league(), 100, k=0.0, seed=5)
        out["teams"]["N0a"]["p_playoffs"] += 1.0
        with self.assertRaises(AssertionError):
            ns.sanity(out, CONF_OF)


class InputsFromDatabase(unittest.TestCase):
    """Regression: a scored game after a complete week must not be dropped from the simulation."""

    def setUp(self):
        import sqlite3
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.con = sqlite3.connect(os.path.join(self._tmp.name, "t.db"))
        self.con.execute("CREATE TABLE nfl_teams (season INT, team TEXT, conference TEXT, "
                         "division TEXT, team_name TEXT, source TEXT)")
        codes = ["T%02d" % i for i in range(32)]
        for i, c in enumerate(codes):
            conf = "AFC" if i < 16 else "NFC"
            self.con.execute("INSERT INTO nfl_teams VALUES (2026,?,?,?,'','x')",
                             (c, conf, "%s %s" % (conf, ["East", "North", "South", "West"][(i % 16) // 4])))
        self.con.execute("CREATE TABLE nfl_schedule (game_id TEXT, season INT, game_type TEXT, "
                         "week INT, home_team TEXT, away_team TEXT, location TEXT, home_score REAL,"
                         " away_score REAL, gameday TEXT, gametime TEXT)")
        # Weeks 1-4 complete (16 games each), week 5 has one scored game and one unscored.
        for wk in range(1, 5):
            for i in range(16):
                h, a = codes[2 * i], codes[2 * i + 1]
                self.con.execute("INSERT INTO nfl_schedule VALUES (?,2026,'REG',?,?,?,'Home',20,17,"
                                 "?,'13:00')", ("g%d_%d" % (wk, i), wk, h, a, "2026-09-%02d" % wk))
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g5_scored',2026,'REG',5,'T00','T02',"
                         "'Home',24,16,'2026-10-08','20:15')")
        self.con.execute("INSERT INTO nfl_schedule VALUES ('g5_open',2026,'REG',5,'T04','T06',"
                         "'Home',NULL,NULL,'2026-10-11','13:00')")
        self.con.commit()

    def tearDown(self):
        self.con.close()
        self._tmp.cleanup()

    def test_scored_week_five_game_is_played_not_dropped(self):
        inp = ns.inputs(self.con, 2026)
        total = self.con.execute("SELECT COUNT(*) FROM nfl_schedule").fetchone()[0]
        self.assertEqual(len(inp["played"]) + len(inp["remaining"]), total)
        self.assertTrue(any(p[1:3] == ("T00", "T02") for p in inp["played"]))
        self.assertFalse(any(r[1:3] == ("T00", "T02") for r in inp["remaining"]))
        self.assertEqual(inp["through_week"], 5)


class HotUpdate(unittest.TestCase):
    def test_home_moves_up_away_moves_down_by_k_times_residual(self):
        d = ns.hot_update({}, "H", "A", residual=10.0, k=0.05)
        self.assertAlmostEqual(d["H"], 0.5, places=12)
        self.assertAlmostEqual(d["A"], -0.5, places=12)

    def test_input_is_not_modified(self):
        base = {"H": 1.0}
        ns.hot_update(base, "H", "A", 4.0, 0.1)
        self.assertEqual(base, {"H": 1.0})

    def test_cold_and_hot_runs_differ(self):
        cold = ns.run(league(), 300, k=0.0, seed=9)
        hot = ns.run(league(), 300, k=0.5, seed=9)
        self.assertNotEqual(cold["teams"]["N0a"]["wins_mean"], hot["teams"]["N0a"]["wins_mean"])


if __name__ == "__main__":
    unittest.main()
