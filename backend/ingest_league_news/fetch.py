"""Fetching: ESPN news API + RSS feeds, with text/date cleaning helpers."""
import datetime
import email.utils
import html
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

from paced_http import Fetcher

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
    # Added 2026-08-30. Tennis News tab (leagues/tennis?tab=news) reads the
    # combined atp+wta feed via /api/news/atp + /api/news/wta with no rows to
    # combine — verified live, both endpoints return 200/real articles.
    "atp": "https://site.api.espn.com/apis/site/v2/sports/tennis/atp/news?limit=25",
    "wta": "https://site.api.espn.com/apis/site/v2/sports/tennis/wta/news?limit=25",
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
