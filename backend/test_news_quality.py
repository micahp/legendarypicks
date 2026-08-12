"""The display bar for news items we did NOT synthesize.

Scope note, because this was got wrong once: this module ranks RAW `news_items`
only. Synthesized conversation cards are deliberately NOT gated on having
receipts — a conversation whose chatter is all social still gets a card, and it
renders with no source chips rather than being dropped (Micah; see the design
note in `ingest_league_narratives._generate`). Six of fourteen cards on dev are
chatter-only by design, and a "quality floor" that removed them was removing the
feature.
"""
from datetime import datetime, timedelta, timezone

from news_quality import item_disqualified, item_score, rank_items

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def item(**kw):
    base = {
        "headline": "Some headline",
        "body": "",
        "url": "https://espn.com/story/1",
        "published": (NOW - timedelta(hours=6)).isoformat(),
        "layer": "narrative",
        "source": "espn-nfl",
        "key_player": "",
    }
    base.update(kw)
    return base


class TestFloors:
    def test_chaff_is_refused(self):
        # A reporter announcing a holiday was on the board as news.
        assert item_disqualified(
            item(headline="[@TheAthleticNHL] RT by @x: I'm off this week. Wasn't going to post"),
            NOW)

    def test_stale_is_refused(self):
        # 2.4% of the displayed pool was published in 2025.
        why = item_disqualified(item(published="2025-08-21T00:00:00+00:00"), NOW)
        assert why and "stale" in why

    def test_fresh_reporting_survives(self):
        assert item_disqualified(item(), NOW) is None

    def test_a_retweet_is_not_disqualified(self):
        # An RT of real injury news is real injury news. It is penalised in the
        # score and deduplicated, never refused for being an RT.
        assert item_disqualified(
            item(headline="[@TheAthleticNFL] RT by @TheAthleticNFL: Tunsil tore a triceps"),
            NOW) is None


class TestRanking:
    def test_injury_outranks_a_thinkpiece(self):
        # The regression that made this weighting exist: publisher tier alone
        # put "What brought Cole Anthony to the NBL?" above a torn triceps.
        injury = item(headline="Burden limps off with leg injury", layer="injury",
                      source="deadspin", url="https://deadspin.com/a")
        feature = item(headline="What brought Cole Anthony to the NBL?", layer="narrative",
                       source="espn-nba", url="https://espn.com/b")
        assert item_score(injury, NOW) > item_score(feature, NOW)

    def test_fresh_outranks_old_at_equal_layer(self):
        new = item(published=(NOW - timedelta(hours=2)).isoformat())
        old = item(published=(NOW - timedelta(days=10)).isoformat())
        assert item_score(new, NOW) > item_score(old, NOW)

    def test_first_hand_outranks_the_retweet_of_it(self):
        first = item(headline="Tunsil tore a triceps", layer="injury")
        rt = item(headline="[@A] RT by @A: Tunsil tore a triceps", layer="injury")
        assert item_score(first, NOW) > item_score(rt, NOW)

    def test_missing_body_is_not_penalised(self):
        # 45% of the pool is body-less and much of it is the best material we
        # carry — a wire post's headline IS the item.
        assert item_score(item(body=""), NOW) > 0


class TestDedupeAndTrim:
    def test_one_story_arriving_five_times_collapses(self):
        rows = [item(headline="Commanders moving Brandon Coleman back to LT", layer="trade")]
        rows += [item(headline="[@A] RT by @A: Commanders moving Brandon Coleman back to LT",
                      layer="trade") for _ in range(4)]
        out = rank_items(rows, trim=0.0, now=NOW)
        assert len(out) == 1
        # and the survivor is the first-hand copy, not a retweet of it
        assert not out[0]["headline"].startswith("[@A]")

    def test_trims_the_requested_fraction(self):
        rows = [item(headline=f"story {i}", layer="injury") for i in range(10)]
        assert len(rank_items(rows, trim=0.20, now=NOW)) == 8

    def test_never_trims_to_nothing(self):
        assert len(rank_items([item()], trim=0.9, now=NOW)) == 1

    def test_all_disqualified_yields_empty(self):
        # An empty state is correct here; min_keep must not resurrect a floor.
        assert rank_items([item(published="2025-01-01T00:00:00+00:00")], now=NOW) == []

    def test_output_is_best_first(self):
        rows = [item(headline="a", layer="narrative"), item(headline="b", layer="injury")]
        assert rank_items(rows, trim=0.0, now=NOW)[0]["headline"] == "b"
