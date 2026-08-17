#!/usr/bin/env python3
"""Record what the RotoWire picks relay carries for soccer, every time it is asked.

WHY THIS EXISTS. On 2026-08-16 the relay was read once and reported as "PrizePicks carries
no MLS". The read happened at 04:19Z. Both of that day's MLS fixtures had kicked off at
00:30Z and 02:30Z, and a pick'em board is pulled at lock — so there was no MLS board to be
absent, and the next slate was 67 hours away. The measurement was taken at the one moment
the answer was guaranteed empty, and a timing artifact became a recorded fact about a
publisher.

That is the failure this file prevents. A single read cannot answer "does this source carry
MLS"; only reads taken in the PRE-LOCK window can, and knowing which window you were in
requires a record. So every read is stored with its timestamp, and the question is answered
from the series rather than from whichever read someone happened to run.

The relay is one request (~2 MB) and carries 10 books. PrizePicks soccer prices seven of
the markets we cannot otherwise get for MLS — passes attempted, saves, shots, shots on
target, tackles, clearances, crosses. Bovada and Kambi supply only goals and assists.

Writes to `source_probe_log`, which is additive and belongs to no league pipeline. It never
writes props and never touches `players`.

Usage:
  python3 monitor_rotowire_soccer.py            # probe once, record, print the series
  python3 monitor_rotowire_soccer.py --history  # print the series without probing
"""
import argparse
import collections
import datetime as dt
import json
import os
import sqlite3
import sys
import urllib.request

API = "https://www.rotowire.com/picks/api/lines.php"
SOURCE = "rotowire_picks_relay"
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "Chrome/131 Safari/537.36"}

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# The MLS club vocabulary, matched against the relay's own team strings. Deliberately the
# full club names rather than codes: this relay is not in our team vocabulary and never
# will be, so the probe asks "is any MLS club named here" rather than pretending to join.
_MLS_CLUBS = (
    "Atlanta United", "Austin FC", "Charlotte FC", "Chicago Fire", "FC Cincinnati",
    "Colorado Rapids", "Columbus Crew", "FC Dallas", "D.C. United", "DC United",
    "Houston Dynamo", "Inter Miami", "LA Galaxy", "Los Angeles Galaxy", "Los Angeles FC",
    "Minnesota United", "CF Montr", "Nashville SC", "New England Revolution",
    "New York City FC", "New York Red Bulls", "NY Red Bulls", "Orlando City",
    "Philadelphia Union", "Portland Timbers", "Real Salt Lake", "San Diego FC",
    "San Jose Earthquakes", "Seattle Sounders", "Sporting Kansas City",
    "St. Louis City", "Toronto FC", "Vancouver Whitecaps",
)


def ensure_table(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS source_probe_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          probed_at TEXT NOT NULL,
          sport TEXT NOT NULL,
          fixtures INTEGER NOT NULL,
          offers INTEGER NOT NULL,
          mls_fixtures INTEGER NOT NULL,
          markets_json TEXT NOT NULL,
          fixtures_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_source_probe_log_read
          ON source_probe_log(source, sport, probed_at);
    """)


def probe():
    """One read of the relay, reduced to what soccer it was carrying."""
    request = urllib.request.Request(API, headers=_HDRS)
    with urllib.request.urlopen(request, timeout=90) as response:
        board = json.load(response)

    markets = {str(m.get("marketID")): m for m in board.get("markets") or []}
    entities = {str(e.get("entityID")): e for e in board.get("entities") or []}
    events = {str(e.get("eventID")): e for e in board.get("events") or []}

    fixtures = {}
    market_counts = collections.Counter()
    offers = 0
    for prop in board.get("props") or []:
        entity_ids = prop.get("entities") or []
        entity = entities.get(str(entity_ids[0])) if len(entity_ids) == 1 else None
        if not entity or str(entity.get("sport") or "").lower() != "soccer":
            continue
        event = events.get(str(entity.get("eventID")))
        if not event:
            continue
        label = (markets.get(str(prop.get("marketID"))) or {}).get("marketName") or "?"
        # Offers live in lines[]; a flat read of props[].book misses every active one.
        for line in (prop.get("lines") or [prop]):
            if str((line or {}).get("book") or "").lower() != "prizepicks":
                continue
            offers += 1
            market_counts[label] += 1
            name = "{} v {}".format(event.get("homeTeam"), event.get("awayTeam"))
            fixtures[name] = fixtures.get(name, 0) + 1

    mls = [name for name in fixtures if any(club in name for club in _MLS_CLUBS)]
    return {
        "sport": "soccer",
        "fixtures": len(fixtures),
        "offers": offers,
        "mls_fixtures": len(mls),
        "markets": dict(market_counts),
        "fixture_names": fixtures,
        "mls_names": mls,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--history", action="store_true",
                        help="print the recorded series without probing")
    args = parser.parse_args(argv)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ensure_table(con)

    if not args.history:
        try:
            reading = probe()
        except Exception as exc:  # noqa: BLE001
            print("PROBE FAILED: {}".format(exc))
            print("  Not recorded. A failed read is not evidence of an empty board — the "
                  "whole point of this log is that the two must never look alike.")
            return 2
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        con.execute(
            "INSERT INTO source_probe_log(source,probed_at,sport,fixtures,offers,"
            "mls_fixtures,markets_json,fixtures_json) VALUES(?,?,?,?,?,?,?,?)",
            (SOURCE, now, reading["sport"], reading["fixtures"], reading["offers"],
             reading["mls_fixtures"], json.dumps(reading["markets"], sort_keys=True),
             json.dumps(reading["fixture_names"], sort_keys=True)))
        con.commit()
        print("probe {}: soccer {} fixtures, {} PrizePicks offers, {} MLS".format(
            now[:16], reading["fixtures"], reading["offers"], reading["mls_fixtures"]))
        for name, count in sorted(reading["fixture_names"].items()):
            print("    {:44s} {} offers{}".format(
                name, count, "   <-- MLS" if name in reading["mls_names"] else ""))
        if reading["markets"]:
            print("  markets: " + ", ".join(
                "{} {}".format(v, k) for k, v in sorted(reading["markets"].items())))

    rows = con.execute(
        "SELECT * FROM source_probe_log WHERE source=? ORDER BY probed_at", (SOURCE,)
    ).fetchall()
    print("\n--- series ({} reads) ---".format(len(rows)))
    for row in rows:
        print("  {}  fixtures={:2d}  offers={:3d}  MLS={}".format(
            row["probed_at"][:16], row["fixtures"], row["offers"], row["mls_fixtures"]))
    ever = sum(row["mls_fixtures"] for row in rows)
    print("  MLS fixtures seen across every read so far: {}".format(ever))
    if not ever:
        print("  NOT YET AN ANSWER. A pick'em board is pulled at lock, so a read taken "
              "after kickoff proves nothing. This is only evidence once a read lands in "
              "the pre-lock window of an MLS slate.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
