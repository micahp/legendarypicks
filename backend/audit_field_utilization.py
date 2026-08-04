#!/usr/bin/env python3
"""How much of what each endpoint publishes do we actually read?

Every headline data gap found on 2026-08-04 was the same thing, five times:

  | recorded as | actually |
  |---|---|
  | NFL "no such column: rush_td, rec_td" | in `stats_player_reg.parquet`, 143 columns published, 19 read |
  | NHL "a defenceman has nowhere to record a block" | `gamecenter/{id}/boxscore` publishes blockedShots and hits per game |
  | NHL "no goalie source at all" | `goalie/summary`, league-wide, one request |
  | MLB "no ERA anywhere in this database" | `statsapi.mlb.com`, one request, the whole line |
  | NBA leaderboard three years stale | bulk `byathlete`, 578 athletes in 6 pages |

Not one was a missing publisher. Every one was a publisher we were ALREADY
calling, whose payload we were reading a fraction of, or an adjacent endpoint of
that same publisher nobody asked. The data arrived on every run and was dropped
before anyone looked.

That failure is invisible to every other check we have. Row counts were healthy.
The API returned 200. Gates were green. A whitelist that drops 124 of 143 columns
looks exactly like a whitelist that drops 0.

So this measures the one number that would have shown it: **fields published vs
fields read, per endpoint.** Low utilisation is not itself a defect -- these are
bulk requests where unread fields cost nothing -- so this is a DISCOVERY metric,
not an efficiency one. The unread field NAMES are the point. That is the list
every gap above was hiding in.

    ./venv/bin/python audit_field_utilization.py
    ./venv/bin/python audit_field_utilization.py --league nhl
    ./venv/bin/python audit_field_utilization.py --json

Adding a league: add its endpoints to `ENDPOINTS` at the same time as its
`MANIFEST` entry. An endpoint we read and never registered here is a payload
nobody has ever counted.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# name -> what we ask for, and where the code says which fields it keeps.
#
#   url         a SAMPLE request. One per endpoint; the shape is what matters.
#   sample      dotted path into the response to reach one representative record
#   reads       (module, attribute) pairs holding the keys that module keeps.
#               Listed rather than inferred: a whitelist is the thing under
#               audit, so it has to be read from the source, not guessed at.
ENDPOINTS = {
    "nhl": {
        "player game-log (skater + goalie)": {
            "url": "https://api-web.nhle.com/v1/player/8478402/game-log/20252026/2",
            "sample": "gameLog.0",
            "reads": [("ingest_nhl_logs", "STAT_KEYS"),
                      ("ingest_nhl_logs", "GOALIE_STAT_KEYS")],
        },
        "gamecenter boxscore (skater)": {
            "url": "https://api-web.nhle.com/v1/gamecenter/2025020001/boxscore",
            "sample": "playerByGameStats.homeTeam.forwards.0",
            "reads": [("backfill_nhl_boxscore_stats", "SKATER_KEYS")],
        },
        "gamecenter boxscore (goalie)": {
            "url": "https://api-web.nhle.com/v1/gamecenter/2025020001/boxscore",
            "sample": "playerByGameStats.homeTeam.goalies.0",
            "reads": [("backfill_nhl_boxscore_stats", "GOALIE_KEYS")],
        },
    },
}


def _dig(doc, path):
    """`a.0.b` -> doc['a'][0]['b'], or None if the path does not exist."""
    cursor = doc
    for part in path.split("."):
        if cursor is None:
            return None
        if part.isdigit():
            if not isinstance(cursor, list) or len(cursor) <= int(part):
                return None
            cursor = cursor[int(part)]
        else:
            if not isinstance(cursor, dict):
                return None
            cursor = cursor.get(part)
    return cursor


def _read_keys(pairs):
    keys = set()
    for module_name, attr in pairs:
        module = importlib.import_module(module_name)
        keys |= set(getattr(module, attr))
    return keys


def audit(leagues=None):
    import espn_client as paced
    paced.set_host_budget(0)          # one request per endpoint; no batch here
    paced.set_min_interval(0.5)
    paced.set_disk_cache(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "espn-cache"),
        ttl=86400)

    results = []
    for league, endpoints in sorted(ENDPOINTS.items()):
        if leagues and league not in leagues:
            continue
        for name, spec in endpoints.items():
            try:
                doc = paced._get(spec["url"], ttl=86400)
                record = _dig(doc, spec["sample"])
            except Exception as exc:
                results.append({"league": league, "endpoint": name,
                                "error": str(exc)[:120]})
                continue
            if not isinstance(record, dict):
                results.append({"league": league, "endpoint": name,
                                "error": f"sample path {spec['sample']!r} is not a record"})
                continue
            published = set(record)
            read = _read_keys(spec["reads"]) & published
            results.append({
                "league": league,
                "endpoint": name,
                "published": len(published),
                "read": len(read),
                "unread": sorted(published - read),
            })
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", action="append", dest="leagues")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    results = audit(args.leagues)
    if args.json:
        print(json.dumps(results, indent=1))
        return 0

    errors = 0
    for r in results:
        if r.get("error"):
            print(f"{r['league']:4s} {r['endpoint']:34s} ERROR {r['error']}")
            errors += 1
            continue
        pct = 100.0 * r["read"] / r["published"] if r["published"] else 0.0
        print(f"{r['league']:4s} {r['endpoint']:34s} "
              f"{r['read']:3d}/{r['published']:3d} read  ({pct:.0f}%)")
        if r["unread"]:
            # The whole point of the report. Every 2026-08-04 gap was a name on
            # a line like this one, on an endpoint already being called.
            print(f"       unread: {', '.join(r['unread'])}")
    print("\nLow utilisation is not a defect -- these are bulk requests and the "
          "extra fields\ncost nothing. Read the UNREAD NAMES: that is where a "
          "'we don't have that' hides.")
    return errors


if __name__ == "__main__":
    raise SystemExit(main())
