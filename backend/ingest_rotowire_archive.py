#!/usr/bin/env python3
"""Archive the whole RotoWire picks relay once a day, for every sport it carries.

    ingest_rotowire_archive.py              archive today
    ingest_rotowire_archive.py --dry-run    fetch, report the shape, write nothing
    ingest_rotowire_archive.py --report     summarise what is already archived

## Why the WHOLE payload, and why for leagues we do not cover

The relay is one request and it carries far more than MLS. Measured 2026-08-19:

    sports   NFL MLB NBA NHL CFB CBB Soccer WNBA CS2 DOTA2 Valorant COD
    markets  NFL 33, MLB 22, WNBA 18, CFB 11, Soccer 8, NBA 4, PGA 3,
             NHL 3, MMA 2, CS2 2, Valorant 1
    payload  5,255 props, 97 events, 1,425 entities, 107 markets, 5.6 MB

Every prop carries `projection`, `lines` AND `hitRates`. **The hit rates are prop history,
and prop history is the one asset that cannot be backfilled.** If we decide in November to
cover WNBA or Valorant, the only way to have their 2026 history is to have been keeping it
since August. A line we did not store on the day is gone: the board moves, the market
settles, and nobody republishes yesterday's price.

So this stores the payload as received, whole and unparsed, and does not filter to the
leagues we currently serve. Parsing is a decision we can revise; the archive is not.

## What this is NOT

It does not write `props`, `prop_games` or `players`, and it does not touch any league
pipeline. It is an archive. `monitor_rotowire_soccer.py` remains the thing that answers
"does this source carry MLS", from its own probe series.

## Cost

One request a day to `www.rotowire.com`, which is not an ESPN host and has no bearing on
the ESPN budget. About 5.6 MB raw, roughly 600 KB gzipped, so on the order of 220 MB a year.
"""
import argparse
import datetime as dt
import gzip
import json
import os
import sys
import urllib.request

API = "https://www.rotowire.com/picks/api/lines.php"
ARCHIVE_DIR = os.environ.get(
    "LP_ROTOWIRE_ARCHIVE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rotowire-archive"))
UA = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}


def fetch():
    """The relay payload as parsed JSON, plus the raw bytes we received."""
    request = urllib.request.Request(API, headers=UA)
    with urllib.request.urlopen(request, timeout=90) as response:
        raw = response.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode()), raw


def shape(payload):
    """What this payload contains, by sport. Printed on every run.

    A silent archive is one nobody can size later, and the counts are how we notice the
    day the relay changes shape or a sport disappears.
    """
    markets = {m["marketID"]: m for m in payload.get("markets", [])}
    by_sport = {}
    for prop in payload.get("props", []):
        market = markets.get(prop.get("marketID")) or {}
        sport = market.get("sport") or "unknown"
        by_sport[sport] = by_sport.get(sport, 0) + 1
    return {
        "events": len(payload.get("events", [])),
        "entities": len(payload.get("entities", [])),
        "markets": len(markets),
        "props": sum(by_sport.values()),
        "props_by_sport": dict(sorted(by_sport.items(), key=lambda kv: -kv[1])),
    }


def archive_path(day=None):
    day = day or dt.datetime.now(dt.timezone.utc).date()
    return os.path.join(ARCHIVE_DIR, f"rotowire-{day.isoformat()}.json.gz")


def write(raw, day=None):
    """Store the payload as received. Never reformatted, never filtered.

    Written to a temp file and renamed, so a run interrupted halfway cannot leave a
    truncated archive that looks like a complete one.
    """
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    path = archive_path(day)
    tmp = path + ".partial"
    with gzip.open(tmp, "wb") as handle:
        handle.write(raw)
    os.replace(tmp, path)
    return path


def report():
    if not os.path.isdir(ARCHIVE_DIR):
        print(f"no archive at {ARCHIVE_DIR}. Nothing has run yet.")
        return 2
    files = sorted(f for f in os.listdir(ARCHIVE_DIR) if f.endswith(".json.gz"))
    if not files:
        print(f"{ARCHIVE_DIR} exists and is empty.")
        return 2
    total = sum(os.path.getsize(os.path.join(ARCHIVE_DIR, f)) for f in files)
    print(f"{len(files)} day(s) archived, {total / 1e6:.1f} MB, "
          f"{files[0][9:19]} to {files[-1][9:19]}")
    for name in files[-5:]:
        size = os.path.getsize(os.path.join(ARCHIVE_DIR, name)) / 1e6
        print(f"  {name}  {size:.2f} MB")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch and report the shape, write nothing")
    parser.add_argument("--report", action="store_true",
                        help="summarise the existing archive without fetching")
    args = parser.parse_args(argv)

    if args.report:
        return report()

    print("[rotowire] 1 request to www.rotowire.com (not an ESPN host)")
    try:
        payload, raw = fetch()
    except Exception as exc:
        # Loud, and a non-zero exit, so a failed day is visible in the timer rather
        # than becoming a silent hole in the history months from now.
        print(f"[rotowire] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    facts = shape(payload)
    print(f"[rotowire] {facts['props']:,} props, {facts['events']} events, "
          f"{facts['entities']:,} entities, {facts['markets']} markets, "
          f"{len(raw) / 1e6:.1f} MB")
    print("[rotowire] props by sport: " + ", ".join(
        f"{sport}={n}" for sport, n in facts["props_by_sport"].items()))

    if not facts["props"]:
        # An empty board is a real state (everything has locked), but it must not
        # overwrite a good archive for the same day with nothing.
        print("[rotowire] the relay carried no props; nothing archived")
        return 0
    if args.dry_run:
        print("[rotowire] dry run, nothing written")
        return 0

    path = write(raw)
    print(f"[rotowire] wrote {path} ({os.path.getsize(path) / 1e6:.2f} MB gzipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
