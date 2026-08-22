"""Recurring pipeline work must never select the finished World Cup."""
from __future__ import annotations

import importlib.util
import os
import sqlite3
from pathlib import Path


_PATH = Path(__file__).parents[1] / "scripts" / "run_pipeline.py"
_SPEC = importlib.util.spec_from_file_location("candidate_run_pipeline", _PATH)
pipeline = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(pipeline)


def test_active_link_leagues_excludes_world_cup_even_if_it_has_recent_rows(tmp_path):
    path = tmp_path / "picks.db"
    with sqlite3.connect(path) as con:
        con.executescript("""
            CREATE TABLE prop_games(league TEXT, date TEXT);
            INSERT INTO prop_games VALUES('wc', DATE('now'));
            INSERT INTO prop_games VALUES('nfl', DATE('now'));
        """)
    previous = os.environ.get("LP_DB_PATH")
    os.environ["LP_DB_PATH"] = str(path)
    try:
        assert pipeline._link_leagues() == ["nfl"]
    finally:
        if previous is None:
            os.environ.pop("LP_DB_PATH", None)
        else:
            os.environ["LP_DB_PATH"] = previous


def test_settlement_has_a_second_world_cup_exclusion_guard(monkeypatch):
    commands = []
    monkeypatch.setattr(pipeline, "_link_leagues", lambda: ["nfl", "wc"])
    monkeypatch.setattr(
        pipeline, "_run",
        lambda command, name, **_kwargs: commands.append((command, name)) or True,
    )

    assert pipeline.step_settle() is True
    assert [name for _, name in commands] == ["settle_nfl"]
    assert all("wc" not in command for command, _ in commands)
    assert "--since" in commands[0][0]
