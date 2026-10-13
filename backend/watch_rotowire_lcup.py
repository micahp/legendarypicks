#!/usr/bin/env python3
"""Poll the RotoWire picks relay until Leagues Cup props appear, then ingest them.

The relay posts soccer close to kickoff: measured 2026-08-25, its whole soccer
board was 21 athletes across fixtures 0-3 days out, while the four Leagues Cup
fixtures (10-34h out) were absent. The 08-19 archive carried 370 MLS rows for
games THAT DAY. So absence now is not absence tonight.

Verified the same day, in RotoWire's own bundle (picks-core.js):
    fetch(`/picks/api/lines.php`)
no parameters and no auth header, so the anonymous payload is the whole board
and there is nothing else to ask for. Polling is the only lever we have.

Writes a line per check to the log; ingests exactly once per new fixture found.
"""
import datetime as dt
import json
import os
import sqlite3
import sys
import time

import ingest_rotowire_archive as archive
import ingest_rotowire_props as I

INTERVAL = 900  # 15 min: light on a free publisher, ~4/hour.
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

CLUBS = ("Toluca", "Monterrey", "Chicago Fire", "Club Leon", "Club León",
         "Real Salt Lake", "Club America", "Club América", "América",
         "Columbus Crew", "Austin FC")


def check():
    """Rows that PASS the cross-club guard, not everything `parse` returns.

    `parse` yields every Soccer row on the board -- 72 of them today, all La Liga
    and Ligue 1. The Leagues Cup test (`_fixture_is_known`: one MLS club against
    one Liga MX club) runs later, inside `ingest`. Gating this watcher on raw
    parsed rows fired on the first check, ingested zero, and exited reporting
    success. The guard has to run HERE or the loop is measuring the wrong thing.
    """
    payload, _ = archive.fetch()
    raw = json.dumps(payload, ensure_ascii=False)
    present = sorted({c for c in CLUBS if c in raw})
    parsed, meta = I.parse(payload, "lcup")

    con = I.connect() if hasattr(I, "connect") else sqlite3.connect(DB)
    try:
        vocabulary = I.team_vocabulary(con, "lcup")
    finally:
        con.close()
    rows = [r for r in parsed if I._fixture_is_known("lcup", r, vocabulary)]
    fixtures = sorted({(r["date"], r["home"], r["away"]) for r in rows})
    return present, rows, fixtures, meta


def main():
    while True:
        stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        try:
            present, rows, fixtures, meta = check()
        except Exception as exc:                       # noqa: BLE001
            print("%s  FETCH FAILED %s: %s" % (stamp, type(exc).__name__, exc), flush=True)
            time.sleep(INTERVAL)
            continue

        if rows:
            print("%s  LEAGUES CUP PROPS FOUND: %d rows across %d fixtures"
                  % (stamp, len(rows), len(fixtures)), flush=True)
            for f in fixtures:
                print("     %s  %s vs %s" % f, flush=True)
            result = I.ingest(rows, "lcup", dry_run=False)
            print("%s  INGESTED: %s" % (stamp, result), flush=True)
            return 0

        print("%s  no lcup yet | clubs seen in payload: %s | soccer props: %d"
              % (stamp, present or "none", meta["counts"].get("sport_props", 0)), flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
