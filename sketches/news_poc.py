#!/usr/bin/env python3
"""
sketches/news_poc.py — League News Engine POC (2026-08-06)

Collects real news from verified free sources, classifies each item into the
two layers Micah wants (narrative vs granular: trade/staff/injury), tags the
league, and emits a JSON report + console summary.

Sources (all verified working, zero auth, per docs/PLAN-league-news-engine.md):
  - ESPN news API     1 req per league (nfl, baseball/mlb, soccer/usa.1, football/college-football)
  - Deadspin RSS      https://deadspin.com/rss
  - Awful Announcing  https://www.awfulannouncing.com/feed
  - Bluesky search    https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts

Request count this run: 4 (ESPN) + 2 (RSS) + 2 (Bluesky) = 8 external requests.

Usage: python3 sketches/news_poc.py [--out sketches/news_poc_output.json]
"""
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Shared ESPN client per espn-request-budget doctrine (§4): one home for pacing,
# per-host budget and disk cache. No hand-rolled urllib against ESPN hosts.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from paced_http import Fetcher  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

_ESPN_FETCHER = Fetcher(
    min_interval=0.5,
    cache_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".news_cache"),
    cache_ttl=3600,        # re-runs inside the hour cost zero requests
    host_budget=20,        # well under the ~100 wall; refuse early, never discover it
)

# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------
ESPN_NEWS = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=25",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit=25",
    "mls": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/news?limit=25",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/news?limit=25",
}
RSS_FEEDS = [
    ("deadspin", "https://deadspin.com/rss/"),  # /rss 308→/rss/ (Py3.8 urllib won't follow 308)
    ("awfulannouncing", "https://www.awfulannouncing.com/feed"),
]
BLUESKY_QUERIES = [
    "dodgers salary cap",
    "mls relegation promotion",
]

# public.api.bsky.app 403'd this box 2026-08-06; api.bsky.app verified working.
_BLUE_FETCHER = Fetcher(
    min_interval=0.5,
    cache_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".news_cache"),
    cache_ttl=3600,
    host_budget=0,          # no measured count limit for Bluesky
)
BLUESKY_SEARCH = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"

# --------------------------------------------------------------------------
# Classifier vocab
# --------------------------------------------------------------------------
LEAGUE_TERMS = {
    "nfl": ["nfl", "chiefs", "eagles", "49ers", "cowboys", "ravens", "bills", "lions",
            "vikings", "packers", "bengals", "dolphins", "jets", "giants", "steelers",
            "broncos", "seahawks", "buccaneers", "saints", "colts", "texans", "jaguars",
            "titans", "panthers", "falcons", "commanders", "patriots", "bears", "browns",
            "cardinals", "chargers", "rams", "raiders"],
    "mlb": ["mlb", "dodgers", "yankees", "mets", "red sox", "cubs", "phillies", "braves",
            "astros", "padres", "orioles", "brewers", "guardians", "twins", "mariners",
            "rangers", "giants", "cardinals", "white sox", "rays", "blue jays", "tigers",
            "royals", "athletics", "pirates", "reds", "rockies", "diamondbacks", "marlins",
            "nationals", "angels", "world series"],
    "mls": ["mls", "inter miami", "lafc", "galaxy", "sounders", "timbers", "atlanta united",
            "toronto", "austin fc", "charlotte", "cincinnati", "colorado", "columbus",
            "dallas", "dc united", "dynamo", "kansas city", "minnesota", "montreal",
            "nashville", "new england", "new york", "orlando", "philadelphia",
            "real salt lake", "san jose", "st. louis", "vancouver", "relegation"],
    "ncaaf": ["sec", "big ten", "big 12", "acc", "pac-12", "college football", "cfp",
              "playoff", "bowl game", "alabama", "georgia", "ohio state", "michigan",
              "texas", "notre dame", "lsu", "clemson", "oklahoma", "oregon", "usc",
              "saban", "super conference", "superleague"],
    "nba": ["nba", "lakers", "celtics", "warriors", "nuggets", "bucks", "heat", "knicks",
            "76ers", "suns", "mavericks", "thunder", "cavaliers", "timberwolves"],
    "nhl": ["nhl", "bruins", "rangers", "maple leafs", "oilers", "avalanche", "golden knights",
            "panthers", "hurricanes", "stars", "penguins"],
}

LAYER_RULES = [
    ("injury", ["injury", "injured", "out for", "out 4-5", "surgery", "torn", "sprain",
                "strain", "doubtful", "questionable", "day-to-day", "injured reserve",
                "hamstring", "ankle", "knee", "shoulder", "fracture", "concussion",
                "placed on ir"]),
    ("staff", ["fired", "firing", "hire", "hired", "coach", "coaching", "manager",
               "general manager", "front office", "stepping down", "resigns",
               "interim", "departs", "departure"]),
    ("narrative", ["salary cap", "salary floor", "relegation", "promotion",
                   "super conference", "superleague", "realignment", "expansion",
                   "cba", "lockout", "media rights", "broadcast", "tv deal",
                   "negotiations", "lawsuit", "settlement", "playoff format",
                   "rule change", "cap and floor", "cap debate", "conference"]),
    ("trade", ["trade", "traded", "acquire", "acquired", "acquires", "sign", "signed",
               "extension", "re-sign", "free agent", "contract", "deal for",
               "swap", "agreement"]),
]

# Small notable-name list per league (POC only — real answer comes from our players table)
NOTABLE = {
    "nfl": ["mahomes", "josh allen", "jalen hurts", "burrow", "lamar", "herbert", "stroud",
            "purdy", "saquon", "mccaffrey", "tyreek", "kelce", "jefferson", "jamarr",
            "aja brown", "jettas"],
    "mlb": ["ohtani", "shohei", "mookie", "betts", "freeman", "judge", "soto", "harper",
            "acuna", "trout", "wheeler", "burnes"],
    "mls": ["messi", "suarez", "busquets", "alba", "reus", "pulisic", "lodeiro"],
    "ncaaf": ["saban", "kirby smart", "ryan day", "james franklin", "lane kiffin", "dabo"],
    "nba": ["lebron", "luka", "giannis", "jokic", "tatum", "curry", "shai", "ant man"],
    "nhl": ["mcdavid", "draisaitl", "mackinnon", "pastrnak", "panarin"],
}


def http_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def classify(text, source_hint):
    t = text.lower()
    # league
    league = None
    for lg, terms in LEAGUE_TERMS.items():
        if any(term in t for term in terms):
            league = lg
            break
    if league is None:
        league = "unclassified"
    # layer — granular first, then narrative
    layer = "other"
    for name, words in LAYER_RULES:
        if any(w in t for w in words):
            layer = name
            break
    # key player
    key_player = None
    for lg, names in NOTABLE.items():
        for n in names:
            if n in t:
                key_player = n.title()
                break
        if key_player:
            break
    return {"league": league, "layer": layer, "key_player": key_player}


def collect_espn():
    if os.environ.get("SKIP_ESPN") or "--no-espn" in sys.argv:
        return []
    items = []
    for league, url in ESPN_NEWS.items():
        try:
            d = _ESPN_FETCHER.json(url)
            for a in d.get("articles", []):
                items.append({
                    "source": "espn-" + league,
                    "headline": a.get("headline", ""),
                    "body": a.get("description", ""),
                    "url": (a.get("links", {}).get("web", {}).get("href")
                            or a.get("link", {}).get("href") or ""),
                    "published": a.get("published", ""),
                })
        except Exception as e:
            items.append({"source": "espn-" + league, "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def collect_rss():
    items = []
    for name, url in RSS_FEEDS:
        try:
            root = ET.fromstring(http_text(url))
            for it in root.iter("item"):
                def txt(tag):
                    el = it.find(tag)
                    return (el.text or "").strip() if el is not None else ""
                title, link, desc = txt("title"), txt("link"), txt("description")
                if not title:
                    continue
                items.append({"source": name, "headline": title, "body": desc,
                              "url": link, "published": txt("pubDate")})
        except Exception as e:
            items.append({"source": name, "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def collect_bluesky():
    items = []
    for q in BLUESKY_QUERIES:
        url = BLUESKY_SEARCH + "?q=%s&limit=8" % urllib.parse.quote(q)
        try:
            d = _BLUE_FETCHER.json(url)
            for p in d.get("posts", []):
                rec = p.get("record", {})
                text = rec.get("text", "")
                author = p.get("author", {}).get("handle", "?")
                items.append({
                    "source": "bluesky",
                    "headline": "[@%s] %s" % (author, text[:140]),
                    "body": text,
                    "url": "https://bsky.app/profile/%s/post/%s"
                           % (author, rec.get("uri", "").rsplit("/", 1)[-1]),
                    "published": rec.get("indexedAt", p.get("indexedAt", "")),
                })
        except Exception as e:
            items.append({"source": "bluesky", "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def main():
    out_path = "sketches/news_poc_output.json"
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    print("League News Engine POC — request budget per host (espn-request-budget doctrine):")
    print("  site.api.espn.com: 4  (host_budget=20, disk cache → re-runs cost 0)")
    print("  deadspin.com: 1 | awfulannouncing.com: 1 | api.bsky.app: 2")
    all_items = collect_espn() + collect_rss() + collect_bluesky()

    for it in all_items:
        src_league = it["source"].replace("espn-", "") if it["source"].startswith("espn-") else None
        cls = classify(it["headline"] + " " + it["body"], src_league)
        it.update(cls)

    # Report: per league -> narrative candidates + granular items
    by_league = {}
    for it in all_items:
        by_league.setdefault(it["league"], []).append(it)

    report = {"generated": datetime.now(timezone.utc).isoformat(), "leagues": {}}
    for lg in sorted(by_league):
        items = by_league[lg]
        narratives = [i for i in items if i["layer"] == "narrative"]
        granular = [i for i in items if i["layer"] in ("trade", "staff", "injury")]
        report["leagues"][lg] = {
            "narratives": [{"headline": i["headline"], "url": i["url"],
                            "source": i["source"], "published": i["published"]}
                           for i in narratives],
            "granular": [{"layer": i["layer"], "headline": i["headline"], "url": i["url"],
                          "source": i["source"], "published": i["published"],
                          "key_player": i["key_player"]}
                         for i in granular],
            "other": len([i for i in items if i["layer"] == "other"]),
        }

    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=2)

    raw_path = out_path.replace(".json", "_raw.json")
    with open(raw_path, "w") as fh:
        json.dump(all_items, fh, indent=2)

    # Console summary
    for lg in sorted(by_league):
        data = report["leagues"][lg]
        print("\n=== %s ===" % lg.upper())
        print("  NARRATIVES (%d):" % len(data["narratives"]))
        for n in data["narratives"][:4]:
            print("    - %s  [%s] %s" % (n["headline"][:95], n["source"], n["url"]))
        print("  GRANULAR (%d):" % len(data["granular"]))
        for g in data["granular"][:8]:
            kp = " [%s]" % g["key_player"] if g["key_player"] else ""
            print("    - %s%s  (%s) %s" % (g["headline"][:90], kp, g["layer"], g["url"]))
        if data["other"]:
            print("  (%d items unclassified)" % data["other"])

    print("\nJSON report: %s" % out_path)


if __name__ == "__main__":
    main()
