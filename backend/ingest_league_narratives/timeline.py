"""timeline helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from .editor import _BODY_CHARS  # noqa: E402
from .roles import is_social  # noqa: E402

_FRESH_DAYS = 21     # newer than this is a DEVELOPMENT; older is BACKGROUND

def _age_days(it, today=None):
    """Days between an item's publish date and today. None when undated."""
    when = (it.get("published") or "")[:10]
    try:
        pub = datetime.date.fromisoformat(when)
    except ValueError:
        return None
    return ((today or datetime.date.today()) - pub).days

def is_background(it, today=None):
    """True when this item describes an already-established state, not news.

    The distinction the card kept getting wrong. A 2025 ESPN feature titled
    "How Leagues Cup is becoming a hotbed for global scouting" scored highest
    in its conversation — it is the single most on-topic article we hold — so
    it supplied the card's one-sentence hook, and the card announced that the
    Leagues Cup "becomes a global scouting stage" in August 2026. Micah:
    "as if that article that talked about it being a proving ground didn't
    come out last year. Leagues Cup is already a proving ground and them
    signing him is proof. it's maturing."

    Relevance ranking has no opinion about time, so the oldest item in a pool
    can be its strongest, and nothing downstream noticed the tense was a year
    late. An undated item is treated as background: we cannot claim it is new.
    """
    age = _age_days(it, today)
    return age is None or age > _FRESH_DAYS

def split_by_age(items, today=None):
    """(developments, background), each as (index, item) with the index the
    item holds in `items` — the number the prompt shows and `_cited_sources`
    resolves against. Grouping must never renumber."""
    fresh, old = [], []
    for i, it in enumerate(items):
        (old if is_background(it, today) else fresh).append((i, it))
    return fresh, old

def stale_anchor(gen, shown, today=None):
    """True when a card cites ONLY background while fresh reporting was in
    front of it — the shape that dated the Leagues Cup card by a year.

    Reported, never fatal: a card standing entirely on background can be
    correct (the state of play has not moved). It is a finding when there were
    developments available and the card reached past them anyway.

    Only PUBLISHED developments count. A social post can never legitimately
    become a source chip — that is what the SOCIAL LEAK check exists to stop —
    so a pool whose only fresh items are posts leaves the card no citable
    development, and citing background is then the correct answer rather than
    a defect. Measured 2026-08-12: `mls-leaguescup-proving` was flagged with
    three developments in front of it, all three of them bluesky/x posts, while
    the card was already carrying them properly as fan voice ("posts note
    Santos Laguna has lost three straight"). A check that demands a citation
    the rules forbid is asking for the leak.
    """
    cited = {(s.get("url") or "") for s in gen.get("sources") or []}
    if not cited:
        return False
    fresh, _old = split_by_age(shown, today)
    fresh = [(i, it) for i, it in fresh if not is_social(it)]
    if not fresh:
        return False
    return not any((it.get("url") or "") in cited for _i, it in fresh)

def pool_key(shown, marks=""):
    """Fingerprint of the material a card was written from.

    Same fingerprint means the same items and the same editor marks, so
    regenerating can only produce different WORDS for an unchanged story. The
    urls, not the count: an item swapped for another of equal age would leave a
    count identical and the story different.
    """
    urls = sorted((it.get("url") or "") for it in shown)
    h = hashlib.sha1()
    h.update("\n".join(urls).encode("utf-8"))
    h.update(b"\x00")
    h.update((marks or "").encode("utf-8"))
    return h.hexdigest()

def newest_item(shown):
    """The publish timestamp of the freshest item shown, '' if none is dated."""
    return max([(it.get("published") or "") for it in shown] or [""])

def _numbered(items, limit=None, today=None):
    """The item list as the model sees it, split into DEVELOPMENTS and
    BACKGROUND.

    Real articles carry an EXCERPT of their body, not just a headline. The
    argument lives in the body: a 7,500-character ESPN feature quoting MLS
    executives on the record reached the model as a single headline, so the
    card could not use one quote or figure from it (2026-08-10). Bluesky posts
    are already their own full text and need no excerpt.

    The DATE alone was not enough. Every item already carried its publish date
    and the instruction to mind it, and the card still wrote a year-old feature
    as today's development — a date on line 1 of ten is a fact the model has to
    act on, a header it has to read past. The two groups say which items the
    present tense belongs to. Numbering is the item's index in `items` either
    way, because `_cited_sources` resolves citations by that number.
    """
    lines = {}
    for i, it in enumerate(items if limit is None else items[:limit]):
        real = not is_social(it)
        url = (" " + it["url"]) if real and it.get("url") else ""
        # The DATE, always. The ESPN scouting feature is from 2025 and the card
        # reported it as current, because the model had no way to know (Micah,
        # 2026-08-10: "it's dated in 2025. we must include that info when
        # sending to model so it's able to understand time").
        when = (it.get("published") or "")[:10]
        stamp = (" (%s)" % when) if when else " (date unknown)"
        tag = it["source"] if real else ("UNVERIFIED SOCIAL POST/%s" % it["source"])
        line = "%d. %s [%s]%s%s" % (i + 1, it["headline"], tag, stamp, url)
        body = ((it.get("body") if isinstance(it, dict) else "") or "").strip()
        if real and body and body[:40] not in it["headline"]:
            excerpt = body[:_BODY_CHARS]
            if len(body) > _BODY_CHARS:
                excerpt += "..."
            line += "\n   excerpt: %s" % excerpt
        lines[i] = line
    shown = (items if limit is None else items[:limit])
    fresh, old = split_by_age(shown, today)
    out = []
    if fresh:
        out.append("DEVELOPMENTS — new since the last card. The news is here:")
        out += [lines[i] for i, _it in fresh]
    if old:
        out.append("BACKGROUND — already established, reported %d+ days ago. "
                   "Context only, never the news:" % _FRESH_DAYS)
        out += [lines[i] for i, _it in old]
    if not fresh:
        out.append("(NOTHING NEW. Every item above is background — write the "
                   "state of play, not a development.)")
    return "\n".join(out)
