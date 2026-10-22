#!/usr/bin/env python3
"""Lock named NBA games from their stored pregame preview when the T-90 window was missed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nba_model_runtime import NBA_MODEL_DB, require_dev_picks_db  # noqa: E402
from nba_model_store import lock_previews_late, open_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", action="append", required=True, help="NBA game id; repeat for several")
    args = parser.parse_args()
    require_dev_picks_db()
    model = open_db(NBA_MODEL_DB)
    try:
        print(json.dumps(lock_previews_late(model, args.game_id), sort_keys=True))
    finally:
        model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
