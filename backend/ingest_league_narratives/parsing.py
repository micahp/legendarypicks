"""parsing helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from news_classifier import entities
from .anchor_routing import _MAX_SOURCES, _better_home  # noqa: E402
from .topic_words import _significant, _topic_hits, _topic_words, weak_seed  # noqa: E402

_ANCHORS = 6               # real articles shown per card, best-scoring first

def _parse_response(text):
    """Parse the model's strict-JSON answer; tolerate code fences / stray text."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None

def _load_chatter(con, conv):
    """Items for one conversation: the tagged bluesky chatter + the league's
    recent real articles.

    The conversation's bluesky posts are tagged with conv_id by the collector
    and are the fan-voice signal. The league's recent real (non-bluesky)
    articles are added as OFFICIAL ANCHOR material the fan posts are reacting
    to — a conversation whose chatter is all social still needs the real story
    to anchor the card (MLB salary-cap had zero real articles in its tagged
    bucket, so the desk had nothing to anchor on and correctly declined rather
    than fabricate; Micah 2026-08-07).

    The anchor pool is RELEVANCE-FILTERED. "The league's 8 most recent
    articles" put Messi's father's death into the Leagues Cup scouting card,
    and the model dutifully used it — Micah, 2026-08-10: "messi is a separate
    topic ... these cards aren't like a newsletter saying everything going on
    in a league." Trusting the model to ignore off-topic material it was
    explicitly told to mine does not work; do not hand it the material.

    Relevance is bridged through the conversation's OWN chatter, not through
    seed words. Seed-word matching alone was too narrow: the pro/rel card is
    anchored by the "commissioner Berg in charge" article, whose headline
    contains neither "relegation" nor "promotion". But the chatter talks about
    Berg, so the entity bridge keeps it — and drops Messi, whom this
    conversation's chatter never mentions.
    """
    conv_id, league = conv["id"], conv["league"]

    # RANK, do not gate (Micah, 2026-08-10). A threshold worked when the pool
    # was six articles and fails at a hundred: everything clears a low bar, so
    # a BIG3 story reached the NBA-expansion card and a matchday preview took
    # over the Leagues Cup scouting card. Scoring instead means a loosely
    # related item still loses to three closely related ones.
    topic_words = _topic_words(conv)

    def _score(row, extra_entities=()):
        head = row["headline"] or ""
        words = _significant(head)
        return (3 * len(topic_words & words)
                + 2 * len(entities(head) & set(extra_entities)))

    # Pass 1 — the conversation's own chatter, ranked on the seed itself. There
    # can be ~100 tagged posts now, so "most recent 12" was arbitrary.
    chatter = [dict(r) for r in con.execute(
        """SELECT headline, url, source, published, body FROM news_items
           WHERE conv_id=? AND url != '' ORDER BY published DESC LIMIT 200""",
        (conv_id,)).fetchall()]
    chatter.sort(key=lambda r: (_score(r), r["published"] or ""), reverse=True)
    out = chatter[:_MAX_SOURCES]

    # Pass 2 — anchors scored on the seed AND on the entities the best chatter
    # actually talks about. Two passes, so the entity set comes from chatter
    # that already matched the seed rather than from whatever was tagged.
    topic_entities = set()
    for r in out:
        topic_entities |= entities(r["headline"])

    seen = {r["url"] for r in out}
    # Candidates: the recent league feed PLUS anything whose headline carries a
    # seed word, at any age. Recency alone cut the ESPN scouting feature — the
    # single best source this conversation has — because it is from 2025 and
    # fell outside the 120 most recent MLS rows (2026-08-10).
    sql = ("""SELECT headline, url, source, published, body FROM news_items
              WHERE league=? AND source NOT IN ('bluesky','x-search')
                AND url != '' ORDER BY published DESC LIMIT 120""")
    rows = list(con.execute(sql, (league,)).fetchall())
    if topic_words:
        like = " OR ".join(["lower(headline) LIKE ?"] * len(topic_words))
        rows += list(con.execute(
            """SELECT headline, url, source, published, body FROM news_items
               WHERE league=? AND source NOT IN ('bluesky','x-search')
                 AND url != '' AND (%s) LIMIT 60""" % like,
            (league, *["%%%s%%" % w for w in topic_words])).fetchall())
    candidates, urls = [], set()
    for r in rows:
        if r["url"] in seen or r["url"] in urls:
            continue
        urls.add(r["url"])
        candidates.append(dict(r))
    scored = [(_score(r, topic_entities), r["published"] or "", r)
              for r in candidates]
    scored = [t for t in scored if t[0] > 0]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    # A TIE AT THE TOP is a finding, not a result. When the best-scoring
    # candidates all score the same, the sort falls through to recency and the
    # card is built from "the most recent league article containing one common
    # word" — which is exactly how `esports worlds` produced a card about the
    # Esports World Cup instead of League of Legends Worlds: 57 articles tied
    # at 1, because `esports` matches everything in the esports league and
    # "Esports World Cup" also catches `worlds`. Nothing failed; the seed
    # simply did no work, and no run said so (Micah, 2026-08-12: "worlds does
    # seem too generic").
    if scored:
        top = scored[0][0]
        tied = sum(1 for t in scored if t[0] == top)
        seed_hits = _topic_hits(scored[0][2]["headline"], topic_words)
        if weak_seed(scored[0][2]["headline"], topic_words, tied):
            print("    WEAK SEED: %s — best candidate matches %d seed word(s), "
                  "%d tied at that rank (ranking fell through to recency); "
                  "topic words: %s"
                  % (conv_id, seed_hits, tied,
                     ",".join(sorted(topic_words)) or "none"))

    # Route: an anchor that fits a sibling conversation better belongs to that
    # sibling, not to both. Dropped OUT LOUD — a card quietly annexing another
    # card's story is exactly the failure this pass exists to stop, so a silent
    # drop would hide the fix working as surely as it hid the bug.
    kept_anchors = []
    for _s, _p, r in scored:
        if len(kept_anchors) >= _ANCHORS:
            break
        owner = _better_home(con, conv, r["headline"], topic_entities)
        if owner:
            print("    route: %s -> %s | %s" % (
                conv["id"], owner, (r["headline"] or "")[:70]))
            continue
        kept_anchors.append(r)
    out.extend(kept_anchors)
    return out
