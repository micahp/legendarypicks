#!/usr/bin/env python3
"""Tests for the props pipeline release gate.

This file exists because props_coverage.py was wired into scripts/release.sh with no
tests at all. A gate nobody tested is a claim about its surface, not about the data: the
2026-08-18 package split shipped two releases with the stats audit silently skipped
because its guard tested a path that had moved, and it stayed green the whole time.

So these assert what the gate REFUSES, not that it runs.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import props_coverage as pc


def _db(path, players, props=(), games=(), results=()):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE players(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          team TEXT, league TEXT NOT NULL, espn_id TEXT, active INTEGER DEFAULT 1,
          updated_at TEXT, UNIQUE(espn_id, league));
        CREATE TABLE prop_games(id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT NOT NULL,
          date TEXT NOT NULL, home TEXT, away TEXT, espn_event_id TEXT,
          final_home INTEGER, final_away INTEGER, start_time TEXT);
        CREATE TABLE props(id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER,
          player_id INTEGER, market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL,
          source TEXT, captured_at TEXT NOT NULL, odds INTEGER, odds_captured_at TEXT);
        CREATE TABLE prop_results(prop_id INTEGER, outcome TEXT);
        """
    )
    con.executemany("INSERT INTO players(name, league, espn_id) VALUES(?,?,?)", players)
    con.executemany(
        "INSERT INTO prop_games(id, league, date, espn_event_id, start_time) VALUES(?,?,?,?,?)",
        games)
    con.executemany(
        "INSERT INTO props(game_id, player_id, market, line, side, source, captured_at)"
        " VALUES(?,?,?,?,?,?,?)", props)
    con.executemany("INSERT INTO prop_results(prop_id, outcome) VALUES(?,?)", results)
    con.commit()
    con.close()
    return path


class SpineDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _measure(self, players):
        return pc.measure(_db(os.path.join(self.tmp, "t.db"), players))

    def test_one_row_with_an_id_and_one_without_is_a_suspected_duplicate(self):
        """The exact shape a harvest produces when it inserts instead of adopting. It
        never raises: the person simply carries half their props."""
        r = self._measure([("Aleksandr Rakic", "ufc", None), ("Aleksandr Rakic", "ufc", "1")])
        self.assertEqual([(d["league"], d["suspected_duplicates"]) for d in r["spine_duplicates"]],
                         [("ufc", 1)])

    def test_two_real_players_sharing_a_name_are_not_a_defect(self):
        """NFL has 442 such groups and NCAAF 171. Counting them makes the number
        unactionable, which is how a check stops being read."""
        r = self._measure([("Josh Allen", "nfl", "1"), ("Josh Allen", "nfl", "2")])
        row = r["spine_duplicates"][0]
        self.assertEqual(row["suspected_duplicates"], 0)
        self.assertEqual(row["distinct_ids_ok"], 1)

    def test_a_unique_name_is_not_reported_at_all(self):
        r = self._measure([("Solo Fighter", "ufc", "1")])
        self.assertEqual(r["spine_duplicates"], [])


class BaselineGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(
            os.path.join(self.tmp, "picks.db"),
            players=[("A", "ufc", "1"), ("A", "ufc", None), ("B", "ufc", "2")],
            games=[(1, "ufc", "2026-08-01", "E1", "2000-01-01T00:00:00")],
            props=[(1, 3, "m", 1.5, "over", "bovada", "2026-08-01")],
            results=[(1, "win")],
        )
        self.result = pc.measure(self.db)

    def _baseline(self, graded=None, dupes=None):
        return {"graded": graded if graded is not None else {"ufc": 100.0},
                "spine_duplicates": dupes if dupes is not None else {"ufc": 1}}

    def test_a_clean_run_reports_no_failures(self):
        self.assertEqual(pc.check_baseline(self.result, self._baseline(), emit=lambda _m: None), [])

    def test_a_grading_drop_beyond_tolerance_fails(self):
        fails = pc.check_baseline(self.result, self._baseline(graded={"ufc": 100.0}),
                                  emit=lambda _m: None)
        self.assertEqual(fails, [])
        self.result["leagues"][0]["settled_pct"] = 40.0
        fails = pc.check_baseline(self.result, self._baseline(graded={"ufc": 100.0}),
                                  emit=lambda _m: None)
        self.assertEqual(len(fails), 1)
        self.assertIn("settled grading", fails[0])

    def test_a_drop_inside_tolerance_does_not_flap(self):
        """The denominator moves as fixtures land; a league sitting exactly on its
        baseline would fail on noise."""
        self.result["leagues"][0]["settled_pct"] = 100.0 - (pc.REGRESSION_TOLERANCE_PCT - 0.1)
        self.assertEqual(pc.check_baseline(self.result, self._baseline(), emit=lambda _m: None), [])

    def test_duplicates_going_up_fails(self):
        fails = pc.check_baseline(self.result, self._baseline(dupes={"ufc": 0}),
                                  emit=lambda _m: None)
        self.assertEqual(len(fails), 1)
        self.assertIn("spine duplicates rose 0 -> 1", fails[0])

    def test_duplicates_going_down_passes(self):
        """A repair must never need the gate edited to land."""
        self.assertEqual(
            pc.check_baseline(self.result, self._baseline(dupes={"ufc": 99}),
                              emit=lambda _m: None), [])

    def test_a_league_with_duplicates_and_no_baseline_fails(self):
        """A new league must not arrive pre-broken and silently accepted."""
        fails = pc.check_baseline(self.result, self._baseline(dupes={}), emit=lambda _m: None)
        self.assertEqual(len(fails), 1)
        self.assertIn("no baseline for this league", fails[0])

    def test_a_duplicate_espn_id_always_fails(self):
        """UNIQUE(espn_id, league) makes this impossible, which is exactly why it is
        checked: a constraint you never verify is a constraint you assume."""
        self.result["duplicate_espn_ids"] = [{"league": "ufc", "espn_id": "1", "n": 2}]
        fails = pc.check_baseline(self.result, self._baseline(), emit=lambda _m: None)
        self.assertEqual(len(fails), 1)
        self.assertIn("espn_id 1 is on 2 rows", fails[0])

    def test_a_missing_baseline_file_is_a_failure_not_a_skip(self):
        """Evidence unavailable is FAIL. Two releases shipped with the stats audit
        skipped because a missing runner was stepped over."""
        original = pc.BASELINE
        pc.BASELINE = os.path.join(self.tmp, "does-not-exist.json")
        try:
            self.assertEqual(pc.main(["--db", self.db, "--check"]), 1)
        finally:
            pc.BASELINE = original

    def test_a_database_absent_from_the_baseline_is_a_failure(self):
        """A database nobody committed an expectation for is a database nothing grades."""
        original = pc.BASELINE
        path = os.path.join(self.tmp, "baseline.json")
        with open(path, "w") as fh:
            json.dump({"some-other.db": self._baseline()}, fh)
        pc.BASELINE = path
        try:
            self.assertEqual(pc.main(["--db", self.db, "--check"]), 1)
        finally:
            pc.BASELINE = original

    def test_the_written_baseline_round_trips_clean(self):
        original = pc.BASELINE
        pc.BASELINE = os.path.join(self.tmp, "written.json")
        try:
            self.assertEqual(pc.main(["--db", self.db, "--write-baseline"]), 0)
            self.assertEqual(pc.main(["--db", self.db, "--check"]), 0)
        finally:
            pc.BASELINE = original


class CurrentHistoryGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = _db(
            os.path.join(self.tmp, "history.db"),
            players=[("Fighter A", "ufc", "1"), ("Fighter B", "ufc", "2")],
            games=[(1, "ufc", "2099-01-01", "E1", "2099-01-01T00:00:00")],
            props=[
                (1, 1, "significant_strikes", 20.5, "over", "underdog", "now"),
                (1, 1, "significant_strikes", 21.5, "under", "underdog", "now"),
                (1, 2, "significant_strikes", 18.5, "over", "underdog", "now"),
            ],
        )
        con = sqlite3.connect(self.db)
        con.executescript("""
            CREATE TABLE player_source_ids(
              source TEXT,league TEXT,source_player_key TEXT,player_id INTEGER);
            CREATE TABLE player_game_logs_ufcstats(
              player_id INTEGER,league TEXT,game_date TEXT,opponent TEXT,stats TEXT);
            INSERT INTO player_source_ids VALUES('ufcstats','ufc','a',1);
            INSERT INTO player_source_ids VALUES('ufcstats','ufc','b',2);
            INSERT INTO player_game_logs_ufcstats
              VALUES(1,'ufc','2026-08-01','Fighter B','{"sigStrikesLanded":30}');
            INSERT INTO player_game_logs_ufcstats
              VALUES(2,'ufc','2026-08-01','Fighter A','{"sigStrikesLanded":12}');
        """)
        con.commit()
        con.close()

    def test_lines_and_sides_collapse_to_one_player_market_denominator(self):
        result = pc.measure_current_history(self.db)

        self.assertEqual(result["pairs"], 2)
        self.assertEqual(result["markets"][0]["n"], 2)
        self.assertEqual(result["markets"][0]["with_history"], 2)
        self.assertEqual(pc.check_current_history(result), [])

    def test_a_three_person_current_ufc_game_fails_the_gate(self):
        con = sqlite3.connect(self.db)
        con.execute(
            "INSERT INTO players(name,league,espn_id) VALUES('Shadow A','ufc',NULL)"
        )
        player_id = con.execute("SELECT MAX(id) FROM players").fetchone()[0]
        con.execute(
            "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at) "
            "VALUES(1,?,'win_by_decision',0.5,'over','bovada','now')",
            (player_id,),
        )
        con.commit()
        con.close()

        result = pc.measure_current_history(self.db)
        failures = pc.check_current_history(result)
        self.assertTrue(any("expected 2" in failure for failure in failures))

if __name__ == "__main__":
    unittest.main()
