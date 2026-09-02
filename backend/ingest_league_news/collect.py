"""Social collection: X timelines (Nitter), Google News search, Bluesky search."""
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET

from paced_http import Fetcher

from .conversations import CONVERSATION_QUERIES, load_conversations
from .creds import _BSKY_GIVE_UP, _bsky_token
from .fetch import CACHE_DIR, _clean, _iso

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

ALL_BLUESKY_QUERIES = [q for _c, q in CONVERSATION_QUERIES]

BLUESKY_SEARCH = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"  # public.api 403'd 2026-08-06

# Bluesky is a RATE limit, not ESPN's count wall, so the no-retry rule does not
# transfer: measured 2026-08-10, 46 of 72 sequential searches at 0.5s came back
# 403 and every one of them was dropped silently (a failed fetch has no url, and
# upsert skips those rows). Slower pacing plus a short ladder; the whole pass is
# still under three minutes on a nightly cron.
# `host_budget=0` used to sit here, which means "this publisher has no ceiling".
# Bluesky is a free provider and we are a guest on it; declaring no ceiling on a
# free host is the thing we should never do. 120 covers the 100 queries below
# with headroom, and makes the job announce a pause rather than keep pulling.
#
# `retry_waits` went (2, 5) -> (2,). See _BSKY_GIVE_UP: a ladder that treats
# every refusal as transient turned 100 queries into 300 requests, all of them
# to an endpoint that is permanently closed to us.
_BLUE_FETCHER = Fetcher(min_interval=1.5, retry_waits=(2,), cache_dir=CACHE_DIR,
                        cache_ttl=3600, host_budget=120)

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
#
# 2026-08-27, THE MIRROR LADDER WAS BURNING THE FLEET (see newsletter repo's
# corpus/README.md for the full autopsy): every public mirror died the week of
# Aug 24 — nitter.net 410 Gone, xcancel served a cease-and-desist from X Corp,
# and tiekoetter began 429ing all account surfaces while its front page stayed
# 200. The spend report attributed ~130 nitter requests/day to this repo
# against 12/day from the newsletter: two timers/day x (3-mirror probe ladder
# + 15 handles), all of it hammering hosts that rate-limit BY IP — which we
# share with the Innovative Hype brief, the podcast corpus, and everything
# else on this box.
#
# Rules since then, both measured not guessed:
# - ONE attempt per host per run. The ladder below exists only so recovery is
#   automatic the day something comes back; it must never be walked twice in
#   one fire, and no caller may retry it inside a run.
# - When every host fails, print it LOUDLY with the per-host status and stop.
#   A silent empty return reads as "quiet day", which is exactly how the
#   frozen-corpus incident went unnoticed for 2.4 days.
NITTER_INSTANCES = [
    "https://nitter.tiekoetter.com",
    "https://nitter.net",
    "https://xcancel.com",
]

# (handle, league) — the league is the handle's OWN label, which beats guessing.
# @UnderdogMLB is MLB with certainty, where the classifier has to infer it from
# words and gets "Rangers" and "Stars" wrong. None = cross-league, classify it.
#
# Measured 2026-08-10 on the mirror: the league accounts share ZERO posts with
# their parent brand (0 of 20 for each of UnderdogNFL/MLB/NBA against @Underdog,
# and TheAthleticNFL against @TheAthletic), so carrying both is not duplication.
# Posting rates over the 20-post window: UnderdogNFL 83/day, TheAthletic 23,
# UnderdogMLB 22, Underdog 7, TheAthleticNFL 6, UnderdogNBA 4, BleacherReport 3.
# @UnderdogNHL, @UnderdogCFB, @BR_NFL and @BR_NBA do not exist.
X_ACCOUNTS = [
    ("UnderdogNFL", "nfl"),          # 83/day — the densest player-news feed we have
    ("UnderdogMLB", "mlb"),
    ("UnderdogNBA", "nba"),
    ("Underdog", None),              # cross-league desk
    ("TheAthletic", None),
    ("TheAthleticNFL", "nfl"),
    ("TheAthleticNHL", "nhl"),
    ("TheAthleticCFB", "ncaaf"),
    ("BleacherReport", None),
    # The people who BREAK the news. Measured 2026-08-10, usable share of 20
    # rows: Shams 80%, TomBogert 44%, Rosenthal 40%, Friedman 36%, Rapoport 35%,
    # Passan 35%, Yates 25% — the best per-item signal of anything we read, and
    # they are the ones who post availability ("sat out practice", "not
    # travelling") hours before a brand account repackages it.
    ("AdamSchefter", "nfl"), ("RapSheet", "nfl"), ("FieldYates", "nfl"),
    ("ShamsCharania", "nba"),
    ("JeffPassan", "mlb"), ("Ken_Rosenthal", "mlb"),
    ("FriedgeHNIC", "nhl"),
    ("TomBogert", "mls"),
    # Not taken, measured the same way: arielhelwani 0% usable, Brett_McMurphy
    # 5%, PeteThamel 10%, TomPelissero 10% (and ~1 post/day). FabrizioRomano
    # scores well at 63% but is European club soccer — competitions we do not
    # cover, the same trap as the ESPN soccer rollup.
    # NO prediction-market accounts, not even the sport-specific ones. Measured
    # 2026-08-10 on one ruler, rows unclassified / usable: Kalshi 100%/0%,
    # Polymarket 95%/10%, KalshiSports 75%/15%, PrizePicks 65%/5%,
    # PolymarketSport 60%/10% — against 0% unclassified for every
    # league-labelled account above. The sport desks beat their parents and are
    # still below the bar: about half their posts are the brand's own marketing
    # ("Track the Chiefs' championship odds on Polymarket"), and much of the
    # rest is competitions we do not cover.
    #
    # Market signal is a different class of data anyway — probabilities, not
    # news. If we want it, it belongs in the odds pipeline beside the Bovada
    # scraper, not in the narrative desk's chatter pool.
]

# The paid fallback (twitterapi.io, ~$0.15/1k reads) is used ONLY when a key is
# set. Micah, 2026-08-10: "i'm not trying to pay" — so the free mirror is the
# default path and this exists for the day nitter.net goes down again.
X_SEARCH = "https://api.twitterapi.io/twitter/tweet/advanced_search"

_X_FETCHER = Fetcher(min_interval=1.5, retry_waits=(2,), cache_dir=CACHE_DIR,
                     cache_ttl=1800, host_budget=0)

def collect_x():
    """Timelines for X_ACCOUNTS through whichever Nitter mirror is alive."""
    items = []
    instance = None
    probe_failures = []
    # ONE attempt per host per run, first success wins. Every attempt is
    # logged so a dead fleet is VISIBLE in the unit log, not inferred.
    for base in NITTER_INSTANCES:
        url = "%s/%s/rss" % (base, X_ACCOUNTS[0][0])
        try:
            _X_FETCHER.text(url)
            instance = base
            break
        except Exception as e:
            status = getattr(e, "code", None)
            probe_failures.append("%s:%s" % (base.replace("https://", ""),
                                             status or repr(e)[:60]))
            continue
    if instance is None:
        # LOUD skip. Empty output == "quiet day" was the bug class that froze
        # the newsletter corpus for 2.4 days; refuse to look like it.
        print("  x: NO WORKING NITTER MIRROR after %d single attempts (%s) — "
              "skipping X collection this run" %
              (len(NITTER_INSTANCES), "; ".join(probe_failures)))
        return []
    for handle, league in X_ACCOUNTS:
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
                    "league_hint": league,
                    "headline": "[@%s] %s" % (handle, text[:140]),
                    "body": _clean(txt("description")) or text,
                    "url": txt("link"),
                    "published": _iso(txt("pubDate")),
                })
        except Exception as e:
            items.append({"source": "x", "headline": "FETCH ERROR: @%s %s" % (handle, e),
                          "body": "", "url": "", "published": ""})
    return items

# X SEARCH, via Google News. Nitter's /search/rss returns an empty document,
# every RSSHub twitter route is 404/503, and the SearxNG JSON instances refuse
# us — but Google indexes x.com, and `site:x.com <topic>` through the Google
# News RSS endpoint returns real post text on the topic we asked for. That is
# the search we could not otherwise buy (2026-08-10, after Micah: "we need
# search on x ... we need to try try and try again").
#
# The results are CHATTER, never receipts. Google's link is a redirect whose
# guid stopped decoding to the target URL in 2024, so we have the post's words
# and date but no verified permalink or author — signal, not a citable source.
GOOGLE_NEWS_RSS = ("https://news.google.com/rss/search"
                   "?q=%s&hl=en-US&gl=US&ceid=US:en")

_GNEWS_FETCHER = Fetcher(min_interval=1.0, retry_waits=(2,), cache_dir=CACHE_DIR,
                         cache_ttl=1800, host_budget=0)

def collect_x_search(conversations=None):
    """One `site:x.com <seed>` query per conversation.

    NOT WIRED INTO THE RUN, on purpose — see the call site in main(). Google
    returns the post's words with no author and no permalink, so nothing
    downstream can tell a beat reporter from an anonymous account. Kept only
    because it becomes usable the day we can attribute a post to a handle.
    """
    out = []
    for conv in (conversations if conversations is not None else load_conversations()):
        query = "site:x.com %s" % conv["seed"]
        try:
            root = ET.fromstring(_GNEWS_FETCHER.text(
                GOOGLE_NEWS_RSS % urllib.parse.quote(query)))
        except Exception as e:
            out.append({"source": "x-search", "conv_id": conv["id"],
                        "headline": "FETCH ERROR: %s" % e,
                        "body": "", "url": "", "published": ""})
            continue
        for it in root.iter("item"):
            def txt(tag):
                el = it.find(tag)
                return (el.text or "").strip() if el is not None else ""
            text = _clean(txt("title"))
            # Google pads results with X's own corporate and profile pages once
            # it runs out of matching posts.
            if not text or text.startswith("X Business") or " / Posts - x.com" in text:
                continue
            out.append({"source": "x-search", "conv_id": conv["id"],
                        "headline": text[:200], "body": text,
                        "url": txt("link"), "published": _iso(txt("pubDate"))})
    return out

def collect_news_search(conversations=None):
    """Real ARTICLES on each conversation's topic, via Google News search.

    Our anchor pool was whatever the six RSS feeds happened to publish — 1 to 6
    articles per conversation, which is why cards kept serving no receipts. One
    Google News query per seed returns ~100 topic-matched articles from
    publishers we have no feed for at all: the New York Times, the Guardian,
    Variety, CNBC, Yahoo, SI, MLB.com, Goal.com, Front Office Sports.

    These are publishers, not chatter: `source` is the real outlet name from the
    feed, so a receipt reads "The New York Times". They are deliberately left
    UNTAGGED so the conversation-relevance filter judges them. The link is Google's redirect
    — its guid stopped decoding to the target in 2024 and the batchexecute
    resolver no longer answers us — so the chip links through Google rather than
    straight to the outlet. Working link, honest attribution (2026-08-10).
    """
    out = []
    for conv in (conversations if conversations is not None else load_conversations()):
        try:
            root = ET.fromstring(_GNEWS_FETCHER.text(
                GOOGLE_NEWS_RSS % urllib.parse.quote(conv["seed"])))
        except Exception as e:
            out.append({"source": "google-news", "conv_id": conv["id"],
                        "headline": "FETCH ERROR: %s" % e,
                        "body": "", "url": "", "published": ""})
            continue
        for it in list(root.iter("item"))[:25]:
            def txt(tag):
                el = it.find(tag)
                return (el.text or "").strip() if el is not None else ""
            title = _clean(txt("title"))
            if not title:
                continue
            publisher = txt("source") or "google-news"
            # Google appends " - Publisher" to every title; the publisher is
            # already its own field, so drop the duplicate.
            if title.endswith(" - " + publisher):
                title = title[: -(len(publisher) + 3)].strip()
            # NOT tagged with conv_id. Google's relevance is topical but loose
            # — "nba expansion" returns Ice Cube on BIG3, "Leagues Cup
            # scouting" returns matchday previews, "esports worlds" returns a
            # trading-card launch — and a tagged item is chatter, which skips
            # the relevance filter and anchors the card. Leaving them untagged
            # sends them through the anchor path, where the entity bridge that
            # already keeps Messi out of the scouting card judges them too
            # (2026-08-10).
            out.append({"source": publisher.lower()[:40],
                        "headline": title, "body": "", "url": txt("link"),
                        "published": _iso(txt("pubDate"))})
    return out

def tag_conversations(items):
    """Attach X posts to the conversations they are actually about.

    X search is closed to us — Nitter's /search/rss returns an empty document —
    so a timeline pull gives whatever those reporters happened to post, and we
    are left hoping it overlaps the topics the articles are on (Micah,
    2026-08-10). We do not have to hope: the 400 posts we capture every two
    hours are a corpus we own, so search THAT instead. A post that carries a
    conversation's seed terms is chatter for that conversation and reaches its
    card; everything else stays a board item.

    Two guards, both learned the hard way on 2026-08-10:

    - The LEAGUE must match. Without it, TomBogert's MLS transfer posts landed
      in `nfl-media-rights` because "finalizing a deal" and "advanced talks"
      hit the generic words in that seed.
    - Generic sports words never count toward the match. "deal", "talks",
      "rights", "season", "league" and their like appear in every seed and
      every post, so a hit on them means nothing.
    """
    convs = load_conversations()
    generic = {"deal", "deals", "talks", "rights", "season", "league", "team",
               "teams", "game", "games", "news", "player", "players", "sports",
               "picture", "debate", "case", "next", "back", "with", "from"}
    topics = []
    for c in convs:
        words = {w for w in re.sub(r"[^a-z0-9 ]", " ", "%s %s" % (c["seed"], c["title"])).lower().split()
                 if len(w) > 3 and w not in generic}
        if words:
            topics.append((c["id"], c["league"], words))
    tagged = 0
    for it in items:
        if it.get("conv_id"):
            continue
        item_league = it.get("league_hint") or it.get("league")
        if not item_league or item_league == "unclassified":
            continue  # cannot place it; leave it as a board item
        text = re.sub(r"[^a-z0-9 ]", " ", ("%s %s" % (it.get("headline", ""), it.get("body", ""))).lower())
        present = set(text.split())
        best, best_hits = None, 0
        for conv_id, conv_league, words in topics:
            if conv_league != item_league:
                continue
            hits = len(words & present)
            need = 2 if len(words) > 1 else 1
            if hits >= need and hits > best_hits:
                best, best_hits = conv_id, hits
        if best:
            it["conv_id"] = best
            tagged += 1
    return tagged

def collect_bluesky(extra_queries=()):
    items = []
    queries = list(CONVERSATION_QUERIES) + list(OPEN_QUERIES) + list(extra_queries)
    # Authenticate if we can. Fetcher reads self.headers per request, so setting
    # it here applies to every call below without a second Fetcher.
    token = _bsky_token()
    if token:
        _BLUE_FETCHER.headers = dict(_BLUE_FETCHER.headers,
                                     **{"Authorization": "Bearer " + token})
    refusals = 0
    spent = 0
    for i, (conv_id, q) in enumerate(queries):
        if refusals >= _BSKY_GIVE_UP:
            # Fail loudly, and name what was skipped. A collector that quietly
            # returns fewer items is indistinguishable from a quiet news day.
            why = ("the session was accepted but the endpoint still refused — "
                   "that is NEW, investigate before assuming a wall"
                   if token else
                   "app.bsky.feed.searchPosts is gated to unauthenticated "
                   "callers, so the rest would all fail the same way")
            print("  bluesky: %d consecutive refusals — STOPPING, %d queries "
                  "skipped. %s" % (refusals, len(queries) - i, why),
                  file=sys.stderr, flush=True)
            break
        url = BLUESKY_SEARCH + "?q=%s&limit=8" % urllib.parse.quote(q)
        spent += 1
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
            refusals = 0          # it answered; whatever came before was transient
        except Exception as e:
            refusals += 1
            items.append({"source": "bluesky", "conv_id": conv_id,
                          "headline": "FETCH ERROR: %s" % e,
                          "body": "", "url": "", "published": ""})
    # Say what this cost. Rung 6 of the espn-request-budget skill: a silent job
    # is one nobody can size later, and this one is a guest on a free host.
    print("  bluesky: %d/%d queries issued (%s)"
          % (spent, len(queries), "authenticated" if token else "UNAUTHENTICATED"))
    return items
