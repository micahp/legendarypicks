"""roles helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from _core import REPORTER_ROSTER
from _core import SOCIAL_SOURCES
from .topic_words import _squash_title  # noqa: E402

# Hosts that serve posts, whatever the row's `source` column happens to say.
_SOCIAL_HOSTS = ("bsky.app", "bsky.social", "twitter.com", "x.com", "nitter",
                 "mastodon", "threads.net", "reddit.com", "t.co")

def is_social(it):
    """True when this item is a POST, not published reporting.

    Membership in `SOCIAL_SOURCES` is checked first, then the SHAPE of the item,
    because the name list has already failed once in the way that matters: `x`
    was not in it while 855 rows carried that source, so every tweet in the
    corpus counted as a verified publisher. A tweet with a false claim reached a
    card as fact that way (Micah, 2026-08-12), and the same hole let two tweets
    into the publisher half of the MLS spending pool.

    Adding the missing string would fix those 855 rows and leave the mechanism
    intact for the next feed someone adds. So this also refuses anything that
    LOOKS like a post — our collector prefixes every one with `[@handle]`, and
    social hosts are recognisable in the URL — and a caller can report the
    disagreement rather than silently trusting the column
    (see `social_leaks`). An item only has to look like a post ONCE, anywhere,
    to be kept out of the receipts.
    """
    if (it.get("source") or "") in SOCIAL_SOURCES:
        return True
    if (it.get("headline") or "").lstrip().startswith("[@"):
        return True
    url = (it.get("url") or "").lower()
    return any(h in url for h in _SOCIAL_HOSTS)

def social_leaks(items):
    """Items the `source` column calls published but that are posts by shape.

    Every one of these is a row that would have been served as a receipt. This
    is the loud half of `is_social`: the guard stops them silently, and this
    reports them so the source list actually gets fixed instead of the guard
    quietly carrying the hole forever.
    """
    return [it for it in items
            if (it.get("source") or "") not in SOCIAL_SOURCES and is_social(it)]

_LINK_RE = re.compile(r"https?://\S+")

_HANDLE_RE = re.compile(r"^\s*\[@([^\]]+)\]\s*")

def post_text(it):
    """A post's own words: the headline with the collector's `[@handle]` cut off."""
    h = it.get("headline") or ""
    m = _HANDLE_RE.match(h)
    return h[m.end():] if m else h

def post_handle(it):
    """The account that posted, or "" for anything that is not a post."""
    m = _HANDLE_RE.match(it.get("headline") or "")
    return m.group(1) if m else ""

# Selling, not reporting. A brand desk's posts are roughly half promotion, and
# promotion is the one kind of social content with a MOTIVE to overstate.
_PROMO_MARKERS = ("sign up", "promo code", "use code", "download the app",
                  "odds on", "bet now", "deposit", "sponsored", "giveaway",
                  "enter to win", "link in bio", "available now on")

def is_promo(it):
    """True when the post exists to sell something."""
    text = post_text(it).lower()
    return any(m in text for m in _PROMO_MARKERS)

# A reporter claiming a story as their own, not handing it to someone else.
# Kept to words that assert firsthand sourcing: "Report:" and "ICYMI:" and
# "Opinion:" are the opposite and stay relays.
_FIRSTHAND_MARKERS = ("sources", "source", "breaking", "exclusive", "update")

def is_relay(it, published_titles=()):
    """True when the post CARRIES someone else's story rather than asserting one.

    The distinction that replaces "is this a tweet?", which was the wrong
    question twice over (Micah, 2026-08-13: "youre right abiut the buckets but
    wrong abiut who falls into them"). A named reporter posting firsthand IS the
    reporting — the outlet's article is downstream of them. A bot pasting an
    article's lede is not reporting at any volume. Platform predicts neither.

    Three shapes, all mechanical, none keyed on the account name:

      * prose CONTINUING past an outbound link — a person links at the end of
        what they wanted to say, a scraper pastes the lede after it. This is
        what `rawnfl`/`rawnba`/`rawchili` do: 10 of 46 social items reaching
        the model, including the `rawnfl` repost that put "Supporters point to
        LSU's reported nine-figure media-rights deal" in a card when no
        publisher item mentioned LSU at all;
      * an explicit retweet marker — "RT by @AdamSchefter: Happy to have EB
        back" is Schefter passing something along, not Schefter reporting, and
        a roster entry must not launder it into a receipt;
      * the story is already in the pool as a publisher item — how `[@cnbc.com]`
        posting CNBC's own article sat beside the `cnbc` item and spent a fan
        slot saying the same thing twice.

    Name-keying was tried first and rejected the same day: "the handle is a
    domain" catches `[@cnbc.com]` and also `[@mothmaam.online]`, a real fan
    whose 25-part video series on salary-cap circumvention is the entire fan
    voice of the Kawhi card. Bluesky lets a person be their own domain. Both
    outlet accounts are caught by the duplicate test anyway, which is evidence
    rather than a guess.
    """
    text = post_text(it)
    if re.match(r"^\s*RT by @", text, re.I) or re.match(r"^\s*RT @", text, re.I):
        return True
    # Attribution IN THE TEXT, with no link to give it away. A desk writing
    # "Schefter: Laremy Tunsil unlikely to play" is passing on someone else's
    # scoop, and the link-shaped tests never see it.
    #
    # `Word:` is not always an attribution, and reading it as one demoted the
    # highest-value post in the corpus: Ian Rapoport's "Sources: The #Patriots
    # have agreed to terms with their standout TE Hunter Henry on a 2-year
    # contract" is his OWN scoop, and `Sources:` is the signature of firsthand
    # reporting rather than a hand-off. The carve-out is deliberately tiny —
    # only a rostered account, only these markers — because the same prefix on
    # an unrostered account is a headline bot ("Opinion:", "Feed:", "Final:",
    # all measured in this corpus) and the fan lane is where a headline bot
    # does its damage. An unknown account keeps failing closed into `relay`.
    prefix = re.match(r"^\s*([A-Z][A-Za-z.\-]+)\s*:", text)
    firsthand = (prefix and prefix.group(1).lower() in _FIRSTHAND_MARKERS
                 and post_handle(it) in REPORTER_ROSTER)
    if (prefix and not firsthand) or re.search(r"\b(via|per|h/t)\s+@?[A-Z]", text):
        return True
    m = _LINK_RE.search(text)
    # Prose CONTINUING past an outbound link is scraped article body.
    if m and text[m.end():].strip():
        return True
    # An outlet posting its own story, matched on the story rather than on the
    # account. 40 characters of squashed headline, either way round, because a
    # post may trim a long headline or append the section label the feed adds.
    body = _squash_title(_LINK_RE.sub("", text))[:40]
    return bool(body) and any(body in t or t[:40] in body
                              for t in published_titles if t)

def post_role(it, published_titles=()):
    """What this item IS: publisher | reporting | relay | promo | voice.

    One function so the roles cannot drift apart, and cheap enough to run over
    the whole corpus: four mechanical signals, no model call.

      publisher  a real article from the news feeds. Citable, as always.
      reporting  a ROSTERED account asserting something firsthand. Citable, and
                 the chip names the person and their outlet.
      relay      carrying someone else's story. Never a receipt — crediting the
                 account that reposted an article is crediting a scraper for
                 another newsroom's work — but a pointer to reporting we are
                 missing, which is what 200 distinct rawchili stories turned
                 out to be.
      desk       a brand account aggregating other people's reporting. Not a
                 receipt and not a fan — see the note in the body.
      promo      selling. Dropped.
      voice      a person reacting. The fan lane, and only this.

    Order matters: relay and promo are tested BEFORE the roster, so a rostered
    reporter's retweet or ad read cannot inherit their credibility. The roster
    is an upgrade applied to firsthand assertions only.
    """
    if not is_social(it):
        return "publisher"
    if is_promo(it):
        return "promo"
    if is_relay(it, published_titles):
        return "relay"
    if post_handle(it) in REPORTER_ROSTER:
        return "reporting"
    # VOICE IS NOT THE FALLBACK. Making it the default is the same fail-open
    # shape the roster was built to avoid, one lane over: the roster refuses to
    # trust an unknown account with a receipt, and then the leftover branch
    # handed that same account to the model as a fan. `@UnderdogNFL` — a desk
    # posting "JK Dobbins left practice with trainers Monday", 83 items a day —
    # came out as a supporter (measured 2026-08-13, before this branch).
    #
    # Nothing here is keyed on the name. HOW THE ITEM ENTERED THE CORPUS says
    # which lane it belongs to, and the collector already knows: `x` rows are
    # timelines we chose to follow, so they are publications by construction and
    # can never be a stranger reacting. `bluesky`/`x-search` rows are keyword
    # searches of the open network, which is where the public actually is. A
    # desk is not a receipt and not a fan; it is aggregation, and it sits with
    # the relays until something earns it a place on the roster.
    if (it.get("source") or "") not in ("bluesky", "x-search"):
        return "desk"
    return "voice"
