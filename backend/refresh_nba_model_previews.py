#!/usr/bin/env python3
"""Refresh display-only upcoming forecasts from dev schedule and pregame history."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nba_model_runtime import NBA_MODEL_DB, refresh_previews, require_dev_picks_db  # noqa: E402


def main() -> int:
    require_dev_picks_db()
    result = refresh_previews(model_db_path=NBA_MODEL_DB)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
