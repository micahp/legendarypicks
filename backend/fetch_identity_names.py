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

# Each league is asked of the publisher that ISSUED the id we are checking --
# asking anyone else only tells you the two sources agree about a name, which
# is not the question. `nfl_gsis_id` comes from nflverse, `nhl_id` from
# api.nhle.com, and `nba_id` from hoopR (see the note on NBA_URL).
NFL_PLAYERS_URL = ("https://github.com/nflverse/nflverse-data/releases/"
                   "download/players/players.parquet")
NHL_SUMMARY_URL = ("https://api.nhle.com/stats/rest/en/{group}/summary"
                   "?limit={limit}&start={start}"
                   "&cayenneExp=seasonId={season_id}%20and%20gameTypeId=2")
# hoopR is ESPN-derived, and `players.nba_id` is ESPN's athlete id -- verified
# 2026-08-05: on all 51 prod rows carrying both, `nba_id == espn_id` exactly.
# stats.nba.com's own ids are not in this database and stats.nba.com blocks
# datacenter IPs anyway (AGENTS.md S7), so hoopR is both the issuer of record
# and the only reachable one.
NBA_URL = ("https://raw.githubusercontent.com/sportsdataverse/hoopR-data/main/"
           "nba/player_box/parquet/player_box_{season}.parquet")

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


def _parquet_pairs(url: str, id_col: str, name_col: str) -> dict[str, str]:
    """`id_col` -> `name_col` from a remote parquet, read column-wise.

    Only the two columns are materialised. `players.parquet` is 25k rows and
    the hoopR box score is far larger; pulling whole row groups into pandas to
    read two fields is how an identity fetch turns into a memory event on a
    shared box.
    """
    import io
    import urllib.request

    import pyarrow.parquet as parquet

    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR),
                                timeout=180) as resp:
        blob = io.BytesIO(resp.read())
    table = parquet.ParquetFile(blob).read(columns=[id_col, name_col])
    out: dict[str, str] = {}
    for raw_id, raw_name in zip(table.column(id_col).to_pylist(),
                                table.column(name_col).to_pylist()):
        if raw_id is None or not raw_name:
            continue
        key = str(raw_id).strip()
        # hoopR stores the id as a float; '4432171.0' would match no row.
        if key.endswith(".0"):
            key = key[:-2]
        if key and key.lower() not in ("nan", "none"):
            out[key] = str(raw_name)
    return out


def nfl_identity_names(season: int) -> dict[str, str]:
    """Published `nfl_gsis_id` -> display name, from nflverse's own register.

    `season` is unused: `players.parquet` is the all-time register, and an
    identity check wants every id the column can hold, not one season's.
    """
    names = _parquet_pairs(NFL_PLAYERS_URL, "gsis_id", "display_name")
    if not names:
        raise IdentityFetchError("nflverse published no players")
    return names


def nhl_identity_names(season: int) -> dict[str, str]:
    """Published `nhl_id` -> full name, skaters and goalies both.

    Goalies are a separate report with a separate name key. Reading only
    `skater/summary` would leave every goalie UNVERIFIED while reporting a
    healthy count -- this league has three player types and the schema has
    been caught assuming one before.
    """
    season_id = f"{season - 1}{season}"
    out: dict[str, str] = {}
    for group, name_key in (("skater", "skaterFullName"),
                            ("goalie", "goalieFullName")):
        start, limit = 0, 100
        while True:
            page = _FETCH.fetch(NHL_SUMMARY_URL.format(
                group=group, limit=limit, start=start, season_id=season_id))
            rows = page.get("data") or []
            for row in rows:
                pid, name = row.get("playerId"), row.get(name_key)
                if pid is not None and name:
                    out[str(int(pid))] = name
            start += limit
            if start >= int(page.get("total") or 0) or not rows:
                break
    if not out:
        raise IdentityFetchError(f"api.nhle.com published no players for {season_id}")
    return out


def nba_identity_names(season: int) -> dict[str, str]:
    """Published `nba_id` -> display name, from the newest hoopR season on disk.

    hoopR lags: on 2026-08-05 the newest published file was **2023**, which is
    the same staleness behind the NBA leaderboard serving 2023. Walking back is
    honest rather than optimistic -- an id absent from the map is reported
    UNVERIFIED by the audit, never PASS, so a stale map cannot manufacture a
    green check for a player it has never heard of.
    """
    errors = []
    for candidate in range(season, season - 6, -1):
        try:
            names = _parquet_pairs(NBA_URL.format(season=candidate),
                                   "athlete_id", "athlete_display_name")
        except Exception as exc:  # 404 for a season hoopR has not published
            errors.append(f"{candidate}: {type(exc).__name__}")
            continue
        if names:
            return names
    raise IdentityFetchError(
        f"hoopR published no player box score for {season}..{season - 5} "
        f"({'; '.join(errors)})")


LEAGUES = (
    ("mlb", "mlbam_id", mlb_identity_names, PEOPLE_URL),
    ("nfl", "nfl_gsis_id", nfl_identity_names, NFL_PLAYERS_URL),
    ("nhl", "nhl_id", nhl_identity_names, NHL_SUMMARY_URL),
    ("nba", "nba_id", nba_identity_names, NBA_URL),
)


def build(season: int, only=None) -> dict:
    """Fetch every league's map, keeping the failures visible.

    One league failing must not cost the others their map, and must not go
    quiet either: the league is omitted -- which the audit reports UNVERIFIED,
    never PASS -- and the reason is written into `_provenance.errors` so the
    diff shows why a league went missing. A map that silently shrank would
    turn a red check green by removing the ids it could not answer for.
    """
    sources, errors, leagues = {}, {}, {}
    for league, id_column, fetch, url in LEAGUES:
        if only and league not in only:
            continue
        sources[league] = url
        try:
            leagues[league] = {"id_column": id_column, "names": fetch(season)}
        except Exception as exc:
            errors[league] = f"{type(exc).__name__}: {exc}"
            print(f"  {league}: FAILED -- {errors[league]}", file=sys.stderr)
    return {
        "_provenance": {
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "season": season,
            "sources": sources,
            "errors": errors,
            "note": "Names verbatim as the publisher spells them, accents included. "
                    "Normalisation belongs to the reader, not to this file -- a "
                    "stripped name here could not be diffed against the source. "
                    "Each league is asked of the publisher that ISSUED its id.",
        },
        "leagues": leagues,
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
