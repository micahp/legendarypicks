#!/usr/bin/env python3
"""Intra-day change-capture for the RotoWire picks relay.

    ingest_rotowire_snapshot.py              fetch; write only if the payload changed
    ingest_rotowire_snapshot.py --dry-run    fetch, report, write nothing
    ingest_rotowire_snapshot.py --report     show today's snapshots so far

## Why

The relay is a pre-lock pick'em board: books post lines near kickoff, so the
payload moves all day. The daily midnight archive (ingest_rotowire_archive.py)
freezes one moment — 00:05 local — and misses everything posted after. Measured
2026-08-29: PrizePicks had one MLS fixture priced on the live board while the
00:06 archive carried zero, so the daily snapshot alone would have missed the
return of MLS props entirely.

This fetches the same single endpoint and writes an additional snapshot **only
when the payload differs from the last one stored for the day** — compared by
SHA-256 of the raw bytes. Unchanged polls cost one request and write nothing,
so the request budget stays bounded (one poll per timer tick, no retries), and
a quiet day produces exactly one file: the archive's.

## Cost

One request per tick to www.rotowire.com (not an ESPN host, no ESPN budget
bearing). At the props timer's 30-minute cadence that is 48 requests/day worst
case; on a normal day most polls are byte-identical no-ops. Storage is a few
hundred KB per distinct payload, gzipped.

## What this is NOT

It does not write `props` or any league pipeline. It is the same pure archive
contract as the midnight job: parse is a decision we can revise, the capture
is not.
"""
import argparse
import datetime as dt
import glob
import gzip
import hashlib
import json
import os
import sys

from ingest_rotowire_archive import API, UA, fetch, shape

SNAPSHOT_DIR = os.environ.get(
    "LP_ROTOWIRE_ARCHIVE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "rotowire-archive"))


def content_digest(payload):
    """SHA-256 over the payload's CONTENT, not its raw bytes.

    The relay re-stamps `lineTime` on lines it re-publishes without changing
    anything a reader cares about (measured 2026-08-29: 10 lines re-stamped
    within two minutes, same lines, same odds). A raw-byte hash treats every
    re-stamp as a change and would store dozens of identical-content snapshots
    a day. This digest covers market catalogue, entities, every prop's
    projection, each book's (line, over, under), and the hit-rate history —
    and nothing that re-stamps without meaning.
    """
    h = hashlib.sha256()
    for m in sorted(payload.get("markets", []), key=lambda x: x.get("marketID", 0)):
        h.update(f"M{m.get('marketID')}:{m.get('sport')}:{m.get('category')}:{m.get('marketName')}".encode())
    for e in sorted(payload.get("entities", []), key=lambda x: x.get("entityID", 0)):
        h.update(f"E{e.get('entityID')}:{e.get('name')}:{e.get('team')}:{e.get('eventID')}".encode())
    for p in sorted(payload.get("props", []), key=lambda x: x.get("propID", "")):
        lines = sorted((l.get("book"), l.get("line"), l.get("over"), l.get("under"))
                       for l in p.get("lines", []))
        h.update(f"P{p.get('propID')}:{p.get('projection')}:{lines}".encode())
        for hr in p.get("hitRates", []):
            h.update(f"H{hr.get('line')}:{hr.get('season')}:{hr.get('prevSeason')}:"
                     f"{hr.get('vsOpponent')}:{hr.get('recent')}".encode())
    return h.hexdigest()


def _day_prefix(day=None):
    day = day or dt.datetime.now(dt.timezone.utc).date()
    return os.path.join(SNAPSHOT_DIR, f"rotowire-{day.isoformat()}")


def latest_hash(day=None):
    """Content digest of the most recent capture stored today.

    Sorted by mtime, not filename: alphabetical order sorts the daily
    `rotowire-<day>.json.gz` AFTER same-day snapshots ('-' < '.'), which would
    make the midnight archive look like the newest capture forever.
    """
    candidates = glob.glob(_day_prefix(day) + "*.json.gz")
    if not candidates:
        return None
    newest = max(candidates, key=os.path.getmtime)
    with gzip.open(newest, "rb") as fh:
        return content_digest(json.loads(fh.read().decode()))


def write_snapshot(raw, payload_hash, day=None):
    """Store a distinct payload under its own timestamped name."""
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    ts = dt.datetime.now(dt.timezone.utc).strftime("%H%M%S")
    path = f"{_day_prefix(day)}-snap{ts}.json.gz"
    tmp = path + ".partial"
    with gzip.open(tmp, "wb") as fh:
        fh.write(raw)
    os.replace(tmp, path)
    return path


def report(day=None):
    files = sorted(glob.glob(_day_prefix(day) + "*.json.gz"))
    if not files:
        print("no snapshots for today yet")
        return 2
    print(f"{len(files)} capture(s) today:")
    for f in files:
        tag = "snap" if "-snap" in f else "daily"
        print(f"  {f}  {os.path.getsize(f) / 1e3:.0f} KB  ({tag})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch, compare and report, write nothing")
    parser.add_argument("--report", action="store_true",
                        help="list today's captures without fetching")
    args = parser.parse_args(argv)

    if args.report:
        return report()

    prev = latest_hash()
    print(f"[rotowire-snap] 1 request to www.rotowire.com (not an ESPN host)")
    try:
        payload, raw = fetch()
    except Exception as exc:
        print(f"[rotowire-snap] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    digest = content_digest(payload)
    facts = shape(payload)
    changed = digest != prev
    print(f"[rotowire-snap] {facts['props']:,} props, {facts['events']} events, "
          f"{len(raw) / 1e6:.1f} MB, content {digest[:12]}")
    print(f"[rotowire-snap] vs last capture: {'CHANGED' if changed else 'identical'}")
    if facts["props_by_sport"].get("Soccer"):
        print(f"[rotowire-snap] soccer props: {facts['props_by_sport']['Soccer']}")

    if not changed:
        return 0
    if not facts["props"]:
        print("[rotowire-snap] the relay carried no props; nothing captured")
        return 0
    if args.dry_run:
        print("[rotowire-snap] dry run, nothing written")
        return 0

    path = write_snapshot(raw, digest)
    print(f"[rotowire-snap] wrote {path} ({os.path.getsize(path) / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
