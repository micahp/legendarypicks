"""anchor_routing helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from news_classifier import entities
from .topic_words import _norm_words, _topic_hits, _topic_words  # noqa: E402

_MAX_SOURCES = 12

_MIN_ITEMS = 2  # fewer than this and there's no "chatter" to summarize

def _better_home(con, conv, headline, own_entities=(), _cache={}):
    """The sibling conversation this anchor belongs to more than `conv`, or None.

    Each card used to score the league feed on its own, with no idea its
    siblings existed. So one story could win a place in several pools at once,
    and the newest copy of it then led every card that took it. That is how
    Messi's father's death — which has its own card, `mls-messi-absence`, 34
    tagged items deep — also opened the Leagues Cup SCOUTING card, three weeks
    after Micah split them apart precisely so it would not (see the note on
    news_conversations.mls-messi-absence, 2026-08-10).

    Note the near miss: URL-level dedupe across pools finds NOTHING here (0 of
    130 anchors are shared). The cards were not holding the same article, they
    were holding the same STORY through different articles. So routing has to
    compare subjects, not urls.

    Strictly higher wins, so a tie leaves the anchor where it is: this decides
    which conversation owns a story, and it should only move one when another
    conversation is a clearly better fit.

    An anchor that touches THIS conversation's own chatter is never routed away,
    whatever a sibling scores. Word counts alone cannot separate an incidental
    match from a core one — "Inter Miami finalizing $15M Berterame transfer"
    matches `mls-ligamx-spending` on one word (transfer, its whole subject, and
    the very deal its conv note cites as evidence) and `mls-messi-absence` on
    two (inter, miami — a club name that card's seed happens to carry). Counting
    words, the transfer card loses its own headline story. Its chatter is the
    tiebreak: the spending conversation is demonstrably talking about this deal,
    and the Leagues Cup scouting chatter never mentions Messi at all.
    """
    # The bridge must be evidence BEYOND the seed, or it is circular. "Leagues
    # Cup" is an entity in the scouting conversation's chatter, and it is also
    # that conversation's own seed word — so every Messi fixture story bridged
    # on it and the guard readmitted exactly what routing had just removed. An
    # entity whose words are already the conversation's topic words carries no
    # information about whether THIS story belongs here.
    own_words = _topic_words(conv)
    bridge = {e for e in own_entities if not (_norm_words(e) & own_words)}
    if bridge and entities(headline or "") & bridge:
        return None
    league = conv["league"]
    if league not in _cache:
        _cache[league] = [dict(r) for r in con.execute(
            "SELECT id, league, seed, title FROM news_conversations "
            "WHERE league=? AND active=1", (league,)).fetchall()]
    mine = _topic_hits(headline, _topic_words(conv))
    best, best_score = None, mine
    for other in _cache[league]:
        if other["id"] == conv["id"]:
            continue
        score = _topic_hits(headline, _topic_words(other))
        if score > best_score:
            best, best_score = other["id"], score
    return best
