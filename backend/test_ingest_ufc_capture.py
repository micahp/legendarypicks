"""UFC plan payloads must enter the raw ledger in the same apply transaction."""
from __future__ import annotations

import json
import sqlite3
from urllib.error import HTTPError

import ingest_ufc_fight_stats as ingest
from ingest_ufc_fight_stats import card
from migrate_publisher_captures import apply_database


def test_fetch_stats_keeps_the_complete_espn_response(monkeypatch):
    raw = {
        "splits": {"categories": [{"stats": [
            {"name": "sigStrikesLanded", "value": 42},
        ]}]},
        "publisher_only": {"future_stat": True},
    }
    monkeypatch.setattr(ingest.espn, "_get", lambda *_args, **_kwargs: raw)

    stats = ingest.fetch_stats("event", "fight", "fighter", attempts=1)

    assert dict(stats) == {"sigStrikesLanded": 42}
    assert stats.raw_payload == raw


def test_empty_stats_response_is_still_retained_in_the_plan(monkeypatch):
    target = ingest.FighterTarget(
        1, "Stored Fighter", "123", None, None, "Opponent"
    )
    fight = {
        "event_id": "event", "fight_id": "fight", "date": "2026-07-25",
        "opponent": "Opponent",
    }
    raw = {"splits": {"categories": []}, "publisher_only": {"keep": 1}}
    monkeypatch.setattr(ingest, "fetch_fight_history", lambda *_args, **_kwargs: [fight])
    monkeypatch.setattr(
        ingest, "fetch_stats", lambda *_args, **_kwargs: ingest.StatsPayload({}, raw)
    )

    plan = ingest.build_plan([target], set(), {"123": 1}, limit=1, emit=lambda _: None)

    assert plan.logs == []
    assert plan.missing_stats == ["Stored Fighter:fight:2026-07-25"]
    assert len(plan.source_payloads) == 1
    assert plan.source_payloads[0].payload == raw


def test_stats_404_does_not_invent_a_capture_payload(monkeypatch):
    error = HTTPError("https://example.test/stats", 404, "missing", None, None)
    monkeypatch.setattr(
        ingest.espn, "_get", lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
    )

    stats = ingest.fetch_stats("event", "fight", "fighter", attempts=1)

    assert dict(stats) == {}
    assert stats.raw_payload is None


def test_card_fetch_carries_the_raw_scoreboard_body(monkeypatch):
    raw = {"events": [{"publisher_only": {"keep": 1}}]}
    normalized = [{"game_id": "fight", "event_id": "event"}]
    monkeypatch.setattr(card.espn, "scoreboard_raw", lambda *_args, **_kwargs: raw)
    monkeypatch.setattr(
        "espn_client.scoreboard._games_from_payload",
        lambda *_args, **_kwargs: normalized,
    )

    cache = {}
    games, error = card._card_for_date("2026-07-25", cache)

    assert error is None
    assert games == normalized
    assert card.card_source_payloads(cache) == [
        (card._scoreboard_endpoint("2026-07-25"), raw)
    ]


def test_history_payloads_are_carried_before_the_history_rows_are_parsed(monkeypatch):
    target = ingest.FighterTarget(
        1, "Stored Fighter", "123", None, None, "Opponent"
    )
    fight = {
        "event_id": "event", "fight_id": "fight", "date": "2026-07-25",
        "opponent": "Opponent", "result": "W", "method": "DEC",
    }
    raw_history = {"fightHistory": ["publisher_only"]}
    history = ingest.espn.FightHistory(
        [fight], [("https://example.test/history", raw_history)]
    )
    raw_stats = {"splits": {"categories": [{"stats": [
        {"name": "sigStrikesLanded", "value": 42},
    ]}]}}
    monkeypatch.setattr(ingest, "fetch_fight_history", lambda *_args, **_kwargs: history)
    monkeypatch.setattr(
        ingest, "fetch_stats",
        lambda *_args, **_kwargs: ingest.StatsPayload(
            {"sigStrikesLanded": 42}, raw_stats
        ),
    )

    plan = ingest.build_plan([target], set(), {"123": 1}, limit=1, emit=lambda _: None)

    assert len(plan.logs) == 1
    assert [source.payload for source in plan.source_payloads] == [
        raw_history, raw_stats,
    ]


def test_espn_history_keeps_every_successful_native_body(monkeypatch):
    overview = {"fightHistory": ["s:mma~l:ufc~e:10~c:20"]}
    competition = {
        "date": "2026-07-25T20:00:00Z",
        "competitors": [{"id": "123", "winner": True}, {"id": "456"}],
    }
    status = {
        "type": {"state": "post"}, "result": {"shortDisplayName": "Decision"},
        "period": 3, "clock": 300, "displayClock": "5:00",
    }
    opponent = {"displayName": "Opponent"}

    def get(url, **_kwargs):
        if url.endswith("/athletes/123/overview"):
            return overview
        if "/competitions/20?" in url:
            return competition
        if "/competitions/20/status?" in url:
            return status
        if "/athletes/456?" in url:
            return opponent
        raise AssertionError(url)

    monkeypatch.setattr(ingest.espn, "_get", get)

    history = ingest.espn.ufc_fight_history("123", limit=1)

    assert list(history) == [{
        "result": "W", "method": "DEC", "opponent": "Opponent",
        "date": "2026-07-25", "event_id": "10", "fight_id": "20",
        "round": 3, "clock_display": "5:00", "fight_time_seconds": 900,
    }]
    assert [payload for _, payload in history.source_payloads] == [
        overview, competition, status, opponent,
    ]


def test_apply_retains_carried_ufc_source_payload(tmp_path):
    path = tmp_path / "picks.db"
    with sqlite3.connect(path) as con:
        con.executescript("CREATE TABLE players(id INTEGER PRIMARY KEY, league TEXT, espn_id TEXT);")
    apply_database(str(path))
    plan = ingest.IngestPlan(
        target_count=0,
        source_payloads=[ingest.SourcePayload(
            endpoint="https://example.test/status", payload={"publisher_only": {"keep": 1}}
        )],
    )
    assert ingest.apply_plan(str(path), plan)["inserted_logs"] == 0
    with sqlite3.connect(path) as con:
        payload = con.execute("SELECT payload_json FROM publisher_captures").fetchone()[0]
    assert json.loads(payload) == {"publisher_only": {"keep": 1}}
