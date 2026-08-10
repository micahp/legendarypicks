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
import datetime
import email.utils
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paced_http import Fetcher  # noqa: E402
from news_classifier import classify, entities  # noqa: E402

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
    # Added 2026-08-10. The cross-border conversation had no article anchors
    # because usa.1 is the MLS wire and nothing else: Liga MX and the tournament
    # itself were invisible to us.
    "leaguescup": "https://site.api.espn.com/apis/site/v2/sports/soccer/concacaf.leagues.cup/news?limit=25",
    "ligamx": "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/news?limit=25",
    # ESPN's SPORT-WIDE soccer rollup. NOT in the default league list — measured
    # 2026-08-10 and it is a net negative today: of 50 items, 84% are
    # competitions we do not cover (Premier League, La Liga, WAFCON, A-League,
    # NWSL), and the 16% that DO classify are mostly wrong — "Rangers CEO" went
    # to mlb (Texas Rangers), "Chicago Stars vs Bay FC" to nhl (Dallas Stars),
    # a WAFCON report to nfl. Soccer club names collide with North American
    # ones across every sport, and the classifier has no sport context to
    # separate them. Opt in with --leagues soccerall to test; wiring it into
    # the nightly run needs that guard first.
    "soccerall": "https://site.api.espn.com/apis/site/v2/sports/soccer/all/news?limit=50",
}
# ESPN's feed key -> the league we file it under. Leagues Cup is MLS *and*
# Liga MX; per PLAN §10 it files under mls for now. Liga MX items get no hint —
# the classifier decides from the text rather than us mislabelling them.
_ESPN_LEAGUE_HINT = {"leaguescup": "mls", "ligamx": None, "soccerall": None}
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
_DEFAULT_CONVERSATIONS = [
    {"id": "mlb-salary-cap", "league": "mlb", "title": "Salary cap debate",
     "seed": "dodgers salary cap"},
    {"id": "mls-pro-rel", "league": "mls", "title": "Promotion/relegation",
     "seed": "mls relegation promotion"},
    # Seeded 2026-08-09 from the FS1 booth during América–Portland (Leagues Cup):
    # MLS clubs are spending real transfer fees on Liga MX players, and the
    # broadcast's argument was that Leagues Cup makes that spend SAFER — you now
    # watch the player against both leagues' opposition on a regular basis — while
    # for a smaller Liga MX club the few million coming back can make or break a
    # season. Receipts in the window: Berterame Monterrey->Inter Miami ~$15M,
    # Bogusz Cruz Azul->Houston ~$10M.
    {"id": "mls-ligamx-spending", "league": "mls", "title": "Cross-border spending",
     "seed": "MLS Liga MX transfer"},
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


def load_conversations():
    """Conversations come from `news_conversations`, not from this file.

    A topic must not need a code edit and a deploy (Micah, 2026-08-10) — and
    the DB rows are also what the discovery pass learns from, since an approved
    topic is a positive label (see discover_topics.py). The list above is the
    seed data for a fresh DB and the fallback when the table is empty or
    unreachable; `--sync-conversations` writes it in.
    """
    try:
        import sqlite3
        db_path = os.environ.get("LP_DB_PATH") or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
        con = sqlite3.connect(db_path)
        rows = con.execute(
            """SELECT id, league, title, seed FROM news_conversations
               WHERE active=1 ORDER BY created_at""").fetchall()
        con.close()
        if rows:
            return [{"id": r[0], "league": r[1], "title": r[2], "seed": r[3]}
                    for r in rows]
    except Exception:
        pass
    return list(_DEFAULT_CONVERSATIONS)


def sync_conversations():
    """Write the built-in defaults into news_conversations (idempotent)."""
    import sqlite3
    from _core import _init_db as _core_init_db
    _core_init_db()
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db_path)
    n = 0
    for c in _DEFAULT_CONVERSATIONS:
        cur = con.execute(
            """INSERT INTO news_conversations(id, league, title, seed, origin)
               VALUES (?,?,?,?, 'dictated') ON CONFLICT(id) DO NOTHING""",
            (c["id"], c["league"], c["title"], c["seed"]))
        n += cur.rowcount
    con.commit()
    total = con.execute("SELECT count(*) FROM news_conversations WHERE active=1").fetchone()[0]
    con.close()
    print("Synced %d new conversations (%d active)" % (n, total))


CONVERSATIONS = load_conversations()

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

# OPEN queries — deliberately tied to NO conversation. Every social row used to
# come from a seed, which meant the corpus's chatter could only ever be about
# topics we had already named, and "chatter converges with articles" — the
# heaviest term in the discovery score — could only fire next to an existing
# seed. These sample each league broadly so a conversation nobody named can
# still show up in social (Micah, 2026-08-10: "we aren't just searching for
# topics i mentioned right?").
_OPEN_LEAGUES = ["NFL", "MLB", "NBA", "NHL", "MLS", "UFC",
                 "college football", "esports"]
OPEN_QUERIES = [(None, lg) for lg in _OPEN_LEAGUES] + \
               [(None, "%s fans" % lg) for lg in _OPEN_LEAGUES]

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
# Bluesky is a RATE limit, not ESPN's count wall, so the no-retry rule does not
# transfer: measured 2026-08-10, 46 of 72 sequential searches at 0.5s came back
# 403 and every one of them was dropped silently (a failed fetch has no url, and
# upsert skips those rows). Slower pacing plus a short ladder; the whole pass is
# still under three minutes on a nightly cron.
_BLUE_FETCHER = Fetcher(min_interval=1.5, retry_waits=(2, 5), cache_dir=CACHE_DIR,
                        cache_ttl=3600, host_budget=0)


_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]{0,200}>")


def _clean(text: str) -> str:
    """Publisher text as a reader should see it.

    Feeds hand us escaped entities, and SB Nation's Atom escapes them TWICE —
    the reader saw the literal `Purdue&#8217;s new AD` on the news page
    (Micah, 2026-08-09). Unescape until stable (bounded), drop any markup the
    unescape revealed, collapse whitespace.
    """
    s = (text or "").strip()
    for _ in range(3):
        if "&" not in s:
            break
        u = html.unescape(s)
        if u == s:
            break
        s = u
    if "<" in s:
        s = _TAG_RE.sub(" ", s)
    return " ".join(s.split())


def _iso(published: str) -> str:
    """Normalize any publisher date to UTC ISO 8601 so ORDER BY published works.

    `published` is sorted as TEXT in SQL, so every row must share one shape.
    RFC 822 ("Thu, 06 Aug 2026 23:00:40 +0000"), ISO with an offset
    ("2026-08-06T17:39:23-04:00") and ISO Zulu all become "...THH:MM:SSZ".
    An unparseable value is returned as-is rather than dropped.
    """
    p = (published or "").strip()
    if not p:
        return ""
    dt = None
    if "," in p or p[:3].isalpha():
        try:
            dt = email.utils.parsedate_to_datetime(p)
        except Exception:
            dt = None
    if dt is None:
        try:
            dt = datetime.datetime.fromisoformat(p.replace("Z", "+00:00"))
        except Exception:
            return p
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


# ESPN's www host 403s this datacenter IP for every user agent (measured
# 2026-08-10: identical 919-byte refusal for curl, Safari, Googlebot and
# facebookexternalhit — it is an edge block, not UA sniffing). The article
# itself is served as JSON, with the FULL story body, by the now.core API host,
# which answers us fine. ESPN blocks per host, not per IP.
_STORY_API = "https://now.core.api.espn.com/v1/sports/news/%s"
_STORY_ID_RE = re.compile(r"/id/(\d+)")


def fetch_espn_story(url_or_id):
    """Full text of one ESPN story, by article URL or id.

    The news feeds carry a headline and a one-line description; the argument
    lives in the body. This is how a feature we find by hand becomes a real
    citable receipt in the corpus instead of a link we cannot read.
    """
    m = _STORY_ID_RE.search(str(url_or_id))
    story_id = m.group(1) if m else str(url_or_id).strip()
    d = _ESPN_FETCHER.json(_STORY_API % story_id)
    heads = d.get("headlines") or []
    if not heads:
        return None
    h = heads[0]
    body = _clean(_TAG_RE.sub(" ", h.get("story") or ""))
    links = h.get("links") or {}
    web = (links.get("web") or {}).get("href") or ""
    return {
        "source": "espn-feature",
        "headline": _clean(h.get("headline", "")),
        "body": body or _clean(h.get("description", "")),
        "url": web or "https://www.espn.com/story/_/id/%s" % story_id,
        "published": _iso(h.get("published", "")),
    }


def collect_espn(leagues):
    items = []
    for league in leagues:
        url = ESPN_NEWS[league]
        try:
            d = _ESPN_FETCHER.json(url)
            for a in d.get("articles", []):
                items.append({
                    "source": "espn-" + league,
                    "headline": _clean(a.get("headline", "")),
                    "body": _clean(a.get("description", "")),
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
                items.append({"source": name, "headline": _clean(title),
                              "body": _clean(desc), "url": link,
                              "published": _iso(txt("pubDate") or txt("updated"))})
        except Exception as e:
            items.append({"source": name, "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    return items


def trending_queries(article_items, limit=12):
    """Search social for what the ARTICLES are about this run.

    Micah, 2026-08-10: "maybe we use topics in the articles we find in that run
    and search social media about them." This is the third leg of the corpus:
    seeded queries follow topics we named, open league queries sample broadly,
    and these follow the news itself — so chatter arrives on a story the day it
    breaks instead of only where a seed happens to sit.

    A topic must appear in TWO different articles to qualify: one headline is an
    event, two is a story.
    """
    from collections import Counter
    counts = Counter()
    for it in article_items:
        if it.get("source") == "bluesky":
            continue
        if (it.get("headline") or "").startswith("FETCH ERROR"):
            continue
        for e in entities(it.get("headline", "")):
            counts[e] += 1
    return [(None, e) for e, n in counts.most_common(limit * 3) if n >= 2][:limit]


# X / Twitter, free, via a Nitter mirror. The accounts that sent us to social in
# the first place are all here: Underdog, PrizePicks, Polymarket, Kalshi.
#
# Two corrections from 2026-08-10 worth keeping. The handle is @Underdog, NOT
# @UnderdogFantasy — testing the wrong handle is what produced an earlier "not
# on any mirror" conclusion. And nitter.net serves these timelines fine; most
# other instances are dead (502, expired certs, NXDOMAIN) or challenge us.
#
# TIMELINES ONLY. Nitter's /search/rss returns an empty document — X's search
# endpoint is closed to it — so keyword queries stay on Bluesky. That is fine:
# we came here for these accounts' own posts, not for search.
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacyredirect.com",
    "https://nitter.tiekoetter.com",
]
X_ACCOUNTS = [
    "Underdog", "UnderdogNFL",      # props desk + its NFL feed
    "PrizePicks",                    # props
    "Polymarket", "Kalshi",          # prediction markets
    "ActionNetworkHQ",               # betting media
    "AdamSchefter",                  # NFL news breaker
]
# The paid fallback (twitterapi.io, ~$0.15/1k reads) is used ONLY when a key is
# set. Micah, 2026-08-10: "i'm not trying to pay" — so the free mirror is the
# default path and this exists for the day nitter.net goes down again.
X_SEARCH = "https://api.twitterapi.io/twitter/tweet/advanced_search"


def _x_key():
    return os.environ.get("LP_XAPI_KEY", "").strip()


_X_FETCHER = Fetcher(min_interval=1.5, retry_waits=(2,), cache_dir=CACHE_DIR,
                     cache_ttl=1800, host_budget=0)


def collect_x():
    """Timelines for X_ACCOUNTS through whichever Nitter mirror is alive."""
    items = []
    instance = None
    for base in NITTER_INSTANCES:
        try:
            _X_FETCHER.text("%s/%s/rss" % (base, X_ACCOUNTS[0]))
            instance = base
            break
        except Exception:
            continue
    if instance is None:
        print("  x: no working nitter mirror (tried %d)" % len(NITTER_INSTANCES))
        return []
    for handle in X_ACCOUNTS:
        try:
            root = ET.fromstring(_X_FETCHER.text("%s/%s/rss" % (instance, handle)))
            for it in root.iter("item"):
                def txt(tag):
                    el = it.find(tag)
                    return (el.text or "").strip() if el is not None else ""
                text = _clean(txt("title"))
                if not text:
                    continue
                items.append({
                    "source": "x",
                    "headline": "[@%s] %s" % (handle, text[:140]),
                    "body": _clean(txt("description")) or text,
                    "url": txt("link"),
                    "published": _iso(txt("pubDate")),
                })
        except Exception as e:
            items.append({"source": "x", "headline": "FETCH ERROR: @%s %s" % (handle, e),
                          "body": "", "url": "", "published": ""})
    return items


def collect_bluesky(extra_queries=()):
    items = []
    for conv_id, q in list(CONVERSATION_QUERIES) + list(OPEN_QUERIES) + list(extra_queries):
        url = BLUESKY_SEARCH + "?q=%s&limit=8" % urllib.parse.quote(q)
        try:
            d = _BLUE_FETCHER.json(url)
            for p in d.get("posts", []):
                rec = p.get("record", {})
                text = _clean(rec.get("text", ""))
                author = p.get("author", {}).get("handle", "?")
                post_uri = p.get("uri", "") or rec.get("uri", "")
                items.append({
                    "source": "bluesky",
                    "conv_id": conv_id,
                    "headline": "[@%s] %s" % (author, text[:140]),
                    "body": text,
                    "url": "https://bsky.app/profile/%s/post/%s"
                           % (author, post_uri.rsplit("/", 1)[-1]),
                    # indexedAt lives on the POST; the record carries createdAt.
                    # Reading rec["indexedAt"] gave every bluesky row an EMPTY
                    # published (244 of them), which hid social from the
                    # discovery window and made "chatter converges with
                    # articles" impossible to ever detect (2026-08-10).
                    "published": _iso(p.get("indexedAt") or rec.get("createdAt") or ""),
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


def repair_stored_text(dry_run=False):
    """Re-clean headline/body and re-normalize published for stored rows.

    The collector now cleans on the way in; rows collected before that carry
    the raw publisher text (`Purdue&#8217;s`) and mixed date shapes (RFC 822
    from three feeds, ISO from the rest), and `published` is sorted as TEXT —
    so "Thu, 06 Aug..." outranked every ISO row regardless of date. No network.
    """
    import sqlite3
    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT id, headline, body, published FROM news_items").fetchall()
    text_fixed = date_fixed = 0
    for rid, headline, body, published in rows:
        h, b, p = _clean(headline), _clean(body), _iso(published)
        if h != (headline or "") or b != (body or ""):
            text_fixed += 1
        if p != (published or ""):
            date_fixed += 1
        if not dry_run and (h != headline or b != body or p != published):
            con.execute(
                "UPDATE news_items SET headline=?, body=?, published=? WHERE id=?",
                (h, b, p, rid))
    con.commit()
    con.close()
    print("Repaired text on %d rows, dates on %d rows (%d scanned)%s"
          % (text_fixed, date_fixed, len(rows), " (dry run)" if dry_run else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues",
                    default="nfl,mlb,mls,ncaaf,nba,nhl,ufc,leaguescup,ligamx",
                    help="comma list of ESPN leagues to collect")
    ap.add_argument("--no-espn", action="store_true")
    ap.add_argument("--no-rss", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--reclassify", action="store_true",
                    help="re-run the classifier over stored rows (no network)")
    ap.add_argument("--repair-text", action="store_true",
                    help="re-clean stored headline/body + normalize published (no network)")
    ap.add_argument("--sync-conversations", action="store_true",
                    help="write the built-in conversation defaults into the DB")
    ap.add_argument("--ingest-story", default="",
                    help="ESPN article URL or id -> full body into news_items")
    args = ap.parse_args()

    if args.ingest_story:
        it = fetch_espn_story(args.ingest_story)
        if not it:
            print("no story found for %s" % args.ingest_story)
            return
        it.update(classify(it["headline"] + " " + it["body"], None))
        print("  %s [%s/%s] %d chars" % (it["headline"][:70], it["league"],
                                         it["layer"], len(it["body"])))
        if not args.dry_run:
            print("  wrote %d new, %d refreshed" % upsert([it]))
        return

    if args.sync_conversations:
        sync_conversations()
        return

    if args.reclassify:
        reclassify_existing(dry_run=args.dry_run)
        return

    if args.repair_text:
        repair_stored_text(dry_run=args.dry_run)
        return

    leagues = [l.strip() for l in args.leagues.split(",") if l.strip() in ESPN_NEWS]

    print("League news ingest — request budget per host (espn-request-budget doctrine):")
    print("  site.api.espn.com: %d  (host_budget=20, disk cache -> re-runs cost 0)" % len(leagues))
    if not args.no_rss:
        print("  deadspin.com: 1 | awfulannouncing.com: 1 | fansided.com: 1 | sbnation.com: 1")
    print("  api.bsky.app: %d (%d seeded + %d open)"
          % (len(ALL_BLUESKY_QUERIES) + len(OPEN_QUERIES),
             len(ALL_BLUESKY_QUERIES), len(OPEN_QUERIES)))

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
    trending = trending_queries(all_items)
    if trending:
        print("  article-derived social queries: %s"
              % ", ".join(q for _c, q in trending))
    all_items += collect_bluesky(trending)
    print("  collected %d from bluesky" % (len(all_items) - before))
    before = len(all_items)
    all_items += collect_x()
    got = len(all_items) - before
    if got:
        print("  collected %d from x" % got)

    # A failed fetch is recorded as an item with an empty url, and upsert skips
    # exactly those rows — so a source that died looked identical to a source
    # with no news: no row, no error, no log line. Say it out loud instead
    # (2026-08-09: a conversation collected nothing and nothing reported it).
    errors = [i for i in all_items if i["headline"].startswith("FETCH ERROR")]
    if errors:
        from collections import Counter as _C
        print("  FETCH FAILURES (not stored, not counted above):")
        for src, n in _C(i["source"] for i in errors).most_common():
            first = next(i["headline"] for i in errors if i["source"] == src)
            print("    %-16s %d  %s" % (src, n, first[:90]))

    for it in all_items:
        src_league = it["source"].replace("espn-", "") if it["source"].startswith("espn-") else None
        if src_league in _ESPN_LEAGUE_HINT:
            src_league = _ESPN_LEAGUE_HINT[src_league]
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
