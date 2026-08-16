"""What a card is allowed to call news, and when it is allowed to change.

Two defects, both measured on dev 2026-08-12, both of which produced cards
that read perfectly well:

  1. **The oldest item supplied the headline.** Relevance ranking has no
     opinion about time, so the single most on-topic article a conversation
     holds can be a year old — and for `mls-leaguescup-proving` it was: a 2025
     ESPN feature, "How Leagues Cup is becoming a hotbed for global scouting".
     The card led with "Leagues Cup becomes a global scouting stage" in August
     2026. Micah: "Leagues Cup is already a proving ground and them signing him
     is proof. it's maturing." Every item already carried its publish date and
     the prompt already said to mind them; a date on line 1 of ten is a fact
     the model must act on, so the items are now GROUPED.

  2. **Every run rewrote every card.** Nothing recorded what a served card was
     built from, so "did anything change?" was unanswerable and the only
     available answer was to write it again. New title, new prose, same story.
     A card whose headline moves nightly while the story stands still teaches
     a reader that a change means nothing.
"""
import datetime

import pytest

from ingest_league_narratives import (
    _norm_words, _numbered, _significant, _topic_hits, _topic_words,
    is_background, newest_item, pool_key, split_by_age, stale_anchor, weak_seed,
)

TODAY = datetime.date(2026, 8, 12)


def item(published, headline="A headline", url=None, source="espn"):
    return {"headline": headline, "url": url or ("https://x/%s" % published),
            "source": source, "body": "", "published": published}


class TestBackground:
    def test_this_weeks_reporting_is_a_development(self):
        assert not is_background(item("2026-08-10T00:00:00Z"), TODAY)

    def test_last_years_feature_is_background(self):
        """The exact item: ESPN, 2025-08-21, in a card generated 2026-08-12."""
        assert is_background(item("2025-08-21T12:00:21Z"), TODAY)

    def test_an_undated_item_is_background(self):
        """We cannot claim an item is new when we do not know that it is."""
        assert is_background(item(""), TODAY)
        assert is_background({"headline": "h", "url": "u", "source": "s"}, TODAY)

    def test_the_boundary_is_three_weeks(self):
        assert not is_background(item("2026-07-25T00:00:00Z"), TODAY)   # 18d
        assert is_background(item("2026-07-10T00:00:00Z"), TODAY)       # 33d


class TestSplitByAge:
    def test_it_separates_the_two_groups(self):
        shown = [item("2025-08-21T00:00:00Z"), item("2026-08-10T00:00:00Z")]
        fresh, old = split_by_age(shown, TODAY)
        assert [i for i, _ in fresh] == [1]
        assert [i for i, _ in old] == [0]

    def test_grouping_never_renumbers(self):
        """Citations resolve by the number the prompt shows, and the prompt
        shows the item's index in the shown list. Reordering the display must
        not move a number onto a different article — that is the drift bug
        from test_news_provenance, reintroduced by a cosmetic change."""
        shown = [item("2025-01-01T00:00:00Z", url="old"),
                 item("2026-08-11T00:00:00Z", url="new"),
                 item("2024-01-01T00:00:00Z", url="older")]
        fresh, old = split_by_age(shown, TODAY)
        assert dict(fresh + old)[1]["url"] == "new"
        assert [i for i, _ in fresh + old] == [1, 0, 2]


class TestNumbered:
    def test_the_model_is_told_which_items_are_the_news(self):
        text = _numbered([item("2025-08-21T00:00:00Z", "Old feature"),
                          item("2026-08-10T00:00:00Z", "New result")],
                         today=TODAY)
        assert "DEVELOPMENTS" in text and "BACKGROUND" in text
        assert text.index("New result") < text.index("Old feature")

    def test_the_numbers_still_match_the_shown_order(self):
        text = _numbered([item("2025-08-21T00:00:00Z", "Old feature"),
                          item("2026-08-10T00:00:00Z", "New result")],
                         today=TODAY)
        assert "2. New result" in text
        assert "1. Old feature" in text

    def test_an_all_background_pool_says_so_rather_than_implying_news(self):
        text = _numbered([item("2025-08-21T00:00:00Z", "Old feature")],
                         today=TODAY)
        assert "NOTHING NEW" in text
        assert "DEVELOPMENTS" not in text


class TestStaleAnchor:
    def card(self, *urls):
        return {"narrative": "n", "sources": [{"url": u} for u in urls]}

    def test_citing_only_a_year_old_feature_is_reported(self):
        shown = [item("2025-08-21T00:00:00Z", url="espn-2025"),
                 item("2026-08-10T00:00:00Z", url="match-report")]
        assert stale_anchor(self.card("espn-2025"), shown, TODAY)

    def test_citing_the_background_alongside_the_news_is_fine(self):
        """Background is legitimate context — the card the desk should write
        cites both, and says when the old one was said."""
        shown = [item("2025-08-21T00:00:00Z", url="espn-2025"),
                 item("2026-08-10T00:00:00Z", url="match-report")]
        assert not stale_anchor(
            self.card("espn-2025", "match-report"), shown, TODAY)

    def test_a_pool_with_no_developments_is_not_stale(self):
        """Nothing to reach past. A standing state of play is a real card."""
        shown = [item("2025-08-21T00:00:00Z", url="espn-2025")]
        assert not stale_anchor(self.card("espn-2025"), shown, TODAY)

    def test_a_pool_whose_only_developments_are_posts_is_not_stale(self):
        """A social post can never become a source chip, so demanding the card
        cite one asks for the very leak the SOCIAL LEAK check forbids.
        `mls-leaguescup-proving` 2026-08-12: three developments, all posts, and
        the card was already carrying them correctly as fan voice."""
        shown = [item("2025-08-21T00:00:00Z", url="https://espn.com/feature"),
                 item("2026-08-06T00:00:00Z", url="https://bsky.app/p/1",
                      source="bluesky"),
                 item("2026-08-12T00:00:00Z", url="https://x.com/p/2",
                      source="x")]
        assert not stale_anchor(self.card("https://espn.com/feature"), shown,
                                TODAY)

    def test_a_published_development_alongside_posts_still_counts(self):
        shown = [item("2025-08-21T00:00:00Z", url="https://espn.com/feature"),
                 item("2026-08-06T00:00:00Z", url="https://bsky.app/p/1",
                      source="bluesky"),
                 item("2026-08-10T00:00:00Z", url="https://espn.com/report")]
        assert stale_anchor(self.card("https://espn.com/feature"), shown, TODAY)

    def test_a_card_citing_nothing_is_another_checks_problem(self):
        assert not stale_anchor(self.card(), [item("2026-08-10T00:00:00Z")],
                                TODAY)


class TestPoolKey:
    def test_the_same_pool_fingerprints_the_same(self):
        pool = [item("2026-08-10T00:00:00Z"), item("2026-08-11T00:00:00Z")]
        assert pool_key(pool) == pool_key(list(reversed(pool)))

    def test_a_new_article_changes_the_fingerprint(self):
        pool = [item("2026-08-10T00:00:00Z")]
        assert pool_key(pool) != pool_key(pool + [item("2026-08-11T00:00:00Z")])

    def test_a_swap_at_equal_count_changes_the_fingerprint(self):
        """Counting items would call these two pools identical. They are two
        different stories."""
        a = [item("2026-08-10T00:00:00Z", url="a")]
        b = [item("2026-08-10T00:00:00Z", url="b")]
        assert pool_key(a) != pool_key(b)

    def test_an_editor_mark_earns_a_rewrite(self):
        """Feedback is a reason to regenerate even with no new reporting —
        the marks are part of what the card was written from."""
        pool = [item("2026-08-10T00:00:00Z")]
        assert pool_key(pool, "GOOD: more of this") != pool_key(pool, "")


class TestNewestItem:
    def test_it_reports_the_freshest_timestamp(self):
        assert newest_item([item("2025-08-21T00:00:00Z"),
                            item("2026-08-10T00:00:00Z")]) == \
            "2026-08-10T00:00:00Z"

    def test_an_empty_pool_has_no_timestamp(self):
        assert newest_item([]) == ""


@pytest.mark.parametrize("published,expected", [
    ("2026-08-12T00:00:00Z", False),
    ("2026-05-01T00:00:00Z", True),
])
def test_the_leagues_cup_regression(published, expected):
    """The card that started this: a 2025 ESPN feature must never be the
    thing a card announces as happening now."""
    assert is_background(item(published), TODAY) is expected


class TestTopicWords:
    """The length floor threw away the word the conversation is NAMED for.

    `len(w) > 4` was applied on BOTH sides — to the seed and to every headline
    — so a word had to be five characters to exist at all. `nfl-turf-grass`
    kept `grass` and lost **turf**; both salary-cap conversations kept `salary`
    and lost **cap**. Measured across the 14 live conversations 2026-08-12,
    restoring them moved 10 of 14 to a higher top score with fewer candidates
    tied on it (turf 1/25 -> 3/11, cap 1/22 -> 3/18).
    """

    def conv(self, seed, title=""):
        return {"id": "c", "league": "nfl", "seed": seed, "title": title}

    def test_the_word_the_conversation_is_named_for_survives(self):
        assert "turf" in _topic_words(self.conv("nfl turf grass"))
        assert "cap" in _topic_words(self.conv("nhl salary cap"))

    def test_it_matches_that_word_in_a_headline_too(self):
        """Both sides, or the seed word has nothing to match against."""
        tw = _topic_words(self.conv("nfl turf grass"))
        assert _topic_hits("Patriots turf ruled noncompliant", tw) >= 1

    def test_turf_beats_a_headline_that_only_shares_the_league(self):
        tw = _topic_words(self.conv("nfl turf grass"))
        assert (_topic_hits("NFL turf and grass fight returns", tw)
                > _topic_hits("NFL schedule released", tw))

    def test_short_stopwords_are_named_not_guessed_by_length(self):
        tw = _topic_words(self.conv("the cap and the new deal"))
        assert "cap" in tw
        for w in ("the", "and", "new", "deal"):
            assert w not in tw

    def test_a_generic_word_still_counts_for_nothing(self):
        assert "league" not in _topic_words(self.conv("league news"))

    def test_the_ranker_uses_the_same_filter_as_the_alarm(self):
        """The first pass at this fixed `_topic_words` and `_topic_hits` and
        left the RANKER's own inline `len(w) > 4` at ingest_league_narratives
        :448 untouched — so the alarm measured a discrimination the scorer
        never actually got. Both sides read `_significant` or the alarm is
        reporting on a scorer that does not exist.
        """
        head = "Patriots turf ruled noncompliant"
        assert _significant(head) == {w for w in _norm_words(head)
                                      if len(w) > 2} - {"the", "and"}
        assert "turf" in _significant(head)


class TestWeakSeed:
    """A tie at the top means recency picked the winner, not the seed."""

    def test_a_wide_tie_is_reported(self):
        """`esports worlds`: 57 candidates tied, because `esports` matches
        everything in its own league and "Esports World Cup" catches `worlds`
        too. The card was about the wrong tournament."""
        assert weak_seed("Lenovo joins Esports World Cup 2026",
                         {"esports", "worlds"}, 57)

    def test_a_seed_that_discriminates_is_silent(self):
        assert not weak_seed(
            "Berg says no to promotion and relegation for MLS",
            {"promotion", "relegation", "division"}, 1)

    def test_a_one_word_seed_is_not_convicted_of_its_own_ceiling(self):
        """`realignment` can never land two hits, so demanding two flagged a
        seed whose top three results were all realignment stories."""
        assert not weak_seed("College Football Realignment: ranking G6 teams",
                             {"realignment"}, 2)

    def test_a_one_word_seed_that_misses_entirely_is_still_reported(self):
        assert weak_seed("College Football Power Rankings for 2026",
                         {"realignment"}, 2)

    def test_one_hit_out_of_several_words_is_recency_in_disguise(self):
        assert weak_seed("College Football Conference Power Rankings",
                         {"ncaaf", "conference", "realignment"}, 3)
