from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.py"
SPEC = importlib.util.spec_from_file_location("run_pipeline_for_test", SCRIPT)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline)


def _replace_steps(monkeypatch, outcomes):
    def step(name):
        return lambda _dry_run=False: outcomes[name]

    monkeypatch.setattr(pipeline, "step_ingest_props", step("ingest"))
    monkeypatch.setattr(pipeline, "step_link_games", step("link"))
    monkeypatch.setattr(pipeline, "step_settle", step("settle"))
    monkeypatch.setattr(pipeline, "step_refresh_stats", step("stats"))
    monkeypatch.setattr(pipeline, "step_coverage_report", step("coverage"))


def test_scheduled_mode_never_calls_the_legacy_props_publisher(monkeypatch):
    outcomes = {"ingest": False, "link": True, "settle": True, "stats": True, "coverage": True}
    _replace_steps(monkeypatch, outcomes)

    assert pipeline.main(["--skip-props"]) == 0


def test_pipeline_returns_nonzero_when_a_selected_step_fails(monkeypatch):
    outcomes = {"ingest": True, "link": False, "settle": True, "stats": True, "coverage": True}
    _replace_steps(monkeypatch, outcomes)

    assert pipeline.main(["--skip-props"]) == 1

