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


def _insert(headline, league, layer, url, body="", source="test", key_player=None,
            published="2026-08-06T12:00:00Z", conv_id=None):
    con = sqlite3.connect(_TEST_DB.name)
    con.execute(
        """INSERT INTO news_items(league, layer, source, headline, body, url, published, key_player, conv_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (league, layer, source, headline, body, url, published, key_player, conv_id),
    )
    con.commit()
    con.close()


def _insert_conv(conv_id, league, title, narrative, fan_voice="", paragraph="",
                 sources="[]", source_count=0):
    con = sqlite3.connect(_TEST_DB.name)
    con.execute(
        """INSERT INTO news_narratives(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count),
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

    def test_giants_broadcaster_is_mlb(self):
        # SF Giants broadcaster = MLB, not the NFL Giants
        c = classify("Longtime Giants broadcaster Mike Krukow retiring after 37 seasons")
        self.assertEqual(c["league"], "mlb")
        c2 = classify("Giants sign quarterback to extension")
        self.assertEqual(c2["league"], "nfl")

    def test_unclassified(self):
        c = classify("Local bakery wins regional award")
        self.assertEqual(c["league"], "unclassified")
        self.assertEqual(c["layer"], "other")

    def test_source_hint(self):
        c = classify("Fantasy baseball lineup advice for Friday", "mlb")
        self.assertEqual(c["league"], "mlb")

    def test_texas_judge_not_ncaaf(self):
        # A generic state name ("texas") must not steal an NBA story, and the
        # common noun "judge" must not tag Aaron Judge (2026-08-08 regression).
        c = classify("James Harden's misdemeanor gun charge dismissed by Texas judge", "nba")
        self.assertEqual(c["league"], "nba")
        self.assertIsNone(c["key_player"])

    def test_ncaaf_team_terms(self):
        c = classify("Longhorns land top quarterback recruit")
        self.assertEqual(c["league"], "ncaaf")
        c2 = classify("Purdue AD introduced at press conference")
        self.assertEqual(c2["league"], "ncaaf")

    def test_nba_team_terms(self):
        c = classify("Clippers star Kawhi Leonard addresses the media")
        self.assertEqual(c["league"], "nba")

    def test_word_boundary_league_terms(self):
        # "acc" must not match "accepting" (stole an NHL story into NCAAF),
        # "nba" must not match "wnba", "stars" must not match "superstar".
        c = classify("Stars keep 'cornerstone' Jason Robertson with one-year deal", "nhl")
        self.assertEqual(c["league"], "nhl")
        c2 = classify("WNBA standings: Superstar trade gives Phoenix Mercury new sign of life")
        self.assertNotEqual(c2["league"], "nba")
        c3 = classify("ACC tournament bracket announced")
        self.assertEqual(c3["league"], "ncaaf")

    def test_word_boundary_notable(self):
        # "alba" must not tag Robby Albarado (surname substring collision)
        c = classify("Two-time Preakness winning jockey Robby Albarado dies")
        self.assertIsNone(c["key_player"])
        c2 = classify("Aaron Judge homers twice")
        self.assertEqual(c2["key_player"], "Aaron Judge")


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
        con.execute("DELETE FROM news_narratives")
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
        # no conversation cards inserted -> conversations list is empty
        self.assertEqual(data["conversations"], [])
        self.assertTrue(all("league" in t for t in data["leagues"]["nfl"]["narratives"]))

    def test_conversations_served(self):
        _insert_conv("nfl-media-rights", "nfl", "Media rights talks",
                     "Fox backs out of early NFL negotiations.", "Fans want transparency.",
                     "Fox backed out. Fans argue the networks are circling.")
        _insert_conv("mlb-salary-cap", "mlb", "Salary cap debate",
                     "Dodgers spending reignites cap talk.", "Small markets want a floor.",
                     "Dodgers spending reignited the cap debate. Small markets say they need a floor.")

        data = news.news_catch_all(league=None)
        self.assertEqual(len(data["conversations"]), 2)
        by_id = {c["conv_id"]: c for c in data["conversations"]}
        self.assertEqual(by_id["nfl-media-rights"]["narrative"],
                         "Fox backs out of early NFL negotiations.")
        self.assertEqual(by_id["nfl-media-rights"]["fan_voice"], "Fans want transparency.")
        self.assertEqual(by_id["mlb-salary-cap"]["paragraph"],
                         "Dodgers spending reignited the cap debate. Small markets say they need a floor.")
        # per-league grouping also carries the conversation
        self.assertEqual(len(data["leagues"]["nfl"]["conversations"]), 1)
        self.assertEqual(data["leagues"]["nfl"]["conversations"][0]["title"], "Media rights talks")

    def test_narratives_endpoint(self):
        _insert_conv("nfl-media-rights", "nfl", "Media rights talks",
                     "Fox backs out of early NFL negotiations.", "Fans want transparency.",
                     "Fox backed out. Fans argue the networks are circling.")
        _insert_conv("mlb-salary-cap", "mlb", "Salary cap debate",
                     "Dodgers spending reignites cap talk.", "Small markets want a floor.",
                     "Dodgers spending reignited the cap debate. Small markets say they need a floor.")

        data = news.news_narratives()
        leagues = [n["league"] for n in data["narratives"]]
        self.assertEqual(leagues, ["mlb", "nfl"])  # sorted by league
        self.assertEqual(data["narratives"][0]["narrative"], "Dodgers spending reignites cap talk.")
        self.assertEqual(data["narratives"][0]["fan_voice"], "Small markets want a floor.")
        self.assertEqual(data["narratives"][0]["paragraph"],
                         "Dodgers spending reignited the cap debate. Small markets say they need a floor.")

    def test_league_filter(self):
        _insert("Fox backs out of NFL negotiations", "nfl", "narrative", "http://x/1")
        _insert("Dodgers salary cap debate", "mlb", "narrative", "http://x/3")

        data = news.news_catch_all(league="nfl")
        self.assertEqual(set(data["leagues"].keys()), {"nfl"})

        data2 = news.news_for_league("nfl")
        self.assertEqual(set(data2["leagues"].keys()), {"nfl"})

    def test_bluesky_not_served(self):
        # social posts are signal for the AI conversation, never displayed
        _insert("[@user] Dodgers salary cap chatter", "mlb", "narrative", "http://bsky/1",
                source="bluesky", published="2026-08-06T23:00:00Z")
        _insert("Dodgers salary cap debate", "mlb", "narrative", "http://x/1",
                published="2026-08-06T12:00:00Z")
        data = news.news_catch_all(league=None)
        self.assertTrue(all(i["source"] != "bluesky"
                            for i in data["leagues"]["mlb"]["narratives"]))
        # the real-article item IS served; the bluesky post is not
        served = [i["source"] for i in data["leagues"]["mlb"]["narratives"]]
        self.assertIn("test", served)
        self.assertNotIn("bluesky", served)

    def test_other_rows_not_served(self):
        _insert("Local bakery wins award", "unclassified", "other", "http://x/9")
        data = news.news_catch_all(league=None)
        self.assertEqual(data["leagues"], {})

    def test_unclassified_trade_not_served(self):
        # Non-league noise must not surface even when it carries a serveable
        # layer (WNBA/tennis/golf items that classify to a trade/staff/injury
        # layer but no league — 2026-08-08 regression: 26 rows leaking).
        _insert("Mystics trade for a guard", "unclassified", "trade", "http://x/10")
        _insert("NFL team signs quarterback", "nfl", "trade", "http://x/11")
        data = news.news_catch_all(league=None)
        self.assertEqual(set(data["leagues"].keys()), {"nfl"})
        served = [i["headline"] for i in data["leagues"]["nfl"]["granular"]]
        self.assertNotIn("Mystics trade for a guard", served)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------- discovery
# The discovery pass turns Micah's approved topics into labels for finding NEW
# conversations (discover_topics.py). These guard the stage-1 gates that were
# each added because the pass surfaced junk without them (2026-08-10).

def test_entities_drops_single_capitalized_tokens():
    """Single tokens are first names and sentence openers, never topics."""
    import discover_topics as d
    ents = d._entities("Larry Berg rules out promotion")
    assert "larry berg" in ents
    assert "larry" not in ents and "berg" not in ents


def test_entities_strips_bluesky_handle_prefix():
    import discover_topics as d
    ents = d._entities("[@zooomsports.bsky.social] Kevin Kelsy joins Portland Timbers")
    assert not any("bsky" in e for e in ents)
    assert "kevin kelsy" in ents


def test_covered_by_existing_needs_two_shared_words():
    """One shared generic word ('cap') must not hide a new conversation."""
    import discover_topics as d
    convs = [{"seed": "dodgers salary cap", "title": "Salary cap debate"}]
    # One shared token ("dodgers") is not enough to call it covered...
    assert d._covered_by_existing("the dodgers", convs) is False
    # ...two are, and so is a full phrase match.
    assert d._covered_by_existing("salary cap", convs) is True
    assert d._covered_by_existing("kevin kelsy", convs) is False


def test_container_entities_come_from_the_classifier_vocabulary():
    """Team names are containers, and we reuse the one list we already have."""
    import discover_topics as d
    assert "red sox" in d._CONTAINER_ENTITIES
    assert "lakers" in d._CONTAINER_ENTITIES


def test_notable_player_story_is_promoted_out_of_other():
    """Messi's father dying is news even though it matches no trade/injury rule."""
    from news_classifier import classify
    c = classify("Miami honors absent Lionel Messi in loss after father's death", "mls")
    assert c["key_player"] == "Messi"
    assert c["layer"] == "notable"


def test_notable_never_rescues_speculation():
    """A listicle that name-drops a star stays speculation."""
    from news_classifier import classify
    c = classify("Top 10 realistic trade packages for Lionel Messi", "mls")
    assert c["layer"] == "speculation"


def test_notable_does_not_override_a_real_layer():
    from news_classifier import classify
    c = classify("Lionel Messi out for three weeks with hamstring injury", "mls")
    assert c["layer"] == "injury"


# ---------------------------------------------------- unsupported allegations
# 2026-08-10: an anonymous X post claiming Inter Miami suspended Messi and
# Suarez over racial-harassment allegations — unconfirmed by the club, the
# league or any outlet — was written up as fact and served on a card.

def test_allegation_without_a_receipt_is_refused():
    from ingest_league_narratives import unsupported_allegation
    assert unsupported_allegation({
        "narrative": "Inter Miami suspends Messi and Suarez for a racial harassment probe",
        "paragraph": "Beckham announced the suspensions pending a full investigation.",
        "source_count": 0}) is True


def test_allegation_with_a_receipt_is_allowed():
    from ingest_league_narratives import unsupported_allegation
    assert unsupported_allegation({
        "narrative": "NBA investigates Kawhi Leonard over salary-cap circumvention",
        "paragraph": "Pablo Torre reported the arrangement.",
        "source_count": 2}) is False


def test_ordinary_card_without_a_receipt_still_serves():
    """Chatter-only cards stay legal — the bar is on allegations, not on cards."""
    from ingest_league_narratives import unsupported_allegation
    assert unsupported_allegation({
        "narrative": "MLS commissioner rules out promotion and relegation",
        "paragraph": "Fans argue an open pyramid would raise stakes.",
        "source_count": 0}) is False


def test_card_built_only_from_social_does_not_serve():
    """Facts come from publishers: a pool of pure chatter cannot hold a card up."""
    from ingest_league_narratives import had_publisher_material
    chatter = [{"source": "bluesky"}, {"source": "x-search"}]
    assert had_publisher_material(chatter) is False
    assert had_publisher_material(chatter + [{"source": "espn-mlb"}]) is True
