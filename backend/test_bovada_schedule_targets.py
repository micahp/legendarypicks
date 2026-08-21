"""Scheduled props collection never requests the out-of-season World Cup."""

from bovada_scraper.cli import targets_for_request


def test_all_targets_exclude_world_cup_but_explicit_historical_request_remains_available():
    assert "wc" not in dict(targets_for_request("all"))
    assert [name for name, _ in targets_for_request("wc")] == ["wc"]


def test_unknown_target_is_rejected():
    assert targets_for_request("not-a-league") is None
