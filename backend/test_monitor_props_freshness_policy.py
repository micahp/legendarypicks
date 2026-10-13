"""Freshness monitoring must not bypass an intentionally disabled props schedule."""
from __future__ import annotations

import monitor_props_freshness as monitor


def test_monitor_has_no_automatic_props_service_targets():
    assert monitor.ENVS == {
        "dev": "http://127.0.0.1:8096",
        "prod": "http://127.0.0.1:8100",
    }
    assert not hasattr(monitor, "_self_heal")


def test_stale_monitoring_alerts_without_starting_a_service(monkeypatch, capsys):
    monkeypatch.setattr(monitor, "ENVS", {"dev": "http://127.0.0.1:8096"})
    monkeypatch.setattr(monitor, "latest_capture", lambda _base: None)
    try:
        monitor.main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        assert False, "stale props must fail the monitor"
    assert "no props in DB" in capsys.readouterr().out
