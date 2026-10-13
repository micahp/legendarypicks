import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import ingest_rotowire_soccer_stats as rw
import scripts_add_rotowire_soccer_logs as schema


def source_row(**overrides):
    row = {
        "ID": "1142", "URL": "/soccer/player/matt-turner-1142",
        "player": "Matt Turner", "firstname": "Matt", "lastname": "Turner",
        "league": "MLS", "team": "NER", "opp": "NSH", "homeaway": "A",
        "position": "GK", "formation": "4231", "gp": 1, "min": "90",
        "p": "13", "ap": "15", "sv": "4", "gc": "1", "sog": "0",
    }
    row.update(overrides)
    return row


def fixture_payload(*, league="mls", season=2026, completed=True):
    codes = ("NE", "NSH") if league == "mls" else ("AME", "ASL")
    return {"events": [{
        "id": "761444", "date": "2026-02-22T00:00Z",
        "season": {"year": season},
        "competitions": [{
            "date": "2026-02-22T00:00Z",
            "status": {"type": {"completed": completed}},
            "competitors": [
                {"homeAway": "home", "team": {"abbreviation": codes[1]}},
                {"homeAway": "away", "team": {"abbreviation": codes[0]}},
            ],
        }],
    }]}


def create_database(path, migrate=True):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE players(
            id INTEGER PRIMARY KEY, name TEXT NOT NULL, team TEXT,
            league TEXT NOT NULL, active INTEGER DEFAULT 1
        );
        CREATE TABLE player_source_ids(
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
            league TEXT NOT NULL, source_player_key TEXT NOT NULL,
            player_id INTEGER NOT NULL, first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE UNIQUE INDEX ux_player_source_ids
            ON player_source_ids(source,league,source_player_key);
        CREATE TABLE unresolved_players(
            id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL,
            raw_name TEXT NOT NULL, league TEXT NOT NULL, team TEXT,
            first_seen TEXT NOT NULL, count INTEGER DEFAULT 1,
            source_player_key TEXT, reason TEXT
        );
        CREATE TABLE player_game_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER,
            league TEXT NOT NULL, season INTEGER NOT NULL, game_no TEXT,
            game_id TEXT, game_date TEXT, team TEXT, opponent TEXT,
            home_away TEXT, stats TEXT NOT NULL, source TEXT,
            source_player_key TEXT, ingested_at TEXT, game_type TEXT,
            UNIQUE(league,source_player_key,season,game_no)
        );
        CREATE TABLE player_game_logs_fotmob(
            id INTEGER PRIMARY KEY AUTOINCREMENT, player_id INTEGER,
            league TEXT NOT NULL, season INTEGER NOT NULL, game_no TEXT,
            game_id TEXT, game_date TEXT, team TEXT, opponent TEXT,
            home_away TEXT, stats TEXT NOT NULL, source TEXT,
            source_player_key TEXT, ingested_at TEXT, game_type TEXT,
            UNIQUE(league,source_player_key,season,game_no)
        );
    """)
    if migrate:
        schema.apply_schema(con)
    con.row_factory = sqlite3.Row
    return con


def add_appearance(con, player_id=1, name="Matt Turner", team="NE",
                   opponent="NSH", game_id="761444", date="2026-02-22",
                   source_key="303794"):
    con.execute(
        "INSERT OR IGNORE INTO players(id,name,team,league) VALUES(?,?,?,'mls')",
        (player_id, name, team),
    )
    con.execute(
        "INSERT INTO player_game_logs(player_id,league,season,game_no,game_id,"
        "game_date,team,opponent,home_away,stats,source,source_player_key,game_type) "
        "VALUES(?,'mls',2026,?,?,?,?,?,'away',?,'espn',?,'REG')",
        (player_id, game_id, game_id, date, team, opponent,
         json.dumps({"saves": 4}), source_key),
    )
    con.commit()


class PublishedStatContract(unittest.TestCase):
    def test_attempted_and_completed_passes_stay_distinct(self):
        line = rw.stat_line(source_row(p="13", ap="15", cr="4", acr="2"))
        self.assertEqual(line["passes"], 13.0)
        self.assertEqual(line["passes_attempted"], 15.0)
        self.assertEqual(line["crosses"], 4.0)
        self.assertEqual(line["accurate_crosses"], 2.0)

    def test_single_week_must_still_be_one_game(self):
        with self.assertRaisesRegex(rw.SourceContractError, "expected one per-match"):
            rw.parse_response([source_row(gp=2)], "mls", 2026, 1, "A")

    def test_required_league_and_identity_fields_fail_loudly(self):
        with self.assertRaises(rw.SourceContractError):
            rw.parse_response([source_row(league="LMX")], "mls", 2026, 1, "A")
        with self.assertRaises(rw.SourceContractError):
            rw.parse_response([source_row(ID="")], "mls", 2026, 1, "A")

    def test_publisher_team_aliases_match_the_canonical_fixture_vocabulary(self):
        self.assertEqual(rw.normalize_team("mls", "NER"), "NE")
        self.assertEqual(rw.normalize_team("mls", "NYR"), "RBNY")
        self.assertEqual(rw.normalize_team("mls", "FIR"), "CHI")
        self.assertEqual(rw.normalize_team("mls", "MNU"), "MIN")
        self.assertEqual(rw.normalize_team("mls", "RAP"), "COL")
        self.assertEqual(rw.normalize_team("mls", "SOU"), "SEA")
        self.assertEqual(rw.normalize_team("mls", "WHI"), "VAN")
        self.assertEqual(rw.normalize_team("ligamx", "CA"), "CAZ")
        self.assertEqual(rw.normalize_team("ligamx", "GUA"), "GDL")
        self.assertEqual(rw.normalize_team("ligamx", "MON"), "MTY")
        self.assertEqual(rw.normalize_team("ligamx", "NEC"), "NCX")
        self.assertEqual(rw.normalize_team("ligamx", "QUE"), "QRO")
        self.assertEqual(rw.normalize_team("ligamx", "TIG"), "UANL")
        self.assertEqual(rw.normalize_team("ligamx", "UNM"), "UNAM")

    def test_overlapping_filters_deduplicate_without_losing_provenance(self):
        first = rw.parse_response([source_row()], "mls", 2026, 1, "A")[0]
        second = rw.parse_response([source_row()], "mls", 2026, 1, "G")[0]
        merged = rw.merge_filter_rows([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["position_filters"], {"A", "G"})

    def test_conflicting_filtered_copies_abort(self):
        first = rw.parse_response([source_row()], "mls", 2026, 1, "A")[0]
        second = rw.parse_response([source_row(ap="99")], "mls", 2026, 1, "G")[0]
        with self.assertRaisesRegex(rw.SourceContractError, "conflicting"):
            rw.merge_filter_rows([first, second])

    def test_fixture_schedule_is_season_and_completion_scoped(self):
        payload = fixture_payload()
        payload["events"].append(fixture_payload(season=2025)["events"][0])
        payload["events"].append(
            fixture_payload(completed=False)["events"][0])
        fixtures = rw.parse_fixture_schedule(payload, "mls", 2026)
        self.assertEqual(len(fixtures), 2)
        away = [row for row in fixtures if row["home_away"] == "away"][0]
        self.assertEqual(
            (away["game_id"], away["game_date"], away["team"], away["opponent"]),
            ("761444", "2026-02-22", "NE", "NSH"),
        )


class AdditiveSchemaMigration(unittest.TestCase):
    def test_apply_takes_a_backup_and_extends_the_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "candidate.db")
            con = create_database(path, migrate=False)
            con.close()

            self.assertEqual(schema.main(["--db", path, "--apply"]), 0)
            self.assertEqual(schema.main(["--db", path, "--check"]), 0)
            backups = [name for name in os.listdir(tmp)
                       if ".pre-rotowire-soccer-" in name]
            self.assertEqual(len(backups), 1)
            check = sqlite3.connect(path)
            try:
                self.assertEqual(schema.status(check), {
                    "table": True, "view_has_rotowire": True})
                self.assertEqual(check.execute(
                    "PRAGMA quick_check").fetchone()[0], "ok")
            finally:
                check.close()


class ProviderSeparatedPublication(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(prefix="rw-soccer-", suffix=".db",
                                             delete=False)
        self.path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.con = create_database(self.path)
        self.addCleanup(self.con.close)
        add_appearance(self.con)

    def parsed(self, **overrides):
        rows = rw.parse_response(
            [source_row(**overrides)], "mls", 2026, 1, "A")
        return rw.merge_filter_rows(rows)

    def test_fixture_roster_identity_and_provider_column(self):
        result = rw.publish(self.con, self.parsed())
        self.assertEqual(result["fixture_name_team"], 1)
        self.assertEqual(result["published"], 1)

        stored = self.con.execute(
            "SELECT player_id,game_id,game_date,team,opponent,source_matchweek,"
            "source_position_filters,stats FROM player_game_logs_rotowire"
        ).fetchone()
        self.assertEqual(
            tuple(stored[:7]), (1, "761444", "2026-02-22", "NE", "NSH", 1, "A"))
        self.assertEqual(json.loads(stored["stats"])["passes_attempted"], 15.0)
        binding = self.con.execute(
            "SELECT player_id FROM player_source_ids WHERE source='rotowire' "
            "AND league='mls' AND source_player_key='1142'"
        ).fetchone()
        self.assertEqual(binding[0], 1)

        view = self.con.execute(
            "SELECT espn_stats,fotmob_stats,rotowire_stats "
            "FROM player_game_logs_all WHERE player_id=1"
        ).fetchone()
        self.assertIsNotNone(view["espn_stats"])
        self.assertIsNone(view["fotmob_stats"])
        self.assertEqual(json.loads(view["rotowire_stats"])["passes_attempted"], 15.0)

    def test_replay_updates_one_provider_row(self):
        rw.publish(self.con, self.parsed())
        rw.publish(self.con, self.parsed(ap="18"))
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_game_logs_rotowire").fetchone()[0], 1)
        stats = json.loads(self.con.execute(
            "SELECT stats FROM player_game_logs_rotowire").fetchone()[0])
        self.assertEqual(stats["passes_attempted"], 18.0)

    def test_identical_replay_is_a_true_noop(self):
        first = rw.publish(self.con, self.parsed())
        before = self.con.execute(
            "SELECT ingested_at FROM player_game_logs_rotowire").fetchone()[0]
        unresolved_before = self.con.execute(
            "SELECT COALESCE(SUM(count),0) FROM unresolved_players").fetchone()[0]
        second = rw.publish(self.con, self.parsed())
        after = self.con.execute(
            "SELECT ingested_at FROM player_game_logs_rotowire").fetchone()[0]
        unresolved_after = self.con.execute(
            "SELECT COALESCE(SUM(count),0) FROM unresolved_players").fetchone()[0]
        self.assertEqual(first["published"], 1)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(second["published"], 0)
        self.assertEqual(after, before)
        self.assertEqual(unresolved_after, unresolved_before)

    def test_ambiguous_fixture_roster_is_retained_unresolved(self):
        add_appearance(
            self.con, player_id=2, name="Matt Turner", team="NE",
            source_key="other-espn-id")
        result = rw.publish(self.con, self.parsed())
        self.assertEqual(result["ambiguous_fixture_name"], 1)
        row = self.con.execute(
            "SELECT player_id FROM player_game_logs_rotowire").fetchone()
        self.assertIsNone(row["player_id"])
        unresolved = self.con.execute(
            "SELECT source_player_key,reason FROM unresolved_players").fetchone()
        self.assertEqual(tuple(unresolved), ("1142", "ambiguous_fixture_name"))

        rw._bind_player(self.con, self.parsed()[0], 1, "later")
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM unresolved_players").fetchone()[0], 0)

    def test_a_nonunique_fixture_aborts_before_writing(self):
        add_appearance(
            self.con, game_id="761999", date="2026-09-01",
            source_key="same-player-second-game")
        with self.assertRaisesRegex(rw.SourceContractError, "nothing written"):
            rw.publish(self.con, self.parsed())
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_game_logs_rotowire").fetchone()[0], 0)

    def test_dry_run_plans_without_writing_identity_or_logs(self):
        result = rw.publish(self.con, self.parsed(), dry_run=True)
        self.assertEqual(result["planned"], 1)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_game_logs_rotowire").fetchone()[0], 0)
        self.assertEqual(self.con.execute(
            "SELECT COUNT(*) FROM player_source_ids").fetchone()[0], 0)

    def test_published_fixture_uses_date_roster_when_game_id_is_absent(self):
        self.con.execute(
            "UPDATE player_game_logs SET team=NULL,opponent=NULL,home_away=NULL")
        self.con.commit()
        fixture = {
            "game_id": "different-provider-id", "game_date": "2026-02-22",
            "team": "NE", "opponent": "NSH", "home_away": "away",
            "game_type": "REG",
        }
        result = rw.publish(
            self.con, self.parsed(), published_fixtures=[fixture])
        self.assertEqual(result["fixture_name_team"], 1)
        stored = self.con.execute(
            "SELECT player_id,game_id FROM player_game_logs_rotowire").fetchone()
        self.assertEqual(tuple(stored), (1, "different-provider-id"))

    def test_stable_binding_survives_a_missing_local_appearance(self):
        rw.publish(self.con, self.parsed())
        self.con.execute("DELETE FROM player_game_logs")
        self.con.commit()
        fixture = {
            "game_id": "later-game", "game_date": "2026-05-09",
            "team": "NE", "opponent": "NSH", "home_away": "away",
            "game_type": "REG",
        }
        result = rw.publish(
            self.con, self.parsed(), published_fixtures=[fixture])
        self.assertEqual(result["source_id_name_team"], 1)

    def test_stable_binding_rejects_a_published_name_disagreement(self):
        rw.publish(self.con, self.parsed())
        changed = self.parsed(player="Different Person")
        with self.assertRaisesRegex(rw.IdentityConflict, "disagrees"):
            rw.publish(self.con, changed)


class RequestAndArchiveBounds(unittest.TestCase):
    def test_request_contains_every_mandatory_flag(self):
        params = rw.request_params("ligamx", 2026, 4, "G")
        self.assertEqual(params["LMX"], "1")
        self.assertEqual(params["MLS"], "0")
        self.assertEqual((params["start"], params["end"]), ("4", "4"))
        self.assertEqual(set(rw._LEAGUE_FLAGS) - set(params), set())

    def test_archives_are_lossless(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rw, "ARCHIVE_DIR", tmp):
            payload = [source_row()]
            path = rw.archive_response(payload, "mls", 2026, 1, "A")
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), payload)

    def test_reuse_archive_avoids_a_duplicate_request(self):
        handle = tempfile.NamedTemporaryFile(prefix="rw-reuse-", suffix=".db",
                                             delete=False)
        path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        con = create_database(path)
        add_appearance(con)
        con.close()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rw, "ARCHIVE_DIR", tmp), \
                mock.patch.object(rw, "DB_PATH", path):
            rw.archive_response(
                [source_row()], "mls", 2026, 1, "A",
                captured_at=rw.dt.datetime(2026, 8, 27, tzinfo=rw.dt.timezone.utc),
            )
            rw.fixture_archive_response(
                fixture_payload(), "mls", 2026,
                captured_at=rw.dt.datetime(2026, 8, 27, tzinfo=rw.dt.timezone.utc),
            )
            with mock.patch.object(rw, "_get") as fetch, \
                    mock.patch("builtins.print") as output:
                result = rw.main([
                    "--league", "mls", "--start-week", "1",
                    "--positions", "A", "--max-requests", "1",
                    "--reuse-archives", "--dry-run",
                ])
            self.assertEqual(result, 0)
            fetch.assert_not_called()
            rendered = "\n".join(" ".join(map(str, call.args))
                                 for call in output.call_args_list)
            self.assertIn("archives_reused=1", rendered)
            self.assertNotIn("requests=", rendered)

    def test_explicit_empty_probe_reports_zero_without_writing(self):
        handle = tempfile.NamedTemporaryFile(prefix="rw-empty-", suffix=".db",
                                             delete=False)
        path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        con = create_database(path)
        con.close()
        with mock.patch.object(rw, "DB_PATH", path), \
                mock.patch.object(rw, "_get", return_value=[]), \
                mock.patch.object(rw, "archive_response", return_value="archive"), \
                mock.patch("builtins.print") as output:
            result = rw.main([
                "--league", "ligamx", "--start-week", "18",
                "--positions", "A", "--max-requests", "1", "--allow-empty",
            ])
        self.assertEqual(result, 0)
        rendered = "\n".join(" ".join(map(str, call.args))
                             for call in output.call_args_list)
        self.assertIn("empty_responses=1", rendered)
        self.assertIn("NO PUBLISHED ROWS", rendered)

    def test_main_counts_capped_responses_and_respects_dry_run(self):
        handle = tempfile.NamedTemporaryFile(prefix="rw-main-", suffix=".db",
                                             delete=False)
        path = handle.name
        handle.close()
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        con = create_database(path)
        add_appearance(con)
        con.close()
        payloads = {
            "A": [source_row()] + [source_row(
                ID=str(2000 + n), player=f"Other {n}")
                for n in range(4)],
            "G": [source_row()] + [source_row(
                ID=str(3000 + n), player=f"Keeper {n}")
                for n in range(4)],
        }

        def fake_get(params):
            return payloads[params["position"]]

        with mock.patch.object(rw, "DB_PATH", path), \
                mock.patch.object(rw, "_get", side_effect=fake_get), \
                mock.patch.object(rw, "archive_response", return_value="archive"), \
                mock.patch.object(rw, "fetch_fixture_schedule",
                                  return_value=fixture_payload()), \
                mock.patch.object(rw, "fixture_archive_response",
                                  return_value="fixture-archive"), \
                mock.patch("builtins.print") as output:
            result = rw.main([
                "--league", "mls", "--start-week", "1", "--positions", "A,G",
                "--max-requests", "2", "--dry-run",
            ])
        self.assertEqual(result, 0)
        rendered = "\n".join(" ".join(map(str, call.args))
                             for call in output.call_args_list)
        self.assertIn("capped_responses=2", rendered)
        self.assertIn("PUBLIC FILTERED SAMPLE", rendered)
        check = sqlite3.connect(path)
        try:
            self.assertEqual(check.execute(
                "SELECT COUNT(*) FROM player_game_logs_rotowire").fetchone()[0], 0)
        finally:
            check.close()

    def test_request_budget_refuses_before_network(self):
        with mock.patch.object(rw, "_get") as fetch:
            with self.assertRaises(SystemExit):
                rw.main([
                    "--league", "mls", "--start-week", "1", "--end-week", "5",
                    "--max-requests", "16", "--dry-run",
                ])
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
