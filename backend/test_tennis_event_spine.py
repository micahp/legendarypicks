import sqlite3
import unittest

import tennis_event_spine as spine


def game(home, away):
    side = lambda pid, name: {"athlete_id": pid, "name": name}
    return {"home": side(*home), "away": side(*away)}


class EventSpine(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.executescript("""
            CREATE TABLE players(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, team TEXT,
              league TEXT NOT NULL, espn_id TEXT, active INTEGER DEFAULT 1, updated_at TEXT,
              UNIQUE(espn_id, league));
            CREATE TABLE player_source_ids(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
              league TEXT NOT NULL, source_player_key TEXT NOT NULL, player_id INTEGER NOT NULL,
              first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, UNIQUE(source, league, source_player_key));
            CREATE TABLE tennis_atp_players(player_id INTEGER, name_first TEXT, name_last TEXT);
            CREATE TABLE tennis_wta_players(player_id INTEGER, name_first TEXT, name_last TEXT);
            INSERT INTO tennis_atp_players VALUES (1,'Jacob','Fearnley'),(2,'Vit','Kopriva'),
              (3,'Alex','Smith'),(4,'Alex','Smith');
        """)

    def sync(self, *games):
        out = spine.sync_event_players("atp", list(games), self.con)
        self.con.commit()
        return out

    def test_a_new_athlete_is_inserted_and_bound_to_sackmann(self):
        out = self.sync(game(("10", "Jacob Fearnley"), ("11", "Vit Kopriva")))
        self.assertEqual((out["inserted"], out["bound"], out["unresolved"]), (2, 2, 0))
        row = self.con.execute("SELECT active FROM players WHERE espn_id='10'").fetchone()
        self.assertEqual(row[0], 0)
        self.assertEqual(self.con.execute(
            "SELECT source_player_key FROM player_source_ids WHERE player_id="
            "(SELECT id FROM players WHERE espn_id='10')").fetchone()[0], "1")

    def test_tbd_slots_never_create_a_player(self):
        out = self.sync(game(("-1", "TBD"), ("", "Jacob Fearnley")))
        self.assertEqual(out["athletes"], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0)

    def test_a_same_name_row_without_an_espn_id_is_adopted_not_duplicated(self):
        self.con.execute("INSERT INTO players(name,league) VALUES('Jacob Fearnley','atp')")
        out = self.sync(game(("10", "Jacob Fearnley"), ("11", "Vit Kopriva")))
        self.assertEqual((out["adopted"], out["inserted"]), (1, 1))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)

    def test_a_same_name_row_holding_another_id_is_not_stolen(self):
        self.con.execute("INSERT INTO players(name,league,espn_id) VALUES('Jacob Fearnley','atp','99')")
        out = self.sync(game(("10", "Jacob Fearnley"), ("11", "Vit Kopriva")))
        self.assertEqual(out["inserted"], 1)
        self.assertEqual(out["unresolved"], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)

    def test_no_sackmann_match_and_ambiguous_match_are_recorded_not_guessed(self):
        out = self.sync(game(("20", "Nobody Known"), ("21", "Alex Smith")))
        self.assertEqual((out["inserted"], out["bound"], out["unresolved"]), (2, 0, 2))
        reasons = dict(self.con.execute("SELECT espn_id,reason FROM tennis_spine_unresolved").fetchall())
        self.assertEqual(reasons["20"], "no Sackmann match")
        self.assertEqual(reasons["21"], "ambiguous Sackmann name")

    def test_a_second_run_changes_nothing_and_clears_a_resolved_athlete(self):
        self.sync(game(("20", "Jacob Fearnley"), ("21", "Nobody Known")))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM tennis_spine_unresolved").fetchone()[0], 1)
        out = self.sync(game(("20", "Jacob Fearnley"), ("21", "Nobody Known")))
        self.assertEqual((out["inserted"], out["bound"]), (0, 0))
        self.con.execute("INSERT INTO tennis_atp_players VALUES (9,'Nobody','Known')")
        out = self.sync(game(("20", "Jacob Fearnley"), ("21", "Nobody Known")))
        self.assertEqual(out["bound"], 1)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM tennis_spine_unresolved").fetchone()[0], 0)

    def test_a_family_name_first_name_matches_the_swapped_sackmann_name(self):
        self.con.execute("INSERT INTO tennis_atp_players VALUES (7,'Xinyu','Wang')")
        out = self.sync(game(("30", "Wang Xinyu"), ("31", "Nobody Known")))
        self.assertEqual((out["bound"], out["unresolved"]), (1, 1))

    def test_an_existing_player_without_a_binding_gets_one(self):
        self.con.execute("INSERT INTO players(name,league,espn_id) VALUES('Vit Kopriva','atp','11')")
        out = self.sync(game(("11", "Vit Kopriva"), ("10", "Jacob Fearnley")))
        self.assertEqual((out["inserted"], out["bound"]), (1, 2))


if __name__ == "__main__":
    unittest.main()
