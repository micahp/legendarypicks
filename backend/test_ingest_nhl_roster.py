#!/usr/bin/env python3
"""ingest_nhl_roster: the population gates and the identity planner, offline.

The publisher's job is to refuse everything that is not a complete, unambiguous
population before a single row moves. These tests pin that refusal and the
atomic publish, without touching the network: every fetch test replaces
``_get`` with a synthetic document, so a live schema change on nhle.com cannot
silently turn a test green.
"""
import copy
import os
import sqlite3
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_nhl_roster as mod
import roster_membership
import team_codes

NHL_CODES = sorted(team_codes.CANONICAL["nhl"])
def _db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE players(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          league TEXT NOT NULL, team TEXT, position TEXT, active INTEGER,
          updated_at TEXT, espn_id TEXT, nhl_id TEXT);
        CREATE TABLE player_source_ids(
          id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
          league TEXT NOT NULL, source_player_key TEXT NOT NULL,
          player_id INTEGER NOT NULL, first_seen TEXT, last_seen TEXT,
          UNIQUE(source, league, source_player_key));
    """)
    roster_membership.create_roster_schema(con)
    return con


def _seed(con, rows):
    """rows of (name, team, position, nhl_id, active)."""
    for name, team, position, nhl_id, active in rows:
        con.execute(
            "INSERT INTO players(name,league,team,position,nhl_id,active,updated_at)"
            " VALUES(?,'nhl',?,?,?,?, '2026-08-04T00:00:00+00:00')",
            (name, team, position, nhl_id, active))
    con.commit()


def _member(pid, name, position, team, jersey=None):
    return {"player_id": pid, "name": name, "position": position,
            "jersey": jersey, "team": team}


def _full_rosters():
    """32 non-empty teams; the interesting members live on CHI and TOR.
    Team keys use the canonical uppercase vocabulary, exactly as
    fetch_population builds them."""
    interesting = {
        "CHI": [_member("100", "Existing Exact", "C", "CHI"),
                _member("101", "Unbound Teammate", "LW", "CHI"),
                _member("999", "Brand New Guy", "D", "CHI")],
        "TOR": [_member("102", "Distinct Same Name", "RW", "TOR")],
    }
    rosters = {}
    filler = 1000
    for code in NHL_CODES:
        if code in interesting:
            rosters[code] = interesting[code]
        else:
            rosters[code] = [_member(str(filler), "Filler {}".format(filler), "C", code)]
            filler += 1
    return rosters


SEED_ROWS = [
    ("Existing Exact", "CHI", "C", "100", 1),
    ("Unbound Teammate", "CHI", "LW", None, 1),
    ("Distinct Same Name", "TOR", "RW", "102", 1),
    ("Traded Away", "VAN", "G", "555", 1),
]


def _plan_db(players=None, crosswalk=()):
    con = _db()
    _seed(con, players if players is not None else SEED_ROWS)
    for source_key, player_id in crosswalk:
        con.execute(
            "INSERT INTO player_source_ids(source,league,source_player_key,"
            "player_id,first_seen,last_seen) VALUES('nhle.com','nhl',?,?,'d','d')",
            (source_key, player_id))
    con.commit()
    return con


def _items(plan):
    return {item["source_player_key"]: item for item in plan["planned"]}


class PositionNormalization(unittest.TestCase):
    def test_nhl_shorthands_map_to_the_stored_vocabulary(self):
        self.assertEqual(mod._position("L"), "LW")
        self.assertEqual(mod._position("R"), "RW")
        self.assertEqual(mod._position("d"), "D")
        self.assertEqual(mod._position(" G "), "G")
        for empty in (None, "", "  "):
            self.assertIsNone(mod._position(empty))


def _directory_document(codes=None):
    return {"standings": [{"teamAbbrev": {"default": code}}
                          for code in (codes or NHL_CODES)]}


def _roster_document(forwards=(), defensemen=(), goalies=()):
    return {"forwards": list(forwards), "defensemen": list(defensemen),
            "goalies": list(goalies)}


def _nhl_player(pid, first, last, position, number=None):
    row = {"id": pid,
           "firstName": {"default": first},
           "lastName": {"default": last},
           "positionCode": position}
    if number is not None:
        row["sweaterNumber"] = number
    return row


class FetchValidation(unittest.TestCase):
    """fetch_population must refuse an incomplete or ambiguous source, loudly."""

    def _patch(self, documents):
        """documents: url fragment -> document, served by a fake _get."""
        def fake_get(url):
            for fragment, document in documents.items():
                if fragment in url:
                    return document
            raise AssertionError("unexpected url " + url)
        return mock.patch.object(mod, "_get", side_effect=fake_get)

    def _happy_documents(self):
        documents = {
            "standings/now": _directory_document(),
            "club-schedule-season": {"currentSeason": 20262027},
        }
        for index, code in enumerate(NHL_CODES):
            documents["roster/" + code + "/"] = _roster_document(
                forwards=[_nhl_player(1000 + 2 * index, "Pat", "Player", "L", 88)],
                goalies=[_nhl_player(1001 + 2 * index, "Goal", "Keeper", "G", 31)],
            )
        return documents

    def test_a_short_directory_is_refused(self):
        with self._patch({"standings/now": _directory_document(NHL_CODES[:-1])}):
            with self.assertRaises(mod.NHLRosterError):
                mod.fetch_population()

    def test_an_unknown_team_code_is_refused(self):
        codes = NHL_CODES[:-1] + ["XX"]
        with self._patch({"standings/now": _directory_document(codes)}):
            with self.assertRaises(mod.NHLRosterError):
                mod.fetch_population()

    def test_an_unparseable_season_is_refused(self):
        documents = {
            "standings/now": _directory_document(),
            "club-schedule-season": {"currentSeason": "not-a-number"},
        }
        with self._patch(documents):
            with self.assertRaises(mod.NHLRosterError):
                mod.fetch_population()

    def test_a_complete_population_is_returned_normalized(self):
        with self._patch(self._happy_documents()):
            season, rosters = mod.fetch_population()
        self.assertEqual(season, 20262027)
        self.assertEqual(len(rosters), 32)
        self.assertEqual(sorted(rosters), NHL_CODES)
        members = rosters["ANA"]
        self.assertEqual([m["position"] for m in members], ["LW", "G"])
        self.assertEqual(members[0]["jersey"], "88")

    def test_an_incomplete_member_is_refused(self):
        documents = self._happy_documents()
        documents["roster/ANA/"] = _roster_document(
            forwards=[{"id": 1000, "firstName": {"default": "No"},
                       "lastName": {"default": "Position"}}])
        with self._patch(documents):
            with self.assertRaises(mod.NHLRosterError):
                mod.fetch_population()

    def test_the_same_nhl_id_on_two_teams_is_refused(self):
        documents = self._happy_documents()
        documents["roster/TOR/"] = _roster_document(
            forwards=[_nhl_player(1000, "Pat", "Player", "R")])  # ANA's id
        with self._patch(documents):
            with self.assertRaises(mod.NHLRosterError):
                mod.fetch_population()

    def test_an_empty_roster_is_refused(self):
        documents = self._happy_documents()
        documents["roster/BOS/"] = _roster_document()
        with self._patch(documents):
            with self.assertRaises(mod.NHLRosterError):
                mod.fetch_population()


class ThePlanner(unittest.TestCase):
    def test_a_bound_nhl_id_resolves_exactly(self):
        plan = mod.plan_population(_plan_db(), _full_rosters())
        item = _items(plan)["100"]
        self.assertEqual(item["write_action"], "update")
        self.assertEqual(item["evidence"], "exact_id")
        self.assertEqual(item["canonical_player_id"], 1)

    def test_a_same_name_on_the_current_team_backfills(self):
        plan = mod.plan_population(_plan_db(), _full_rosters())
        item = _items(plan)["101"]
        self.assertEqual(item["write_action"], "update")
        self.assertEqual(item["evidence"], "matched_team_position")
        self.assertEqual(item["canonical_player_id"], 2)

    def test_a_new_identity_inserts(self):
        plan = mod.plan_population(_plan_db(), _full_rosters())
        item = _items(plan)["999"]
        self.assertEqual(item["write_action"], "insert")
        self.assertIsNone(item["canonical_player_id"])

    def test_a_bound_same_name_with_a_new_source_id_is_a_distinct_person(self):
        """'Distinct Same Name' is already bound to nhl_id 102. A source member
        of the same name carrying a NEW id is a different human: insert, never
        re-point the bound row."""
        plan = mod.plan_population(_plan_db(), {
            "tor": [_member("777", "Distinct Same Name", "RW", "tor")]})
        item = _items(plan)["777"]
        self.assertEqual(item["write_action"], "insert")

    def test_an_ambiguous_name_fails_closed(self):
        plan = mod.plan_population(
            _plan_db(players=[("Twin Name", "CHI", "C", None, 1),
                              ("Twin Name", "CHI", "C", None, 1)]),
            {"chi": [_member("555", "Twin Name", "C", "chi")]})
        self.assertEqual(plan["failures"][0]["reason"], "ambiguous_name")
        self.assertNotIn("555", _items(plan))

    def test_a_name_only_match_without_evidence_fails_closed(self):
        plan = mod.plan_population(
            _plan_db(players=[("Mystery Man", "VAN", "G", None, 1)]),
            {"chi": [_member("555", "Mystery Man", "C", "chi")]})
        self.assertEqual(plan["failures"][0]["reason"], "unverified_name")

    def test_a_crosswalk_that_points_at_a_different_owner_fails_closed(self):
        """source 100 is durably recorded as player 2, but the spine says
        nhl_id 100 belongs to player 1. Republishing would silently move the
        crosswalk, so the plan refuses."""
        plan = mod.plan_population(_plan_db(crosswalk=[("100", 2)]), _full_rosters())
        self.assertIn("source_crosswalk_conflict",
                      {row["reason"] for row in plan["failures"]})

    def test_a_stranded_crosswalk_fails_closed(self):
        """source 999 is durably recorded as player 9, but the spine has no row
        answering to that member any more, so the crosswalk owns a ghost."""
        plan = mod.plan_population(
            _plan_db(players=[("Unrelated", "VAN", "G", "1", 1)],
                     crosswalk=[("999", 9)]),
            {"chi": [_member("999", "Brand New Guy", "D", "chi")]})
        self.assertIn("stranded_source_crosswalk",
                      {row["reason"] for row in plan["failures"]})

    def test_a_duplicated_spine_nhl_id_fails_closed(self):
        plan = mod.plan_population(
            _plan_db(players=[("Twin One", "CHI", "C", "100", 1),
                              ("Twin Two", "TOR", "C", "100", 1)]),
            {"chi": [_member("100", "Twin One", "C", "chi")]})
        self.assertEqual(plan["failures"][0]["reason"], "duplicate_spine_nhl_id")


class ThePublisher(unittest.TestCase):
    @staticmethod
    def _nhl_rows(con):
        return [(row["name"], row["nhl_id"], row["active"]) for row in con.execute(
            "SELECT name,nhl_id,active FROM players WHERE league='nhl' "
            "ORDER BY id")]

    @staticmethod
    def _crosswalks(con):
        return [(row["source_player_key"], row["player_id"]) for row in con.execute(
            "SELECT source_player_key,player_id FROM player_source_ids "
            "WHERE source='nhle.com' ORDER BY source_player_key")]

    @staticmethod
    def _snapshot(con):
        return con.execute(
            "SELECT * FROM roster_snapshots WHERE status='published'"
        ).fetchone()

    def _publish(self, rosters=None, apply=True, players=None, crosswalk=(),
                 snapshot_raiser=None):
        con = _plan_db(players=players, crosswalk=crosswalk)
        if snapshot_raiser is not None:
            patcher = mock.patch.object(mod, "publish_roster_snapshot",
                                        side_effect=snapshot_raiser)
            patcher.start()
            self.addCleanup(patcher.stop)
        plan = mod.publish_population(
            con, source_season=20262027,
            rosters=copy.deepcopy(rosters or _full_rosters()),
            captured_at="2026-09-22T20:00:00+00:00", apply=apply)
        return con, plan

    def test_a_dry_run_touches_nothing(self):
        con, plan = self._publish(apply=False)
        self.assertEqual(plan["status"], "ready")
        self.assertIsNone(self._snapshot(con))
        self.assertEqual(self._nhl_rows(con),
                         [("Existing Exact", "100", 1), ("Unbound Teammate", None, 1),
                          ("Distinct Same Name", "102", 1), ("Traded Away", "555", 1)])
        self.assertEqual(self._crosswalks(con), [])

    def test_failures_publish_nothing(self):
        rosters = _full_rosters()
        rosters["CHI"] = [_member("100", "Existing Exact", "C", "CHI"),
                          _member("555", "Mystery Man", "C", "CHI")]
        con, plan = self._publish(
            rosters=rosters, apply=True,
            players=[("Existing Exact", "CHI", "C", "100", 1),
                     ("Mystery Man", "VAN", "G", None, 1)])
        self.assertEqual(plan["status"], "identity_incomplete")
        self.assertIsNone(self._snapshot(con))
        self.assertEqual(
            sorted(self._nhl_rows(con)),
            sorted([("Existing Exact", "100", 1), ("Mystery Man", None, 1)]))

    def test_apply_publishes_one_snapshot_and_the_whole_population(self):
        con, plan = self._publish()
        self.assertEqual(plan["status"], "published")
        snapshot = self._snapshot(con)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["player_count"], 34)  # 4 interesting + 30 filler
        self.assertEqual(snapshot["team_count"], 32)
        self.assertEqual(len(self._crosswalks(con)), 34)
        rows = {name: (nhl_id, active) for name, nhl_id, active in self._nhl_rows(con)}
        # inserts
        self.assertEqual(rows["Brand New Guy"], ("999", 1))
        # backfilled by name + team + position evidence
        self.assertEqual(rows["Unbound Teammate"], ("101", 1))
        # exact id keeps its binding and stays active
        self.assertEqual(rows["Existing Exact"], ("100", 1))
        # the distinct same-name person is preserved and re-activated
        self.assertEqual(rows["Distinct Same Name"], ("102", 1))
        # everyone NOT in the source population is deactivated, not deleted
        self.assertEqual(rows["Traded Away"], ("555", 0))
        memberships = con.execute(
            "SELECT COUNT(*) FROM roster_memberships").fetchone()[0]
        self.assertEqual(memberships, 34)

    def test_a_mid_publish_failure_rolls_everything_back(self):
        con = _plan_db()
        patcher = mock.patch.object(
            mod, "publish_roster_snapshot",
            side_effect=roster_membership.RosterContractError("boom"))
        patcher.start()
        self.addCleanup(patcher.stop)
        with self.assertRaises(roster_membership.RosterContractError):
            mod.publish_population(
                con, source_season=20262027, rosters=_full_rosters(),
                captured_at="2026-09-22T20:00:00+00:00", apply=True)
        self.assertIsNone(self._snapshot(con))
        self.assertEqual(self._nhl_rows(con),
                         [("Existing Exact", "100", 1), ("Unbound Teammate", None, 1),
                          ("Distinct Same Name", "102", 1), ("Traded Away", "555", 1)])
        self.assertEqual(self._crosswalks(con), [])


class TheCommandLineContract(unittest.TestCase):
    """The publisher is dry-run by default and mutates only with --apply."""

    def test_apply_is_forwarded_explicitly(self):
        with mock.patch.object(mod, "refresh") as refresh:
            refresh.return_value = {"failures": [], "planned": []}
            code = mod.main(["--db", ":memory:", "--apply"])
        self.assertEqual(code, 0)
        refresh.assert_called_once()
        self.assertTrue(refresh.call_args.kwargs["apply"])

    def test_a_plain_dry_run_needs_no_flag(self):
        with mock.patch.object(mod, "refresh") as refresh:
            refresh.return_value = {"failures": [], "planned": []}
            code = mod.main(["--db", ":memory:"])
        self.assertEqual(code, 0)
        refresh.assert_called_once()
        self.assertFalse(refresh.call_args.kwargs["apply"])


if __name__ == "__main__":
    unittest.main()
