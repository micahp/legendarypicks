#!/usr/bin/env python3
"""test_news.py — classifier + news router tests (league news engine)."""

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(prefix="news-api-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

import sqlite3  # noqa: E402
from news_classifier import classify  # noqa: E402
from routers import news  # noqa: E402


def _insert(headline, league, layer, url, body="", source="test", key_player=None, published="2026-08-06T12:00:00Z"):
    con = sqlite3.connect(_TEST_DB.name)
    con.execute(
        """INSERT INTO news_items(league, layer, source, headline, body, url, published, key_player)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (league, layer, source, headline, body, url, published, key_player),
    )
    con.commit()
    con.close()


class ClassifierTests(unittest.TestCase):
    def test_trade(self):
        c = classify("Rams acquire star receiver in blockbuster trade")
        self.assertEqual(c["layer"], "trade")
        self.assertEqual(c["league"], "nfl")

    def test_trade_extension(self):
        c = classify("Colts, RB Jonathan Taylor agree to extension")
        self.assertEqual(c["layer"], "trade")

    def test_trade_release(self):
        c = classify("Pirates release DH Marcell Ozuna")
        self.assertEqual(c["layer"], "trade")

    def test_trade_definitive_statement(self):
        # "no plans to trade" is real signal, not speculation
        c = classify("Bucs GM: No plans to trade Vita Vea, Baker Mayfield a franchise QB")
        self.assertEqual(c["layer"], "trade")

    def test_trade_speculation_packages(self):
        c = classify("Realistic trade packages for Jonathan Taylor")
        self.assertEqual(c["layer"], "speculation")

    def test_trade_speculation_should_happen(self):
        c = classify("Top 10 trades that should happen this offseason")
        self.assertEqual(c["layer"], "speculation")

    def test_trade_speculation_projection(self):
        c = classify("Projecting trade packages for Marcell Ozuna")
        self.assertEqual(c["layer"], "speculation")

    def test_trade_speculation_rumor(self):
        c = classify("NFL Rumors: Falcons emerge as Tyreek Hill trade destination")
        self.assertEqual(c["layer"], "speculation")

    def test_injury(self):
        c = classify("Broncos coach: WR Jaylen Waddle (leg) out 4-5 days")
        self.assertEqual(c["layer"], "injury")
        self.assertEqual(c["league"], "nfl")

    def test_staff(self):
        c = classify("Eagles fire defensive coordinator after rough start")
        self.assertEqual(c["layer"], "staff")
        self.assertEqual(c["league"], "nfl")

    def test_staff_hired(self):
        c = classify("Eagles hire new offensive coordinator")
        self.assertEqual(c["layer"], "staff")

    def test_staff_not_coaches_poll(self):
        # commentary that merely mentions coaches is not a staff decision
        c = classify("Preseason coaches poll just inflates SEC, Big Ten egos")
        self.assertNotEqual(c["layer"], "staff")

    def test_staff_not_fired_up(self):
        # "fired up" = excited, not terminated
        c = classify("Jon Gruden 'fired up' for NFL play-by-play opportunity")
        self.assertNotEqual(c["layer"], "staff")

    def test_narrative_cap(self):
        c = classify("With Dodgers in a free fall, should a salary cap be instituted?")
        self.assertEqual(c["layer"], "narrative")
        self.assertEqual(c["league"], "mlb")

    def test_narrative_media_rights(self):
        c = classify("With Fox backing out of early NFL negotiations, will other networks follow?")
        self.assertEqual(c["layer"], "narrative")
        self.assertEqual(c["league"], "nfl")

    def test_narrative_relegation(self):
        c = classify("MLS commissioner Larry Berg rules out promotion and relegation anytime soon")
        self.assertEqual(c["layer"], "narrative")
        self.assertEqual(c["league"], "mls")

    def test_key_player(self):
        c = classify("Messi leads Inter Miami to another win")
        self.assertEqual(c["key_player"], "Messi")
        self.assertEqual(c["league"], "mls")

    def test_unclassified(self):
        c = classify("Local bakery wins regional award")
        self.assertEqual(c["league"], "unclassified")
        self.assertEqual(c["layer"], "other")

    def test_source_hint(self):
        c = classify("Fantasy baseball lineup advice for Friday", "mlb")
        self.assertEqual(c["league"], "mlb")


class NewsApiTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(_TEST_DB.name)
        except FileNotFoundError:
            pass

    def setUp(self):
        con = sqlite3.connect(_TEST_DB.name)
        con.execute("DELETE FROM news_items")
        con.commit()
        con.close()

    def test_catch_all_groups_by_league(self):
        _insert("Fox backs out of NFL negotiations", "nfl", "narrative", "http://x/1")
        _insert("Jaylen Waddle out 4-5 days", "nfl", "injury", "http://x/2", key_player="Jaylen Waddle")
        _insert("Dodgers salary cap debate", "mlb", "narrative", "http://x/3")
        _insert("Pirates release Marcell Ozuna", "mlb", "trade", "http://x/4")

        data = news.news_catch_all(league=None)
        self.assertEqual(set(data["leagues"].keys()), {"nfl", "mlb"})
        self.assertEqual(data["leagues"]["nfl"]["narratives"][0]["headline"],
                         "Fox backs out of NFL negotiations")
        self.assertEqual(data["leagues"]["nfl"]["granular"][0]["layer"], "injury")
        self.assertEqual(data["leagues"]["mlb"]["granular"][0]["layer"], "trade")
        # top feed: flat, recency-ordered, carries league
        self.assertEqual(len(data["top"]), 4)
        self.assertEqual({t["league"] for t in data["top"]}, {"nfl", "mlb"})
        self.assertTrue(all("league" in t for t in data["top"]))

    def test_top_caps_at_10_and_excludes_junk(self):
        for i in range(12):
            _insert("Item %d" % i, "nfl" if i % 2 else "mlb", "injury", "http://x/t%d" % i,
                    published="2026-08-06T%02d:00:00Z" % (23 - i))
        _insert("Junk row", "unclassified", "other", "http://x/junk",
                published="2026-08-07T00:00:00Z")

        data = news.news_catch_all(league=None)
        self.assertEqual(len(data["top"]), 10)
        # most recent first
        pubs = [t["published"] for t in data["top"]]
        self.assertEqual(pubs, sorted(pubs, reverse=True))
        # junk (other layer / unclassified league) never in top
        self.assertTrue(all(t["layer"] != "other" for t in data["top"]))
        self.assertTrue(all(t["league"] != "unclassified" for t in data["top"]))

    def test_narratives_one_per_league(self):
        _insert("Fox backs out of NFL negotiations", "nfl", "narrative", "http://x/1")
        _insert("Dodgers salary cap debate", "mlb", "narrative", "http://x/3")
        _insert("Second MLB narrative", "mlb", "narrative", "http://x/5")

        con = sqlite3.connect(_TEST_DB.name)
        con.execute(
            """INSERT INTO news_narratives(league, narrative, points, sources, source_count)
               VALUES ('nfl', 'Media rights talks are shifting.', '[]', '[{"headline":"h","url":"u","source":"s"}]', 1)""")
        con.execute(
            """INSERT INTO news_narratives(league, narrative, points, sources, source_count)
               VALUES ('mlb', 'The cap debate is the story.', '["Dodgers spend"]', '[]', 1)""")
        con.commit()
        con.close()

        data = news.news_narratives()
        leagues = [n["league"] for n in data["narratives"]]
        self.assertEqual(leagues, ["mlb", "nfl"])  # sorted
        self.assertEqual(len([n for n in data["narratives"] if n["league"] == "mlb"]), 1)
        self.assertEqual(data["narratives"][0]["narrative"], "The cap debate is the story.")
        self.assertEqual(data["narratives"][1]["points"], [])
        self.assertEqual(data["narratives"][1]["sources"][0]["headline"], "h")

    def test_league_filter(self):
        _insert("Fox backs out of NFL negotiations", "nfl", "narrative", "http://x/1")
        _insert("Dodgers salary cap debate", "mlb", "narrative", "http://x/3")

        data = news.news_catch_all(league="nfl")
        self.assertEqual(set(data["leagues"].keys()), {"nfl"})

        data2 = news.news_for_league("nfl")
        self.assertEqual(set(data2["leagues"].keys()), {"nfl"})

    def test_other_rows_not_served(self):
        _insert("Local bakery wins award", "unclassified", "other", "http://x/9")
        data = news.news_catch_all(league=None)
        self.assertEqual(data["leagues"], {})


if __name__ == "__main__":
    unittest.main()
