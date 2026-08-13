"""The editor's link path: what a hand-delivered URL does and does not buy.

Micah, 2026-08-13: "ill evaluate cards on the site and send you links i want
part of the conversation. im not sifting through every article or post."

A link asserts RELEVANCE — this belongs in that conversation, no score needed.
It asserts nothing about PROVENANCE. The tests below pin that separation,
because it is the one that failed before: `SOCIAL_SOURCES` missing `x` let 855
tweets ride through as verified publishers, and "a human sent it to us" is not
a reason to reopen that door.
"""
import sqlite3

import pytest

import add_conversation_link as acl
from ingest_league_narratives import post_role
from ingest_league_news import CONVERSATIONS


@pytest.fixture
def con():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE news_items(
                   id INTEGER PRIMARY KEY AUTOINCREMENT, league TEXT, layer TEXT,
                   source TEXT, headline TEXT, body TEXT, url TEXT UNIQUE,
                   published TEXT, conv_id TEXT)""")
    return c


CONV = CONVERSATIONS[0]["id"]
LEAGUE = CONVERSATIONS[0]["league"]

TWEET = {"source": "x", "headline": "[@AllFutbolMX] Mexico's interest in leaving "
         "CONCACAF may have been fueled by the Gold Cup's Netflix deal",
         "body": "", "published": "2026-08-12T00:00:00"}


class TestALinkIsNotAPromotion:
    def test_an_editors_tweet_is_still_a_post(self, con):
        acl.add(con, CONV, "https://x.com/allfutbolmx/status/1", TWEET)
        row = dict(con.execute("SELECT * FROM news_items").fetchone())
        assert row["source"] == "x"
        assert row["conv_id"] == CONV
        assert post_role(row) != "publisher"

    def test_the_handle_prefix_is_preserved(self, con):
        """`is_social` recognises a post by SHAPE as well as by source name.

        An item stored without the collector's `[@handle]` prefix would be the
        one row in the corpus that only one of those two guards can see — and
        the shape guard exists precisely because the name list failed once.
        """
        acl.add(con, CONV, "https://x.com/allfutbolmx/status/1", TWEET)
        head = con.execute("SELECT headline FROM news_items").fetchone()[0]
        assert head.startswith("[@")

    def test_an_unknown_conversation_is_refused(self, con):
        with pytest.raises(SystemExit):
            acl.add(con, "not-a-conversation", "https://x.com/a/status/1", TWEET)


class TestAlreadyCollected:
    def test_an_existing_row_is_re_homed_not_refetched(self, con):
        """The common case, and why this must not depend on the network.

        874 of 1,033 stored `x` rows match no seed word, so the item Micah
        sends is usually one we already hold and simply could not place.
        """
        con.execute("""INSERT INTO news_items(league, layer, source, headline,
                       body, url, published, conv_id)
                       VALUES (?,'narrative','x','[@RapSheet] Sources: the deal
                       is done','', 'https://x.com/rapsheet/status/9','','')""",
                    (LEAGUE,))
        action, _ = acl.add(con, CONV, "https://x.com/rapsheet/status/9",
                            item=None)  # item=None: a fetch here would be a bug
        assert action.startswith("re-homed")
        assert con.execute("SELECT conv_id FROM news_items").fetchone()[0] == CONV

    def test_re_homing_reports_where_it_came_from(self, con):
        con.execute("""INSERT INTO news_items(league, layer, source, headline,
                       body, url, published, conv_id)
                       VALUES (?,'narrative','x','[@a] x','','https://x/9','',
                       'some-other-conv')""", (LEAGUE,))
        action, _ = acl.add(con, CONV, "https://x/9", item=None)
        assert "some-other-conv" in action


class TestMasthead:
    """`og:title` is written for a browser tab, so publishers bolt their own
    name onto it. Left in, the outlet lands in the subject slot of a numbered
    prompt item — the thing the name-drop rules already forbid in the prose."""

    @pytest.mark.parametrize("raw,want", [
        ("Deadspin | Colts, RB Jonathan Taylor agree to extension",
         "Colts, RB Jonathan Taylor agree to extension"),
        ("Netflix lands Gold Cup rights | CNBC", "Netflix lands Gold Cup rights"),
        ("Fox boss says network wont redo the NFL deal — The Athletic",
         "Fox boss says network wont redo the NFL deal"),
    ])
    def test_a_bolted_on_masthead_is_removed(self, raw, want):
        assert acl._strip_masthead(raw) == want

    def test_a_headline_with_no_masthead_is_untouched(self):
        h = "NFL players turn up pressure for grass fields following World Cup"
        assert acl._strip_masthead(h) == h

    def test_a_title_that_is_ONLY_a_masthead_is_kept(self):
        """A fetch that failed in a way worth seeing, not a headline to empty."""
        assert acl._strip_masthead("ESPN.com") == "ESPN.com"


class TestUrlShapes:
    @pytest.mark.parametrize("url,handle,sid", [
        ("https://x.com/allfutbolmx/status/2087577111808606361",
         "allfutbolmx", "2087577111808606361"),
        ("https://twitter.com/RapSheet/status/123", "RapSheet", "123"),
        ("https://x.com/a/status/9?s=46", "a", "9"),
    ])
    def test_a_tweet_url_is_recognised_with_or_without_tracking(self, url, handle, sid):
        m = acl._TWEET.match(url)
        assert m and m.group(1) == handle and m.group(2) == sid

    def test_an_article_url_is_not_mistaken_for_a_tweet(self):
        assert not acl._TWEET.match("https://espn.com/nfl/story/_/id/1/status/x")
