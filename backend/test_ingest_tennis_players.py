import collections
import os
import sqlite3
import tempfile
import unittest

import ingest_tennis_players as tennis


def atp_page(rows, later_page=False):
    links = '<a href="?page=2">2</a>' if later_page else ""
    body = ["<html><body><table class=\"result\"><tbody>"]
    for rank, name, slug in rows:
        body.append(
            "<tr><td class=\"rank first\">{}. </td>"
            "<td class=\"t-name\"><a href=\"/player/{}/\">{}</a></td></tr>".format(
                rank, slug, name
            )
        )
    body.append("</tbody></table>" + links + "</body></html>")
    return "".join(body)


def wta_page(players):
    return [
        {"player": {"id": player_id, "fullName": name}}
        for player_id, name in players
    ]


class TennisSpineTest(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.addCleanup(lambda: os.unlink(self.db_path) if os.path.exists(self.db_path) else None)
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE players(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    team TEXT,
                    league TEXT NOT NULL,
                    espn_id TEXT,
                    mlbam_id INTEGER,
                    nfl_gsis_id TEXT,
                    nhl_id INTEGER,
                    nba_id INTEGER,
                    active INTEGER DEFAULT 1,
                    updated_at TEXT,
                    UNIQUE(espn_id, league)
                );
                CREATE TABLE unresolved_players(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    raw_name TEXT NOT NULL,
                    league TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    source_player_key TEXT,
                    reason TEXT
                );
                CREATE TABLE player_source_ids(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    league TEXT NOT NULL,
                    source_player_key TEXT NOT NULL,
                    player_id INTEGER NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    UNIQUE(source,league,source_player_key)
                );
                """
            )
            connection.execute(
                "INSERT INTO players(name,team,league,espn_id,active,updated_at) "
                "VALUES('Carlos Alcaraz',NULL,'atp','espn-a',1,'old')"
            )
            connection.execute(
                "INSERT INTO players(name,team,league,espn_id,active,updated_at) "
                "VALUES('Coco Gauff',NULL,'wta','espn-c',1,'old')"
            )
            connection.executemany(
                "INSERT INTO unresolved_players(source,raw_name,league,count,source_player_key,reason) "
                "VALUES(?,?,?,?,?,?)",
                [
                    ("underdog", "Carlos Alcaraz", "atp", 2, "ud-a", "source_id_not_in_spine"),
                    ("underdog", "Unlisted ATP Name", "atp", 1, "ud-miss", "source_id_not_in_spine"),
                    ("bovada", "Jannik Sinner", "atp", 3, None, None),
                    ("bovada", "Bovada Only Name", "atp", 1, None, None),
                    ("underdog", "Coco Gauff", "wta", 1, "ud-w", "source_id_not_in_spine"),
                    ("bovada", "Iga Swiatek", "wta", 1, None, None),
                    ("bovada", "Maria Camila Osorio", "wta", 1, None, None),
                ],
            )

    def sources(self):
        atp_html = atp_page([
            (1, "Alcaraz Carlos", "alcaraz-5ab70"),
            (2, "Sinner Jannik", "sinner-8b8e8"),
        ])
        return (
            lambda url: (200, atp_html),
            lambda url: (200, wta_page([
                (328560, "Coco Gauff"),
                (323190, "Iga Świątek"),
                (325898, "Camila Osorio"),
            ])),
        )

    def test_tennisexplorer_uses_url_slug_and_reorders_compound_surname(self):
        self.assertEqual(
            ("Jannik Sinner", "sinner-8b8e8"),
            tennis.tennisexplorer_name("Sinner Jannik", "/player/sinner-8b8e8/"),
        )
        self.assertEqual(
            ("Botic Van de Zandschulp", "van-de-zandschulp-31ee8"),
            tennis.tennisexplorer_name(
                "Van de Zandschulp Botic", "/player/van-de-zandschulp-31ee8/"
            ),
        )

    def test_tennisexplorer_page_parser_extracts_ranked_rows_and_page_links(self):
        parsed = tennis.parse_tennisexplorer_page(
            atp_page([(1, "Sinner Jannik", "sinner-8b8e8")], later_page=True), 1
        )
        self.assertTrue(parsed["has_later_page"])
        self.assertEqual(
            [{"publisher_id": "sinner-8b8e8", "name": "Jannik Sinner",
              "active": True, "rank": 1}],
            parsed["players"],
        )

    def test_empty_publisher_source_fails_loudly(self):
        with self.assertRaisesRegex(tennis.TennisSpineError, "published 0 players"):
            tennis.fetch_atp_population(
                year=2026,
                fetch_page=lambda _url: (200, "<html><body>No ranking rows</body></html>"),
                request_counts=collections.Counter(),
                sleeper=lambda _seconds: None,
            )
        with self.assertRaisesRegex(tennis.TennisSpineError, "published 0 players"):
            tennis.fetch_wta_population(
                fetch_json=lambda _url: (200, []),
                request_counts=collections.Counter(),
                sleeper=lambda _seconds: None,
            )

    def test_dry_run_measures_both_books_and_does_not_change_schema_or_rows(self):
        fetch_atp, fetch_wta = self.sources()
        counts = collections.Counter()
        result = tennis.refresh(
            self.db_path,
            fetch_atp_page=fetch_atp,
            fetch_wta_json=fetch_wta,
            request_counts=counts,
            dry_run=True,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(1, result["atp"]["underdog_covered"])
        self.assertEqual(1, result["atp"]["bovada_covered"])
        self.assertEqual(1, result["atp"]["underdog_key_unmatched"])
        self.assertEqual(1, result["wta"]["underdog_covered"])
        self.assertEqual(2, result["wta"]["bovada_covered"])
        self.assertEqual(1, result["wta"]["verified_aliases"])
        self.assertFalse(result["schema_written"])
        self.assertEqual(1, counts[tennis.ATP_HOST])
        self.assertEqual(1, counts[tennis.WTA_HOST])
        with sqlite3.connect(self.db_path) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(players)")}
            self.assertNotIn("publisher", columns)
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM players").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM player_source_ids").fetchone()[0])

    def test_apply_stores_publisher_ids_preserves_espn_ids_and_binds_underdog_keys(self):
        fetch_atp, fetch_wta = self.sources()
        backup = self.db_path + ".backup"
        self.addCleanup(lambda: os.unlink(backup) if os.path.exists(backup) else None)
        result = tennis.refresh(
            self.db_path,
            fetch_atp_page=fetch_atp,
            fetch_wta_json=fetch_wta,
            request_counts=collections.Counter(),
            dry_run=False,
            backup_path=backup,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual("ok", result["backup_quick_check"])
        self.assertTrue(os.path.isfile(backup))
        self.assertEqual(2, result["atp"]["stored_current"])
        self.assertEqual(3, result["wta"]["stored_current"])
        self.assertEqual(1, result["atp"]["underdog_new_bindings"])
        self.assertEqual(1, result["wta"]["underdog_new_bindings"])
        self.assertEqual(1, result["wta"]["verified_aliases_stored"])
        self.assertEqual(1, result["wta"]["verified_aliases_inserted"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(
                ("espn-a", "tennisexplorer.com", "alcaraz-5ab70"),
                connection.execute(
                    "SELECT espn_id,publisher,publisher_id FROM players WHERE name='Carlos Alcaraz'"
                ).fetchone(),
            )
            self.assertEqual(
                ("espn-c", "wtatennis.com", "328560"),
                connection.execute(
                    "SELECT espn_id,publisher,publisher_id FROM players WHERE name='Coco Gauff'"
                ).fetchone(),
            )
            self.assertEqual(
                ("Camila Osorio", "wtatennis.com", "325898"),
                connection.execute(
                    "SELECT name,publisher,publisher_id FROM players "
                    "WHERE league='wta' AND publisher_id='325898'"
                ).fetchone(),
            )
            self.assertEqual(
                ("maria camila osorio",),
                connection.execute(
                    "SELECT alias_norm FROM name_alias WHERE player_id=("
                    "SELECT id FROM players WHERE publisher='wtatennis.com' "
                    "AND publisher_id='325898')"
                ).fetchone(),
            )
            self.assertEqual(
                ("Jannik Sinner", "tennisexplorer.com", "sinner-8b8e8", None),
                connection.execute(
                    "SELECT name,publisher,publisher_id,espn_id FROM players WHERE league='atp' "
                    "AND publisher_id='sinner-8b8e8'"
                ).fetchone(),
            )
            self.assertEqual(
                ("ud-a",),
                connection.execute(
                    "SELECT source_player_key FROM player_source_ids "
                    "WHERE source='underdog' AND league='atp' AND player_id=("
                    "SELECT id FROM players WHERE name='Carlos Alcaraz')"
                ).fetchone(),
            )
            self.assertEqual(
                ("ud-w",),
                connection.execute(
                    "SELECT source_player_key FROM player_source_ids "
                    "WHERE source='underdog' AND league='wta' AND player_id=("
                    "SELECT id FROM players WHERE name='Coco Gauff')"
                ).fetchone(),
            )
            self.assertEqual(5, connection.execute("SELECT COUNT(*) FROM players").fetchone()[0])
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM player_source_ids").fetchone()[0])

    def test_duplicate_publisher_names_and_ids_fail_before_any_write(self):
        duplicate_names = atp_page([
            (1, "Sinner Jannik", "sinner-8b8e8"),
            (2, "Sinner Jannik", "sinner-other"),
        ])
        with self.assertRaisesRegex(tennis.TennisSpineError, "unique resolver names"):
            tennis.refresh(
                self.db_path,
                leagues=("atp",),
                fetch_atp_page=lambda _url: (200, duplicate_names),
                dry_run=True,
                sleeper=lambda _seconds: None,
            )
        with self.assertRaisesRegex(tennis.TennisSpineError, "unique IDs"):
            tennis._validate_population("atp", [
                {"publisher_id": "same-id", "name": "Carlos Alcaraz"},
                {"publisher_id": "same-id", "name": "Jannik Sinner"},
            ], tennis.ATP_PUBLISHER)
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual(2, connection.execute("SELECT COUNT(*) FROM players").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM player_source_ids").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
