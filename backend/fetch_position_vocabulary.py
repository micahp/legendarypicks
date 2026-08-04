#!/usr/bin/env python3
"""Fetch each league's position vocabulary from the publisher that defines it.

`C/vocabulary[position]` failed for NBA, NFL and NHL on the rule "a one-character
code is coarse, a two-character code is granular, and both present means two
ingests are fighting". That is a string-length proxy for a semantic property, and
it is wrong in three of four leagues: hockey's `C/D/G/LW/RW` is a single
vocabulary, and football's `S/G/C/P` sit in the same vocabulary as `WR/LB/CB`.
The gate was red on leagues that were fine.

Rather than hand-write the right list -- which is the same mistake one layer down,
a question answered from memory -- read it from ESPN, which publishes it:

    /v2/sports/{sport}/leagues/{league}/positions

Every position carries `abbreviation`, `leaf`, and a `parent` ref. `leaf` IS the
coarse/granular distinction, published rather than inferred, and `parent` says
which coarse bucket a granular code rolls up into. That makes the real question
answerable: two vocabularies are in play only when a position AND one of its own
descendants both appear -- NBA holding `G` and `PG` together, say. Codes that are
merely different lengths are not evidence of anything.

Output is committed, not fetched at audit time: the gate must run offline and a
vocabulary changes about never. Provenance (URL, fetch date, counts) is written
into the artifact so the next person can tell what was asked and re-ask it.

    ./venv/bin/python fetch_position_vocabulary.py --out data/position-vocabulary.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import espn_client as espn


# The `positions` collection lives on sports.core, which addresses leagues by
# sport rather than by the site API's path, so the mapping is spelled out here.
_SPORT = {"nhl": "hockey", "nba": "basketball", "nfl": "football", "mlb": "baseball"}

_INDEX = ("https://sports.core.api.espn.com/v2/sports/{sport}"
          "/leagues/{league}/positions?limit=200")


def _position_id(ref: str) -> str:
    """`.../positions/20?lang=en&region=us` -> `20`."""
    return ref.split("/positions/")[-1].split("?")[0]


def fetch_league(league: str) -> dict:
    sport = _SPORT[league]
    index = espn._get(_INDEX.format(sport=sport, league=league), ttl=86400)
    positions = {}
    for item in index.get("items", []):
        ref = item.get("$ref")
        if not ref:
            continue
        # The refs come back as http; ask over https so this is not the one
        # request in the repo that goes out in the clear.
        node = espn._get(ref.replace("http://", "https://"), ttl=86400)
        abbrev = node.get("abbreviation")
        if not abbrev:
            continue          # a few ids are placeholders with no code
        parent = node.get("parent", {}).get("$ref")
        positions[abbrev] = {
            "id": str(node.get("id")),
            "name": node.get("name") or node.get("displayName"),
            "leaf": bool(node.get("leaf")),
            "parent_id": _position_id(parent) if parent else None,
        }
    return positions


def ancestry(positions: dict) -> dict:
    """{abbreviation: set of ancestor abbreviations}, resolved through parent ids."""
    by_id = {p["id"]: abbrev for abbrev, p in positions.items()}
    out = {}
    for abbrev, p in positions.items():
        chain, cursor, guard = [], p["parent_id"], 0
        while cursor and guard < 20:      # guard: a cycle upstream must not hang us
            parent_abbrev = by_id.get(cursor)
            if not parent_abbrev:
                break
            chain.append(parent_abbrev)
            cursor = positions[parent_abbrev]["parent_id"]
            guard += 1
        out[abbrev] = chain
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "position-vocabulary.json"))
    ap.add_argument("--leagues", nargs="*", default=sorted(_SPORT))
    args = ap.parse_args()

    # One-time fetch of ~140 refs. Paced, and cached to disk so a re-run is free.
    espn.set_min_interval(float(os.environ.get("LP_ESPN_MIN_INTERVAL", "1.0")))
    espn.set_disk_cache(os.environ.get("LP_ESPN_CACHE_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "espn-cache"), ttl=86400 * 7)

    # Resume rather than restart. `sports.core` refused partway through the first
    # run after ~119 requests at 1s spacing -- this host does trip where
    # site.web.api did not -- and the leagues already fetched should not be
    # thrown away because a later one was refused. Between the disk cache and
    # this merge, a re-run costs only the leagues still missing.
    artifact = {"_provenance": {}, "leagues": {}}
    if os.path.exists(args.out):
        try:
            with open(args.out) as f:
                artifact = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    artifact.setdefault("leagues", {})

    def save():
        artifact["_provenance"] = {
            "source": _INDEX,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "note": "abbreviation/leaf/parent as published by ESPN; not hand-authored",
            "leagues": sorted(artifact["leagues"]),
        }
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        tmp = args.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(artifact, f, indent=1, sort_keys=True)
        os.replace(tmp, args.out)

    missing = []
    for league in args.leagues:
        try:
            positions = fetch_league(league)
        except Exception as exc:
            print(f"{league}: NOT FETCHED -- {exc}")
            missing.append(league)
            continue
        artifact["leagues"][league] = {
            "positions": positions,
            "ancestry": ancestry(positions),
        }
        leaves = sum(1 for p in positions.values() if p["leaf"])
        print(f"{league}: {len(positions)} positions ({leaves} leaf, "
              f"{len(positions) - leaves} grouping)")
        save()          # after every league, so a refusal costs one league

    save()
    print("wrote", args.out, "| leagues:", sorted(artifact["leagues"]))
    if missing:
        print("STILL MISSING:", missing, "-- re-run; cached leagues cost nothing")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
