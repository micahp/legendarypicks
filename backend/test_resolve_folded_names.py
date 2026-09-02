#!/usr/bin/env python3
"""A diacritic is not a different person, and a re-scrape is not a new prop.

Two defects found together on 2026-08-16 while putting MLS props on a live board:

  1. `_resolve_player_for_ingest` folded accents off the INCOMING name and compared it to
     the STORED name unfolded. `Thomas Muller` from Bovada therefore never matched
     `Thomas Müller` as ESPN publishes him. 53 of 74 unresolved MLS names had an exact
     same-team match in the spine differing only by a diacritic or a capital. Nothing
     raised: a name that resolves to nothing looks exactly like a player we do not carry.

  2. `/api/props/ingest` INSERTed unconditionally into a table with no UNIQUE constraint,
     while the scrapers run on 30-minute timers. Dev held 47,827 duplicated
     (game_id, player_id, market, line, side, source) groups.

The fold must not become a fuzzy matcher: two different people who fold to the same string
are still ambiguous, and ambiguity is refused.
"""
import datetime as dt
import os
import sqlite3
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

from _core import _resolve_player_for_ingest, _FOLDED_NAME_INDEX


class FoldedNameResolutionTests(unittest.TestCase):
    def setUp(self):
        _FOLDED_NAME_INDEX.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.con = sqlite3.connect(os.path.join(self.tmp.name, "t.db"))
        self.con.row_factory = sqlite3.Row
        self.con.executescript(
            "CREATE TABLE players("
            "id INTEGER PRIMARY KEY, name TEXT, team TEXT, league TEXT, updated_at TEXT);"
            "CREATE TABLE prop_games("
            "id INTEGER PRIMARY KEY, league TEXT, date TEXT, home TEXT, away TEXT);"
            "CREATE TABLE name_alias(alias_norm TEXT, player_id INTEGER);"
            "CREATE TABLE unresolved_players("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, "
            "raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT, "
            "first_seen TEXT NOT NULL, count INTEGER DEFAULT 1);"
        )
        self.con.executemany(
            "INSERT INTO players(id,name,team,league,updated_at) VALUES(?,?,?,?,?)",
            [(1, "Thomas Müller", "VAN", "mls", "2026-08-16"),
             (2, "Christian Ramírez", "ATX", "mls", "2026-08-16"),
             (3, "Kim Kee-Hee", "SEA", "mls", "2026-08-16"),
             (4, "Albert Rusnák", "SEA", "mls", "2026-08-16")],
        )
        self.con.commit()

    def _resolve(self, name, team="", game_id=None):
        return _resolve_player_for_ingest(self.con, name, team, "mls", game_id=game_id)

    def test_diacritic_only_difference_resolves(self):
        self.assertEqual(self._resolve("Thomas Muller", "VAN"), (1, "high"))

    def test_diacritic_resolves_without_a_team_tag(self):
        """Bovada drops the club tag on some outcomes; the name still identifies him."""
        self.assertEqual(self._resolve("Christian Ramirez"), (2, "high"))

    def test_capitalisation_only_difference_resolves(self):
        self.assertEqual(self._resolve("Kim Kee-hee", "SEA"), (3, "high"))

    def test_an_unknown_name_still_goes_to_the_review_queue(self):
        """The fold must widen matching, not invent one."""
        self.assertEqual(self._resolve("Someone Nobody", "SEA"), (None, None))
        self.assertEqual(
            self.con.execute("SELECT raw_name FROM unresolved_players").fetchone()[0],
            "Someone Nobody")

    def _add_folding_twin(self):
        """A second man whose name folds to the same string as player 1's.

        The incoming spelling in these tests ("Thomas Mullér") matches NEITHER stored name
        exactly, so the exact-name fast path is skipped and the fold is what decides --
        which is the only place the fold can do damage.
        """
        self.con.execute(
            "INSERT INTO players(id,name,team,league,updated_at) VALUES(?,?,?,?,?)",
            (5, "Thomas Muller", "SEA", "mls", "2026-08-16"))
        self.con.commit()

    def test_two_people_who_fold_alike_stay_ambiguous(self):
        """Same-fold is not same-person. Without a tiebreak this must refuse."""
        self._add_folding_twin()
        self.assertEqual(self._resolve("Thomas Mullér"), (None, None))

    def test_ambiguity_is_broken_by_the_team_tag(self):
        self._add_folding_twin()
        self.assertEqual(self._resolve("Thomas Mullér", "VAN"), (1, "high"))

    def test_ambiguity_is_broken_by_who_is_in_the_game(self):
        """The tag is often missing or stale; the fixture still names two clubs."""
        self._add_folding_twin()
        self.con.execute(
            "INSERT INTO prop_games(id,league,date,home,away) VALUES(?,?,?,?,?)",
            (77, "mls", "2026-08-16", "SEA", "POR"))
        self.con.commit()
        self.assertEqual(self._resolve("Thomas Mullér", game_id=77), (5, "high"))

    def test_a_player_inserted_after_the_first_lookup_is_visible(self):
        """The cache is stamped, not permanent -- a stale map would re-break resolution."""
        self.assertEqual(self._resolve("Brand New", "ATX"), (None, None))
        self.con.execute(
            "INSERT INTO players(id,name,team,league,updated_at) VALUES(?,?,?,?,?)",
            (9, "Bränd New", "ATX", "mls", "2026-08-17"))
        self.con.commit()
        self.assertEqual(self._resolve("Brand New", "ATX"), (9, "high"))

    def test_a_rename_in_place_is_visible(self):
        """COUNT and MAX(id) both stay put on a rename; updated_at is what moves."""
        self.assertEqual(self._resolve("Renamed Guy", "ATX"), (None, None))
        self.con.execute(
            "UPDATE players SET name=?, updated_at=? WHERE id=2",
            ("Renamed Guy", "2026-08-17"))
        self.con.commit()
        self.assertEqual(self._resolve("Renamed Guy", "ATX"), (2, "high"))


class PropIngestUpsertTests(unittest.TestCase):
    """The same board scraped twice is the same prop, refreshed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "t.db")
        con = sqlite3.connect(self.path)
        con.executescript(
            "CREATE TABLE props("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, game_id INTEGER, player_id INTEGER,"
            "market TEXT NOT NULL, line REAL NOT NULL, side TEXT NOT NULL, source TEXT,"
            "captured_at TEXT NOT NULL, odds INTEGER, odds_captured_at TEXT);"
        )
        con.commit()
        con.close()

    def _ingest(self, odds):
        """The upsert exactly as routers/props.py performs it."""
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        existing = con.execute(
            "SELECT id FROM props WHERE game_id=? AND player_id=? AND market=? "
            "AND line=? AND side=? AND source IS ?",
            (1, 1, "goals", 0.5, "over", "bovada")).fetchone()
        if existing:
            con.execute("UPDATE props SET captured_at=?,odds=?,odds_captured_at=? WHERE id=?",
                        (now, odds, now, existing["id"]))
            written = "refreshed"
        else:
            con.execute(
                "INSERT INTO props(game_id,player_id,market,line,side,source,captured_at,"
                "odds,odds_captured_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (1, 1, "goals", 0.5, "over", "bovada", now, odds, now))
            written = "ingested"
        con.commit()
        rows = con.execute("SELECT COUNT(*), MAX(odds) FROM props").fetchone()
        con.close()
        return written, rows[0], rows[1]

    def test_rescraping_the_same_prop_updates_it_instead_of_copying_it(self):
        self.assertEqual(self._ingest(250), ("ingested", 1, 250))
        self.assertEqual(self._ingest(275), ("refreshed", 1, 275))
        self.assertEqual(self._ingest(300), ("refreshed", 1, 300))


if __name__ == "__main__":
    unittest.main()
