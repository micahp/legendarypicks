#!/usr/bin/env python3
"""Contracts for the FotMob soccer log ingest.

The fixture below is shaped from a real matchDetails response, field for field:
each stat is `{"key": ..., "stat": {"value": ..}}`, and FotMob's key vocabulary
is genuinely inconsistent -- `total_shots` snake_case, `ShotsOnTarget`
camelCase, and tackles as `matchstats.headers.tackles`, an i18n path leaked into
the data. A fixture that tidied those up would define a world in which the
mapping cannot be got wrong.
"""
import json
import os
import sqlite3
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_fotmob_soccer_logs as fm  # noqa: E402


def _provider_tables(con):
    """Create FotMob's table and the joining view from the MIGRATION's own DDL.

    Not a copy. A fixture that declares its own version of a shipped schema is a
    claim about that schema, and the two drift: earlier fixtures in this file
    declared `player_game_logs` without the `source` column the real table has,
    so they described a world where the reader could not tell providers apart.
    Importing the DDL means a schema change cannot pass these tests while
    breaking production.
    """
    import scripts_split_provider_logs as split
    split.ensure_espn_columns(con)
    con.executescript(split.DDL_TABLE)
    con.executescript(split.DDL_VIEW)



def _stat(key, value):
    return {"key": key, "stat": {"value": value, "type": "integer"}}


def player(name, **stats):
    return {"name": name, "stats": [{"title": "Top stats", "stats": stats}]}


class TheStatMapReadsTheMachineKey(unittest.TestCase):
    def test_the_inconsistent_keys_all_map(self):
        line = fm.stat_line(player(
            "A Player",
            **{"Minutes played": _stat("minutes_played", 90),
               "Total shots": _stat("total_shots", 3),
               "Shots on target": _stat("ShotsOnTarget", 2),
               "Tackles": _stat("matchstats.headers.tackles", 4),
               "Successful dribbles": _stat("dribbles_succeeded", 1),
               "Accurate passes": _stat("accurate_passes", 55)}))
        self.assertEqual(line, {"minutes": 90.0, "shots": 3.0,
                                "shots_on_target": 2.0, "tackles": 4.0,
                                "dribbles": 1.0, "passes": 55.0})

    def test_the_label_carries_it_when_the_key_changes(self):
        # `matchstats.headers.tackles` is a leaked i18n path, exactly the kind
        # of thing that gets cleaned up upstream. The label must still find it.
        line = fm.stat_line(player(
            "A Player", **{"Tackles": _stat("tackles_renamed_upstream", 6)}))
        self.assertEqual(line, {"tackles": 6.0})

    def test_a_compound_string_keeps_the_count_not_the_percentage(self):
        line = fm.stat_line(player(
            "A Player", **{"Accurate passes": _stat("accurate_passes",
                                                    "43 (72%)")}))
        self.assertEqual(line, {"passes": 43.0})


class AmbiguityFailsClosed(unittest.TestCase):
    def test_one_spine_row_resolves(self):
        index = {"juan dominguez": [{"id": 7, "team": "LEO", "espn_id": "1"}]}
        self.assertEqual(fm.resolve(index, "Juan Domínguez")["id"], 7)

    def test_two_spine_rows_resolve_to_neither(self):
        # An ambiguous key does not raise, it silently attributes a match to
        # the wrong player.
        index = {"juan dominguez": [{"id": 7, "team": "LEO", "espn_id": "1"},
                                    {"id": 8, "team": "AME", "espn_id": "2"}]}
        self.assertIsNone(fm.resolve(index, "Juan Dominguez"))

    def test_no_spine_row_resolves_to_none(self):
        self.assertIsNone(fm.resolve({}, "Nobody Here"))


class TheProvidersKeepSeparateRows(unittest.TestCase):
    """Each provider owns its rows and nothing edits another's.

    This once merged FotMob's line into the ESPN row for the same date, one row
    per appearance. That left a row stamped `source='espn'` carrying
    FotMob-sourced tackles, so the column named the row's creator rather than
    each field's origin. Reverted; the cost is that one appearance can have two
    rows, which every READER must resolve. See OneRowPerAppearance in
    test_props_history.py for the reader half of this contract.
    """

    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="fm-", suffix=".db",
                                             delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.con = sqlite3.connect(self.path)
        self.con.executescript("""
            CREATE TABLE player_game_logs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER,
              league TEXT NOT NULL, season INTEGER NOT NULL, game_no TEXT,
              game_id TEXT, game_date TEXT, stats TEXT NOT NULL, source TEXT,
              source_player_key TEXT,
              UNIQUE(league, source_player_key, season, game_no)
            );
        """)
        _provider_tables(self.con)
        self.addCleanup(self.con.close)

    def _rows(self):
        """FotMob's rows, from FotMob's table. `player_game_logs` is ESPN's."""
        return self.con.execute(
            "SELECT stats, source FROM player_game_logs_fotmob").fetchall()

    def test_it_writes_its_own_row_and_leaves_the_espn_row_alone(self):
        self.con.execute(
            "INSERT INTO player_game_logs(player_id, league, season, game_no,"
            " game_id, game_date, stats, source, source_player_key)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (7, "ligamx", 2026, "401877001", "401877001", "2026-08-24",
             json.dumps({"goals": 0, "shots": 2}), "espn", "49306"))
        self.con.commit()
        who = {"id": 7, "team": "LEO", "espn_id": "49306"}
        result = fm.upsert(self.con, "ligamx", 2026, who, 1000014543,
                           "2026-08-24", {"tackles": 4.0, "shots": 99.0}, False,
                           fotmob_id=880042)
        self.assertEqual(result, "inserted")

        # Each provider's line is in its provider's TABLE.
        espn = self.con.execute(
            "SELECT stats, source FROM player_game_logs").fetchall()
        fotmob = self._rows()
        self.assertEqual(len(espn), 1, "ESPN's table gains no row")
        self.assertEqual(len(fotmob), 1, "FotMob writes exactly its own row")
        # The ESPN row is untouched: it never learns a stat ESPN never published.
        self.assertEqual(json.loads(espn[0][0]), {"goals": 0, "shots": 2})
        self.assertEqual(espn[0][1], "espn")
        self.assertEqual(json.loads(fotmob[0][0]), {"tackles": 4.0, "shots": 99.0})
        self.assertEqual(fotmob[0][1], "fotmob")

    def test_the_view_puts_one_appearance_on_one_row(self):
        """The point of the split: two providers, one row, provenance by COLUMN."""
        self.con.execute(
            "INSERT INTO player_game_logs(player_id, league, season, game_no,"
            " game_id, game_date, stats, source, source_player_key)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (7, "ligamx", 2026, "401877001", "401877001", "2026-08-24",
             json.dumps({"goals": 0, "shots": 2}), "espn", "49306"))
        fm.upsert(self.con, "ligamx", 2026,
                  {"id": 7, "team": "LEO", "espn_id": "49306"}, 1000014543,
                  "2026-08-24", {"tackles": 4.0}, False, fotmob_id=880042)
        self.con.commit()
        rows = self.con.execute(
            "SELECT espn_stats, fotmob_stats FROM player_game_logs_all"
            " WHERE player_id=7").fetchall()
        self.assertEqual(len(rows), 1, "one appearance is one row")
        self.assertEqual(json.loads(rows[0][0])["shots"], 2)
        self.assertEqual(json.loads(rows[0][1])["tackles"], 4.0)

    def test_the_key_identifies_the_player_not_the_fixture(self):
        """`fotmob-{match}-{team}` was one string for all eleven on a side, so
        UNIQUE(league, source_player_key, season, game_no) kept ONE row per team
        per match and INSERT OR IGNORE dropped the rest silently: a run that
        reported 795 inserts wrote 131."""
        for espn_id, fotmob_id in ((7, 880042), (8, 880043), (9, 880044)):
            fm.upsert(self.con, "ligamx", 2026,
                      {"id": espn_id, "team": "LEO", "espn_id": str(espn_id)},
                      1000014543, "2026-08-24", {"tackles": 1.0}, False,
                      fotmob_id=fotmob_id)
        self.assertEqual(len(self._rows()), 3,
                         "three team-mates in one fixture are three rows")

    def test_an_unresolved_player_is_retained_not_dropped(self):
        result = fm.upsert(self.con, "ligamx", 2026, None, 1000014543,
                           "2026-08-24", {"tackles": 1.0}, False)
        self.assertEqual(result, "inserted")
        self.assertEqual(len(self._rows()), 1)
        self.assertIsNone(self.con.execute(
            "SELECT player_id FROM player_game_logs_fotmob").fetchone()[0])
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_game_logs").fetchone()[0], 0,
            "an unresolved FotMob row never lands in ESPN's table")


class TheSpineIsTheLeaguesThatOwnTheAthletes(unittest.TestCase):
    """`players WHERE league='lcup'` has always held zero rows.

    Written after the same defect was fixed in four other places tonight, and
    introduced here anyway: 0 of 1,905 players resolved, 55 orphan rows written.
    """

    def test_lcup_reads_the_domestic_spines(self):
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY, name TEXT, team TEXT,
                                 league TEXT, espn_id TEXT);
        """)
        con.executemany("INSERT INTO players VALUES(?,?,?,?,?)",
                        [(1, "MLS Guy", "CLB", "mls", "10"),
                         (2, "Liga MX Guy", "AME", "ligamx", "20"),
                         (3, "Someone Else", "NYY", "mlb", "30")])
        index = fm.spine(con, "lcup")
        self.assertIsNotNone(fm.resolve(index, "MLS Guy"))
        self.assertIsNotNone(fm.resolve(index, "Liga MX Guy"))
        # Still scoped: a competition's spine is not every player we hold.
        self.assertIsNone(fm.resolve(index, "Someone Else"))


if __name__ == "__main__":
    unittest.main()
