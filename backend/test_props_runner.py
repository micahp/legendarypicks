from __future__ import annotations

import datetime as dt
import fcntl
import os
import sqlite3
import sys
import time

import pytest

import monitor_props_freshness as freshness
import run_props_ingest as runner


def _db(path):
    sqlite3.connect(path).close()
    return path


def _provider(provider_id, code="print('ok')", cadence_min=30, timeout_sec=5, host_lock=None):
    return {
        "id": provider_id,
        "cadence_min": cadence_min,
        "timeout_sec": timeout_sec,
        "host_lock": host_lock or provider_id,
        "steps": [["-c", code]],
        "needs_api_base": False,
    }


def _rows(path):
    with sqlite3.connect(path) as con:
        return con.execute(
            "SELECT provider,status,exit_code,db_path,detail FROM ingest_runs ORDER BY id"
        ).fetchall()


def _configure(monkeypatch, tmp_path, providers, db_path):
    monkeypatch.setattr(runner, "PROVIDERS", providers)
    monkeypatch.setattr(runner, "LOCK_DIR", str(tmp_path / "locks"))
    (tmp_path / "locks").mkdir(exist_ok=True)
    monkeypatch.setenv("LP_DB_PATH", str(db_path))


def test_a_provider_that_ran_recently_is_skipped_by_cadence(monkeypatch, tmp_path):
    db_path = _db(tmp_path / "cadence.db")
    _configure(monkeypatch, tmp_path, [_provider("recent")], db_path)

    assert runner.main([]) == 0
    assert runner.main([]) == 0

    assert [row[1] for row in _rows(db_path)] == ["ok", "skipped_cadence"]


def test_a_provider_with_no_prior_ok_row_is_due(monkeypatch, tmp_path):
    db_path = _db(tmp_path / "due.db")
    _configure(monkeypatch, tmp_path, [_provider("due")], db_path)

    assert runner.main([]) == 0

    assert [(row[0], row[1]) for row in _rows(db_path)] == [("due", "ok")]


def test_force_overrides_cadence_but_not_the_lock(monkeypatch, tmp_path):
    db_path = _db(tmp_path / "force.db")
    provider = _provider("shared")
    _configure(monkeypatch, tmp_path, [provider], db_path)
    assert runner.main([]) == 0

    with open(runner._host_lock_path("shared"), "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.main(["--force"]) == 0

    assert [row[1] for row in _rows(db_path)] == ["ok", "skipped_lock"]


def test_a_failing_provider_does_not_stop_the_next_one(monkeypatch, tmp_path):
    db_path = _db(tmp_path / "continue.db")
    providers = [
        _provider("broken", "import sys; print('broken'); sys.exit(7)"),
        _provider("later", "print('later ran')"),
    ]
    _configure(monkeypatch, tmp_path, providers, db_path)

    assert runner.main([]) == 0

    rows = _rows(db_path)
    assert ("broken", "failed", 7) == rows[0][:3]
    assert ("later", "ok", 0) == rows[1][:3]


def test_a_hanging_step_is_killed_at_its_budget_and_recorded_as_timeout(monkeypatch, tmp_path):
    db_path = _db(tmp_path / "timeout.db")
    _configure(
        monkeypatch,
        tmp_path,
        [_provider("hanging", "import time; time.sleep(30)", timeout_sec=1)],
        db_path,
    )

    started = time.monotonic()
    assert runner.main([]) == 1
    elapsed = time.monotonic() - started

    assert elapsed < 10
    assert _rows(db_path)[0][1] == "timeout"


def test_the_second_concurrent_run_exits_zero_without_ingesting(monkeypatch, tmp_path):
    db_path = _db(tmp_path / "concurrent.db")
    _configure(monkeypatch, tmp_path, [_provider("one")], db_path)

    with sqlite3.connect(db_path) as con:
        con.executescript(runner.INGEST_RUNS_DDL)
    with open(runner._run_lock_path(os.path.abspath(db_path)), "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.main([]) == 0

    assert _rows(db_path) == []


def test_two_environments_cannot_run_one_provider_at_once(monkeypatch, tmp_path):
    first_db = _db(tmp_path / "first.db")
    second_db = _db(tmp_path / "second.db")
    providers = [
        _provider("shared", host_lock="publisher"),
        _provider("independent", host_lock="other-publisher"),
    ]
    _configure(monkeypatch, tmp_path, providers, first_db)

    monkeypatch.setenv("LP_DB_PATH", str(second_db))
    with open(runner._host_lock_path("publisher"), "a+") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert runner.main(["--force"]) == 0

    rows = _rows(second_db)
    assert [(row[0], row[1]) for row in rows] == [
        ("shared", "skipped_lock"),
        ("independent", "ok"),
    ]


def test_lp_db_path_fully_determines_the_target(monkeypatch, tmp_path):
    first_db = _db(tmp_path / "target-one.db")
    second_db = _db(tmp_path / "target-two.db")
    _configure(monkeypatch, tmp_path, [_provider("writer")], first_db)

    monkeypatch.setenv("LP_DB_PATH", str(first_db))
    assert runner.main(["--force"]) == 0
    monkeypatch.setenv("LP_DB_PATH", str(second_db))
    assert runner.main(["--force"]) == 0

    first_rows = _rows(first_db)
    second_rows = _rows(second_db)
    assert len(first_rows) == len(second_rows) == 1
    assert first_rows[0][3] == os.path.abspath(first_db)
    assert second_rows[0][3] == os.path.abspath(second_db)


def test_an_unknown_only_value_exits_2():
    with pytest.raises(SystemExit) as exc:
        runner.main(["--only", "nope"])
    assert exc.value.code == 2


def test_dry_run_writes_no_ingest_runs_row_and_skips_bovada(monkeypatch, tmp_path, capsys):
    db_path = _db(tmp_path / "dry.db")
    providers = [
        {
            "id": "bovada",
            "cadence_min": 30,
            "timeout_sec": 5,
            "host_lock": "bovada",
            "steps": [["-c", "raise AssertionError('must not run')"]],
            "needs_api_base": True,
        },
        _provider("underdog", "import sys; assert sys.argv[-1] == '--dry-run'"),
        _provider("rotowire", "import sys; assert sys.argv[-1] == '--dry-run'"),
    ]
    _configure(monkeypatch, tmp_path, providers, db_path)

    assert runner.main(["--dry-run"]) == 0

    assert _rows(db_path) == []
    output = capsys.readouterr().out
    assert "Skipping bovada: it does not support --dry-run" in output


def test_every_registry_provider_appears_in_the_report_even_when_skipped(
    monkeypatch, tmp_path, capsys
):
    db_path = _db(tmp_path / "report.db")
    providers = [_provider("alpha"), _provider("beta"), _provider("gamma")]
    _configure(monkeypatch, tmp_path, providers, db_path)

    assert runner.main(["--only", "alpha"]) == 0

    report = capsys.readouterr().out.split("--- props ingest run report ---", 1)[1]
    assert all(provider["id"] in report for provider in providers)
    assert "not_selected" in report


def test_an_unmapped_source_label_is_reported_by_the_freshness_monitor(monkeypatch, capsys):
    now = dt.datetime.now(dt.timezone.utc)
    monkeypatch.setattr(freshness, "ENVS", {"dev": "unused"})
    monkeypatch.setattr(
        freshness,
        "latest_capture",
        lambda _base: {
            "bovada": now,
            "underdog": now,
            "rotowire:prizepicks": now,
            "new-provider-label": now,
        },
    )

    with pytest.raises(SystemExit) as exc:
        freshness.main()

    assert exc.value.code == 1
    assert "UNKNOWN SOURCE new-provider-label" in capsys.readouterr().out

def test_a_cadence_equal_to_the_timer_interval_still_fires(monkeypatch, tmp_path):
    """The *:04/*:34 firing measures its age from the previous run's `started_at`, which is
    a few seconds after *:04, so an exact-equality check lands short and skips forever.
    Measured on the box 2026-08-24: bovada skipped at *:34 with "last ok 30m ago"."""
    db_path = _db(tmp_path / "grace.db")
    _configure(monkeypatch, tmp_path, [_provider("ontime", cadence_min=30)], db_path)

    assert runner.main([]) == 0
    # The previous run started 29m58s ago: one timer interval, minus the seconds the run
    # itself took to reach the ingest_runs insert.
    with sqlite3.connect(db_path) as con:
        con.execute(
            "UPDATE ingest_runs SET started_at = ?",
            ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=29, seconds=58))
             .isoformat(),),
        )
    assert runner.main([]) == 0
    assert [row[1] for row in _rows(db_path)] == ["ok", "ok"]
