#!/usr/bin/env python3
"""The per-host budget has to be counted on the scope the publisher counts on.

These exist because the guard was real, documented and measured -- and still could not
fire in the way it was actually being used. `_host_spend` was process-local, so four
separate 31-request scripts against one ESPN host spent ~124 requests and hit the wall
while every one of them believed it was at 31 of 100. Nothing was broken in a way a test
of a single process could see, which is why the first test here spans two.
"""
import json
import time

import pytest

import paced_http


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "http-spend.json"
    monkeypatch.setattr(paced_http, "_SPEND_PATH", str(path))
    monkeypatch.setattr(paced_http, "SPEND_WINDOW", 600.0)
    paced_http._host_spend.clear()
    return path


URL = "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
HOST = "site.web.api.espn.com"


def test_budget_spans_processes(ledger):
    """The regression. A second process must SEE what the first one spent."""
    for _ in range(100):
        paced_http._charge(URL, budget=100, cooldown=0, persist=True)

    # A fresh interpreter would arrive with an empty _host_spend; the ledger is the only
    # thing that carries the count across. Simulate exactly that.
    paced_http._host_spend.clear()

    with pytest.raises(paced_http.HostBudgetExhausted) as exc:
        paced_http._charge(URL, budget=100, cooldown=0, persist=True)
    assert HOST in str(exc.value)
    assert "100" in str(exc.value)


def test_refuses_before_spending_not_after(ledger):
    """It must raise INSTEAD of issuing the request, not after discovering a 403.

    A partial write behind a mid-run refusal is the failure this replaces, so the 101st
    charge must leave the ledger untouched rather than recording an attempt.
    """
    for _ in range(100):
        paced_http._charge(URL, budget=100, cooldown=0, persist=True)
    before = json.loads(ledger.read_text())[HOST]
    with pytest.raises(paced_http.HostBudgetExhausted):
        paced_http._charge(URL, budget=100, cooldown=0, persist=True)
    assert json.loads(ledger.read_text())[HOST] == before


def test_hosts_have_separate_budgets(ledger):
    """site.api being spent says nothing about sports.core -- they are separate walls."""
    for _ in range(100):
        paced_http._charge(URL, budget=100, cooldown=0, persist=True)
    other = "https://sports.core.api.espn.com/v2/sports/baseball/leagues/mlb/teams"
    paced_http._charge(other, budget=100, cooldown=0, persist=True)  # must not raise
    report = paced_http.host_spend_report()
    assert report[HOST] == 100
    assert report["sports.core.api.espn.com"] == 1


def test_spend_outside_the_window_does_not_count(ledger):
    """The wall is not permanent. An hour-old spend must not refuse today's request."""
    stale = time.time() - (paced_http.SPEND_WINDOW + 60)
    ledger.write_text(json.dumps({HOST: [stale] * 500}))
    paced_http._charge(URL, budget=100, cooldown=0, persist=True)  # must not raise
    assert paced_http.host_spend_report()[HOST] == 1


def test_unreadable_ledger_means_no_evidence_not_exhausted(ledger):
    """A corrupt ledger must fail OPEN.

    This is the one place where fail-loudly's default is wrong: refusing on an unparseable
    file would wedge every batch job on the box behind a file nobody knows to delete, and
    the publisher itself would have served the request.
    """
    ledger.write_text("{not json")
    paced_http._charge(URL, budget=100, cooldown=0, persist=True)
    assert paced_http.host_spend_report()[HOST] == 1


def test_serving_path_does_not_inherit_batch_spend(ledger):
    """persist=False keeps the old process-local behaviour, deliberately.

    A page load must never sleep 60s because an ingest ran. This asserts the opt-in is a
    real boundary rather than a flag that happens to be off.
    """
    for _ in range(100):
        paced_http._charge(URL, budget=100, cooldown=0, persist=True)
    # No raise, no sleep: the serving fetcher's own count is still 0.
    paced_http._charge(URL, budget=100, cooldown=0, persist=False)
    assert paced_http._host_spend[HOST] == 1


def test_default_fetcher_does_not_persist():
    """espn_client's module-level Fetcher serves pages. It must stay opt-out."""
    import espn_client
    assert espn_client._FETCHER.persist_spend is False
