"""What a card is allowed to stand on, and what it may claim to stand on.

Three defects, all measured on dev 2026-08-12, all of which produced cards that
looked completely normal:

  1. **The model was never shown the reporting.** `_load_chatter` returns social
     chatter first and appends publisher anchors after it; the prompt took the
     first 10. Six of fourteen conversations therefore reached the model with
     ZERO publisher items — and those six are exactly the six cards that served
     `source_count = 0`. The MLS spending card called a completed transfer
     "unconfirmed social reports" while The Athletic, USA Today and
     mlssoccer.com sat unread in its own pool.

  2. **Citations resolved against a different list than the prompt numbered.**
     The prompt numbered deduplicated items; `_cited_sources` indexed the raw
     pool. Any duplicate dropped before item N shifted every citation after it.

  3. **Posts counted as publishers.** `SOCIAL_SOURCES` listed `x-search` but not
     `x`, while 855 rows carried `x` — so every tweet in the corpus was a
     verified publisher, and a tweet carrying a false claim was read as one and
     served as fact (Micah, 2026-08-12).

And the prose half of (3): a card naming an outlet it cannot cite. "Raw Chili"
is a content farm reposting other people's articles through bot accounts; two
cards credited it as a news outlet, and a third credited PCGamesN for a report
we never read — we had read a bluesky post linking to it.
"""
import pytest

from ingest_league_narratives import (
    _outlet_vocab, _prompt_items, had_publisher_material, is_social,
    social_leaks, uncited_outlets,
)


def post(headline="[@someone.bsky.social] a take", url="https://bsky.app/p/1",
         source="bluesky"):
    return {"headline": headline, "url": url, "source": source, "body": "",
            "published": "2026-08-12T00:00:00Z"}


def article(headline="Real reporting", url="https://nytimes.com/a",
            source="the new york times"):
    return {"headline": headline, "url": url, "source": source, "body": "",
            "published": "2026-08-12T00:00:00Z"}


class TestIsSocial:
    def test_a_source_on_the_list_is_social(self):
        assert is_social(post())

    def test_the_source_that_was_missing_from_the_list_is_social(self):
        """`x` carried 855 rows and was not in SOCIAL_SOURCES."""
        assert is_social(post(source="x"))

    def test_an_unlisted_feed_shaped_like_a_post_is_still_social(self):
        """The mechanism, not the instance: adding "x" to a list fixes 855 rows
        and leaves the next feed to be discovered the same painful way."""
        assert is_social(post(headline="[@handle] something", source="brandnew"))
        assert is_social({"headline": "A tweet", "source": "brandnew",
                          "url": "https://x.com/a/status/1"})

    def test_a_real_article_is_not_social(self):
        assert not is_social(article())

    def test_social_leaks_names_the_disagreement(self):
        """`x` is on the list now, so the leak to catch is the NEXT one: a feed
        whose rows are posts while its source name says otherwise."""
        leaks = social_leaks([article(), post(source="brandnew"), post()])
        assert [it["source"] for it in leaks] == ["brandnew"]

    def test_a_card_standing_only_on_tweets_has_no_publisher_material(self):
        assert not had_publisher_material([post(source="x"), post()])


class TestPromptItems:
    def test_publisher_items_survive_a_busy_social_lane(self):
        """The reported defect: 12 posts drowned 6 articles out of the prompt."""
        pool = [post(headline="[@a] take %d" % i, url="u%d" % i)
                for i in range(12)]
        pool += [article(headline="Report %d" % i, url="a%d" % i)
                 for i in range(6)]
        shown = _prompt_items(pool)
        assert sum(1 for i in shown if not is_social(i)) >= 4

    def test_published_material_comes_first(self):
        pool = [post(url="u%d" % i) for i in range(12)] + [article()]
        assert not is_social(_prompt_items(pool)[0])

    def test_spare_slots_go_back_to_the_articles(self):
        pool = [post()] + [article(headline="R%d" % i, url="a%d" % i)
                           for i in range(12)]
        shown = _prompt_items(pool, limit=10)
        assert len(shown) == 10
        assert sum(1 for i in shown if not is_social(i)) == 9

    def test_a_chatter_only_conversation_still_gets_its_items(self):
        """Chatter-only cards are a feature, not a failure (Micah)."""
        shown = _prompt_items([post(headline="[@a] take %d" % i,
                                    url="u%d" % i) for i in range(5)])
        assert len(shown) == 5

    def test_duplicates_are_dropped_once_so_numbering_cannot_drift(self):
        dupe = article(headline="Same story", url="a1")
        pool = [dupe, article(headline="Same story", url="a2"), article(
            headline="Other", url="a3")]
        shown = _prompt_items(pool)
        assert [i["url"] for i in shown] == ["a1", "a3"]

    def test_the_shown_list_is_what_citations_must_index(self):
        """Item #2 in the prompt has to BE item #2 to the resolver.

        This is the regression that made mlb-salary-cap's "#7" a salary-cap
        article in the prompt and a bluesky post in the resolver.
        """
        pool = [article(headline="A", url="a1"), article(headline="A", url="a2"),
                article(headline="B", url="a3")]
        shown = _prompt_items(pool)
        assert shown[1]["url"] == "a3"
        assert pool[1]["url"] == "a2"  # the raw pool disagrees — hence the bug


class TestUncitedOutlets:
    VOCAB = {"rawchili", "pcgamesn", "elpasoinc", "theathletic", "complex"}

    def card(self, text, sources=()):
        return {"narrative": text, "paragraph": "", "fan_voice": "",
                "sources": list(sources)}

    def test_a_named_outlet_with_no_receipt_is_reported(self):
        gen = self.card("Social posts circulating on Raw Chili said so.")
        assert uncited_outlets(gen, self.VOCAB) == ["rawchili"]

    def test_crediting_an_outlet_we_only_saw_linked_is_reported(self):
        gen = self.card("Posts cited a PCGamesN report on resale tickets.")
        assert uncited_outlets(gen, self.VOCAB) == ["pcgamesn"]

    def test_an_outlet_we_actually_cite_is_fine(self):
        gen = self.card("The Athletic reported the fee.",
                        [{"source": "the athletic",
                          "url": "https://theathletic.com/1"}])
        assert uncited_outlets(gen, self.VOCAB) == []

    def test_a_lowercase_word_that_happens_to_be_an_outlet_is_not_flagged(self):
        """"complex" in "the already complex case" is not Complex.com."""
        gen = self.card("It added a layer to the already complex case.")
        assert uncited_outlets(gen, self.VOCAB) == []

    def test_a_multi_word_masthead_is_matched(self):
        gen = self.card("Yahoo Sports and El Paso Inc. have both covered it.")
        assert uncited_outlets(gen, self.VOCAB) == ["elpasoinc"]

    def test_a_team_or_event_that_runs_a_website_is_not_an_attribution(self):
        """Naming a club is not crediting a publisher. "the LA Galaxy moved
        Edwin Cerrillo" was flagged against lagalaxy.com."""
        gen = self.card("MLSsoccer.com confirmed the LA Galaxy moved Cerrillo.",
                        [{"source": "mlssoccer.com",
                          "url": "https://mlssoccer.com/1", "headline": "x"}])
        assert uncited_outlets(gen, self.VOCAB | {"lagalaxy"}) == []

    def test_a_reporting_verb_across_a_sentence_break_does_not_attribute(self):
        """"...of the Esports World Cup 2026. Dust2.us listed BetBoom..." put a
        reporting verb three tokens after an event name in the PREVIOUS
        sentence."""
        gen = self.card("Lenovo joined the Esports World Cup 2026. "
                        "Dust2.us listed the schedule.")
        assert "esportsworldcup" not in uncited_outlets(
            gen, self.VOCAB | {"esportsworldcup", "dust2"})

    def test_the_receipts_headline_is_an_alias_for_its_outlet(self):
        """We ingest The Athletic under source "the new york times", so a card
        citing that row and writing "The Athletic reported" is correct."""
        gen = self.card("The Athletic reported the fee.",
                        [{"source": "the new york times",
                          "url": "https://nytimes.com/1",
                          "headline": "Monterrey agree fee - The Athletic"}])
        assert uncited_outlets(gen, self.VOCAB) == []

    def test_it_reports_and_never_deletes(self):
        """Deliberately not a refusal. Chatter-only cards are a feature, and a
        wrong attribution is a reason to fix the sentence, not drop the card."""
        assert isinstance(uncited_outlets(self.card("Raw Chili"), self.VOCAB),
                          list)


class TestVocabulary:
    def test_domains_written_inside_a_post_reach_the_vocabulary(self):
        """A bluesky row's url is its bsky permalink, so the outlet it credits
        appears only in the post TEXT. Harvesting urls alone missed both
        rawchili.com and pcgamesn.com -- the two cases this check exists for."""

        class Con:
            def execute(self, sql, *a):
                if "DISTINCT source" in sql:
                    return [("bluesky",)]
                if "DISTINCT url" in sql:
                    return [("https://bsky.app/profile/x/post/1",)]
                return [("[@rawnba] Las Vegas NBA expansion FAQ "
                         "https://www.rawchili.com/506 more",)]

        _outlet_vocab.__defaults__[0].clear()  # reset the module-level cache
        vocab = _outlet_vocab(Con())
        assert "rawchili" in vocab
        _outlet_vocab.__defaults__[0].clear()


@pytest.fixture(autouse=True)
def _clear_vocab_cache():
    yield
    _outlet_vocab.__defaults__[0].clear()
