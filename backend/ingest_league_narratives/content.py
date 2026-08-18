"""content helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from .editor import _SHOW_ANCHORS  # noqa: E402
from .roles import is_social, post_handle, post_role, post_text  # noqa: E402
from .topic_words import _squash_title  # noqa: E402

def _content_words(s):
    return {w for w in re.findall(r"[a-z]{4,}", (s or "").lower())
            if w not in _CORROB_STOP}

_CORROB_STOP = {"this", "that", "with", "from", "have", "will", "been", "says",
                "said", "after", "about", "their", "they", "there", "were",
                "would", "could", "more", "than", "into", "over", "just"}

def corroboration(it, corpus, min_overlap=4):
    """`corroborated` when an INDEPENDENT source carries the same claim, else
    `single-source`.

    Deliberately separate from `REPORTER_ROSTER`, and computed the same way for
    a Hall-of-Famer and a stranger: a trust list that also decided what counted
    as confirmation could confirm itself. A wrong roster entry can cost us a
    story; it must never be able to make an unmatched claim read as verified.

    Measured across the corpus 2026-08-13, over the eight rostered reporters:
    81 posts corroborated, 222 single-source. That 73% is the product argument
    for carrying them at all — it is reporting our publisher feeds do not have —
    and it is exactly why the state has to be SHOWN rather than hidden. Being
    first is worth nothing if a reader cannot tell it apart from being
    confirmed, so the card says which one it is.
    """
    w = _content_words(post_text(it))
    if len(w) < 3:
        return "unknown"
    handle = post_handle(it)
    for other in corpus:
        if other is it or (other.get("url") or "") == (it.get("url") or ""):
            continue
        # Independence, not merely difference: the same desk repeating itself
        # on two feeds is one source, and a reporter cannot corroborate their
        # own post.
        if handle and post_handle(other) == handle:
            continue
        if len(w & _content_words(post_text(other))) >= min_overlap:
            return "corroborated"
    return "single-source"

_PROMPT_ITEMS = 10   # how many pool items reach the model, per card

def _prompt_items(items, limit=_PROMPT_ITEMS):
    """The EXACT list the model is shown — published articles first.

    Two defects lived in the four lines this replaces, both measured on dev
    2026-08-12.

    **The model was never shown the reporting.** `_load_chatter` returns social
    chatter first (up to 12) and appends the publisher anchors after it, and the
    prompt took `[:10]`. So for any conversation with a busy social lane, the
    anchors fell off the end and the card was written from bluesky alone. Six of
    fourteen conversations were in that state, and they are EXACTLY the six
    cards serving `source_count = 0`:

        esports-worlds  mls-ligamx-spending  mls-messi-absence
        nba-expansion   nfl-media-rights     nhl-salary-cap

    The spending card called a completed transfer "unconfirmed social reports"
    while The Athletic, USA Today and mlssoccer.com sat in its pool unread. That
    is `published-first` §1 exactly: we had the published fact and used the
    chatter about it. Reserving anchor slots is the fix — a card may still be
    chatter-only, but only when there is genuinely nothing published to show it.

    **Citations resolved against the wrong list.** The prompt numbered the
    DEDUPED items while `_cited_sources` indexed the raw pool, so every number
    after a dropped duplicate pointed one article too early. Two of fourteen
    conversations were misaligned — mlb-salary-cap's "#7" was a Skubal salary-cap
    piece in the prompt and a bluesky post in the resolver. A wrong receipt is
    worse than no receipt: it is a citation to something that does not say it.
    Callers now number and resolve against this one list.
    """
    seen, uniq = set(), []
    for it in items:
        # The collector stores the same post from several feeds; duplicates
        # crowded a real injury item out of the window once already.
        h = (it["headline"] or "").strip()
        if h in seen:
            continue
        seen.add(h)
        uniq.append(it)
    articles = [i for i in uniq if not is_social(i)]
    titles = {_squash_title(i.get("headline")) for i in articles}
    roles = {id(i): post_role(i, titles) for i in uniq}
    # Rostered reporting sits with the ANCHORS, not with the chatter. Schefter
    # breaking a trade is the story, and shelving it in the fan lane is how a
    # card ends up citing the writeup of a scoop we already had.
    anchors = articles + [i for i in uniq if roles[id(i)] == "reporting"]
    # The chatter lane is for VOICE and nothing else. A repost bot and an
    # outlet's own account are carrying an article, not saying anything, and
    # handing them to the model under "what fans are saying" is how a card
    # acquires supporters who do not exist (see `post_role`). Deduping on the
    # raw headline above cannot catch them: the collector's `[@handle]` prefix
    # means an outlet's post of its own story never string-matches the
    # publisher item beside it.
    chatter = [i for i in uniq if roles[id(i)] == "voice"]
    n_anchor = min(len(anchors), _SHOW_ANCHORS)
    n_chat = min(len(chatter), limit - n_anchor)
    # Slots the chatter did not need go back to the anchors, never wasted.
    n_anchor = min(len(anchors), limit - n_chat)
    return anchors[:n_anchor] + chatter[:n_chat]
