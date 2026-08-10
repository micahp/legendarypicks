#!/usr/bin/env python3
"""ingest_league_news.py — collect + classify league news into `news_items`.

Out-of-band collection path (never per-pageview). Sources (all verified
2026-08-06, see docs/PLAN-league-news-engine.md):

  - ESPN news API      1 req per league (nfl, baseball/mlb, soccer/usa.1, football/college-football)
  - Deadspin RSS       https://deadspin.com/rss/
  - Awful Announcing   https://www.awfulannouncing.com/feed
  - FanSided           https://fansided.com/feed/
  - SB Nation          https://www.sbnation.com/rss/index.xml
  - Bluesky search     https://api.bsky.app/xrpc/app.bsky.feed.searchPosts

ESPN requests go through the shared paced_http Fetcher (espn-request-budget
doctrine §4: one home for pacing, per-host budget and disk cache; re-runs
inside the cache TTL cost zero requests). host_budget=20: refuse early, never
discover the wall.

Usage:
  LP_DB_PATH=/path/to/db python3 ingest_league_news.py            # all leagues
  python3 ingest_league_news.py --leagues nfl,mlb --no-espn        # subset
  python3 ingest_league_news.py --dry-run                          # collect+classify, no write
"""
import argparse
import email.utils
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paced_http import Fetcher  # noqa: E402
from news_classifier import classify  # noqa: E402

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# Outside the repo so uvicorn --reload (which watches backend/) never restarts
# the dev server when the collector writes cache files.
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".hermes", "news-cache")

ESPN_NEWS = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=25",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/news?limit=25",
    "mls": "https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/news?limit=25",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/news?limit=25",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news?limit=25",
    "nhl": "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/news?limit=25",
    "ufc": "https://site.api.espn.com/apis/site/v2/sports/mma/ufc/news?limit=25",
}
RSS_FEEDS = [
    ("deadspin", "https://deadspin.com/rss/"),  # /rss 308→/rss/ (Py3.8 urllib won't follow 308)
    ("awfulannouncing", "https://www.awfulannouncing.com/feed"),
    ("fansided", "https://fansided.com/feed/"),
    ("sbnation", "https://www.sbnation.com/rss/index.xml"),
    ("dotesports", "https://dotesports.com/feed"),
]
# Conversations — Micah's dictated narratives ARE the seed (2026-08-07):
# "dodgers salary cap" and "mls relegation promotion" are the two canonical
# examples of what an important conversation looks like. Each conversation is
# its own card on the site and gets to breathe — we do NOT merge them into one
# league summary. Add new conversations HERE (e.g. NFL turf vs grass, 2026-08-07).
# `title` is the short human label; `seed` is the query that anchors it.
CONVERSATIONS = [
    {"id": "mlb-salary-cap", "league": "mlb", "title": "Salary cap debate",
     "seed": "dodgers salary cap"},
    {"id": "mls-pro-rel", "league": "mls", "title": "Promotion/relegation",
     "seed": "mls relegation promotion"},
    {"id": "nfl-media-rights", "league": "nfl", "title": "Media rights talks",
     "seed": "nfl media rights deal"},
    {"id": "nfl-turf-grass", "league": "nfl", "title": "Turf vs. grass",
     "seed": "nfl turf grass"},
    {"id": "nba-expansion", "league": "nba", "title": "Expansion",
     "seed": "nba expansion"},
    # Added 2026-08-09 from evidence in the collected feed (Pablo Torre
    # bombshell + Stephen A. "banishment" call): a live, recurring NBA
    # conversation distinct from expansion. Seeded only because 3+ collected
    # items recur on it — not a dictated narrative this time.
    {"id": "nba-kawhi-cap", "league": "nba", "title": "Kawhi salary-cap case",
     "seed": "Kawhi Leonard salary cap circumvention Clippers"},
    {"id": "nhl-salary-cap", "league": "nhl", "title": "Salary cap",
     "seed": "nhl salary cap"},
    {"id": "ufc-title-fight", "league": "ufc", "title": "Title picture",
     "seed": "ufc title fight"},
    {"id": "ncaaf-realignment", "league": "ncaaf", "title": "Realignment",
     "seed": "ncaaf conference realignment"},
    {"id": "esports-worlds", "league": "esports", "title": "Worlds",
     "seed": "esports worlds"},
    {"id": "esports-valorant", "league": "esports", "title": "Valorant",
     "seed": "valorant champions"},
]

# Generic texture dimensions: the ways a story shows up in fans' lives. Any
# conversation's seed is searched against these to find the ADJACENT
# conversation — the packed stadium, the lower-division energy, the highlight
# clip, the player quote — because those posts carry the story's keywords too
# (Micah, 2026-08-07). This list is sport-agnostic; it is not per-league
# hardcoding.
_TEXTURE_DIMENSIONS = [
    "stadium",
    "attendance",
    "fans",
    "lower division",
    "highlight",
]

# Each (conversation, dimension) pair is its own bluesky query, tagged with the
# conversation so collected items can be attributed back to it.
def _conversation_queries() -> list:
    out = []
    for conv in CONVERSATIONS:
        out.append((conv["id"], conv["seed"]))
        for dim in _TEXTURE_DIMENSIONS:
            out.append((conv["id"], "%s %s" % (conv["seed"], dim)))
    return out

CONVERSATION_QUERIES = _conversation_queries()
ALL_BLUESKY_QUERIES = [q for _c, q in CONVERSATION_QUERIES]
BLUESKY_SEARCH = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"  # public.api 403'd 2026-08-06

# Ingest path: NO retry ladder (espn-request-budget doctrine §6) — a 403 means
# "this host is spent"; fail fast, record the FETCH ERROR row, move on. A
# sleeping ladder is how a batch job burns 10 minutes discovering a wall.
# UA matters: measured 2026-08-07 — site.api.espn.com/news 403s the Chrome UA
# but answers the curl UA (200, full article lists). DEFAULT_HDRS (Chrome)
# is what the shared Fetcher uses; override headers here so the news endpoint
# is actually reachable. One request per league, count-budgeted like the rest.
_ESPN_FETCHER = Fetcher(min_interval=0.5, retry_waits=(), cache_dir=CACHE_DIR,
                        cache_ttl=3600, host_budget=20,
                        headers={"User-Agent": "curl/8.5.0"})
_BLUE_FETCHER = Fetcher(min_interval=0.5, retry_waits=(), cache_dir=CACHE_DIR,
                        cache_ttl=3600, host_budget=0)


def _iso(published: str) -> str:
    """Normalize RFC822 (RSS) dates to ISO 8601 so ORDER BY published works."""
    p = (published or "").strip()
    if not p:
        return ""
    if p[0].isdigit() and "," in p:
        try:
            return email.utils.parsedate_to_datetime(p).astimezone().isoformat()
        except Exception:
            return p
    return p


def _http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def collect_espn(leagues):
    items = []
    for league in leagues:
        url = ESPN_NEWS[league]
        try:
            d = _ESPN_FETCHER.json(url)
            for a in d.get("articles", []):
                items.append({
                    "source": "espn-" + league,
                    "headline": a.get("headline", ""),
                    "body": a.get("description", ""),
                    "url": (a.get("links", {}).get("web", {}).get("href")
                            or a.get("link", {}).get("href") or ""),
                    "published": _iso(a.get("published", "")),
                })
        except Exception as e:
            items.append({"source": "espn-" + league, "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def collect_rss():
    items = []
    for name, url in RSS_FEEDS:
        try:
            root = ET.fromstring(_http_text(url))
            # RSS 2.0 <item> or Atom <entry> (SB Nation is Atom).
            for it in list(root.iter("item")) + list(root.iter("{http://www.w3.org/2005/Atom}entry")):
                def txt(tag):
                    el = it.find(tag)
                    if el is None:
                        el = it.find("{http://www.w3.org/2005/Atom}" + tag)
                    return (el.text or "").strip() if el is not None else ""
                title, link, desc = txt("title"), txt("link"), txt("summary")
                if not title:
                    continue
                if not link:
                    link_el = it.find("{http://www.w3.org/2005/Atom}link")
                    if link_el is not None:
                        link = link_el.get("href", "")
                items.append({"source": name, "headline": title, "body": desc,
                              "url": link, "published": _iso(txt("pubDate") or txt("updated"))})
        except Exception as e:
            items.append({"source": name, "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def collect_bluesky():
    items = []
    for conv_id, q in CONVERSATION_QUERIES:
        url = BLUESKY_SEARCH + "?q=%s&limit=8" % urllib.parse.quote(q)
        try:
            d = _BLUE_FETCHER.json(url)
            for p in d.get("posts", []):
                rec = p.get("record", {})
                text = rec.get("text", "")
                author = p.get("author", {}).get("handle", "?")
                post_uri = p.get("uri", "") or rec.get("uri", "")
                items.append({
                    "source": "bluesky",
                    "conv_id": conv_id,
                    "headline": "[@%s] %s" % (author, text[:140]),
                    "body": text,
                    "url": "https://bsky.app/profile/%s/post/%s"
                           % (author, post_uri.rsplit("/", 1)[-1]),
                    "published": _iso(rec.get("indexedAt", "")),
                })
        except Exception as e:
            items.append({"source": "bluesky", "conv_id": conv_id,
                          "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def upsert(items, dry_run=False):
    if not items:
        return 0, 0
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    # Single source of truth for schema: _core's _init_db (creates news_items
    # + every other table idempotently). Fall back to the news table alone if
    # importing _core is impossible in this environment.
    try:
        from _core import _init_db as _core_init_db
        _core_init_db()
    except Exception:
        con = sqlite3.connect(db_path)
        con.execute("""
        CREATE TABLE IF NOT EXISTS news_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL,
          layer TEXT NOT NULL,
          source TEXT NOT NULL,
          headline TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL UNIQUE,
          published TEXT NOT NULL DEFAULT '',
          key_player TEXT,
          conv_id TEXT,
          first_seen TEXT NOT NULL DEFAULT (datetime('now')));
        """)
        con.commit()
        con.close()
    con = sqlite3.connect(db_path)
    inserted = updated = 0
    for it in items:
        if not it.get("url"):
            continue
        if dry_run:
            continue
        before = con.total_changes
        con.execute(
            """INSERT INTO news_items(league, layer, source, headline, body, url, published, key_player, conv_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                 league=excluded.league, headline=excluded.headline, body=excluded.body,
                 published=excluded.published,
                 layer=excluded.layer, key_player=excluded.key_player, source=excluded.source,
                 conv_id=excluded.conv_id""",
            (it["league"], it["layer"], it["source"], it["headline"], it["body"],
             it["url"], it["published"], it.get("key_player"), it.get("conv_id")),
        )
        delta = con.total_changes - before
        if delta == 1:
            inserted += 1
        else:
            updated += 1
    con.commit()
    con.close()
    return inserted, updated


def reclassify_existing(dry_run=False):
    """Re-run the classifier over stored rows (headline+body) and update
    league/layer/key_player — items that fell out of the live feeds keep their
    old classification otherwise (e.g. the Giants-broadcaster MLB fix)."""
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT id, headline, body, source FROM news_items WHERE url != ''").fetchall()
    changed = 0
    for rid, headline, body, source in rows:
        src_league = source.replace("espn-", "") if source.startswith("espn-") else None
        cls = classify((headline or "") + " " + (body or ""), src_league)
        if not dry_run:
            cur = con.execute(
                "UPDATE news_items SET league=?, layer=?, key_player=? WHERE id=?",
                (cls["league"], cls["layer"], cls.get("key_player"), rid))
            changed += cur.rowcount
        else:
            changed += 1
    con.commit()
    con.close()
    print("Reclassified %d rows%s" % (changed, " (dry run)" if dry_run else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="nfl,mlb,mls,ncaaf,nba,nhl,ufc",
                    help="comma list of ESPN leagues to collect")
    ap.add_argument("--no-espn", action="store_true")
    ap.add_argument("--no-rss", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reclassify", action="store_true",
                    help="re-run the classifier over stored rows (no network)")
    args = ap.parse_args()

    if args.reclassify:
        reclassify_existing(dry_run=args.dry_run)
        return

    leagues = [l.strip() for l in args.leagues.split(",") if l.strip() in ESPN_NEWS]

    print("League news ingest — request budget per host (espn-request-budget doctrine):")
    print("  site.api.espn.com: %d  (host_budget=20, disk cache -> re-runs cost 0)" % len(leagues))
    if not args.no_rss:
        print("  deadspin.com: 1 | awfulannouncing.com: 1 | fansided.com: 1 | sbnation.com: 1")
    print("  api.bsky.app: %d" % len(ALL_BLUESKY_QUERIES))

    all_items = []
    if not args.no_espn:
        all_items += collect_espn(leagues)
        print("  collected %d from espn" % sum(1 for i in all_items if i["source"].startswith("espn-")))
    if not args.no_rss:
        before = len(all_items)
        all_items += collect_rss()
        for name, _url in RSS_FEEDS:
            n = sum(1 for i in all_items[before:] if i["source"] == name)
            print("  collected %d from %s" % (n, name))
    before = len(all_items)
    all_items += collect_bluesky()
    print("  collected %d from bluesky" % (len(all_items) - before))

    for it in all_items:
        src_league = it["source"].replace("espn-", "") if it["source"].startswith("espn-") else None
        cls = classify(it["headline"] + " " + it["body"], src_league)
        it.update(cls)

    if args.dry_run:
        from collections import Counter
        print("DRY RUN — %d items collected" % len(all_items))
        print("  by source:", dict(Counter(i["source"] for i in all_items)))
        print("  by layer:", dict(Counter(i["layer"] for i in all_items)))
        return

    inserted, updated = upsert(all_items)
    print("Wrote %d new, %d refreshed rows to news_items" % (inserted, updated))


if __name__ == "__main__":
    main()
