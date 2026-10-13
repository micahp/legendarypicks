#!/usr/bin/env python3
"""Contracts for the PrizePicks props importer.

The payload this parses is fetched by a human browser, because PrizePicks blocks
this box's IP estate-wide. The fixture below is shaped from the real 2026-08-25
`/projections?league_id=82` response, field for field: `data[]` are projections
whose `relationships.new_player` points into `included[]`, `attributes.
description` names the OPPONENT and never which side is home, and `odds_type`
distinguishes a standard line from the boosted demon/goblin variants.
"""
import os
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import ingest_prizepicks_props as pp  # noqa: E402


def payload(team, description, stat="Shots", line=2.5, odds_type="demon",
            status="pre_game", name="A Player"):
    return {
        "data": [{
            "type": "projection", "id": "1",
            "attributes": {"stat_type": stat, "line_score": line,
                           "description": description, "odds_type": odds_type,
                           "status": status, "start_time": "2026-08-25T20:30:00-04:00"},
            "relationships": {"new_player": {"data": {"type": "new_player", "id": "9"}}},
        }],
        "included": [{"type": "new_player", "id": "9",
                      "attributes": {"name": name, "team": team, "league": "SOCCER"}}],
    }


# The published spellings, as `team_vocabulary` returns them: normalized name to
# `roster_league:CODE`.
VOCAB = {
    "real salt lake": "mls:RSL",
    "club leon": "ligamx:LEO",
    "chicago fire": "mls:CHI",
    "columbus crew": "mls:CLB",
    "cf monterrey": "ligamx:MTY",
}


class AClubNamedByAFragment(unittest.TestCase):
    """The defect that dropped a whole fixture on 2026-08-25.

    PrizePicks writes `Salt Lake` for Real Salt Lake. The first fallback matched
    LEADING fragments only, so `Salt Lake` missed, both sides of Leon vs Real
    Salt Lake failed to resolve, and 380 props vanished. Nothing raised: the
    fixture simply was not in the output, which is why the count reconciliation
    matters more than the absence of an error.
    """

    def test_a_trailing_fragment_resolves(self):
        self.assertEqual(pp.resolve_club(VOCAB, "Salt Lake"), "mls:RSL")

    def test_a_leading_fragment_resolves(self):
        self.assertEqual(pp.resolve_club(VOCAB, "Chicago"), "mls:CHI")
        self.assertEqual(pp.resolve_club(VOCAB, "Columbus"), "mls:CLB")

    def test_an_exact_published_spelling_still_resolves(self):
        self.assertEqual(pp.resolve_club(VOCAB, "Club León"), "ligamx:LEO")

    def test_a_fragment_naming_two_clubs_resolves_to_neither(self):
        # Fail closed. Widening an ambiguous code is how a Liga MX player lands
        # on an MLS roster -- the same reason the props endpoint refuses `ATL`.
        ambiguous = {"atlanta united": "mls:ATL", "atlante fc": "ligamx:ATE"}
        self.assertIsNone(pp.resolve_club(ambiguous, "Atl"))

    def test_a_fragment_must_be_a_whole_word(self):
        self.assertIsNone(pp.resolve_club({"leones negros": "ligamx:LEN"}, "Leon"))


class TheVariantIsNotFlattenedAway(unittest.TestCase):
    """A demon is a harder line and a goblin an easier one, both with adjusted
    payouts and only More offered. Recording them as plain over/unders would
    file a different bet than the one the book is taking. On the 2026-08-25
    board only 16 of 1,653 rows were standard, so this is the common case."""

    def test_each_odds_type_keeps_its_own_source(self):
        seen = {}
        for odds_type in ("standard", "demon", "goblin"):
            rows, _ = pp.parse([payload("Chicago", "CF Monterrey",
                                        odds_type=odds_type)], VOCAB)
            seen[odds_type] = rows[0]["source"]
        self.assertEqual(seen, {"standard": "prizepicks",
                                "demon": "prizepicks-demon",
                                "goblin": "prizepicks-goblin"})


class WhatWeRefuseToIngest(unittest.TestCase):
    def test_fantasy_score_is_reported_not_ingested(self):
        # Same rule as the MLB and RotoWire Fantasy Score ids: a composite of a
        # scoring formula the publisher does not send cannot be settled.
        rows, report = pp.parse(
            [payload("Chicago", "CF Monterrey", stat="Outfield Fantasy Score")],
            VOCAB)
        self.assertEqual(rows, [])
        self.assertEqual(dict(report["unmapped"]), {"Outfield Fantasy Score": 1})

    def test_a_settled_projection_is_skipped(self):
        rows, report = pp.parse(
            [payload("Chicago", "CF Monterrey", status="final")], VOCAB)
        self.assertEqual(rows, [])
        self.assertEqual(report["counts"]["not_pre_game"], 1)

    def test_another_competition_is_not_ours(self):
        # PrizePicks files every competition under one SOCCER league, so most of
        # the payload is La Liga and the EPL.
        rows, _ = pp.parse([payload("Real Madrid", "Real Sociedad")], VOCAB)
        self.assertEqual(rows, [])


class TheRowsCarryWhatTheBoardNeeds(unittest.TestCase):
    def test_a_resolved_row(self):
        rows, _ = pp.parse([payload("Salt Lake", "Club León", stat="Tackles",
                                    line=1.5, name="Diego Luna")], VOCAB)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["player_name"], "Diego Luna")
        self.assertEqual(row["team"], "RSL")
        self.assertEqual(row["roster_league"], "mls")
        self.assertEqual(row["opponent"], "LEO")
        self.assertEqual(row["market"], "tackles")
        self.assertEqual(row["line"], 1.5)
        self.assertEqual(row["side"], "over")


if __name__ == "__main__":
    unittest.main()
