import datetime as dt
import sqlite3

import ingest_rotowire_props as publisher
import monitor_rotowire_soccer as monitor


def _database():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE prop_games(
          league TEXT,
          start_time TEXT
        );
        CREATE TABLE scoreboard_snapshots(
          league TEXT,
          start_time TEXT
        );
        """
    )
    return con


def test_kickoff_window_uses_published_scoreboard_without_prop_game():
    con = _database()
    kickoff = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
    con.execute(
        "INSERT INTO scoreboard_snapshots(league,start_time) VALUES('mls',?)",
        (kickoff.isoformat(),),
    )

    should_probe, reason = monitor._kickoff_window(con)

    assert should_probe is True
    assert "next MLS kickoff in" in reason


def test_kickoff_window_retains_prop_games_fallback():
    con = _database()
    kickoff = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
    con.execute(
        "INSERT INTO prop_games(league,start_time) VALUES('mls',?)",
        (kickoff.isoformat(),),
    )

    should_probe, reason = monitor._kickoff_window(con)

    assert should_probe is True
    assert "next MLS kickoff in" in reason


def test_kickoff_window_skips_without_a_scheduled_game():
    con = _database()

    should_probe, reason = monitor._kickoff_window(con)

    assert should_probe is False
    assert "no upcoming MLS fixture" in reason


def test_one_payload_is_published_serially_to_both_databases(tmp_path, monkeypatch):
    dev = tmp_path / "picks.dev.db"
    prod = tmp_path / "picks.db"
    dev.touch()
    prod.touch()
    parsed = []
    published = []

    def fake_parse(payload, league):
        parsed.append((payload, league))
        return [object()], {"counts": {"game_props": 1}}

    def fake_ingest(rows, league):
        published.append((publisher.DB, rows, league))
        return {
            "new": 1,
            "refreshed": 0,
            "games": 1,
            "players": 1,
            "unresolved_player_rows": 0,
            "board_rows": 1,
            "unknown_team": 0,
        }

    monkeypatch.setattr(publisher, "parse", fake_parse)
    monkeypatch.setattr(publisher, "ingest", fake_ingest)

    assert monitor.publish_payload({"props": []}, [str(dev), str(prod)]) is True
    assert len(parsed) == 1
    assert [row[0] for row in published] == [str(dev), str(prod)]
