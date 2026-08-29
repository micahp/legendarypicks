#!/usr/bin/env python3
"""`?league=` means the competition, not the spine each athlete sits in.

For every single-league sport the two are the same word, so this went unnoticed.
They diverge in a cross-league tournament: a Leagues Cup game is `lcup` while the
athletes playing it are `mls` and `ligamx`. `/api/props` filtered on `pl.league`
and returned nothing for `lcup`, while `/api/props/slate` filtered on `pg.league`
and still advertised the game with its prop_count. A board that claims N props
and lists none, on the feature the product is built around.
"""
import os
import sqlite3
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# `_core.DB` is bound at IMPORT and never re-read. Pointing LP_DB_PATH at a
# fixture before importing only works if nothing else imported `_core` first,
# which is true when this file runs alone and false in the suite: another test
# imports it, `DB` is already bound, and this file's fixture never gets a schema.
# So bind the module attribute per test instead. That is the same shape as the
# package split where `from .constants import _DB` bound a copy and 36 "fixture"
# tests read prod.
import _core  # noqa: E402
from routers import props  # noqa: E402

_FIXTURE = tempfile.NamedTemporaryFile(prefix="props-league-", suffix=".db", delete=False)
_FIXTURE.close()


def _seed():
    con = sqlite3.connect(_FIXTURE.name)
    # One Leagues Cup fixture: an MLS club against a Liga MX club, one athlete from
    # each spine. This is the real shape of 2026-08-26.
    con.execute("INSERT INTO players(id,name,team,league) VALUES(1,'MLS Forward','RSL','mls')")
    con.execute("INSERT INTO players(id,name,team,league) VALUES(2,'Liga MX Forward','LEO','ligamx')")
    # An MLS-vs-MLS fixture on the same day, so a filter that simply stopped
    # filtering would also pass and must not.
    con.execute("INSERT INTO players(id,name,team,league) VALUES(3,'Other Forward','ATX','mls')")
    con.execute("INSERT INTO prop_games(id,league,date,start_time,home,away) "
                "VALUES(10,'lcup','2026-08-26','2099-08-27T02:00:00+00:00','Leon','Real Salt Lake')")
    con.execute("INSERT INTO prop_games(id,league,date,start_time,home,away) "
                "VALUES(11,'mls','2026-08-26','2099-08-27T02:00:00+00:00','Austin FC','FC Dallas')")
    for pid, (gid, player) in enumerate(((10, 1), (10, 2), (11, 3)), start=100):
        con.execute(
            "INSERT INTO props(id,game_id,player_id,market,line,side,source,captured_at,odds) "
            "VALUES(?,?,?,'shots_on_target',1.5,'over','rotowire','2026-08-26T12:00:00Z',-120)",
            (pid, gid, player))
        con.execute(
            "INSERT INTO prop_results(prop_id,actual_value,hit,settled_at) "
            "VALUES(?,2.0,1,'2026-08-27T05:00:00Z')", (pid,))
    con.commit()
    con.close()


class LeagueFilterIsTheCompetition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._old_db = _core.DB
        _core.DB = _FIXTURE.name
        _core._init_db()
        _seed()

    @classmethod
    def tearDownClass(cls):
        _core.DB = cls._old_db
        try:
            os.unlink(_FIXTURE.name)
        except FileNotFoundError:
            pass

    def test_lcup_returns_both_spines(self):
        rows = props.list_props(player=None, market=None, league="lcup", date=None,
                                limit=50, offset=0)
        self.assertEqual(len(rows), 2, "both halves of the fixture must reach the board")
        self.assertEqual(sorted(r["league"] for r in rows), ["ligamx", "mls"])
        self.assertEqual({r["game_home"] for r in rows}, {"Leon"})

    def test_mls_does_not_swallow_the_tournament_game(self):
        """The filter must still be a filter: `mls` returns only the MLS fixture."""
        rows = props.list_props(player=None, market=None, league="mls", date=None,
                                limit=50, offset=0)
        self.assertEqual([r["game_home"] for r in rows], ["Austin FC"])

    def test_props_pages_are_stable_and_do_not_repeat_rows(self):
        pages = [props.list_props(player=None, market=None, league=None, date=None,
                                  limit=1, offset=offset)
                 for offset in range(3)]
        ids = [page[0]["id"] for page in pages]
        self.assertEqual(ids, [102, 101, 100])
        self.assertEqual(len(set(ids)), 3)

    def test_the_slate_expands_to_the_props_it_advertised(self):
        """The one endpoint that had BOTH rulers in it.

        `props_slate` filters its GAME list on `pg.league` and used to fetch the
        nested props on `pl.league`, so a Leagues Cup fixture was listed with its
        prop_count and then expanded to nothing. The count and the list have to
        be measured the same way or the board lies about itself.
        """
        slate = props.props_slate(league="lcup", date=None, summary=0, game_id=None)
        games = slate["games"] if isinstance(slate, dict) else slate
        self.assertEqual(len(games), 1, "the lcup fixture must be listed")
        advertised = games[0].get("prop_count")
        listed = len(games[0].get("players") or games[0].get("props") or [])
        self.assertTrue(listed > 0, "the fixture expanded to nothing")
        if advertised is not None:
            self.assertEqual(advertised, 2)

    def test_the_expanded_slate_labels_the_game_with_the_competition(self):
        """The fourth site of this shape, and the only one not in a WHERE clause.

        The expanded slate SELECTed `pl.league` and put it on the GAME object, so
        the same endpoint answered `lcup` under `summary=1` (which reads
        `pg.league`) and `mls` for the same game when expanded, flipping to
        `ligamx` with whichever athlete happened to sort first. No filter test
        could reach it: the rows returned were already the right rows, it was the
        label on them that was wrong.
        """
        summary = props.props_slate(league="lcup", date=None, summary=1, game_id=None)
        summary_games = summary["games"] if isinstance(summary, dict) else summary
        self.assertEqual(summary_games[0]["league"], "lcup")

        for game_id in (None, 10):
            slate = props.props_slate(league=None if game_id else "lcup",
                                      date=None, summary=0, game_id=game_id)
            games = slate["games"] if isinstance(slate, dict) else slate
            game = next(g for g in games if g["game_id"] == 10)
            self.assertEqual(
                game["league"], "lcup",
                "the expanded slate labelled the competition with a player's spine")

    def test_stats_counts_the_competition_not_the_spine(self):
        stats = props.prop_stats(market=None, league="lcup", window=365)
        self.assertEqual(sum(s["total"] for s in stats), 2)


if __name__ == "__main__":
    unittest.main()
