"""Which conversation an item belongs to, and when to refuse to guess.

`tag_conversations` scores an item against a conversation's hand-written seed.
Article headlines restate their subject, so that works; posts do not, so it
does not. Over the 1,033 stored `x` rows on dev 2026-08-13: 874 matched ZERO
seed words, 31 matched one, none matched the two required. The entire X feed —
every rostered reporter — had never reached a card, and no threshold was going
to fix it, because Ian Rapoport's "Sources: The #Patriots have agreed to terms
with their standout TE Hunter Henry" contains none of `media`, `rights`,
`broadcast`.

The asymmetry that sets every threshold below: an untagged item costs us a
story, a misrouted one puts a real receipt under a card it does not belong to.
So this refuses far more than it accepts, and every gate fails closed.
"""
import route_conversations as rc


def item(headline, league="nfl", source="espn-nfl"):
    return {"headline": headline, "body": "", "url": "https://x/1",
            "source": source, "league": league}


def profile(entities, words, seed, league="nfl", common=()):
    return {"league": league, "entities": set(entities), "words": set(words),
            "seed_words": set(seed), "common": set(common), "pool": 10}


# Built from what the extractors actually return, not from what the words look
# like: `_significant` drops "rights" as a generic sports word, and `entities`
# reads consecutive capitalised PAIRS, so "CEO Lachlan Murdoch" yields
# `ceo lachlan` rather than the name. A fixture written by eye tests a scorer
# that does not exist.
NFL_RIGHTS = profile(
    entities={"lachlan murdoch", "fox sports"},
    words={"media", "broadcast", "package", "network", "opt"},
    seed={"media", "broadcast", "package"})


class TestBothSignalsOrNothing:
    """The box-score failure, which is why the score is a conjunction.

    The first version weighted entities at 4 and required 8, so two shared
    names bought a route with no topical evidence at all. "Tarik Skubal"
    entered `mlb-salary-cap`'s profile from the trade-deadline card and every
    Skubal box score followed him in: "Dodgers edge Royals to salvage Skubal's
    Dodger Stadium debut", "Skubal remains winless since trade", "Re-ranking
    the Tigers' farm system". Hand-read precision was about half.
    """

    def test_the_right_names_about_the_wrong_subject_is_refused(self):
        it = item("Fox Sports boss Lachlan Murdoch spotted at the company picnic")
        assert rc.route(it, {"nfl-media-rights": NFL_RIGHTS})[0] is None

    def test_the_right_subject_naming_nobody_we_know_is_refused(self):
        it = item("Sky Italia broadcast package draws new media bidders")
        assert rc.route(it, {"nfl-media-rights": NFL_RIGHTS})[0] is None

    def test_both_together_route(self):
        it = item("Fox Sports boss Lachlan Murdoch says the network will not "
                  "redo its NFL media package until the 2029-30 opt-out")
        assert rc.route(it, {"nfl-media-rights": NFL_RIGHTS})[0] == "nfl-media-rights"


class TestLeagueIsAHardGuard:
    """Not a signal — a gate.

    Without it TomBogert's MLS transfer posts landed in `nfl-media-rights`
    because "finalizing a deal" hit that seed's generic words (2026-08-10).
    Entity routing makes the risk worse, since player and city names collide
    across leagues far more readily than topic words do.
    """

    def test_a_matching_story_in_the_wrong_league_is_refused(self):
        it = item("Fox Sports boss Lachlan Murdoch on the NFL media package",
                  league="mls")
        assert rc.route(it, {"nfl-media-rights": NFL_RIGHTS})[0] is None

    def test_an_unclassified_item_is_never_routed(self):
        it = item("Fox Sports boss Lachlan Murdoch on the NFL media package",
                  league="unclassified")
        assert rc.route(it, {"nfl-media-rights": NFL_RIGHTS})[0] is None

    def test_an_item_with_no_league_is_never_routed(self):
        it = item("Fox Sports boss Lachlan Murdoch on the NFL media package",
                  league=None)
        assert rc.route(it, {"nfl-media-rights": NFL_RIGHTS})[0] is None


class TestAmbiguityIsRefusedNotBroken:
    """A near-tie is a finding, not a result.

    `esports worlds` scored LoL Worlds and the Esports World Cup identically,
    the tie fell through to recency, and the card became the wrong event
    (Micah, 2026-08-12). The same tie one stage earlier would put the item in
    one of two conversations at random, so a route has to WIN, not lead.
    """

    def test_two_conversations_that_both_want_it_get_neither(self):
        a = profile({"lionel messi"}, {"leagues", "cup", "absence"},
                    {"messi", "absence"}, league="mls")
        b = profile({"lionel messi"}, {"leagues", "cup", "proving"},
                    {"messi", "leagues"}, league="mls")
        it = item("Lionel Messi returns for Inter Miami in the Leagues Cup",
                  league="mls")
        cid, best, margin = rc.route(it, {"a": a, "b": b})
        assert cid is None
        assert margin < rc._MIN_MARGIN

    def test_a_clear_winner_still_routes_when_a_sibling_scores(self):
        strong = profile({"lachlan murdoch", "fox sports"},
                         {"media", "broadcast", "network", "package"},
                         {"media", "broadcast"})
        weak = profile({"fox sports"}, {"turf", "grass"}, {"turf", "grass"})
        it = item("Fox Sports boss Lachlan Murdoch on the NFL media "
                  "broadcast package")
        assert rc.route(it, {"strong": strong, "weak": weak})[0] == "strong"


class TestUbiquitousEntitiesIdentifyNothing:
    def test_an_entity_every_conversation_shares_earns_no_route(self):
        p = profile({"los angeles"}, {"media", "package"}, {"media", "package"},
                    common={"los angeles"})
        it = item("Los Angeles holders meet on the media package")
        assert rc.route(it, {"nfl-media-rights": p})[0] is None


class TestProfilesAreBuiltFromThePool:
    def test_a_held_out_url_cannot_route_itself(self, tmp_path):
        """Validation with the item still in its own profile means nothing.

        Every already-tagged row would score against a profile containing that
        exact row and recover perfectly, reporting a number about bookkeeping
        rather than about routing.
        """
        import sqlite3
        db = tmp_path / "t.db"
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        con.execute("""CREATE TABLE news_items (headline TEXT, body TEXT,
                       url TEXT, conv_id TEXT)""")
        con.execute("""CREATE TABLE news_narratives (conv_id TEXT, title TEXT,
                       narrative TEXT, paragraph TEXT)""")
        cid = rc.CONVERSATIONS[0]["id"]
        con.execute("INSERT INTO news_items VALUES (?,?,?,?)",
                    ("Bellwether Zorkmid signs with the Fictional Nine", "",
                     "https://u/1", cid))
        con.commit()
        with_it = rc.conversation_profiles(con)
        without = rc.conversation_profiles(con, exclude_urls={"https://u/1"})
        assert "bellwether zorkmid" in with_it[cid]["entities"]
        assert "bellwether zorkmid" not in without[cid]["entities"]
