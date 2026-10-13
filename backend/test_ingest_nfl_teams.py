"""Tests for ingest_nfl_teams.py. No network: the teams file is a synthetic fixture.

Each guard is checked against a broken input, not only a passing one.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_nfl_teams as nt  # noqa: E402

CURRENT = ["ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN", "DET", "GB",
           "HOU", "IND", "JAX", "KC", "LAC", "LAR", "LV", "MIA", "MIN", "NE", "NO", "NYG",
           "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WSH"]
HEADER = "team_abbr,team_name,team_id,team_nick,team_conf,team_division"


def teams_csv(extra_legacy=True):
    lines = [HEADER]
    for code in CURRENT:
        lines.append("%s,Name %s,1,Nick,AFC,AFC East" % (code, code))
    if extra_legacy:
        # nflverse keeps these alongside the current codes.
        lines += ["LA,Los Angeles Rams,1,Rams,NFC,NFC West",
                  "WAS,Washington,1,Commanders,NFC,NFC East",
                  "OAK,Oakland Raiders,1,Raiders,AFC,AFC West",
                  "SD,San Diego Chargers,1,Chargers,AFC,AFC West",
                  "STL,St. Louis Rams,1,Rams,NFC,NFC West"]
    return "\n".join(lines) + "\n"


class ParseTeams(unittest.TestCase):
    def test_legacy_codes_collapse_to_32_canonical(self):
        rows = nt.parse_teams(teams_csv())
        codes = [r["team"] for r in rows]
        self.assertEqual(len(rows), 32)
        self.assertEqual(sorted(codes), sorted(CURRENT))
        for legacy in ("LA", "WAS", "OAK", "SD", "STL"):
            self.assertNotIn(legacy, codes)

    def test_canonical_row_wins_over_alias(self):
        # LAR's own row must be the one kept, not the LA alias row (different name here).
        text = HEADER + "\nLA,Alias Rams,1,R,NFC,NFC West\nLAR,Real Rams,1,R,NFC,NFC West\n"
        rows = nt.parse_teams(text + "\n".join(
            "%s,N,1,N,AFC,AFC East" % c for c in CURRENT if c != "LAR") + "\n")
        lar = [r for r in rows if r["team"] == "LAR"]
        self.assertEqual(len(lar), 1)
        self.assertEqual(lar[0]["team_name"], "Real Rams")

    def test_unknown_code_raises(self):
        with self.assertRaises(Exception):
            nt.parse_teams(HEADER + "\nZZZ,Nope,1,N,AFC,AFC East\n")


class Reconcile(unittest.TestCase):
    def setUp(self):
        self.rows = nt.parse_teams(teams_csv())

    def test_matching_schedule_passes(self):
        nt.reconcile(self.rows, set(CURRENT), 2026)

    def test_schedule_mismatch_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            nt.reconcile(self.rows, set(CURRENT) - {"TB"} | {"XXX"}, 2026)

    def test_wrong_count_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            nt.reconcile(self.rows[:31], set(CURRENT), 2026)

    def test_empty_schedule_exits_nonzero(self):
        with self.assertRaises(SystemExit):
            nt.reconcile(self.rows, set(), 2026)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self._tmp.name, "t.db")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE nfl_schedule (season INTEGER, home_team TEXT, away_team TEXT)")
        for i in range(0, 32, 2):
            con.execute("INSERT INTO nfl_schedule VALUES (2026, ?, ?)", (CURRENT[i], CURRENT[i + 1]))
        con.commit()
        con.close()
        self._orig_db, self._orig_fetch = nt.DB, nt.fetch
        nt.DB = self.db
        nt.fetch = lambda *a, **k: teams_csv()

    def tearDown(self):
        nt.DB, nt.fetch = self._orig_db, self._orig_fetch
        self._tmp.cleanup()

    def test_writes_32_rows_and_rerun_is_idempotent(self):
        self.assertEqual(nt.main([]), 0)
        self.assertEqual(nt.main([]), 0)
        con = sqlite3.connect(self.db)
        n, = con.execute("SELECT COUNT(*) FROM nfl_teams WHERE season=2026").fetchone()
        self.assertEqual(n, 32)
        con.close()

    def test_dry_run_writes_nothing(self):
        self.assertEqual(nt.main(["--dry-run"]), 0)
        con = sqlite3.connect(self.db)
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master")]
        con.close()
        self.assertNotIn("nfl_teams", names)

    def test_bad_schedule_writes_nothing(self):
        con = sqlite3.connect(self.db)
        con.execute("UPDATE nfl_schedule SET home_team='XXX' WHERE home_team='SF'")
        con.commit()
        con.close()
        with self.assertRaises(SystemExit):
            nt.main([])
        con = sqlite3.connect(self.db)
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master")]
        con.close()
        self.assertNotIn("nfl_teams", names)


if __name__ == "__main__":
    unittest.main()
