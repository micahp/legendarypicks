#!/usr/bin/env python3
"""Pull PrizePicks from a residential IP and write one file we can ingest.

Run this on a machine PrizePicks will answer -- a home PC or a phone hotspot.
The datacenter this box lives in is blocked estate-wide: api, partner-api, app
and www all refuse with the same Cloudflare ray id, so the block is on the IP,
not on any one endpoint or on how the request is shaped.

    python3 pull_prizepicks.py            # every league, every projection
    python3 pull_prizepicks.py --league 82

Standard library only, so there is nothing to install. Python 3.7+.
Writes prizepicks-YYYY-MM-DDTHH-MM-SSZ.json next to itself, then prints the
soccer market names it found so you can tell at a glance whether the four
Leagues Cup fixtures are on the board yet.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://api.prizepicks.com"
# A browser User-Agent is not a trick here: the endpoint is the one the site's
# own front end calls, and the default python-urllib agent is refused outright.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Referer": "https://app.prizepicks.com/",
        "Origin": "https://app.prizepicks.com",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--league", help="one league id; default is all of them")
    parser.add_argument("--out", help="output path")
    args = parser.parse_args()

    bundle = {"pulled_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}

    try:
        bundle["leagues"] = get(BASE + "/leagues")
    except urllib.error.HTTPError as error:
        # Fail loudly and say which failure this is. A 403 here means this
        # machine is blocked too and the whole run is pointless; anything else
        # is worth reporting verbatim rather than retrying blindly.
        sys.exit("leagues: HTTP {}. {}".format(
            error.code,
            "This machine is blocked too -- try a phone hotspot."
            if error.code == 403 else error.read()[:300]))
    except Exception as error:
        sys.exit("leagues: {}: {}".format(type(error).__name__, error))

    ids = []
    for row in (bundle["leagues"].get("data") or []):
        name = (row.get("attributes") or {}).get("name") or ""
        ids.append((row.get("id"), name))
    print("{} leagues published".format(len(ids)))

    wanted = [(i, n) for i, n in ids if args.league in (None, i)]
    bundle["projections"] = {}
    for league_id, name in wanted:
        url = "{}/projections?league_id={}&per_page=1000".format(BASE, league_id)
        try:
            payload = get(url)
        except Exception as error:
            print("  {:>5} {:24s} {}".format(league_id, name[:24], type(error).__name__))
            continue
        rows = payload.get("data") or []
        if rows:
            bundle["projections"][league_id] = payload
            print("  {:>5} {:24s} {} projections".format(league_id, name[:24], len(rows)))

    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "prizepicks-{}.json".format(bundle["pulled_at"].replace(":", "-")))
    with open(out, "w") as handle:
        json.dump(bundle, handle)

    # What the run was for: the stat markets, and whether soccer is among them.
    markets = {}
    for payload in bundle["projections"].values():
        for row in (payload.get("data") or []):
            stat = (row.get("attributes") or {}).get("stat_type")
            if stat:
                markets[stat] = markets.get(stat, 0) + 1
    soccer_words = ("shot", "pass", "tackle", "clearance", "save", "cross",
                    "foul", "chance", "goal", "assist")
    soccer = {k: v for k, v in markets.items()
              if any(w in k.lower() for w in soccer_words)}
    print("\nwrote {} ({:.1f} KB)".format(out, os.path.getsize(out) / 1024.0))
    print("{} distinct stat markets, {} of them soccer-shaped:".format(
        len(markets), len(soccer)))
    for stat, count in sorted(soccer.items(), key=lambda kv: -kv[1]):
        print("   {:28s} {}".format(stat, count))


if __name__ == "__main__":
    main()
