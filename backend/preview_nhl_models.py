#!/usr/bin/env python3
"""Write unlocked NHL projections as display-only previews for the Model tab.

Previews come from the research feed for games still more than the T-90 lead before puck drop.
They are never graded and never written to the lock tables. Each run replaces the previews of the
feed's model version. Dry-run by default; --apply writes the standalone NHL model database.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

from nhl_model_store import (DEFAULT_DB, DEFAULT_FEED, NHLModelError, ensure_schema,
                             open_db, parse_time, preview_feed, read_feed)


def _assert_standalone(path: str) -> None:
    if os.path.basename(os.path.realpath(path)) in {"picks.db", "picks.dev.db"}:
        raise SystemExit("refusing Legendary Picks database path: %s" % path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feed", default=DEFAULT_FEED)
    parser.add_argument("--db", default=os.environ.get("NHL_MODEL_DB_PATH", DEFAULT_DB))
    parser.add_argument("--now", help="timezone-qualified ISO time, for deterministic checks")
    parser.add_argument("--apply", action="store_true", help="replace preview rows in the standalone database")
    args = parser.parse_args(argv)
    _assert_standalone(args.db)
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    try:
        feed = read_feed(args.feed)
        # A dry run validates the feed against an empty database, so it cannot see existing locks.
        con = open_db(args.db if args.apply else ":memory:")
        try:
            ensure_schema(con)
            report = preview_feed(con, feed, now)
        finally:
            con.close()
    except NHLModelError as exc:
        print("NHL preview failed: %s" % exc, file=sys.stderr)
        return 1
    mode = "applied" if args.apply else "dry-run"
    print("{mode} at {time}: {feed_games} feed games, {preview_rows} preview rows, "
          "{not_previewable} not previewable (inside the lock lead or started), "
          "{already_locked} already locked".format(mode=mode, time=now.isoformat(), **report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
