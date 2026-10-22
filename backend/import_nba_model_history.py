#!/usr/bin/env python3
"""Install hash-verified free SportsDataverse history into the dev-only model DB."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nba_model_data import load_release_data  # noqa: E402
from nba_model_runtime import NBA_MODEL_DB, require_dev_picks_db  # noqa: E402
from nba_model_store import import_history, open_db  # noqa: E402

DEFAULT_DATA = Path(__file__).resolve().parent / "data" / "nba-model-source"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=os.environ.get("NBA_MODEL_SOURCE_DATA", str(DEFAULT_DATA)))
    parser.add_argument("--model-db", default=NBA_MODEL_DB)
    parser.add_argument("--download", action="store_true", help="download missing pinned releases serially")
    args = parser.parse_args()
    require_dev_picks_db()
    release = load_release_data(args.data_dir, download=args.download)
    model = open_db(args.model_db)
    try:
        changed = import_history(model, [game.__dict__ for game in release.games],
                                 release.asset_hashes, release.coverage)
        count = model.execute("SELECT COUNT(*) FROM nba_model_history").fetchone()[0]
    finally:
        model.close()
    print(f"history_source_games={len(release.games)} history_rows_added={changed} total={count}")
    print(f"source_assets_sha256_verified={len(release.asset_hashes)}")
    print(f"model_db={Path(args.model_db).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
