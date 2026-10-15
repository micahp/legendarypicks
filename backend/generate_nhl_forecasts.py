#!/usr/bin/env python3
"""Generate NHL forecasts for upcoming games using the frozen research model.

Reads the NHL schedule API, identifies games without complete forecast sets,
runs the existing pipeline logic from run_pipeline.py, and appends to
forecasts.jsonl. Idempotent and safe to run on a schedule.

Defaults to dry-run. Use --apply to write to the ledger.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import sys
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# Stub out sklearn before importing run_pipeline.
# sklearn is only needed for fit_frozen() (model training), not forecast().
# The backend venv has numpy but not sklearn; the frozen model JSON already
# contains fitted coefficients so forecast() only needs numpy dot products.
# ---------------------------------------------------------------------------
_sklearn_stub = types.ModuleType("sklearn")
_lm_stub = types.ModuleType("sklearn.linear_model")


class _DummyPoissonRegressor:
    def __init__(self, *args, **kwargs):
        pass

    def fit(self, X, y):
        return self


_lm_stub.PoissonRegressor = _DummyPoissonRegressor
_sklearn_stub.linear_model = _lm_stub
sys.modules.setdefault("sklearn", _sklearn_stub)
sys.modules.setdefault("sklearn.linear_model", _lm_stub)

# ---------------------------------------------------------------------------
# Import run_pipeline from the research directory.
# ---------------------------------------------------------------------------
RESEARCH_DIR = Path(
    "/root/legendarypicks/research/nhl/prospective-2026-27"
)
_spec = importlib.util.spec_from_file_location(
    "run_pipeline", RESEARCH_DIR / "run_pipeline.py"
)
run_pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_pipeline)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--horizon-hours",
        type=float,
        default=24,
        help="Forecast games starting within this many hours (default: 24)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually append forecasts to the ledger (default: dry-run)",
    )
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.timezone.utc)
    mode = "apply" if args.apply else "dry-run"

    # --- Dry-run: inspect what would be forecast ---
    try:
        games, _schedule_meta = run_pipeline.live_schedule(now, args.horizon_hours)
    except Exception as exc:
        print("ERROR: Failed to fetch NHL schedule: %s" % exc, file=sys.stderr)
        return 1

    existing = run_pipeline.read_jsonl(run_pipeline.LEDGER)
    done = {(int(r["game_id"]), r["model_name"]) for r in existing}

    new_games = []
    for game in games:
        if not all(
            (game["game_id"], m) in done for m in run_pipeline.MODELS
        ):
            new_games.append(game)

    print(
        "[%s] %d upcoming game(s) in next %.0fh, %d need forecasting"
        % (mode, len(games), args.horizon_hours, len(new_games))
    )
    for g in new_games:
        print(
            "  NEW: %s @ %s on %s at %s"
            % (g["away_team"], g["home_team"], g["game_date"], g["start_time_utc"])
        )

    if not args.apply:
        print(
            "Dry-run: %d game(s) would be forecast. Use --apply to write."
            % len(new_games)
        )
        return 0

    if not new_games:
        print("No new games to forecast.")
        return 0

    # --- Apply: run the full pipeline ---
    try:
        rows = run_pipeline.forecast(args.horizon_hours)
    except Exception as exc:
        print("ERROR: Forecast generation failed: %s" % exc, file=sys.stderr)
        return 1

    print("Applied: %d forecast rows appended to %s" % (len(rows), run_pipeline.LEDGER))
    for r in rows:
        print(
            "  %s @ %s | %s | home_win=%.3f | goals=%.2f-%.2f"
            % (
                r["away_team"],
                r["home_team"],
                r["model_name"],
                r["home_win_probability"],
                r["home_expected_goals"],
                r["away_expected_goals"],
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
