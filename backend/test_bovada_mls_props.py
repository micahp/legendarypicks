#!/usr/bin/env python3
"""MLS player props: what the parser must keep, refuse, and report.

MLS was absent from `bovada_scraper.LEAGUES` entirely while 14 fixtures and 1,464 player
outcomes sat on Bovada's board every day. The 714 props we did hold were a one-off capture
from 2026-08-07..08-09 that nothing refreshed, covering 2 markets of the 8 published.

These tests pin the three decisions that were easy to get silently wrong:

  1. The club parenthetical is OPTIONAL. Requiring it dropped 31 real players.
  2. A club tag that is not one of the fixture's two teams is STALE, not identity.
  3. A player-attributed market we have no mapping for must be REPORTED, never skipped.
"""
import os
import tempfile
import unittest

_IMPORT_TMP = tempfile.TemporaryDirectory()
os.environ["LP_DB_PATH"] = os.path.join(_IMPORT_TMP.name, "import-only.db")

import bovada_scraper as bs


def _outcome(desc, american=100):
    return {"description": desc, "price": {"american": american}}


def _event(markets_by_group, desc="Austin FC vs FC Dallas"):
    return {
        "description": desc,
        "startTime": 1786926600000,
        "competitors": [{"name": "Austin FC", "home": True},
                        {"name": "FC Dallas", "home": False}],
        "displayGroups": [
            {"description": group, "markets": markets}
            for group, markets in markets_by_group.items()
        ],
    }


class MLSPropParsingTests(unittest.TestCase):
    def setUp(self):
        bs._UNMAPPED_PLAYER_MARKETS.clear()
        bs._STALE_TEAM_TAGS.clear()

    def test_mls_is_scraped_from_bovada_for_goals_and_assists(self):
        """Bovada is the MLS source for the two markets nothing else prices.

        HISTORY. MLS was removed from LEAGUES on 2026-08-17 because Bovada prices 2 of the
        11 markets this league is built for while the RotoWire/PrizePicks relay prices 7.
        The stated reason was that a second book writing goals and assists into the same
        board would mean two sources disagreeing.

        RESTORED 2026-09-05, because that reason turned out to be false in the only way
        that matters: the relay writes ZERO goals and ZERO assists. Measured on the
        13-fixture slate of 2026-09-05 — 428 props, 8 markets, every row
        `rotowire:prizepicks`, not one goalscorer line. The newest goals row anywhere in
        the database was 2026-08-17, the day of the removal, so the product shipped a
        soccer league with no goalscorer market for 19 days.

        There is no disagreement to create when the other source is silent. Bovada's 2 and
        the relay's 7 are different markets, not competing opinions on one market.

        The route is the continent path; `soccer/usa/mls` 404s. Recorded here because
        rediscovering it cost real time once already.
        """
        self.assertEqual(bs.LEAGUES.get("mls"),
                         ("soccer", "north-america/united-states/mls"))
        self.assertTrue(callable(bs._parse_mls_props))

    def test_goal_ladder_is_one_market_at_three_lines(self):
        """Anytime / 2+ / hat trick all settle from the published `goals` stat."""
        ev = _event({"Goalscorer": [
            {"description": "Anytime Goal Scorer",
             "outcomes": [_outcome("Christian Ramirez (ATX)", 250)]},
            {"description": "To Score 2 or More Goals",
             "outcomes": [_outcome("Christian Ramirez (ATX)", 2500)]},
            {"description": "To Score a Hat Trick",
             "outcomes": [_outcome("Christian Ramirez (ATX)", 25000)]},
        ]})
        props = bs._parse_mls_props(ev)
        self.assertEqual({(p["market"], p["line"]) for p in props},
                         {("goals", 0.5), ("goals", 1.5), ("goals", 2.5)})

    def test_a_bare_name_with_no_club_tag_is_still_a_player(self):
        """31 of 1,464 outcomes carried no parenthetical. Requiring one dropped them."""
        ev = _event({"Assists": [
            {"description": "To Assist a Goal",
             "outcomes": [_outcome("Sergi Roberto"), _outcome("Ilie Sánchez (ATX)")]},
        ]})
        props = bs._parse_mls_props(ev)
        by_name = {p["player_name"]: p for p in props}
        self.assertIn("Sergi Roberto", by_name)
        self.assertEqual(by_name["Sergi Roberto"]["team"], "")
        self.assertEqual(by_name["Ilie Sánchez"]["team"], "ATX")

    def test_the_no_goalscorer_outcome_is_never_a_player(self):
        """It is the market's complement. Minting it makes a person out of a price."""
        ev = _event({"Goalscorer": [
            {"description": "Anytime Goal Scorer",
             "outcomes": [_outcome("No Goalscorer", 700), _outcome("Ilie Sánchez (ATX)")]},
        ]})
        names = {p["player_name"] for p in bs._parse_mls_props(ev)}
        self.assertEqual(names, {"Ilie Sánchez"})

    def test_a_club_tag_from_another_fixture_is_dropped_and_reported(self):
        """Bovada tags Alexis Sanchez (SEV) inside an MLS fixture between two other clubs.

        Passing SEV to the resolver turns a resolvable player into an unresolved one, so
        the tag is dropped and the resolver disambiguates on game_id instead. It is
        recorded either way -- a silent drop is a player nobody knows we lost.
        """
        ev = _event({"Goalscorer": [
            {"description": "Anytime Goal Scorer",
             "outcomes": [_outcome("Ilie Sánchez (ATX)"), _outcome("Ervin Torres (ATX)"),
                          _outcome("Petar Musa (DAL)"), _outcome("Ramiro (DAL)"),
                          _outcome("Alexis Sanchez (SEV)")]},
        ]})
        props = {p["player_name"]: p["team"] for p in bs._parse_mls_props(ev)}
        self.assertEqual(props["Alexis Sanchez"], "")
        self.assertEqual(props["Petar Musa"], "DAL")
        self.assertIn(("Alexis Sanchez", "SEV"), bs._STALE_TEAM_TAGS)

    def test_a_leagues_cup_fixture_files_under_lcup_not_mls(self):
        """A tournament fixture draws entrants FROM leagues; it is not the league.

        A Chivas (GDL) vs San Diego (SD) Leagues Cup fixture must file its props under
        `lcup` -- the tournament's own competition key -- so GDL players stay resolvable
        against Liga MX rather than being minted as shadow MLS players nobody's spine
        can resolve (the 2026-08-17 defect: AME/GDL/PUE/TOL rows under `mls`).
        """
        ev = _event({"Goalscorer": [
            {"description": "Anytime Goal Scorer",
             "outcomes": [_outcome("David Morales (GDL)"), _outcome("Hirving Lozano (GDL)"),
                          _outcome("Christopher McVey (SD)")]},
        ]}, desc="Chivas Guadalajara vs San Diego FC")
        props = bs._parse_mls_props(ev)
        self.assertTrue(props)
        self.assertEqual({p["league"] for p in props}, {"lcup"})
        # A GDL player keeps its club tag: it is resolvable against Liga MX.
        self.assertEqual(next(p for p in props if p["player_name"] == "David Morales")["team"], "GDL")

    def test_an_mls_fixture_still_files_under_mls(self):
        """The same parser keeps filing a real MLS fixture under `mls`."""
        ev = _event({"Goalscorer": [
            {"description": "Anytime Goal Scorer",
             "outcomes": [_outcome("Ilie Sánchez (ATX)"), _outcome("Petar Musa (DAL)")]},
        ]})
        props = bs._parse_mls_props(ev)
        self.assertTrue(props)
        self.assertEqual({p["league"] for p in props}, {"mls"})

    def test_an_unmapped_player_market_is_reported_and_exits_nonzero(self):
        """A market Bovada adds later must surface, not vanish into a plausible count."""
        ev = _event({"Goalscorer": [
            {"description": "To Score From Outside The Box",
             "outcomes": [_outcome("Ilie Sánchez (ATX)"), _outcome("Petar Musa (DAL)")]},
        ]})
        self.assertEqual(bs._parse_mls_props(ev), [])
        self.assertEqual(len(bs._UNMAPPED_PLAYER_MARKETS), 1)
        self.assertEqual(bs._run_report({}, did_ingest=False), 3)

    def test_a_team_market_in_a_player_group_is_not_reported_as_unmapped(self):
        """"Total Cards O/U - Seattle Sounders" is a team total sharing the Cards group."""
        ev = _event({"Cards": [
            {"description": "Total Cards O/U - Austin FC",
             "outcomes": [_outcome("Over"), _outcome("Under")]},
        ]})
        self.assertEqual(bs._parse_mls_props(ev), [])
        self.assertEqual(bs._UNMAPPED_PLAYER_MARKETS, {})

    def test_resolving_none_of_what_was_scraped_exits_nonzero(self):
        """`0 ingested` is a finding, not a result (fail-loudly §2a)."""
        counts = {"mls": {"scraped": 1461, "ingested": 0, "refreshed": 0,
                          "unresolved": 1461, "games_failed": 0, "games": 14}}
        self.assertEqual(bs._run_report(counts, did_ingest=True), 3)

    def test_a_clean_run_exits_zero(self):
        counts = {"mls": {"scraped": 1461, "ingested": 3, "refreshed": 1433,
                          "unresolved": 25, "games_failed": 0, "games": 14}}
        self.assertEqual(bs._run_report(counts, did_ingest=True), 0)


if __name__ == "__main__":
    unittest.main()
