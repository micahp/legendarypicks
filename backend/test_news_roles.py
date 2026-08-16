"""Which lane an item belongs in, and which lanes may become a receipt.

`is_social` answered "did this arrive as a post?", and the card pipeline used
that one bit to decide both what could be cited and who counted as a fan. The
corpus has more populations than that (measured on dev 2026-08-13, 4,855 rows):
2,340 publisher articles, 209 firsthand posts from named reporters, 709 relays
carrying someone else's story, 473 brand desks, 12 ads, and 1,112 people
talking. Collapsing the middle four into "social" broke the pipeline at both
ends.

At the citable end: a tweet from Adam Schefter breaking a trade is the
reporting, and the outlet's article is downstream of him. Filing it as chatter
means a card cites the writeup of a scoop we already held.

At the fan end: `nfl-media-rights` printed "Supporters point to LSU's reported
nine-figure media-rights deal." No supporter said it. The only LSU item in the
pool was a `rawnfl` repost of an article, and no publisher item mentioned LSU at
all. The card invented the constituency and used the attribution to walk an
unverified nine-figure number past the publisher rule.

So the tests below are mostly about what must NEVER happen. Every unknown
account fails closed — absent from the roster means ordinary voice, never
trusted — and no account name appears in any rule except the hand-curated
roster itself.
"""
import pytest

from _core import REPORTER_ROSTER
from ingest_league_narratives import (
    corroboration, is_promo, is_relay, post_handle, post_role, post_text,
    speakers_shown, voice_without_speakers,
)


def post(handle="someone.bsky.social", text="a take", source="bluesky",
         url="https://bsky.app/p/1"):
    return {"headline": "[@%s] %s" % (handle, text), "url": url,
            "source": source, "body": "",
            "published": "2026-08-13T00:00:00Z"}


def article(headline="Owners approve the new media rights package",
            url="https://espn.com/a", source="espn-nfl"):
    return {"headline": headline, "url": url, "source": source, "body": "",
            "published": "2026-08-13T00:00:00Z"}


class TestNothingUnknownBecomesAReceipt:
    """The property the whole design exists to hold.

    `SOCIAL_SOURCES` failed once by MISSING the string `x` while 855 rows
    carried it, and every one of those tweets counted as a verified publisher.
    The lesson was not "write a better list" — it was that an absent entry must
    fail CLOSED. These cases are the accounts that were actually corrupting
    cards; none of them may reach a lane a reader would read as reporting.
    """

    @pytest.mark.parametrize("it", [
        post("rawnfl.bsky.social",
             "Owners approve the media deal https://rawchili.com/nfl/1 "
             "The vote was 30-2 and takes effect next season."),
        post("UnderdogNFL", "JK Dobbins left practice with trainers Monday",
             source="x"),
        post("Polymarket", "JUST IN: WNBA denounces bad faith claims",
             source="x"),
        post("cnbc.com", "Netflix lands the Gold Cup rights"),
        post("nobody.in.particular", "the cap is fake and everyone knows it"),
    ])
    def test_an_unrostered_account_is_never_citable(self, it):
        assert post_role(it) not in ("publisher", "reporting")

    def test_an_unknown_source_string_cannot_be_a_publisher(self):
        """The next feed someone adds, before anyone updates a list.

        Shape decides, not the `source` column: our collector prefixes every
        post with `[@handle]`, so a brand new source name still lands as a post.
        """
        assert post_role(post(source="x-firehose-v2")) != "publisher"

    def test_a_real_article_is_the_publisher_lane(self):
        assert post_role(article()) == "publisher"


class TestRelay:
    """Carrying someone else's story is never reporting, at any volume."""

    def test_prose_continuing_past_a_link_is_scraped_article_body(self):
        assert is_relay(post("rawnfl.bsky.social",
                             "Owners approve the deal https://rawchili.com/1 "
                             "The vote was 30-2, sources said."))

    def test_a_person_linking_at_the_end_of_their_own_words_is_not_a_relay(self):
        assert not is_relay(post("mothmaam.online",
                                 "part 12 of why the cap is circumvented, "
                                 "receipts in here https://youtu.be/x"))

    def test_a_retweet_by_a_rostered_reporter_is_still_a_relay(self):
        """The roster upgrades firsthand assertions, not everything they touch.

        "RT by @AdamSchefter: Happy to have EB back" is Schefter passing
        something along. Letting a roster entry launder it into a receipt is
        exactly the name-keyed trust the roster is supposed to avoid.
        """
        it = post("AdamSchefter", "RT by @SomeoneElse: Happy to have EB back",
                  source="x")
        assert is_relay(it)
        assert post_role(it) == "relay"

    def test_attribution_inside_the_text_is_a_relay_with_no_link_to_show_it(self):
        assert is_relay(post("SomeDesk", "Schefter: Tunsil unlikely to play",
                             source="x"))
        assert is_relay(post("SomeDesk", "Tunsil unlikely to play, per @RapSheet",
                             source="x"))

    def test_a_rostered_reporter_claiming_the_sourcing_is_not_a_relay(self):
        """`Sources:` is the signature of a scoop, not a hand-off.

        Reading every `Word:` as an attribution demoted the single highest-value
        post in the corpus — Rapoport's own Hunter Henry contract scoop — into
        the lane that may never be cited.
        """
        it = post("RapSheet", "Sources: The #Patriots have agreed to terms with "
                  "their standout TE Hunter Henry on a 2-year contract",
                  source="x")
        assert not is_relay(it)
        assert post_role(it) == "reporting"

    def test_the_carve_out_does_not_reach_an_unrostered_account(self):
        """Because the same prefix on a stranger is a headline bot.

        "Opinion:", "Feed:", "Final:" are all live in this corpus, and the fan
        lane is where a headline bot does its damage.
        """
        assert is_relay(post("some.bot", "BREAKING: Sabres fans need to cheer"))
        assert post_role(post("some.bot", "BREAKING: Sabres fans need to cheer")) == "relay"

    def test_a_marker_that_is_not_firsthand_stays_a_relay(self):
        assert is_relay(post("AdamSchefter", "Report: Tunsil unlikely to play",
                             source="x"))
        assert is_relay(post("AdamSchefter", "ICYMI: our full offseason grades",
                             source="x"))

    def test_an_outlet_posting_its_own_story_matches_on_the_STORY(self):
        """`[@cnbc.com]` beside the `cnbc` item, caught without naming either.

        Keying on "the handle is a domain" was tried first and rejected the same
        day: it also catches `[@mothmaam.online]`, a real fan whose 25-part
        video series is the entire fan voice of the Kawhi card. Bluesky lets a
        person be their own domain.
        """
        art = article("Netflix lands the Gold Cup broadcast rights",
                      url="https://cnbc.com/a", source="cnbc")
        pool = [art, post("cnbc.com", "Netflix lands the Gold Cup broadcast rights")]
        titles = {"netflixlandsthegoldcupbroadcastrights"}
        assert is_relay(pool[1], titles)
        assert post_role(pool[1], titles) == "relay"

    def test_a_fan_with_a_domain_handle_is_still_a_fan(self):
        assert post_role(post("mothmaam.online",
                              "the cap is circumvented every single year")) == "voice"


class TestPromo:
    def test_selling_something_is_not_reporting(self):
        assert is_promo(post("SomeBook", "use code LEGEND to deposit today"))

    def test_promo_is_tested_before_the_roster(self):
        it = post("AdamSchefter", "Download the app for live scores", source="x")
        assert post_role(it) == "promo"


class TestVoiceIsNotTheFallback:
    """Making `voice` the leftover branch reintroduced the same fail-open.

    The roster refuses to trust an unknown account with a receipt, and then the
    leftover branch handed that same account to the model as a fan.
    `@UnderdogNFL` — a brand desk posting "JK Dobbins left practice with
    trainers Monday", 83 items a day — came out a supporter.

    Nothing here is keyed on the name. HOW the item entered the corpus decides:
    `x` rows are timelines we chose to follow, so they are publications by
    construction and can never be a stranger reacting; `bluesky`/`x-search` rows
    are keyword searches of the open network, which is where the public is.
    """

    def test_an_unknown_account_from_a_followed_timeline_is_a_desk(self):
        assert post_role(post("UnderdogNFL", "Dobbins left practice",
                              source="x")) == "desk"

    def test_an_unknown_account_from_an_open_search_is_voice(self):
        assert post_role(post("a.fan", "this is a disaster",
                              source="bluesky")) == "voice"
        assert post_role(post("a.fan", "this is a disaster",
                              source="x-search")) == "voice"

    def test_a_desk_is_not_citable_either(self):
        assert post_role(post("UnderdogNFL", "Dobbins left practice",
                              source="x")) != "reporting"


class TestRoster:
    def test_a_rostered_reporter_posting_firsthand_is_reporting(self):
        assert post_role(post("AdamSchefter",
                              "The Bills and Ravens have agreed to terms on a trade",
                              source="x")) == "reporting"

    def test_the_roster_holds_no_aggregator(self):
        """A guard on the table itself, since it is edited by hand.

        Everything in here prints on a chip, so a scraper or a prediction-market
        account arriving by copy-paste would be published as provenance.
        """
        for handle in REPORTER_ROSTER:
            assert not any(bad in handle.lower() for bad in
                           ("raw", "polymarket", "kalshi", "underdog", "bot"))

    def test_every_entry_names_a_beat_and_a_display_name(self):
        for handle, (name, outlet, beat) in REPORTER_ROSTER.items():
            assert name and beat, handle


class TestCorroboration:
    """Computed independently of the roster, on purpose.

    A trust list that also decided what counted as confirmation could confirm
    itself. A wrong roster entry may cost us a story; it must never be able to
    make an unmatched claim read as verified. Measured over the eight rostered
    reporters: 81 corroborated, 222 single-source.
    """

    def test_an_independent_source_carrying_the_same_claim_corroborates(self):
        it = post("AdamSchefter",
                  "Bills trading receiver Stefon Diggs to the Ravens for a "
                  "second round pick", source="x")
        other = article("Ravens acquire receiver Stefon Diggs from Bills for a "
                        "second round pick", url="https://espn.com/b")
        assert corroboration(it, [it, other]) == "corroborated"

    def test_a_reporter_cannot_corroborate_themselves(self):
        it = post("AdamSchefter", "Bills trading receiver Stefon Diggs to the "
                  "Ravens for a second round pick", source="x",
                  url="https://x.com/1")
        echo = post("AdamSchefter", "Bills trading receiver Stefon Diggs to the "
                    "Ravens for a second round pick", source="x",
                    url="https://x.com/2")
        assert corroboration(it, [it, echo]) == "single-source"

    def test_being_first_is_reported_not_hidden(self):
        it = post("JeffPassan", "Cubs sign reliever Ryan Pressly to a one year "
                  "deal worth twelve million", source="x")
        assert corroboration(it, [it, article()]) == "single-source"


class TestSpeakers:
    """Who counts as a fan, for the check that catches invented constituencies.

    Written against `is_social`, this asked "was any item a post?" — and once
    rostered reporting moved into the anchors, a pool holding Schefter and no
    fan answered yes, so "Fans argue X" passed the check whose entire job was
    to catch it.
    """
    FAN_CLAIM = {"fan_voice": "Fans argue the deal shortchanges small markets."}

    def test_a_reporter_is_not_a_constituency(self):
        pool = [article(), post("AdamSchefter", "Bills and Ravens agree to terms",
                                source="x")]
        assert speakers_shown(pool) == []
        assert voice_without_speakers(self.FAN_CLAIM, pool)

    def test_a_repost_bot_is_not_a_constituency(self):
        """The `rawnfl` repost that put LSU's nine-figure number in a card."""
        pool = [article(), post("rawnfl.bsky.social",
                                "LSU signs a media rights deal "
                                "https://rawchili.com/1 The agreement runs "
                                "through 2035, the school said.")]
        assert speakers_shown(pool) == []
        assert voice_without_speakers(self.FAN_CLAIM, pool)

    def test_a_real_fan_satisfies_it(self):
        pool = [article(), post("a.fan", "this deal is a disaster for us")]
        assert len(speakers_shown(pool)) == 1
        assert not voice_without_speakers(self.FAN_CLAIM, pool)

    def test_silence_is_a_valid_outcome_not_a_failure(self):
        """Most of these cards have a publisher anchor and need no chorus."""
        assert not voice_without_speakers({"fan_voice": ""}, [article()])

    def test_a_card_that_does_not_speak_for_anyone_is_not_flagged(self):
        gen = {"fan_voice": "Rodgers said he expects to play Sunday."}
        assert not voice_without_speakers(gen, [article()])


class TestPostText:
    def test_the_collectors_handle_prefix_is_not_the_posts_words(self):
        assert post_text(post("someone", "a take")) == "a take"
        assert post_handle(post("someone", "a take")) == "someone"

    def test_an_article_has_no_handle(self):
        assert post_handle(article()) == ""
