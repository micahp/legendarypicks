#!/usr/bin/env python3
"""Phase 1 tests — EWC CoD scoreboard reconciliation (raw-TBD repair).

Fixture-driven: the graph is built from the captured PandaScore bracket/serie fixtures and rows
from the captured Breaking Point feed (captured 2026-08-08 13:20-13:35 UTC). No network calls.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_TEST_DB = tempfile.NamedTemporaryFile(prefix="cod-ewc-", suffix=".db", delete=False)
_TEST_DB.close()
os.environ["LP_DB_PATH"] = _TEST_DB.name

from routers.esports import cod_ewc  # noqa: E402
from routers.esports.ewc import participant_label  # noqa: E402

FIX = os.path.join(HERE, "..", "docs", "ewc2026", "fixtures")


def _load(name):
    with open(os.path.join(FIX, name)) as f:
        return json.load(f)


def _graph():
    bracket = _load("pandascore-ewc-cod-brackets-2026-08-08T1325Z.json")
    serie = _load("pandascore-codmw-serie10834-matches-2026-08-08T1330Z.json")
    return cod_ewc.build_ewc_cod_graph(bracket, serie)


def _bp_rows():
    return _load("cod-games-normalized-2026-08-08T1335Z.json")


class GraphBuildTests(unittest.TestCase):
    def test_graph_has_all_eight_bracket_nodes(self):
        g = _graph()
        self.assertEqual(len(g["nodes"]), 8)
        self.assertEqual(len(g["by_round"]["quarterfinal"]), 4)
        self.assertEqual(len(g["by_round"]["semifinal"]), 2)
        self.assertEqual(len(g["by_round"]["3rd place"]), 1)
        self.assertEqual(len(g["by_round"]["grand final"]), 1)

    def test_group_matches_indexed(self):
        g = _graph()
        # 27 serie matches = 20 group-stage + 7 that overlap bracket nodes (the running QF2 is
        # absent from the upcoming/past feeds). All 20 group matches are indexed.
        self.assertEqual(len(g["group_matches"]), 20)


class ResolveSidesTests(unittest.TestCase):
    def setUp(self):
        self.g = _graph()

    def test_quarterfinal_sides_are_named(self):
        a, b = cod_ewc.resolve_sides(self.g, 1609942)  # QF1 G2 vs HTCS (finished)
        self.assertEqual(participant_label(a), "G2 Esports")
        self.assertEqual(participant_label(b), "Team Heretics")

    def test_semifinal1_slot1_resolved_slot2_pending(self):
        # SF1: prev = [winner(1609943), winner(1609942)] -> slot1 HTCS (decided), slot2 undecided
        a, b = cod_ewc.resolve_sides(self.g, 1609946)
        self.assertEqual(participant_label(a), "Team Heretics")
        self.assertEqual(b["state"], "pending")
        self.assertEqual(b["feederGameId"], 1609943)
        self.assertEqual(b["outcome"], "winner")
        self.assertEqual(participant_label(b), "Winner of Team Falcons–Gentle Mates")

    def test_semifinal2_slot1_decided_slot2_pending(self):
        # SF2: prev = [winner(1609945), winner(1609944)] -> slot1 = 100 Thieves (QF3 winner,
        # decided), slot2 = winner of QF4 (undecided). Sides come from the feeder graph.
        a, b = cod_ewc.resolve_sides(self.g, 1609947)
        self.assertEqual(participant_label(a), "100 Thieves")
        self.assertEqual(b["state"], "pending")
        self.assertEqual(b["feederGameId"], 1609945)
        self.assertEqual(participant_label(b), "Winner of FaZe Clan–OpTic Gaming")

    def test_grand_final_both_pending(self):
        a, b = cod_ewc.resolve_sides(self.g, 1609948)
        self.assertEqual(a["state"], "pending")
        self.assertEqual(b["state"], "pending")
        self.assertEqual(participant_label(a), "Winner of Semifinal 2")
        self.assertEqual(participant_label(b), "Winner of Semifinal 1")

    def test_third_place_both_pending_loser(self):
        a, b = cod_ewc.resolve_sides(self.g, 1609949)
        self.assertEqual(a["outcome"], "loser")
        self.assertEqual(b["outcome"], "loser")
        self.assertEqual(participant_label(a), "Loser of Semifinal 2")
        self.assertEqual(participant_label(b), "Loser of Semifinal 1")

    def test_missing_feeder_node_label_is_structural_not_tbd(self):
        # Regression: a predecessor whose match node is absent from the graph must label the slot
        # honestly ('preceding match'), never the literal 'TBD' (no-TBD surface gate).
        g = {
            "nodes": {
                99: {"ps_id": 99, "node_name": "Grand final", "round_key": "grand final",
                     "opponents": [], "prev": [("winner", 9999), ("winner", 9998)],
                     "status": "upcoming"},
            },
            "by_round": {"grand final": []},
            "group_matches": [],
        }
        a, b = cod_ewc.resolve_sides(g, 99)
        self.assertEqual(a["state"], "pending")
        self.assertEqual(participant_label(a), "Winner of preceding match")
        self.assertNotIn("TBD", participant_label(a))
        self.assertNotIn("TBD", participant_label(b))

    def test_decided_loser_feeder_resolves_loser_not_winner(self):
        # Regression: once a semifinal finishes, the 3rd-place slot fed by type='loser' must get
        # the *other* opponent (the loser), never the winner (resolve_sides used to ignore the
        # predecessor outcome and always emit the feeder's winner).
        g = {
            "nodes": {
                1: {"ps_id": 1, "node_name": "Semifinal 1: Alpha vs Beta",
                    "round_key": "semifinal",
                    "opponents": [{"id": 10, "name": "Alpha"}, {"id": 11, "name": "Beta"}],
                    "winner_id": 10, "prev": [], "status": "finished"},
                2: {"ps_id": 2, "node_name": "Semifinal 2: Gamma vs Delta",
                    "round_key": "semifinal",
                    "opponents": [{"id": 20, "name": "Gamma"}, {"id": 21, "name": "Delta"}],
                    "winner_id": None, "prev": [], "status": "upcoming"},
                99: {"ps_id": 99, "node_name": "3rd place match", "round_key": "3rd place",
                     "opponents": [], "prev": [("loser", 1), ("loser", 2)],
                     "status": "upcoming"},
            },
            "by_round": {"semifinal": [], "3rd place": []},
            "group_matches": [],
        }
        a, b = cod_ewc.resolve_sides(g, 99)
        # Slot mapping mirrors the fixture: [prev[1], prev[0]] = [loser(SF2), loser(SF1)].
        self.assertEqual(participant_label(a), "Loser of Gamma–Delta")
        self.assertEqual(a["state"], "pending")
        self.assertEqual(participant_label(b), "Beta")  # loser of decided SF1, NOT Alpha
        self.assertEqual(b["state"], "named")
        self.assertEqual(b["clubId"], 11)

    def test_decided_loser_with_partial_feeder_opponents_stays_pending(self):
        # When the decided feeder lists only one opponent (as today's semifinal nodes do), the
        # loser's identity is genuinely unknown — stay structurally pending, never guess.
        g = {
            "nodes": {
                1: {"ps_id": 1, "node_name": "Semifinal 1: Alpha vs TBD",
                    "round_key": "semifinal",
                    "opponents": [{"id": 10, "name": "Alpha"}],
                    "winner_id": 10, "prev": [], "status": "finished"},
                99: {"ps_id": 99, "node_name": "3rd place match", "round_key": "3rd place",
                     "opponents": [], "prev": [("loser", 1), ("loser", 1)],
                     "status": "upcoming"},
            },
            "by_round": {"semifinal": [], "3rd place": []},
            "group_matches": [],
        }
        a, b = cod_ewc.resolve_sides(g, 99)
        self.assertEqual(a["state"], "pending")
        self.assertEqual(a["outcome"], "loser")
        self.assertNotEqual(participant_label(a), "Alpha")


class AssociateBpRowTests(unittest.TestCase):
    def setUp(self):
        t0 = cod_ewc._iso_to_ms("2026-08-08T12:00:00Z")
        self.row = {"game_id": "BP-99", "date": "2026-08-08T12:00:00Z", "state": "pre",
                    "status": "Upcoming", "event": "Esports World Cup 2026",
                    "round": "Quarterfinals",
                    "home": {"name": "Alpha", "score": None},
                    "away": {"name": "Beta", "score": None}}

        def node(ps_id, name, a_id, a_name, b_id, b_name):
            return {"ps_id": ps_id, "node_name": name, "round_key": "quarterfinal",
                    "opponents": [{"id": a_id, "name": a_name}, {"id": b_id, "name": b_name}],
                    "scheduled_ms": t0, "prev": [], "status": "upcoming"}

        self.duplicate = {
            "nodes": {
                1: node(1, "Quarterfinal 1: Alpha vs Beta", 10, "Alpha", 11, "Beta"),
                2: node(2, "Quarterfinal 2: Alpha vs Beta", 10, "Alpha", 11, "Beta"),
            },
            "by_round": {"quarterfinal": []},
            "group_matches": [],
        }
        self.duplicate["by_round"] = {"quarterfinal": list(self.duplicate["nodes"].values())}
        self.distinct = {
            "nodes": {
                1: node(1, "Quarterfinal 1: Alpha vs Beta", 10, "Alpha", 11, "Beta"),
                2: node(2, "Quarterfinal 2: Gamma vs Delta", 20, "Gamma", 21, "Delta"),
            },
            "by_round": {"quarterfinal": []},
            "group_matches": [],
        }
        self.distinct["by_round"] = {"quarterfinal": list(self.distinct["nodes"].values())}

    def test_tier1_ambiguous_name_match_returns_none(self):
        # Regression: two bracket nodes in the same round matching the same participant names
        # within the time tolerance must resolve to None (ambiguity), never the first hit.
        self.assertIsNone(cod_ewc.associate_bp_row(self.row, self.duplicate, set()))

    def test_tier1_single_exact_match_resolves(self):
        self.assertEqual(cod_ewc.associate_bp_row(self.row, self.distinct, set()), 1)


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.g = _graph()
        self.rows = _bp_rows()

    def _by_id(self, reconciled, game_id):
        return next(m for m in reconciled if m.get("game_id") == game_id)

    def test_no_raw_tbd_anywhere(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        for m in reconciled:
            for side in ("home", "away"):
                self.assertNotIn((m.get(side) or {}).get("name"), ("TBD", "TBA"),
                                 f"{m.get('game_id')} {side}")

    def test_finished_quarterfinal_resolves_clubs_and_scores(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356979")  # QF1 3-4
        self.assertEqual(m["detail_game_id"], "1609942")
        self.assertEqual((m["home"] or {}).get("name"), "G2 Esports")
        self.assertEqual((m["away"] or {}).get("name"), "Team Heretics")
        self.assertEqual(m["state"], "post")
        self.assertEqual((m["home"] or {}).get("score"), 3)
        self.assertEqual((m["away"] or {}).get("score"), 4)

    def test_finished_quarterfinal3_resolves_clubs_and_scores(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356980")  # QF3: 100 Thieves 4-0 Movistar KOI
        self.assertEqual(m["detail_game_id"], "1609944")
        self.assertEqual((m["home"] or {}).get("name"), "100 Thieves")
        self.assertEqual((m["away"] or {}).get("name"), "Movistar KOI")
        self.assertEqual((m["home"] or {}).get("score"), 4)
        self.assertEqual((m["away"] or {}).get("score"), 0)

    def test_live_quarterfinal_shows_real_clubs(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356981")
        self.assertEqual(m["detail_game_id"], "1609943")
        names = {(m["home"] or {}).get("name"), (m["away"] or {}).get("name")}
        self.assertEqual(names, {"Team Falcons", "Gentle Mates"})
        self.assertEqual(m["state"], "in")
        self.assertEqual(m["status"], "Live")
        # Scores come from PandaScore (fresher orientation), not the raw BP 1-0.
        self.assertIn((m["home"] or {}).get("score"), (0, 1))

    def test_upcoming_quarterfinal_resolves_both_clubs(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356982")
        self.assertEqual(m["detail_game_id"], "1609945")
        names = {(m["home"] or {}).get("name"), (m["away"] or {}).get("name")}
        self.assertEqual(names, {"FaZe Clan", "OpTic Gaming"})

    def test_semifinal_renders_dependency_label(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356983")
        self.assertEqual(m["detail_game_id"], "1609946")
        labels = {participant_label((m["home"] or {}).get("participant")),
                  participant_label((m["away"] or {}).get("participant"))}
        self.assertIn("Team Heretics", labels)
        self.assertIn("Winner of Team Falcons–Gentle Mates", labels)

    def test_semifinal2_renders_decided_club_and_dependency(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356984")
        self.assertEqual(m["detail_game_id"], "1609947")
        labels = {participant_label((m["home"] or {}).get("participant")),
                  participant_label((m["away"] or {}).get("participant"))}
        self.assertIn("100 Thieves", labels)
        self.assertIn("Winner of FaZe Clan–OpTic Gaming", labels)

    def test_grand_final_renders_dependencies(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356986")
        self.assertEqual(m["detail_game_id"], "1609948")
        labels = {participant_label((m["home"] or {}).get("participant")),
                  participant_label((m["away"] or {}).get("participant"))}
        self.assertEqual(labels, {"Winner of Semifinal 1", "Winner of Semifinal 2"})

    def test_third_place_renders_loser_dependencies(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356985")
        labels = {participant_label((m["home"] or {}).get("participant")),
                  participant_label((m["away"] or {}).get("participant"))}
        self.assertEqual(labels, {"Loser of Semifinal 1", "Loser of Semifinal 2"})

    def test_group_play_row_with_one_known_name_fills_other_side(self):
        reconciled = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        m = self._by_id(reconciled, "BP-356966")  # BP: TBD 3-0 Vancouver Surge
        names = {(m["home"] or {}).get("name"), (m["away"] or {}).get("name")}
        self.assertIn("Vancouver Surge", names)
        self.assertNotIn(None, names)
        self.assertNotIn("TBD", names)
        self.assertIn("Team Heretics", names)

    def test_non_ewc_rows_pass_through_unchanged(self):
        non_ewc = [
            {"game_id": "BP-1", "date": "2026-07-01T12:00:00Z", "state": "pre", "status": "Upcoming",
             "event": "CDL 2026", "round": "Week 4",
             "home": {"abbrev": "OpTic", "name": "OpTic Texas", "score": None},
             "away": {"abbrev": "Breach", "name": "Boston Breach", "score": None}},
        ]
        out = cod_ewc.reconcile_cod_matches(non_ewc, graph=self.g)
        self.assertEqual(out, non_ewc)

    def test_unresolvable_row_is_participant_unavailable_not_tbd(self):
        # A bracket row whose round has no nodes (e.g. a hypothetical extra round) must degrade
        # to Participant unavailable, never a bare TBD.
        weird = [
            {"game_id": "BP-9", "date": "2026-08-10T12:00:00Z", "state": "pre", "status": "Upcoming",
             "event": "Esports World Cup 2026", "round": "Qualification Round",
             "home": {"abbrev": "TBD", "name": "TBD", "score": None},
             "away": {"abbrev": "TBD", "name": "TBD", "score": None}},
        ]
        out = cod_ewc.reconcile_cod_matches(weird, graph=self.g)
        m = out[0]
        self.assertIsNone((m["home"] or {}).get("name"))
        self.assertEqual(participant_label((m["home"] or {}).get("participant")),
                         "Participant unavailable")

    def test_reconciliation_is_deterministic(self):
        first = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        second = cod_ewc.reconcile_cod_matches(self.rows, graph=self.g)
        self.assertEqual(first, second)


class NoGraphDegradationTests(unittest.TestCase):
    def test_missing_graph_never_emits_tbd(self):
        rows = _bp_rows()
        with mock.patch.object(cod_ewc, "get_ewc_cod_graph", return_value=None):
            out = cod_ewc.reconcile_cod_matches(rows, graph=None)
        for m in out:
            for side in ("home", "away"):
                self.assertNotIn((m.get(side) or {}).get("name"), ("TBD", "TBA"))


if __name__ == "__main__":
    unittest.main()
