"""Tests for the pure relationship graph built from NBA.com player movement rows."""
import json
import os
import sqlite3
import unittest

import ingest_nba_player_movement as ingest
import sports_relationships as sr

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "fixtures", "nba_player_movement_sample.json")

DURANT, GREEN, BROOKS, CAPELA = "201142", "1630224", "1628415", "203991"


def rows_from(payload):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE player_source_ids(player_id INT, league TEXT, source TEXT, source_player_key TEXT)")
    ingest.ingest(con, payload, now="2026-11-13T00:00:00+00:00")
    return [dict(r) for r in con.execute("SELECT * FROM nba_player_movement ORDER BY id")]


def sample_payload():
    with open(SAMPLE) as handle:
        return json.load(handle)


def extra(payload, *new_rows):
    out = json.loads(json.dumps(payload))
    out["NBA_Player_Movement"]["rows"].extend(new_rows)
    return out


def raw(date, kind, desc, slug, pid, pslug, group=None, order=0.0):
    return {"Transaction_Type": kind, "TRANSACTION_DATE": date + "T00:00:00",
            "TRANSACTION_DESCRIPTION": desc, "TEAM_ID": 0.0, "TEAM_SLUG": slug,
            "PLAYER_ID": float(pid), "PLAYER_SLUG": pslug, "Additional_Sort": order,
            "GroupSort": group}


class Trades(unittest.TestCase):
    def setUp(self):
        self.graph = sr.build_graph(rows_from(sample_payload()))

    def test_durant_trade_direction(self):
        moves = {m.player_key: (m.from_team, m.to_team) for m in self.graph.movements()}
        self.assertEqual(moves[DURANT], ("PHX", "HOU"))
        self.assertEqual(moves[GREEN], ("HOU", "PHX"))
        self.assertEqual(moves[BROOKS], ("HOU", "PHX"))
        self.assertNotEqual(moves[DURANT], ("HOU", "PHX"))

    def test_one_transaction_node_for_the_multi_team_deal(self):
        deals = [t for t in self.graph.transactions if DURANT in t.player_keys]
        self.assertEqual(len(deals), 1)
        deal = deals[0]
        self.assertEqual(deal.teams, {"ATL", "BKN", "HOU", "MIN", "PHX"})
        self.assertEqual(deal.effective_date, "2025-07-06")
        self.assertEqual({m.player_key for m in deal.movements}, {DURANT, GREEN, BROOKS, CAPELA})
        self.assertEqual(len(deal.other_assets), 4)       # draft consideration rows kept, not dropped

    def test_a_conflict_or_unparsed_row_never_enters_the_graph(self):
        rows = rows_from(sample_payload())
        for row in rows:
            if row["nba_player_id"] == DURANT:
                row["direction_check"] = "conflict"
        graph = sr.build_graph(rows)
        self.assertNotIn(DURANT, {m.player_key for m in graph.movements()})
        self.assertEqual(graph.excluded_rows, 1)

    def test_players_are_keyed_on_id_not_name(self):
        moves = [m for m in self.graph.movements() if m.player_key == DURANT]
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0].player_key, DURANT)

    def test_reciprocal_trade_between_two_teams(self):
        deal = [t for t in self.graph.transactions if DURANT in t.player_keys][0]
        pair = sr.reciprocal_players(deal, "HOU", "PHX")
        self.assertEqual(pair["HOU_to_PHX"], {GREEN, BROOKS})
        self.assertEqual(pair["PHX_to_HOU"], {DURANT})
        self.assertIsNone(sr.reciprocal_players(deal, "HOU", "ATL"))   # Capela only went one way

    def test_as_of_hides_a_later_trade(self):
        before = sr.build_graph(rows_from(sample_payload()), as_of="2025-07-05")
        self.assertNotIn(DURANT, {m.player_key for m in before.movements()})
        after = sr.build_graph(rows_from(sample_payload()), as_of="2025-07-06")
        self.assertIn(DURANT, {m.player_key for m in after.movements()})


class Stints(unittest.TestCase):
    def graph(self, *new_rows):
        return sr.build_graph(rows_from(extra(sample_payload(), *new_rows)))

    def test_trade_starts_a_stint_and_ends_the_previous_one(self):
        graph = self.graph(
            raw("2022-02-10", "Trade", "Phoenix Suns received forward Kevin Durant from Brooklyn Nets.",
                "suns", 201142, "kevin-durant", "Trade 2023001"))
        stints = graph.stints(DURANT)
        phx = [s for s in stints if s.team == "PHX"]
        self.assertEqual(len(phx), 1)
        self.assertEqual(phx[0].start, "2022-02-10")
        self.assertEqual(phx[0].end, "2025-07-06")
        self.assertEqual(stints[-1].team, "HOU")
        self.assertIsNone(stints[-1].end)                   # still open

    def test_a_stint_that_starts_before_coverage_is_marked(self):
        graph = self.graph()
        first = graph.stints(DURANT)[0]
        self.assertEqual(first.team, "PHX")
        self.assertFalse(first.start_covered)               # nothing in the file says when he joined PHX
        last = graph.stints(DURANT)[-1]
        self.assertTrue(last.start_covered)

    def test_returning_to_the_same_team_makes_two_stints(self):
        graph = self.graph(
            raw("2016-01-05", "Trade", "Houston Rockets received forward Kevin Durant from Phoenix Suns.",
                "rockets", 201142, "kevin-durant", "Trade 2016001"),
            raw("2018-01-05", "Trade", "Phoenix Suns received forward Kevin Durant from Houston Rockets.",
                "suns", 201142, "kevin-durant", "Trade 2018001"))
        teams = [s.team for s in graph.stints(DURANT)]
        self.assertEqual(teams.count("HOU"), 2)

    def test_stint_carries_evidence_ids(self):
        graph = self.graph()
        last = graph.stints(DURANT)[-1]
        self.assertTrue(last.start_evidence)
        self.assertTrue(all(isinstance(e, str) for e in last.start_evidence))

    def test_a_waive_closes_the_stint(self):
        graph = self.graph(
            raw("2026-01-10", "Waive", "Houston Rockets waived forward Kevin Durant.",
                "rockets", 201142, "kevin-durant"))
        last = graph.stints(DURANT)[-1]
        self.assertEqual(last.end, "2026-01-10")


class SharedTenure(unittest.TestCase):
    def graph(self):
        return sr.build_graph(rows_from(extra(
            sample_payload(),
            raw("2017-07-01", "Signing", "Boston Celtics re-signed forward Jayson Tatum to a Rookie Scale Contract.",
                "celtics", 1628369, "jayson-tatum"),
            raw("2016-07-27", "Signing", "Boston Celtics re-signed guard Jaylen Brown to a Rookie Scale Contract.",
                "celtics", 1627759, "jaylen-brown"),
            raw("2026-07-06", "Trade", "Philadelphia 76ers received guard Jaylen Brown from Boston Celtics.",
                "sixers", 1627759, "jaylen-brown", "Trade 2026001"))))

    def test_shared_tenure_is_the_overlap_on_the_same_team(self):
        shared = self.graph().shared_tenure("1627759", "1628369")
        self.assertEqual(len(shared), 1)
        self.assertEqual(shared[0].team, "BOS")
        self.assertEqual(shared[0].start, "2017-07-01")
        self.assertEqual(shared[0].end, "2026-07-06")

    def test_players_on_different_teams_at_the_same_time_do_not_share_tenure(self):
        shared = self.graph().shared_tenure(DURANT, "1628369")
        self.assertEqual(shared, [])

    def test_a_re_sign_row_does_not_prove_when_the_tenure_began(self):
        shared = self.graph().shared_tenure("1627759", "1628369")
        self.assertFalse(shared[0].complete)                 # "re-signed" means they were already there

    def test_shared_tenure_is_complete_when_both_starts_are_documented(self):
        graph = sr.build_graph(rows_from(extra(
            sample_payload(),
            raw("2020-01-01", "Signing", "Boston Celtics signed guard Some Guy to a Contract.",
                "celtics", 111, "some-guy"),
            raw("2021-01-01", "Signing", "Boston Celtics signed guard Other Guy to a Contract.",
                "celtics", 222, "other-guy"),
            raw("2023-01-01", "Waive", "Boston Celtics waived guard Some Guy.",
                "celtics", 111, "some-guy"))))
        overlap = graph.shared_tenure("111", "222")
        self.assertEqual((overlap[0].start, overlap[0].end, overlap[0].complete),
                         ("2021-01-01", "2023-01-01", True))

    def test_no_first_claim_without_coverage(self):
        graph = self.graph()
        self.assertEqual(graph.coverage_start, "2016-07-27")   # earliest row in this fixture
        self.assertFalse(graph.covers("2014-06-01"))
        self.assertTrue(graph.covers("2016-08-01"))


class FormerTeams(unittest.TestCase):
    def test_former_teams_come_from_documented_movement(self):
        graph = sr.build_graph(rows_from(sample_payload()))
        former = {f.team: f for f in graph.former_teams(DURANT, current_team="HOU")}
        self.assertIn("PHX", former)
        self.assertEqual(former["PHX"].left_on, "2025-07-06")
        self.assertNotIn("HOU", former)

    def test_a_player_never_documented_on_a_team_has_no_tie_to_it(self):
        graph = sr.build_graph(rows_from(sample_payload()))
        self.assertNotIn("OKC", {f.team for f in graph.former_teams(DURANT, current_team="HOU")})


if __name__ == "__main__":
    unittest.main()
