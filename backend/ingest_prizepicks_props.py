#!/usr/bin/env python3
"""PrizePicks soccer props from a payload fetched off a non-datacenter IP.

PrizePicks is the only source measured on 2026-08-25 that prices Leagues Cup
player stat markets, and its whole estate refuses this box: `api`, `partner-api`,
`app` and `www` all return 403 with a byte-identical error id, and a path that
does not exist returns 403 rather than 404, so the block fires ahead of routing.
The RotoWire relay carries `prizepicks` as a book but does not carry this
competition: 22 soccer props on one La Liga fixture while PrizePicks had all
four Leagues Cup games on the board. A relay's book list is a claim about the
relay.

CORRECTED 2026-08-26 from eight days of the relay archive (08-19..08-26): the
sentence above used to read "republishes almost none of it", generalised from
that single day. The relay carries 979 soccer props over those eight days
across twelve markets and five competitions -- Serie A, La Liga, the Premier
League, Ligue 1 and MLS -- and its daily soccer volume swings 23..246, so no
one day describes it. What survives is the narrow claim: ZERO Leagues Cup and
ZERO Liga MX on all eight days, which is why this file exists.

So the payload arrives as a file, fetched by a human browser (see
`tools/pull_prizepicks.py`). This reads that file. It does not fetch.

Resolution reuses the HTTP ingest endpoint rather than opening a second
resolver: `/api/props/ingest` already routes a Leagues Cup club to the `mls` or
`ligamx` spine by the club's own membership and fails closed when a code names
both (`ATL` is Atlanta United and Atlante). Duplicating that here is how the two
copies drift.

Usage:
  python3 ingest_prizepicks_props.py path/to/projections.json --dry-run
  python3 ingest_prizepicks_props.py path/to/projections.json
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ingest_rotowire_props as rw  # noqa: E402

API_BASE = os.environ.get("LP_API_BASE", "http://127.0.0.1:8096")
DB_PATH = os.environ.get("LP_DB_PATH", "data/picks.dev.db")

# PrizePicks' own stat_type strings -> our market vocabulary. Taken from a real
# payload, not from their docs. The two Fantasy Score markets are deliberately
# absent for the same reason the MLB and RotoWire Fantasy Score ids are: they are
# composites of a scoring formula the publisher does not send, so nothing
# downstream could settle them. They are reported as UNMAPPED, not ingested.
MARKETS = {
    "Shots": "shots",
    "Shots On Target": "shots_on_target",
    "Goals": "goals",
    "Assists": "assists",
    "Goal + Assist": "goal_or_assist",
    "Tackles": "tackles",
    "Passes Attempted": "passes_attempted",
    "Clearances": "clearances",
    "Crosses": "crosses",
    "Attempted Dribbles": "dribbles",
    "Shots Assisted": "shots_assisted",
    # PrizePicks says "Fouls" where RotoWire says "Fouls Committed" and ESPN
    # publishes foulsCommitted AND foulsSuffered as separate fields. Mapped to
    # committed because that is the near-universal meaning of an unqualified
    # soccer fouls line, but it is an ASSUMPTION about this publisher, not a
    # verified equivalence, and settlement should be checked against a graded
    # result before this market is trusted.
    "Fouls": "fouls_committed",
    # Goalkeeper markets. PrizePicks publishes both and we dropped both as
    # UNMAPPED, while `saves` and `goals_allowed` have been in the chart map for
    # ligamx and lcup all along and the logs carry `saves` and `goals_conceded`
    # on every soccer row. Measured in a real payload 2026-08-26: 29 Goalie
    # Saves and 3 Goals Allowed lines, none of them on a fixture we currently
    # price, so this adds no rows today and closes the gap for when it does.
    "Goalie Saves": "saves",
    "Goals Allowed": "goals_allowed",
}

# A demon is a harder line and a goblin an easier one, both with adjusted
# payouts, and on this board only "More" is offered on either. They are real
# props but they are NOT the standard line, so the variant is carried in the
# source rather than flattened away -- a reader that treats a demon as a plain
# over/under is reading a different bet than the one PrizePicks is taking.
SOURCE_BY_ODDS_TYPE = {
    "standard": "prizepicks",
    "demon": "prizepicks-demon",
    "goblin": "prizepicks-goblin",
}


def load(path):
    """Either a raw /projections response or a tools/pull_prizepicks.py bundle."""
    with open(path) as handle:
        payload = json.load(handle)
    if "data" in payload and "included" in payload:
        return [payload]
    bundles = payload.get("projections")
    if isinstance(bundles, dict):
        return [b for b in bundles.values() if isinstance(b, dict) and "data" in b]
    raise SystemExit(
        "{}: not a PrizePicks projections payload (no `data`/`included`, no "
        "`projections` map)".format(path))


def _fragment_fallback(vocabulary, raw):
    """A club named by a whole-word fragment, accepted only when unambiguous.

    PrizePicks writes `Chicago` for Chicago Fire, `Columbus` for Columbus Crew
    and `Salt Lake` for Real Salt Lake, so the published spellings miss. Note the
    last one is a TRAILING fragment, not a leading one -- matching only prefixes
    silently dropped both sides of Leon vs Real Salt Lake, 380 props, and the
    fixture simply did not appear rather than erroring.

    Matched on word boundaries only, so `Leon` never matches `Leones`, and a
    fragment naming two clubs resolves to neither: widening it is how a Liga MX
    player ends up on an MLS roster.
    """
    if vocabulary is None or not raw:
        return None
    key = rw.normalize_name(raw)
    matches = {code for spelling, code in vocabulary.items()
               if spelling == key
               or spelling.startswith(key + " ")
               or spelling.endswith(" " + key)
               or (" " + key + " ") in spelling}
    if len(matches) == 1:
        return next(iter(matches))
    return None


def resolve_club(vocabulary, raw):
    return rw.resolve_team(vocabulary, raw) or _fragment_fallback(vocabulary, raw)


def parse(payloads, vocabulary):
    """Board rows plus the counts needed to reconcile against the source."""
    counts = collections.Counter()
    unmapped = collections.Counter()
    unknown_clubs = collections.Counter()
    rows = []
    for payload in payloads:
        included = {(i["type"], i["id"]): i for i in payload.get("included", [])}
        for projection in payload.get("data", []):
            attributes = projection.get("attributes", {})
            counts["projections"] += 1
            if attributes.get("status") != "pre_game":
                counts["not_pre_game"] += 1
                continue
            player_ref = ((projection.get("relationships", {}).get("new_player")
                           or {}).get("data") or {})
            player = included.get(("new_player", player_ref.get("id")), {})
            player_attributes = player.get("attributes", {})

            club = resolve_club(vocabulary, player_attributes.get("team"))
            opponent = resolve_club(vocabulary, attributes.get("description"))
            if not club or not opponent:
                # Not this tournament's clubs. PrizePicks files every
                # competition under one SOCCER league, so most of this payload
                # is La Liga and the EPL and is simply not ours.
                unknown_clubs[(player_attributes.get("team"),
                               attributes.get("description"))] += 1
                continue
            counts["our_clubs"] += 1

            stat = attributes.get("stat_type")
            market = MARKETS.get(stat)
            if not market:
                unmapped[stat] += 1
                continue

            rows.append({
                "player_name": player_attributes.get("name"),
                "team": club.split(":")[-1],
                "roster_league": club.split(":")[0] if ":" in club else None,
                "opponent": opponent.split(":")[-1],
                "market": market,
                "line": attributes.get("line_score"),
                "side": "over",
                "source": SOURCE_BY_ODDS_TYPE.get(
                    attributes.get("odds_type"), "prizepicks"),
                "start_time": attributes.get("start_time"),
                "stat_type": stat,
            })
            counts["rows"] += 1
    return rows, {"counts": counts, "unmapped": unmapped,
                  "unknown_clubs": unknown_clubs}


def fixtures(con, vocabulary, league):
    """Existing prop_games keyed by the unordered pair of club codes.

    Matching an existing fixture rather than posting home/away keeps one game row
    per match: this payload names only the opponent, never which side is home, so
    inventing a home/away here would create a second, duplicate fixture beside
    the one the Bovada scraper already wrote.
    """
    index = {}
    for row in con.execute(
            "SELECT id, date, home, away FROM prop_games WHERE league=?", (league,)):
        home = resolve_club(vocabulary, row[2])
        away = resolve_club(vocabulary, row[3])
        if not home or not away:
            continue
        key = frozenset((home.split(":")[-1], away.split(":")[-1]))
        index[key] = {"id": row[0], "date": row[1], "home": row[2], "away": row[3]}
    return index


def post(batch):
    request = urllib.request.Request(
        "{}/api/props/ingest".format(API_BASE),
        data=json.dumps(batch).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path")
    parser.add_argument("--league", default="lcup")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    payloads = load(args.path)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    vocabulary = rw.team_vocabulary(con, args.league)
    if vocabulary is None:
        raise SystemExit(
            "no published team vocabulary for {}: refusing to resolve clubs by "
            "name alone".format(args.league))

    rows, report = parse(payloads, vocabulary)
    counts = report["counts"]
    print("Source: {} projections, {} pre-game on our clubs, {} board rows."
          .format(counts["projections"], counts["our_clubs"], counts["rows"]))
    for stat, n in report["unmapped"].most_common():
        print("  UNMAPPED stat_type {!r}: {} props not ingested".format(stat, n))

    index = fixtures(con, vocabulary, args.league)
    con.close()
    print("{} known {} fixtures.".format(len(index), args.league))

    grouped = collections.defaultdict(list)
    orphans = collections.Counter()
    for row in rows:
        key = frozenset((row["team"], row["opponent"]))
        if key not in index:
            orphans[tuple(sorted(key))] += 1
            continue
        grouped[key].append(row)
    for pair, n in orphans.most_common():
        print("  NO FIXTURE for {}: {} props not ingested".format(pair, n))

    markets = collections.Counter(r["market"] for rs in grouped.values() for r in rs)
    print("\n{} markets across {} fixtures:".format(len(markets), len(grouped)))
    for market, n in markets.most_common():
        print("   {:22s} {}".format(market, n))

    if args.dry_run:
        print("\ndry run -- nothing written.")
        return 0

    totals = collections.Counter()
    for key, batch_rows in grouped.items():
        game = index[key]
        result = post({
            "league": args.league,
            "date": game["date"],
            "home": game["home"],
            "away": game["away"],
            "props": [{"player_name": r["player_name"], "team": r["team"],
                       "market": r["market"], "line": r["line"],
                       "side": r["side"], "source": r["source"]}
                      for r in batch_rows],
        })
        # The endpoint calls it `ingested`, not `new`. Reading the wrong key
        # reported "0 new" for a run that had just written 1,543 props, which is
        # the failure mode where a summary is a claim nobody checked against the
        # table it describes.
        if "ingested" not in result:
            raise SystemExit(
                "ingest response has no `ingested` key: {!r}".format(result))
        totals["ingested"] += result["ingested"]
        totals["refreshed"] += result.get("refreshed", 0)
        totals["unresolved"] += result.get("unresolved", 0)
        print("  {} @ {}: {} ingested, {} refreshed, {} unresolved".format(
            game["away"], game["home"], result["ingested"],
            result.get("refreshed", 0), result.get("unresolved", 0)))
    print("\nIngest: {ingested} ingested, {refreshed} refreshed, {unresolved} "
          "unresolved.".format(**totals))
    written = totals["ingested"] + totals["refreshed"] + totals["unresolved"]
    if written != len(rows) - sum(orphans.values()):
        print("  RECONCILE MISMATCH: {} board rows in, {} accounted for."
              .format(len(rows) - sum(orphans.values()), written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
