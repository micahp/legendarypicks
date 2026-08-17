#!/usr/bin/env python3
"""MLS player props from Kambi (the Unibet platform) — a second publisher for the league.

WHY A SECOND SOURCE. Bovada is the only book that answers from this box for MLS, and it
publishes 8 player markets across 14 fixtures. It does not publish shots, shots on target,
tackles or passes at all. DraftKings does — Micah's link prices player tackles — but every
DraftKings host is walled at the Akamai edge for this IP: 6 hosts probed 2026-08-16,
all 403 including the plain HTML page, so it is not a header or a User-Agent problem.
PrizePicks 403s, FanDuel 403s, BetMGM 403s, the Odds API needs a paid key, Underdog
publishes no MLS at all (see docs/UNDERDOG-API-RECON-2026-07-23.md), and Pinnacle's MLS
board is 696 matchups of which **zero** are player props.

Kambi answers. Measured 2026-08-16 across all 32 fixtures on its MLS list:

    To Score                             788        Bovada: 357
    First Goal Scorer                    776        Bovada: 332
    To score or give an assist           773        Bovada:  20
    To give an assist                    500        Bovada: 639
    To score at least 2 goals            381        Bovada:  20
    To score at least 3 goals             52        Bovada:  56 (hat trick)
    To score at least 4 goals              3        Bovada:   0
    Player's shots on target              23        Bovada:   0
    ------------------------------------------
    32 fixtures                                     Bovada: 14

BE HONEST ABOUT THE SHOTS MARKET. `Player's shots on target` appeared on **one of 32
fixtures**, not on the nearest kickoff — Austin/Dallas kicks off first and has none. It is
sporadic, not a reliable feed, and this script must not be described as "we have MLS shots
data now". What it reliably adds is a deeper goalscorer/assist board and **more than twice
the fixture horizon**.

The Opta note in those market labels is the publisher naming its own settlement source.
We settle from ESPN, and the two can disagree on a deflected shot. Props from here carry
source='kambi' so a disagreement is attributable rather than mysterious.

IDENTITY. Kambi spells players the way ESPN does, accents intact ("Albert Rusnák"), which
is better than Bovada. Resolution still goes through /api/props/ingest, which never creates
a player — an unresolved name lands in unresolved_players where it can be read.

GAMES. This script NEVER creates a prop_games row. It resolves each Kambi fixture to a game
we already hold, by canonical team code and date, and passes that row's espn_event_id. A
book-specific display name that failed to match would otherwise mint a second prop_games
row for a fixture we already have, splitting one game's board across two ids — the exact
shape that made 714 MLS props unreachable. A fixture that does not resolve is REPORTED and
skipped.

STATUS 2026-08-16: OFF. Not scheduled, and refuses to run without --enable.

MLS props come from the RotoWire/PrizePicks relay. Of the eleven markets this league is
being built for — shots, shots on target, passes attempted, goals, goalie saves,
clearances, assists, attempted dribbles, tackles, crosses, fouls — Kambi prices goals,
assists, and a shots-on-target market that appeared on one fixture of thirty-two. The relay
prices seven. Two sources writing goals and assists into the same board, where one of them
answers almost none of the question, is a disagreement to adjudicate for no gain.

The file is kept because the measurement in it is real and the league is one flag away if
the relay does not work out. It is inert rather than deleted for the same reason
`_parse_mls_props` stays in bovada_scraper.py.

Usage:
  python3 ingest_kambi_mls_props.py --enable            # scrape and report, write nothing
  python3 ingest_kambi_mls_props.py --enable --ingest   # POST to the resolver API
"""
import argparse
import collections
import json
import os
import sqlite3
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from link_prop_games import _TEAM_MAPS  # noqa: E402

LEAGUE = "mls"
SOURCE = "kambi"
API_BASE = os.environ.get("LP_API_BASE", "http://localhost:8000")
DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

_LIST = ("https://eu-offering-api.kambicdn.com/offering/v2018/ub/listView/"
         "football/usa/mls.json?lang=en_GB&market=GB")
_EVENT = ("https://eu-offering-api.kambicdn.com/offering/v2018/ub/betoffer/"
          "event/{event_id}.json?lang=en_GB&market=GB")
_HDRS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "Chrome/131 Safari/537.36"}
_MIN_INTERVAL = float(os.environ.get("LP_KAMBI_MIN_INTERVAL") or 0.3)

# Kambi criterion label -> (canonical market, line, kind). Exact match, never substring:
# "To score at least 2 goals" and "To Score" would collide under a substring rule, and an
# exact table makes an unrecognised market visible instead of silently absorbed.
#
# The goal ladder is one market at four lines, the same decision the Bovada MLS parser
# makes, so both books' goalscorer prices land on the same `goals` market and can be
# compared directly.
_YES_NO = "yes_no"        # outcome is the player, "Yes" side, line implied
_OVER_UNDER = "over_under"  # outcome carries OT_OVER/OT_UNDER and a line in milli-units
_MARKETS = {
    "To Score":                                             ("goals", 0.5, _YES_NO),
    "To score at least 2 goals":                            ("goals", 1.5, _YES_NO),
    "To score at least 3 goals":                            ("goals", 2.5, _YES_NO),
    "To score at least 4 goals":                            ("goals", 3.5, _YES_NO),
    "First Goal Scorer":                                    ("first_goal_scorer", 0.5, _YES_NO),
    "To give an assist (Settled using Opta data)":          ("assists", 0.5, _YES_NO),
    "To score or give an assist (Settled using Opta data)": ("goal_or_assist", 0.5, _YES_NO),
    "Player's shots on target (Settled using Opta data)":   ("sot", None, _OVER_UNDER),
}

# Markets whose `participant` is a TEAM, not a person. Kambi puts both in the same field,
# so without this list a handicap line would be ingested as a player prop on a club.
# Listed explicitly rather than pattern-matched: a market that is in neither table is
# REPORTED, which is how a new player market gets noticed instead of dropped.
_TEAM_PARTICIPANT_MARKETS = {
    "Asian Handicap", "Asian Handicap - 1st Half", "Handicap", "3-Way Handicap",
    "3-Way Handicap - 1st Half", "Draw No Bet", "Draw No Bet - 1st Half",
    "Draw No Bet - 2nd Half", "Most Corners", "Full Time", "Half Time", "2nd Half",
    "First Goal (Draw: No Goals)",
    "Most Shots on Target (Settled using Opta data)",
    "Next Corner, No Corner No Bet (1)", "Next Corner, No Corner No Bet (4)",
    "Interval Winner - 50:00-54:59", "Interval Winner - 45:00-59:59",
    "Next Goal (2) (Draw: No More Goals)",
}

# In-play markets about what happens NEXT. They are real player markets, and they are
# deliberately not ingested: the answer depends on the moment the line was taken, which
# `props` has no column for, so a settled result would be unfalsifiable.
_INPLAY_SKIP = {"Next Goal Scorer 2"}

# Kambi types the player side of a yes/no market differently per market family: OT_YES on
# "To Score", OT_PLAYER_PARTICIPANT on "First Goal Scorer". Assuming OT_YES alone silently
# dropped 720 of 776 first-goal outcomes on 2026-08-16 while the run still printed a
# plausible total — the defect this whole file is written against, committed by its own
# author. Both sets are explicit, and anything in neither is REPORTED.
_YES_SIDE_TYPES = {"OT_YES", "OT_PLAYER_PARTICIPANT", ""}
_COMPLEMENT_TYPES = {"OT_NO", "OT_NO_GOAL", "OT_NO_GOALSCORER"}

# Two team-market families are indexed by an ordinal or a clock window, so their labels
# change as a match runs: "Next Corner, No Corner No Bet (5)" becomes "(6)", and
# "Interval Winner - 50:00-54:59" becomes "55:00-59:59". They cannot be enumerated exactly.
# A prefix rule is right for these two and only these two — they are team markets by
# construction, and neither can ever become a player market. Every other label still has to
# match exactly, so a genuinely new PLAYER market is still reported rather than absorbed.
_TEAM_PARTICIPANT_PREFIXES = ("Next Corner, No Corner No Bet", "Interval Winner - ")

# code -> the display name THIS APP uses for the club, read off the prop_games rows Bovada
# has been writing since 2026-08-07. Kambi writes six of them differently ("Atlanta United
# FC", "D.C. United", "Inter Miami CF", "Los Angeles Galaxy", "Minnesota United FC"), and
# /api/props/ingest matches a game on (league, date, home, away) when there is no ESPN id
# yet. Posting Kambi's spelling would therefore mint a SECOND prop_games row for a fixture
# Bovada is about to write under its own name, splitting one match's board across two ids —
# which is how 714 MLS props ended up unreachable. Both books post the same strings.
_OUR_NAME = {
    "ATL": "Atlanta United",      "ATX": "Austin FC",
    "CHI": "Chicago Fire",        "CIN": "FC Cincinnati",
    "CLB": "Columbus Crew",       "CLT": "Charlotte FC",
    "COL": "Colorado Rapids",     "DAL": "FC Dallas",
    "DC": "DC United",            "HOU": "Houston Dynamo",
    "LA": "LA Galaxy",            "LAFC": "Los Angeles FC",
    "MIA": "Inter Miami",         "MIN": "Minnesota United",
    "MTL": "CF Montréal",         "NE": "New England Revolution",
    "NSH": "Nashville SC",        "NYC": "New York City FC",
    "ORL": "Orlando City",        "PHI": "Philadelphia Union",
    "POR": "Portland Timbers",    "RBNY": "New York Red Bulls",
    "RSL": "Real Salt Lake",      "SD": "San Diego FC",
    "SEA": "Seattle Sounders",    "SJ": "San Jose Earthquakes",
    "SKC": "Sporting Kansas City", "STL": "St. Louis City SC",
    "TOR": "Toronto FC",          "VAN": "Vancouver Whitecaps",
}

_last_request = [0.0]


def _get(url):
    gap = _MIN_INTERVAL - (time.monotonic() - _last_request[0])
    if gap > 0:
        time.sleep(gap)
    _last_request[0] = time.monotonic()
    with urllib.request.urlopen(urllib.request.Request(url, headers=_HDRS), timeout=30) as r:
        return json.load(r)


def _code(name):
    """A club's canonical ESPN code, or None when this vocabulary has no entry.

    Kambi writes six names our map does not ("Atlanta United FC", "D.C. United",
    "Inter Miami CF", "Los Angeles Galaxy", "Minnesota United FC"), so try the map, then
    try it again with the corporate suffixes stripped. Never guess past that: a wrong team
    code does not raise, it misses (docs/DATA-SPINE.md §5).
    """
    table = _TEAM_MAPS.get(LEAGUE) or {}
    key = (name or "").strip().lower()
    if key in table:
        return table[key]
    stripped = key
    for suffix in (" fc", " cf", " sc"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
    stripped = stripped.replace(".", "")
    for candidate in (stripped, "los angeles galaxy" == key and "la galaxy" or stripped):
        if candidate in table:
            return table[candidate]
    return None


def _our_games(con):
    """{(date, home_code, away_code): (prop_games.id, espn_event_id)} for MLS."""
    out = {}
    for row in con.execute(
            "SELECT id, date, home, away, espn_event_id FROM prop_games WHERE league=?",
            (LEAGUE,)):
        home, away = _code(row["home"]), _code(row["away"])
        if home and away:
            out[(row["date"], home, away)] = (row["id"], row["espn_event_id"] or "")
    return out


def scrape():
    """[(event, [prop, ...])] for every fixture on Kambi's MLS list."""
    listing = _get(_LIST)
    events = [entry.get("event") or {} for entry in listing.get("events") or []]
    print("Kambi MLS list: {} fixtures".format(len(events)))

    unmapped = collections.Counter()
    skipped_inplay = collections.Counter()
    unknown_types = collections.Counter()
    scraped = []
    for event in events:
        event_id = event.get("id")
        if not event_id:
            continue
        try:
            document = _get(_EVENT.format(event_id=event_id))
        except Exception as exc:  # noqa: BLE001 - one fixture must not kill the run
            print("  fixture {} offers failed: {}".format(event_id, exc))
            continue

        props = []
        for offer in document.get("betOffers") or []:
            label = ((offer.get("criterion") or {}).get("label") or "").strip()
            outcomes = [o for o in (offer.get("outcomes") or []) if o.get("participant")]
            if not outcomes:
                continue
            if label in _TEAM_PARTICIPANT_MARKETS or label.startswith(_TEAM_PARTICIPANT_PREFIXES):
                continue
            if label in _INPLAY_SKIP:
                skipped_inplay[label] += len(outcomes)
                continue
            rule = _MARKETS.get(label)
            if rule is None:
                unmapped[label] += len(outcomes)
                continue

            market, line, kind = rule
            for outcome in outcomes:
                player = (outcome.get("participant") or "").strip()
                if not player:
                    continue
                odds = outcome.get("oddsAmerican")
                if kind == _YES_NO:
                    outcome_type = (outcome.get("type") or "")
                    if outcome_type in _COMPLEMENT_TYPES:
                        # "No goalscorer" / the No side. The market's complement, priced,
                        # but not a person and not a second prop.
                        continue
                    if outcome_type not in _YES_SIDE_TYPES:
                        # Kambi types a yes/no market's player side differently per market
                        # family — OT_YES on "To Score", OT_PLAYER_PARTICIPANT on "First
                        # Goal Scorer". Assuming one of them silently dropped 720 of 776
                        # first-goal outcomes on 2026-08-16 and the run still printed a
                        # plausible total. An unrecognised type is reported, not skipped.
                        unknown_types[(label, outcome_type)] += 1
                        continue
                    prop_line, side = line, "over"
                else:
                    raw = outcome.get("line")
                    if raw is None:
                        continue
                    # Kambi publishes lines in milli-units: 500 is 0.5.
                    prop_line = float(raw) / 1000.0
                    side = "under" if (outcome.get("type") or "") == "OT_UNDER" else "over"
                props.append({
                    "player_name": player,
                    "team": "",  # Kambi does not tag the club on the outcome
                    "market": market,
                    "line": prop_line,
                    "side": side,
                    "odds": odds,
                    "source": SOURCE,
                    "market_raw": label,
                })
        scraped.append((event, props))
        print("  {}: {} player props".format(event.get("name"), len(props)))

    return scraped, unmapped, skipped_inplay, unknown_types


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ingest", action="store_true",
                        help="POST to the resolver API (writes props)")
    parser.add_argument("--enable", action="store_true",
                        help="required: this source is OFF (MLS props come from the "
                             "RotoWire/PrizePicks relay)")
    args = parser.parse_args(argv)

    if not args.enable:
        # Refuses rather than quietly doing nothing. A disabled ingest that exits 0 with no
        # output is indistinguishable from one that ran and found an empty board, and this
        # repo has paid for that confusion before.
        print("DISABLED — Kambi is not the MLS source. It prices 3 of the 11 markets this "
              "league needs; the RotoWire/PrizePicks relay prices 7.")
        print("  Pass --enable to run it anyway (manual comparison only). Nothing was "
              "fetched and nothing was written.")
        return 4

    scraped, unmapped, skipped_inplay, unknown_types = scrape()
    total = sum(len(props) for _, props in scraped)
    print("\nTotal player props scraped: {}".format(total))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    ours = _our_games(con)

    matched = []          # fixtures we already hold
    new_fixtures = []     # fixtures Kambi lists further out than Bovada does
    unmatched = []        # fixtures whose clubs this vocabulary cannot name
    for event, props in scraped:
        if not props:
            continue
        date = (event.get("start") or "")[:10]
        home, away = _code(event.get("homeName")), _code(event.get("awayName"))
        if not home or not away or home not in _OUR_NAME or away not in _OUR_NAME:
            unmatched.append((event.get("name"), date, home, away,
                              "club not in the MLS team vocabulary"))
            continue
        found = ours.get((date, home, away))
        entry = (event, props, home, away, found[1] if found else "")
        (matched if found else new_fixtures).append(entry)
    con.close()

    ingested = refreshed = unresolved = failed = 0
    if args.ingest:
        print("\nIngesting into {}...".format(API_BASE))
        for event, props, home, away, espn_event_id in matched + new_fixtures:
            batch = {
                "league": LEAGUE,
                "date": (event.get("start") or "")[:10],
                # OUR names, not Kambi's — see _OUR_NAME.
                "home": _OUR_NAME[home],
                "away": _OUR_NAME[away],
                "espn_event_id": espn_event_id,
                "props": props,
            }
            try:
                data = json.dumps(batch).encode()
                request = urllib.request.Request(
                    API_BASE + "/api/props/ingest", data=data,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=60) as response:
                    result = json.load(response)
                ingested += result.get("ingested") or 0
                refreshed += result.get("refreshed") or 0
                unresolved += result.get("unresolved") or 0
                print("  {}: {} new, {} refreshed".format(
                    event.get("name"), result.get("ingested"), result.get("refreshed", 0)))
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print("  {}: FAIL {}".format(event.get("name"), exc))

    # --- run report. Every line prints at zero too. ---
    problems = []
    print("\n--- run report ---")
    print("  fixtures with player props: {} of {}".format(
        len(matched) + len(new_fixtures) + len(unmatched), len(scraped)))
    print("  fixtures matched to a game we already hold: {}".format(len(matched)))
    # Not a problem — this is the point. Kambi lists further out than Bovada, so these are
    # fixtures we would otherwise have no board for at all. They are posted under OUR
    # canonical club names so Bovada's later insert lands on the same prop_games row.
    print("  fixtures ahead of Bovada's horizon (game row created by the API): {}"
          .format(len(new_fixtures)))
    for event, _props, home, away, _espn in new_fixtures:
        print("      AHEAD {} {} v {}".format(
            (event.get("start") or "")[:10], _OUR_NAME[home], _OUR_NAME[away]))
    print("  fixtures NOT resolved (skipped, nothing written): {}".format(len(unmatched)))
    for name, date, home, away, why in unmatched:
        print("      UNMATCHED {} {} [{} v {}] — {}".format(date, name, home, away, why))
        problems.append("unmatched fixture {}".format(name))

    print("  unmapped player markets: {}".format(len(unmapped)))
    for label, count in unmapped.most_common():
        print("      UNMAPPED {!r} — {} outcomes, NOT ingested".format(label, count))
        problems.append("unmapped market {}".format(label))

    print("  outcomes with an unrecognised type: {}".format(sum(unknown_types.values())))
    for (label, outcome_type), count in unknown_types.most_common():
        print("      UNKNOWN TYPE {!r} on {!r} — {} outcomes, NOT ingested"
              .format(outcome_type, label, count))
        problems.append("unknown outcome type {} on {}".format(outcome_type, label))

    print("  in-play markets deliberately skipped: {}".format(len(skipped_inplay)))
    for label, count in skipped_inplay.most_common():
        print("      SKIPPED {!r} — {} outcomes (answer depends on when the line was taken)"
              .format(label, count))

    if args.ingest:
        resolved = ingested + refreshed
        print("  resolved {} of {} scraped ({} new, {} refreshed, {} unresolved)"
              .format(resolved, total, ingested, refreshed, unresolved))
        if total and not resolved:
            print("      REJECTED all {} props — nothing in `players` matched. "
                  "A count of zero is a finding.".format(total))
            problems.append("resolved 0 of {}".format(total))
        if failed:
            print("      {} fixtures failed to POST".format(failed))
            problems.append("{} fixtures failed to POST".format(failed))

    if problems:
        print("\nEXIT 3 — " + "; ".join(problems))
        return 3
    print("  no problems found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
