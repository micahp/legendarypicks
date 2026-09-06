#!/usr/bin/env python3
"""Identity boundaries for the CFBD NCAAF game-log publisher."""
import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import ingest_cfbd_logs as logs
from ingest_nfl_logs import ensure_table


def _game_payload():
    athletes = [
        {"id": "101", "name": "Known Athlete", "stat": "10"},
        {"id": "202", "name": "Missing Athlete", "stat": "7"},
        {"id": "-1001", "name": "Team", "stat": "17"},
    ]
    return [{
        "id": "game-1",
        "teams": [{
            "team": "Alpha",
            "homeAway": "home",
            "categories": [{
                "name": "rushing",
                "types": [{"name": "yds", "athletes": athletes}],
            }],
        }],
    }]


class CfbdLogIdentityTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(
            prefix="cfbd-log-identity-", suffix=".db", delete=False
        )
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        with sqlite3.connect(self.path) as con:
            con.row_factory = sqlite3.Row
            con.execute(
                """CREATE TABLE players(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT NOT NULL,
                     team TEXT,
                     league TEXT NOT NULL,
                     espn_id TEXT,
                     active INTEGER DEFAULT 1
                   )"""
            )
            con.execute(
                "INSERT INTO players(name,team,league,espn_id) "
                "VALUES('Known Athlete','ALP','ncaaf','101')"
            )
            team_player_id = con.execute(
                "INSERT INTO players(name,team,league,espn_id) "
                "VALUES('Team','ALP','ncaaf','-1001')"
            ).lastrowid
            ensure_table(con)
            con.execute(
                """INSERT INTO player_game_logs(
                     player_id,league,season,game_no,game_id,stats,source,
                     source_player_key
                   ) VALUES(?, 'ncaaf', 2026, 'legacy-game', 'legacy-game', '{}',
                            'cfbd', '-1001')""",
                (team_player_id,),
            )

    @staticmethod
    def _get_json(url):
        if "/games?" in url:
            return [{
                "id": "game-1",
                "startDate": "2026-09-01T00:00:00Z",
                "completed": True,
                "homeTeam": "Alpha",
                "awayTeam": "Bravo",
            }]
        if "/teams?" in url:
            return [
                {"school": "Alpha", "abbreviation": "ALP"},
                {"school": "Bravo", "abbreviation": "BRV"},
            ]
        if "/games/players?" in url:
            return _game_payload()
        raise AssertionError("unexpected URL %s" % url)

    @staticmethod
    def _school_to_code(school, _abbrev):
        return {"Alpha": "ALP", "Bravo": "BRV"}.get(school)

    def _run(self, dry_run):
        output = io.StringIO()
        with mock.patch.object(logs, "_get_json", side_effect=self._get_json), \
             mock.patch.object(
                 logs, "_school_to_code", side_effect=self._school_to_code
             ), contextlib.redirect_stdout(output):
            count = logs.ingest(2026, dry_run=dry_run, db_path=self.path)
        return count, output.getvalue()

    def test_source_id_miss_is_queued_and_never_mints_a_player(self):
        count, output = self._run(dry_run=False)

        self.assertEqual(count, 1)
        with sqlite3.connect(self.path) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM players").fetchone()[0], 2)
            queued = con.execute(
                """SELECT source,raw_name,source_player_key,reason
                   FROM unresolved_players"""
            ).fetchone()
            self.assertEqual(
                queued, ("cfbd", "Missing Athlete", "202", "absent_from_spine")
            )
            rows = con.execute(
                """SELECT source_player_key,player_id FROM player_game_logs
                   ORDER BY source_player_key"""
            ).fetchall()
            self.assertEqual([row[0] for row in rows], ["-1001", "101"])
            self.assertIsNotNone(rows[1][1])
        self.assertIn("IDENTITY RESOLUTION: matched 1 of 2 athlete IDs", output)
        self.assertIn("UNRESOLVED ATHLETES: 1 unique IDs across 1 log rows", output)

    def test_negative_team_entity_is_rejected_and_legacy_row_is_preserved(self):
        _, output = self._run(dry_run=False)

        with sqlite3.connect(self.path) as con:
            team_rows = con.execute(
                """SELECT COUNT(*) FROM player_game_logs
                   WHERE source_player_key='-1001'"""
            ).fetchone()[0]
        self.assertEqual(team_rows, 1)
        self.assertIn(
            "REJECTED NON-ATHLETE TEAM ENTITIES: 1 unique negative ESPN IDs "
            "across 1 stat lines",
            output,
        )
        self.assertIn(
            "legacy team-entity rows already stored for this season: 1 preserved",
            output,
        )

    def test_dry_run_resolves_against_spine_without_writing(self):
        with open(self.path, "rb") as fh:
            before = fh.read()
        _, output = self._run(dry_run=True)
        with open(self.path, "rb") as fh:
            after = fh.read()

        self.assertEqual(after, before)
        self.assertIn("IDENTITY RESOLUTION: matched 1 of 2 athlete IDs", output)
        self.assertIn("would be queued (dry run; no writes)", output)

    def test_duplicate_positive_source_id_fails_closed(self):
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT INTO players(name,team,league,espn_id) "
                "VALUES('Duplicate Athlete','ALP','ncaaf','101')"
            )
        with self.assertRaisesRegex(RuntimeError, "more than one player"):
            self._run(dry_run=True)

    def test_absent_spine_id_is_counted_even_without_a_team_code(self):
        with mock.patch.object(logs, "_get_json", side_effect=self._get_json), \
             mock.patch.object(
                 logs,
                 "_school_to_code",
                 side_effect=lambda school, _abbrev: {
                     "Alpha": "ALP", "Bravo": "BRV"
                 }.get(school),
             ), \
             mock.patch.object(logs, "_team_code", return_value=None), \
             mock.patch.object(logs, "_merge_game_athletes", return_value=iter([
                 ("202", "Missing Athlete", "Unmapped School", "home", {"rush_yds": 7})
             ])), contextlib.redirect_stdout(io.StringIO()) as output:
            logs.ingest(2026, dry_run=True, db_path=self.path)

        self.assertIn("UNRESOLVED ATHLETES: 1 unique IDs across 1 log rows", output.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
