"""A story belongs to one conversation, not to every card that half-matches it.

Each card used to score the league's article feed on its own, with no idea its
sibling conversations existed, so one story could win a place in several pools
at once. Because anchors are ranked with recency in the tiebreak, a big
breaking story was the NEWEST item in every pool it reached and therefore led
every card that took it.

That is how Messi's father's death opened the Leagues Cup SCOUTING card three
weeks after Micah split the two conversations apart for exactly this reason
(`news_conversations.mls-messi-absence` note, 2026-08-10: "the Messi story is
its own card, not a line in the Leagues Cup scouting card"). The split was made
in the conversation table; anchor selection never learned about it.

Measured on dev 2026-08-12: 5 of 130 anchors sat in a card that scored them
lower than a sibling did. Note what does NOT find this -- URL dedupe across
pools reports 0 of 130 shared, because the cards were not holding the same
ARTICLE, they were holding the same STORY through different articles.
"""
from ingest_league_narratives import _better_home, _topic_words


def conv(cid, seed, title, league="mls"):
    return {"id": cid, "league": league, "seed": seed, "title": title}


SCOUTING = conv("mls-leaguescup-proving", "Leagues Cup scouting Liga MX",
                "Leagues Cup proving ground")
MESSI = conv("mls-messi-absence", "Messi Inter Miami", "Messi absence")
SPENDING = conv("mls-ligamx-spending", "MLS Liga MX transfer",
                "Cross-border spending")


class _Con:
    """Stands in for the sqlite connection `_better_home` reads siblings from."""

    def __init__(self, convs):
        self._convs = convs

    def execute(self, _sql, _params):
        return self

    def fetchall(self):
        return self._convs


def home(current, headline, own_entities=(), siblings=(SCOUTING, MESSI, SPENDING)):
    # _better_home caches siblings per league across calls; give each case its
    # own league so one test cannot poison the next.
    key = "mls-%d" % id(siblings)
    cur = dict(current, league=key)
    sibs = [dict(c, league=key) for c in siblings]
    return _better_home(_Con(sibs), cur, headline, own_entities)


class TestRouting:
    def test_the_messi_story_leaves_the_scouting_card(self):
        """The reported defect, stated as a test."""
        assert home(SCOUTING,
                    "Messi unlikely to play as Inter Miami faces Leagues Cup "
                    "elimination vs. Leon") == "mls-messi-absence"

    def test_the_scouting_feature_stays_in_the_scouting_card(self):
        assert home(SCOUTING,
                    "How Leagues Cup is becoming a hotbed for global scouting") is None

    def test_a_fixture_the_conversation_owns_is_not_routed_away(self):
        assert home(MESSI, "Why isn't Lionel Messi playing for Inter Miami "
                           "vs Monterrey in 2026 Leagues Cup?") is None


class TestTheEntityBridge:
    def test_a_conversations_own_chatter_protects_its_headline_story(self):
        """Word counts alone took the transfer card's own lead story away.

        "Inter Miami finalizing $15M Berterame transfer" matches the spending
        card on one word -- `transfer`, its entire subject, and the very deal
        its conv note cites as evidence -- and the Messi card on two, `inter`
        and `miami`, a club name that seed happens to carry. On counts the
        spending card loses its own headline. Its chatter is the tiebreak.
        """
        # `entities()` yields lowercase MULTI-word entities, so the bridge here
        # is "inter miami" -- a bare surname like "Berterame" is never one.
        assert home(SPENDING,
                    "Inter Miami finalizing $15M Berterame transfer",
                    own_entities={"inter miami"}) is None

    def test_the_bridge_may_not_be_the_conversations_own_seed_word(self):
        """A bridge built on the seed is circular and readmits everything.

        "Leagues Cup" is an entity in the scouting card's chatter AND that
        card's own seed word, so every Messi fixture story bridged on it and
        the guard put back exactly what routing had removed.
        """
        assert home(SCOUTING,
                    "Messi unlikely to play as Inter Miami faces Leagues Cup "
                    "elimination vs. Leon",
                    own_entities={"leagues cup"}) == "mls-messi-absence"

    def test_a_distinctive_bridge_entity_still_protects(self):
        assert home(SCOUTING,
                    "Santos Laguna up first for NYCFC in Leagues Cup",
                    own_entities={"santos laguna"}) is None


class TestTopicWords:
    def test_generic_words_are_not_topic_words(self):
        assert "league" not in _topic_words(SCOUTING)
        assert "scouting" in _topic_words(SCOUTING)

    def test_a_conversation_with_no_siblings_keeps_everything(self):
        assert home(SCOUTING, "Messi unlikely to play vs Leon",
                    siblings=(SCOUTING,)) is None
