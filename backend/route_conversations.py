"""Assign `conv_id` to items the seed-word tagger cannot place.

    LP_DB_PATH=/path/to/db python3 route_conversations.py [--apply] [--limit N]

Runs after collection, over rows already in `news_items`. Read-only unless
`--apply` is passed.

WHY THIS EXISTS
---------------
`tag_conversations` scores an item against a conversation's SEED — the handful
of words in its hand-written title and query. That works on article headlines,
which restate their subject, and fails completely on posts, which do not.
Measured on dev 2026-08-13 over the 1,033 stored `x` rows:

    874 match ZERO seed words
     31 match one
      0 match the two the tagger requires

So the entire X feed — every rostered reporter, 1,033 rows — has never reached
a single card. Not because it was judged and rejected: because nothing could
place it. Dropping the bar to one word buys 31 items and most are junk (`RT by
@TheAthletic`, a PrizePicks promo, a livestream plug), which is the tell that
the threshold was never the problem. Ian Rapoport's "Sources: The #Patriots
have agreed to terms with their standout TE Hunter Henry on a 2-year contract"
contains none of `media`, `rights`, `broadcast`, and no threshold will find it.

A terse post does not restate the topic. It names the PEOPLE and CLUBS in it,
and assumes you already know why they matter — which is exactly what the
conversation's existing pool knows. So route on that instead: an item belongs
where the entities it names are already being discussed.

This is the same entity bridge `_load_chatter` uses to pick anchors, where it
was introduced for the same reason ("the pro/rel card is anchored by the
'commissioner Berg in charge' article, whose headline contains neither
'relegation' nor 'promotion'"). The tagger never got it.

WHAT IT WILL NOT DO
-------------------
Decide whether a story is worth telling. Routing answers "which conversation is
this about", and nothing here ranks newsworthiness — spread and topicality both
prefer a blowout to a media-rights fight. That judgment stays with the editor,
and `news_card_feedback` is where it accumulates.
"""
import argparse
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_league_narratives import (  # noqa: E402
    _significant, _topic_words, is_social, post_text,
)
from ingest_league_news import CONVERSATIONS  # noqa: E402
from news_classifier import entities  # noqa: E402

# An entity has to be SHARED before it identifies anything. "Las Vegas" earns a
# route to nba-expansion; "Los Angeles" appears in every league's pool and earns
# nothing. Computed from the corpus rather than listed by hand, because a hand
# list is a name-keyed guess that goes stale the week a team moves.
_UBIQUITY = 4

# Entities carry the signal; words are a tiebreaker. A post naming "Hunter
# Henry" and "New England" is about that transaction whatever verbs it uses,
# while sharing "contract" with a conversation means almost nothing.
_W_ENTITY = 4
_W_WORD = 1

# A route has to WIN, not merely lead. `esports worlds` scored LoL Worlds and
# the Esports World Cup identically and the tie fell through to recency, so the
# card became the wrong event (Micah, 2026-08-12). A near-tie here is the same
# failure one stage earlier, and an item routed into the wrong conversation is
# worse than one left untagged: untagged costs a story, misrouted puts a real
# receipt under a card it does not belong to.
_MIN_SCORE = 8
_MIN_MARGIN = 4

# Both gates, independently. See `score` for what each one is asking and for
# the box-score failure that made a sum insufficient.
_MIN_ENTITY = 1
_MIN_SEED = 1


def _card_text(con, conv_id):
    """The conversation's current card — what it is about NOW, not at seeding.

    A seed is written once; a conversation moves. `nba-kawhi-cap` was seeded on
    the salary cap and is now substantially about an endorsement deal, and an
    item naming Daktronics belongs to it even though no seed word says so.
    """
    row = con.execute(
        "SELECT title, narrative, paragraph FROM news_narratives WHERE conv_id=?",
        (conv_id,)).fetchone()
    if not row:
        return ""
    return " ".join(x or "" for x in (row["title"], row["narrative"],
                                      row["paragraph"]))


def conversation_profiles(con, exclude_urls=()):
    """{conv_id: profile} built from the pool each conversation ALREADY holds.

    `exclude_urls` drops specific rows from the profile so a held-out item
    cannot be routed by its own presence — without it, validation would score
    every already-tagged row against a profile containing that row and report a
    perfect result that means nothing.
    """
    ent_freq = collections.Counter()
    profiles = {}
    for conv in CONVERSATIONS:
        rows = [r for r in con.execute(
            """SELECT headline, body, url FROM news_items
               WHERE conv_id=? AND url != ''""", (conv["id"],)).fetchall()
            if r["url"] not in exclude_urls]
        ents, words = set(), set(_topic_words(conv))
        for r in rows:
            ents |= entities(r["headline"] or "")
            words |= _significant(r["headline"] or "")
        card = _card_text(con, conv["id"])
        if card:
            ents |= entities(card)
            words |= _significant(card)
        profiles[conv["id"]] = {"league": conv["league"], "entities": ents,
                                "words": words, "pool": len(rows),
                                "seed_words": set(_topic_words(conv))}
        ent_freq.update(ents)
    # Strip the entities that identify nothing because everyone has them.
    common = {e for e, n in ent_freq.items() if n >= _UBIQUITY}
    for p in profiles.values():
        p["entities"] -= common
        p["common"] = common
    return profiles


def score(item, profile):
    """(total, entity_hits, seed_hits) — a CONJUNCTION, not a weighted sum.

    A sum lets one signal buy the route on its own, and entity overlap is the
    one that will: two shared names cleared the old bar with no topical
    evidence at all. Measured on the first version, 2026-08-13 — "Tarik Skubal"
    entered `mlb-salary-cap`'s profile from the trade-deadline card, and after
    that every Skubal box score routed to the salary cap: "Dodgers edge Royals
    to salvage Skubal's Dodger Stadium debut", "Skubal remains winless since
    trade", "Re-ranking the Tigers' farm system". Precision on a hand-read
    sample was about half, while leave-one-out reported zero misroutes — two
    numbers on different rulers, because the held-out items all HAD a home and
    the corpus this runs on mostly does not.

    The two signals answer different questions and both must answer yes:

      entities  WHICH story is this? Shared proper nouns, minus the ones
                everybody shares.
      seed      is it this conversation's KIND of story? A box score and
                "Boras attacks the Tigers over Skubal" name the same player;
                only one of them says cap, arbitration, contract.

    Seed words specifically, not the pool's whole vocabulary. Pool words drift
    with whatever got tagged last — which is the loop that made a matchday
    preview look like a spending story — while the seed is the standing
    definition of the conversation.
    """
    text = post_text(item) if is_social(item) else (item.get("headline") or "")
    ents = entities(text) - profile.get("common", set())
    words = _significant(text)
    e_hits = len(ents & profile["entities"])
    s_hits = len(words & profile["seed_words"])
    total = _W_ENTITY * e_hits + _W_WORD * len(words & profile["words"])
    return total, e_hits, s_hits


def route(item, profiles):
    """(conv_id, score, margin) for a confident route, else (None, best, margin).

    League is a hard guard, not a signal. Without it TomBogert's MLS transfer
    posts landed in `nfl-media-rights` because "finalizing a deal" hit that
    seed's generic words (2026-08-10) — and entity routing makes that worse,
    not better, since player names collide across leagues far more readily than
    topic words do.
    """
    league = item.get("league_hint") or item.get("league")
    if not league or league == "unclassified":
        return None, 0, 0
    scored = []
    for cid, p in profiles.items():
        if p["league"] != league:
            continue
        total, e_hits, s_hits = score(item, p)
        # Both signals or nothing. An item naming the right people about the
        # wrong subject is the box-score failure; an item on the right subject
        # naming nobody the conversation knows is a different story that
        # happens to share vocabulary.
        if e_hits < _MIN_ENTITY or s_hits < _MIN_SEED:
            total = 0
        scored.append((total, cid))
    scored.sort(reverse=True)
    if not scored:
        return None, 0, 0
    best, cid = scored[0]
    runner = scored[1][0] if len(scored) > 1 else 0
    margin = best - runner
    if best >= _MIN_SCORE and margin >= _MIN_MARGIN:
        return cid, best, margin
    return None, best, margin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write conv_id back (default: report only)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    profiles = conversation_profiles(con)
    rows = [dict(r) for r in con.execute(
        """SELECT id, source, headline, body, url, league, conv_id
           FROM news_items
           WHERE (conv_id IS NULL OR conv_id = '') AND url != ''
           ORDER BY published DESC""" + (" LIMIT %d" % args.limit
                                         if args.limit else ""))]
    print("untagged rows considered: %d" % len(rows))

    routed = collections.Counter()
    near = 0
    for it in rows:
        cid, best, margin = route(it, profiles)
        if cid:
            routed[cid] += 1
            if args.apply:
                con.execute("UPDATE news_items SET conv_id=? WHERE id=?",
                            (cid, it["id"]))
        elif best >= _MIN_SCORE:
            # An ambiguous key does not raise, it MISSES — so say so. These are
            # the items two conversations both want, and a silent skip here is
            # indistinguishable from an item nothing wanted.
            near += 1
            if near <= 10:
                print("    AMBIGUOUS: score %d, margin %d | %s"
                      % (best, margin, (it["headline"] or "")[:70]))
    if args.apply:
        con.commit()
    print("routed %d item(s)%s; %d scored well but had no clear winner"
          % (sum(routed.values()), "" if args.apply else " (DRY RUN)", near))
    for cid, n in routed.most_common():
        print("   %-24s %4d" % (cid, n))
    con.close()


if __name__ == "__main__":
    main()
