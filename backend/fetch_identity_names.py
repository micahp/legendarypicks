#!/usr/bin/env python3
"""Fetch each publisher's own id -> name map into a committed artifact.

`players` carries one external id per publisher (`mlbam_id`, `espn_id`, ...) and
everything joins on them. Nothing has ever asserted that those ids point at the
person whose name sits on the row. On 2026-08-04 that turned out to matter:
**224 MLB rows carried another player's `mlbam_id`.**

    id=26571 row='Mason Miller'  mlbam=702616  MLB publishes 'Jackson Holliday'
    id=26573 row='Yennier Cano'  mlbam=701538  MLB publishes 'Jackson Merrill'

That is not a cosmetic defect. `dedupe_mlb.py` documents itself as
"identity-safe: only merges rows that share the SAME mlbam_id (= provably the
same person)". With these ids, 124 of 317 duplicate groups were two *different*
people, and a merge would have repointed 408,610 prop rows and 26,491 game logs
onto the wrong players before deleting the originals. A UNIQUE constraint on
`player_stats` aborted the run by luck, not by design.

The corruption predates every backup on disk (present 2026-06-15, the oldest),
so the writing script could not be identified. That is exactly when a gate beats
a root cause: this check fails on the *state* whatever produced it, so a repair
is provable and a regression is loud.

Written as a committed artifact rather than a live fetch for the same reason as
`fetch_position_vocabulary.py`: the audit must run offline, and an identity map
read at audit time could not be reviewed in a diff.

Only MLB is populated today. `statsapi.mlb.com` publishes the whole season
roster with ids in one request. Leagues with no entry are reported UNVERIFIED by
the audit -- never PASS, which would be a guess wearing a green badge.

Usage:
  cd backend && venv/bin/python fetch_identity_names.py [--season 2026]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import paced_http

ARTIFACT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "published-identity-names.json")

PEOPLE_URL = "https://statsapi.mlb.com/api/v1/sports/1/players?season={season}"
HDR = {"User-Agent": "legendarypicks/1.0"}

# host_budget=0: the 100-per-host ceiling is a measured ESPN figure and no
# refusal has ever been observed from statsapi.mlb.com. Same call this repo
# already makes in ingest_mlb_spine_identity.py.
_FETCH = paced_http.Fetcher(min_interval=0.5, retry_waits=(5.0, 20.0, 60.0),
                            headers=HDR, timeout=30, host_budget=0)


class IdentityFetchError(RuntimeError):
    """The published identity snapshot was missing or empty."""


def mlb_identity_names(season: int) -> dict[str, str]:
    """Published `mlbam_id` -> full name, as MLB itself spells it."""
    people = _FETCH.fetch(PEOPLE_URL.format(season=season)).get("people") or []
    if not people:
        raise IdentityFetchError(f"MLB published no players for {season}")
    out: dict[str, str] = {}
    for person in people:
        pid, name = person.get("id"), person.get("fullName")
        if pid is None or not name:
            continue
        # Stored as a string key: JSON object keys are strings anyway, and
        # round-tripping through int would invite a silent type mismatch at
        # lookup time.
        out[str(int(pid))] = name
    return out


def build(season: int) -> dict:
    return {
        "_provenance": {
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "season": season,
            "sources": {"mlb": PEOPLE_URL.format(season=season)},
            "note": "Names verbatim as the publisher spells them, accents included. "
                    "Normalisation belongs to the reader, not to this file -- a "
                    "stripped name here could not be diffed against the source.",
        },
        "leagues": {
            "mlb": {"id_column": "mlbam_id", "names": mlb_identity_names(season)},
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=dt.date.today().year)
    ap.add_argument("--out", default=ARTIFACT)
    args = ap.parse_args(argv)

    artifact = build(args.season)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(artifact, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, args.out)

    for league, entry in sorted(artifact["leagues"].items()):
        print(f"  {league}: {len(entry['names'])} published {entry['id_column']} -> name pairs")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
