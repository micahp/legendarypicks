"""Put a link the editor sent into a conversation's pool.

    LP_DB_PATH=... python3 add_conversation_link.py <conv_id> <url> [<url> ...]
    LP_DB_PATH=... python3 add_conversation_link.py --route <url> [<url> ...]

WHY THIS EXISTS
---------------
Micah, 2026-08-13: "ill evaluate cards on the site and send you links i want
part of the conversation. im not sifting through every article or post."

That is the whole design constraint. Every automatic path we have answers a
question the machine can answer — what IS this item (`post_role`), which
conversation is it about (`route_conversations`) — and none of them answers the
one that decides whether a card is worth reading. Ranking candidates for review
just moves the sifting; it does not remove it. So the editor's input is a
handful of URLs, and everything else stays automatic.

WHAT AN EDITOR'S LINK ASSERTS, AND WHAT IT DOES NOT
---------------------------------------------------
It asserts RELEVANCE: this belongs in that conversation, no score required.
It asserts nothing about PROVENANCE. A tweet someone sent us is still a tweet,
and it is stored with its real source and its `[@handle]` prefix so that
`is_social`, `post_role` and every downstream check classify it exactly as they
would have if the collector had found it. A link is a decision about what the
conversation is about, never a promotion to publisher — that distinction is the
one that let 855 tweets ride through as verified sources, and a hand-delivered
URL is not a reason to reopen it.

The counterpart rule lives in `route_conversations`: evidence the ROUTER finds
accumulates, evidence the EDITOR sends counts. A card should not be rewritten
because its pool gained a box score (Micah: "no we didnt need to regenerate
that card"), but it should absolutely be rewritten when he says a story belongs
in it.
"""
import argparse
import html
import json
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import _init_db  # noqa: E402
from ingest_league_news import CONVERSATIONS  # noqa: E402

_UA = "Mozilla/5.0 (compatible; LegendaryPicks/1.0)"
_TWEET = re.compile(r"^https?://(?:www\.)?(?:x|twitter)\.com/([^/]+)/status/(\d+)")
_BSKY = re.compile(r"^https?://bsky\.app/profile/([^/]+)/post/([^/?#]+)")
# X's public embed endpoint. No auth, no login wall, and no scraping of the
# rendered page: it is the same JSON the official embed widget reads. Nitter
# mirrors were tried first (2026-08-13) — nitter.net returns empty bodies and
# xcancel sits behind a JS challenge — so this is the path that actually works
# from this box.
_SYNDICATION = ("https://cdn.syndication.twimg.com/tweet-result"
                "?id=%s&token=a&lang=en")


def _fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _resolve_tweet(handle, status_id):
    d = json.loads(_fetch(_SYNDICATION % status_id))
    author = (d.get("user") or {}).get("screen_name") or handle
    text = " ".join((d.get("text") or "").split())
    return {
        "source": "x",
        # The collector's prefix, deliberately. `is_social` recognises a post by
        # SHAPE as well as by source name, and an item that skipped the prefix
        # would be the one row in the corpus that only one of those two guards
        # can see.
        "headline": "[@%s] %s" % (author, text[:140]),
        "body": text,
        "published": (d.get("created_at") or "")[:19],
    }


# "Deadspin | Colts, RB Jonathan Taylor agree to extension" — `og:title` is
# written for a browser tab, so most publishers bolt their own masthead onto
# it. Left in, the outlet lands in the subject slot of a numbered prompt item,
# which is what the name-drop rules already forbid in the prose, and
# `credited_outlets` would read it as an attribution the card never made.
_MASTHEAD = re.compile(r"^\s*[^|—–\-]{2,28}\s*[|—–]\s*|\s*[|—–]\s*[^|—–]{2,28}\s*$")


def _strip_masthead(title):
    cut = _MASTHEAD.sub("", title).strip()
    # Only if something survives: "ESPN.com" as the entire title is a fetch
    # that failed in a way worth seeing, not a headline to be emptied.
    return cut if len(cut) >= 20 else title


def _wayback(url):
    """The most recent snapshot, for publishers that refuse this box.

    ESPN and PFR return 403 to our datacenter IP regardless of headers. A 403
    is not an unanswerable question — the archive has the page, and an editor
    handing over a link should not be told "unreachable" for a story that is
    plainly readable from his laptop.
    """
    try:
        d = json.loads(_fetch("https://archive.org/wayback/available?url=%s"
                              % urllib.parse.quote(url, safe="")))
        snap = ((d.get("archived_snapshots") or {}).get("closest") or {})
        return _fetch(snap["url"]) if snap.get("available") else ""
    except Exception:
        return ""


def _resolve_page(url):
    try:
        doc = _fetch(url)
    except Exception:
        doc = _wayback(url)
    if not doc:
        return None
    def meta(*names):
        for n in names:
            m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+'
                          r'content=["\']([^"\']+)' % re.escape(n), doc, re.I)
            if m:
                return html.unescape(m.group(1)).strip()
        return ""
    title = meta("og:title", "twitter:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", doc, re.I | re.S)
        title = html.unescape(m.group(1)).strip() if m else ""
    return {
        "source": urllib.parse.urlparse(url).netloc.replace("www.", ""),
        "headline": _strip_masthead(" ".join(title.split()))[:300],
        "body": meta("og:description", "description"),
        "published": meta("article:published_time")[:19],
    }


def resolve(url):
    """{source, headline, body, published} for a URL, or None if unreachable."""
    m = _TWEET.match(url)
    if m:
        return _resolve_tweet(m.group(1), m.group(2))
    m = _BSKY.match(url)
    if m:
        # Bluesky's public AppView needs no auth either.
        at = ("https://public.api.bsky.app/xrpc/app.bsky.feed.getPosts"
              "?uris=at://%s/app.bsky.feed.post/%s"
              % (urllib.parse.quote(m.group(1)), m.group(2)))
        d = json.loads(_fetch(at))
        p = (d.get("posts") or [None])[0]
        if not p:
            return None
        text = " ".join(((p.get("record") or {}).get("text") or "").split())
        return {"source": "bluesky",
                "headline": "[@%s] %s" % ((p.get("author") or {}).get("handle", "?"),
                                          text[:140]),
                "body": text,
                "published": ((p.get("record") or {}).get("createdAt") or "")[:19]}
    return _resolve_page(url)


def add(con, conv_id, url, item=None):
    """Insert or re-home one URL. Returns (action, headline)."""
    conv = next((c for c in CONVERSATIONS if c["id"] == conv_id), None)
    if conv is None:
        raise SystemExit("unknown conversation: %s (have: %s)"
                         % (conv_id, ", ".join(c["id"] for c in CONVERSATIONS)))
    row = con.execute("SELECT id, conv_id, headline FROM news_items WHERE url=?",
                      (url,)).fetchone()
    if row:
        # Already collected, just never placed — the common case for anything
        # off the X timelines, where 874 of 1,033 rows match no seed word.
        con.execute("UPDATE news_items SET conv_id=? WHERE id=?",
                    (conv_id, row["id"]))
        return ("re-homed from %r" % (row["conv_id"] or "untagged"),
                row["headline"])
    it = item or resolve(url)
    if not it or not it.get("headline"):
        return ("UNRESOLVED", url)
    con.execute(
        """INSERT INTO news_items(league, layer, source, headline, body, url,
                                  published, conv_id)
           VALUES (?, 'narrative', ?, ?, ?, ?, ?, ?)
           ON CONFLICT(url) DO UPDATE SET conv_id=excluded.conv_id""",
        (conv["league"], it["source"], it["headline"], it.get("body") or "",
         url, it.get("published") or "", conv_id))
    return ("added", it["headline"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conv_id", nargs="?",
                    help="conversation to file these under")
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--route", action="store_true",
                    help="let route_conversations pick the conversation")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.route and args.conv_id:
        args.urls.insert(0, args.conv_id)
        args.conv_id = None
    if not args.route and not args.conv_id:
        raise SystemExit("give a conv_id, or pass --route")

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    _init_db()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    profiles = None
    if args.route:
        from route_conversations import conversation_profiles, route
        profiles = conversation_profiles(con)

    for url in args.urls:
        conv_id = args.conv_id
        item = None
        if profiles is not None:
            item = resolve(url)
            if not item:
                print("  UNRESOLVED %s" % url)
                continue
            # The router is a SUGGESTION here, and a refusal is not a rejection
            # of the link — it means no conversation is a clear home, which is
            # exactly when a human should name one rather than have a tie
            # broken for them.
            guess, best, margin = route(
                dict(item, league=None, headline=item["headline"]), profiles)
            if not guess:
                print("  NO CLEAR HOME (score %d, margin %d) — name a conv_id "
                      "for: %s" % (best, margin, item["headline"][:70]))
                continue
            conv_id = guess
        action, head = add(con, conv_id, url, item)
        print("  %-24s %-12s %s" % (conv_id, action, (head or "")[:70]))
    if args.dry_run:
        con.rollback()
        print("(dry run — nothing written)")
    else:
        con.commit()
    con.close()


if __name__ == "__main__":
    main()
