import datetime as dt
from unittest import mock

import ingest_ufcstats_prop_history as command
from ingest_ufc_fight_stats.ufcstats_pipeline import UfcStatsPlan


def test_dry_run_never_backs_up_or_writes(tmp_path, monkeypatch):
    database = tmp_path / "picks.db"
    database.write_bytes(b"not empty")
    monkeypatch.setattr(command, "inspect_migration", lambda _path: {"state": "applied"})
    monkeypatch.setattr(
        command, "load_ufcstats_state",
        lambda *_args, **_kwargs: ([mock.sentinel.target], {}, {}, {}, {}),
    )
    monkeypatch.setattr(
        command, "build_ufcstats_plan",
        lambda *_args, **_kwargs: UfcStatsPlan(target_count=1, no_history=["Debut Fighter"]),
    )
    backup = mock.Mock()
    writer = mock.Mock()
    monkeypatch.setattr(command, "_backup_to", backup)
    monkeypatch.setattr(command, "apply_ufcstats_plan", writer)

    result = command.run(
        str(database), dt.date(2026, 9, 5), str(tmp_path / "archive"),
        client=mock.sentinel.client, emit=lambda _line: None,
    )

    assert result["status"] == "dry_run"
    assert result["targets"] == 1
    assert result["no_history"] == 1
    backup.assert_not_called()
    writer.assert_not_called()


def test_apply_refuses_when_counted_plan_changes(tmp_path, monkeypatch):
    database = tmp_path / "picks.db"
    database.write_bytes(b"not empty")
    monkeypatch.setattr(command, "inspect_migration", lambda _path: {"state": "applied"})
    monkeypatch.setattr(
        command, "load_ufcstats_state",
        lambda *_args, **_kwargs: ([mock.sentinel.target], {}, {}, {}, {}),
    )
    monkeypatch.setattr(
        command, "build_ufcstats_plan",
        lambda *_args, **_kwargs: UfcStatsPlan(target_count=1),
    )
    backup = mock.Mock()
    monkeypatch.setattr(command, "_backup_to", backup)

    try:
        command.run(
            str(database), dt.date(2026, 9, 5), str(tmp_path / "archive"),
            apply=True, backup_path=str(tmp_path / "backup.db"),
            expected={"targets": 2, "inserts": 0, "updates": 0,
                      "mappings": 0, "no_history": 0},
            client=mock.sentinel.client, emit=lambda _line: None,
        )
    except RuntimeError as exc:
        assert "plan changed" in str(exc)
    else:
        raise AssertionError("changed plan was accepted")
    backup.assert_not_called()
