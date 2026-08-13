"""The cards are allowed to be same-y one at a time. Stacked, they are not.

Micah, 2026-08-13: "our headlines all sound the same cus they have the same
structure". They do. Measured over the 344 generations in
`news_narratives_runs` (2026-08-07 .. 2026-08-13):

    fan_voice opening with a collective noun ..... 299/344   86.9%
    fan_voice opening one of the prompt's own
      three example strings, verbatim ............  78/344   22.7%
    titles carrying an ' as ' subordinate ........ 122/344   35.5%
    'Fans argue' alone ...........................  55/344   16.0%

The cause was in `_SYSTEM`, not in the model: the instruction that demanded
variety supplied three literal fan openers and four worked headline examples,
and the examples were written from these same 14 conversations. An example
inside the target distribution stops illustrating form and starts supplying
content — the `the outlet is not the story` shape, where a rule phrased as a
constraint on X teaches X.

The remedy is selection, not prohibition — Micah, 2026-08-13: "it should vary
but shouldn't force it to not be able to use the same structure ever again ...
have guidelines and write a couple drafts and compare to rubric and compare to
each other and write final draft." So the model writes alternates, and we only
move a sentence when it collides with another card in the SAME run. ' as ' is a
good construction; it was a rut at 36%, not a crime at 5%.

The tests pin both halves. The prompt must no longer supply the strings, and
selection must prefer an alternate over an echo — while still shipping the echo
when nothing better was written. Either half alone rots: a ban list nobody
checks against the prompt goes stale the first time someone adds a helpful
example back.
"""
import re

import pytest

from narrative_variety import (SEEDED_PHRASES, choose, opening_bigram, report,
                               resolve, rubric_score, seeded_hits, survey)


def card(conv_id="c", narrative="", fan_voice=""):
    return {"conv_id": conv_id, "narrative": narrative, "fan_voice": fan_voice}


class TestSeededPhrases:
    """The half that needs no judgment: the model handing our example back."""

    def test_the_prompt_no_longer_supplies_the_phrases_it_was_teaching(self):
        # The load-bearing test. If someone re-adds "Fans argue…" as a helpful
        # illustration, the corpus goes back to 22.7% and this says why.
        from ingest_league_narratives import _SYSTEM
        low = _SYSTEM.lower()
        found = [p for p in SEEDED_PHRASES if p in low]
        assert not found, (
            "_SYSTEM supplies phrases the cards then copy verbatim: %s. "
            "Describe the shape instead of writing one out." % found)

    def test_an_echoed_phrase_is_scored_down_not_banned(self):
        # Micah, 2026-08-13: it "shouldn't force it to not be able to use the
        # same structure ever again". So the echo costs a draft points and
        # loses to an alternate — it is never rejected outright.
        assert rubric_score("Fans argue the cap is broken and unfair to small clubs") < \
               rubric_score("Season-ticket holders say the cap punishes small clubs")

    def test_the_check_is_case_insensitive_and_finds_it_mid_sentence(self):
        assert seeded_hits("In Seattle, critics say the vote was rushed.") == ["critics say"]

    def test_an_echo_still_ships_when_it_is_the_only_thing_written(self):
        # No alternate means no choice. Shipping the model's sentence beats
        # shipping nothing, and the run log still names it.
        picked, swapped = choose([], "Fans argue the cap is broken.")
        assert picked == "Fans argue the cap is broken."
        assert not swapped


class TestChoosingBetweenDrafts:
    """Guidelines, two drafts, compare, final — the model's final wins ties."""

    def test_the_models_own_final_wins_a_tie(self):
        final = "Braves sign Acuna to a five-year extension"
        picked, swapped = choose(["Acuna signs a five-year deal with the Braves"], final)
        assert picked == final
        assert not swapped

    def test_an_alternate_is_promoted_only_when_it_scores_higher(self):
        # The final collides with a shape already used in this run; the draft
        # the model already wrote does not.
        picked, swapped = choose(
            drafts=["Acuna signs a five-year deal with the Braves"],
            final="Leagues Cup exit leaves Miami without a trophy",
            taken_openings={"leagues cup"})
        assert picked == "Acuna signs a five-year deal with the Braves"
        assert swapped

    def test_first_card_keeps_the_shape_and_the_second_moves(self):
        cards = [
            {"conv_id": "a", "narrative": "Leagues Cup exit leaves Miami without a trophy",
             "narrative_drafts": ["Miami is out of the Leagues Cup"]},
            {"conv_id": "b", "narrative": "Leagues Cup format draws complaints",
             "narrative_drafts": ["Liga MX clubs complain about the format"]},
        ]
        out, swaps = resolve(cards)
        assert out[0]["narrative"] == cards[0]["narrative"], "the first card keeps its shape"
        assert out[1]["narrative"] == "Liga MX clubs complain about the format"
        assert len(swaps) == 1 and "VARIETY SWAP" in swaps[0]

    def test_resolve_does_not_mutate_its_input(self):
        cards = [{"conv_id": "a", "narrative": "Fans argue the cap is broken",
                  "narrative_drafts": ["The cap has not moved since 2019"]}]
        before = dict(cards[0])
        resolve(cards)
        assert cards[0] == before

    def test_a_shape_may_repeat_when_no_alternate_is_better(self):
        # The point of selecting rather than banning: with nothing better on
        # offer, the repeated shape ships.
        cards = [{"conv_id": "a", "narrative": "Leagues Cup exit leaves Miami out"},
                 {"conv_id": "b", "narrative": "Leagues Cup format draws complaints"}]
        out, swaps = resolve(cards)
        assert [c["narrative"] for c in out] == [c["narrative"] for c in cards]
        assert swaps == []

    def test_selection_reads_the_field_it_was_given(self):
        cards = [{"conv_id": "a", "fan_voice": "Fans argue the cap is broken",
                  "fan_voice_drafts": ["A supporters' trust published its own count"]}]
        out, swaps = resolve(cards)
        assert out[0]["fan_voice"] == "A supporters' trust published its own count"
        assert "fan_voice" in swaps[0]


class TestOpeningBigram:
    def test_it_is_the_first_two_words_lowercased(self):
        assert opening_bigram("Leagues Cup exit leaves Miami") == "leagues cup"

    def test_a_one_word_string_is_still_usable(self):
        assert opening_bigram("Braves") == "braves"

    def test_empty_is_empty_not_an_error(self):
        assert opening_bigram("") == ""
        assert opening_bigram(None) == ""


class TestAgainstTheStoredHistory:
    """The numbers in this module's docstring must stay true of the corpus."""

    def test_the_documented_baseline_still_describes_the_old_generations(self):
        import os
        import sqlite3
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "picks.dev.db")
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = [dict(r) for r in con.execute(
                "SELECT narrative, fan_voice FROM news_narratives_runs "
                "WHERE narrative != '' AND generated_at <= '2026-08-13 23:59:59'")]
        finally:
            con.close()
        if len(rows) < 300:
            pytest.skip("dev history not present (%d rows)" % len(rows))
        voices = [r["fan_voice"] for r in rows if (r["fan_voice"] or "").strip()]
        seeded = sum(1 for v in voices if seeded_hits(v))
        as_share = sum(1 for r in rows if re.search(r"\bas\b", r["narrative"], re.I)) / len(rows)
        # Stated as floors, not equalities: new generations land in this table
        # and should push these DOWN. A rise means the fix regressed.
        assert seeded >= 70, "the historical echo count moved: %d" % seeded
        assert as_share >= 0.30, "the historical ' as ' share moved: %.3f" % as_share
