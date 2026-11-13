import copy
import json
import os
import sqlite3
import unittest

import ingest_nba_player_movement as m
import team_codes

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "fixtures", "nba_player_movement_sample.json")


def sample():
    with open(SAMPLE) as handle:
        return json.load(handle)


def db(with_ids=True):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE player_source_ids(player_id INT, league TEXT, source TEXT, source_player_key TEXT)")
    if with_ids:
        for pid, key in ((29313, "201142"), (29368, "1631105"), (29364, "1628415")):
            con.execute("INSERT INTO player_source_ids VALUES(?,'nba','nba.com',?)", (pid, key))
    return con


class Direction(unittest.TestCase):
    def setUp(self):
        self.con = db()
        self.result = m.ingest(self.con, sample(), now="2026-11-13T00:00:00+00:00")

    def moves(self, slug):
        return self.con.execute(
            "SELECT from_team, to_team FROM nba_player_movement WHERE nba_player_slug=? "
            "AND transaction_type='Trade'", (slug,)).fetchall()

    def test_durant_goes_phoenix_to_houston(self):
        self.assertEqual(self.moves("kevin-durant"), [("PHX", "HOU")])

    def test_green_and_brooks_go_houston_to_phoenix(self):
        self.assertEqual(self.moves("jalen-green"), [("HOU", "PHX")])
        self.assertEqual(self.moves("dillon-brooks"), [("HOU", "PHX")])

    def test_the_seven_team_deal_is_one_group(self):
        groups = {r[0] for r in self.con.execute(
            "SELECT group_sort FROM nba_player_movement WHERE nba_player_slug IN "
            "('kevin-durant','jalen-green','dillon-brooks','clint-capela')")}
        self.assertEqual(groups, {"Trade 2025005"})
        teams = {t for r in self.con.execute(
            "SELECT from_team, to_team FROM nba_player_movement WHERE group_sort='Trade 2025005'") for t in r}
        self.assertEqual(teams, {"HOU", "PHX", "ATL", "MIN", "BKN"})

    def test_a_different_trade_is_a_different_group(self):
        self.assertEqual(self.con.execute(
            "SELECT COUNT(DISTINCT group_sort) FROM nba_player_movement WHERE transaction_type='Trade'"
        ).fetchone()[0], 2)

    def test_picks_are_not_players(self):
        kinds = self.con.execute("SELECT DISTINCT asset_kind FROM nba_player_movement "
                                 "WHERE description LIKE '%draft consideration%'").fetchall()
        self.assertEqual(kinds, [("other",)])

    def test_player_ids_join_to_our_players(self):
        self.assertEqual(self.con.execute(
            "SELECT player_id FROM nba_player_movement WHERE nba_player_slug='kevin-durant'").fetchone()[0], 29313)

    def test_clean_file_is_complete(self):
        self.assertEqual(self.result["status"], "complete")
        self.assertEqual(self.result["direction"]["conflict"] + self.result["direction"]["unparsed"], 0)

    def test_unmatched_ids_are_reported_not_hidden(self):
        self.assertRegex(self.result["player_ids_matched"], r"^\d+ of \d+$")
        self.assertNotEqual(self.result["player_ids_matched"].split(" of ")[0],
                            self.result["player_ids_matched"].split(" of ")[1])


class FailLoud(unittest.TestCase):
    def test_a_slug_that_disagrees_with_the_description_is_a_conflict(self):
        payload = sample()
        for row in payload["NBA_Player_Movement"]["rows"]:
            if row["PLAYER_SLUG"] == "kevin-durant":
                row["TEAM_SLUG"] = "suns"           # description says Houston received him
        con = db()
        result = m.ingest(con, payload)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["direction"]["conflict"], 1)
        self.assertEqual(con.execute(
            "SELECT direction_check FROM nba_player_movement WHERE nba_player_slug='kevin-durant'"
        ).fetchone()[0], "conflict")

    def test_an_unparseable_trade_is_stored_as_unparsed(self):
        payload = sample()
        for row in payload["NBA_Player_Movement"]["rows"]:
            if row["PLAYER_SLUG"] == "jalen-green":
                row["TRANSACTION_DESCRIPTION"] = "Jalen Green moved."
        con = db()
        result = m.ingest(con, payload)
        self.assertEqual(result["status"], "incomplete")
        row = con.execute("SELECT direction_check, to_team, from_team FROM nba_player_movement "
                          "WHERE nba_player_slug='jalen-green'").fetchone()
        self.assertEqual(row, ("unparsed", None, None))

    def test_an_unknown_team_name_is_unparsed_not_guessed(self):
        payload = sample()
        for row in payload["NBA_Player_Movement"]["rows"]:
            if row["PLAYER_SLUG"] == "kevin-durant":
                row["TRANSACTION_DESCRIPTION"] = "Houston Rockets received forward Kevin Durant from Seattle SuperSonics."
        self.assertEqual(m.ingest(db(), payload)["direction"]["unparsed"], 1)

    def test_a_missing_column_raises(self):
        payload = sample()
        del payload["NBA_Player_Movement"]["rows"][0]["GroupSort"]
        with self.assertRaises(m.MovementFeedError):
            m.ingest(db(), payload)

    def test_an_empty_feed_raises(self):
        with self.assertRaises(m.MovementFeedError):
            m.ingest(db(), {"NBA_Player_Movement": {"rows": []}})

    def test_an_unknown_transaction_type_raises(self):
        payload = sample()
        payload["NBA_Player_Movement"]["rows"][0]["Transaction_Type"] = "Mystery"
        with self.assertRaises(m.MovementFeedError):
            m.ingest(db(), payload)

    def test_a_shrinking_feed_is_refused_and_writes_nothing(self):
        con = db()
        m.ingest(con, sample())
        small = sample()
        small["NBA_Player_Movement"]["rows"] = small["NBA_Player_Movement"]["rows"][:5]
        before = con.execute("SELECT COUNT(*) FROM nba_player_movement").fetchone()[0]
        with self.assertRaises(m.MovementFeedError):
            m.ingest(con, small)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM nba_player_movement").fetchone()[0], before)

    def test_a_feed_that_goes_backwards_is_refused(self):
        con = db()
        m.ingest(con, sample())
        older = sample()
        for row in older["NBA_Player_Movement"]["rows"]:
            row["TRANSACTION_DATE"] = "2020-01-01T00:00:00"
        with self.assertRaises(m.MovementFeedError):
            m.ingest(con, older)


class Idempotence(unittest.TestCase):
    def test_same_feed_twice_is_unchanged(self):
        con = db()
        first = m.ingest(con, sample())
        second = m.ingest(con, sample())
        self.assertEqual(second["status"], "unchanged")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM nba_player_movement").fetchone()[0], first["rows"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM nba_player_movement_snapshots").fetchone()[0], 1)

    def test_a_new_row_is_added_and_old_rows_are_kept(self):
        con = db()
        m.ingest(con, sample())
        grown = sample()
        extra = copy.deepcopy(grown["NBA_Player_Movement"]["rows"][-1])
        extra["TRANSACTION_DATE"] = "2026-11-12T00:00:00"
        extra["TRANSACTION_DESCRIPTION"] = "A new waive."
        grown["NBA_Player_Movement"]["rows"].append(extra)
        result = m.ingest(con, grown)
        self.assertEqual(result["inserted"], 1)

    def test_a_changed_row_is_a_new_version_not_an_overwrite(self):
        con = db()
        m.ingest(con, sample())
        edited = sample()
        edited["NBA_Player_Movement"]["rows"][0]["TRANSACTION_DESCRIPTION"] += " (corrected)"
        extra = copy.deepcopy(edited["NBA_Player_Movement"]["rows"][-1])
        extra["TRANSACTION_DATE"] = "2026-11-12T00:00:00"
        edited["NBA_Player_Movement"]["rows"].append(extra)
        m.ingest(con, edited)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM nba_player_movement").fetchone()[0], 13 + 2)


class Vocabulary(unittest.TestCase):
    def test_every_code_is_a_repo_canonical_nba_code(self):
        for code in list(m.TEAM_NAME_TO_CODE.values()) + list(m.SLUG_TO_CODE.values()):
            self.assertIn(code, team_codes.CANONICAL["nba"], code)

    def test_thirty_teams_in_each_map(self):
        self.assertEqual(len(set(m.TEAM_NAME_TO_CODE.values())), 30)
        self.assertEqual(len(set(m.SLUG_TO_CODE.values())), 30)
        self.assertEqual(set(m.TEAM_NAME_TO_CODE.values()), set(m.SLUG_TO_CODE.values()))


if __name__ == "__main__":
    unittest.main()
