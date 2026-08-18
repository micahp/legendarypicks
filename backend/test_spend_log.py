"""The spend log: one line per request, and it can never break a request.

Every figure we have about ESPN's limit except the response cap is inferred
from behaviour (docs/DESIGN-request-budget.md §1). This log exists to replace
the inference with data, so the two things it must guarantee are that a
refusal is recorded (the line that decides whether a 403 tracks a request
count) and that a logging failure is invisible to the caller.
"""
import json
import os
import sys
import tempfile
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import paced_http


def _lines(path):
    with open(path) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def test_a_success_is_recorded_with_host_and_path(tmp_path, monkeypatch):
    log = tmp_path / "spend.jsonl"
    monkeypatch.setattr(paced_http, "SPEND_LOG", str(log))
    paced_http.record_spend(
        "https://site.web.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates=20260818",
        200)
    row = _lines(str(log))[0]
    assert row["host"] == "site.web.api.espn.com"
    assert row["status"] == 200
    assert row["cached"] is False
    # The query string is dropped: the question is which ENDPOINT costs us,
    # not which game, or every date becomes its own row.
    assert "dates" not in row["path"]
    assert row["path"].startswith("/apis/site/v2")


def test_a_refusal_is_recorded(tmp_path, monkeypatch):
    """The most valuable line in the file. Without it the 403s are invisible."""
    log = tmp_path / "spend.jsonl"
    monkeypatch.setattr(paced_http, "SPEND_LOG", str(log))
    paced_http.record_spend("https://site.api.espn.com/x", 403, note="raised")
    row = _lines(str(log))[0]
    assert row["status"] == 403
    assert row["note"] == "raised"


def test_a_cache_hit_is_marked_as_one(tmp_path, monkeypatch):
    log = tmp_path / "spend.jsonl"
    monkeypatch.setattr(paced_http, "SPEND_LOG", str(log))
    paced_http.record_spend("https://x.espn.com/y", 200, cached=True, note="disk")
    assert _lines(str(log))[0]["cached"] is True


def test_the_process_is_identified(tmp_path, monkeypatch):
    """Eighteen timers write one file. A line that cannot name its job is noise."""
    log = tmp_path / "spend.jsonl"
    monkeypatch.setattr(paced_http, "SPEND_LOG", str(log))
    paced_http.record_spend("https://x.espn.com/y", 200)
    row = _lines(str(log))[0]
    assert row["proc"]
    assert row["pid"] == os.getpid()


def test_a_broken_log_never_breaks_the_caller():
    """Measurement must not be able to take down a fetch.

    Losing a record is strictly better than losing the request, so this
    swallows everything rather than choosing which failures are survivable.
    """
    with mock.patch.object(paced_http, "SPEND_LOG", "/nonexistent/dir/spend.jsonl"):
        paced_http.record_spend("https://x.espn.com/y", 200)  # must not raise
    with mock.patch("builtins.open", side_effect=OSError("disk full")):
        paced_http.record_spend("https://x.espn.com/y", 200)  # must not raise


def test_concurrent_writers_do_not_interleave(tmp_path, monkeypatch):
    """Eighteen timers append to this file, so every line must stay parseable.

    An O_APPEND write below PIPE_BUF is atomic on Linux, which is why this is
    a plain file and not SQLite: there is no lock to contend and no job can be
    wedged behind one.
    """
    log = tmp_path / "spend.jsonl"
    monkeypatch.setattr(paced_http, "SPEND_LOG", str(log))
    for i in range(200):
        paced_http.record_spend(f"https://h{i % 3}.espn.com/apis/v2/x", 200)
    rows = _lines(str(log))
    assert len(rows) == 200
    assert len({r["host"] for r in rows}) == 3
