#!/usr/bin/env python3
"""Generate the homepage prop preview and store it for GET /api/home/featured (table home_prop_cache).

The preview is the slow part of the homepage payload: it reads a game log per candidate player until one
qualifies. Its pick changes only when the board or the schedule does, so this script selects it and stores it,
and the endpoint only reads the stored row.

  python3 backend/home_prop_refresh.py                    dry run: prints the pick it would store
  python3 backend/home_prop_refresh.py --apply            store it if the stored copy is missing or 7+ days old
  python3 backend/home_prop_refresh.py --apply --force    store it now

The ingest registry runs this job every seven days in dev and production.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
from contextlib import closing
from typing import List, Optional

from _core import _db
from routers import home


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="store the preview (default: dry run)")
    ap.add_argument("--force", action="store_true", help="store now even if the stored copy is recent")
    ap.add_argument("--dry-run", action="store_true", help="select without writing (used by the job runner)")
    ap.add_argument("--max-age-days", type=float, default=7.0)
    args = ap.parse_args(argv)

    now = home._now(None)
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        stored = home.prop_cache_read(con)
        if stored and not args.force:
            made = home._parse_ts(stored[0])
            if made is not None and now - made < dt.timedelta(days=args.max_age_days):
                print(f"stored preview from {stored[0]} is under {args.max_age_days:g} days old; nothing to do")
                return 0
        fp = home.featured_prop(con, now)
        prop = fp["prop"]
        print(json.dumps({"player": prop["player"] if prop else None,
                          "market": prop["market"] if prop else None,
                          "line": prop["line"] if prop else None,
                          "reason": fp["reason"]}, indent=2))
        if not args.apply or args.dry_run:
            print("dry run: nothing stored")
            return 0
        home.prop_cache_write(con, now, fp)
        print(f"stored at {home._iso(now)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
