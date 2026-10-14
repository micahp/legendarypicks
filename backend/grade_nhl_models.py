#!/usr/bin/env python3
"""Grade locked NHL model rows against official NHL landing results.

Official winner and official score are preserved separately from score targets
that omit shootout-deciding goals. Writes are idempotent and dry-run by default.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

from nhl_model_store import (DEFAULT_DB, DEFAULT_FEED, FINAL_GRACE, NHLModelError, ensure_schema,
                             grade_result, iso_utc, normalize_official_result, open_db, parse_time,
                             preview_feed, read_feed, write_standings)

STANDINGS_API = "https://api-web.nhle.com/v1/standings/now"


def fetch_standings() -> list:
    """Current NHL standings. A failure here raises, so the timer's OnFailure alert fires."""
    request = urllib.request.Request(STANDINGS_API, headers={"User-Agent": "legendarypicks/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())["standings"]

API = "https://api-web.nhle.com/v1/gamecenter/{game_id}/landing"


def fetch_landing(game_id: str) -> tuple[dict, str]:
    url = API.format(game_id=game_id)
    request = urllib.request.Request(url, headers={"User-Agent": "legendarypicks/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise NHLModelError("NHL landing request failed for %s: %s" % (game_id, exc)) from exc
    try:
        document = json.loads(body)
    except json.JSONDecodeError as exc:
        raise NHLModelError("NHL landing response is invalid JSON for %s" % game_id) from exc
    if not isinstance(document, dict):
        raise NHLModelError("NHL landing response is not an object for %s" % game_id)
    return document, hashlib.sha256(body).hexdigest()


def grade_due(con, now: dt.datetime, apply: bool, fetch=fetch_landing) -> dict:
    now = now.astimezone(dt.timezone.utc)
    candidates = con.execute("""
      SELECT DISTINCT p.game_id,p.scheduled_start_utc
      FROM nhl_game_projections p LEFT JOIN nhl_projection_grades g
        ON g.game_id=p.game_id AND g.model_key=p.model_key AND g.model_version=p.model_version
      WHERE g.game_id IS NULL ORDER BY p.scheduled_start_utc,p.game_id
    """).fetchall()
    report = {"locked_games": len(candidates), "eligible_games": 0, "graded_games": 0,
              "graded_model_rows": 0, "not_final_or_grace": 0, "already_graded": 0}
    con.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
    try:
        for candidate in candidates:
            gid = str(candidate["game_id"])
            start = parse_time(candidate["scheduled_start_utc"])
            if now - start < FINAL_GRACE:
                report["not_final_or_grace"] += 1
                continue
            report["eligible_games"] += 1
            document, digest = fetch(gid)
            result = normalize_official_result(gid, document)
            if result is None:
                report["not_final_or_grace"] += 1
                continue
            inserted = grade_result(con, gid, result, now, digest, API.format(game_id=gid)) if apply else _dry_grade_count(con, gid)
            report["graded_model_rows"] += inserted
            if inserted:
                report["graded_games"] += 1
            else:
                report["already_graded"] += 1
        if apply:
            con.commit()
        else:
            con.rollback()
    except Exception:
        con.rollback()
        raise
    return report


def _dry_grade_count(con, game_id: str) -> int:
    return con.execute("""
      SELECT COUNT(*) FROM nhl_game_projections p
      WHERE p.game_id=? AND NOT EXISTS (
        SELECT 1 FROM nhl_projection_grades g WHERE g.game_id=p.game_id
          AND g.model_key=p.model_key AND g.model_version=p.model_version)
    """, (str(game_id),)).fetchone()[0]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("NHL_MODEL_DB_PATH", DEFAULT_DB))
    parser.add_argument("--feed", default=DEFAULT_FEED, help="forecast feed the daily previews are built from")
    parser.add_argument("--now", help="timezone-qualified ISO time, for deterministic checks")
    parser.add_argument("--apply", action="store_true", help="write immutable grade rows and refresh previews")
    args = parser.parse_args(argv)
    if os.path.basename(os.path.realpath(args.db)) in {"picks.db", "picks.dev.db"}:
        raise SystemExit("refusing Legendary Picks database path: %s" % args.db)
    now = parse_time(args.now) if args.now else dt.datetime.now(dt.timezone.utc)
    preview = None
    standings = None
    try:
        con = open_db(args.db, readonly=not args.apply)
        try:
            if args.apply:
                ensure_schema(con)
            report = grade_due(con, now, args.apply)
            # Previews are rebuilt from the feed on every applied run, so the grade timer is the daily refresh.
            if args.apply:
                preview = preview_feed(con, read_feed(args.feed), now)
                standings = write_standings(con, fetch_standings(), iso_utc(now))
        finally:
            con.close()
    except NHLModelError as exc:
        print("NHL grading failed: %s" % exc, file=sys.stderr)
        return 1
    print("{mode} at {time}: {locked_games} locked games, {eligible_games} eligible, "
          "{graded_games} games / {graded_model_rows} model rows graded, "
          "{not_final_or_grace} pending, {already_graded} already graded".format(
              mode="applied" if args.apply else "dry-run", time=now.isoformat(), **report))
    if preview is not None:
        print("previews refreshed: {preview_rows} rows for upcoming games, {not_previewable} not previewable, "
              "{already_locked} already locked".format(**preview))
    if standings is not None:
        print("standings refreshed: %d teams" % standings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
