"""What we display of the news we did NOT write, and in what order.

Two pools reach a user, and only one of them was ever gated:

  * **Conversation cards** (`news_narratives`) — synthesized. The generation path
    refuses to WRITE one with no published reporting behind it. Nothing asked
    again on the way out, so 6 of 14 served cards carry `sources = []`.
  * **Raw items** (`news_items`) — NOT synthesized, shown as-is. Filtered only by
    source and layer, then `ORDER BY published DESC LIMIT 300`. Recency was the
    entire bar.

This module is the bar for both, applied on the serve path where it governs
every row every time, rather than only rows written after a particular deploy.

## What the raw pool actually contained, measured 2026-08-12 (616 displayed)

    retweets, shown as news        50   8.1%   incl. "I'm off this week."
    published 2025 or earlier      15   2.4%   a year old, still on the page
    older than 30 days             72  11.7%
    exact duplicate headlines       8   1.3%   one story, five rows
    -----------------------------------------
    RT + >30 days combined        121  19.6%

The retweets are the instructive case. A blanket ban would be wrong: *"Commanders
LT Laremy Tunsil suffered a torn triceps in practice"* is real injury news that
happens to arrive as a retweet. What is wrong with them is duplication (the same
story five times) and chaff (a reporter announcing a holiday). So retweets are
penalised and deduplicated, never dropped for being retweets.

Every input below is something we can check about the item. None of it asks the
model, or the publisher, how good they think they are.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

# Fraction of the survivors to trim (Micah 2026-08-12: "prune at least the least
# valuable 20%"). "At least" — the hard floors usually take more.
DEFAULT_TRIM = 0.20
MIN_KEEP = 1

# Beyond this, a story is not news any more. 2.4% of the displayed pool was from
# 2025; one MLS item was 356 days old and still on the page.
MAX_AGE_DAYS = 30

# Matches the whole retweet prefix INCLUDING the handle and colon. Stopping at
# "RT by @" left "a: " on the front of the text, so the dedupe key of a retweet
# never equalled the key of the post it quoted and the same story survived five
# times — which is the thing dedupe exists to stop.
_RT = re.compile(r"^\[@[^\]]+\]\s*RT by @[^:]*:\s*", re.I)

# Chaff: a post that is a reporter talking about themselves rather than reporting.
# Matched on the message, not the author — the same account posts real news.
_CHAFF = re.compile(
    r"\b(i'?m off\b|off this week|on vacation|back next week|"
    r"thanks for (having me|watching)|subscribe|link in bio|"
    r"catch (me|us) (on|at)|see you (at|on))",
    re.I,
)

# Publisher tiers. Not a quality judgement about the outlet — a statement about
# how directly the link reaches the reporting. Kept deliberately SMALL: the first
# version of this weighted it 1.5 and the ranking came out backwards, promoting
# "What brought Cole Anthony to the NBL?" over "Bears WR Luther Burden limps off
# field with leg injury". Where a story is published says much less than what it
# is about.
_DIRECT_PUBLISHER = 0.5      # espn.com, nytimes.com, theathletic.com …
_AGGREGATOR = 0.1            # news.google.com redirects
_MIRROR = 0.3                # nitter.net — resolves today (HTTP 200, checked
                             # 2026-08-12) but is one third-party mirror away
                             # from every social receipt we serve

# What the item is ABOUT, which is the strongest signal we have. This is a
# fantasy and props product: a player being ruled out changes a lineup, and a
# league think-piece does not. Ranking without this put an NBL feature above a
# torn triceps.
_LAYER_WEIGHT = {
    "injury": 2.2,
    "trade": 1.8,
    "notable": 1.2,
    "staff": 0.8,
    "narrative": 0.5,
}


def _domain(url: str) -> str:
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _link_weight(url: str) -> float:
    d = _domain(url)
    if not d:
        return 0.0
    if "news.google.com" in d:
        return _AGGREGATOR
    if "nitter" in d:
        return _MIRROR
    return _DIRECT_PUBLISHER


def _age_days(stamp, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((now - when).total_seconds() / 86400.0, 0.0)


# ── raw items (the ones we did not write) ────────────────────────────────────

def item_disqualified(item: dict, now: datetime | None = None) -> str | None:
    """A reason this item must not display, or None. Hard floors only.

    Separate from the score on purpose: a floor is a refusal we will not trade
    away for freshness or a good source, and a ranking always has a top even
    when everything in it is bad.
    """
    now = now or datetime.now(timezone.utc)
    headline = (item.get("headline") or "").strip()
    if not headline:
        return "no headline"
    if _CHAFF.search(headline):
        return "chaff — not reporting"
    age = _age_days(item.get("published"), now)
    if age is not None and age > MAX_AGE_DAYS:
        return f"stale — {age:.0f} days old"
    return None


def item_score(item: dict, now: datetime | None = None) -> float:
    """How much is this item worth showing, higher is better."""
    now = now or datetime.now(timezone.utc)
    headline = (item.get("headline") or "").strip()

    # 1. Freshness. News decays fast; three-day half-life.
    age = _age_days(item.get("published"), now)
    fresh = 3.0 * (0.5 ** (age / 3.0)) if age is not None else 0.5

    # 2. How directly the link reaches the reporting.
    link = _link_weight(item.get("url") or "")

    # 3. Substance. A body is real added content — but its ABSENCE is not a
    #    defect for a wire-style post, where the headline is the whole item, so
    #    this is a bonus and never a penalty. 45% of the pool has no body and
    #    much of it is the best material we carry.
    body = (item.get("body") or "").strip()
    substance = 0.8 if len(body) > 140 else (0.4 if body else 0.0)

    # 4. What it is about. Dominates on purpose — see _LAYER_WEIGHT.
    layer = _LAYER_WEIGHT.get((item.get("layer") or "").lower(), 0.5)

    # 5. Named player, a small bonus on top of the layer. Small because
    #    key_player is blank on 84% of the pool, so it cannot carry the ranking
    #    — a signal that sparse would silently rank on its own absence.
    named = 0.4 if (item.get("key_player") or "").strip() else 0.0

    # 6. Retweet penalty. Not a ban: an RT of real injury news is real injury
    #    news. It is second-hand and usually duplicated, so it loses to the
    #    same story first-hand.
    rt = -0.7 if _RT.match(headline) else 0.0

    return fresh + link + substance + layer + named + rt


def _dedupe_key(item: dict) -> str:
    """Collapse one story arriving several times.

    Strips the `[@handle] RT by @handle:` prefix first, so a retweet and the post
    it quotes land on the same key and only the better-scoring one survives.
    """
    h = (item.get("headline") or "").lower()
    h = _RT.sub("", h)
    h = re.sub(r"^\[@[^\]]+\]\s*", "", h)
    return re.sub(r"[^a-z0-9]+", " ", h).strip()[:60]


def rank_items(items: Iterable[dict], *, trim: float = DEFAULT_TRIM,
               min_keep: int = MIN_KEEP, now: datetime | None = None,
               explain: bool = False) -> list[dict]:
    """Floor, deduplicate, rank, then trim the worst `trim` of what survives."""
    now = now or datetime.now(timezone.utc)
    kept: dict[str, dict] = {}
    for it in items:
        if item_disqualified(it, now):
            continue
        it = dict(it)
        s = item_score(it, now)
        if explain:
            it["quality"] = {"score": round(s, 2)}
        it["_score"] = s
        key = _dedupe_key(it)
        # Keep the best copy of a story, not the first one we happened to read.
        if key not in kept or s > kept[key]["_score"]:
            kept[key] = it

    ranked = sorted(kept.values(), key=lambda i: i["_score"], reverse=True)
    if not ranked:
        return []
    keep_n = max(min_keep, math.ceil(len(ranked) * (1.0 - trim)))
    out = ranked[:keep_n]
    for it in out:
        it.pop("_score", None)
    return out


# ── synthesized cards ────────────────────────────────────────────────────────

def card_has_receipts(card: dict) -> bool:
    """The floor for a synthesized card: something published stands behind it.

    Reads the receipts, not `source_count` — that column is written at
    generation, and a stale count must not be able to promote an empty card.
    """
    return bool(card.get("sources"))


def card_score(card: dict, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    sources = card.get("sources") or []
    receipts = math.log1p(len(sources)) * 2.0
    # Independent outlets: three receipts from one publisher is one source cited
    # three times. Google News collapses to a single domain, which is the point.
    outlets = {d for d in (_domain(s.get("url", "")) for s in sources) if d}
    independence = math.log1p(len(outlets)) * 1.5
    age = _age_days(card.get("story_time") or card.get("generated_at"), now)
    fresh = 2.5 * (0.5 ** (age / 3.0)) if age is not None else 0.0
    complete = sum(0.5 for f in ("narrative", "paragraph", "fan_voice")
                   if (card.get(f) or "").strip())
    return receipts + independence + fresh + complete


def rank_cards(cards: Iterable[dict], *, trim: float = DEFAULT_TRIM,
               min_keep: int = MIN_KEEP, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    kept = []
    for c in cards:
        if not card_has_receipts(c):
            continue
        c = dict(c)
        sources = c.get("sources") or []
        c["quality"] = {
            "score": round(card_score(c, now), 2),
            "receipts": len(sources),
            "outlets": len({d for d in (_domain(s.get("url", "")) for s in sources) if d}),
        }
        kept.append(c)
    kept.sort(key=lambda c: c["quality"]["score"], reverse=True)
    if not kept:
        return []
    keep_n = max(min_keep, math.ceil(len(kept) * (1.0 - trim)))
    return kept[:keep_n]
