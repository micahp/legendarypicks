#!/usr/bin/env python3
"""discover_topics.py — find the conversations nobody told us about.

The seeds in `news_conversations` are search strings: they can only retrieve a
conversation a human already named. `nba-kawhi-cap` exists because a person read
the feed, noticed the Pablo Torre story recurring, and typed an entry. That is
the work this script automates (Micah, 2026-08-10: "i don't just want these to
be in the conversation i want it to be training data for it to get better at
finding the signal").

Two stages, deliberately:

  1. CHEAP + DETERMINISTIC — cluster the recent corpus by recurring entity and
     score each cluster on the properties Micah's own topics share: it recurs
     over several days, several INDEPENDENT sources carry it, social chatter
     and real articles CONVERGE on it, and there is a stake (money, rules,
     power) rather than a result. No model, no cost, fully inspectable.
  2. JUDGED — the surviving candidates go to DeepSeek together with the
     APPROVED conversations as positive exemplars and the REJECTED candidates
     as negative ones. The model infers the boundary from the contrast; it does
     not apply a fixed rule. Same shape as the card feedback loop
     (`_editor_marks` in ingest_league_narratives.py), pointed at DISCOVERY
     instead of framing.

The labels are the training data. Every approve/reject sharpens stage 2, and a
dictated topic is the strongest positive label there is.

Nothing is published automatically — a candidate becomes a conversation only
when a human approves it.

Usage:
  LP_DB_PATH=... python3 discover_topics.py                 # run the pass
  LP_DB_PATH=... python3 discover_topics.py --dry-run       # stage 1 only, no writes
  LP_DB_PATH=... python3 discover_topics.py --list          # review proposals
  LP_DB_PATH=... python3 discover_topics.py --approve 3     # becomes a conversation
  LP_DB_PATH=... python3 discover_topics.py --reject 4 --note "just a result"
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import _deepseek_chat, _init_db  # noqa: E402
from news_classifier import LEAGUE_TERMS  # noqa: E402

# Team and league names are CONTAINERS, not conversations: "brewers" recurs
# every day across every outlet and says nothing. Reuse the classifier's own
# vocabulary rather than writing a second list of team names (2026-08-10).
_CONTAINER_ENTITIES = {t for terms in LEAGUE_TERMS.values() for t in terms}

_WINDOW_DAYS = 10          # how far back the corpus scan reaches
_MIN_ITEMS = 3             # a cluster nobody repeated is not a conversation
_MIN_SOURCES = 2           # one outlet talking to itself is not a conversation
_MIN_DAYS = 2              # a one-day spike is a result, not a conversation
_MAX_CANDIDATES = 14       # how many survive stage 1 into the model call

# A stake is what separates a conversation from a scoreline. These are the
# shapes Micah's dictated topics all have: money, rules, power, or a fight.
_STAKE_TERMS = (
    "salary cap", "salary floor", "cap", "luxury tax", "revenue", "media rights",
    "tv deal", "broadcast rights", "transfer fee", "million", "billion", "payroll",
    "expansion", "relegation", "promotion", "realignment", "conference",
    "lawsuit", "settlement", "investigation", "circumvention", "banned",
    "suspension", "cba", "lockout", "strike", "rule change", "vote", "owners",
    "commissioner", "union", "franchise", "stadium", "ownership", "sale",
)
# Words that look like entities but never name a conversation.
_STOP_ENTITIES = {
    "the", "this", "that", "what", "why", "how", "when", "who", "his", "her",
    "new", "top", "best", "first", "last", "next", "one", "two", "three",
    "game", "games", "highlights", "week", "season", "day", "night", "report",
    "reports", "sources", "source", "news", "update", "updates", "live",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "mlb", "nfl", "nba", "nhl",
    "mls", "ufc", "ncaaf", "espn", "vs",
}
_ENTITY_RE = re.compile(r"\b([A-Z][a-zA-Z'’.-]{2,})(?:\s+([A-Z][a-zA-Z'’.-]{2,}))?")


def _db():
    path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


# ---------------------------------------------------------------- stage 1

def _entities(headline):
    """Capitalized TWO-word sequences — a cheap proper-noun proxy.

    Two words, not one: single capitalized tokens are first names and sentence
    openers ("larry", "mike", "red", "after"), and they dominated the ranking
    when they were allowed (2026-08-10). A person or a policy worth a card
    survives as a pair — "tarik skubal", "salary cap".

    Bluesky headlines are prefixed with `[@handle] `; that prefix is stripped
    so a poster's handle never becomes the topic.
    """
    h = re.sub(r"^\[@[^\]]+\]\s*", "", headline or "")
    out = set()
    for m in _ENTITY_RE.finditer(h):
        one, two = m.group(1), m.group(2)
        if not two:
            continue
        if one.lower() in _STOP_ENTITIES or two.lower() in _STOP_ENTITIES:
            continue
        out.add(("%s %s" % (one, two)).lower())
    return out


def _covered_by_existing(key, convs):
    """True if an active conversation already owns this entity.

    Token overlap, not substring: "the dodgers" never matched the seed
    "dodgers salary cap" as a substring, so the pass proposed a topic we
    already serve (2026-08-10).
    """
    words = {w for w in key.lower().split() if w not in _STOP_ENTITIES}
    if not words:
        return True
    for c in convs:
        text = ("%s %s" % (c["seed"], c["title"])).lower()
        if key.lower() in text:
            return True
        # Two shared words, not one: seeds are full of generic terms ("cap",
        # "transfer", "title"), and a single-token overlap excluded almost
        # every candidate (2026-08-10).
        if len(words & set(text.split())) >= 2:
            return True
    return False


def cluster(con, window_days=_WINDOW_DAYS):
    """Group recent items by recurring entity and score each group."""
    since = (datetime.datetime.utcnow()
             - datetime.timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute(
        """SELECT id, league, source, headline, body, url, published, layer
           FROM news_items
           WHERE published >= ? AND url != '' AND headline NOT LIKE 'FETCH ERROR%'""",
        (since,)).fetchall()
    convs = con.execute(
        "SELECT id, league, title, seed FROM news_conversations WHERE active=1").fetchall()

    groups = defaultdict(list)
    for r in rows:
        keys = _entities(r["headline"])
        # Also cluster on the STAKE PHRASE itself. Not every conversation is
        # named after a person or a club — "media rights", "promotion and
        # relegation" and "expansion" are the shape Micah's own topics take,
        # and entity clustering alone can never form them (2026-08-10).
        head = (r["headline"] or "").lower()
        for t in _STAKE_TERMS:
            if " " in t and t in head:
                keys.add(t)
        for e in keys:
            groups[e].append(r)

    out = []
    for key, items in groups.items():
        if len(items) < _MIN_ITEMS:
            continue
        if key in _CONTAINER_ENTITIES:
            continue
        sources = {i["source"] for i in items}
        # espn-nfl and espn-mlb are one outlet, not two.
        outlets = {s.split("-")[0] for s in sources}
        if len(outlets) < _MIN_SOURCES:
            continue
        days = {(i["published"] or "")[:10] for i in items if i["published"]}
        if len(days) < _MIN_DAYS:
            continue
        if _covered_by_existing(key, convs):
            continue
        social = [i for i in items if i["source"] == "bluesky"]
        articles = [i for i in items if i["source"] != "bluesky"]
        blob = " ".join(((i["headline"] or "") + " " + (i["body"] or "")).lower()
                        for i in items)
        # The stake must be in the HEADLINES, and in more than one of them.
        # Scanning the whole blob let ambient chatter satisfy it: any cluster of
        # 30 MLB items contains the words "salary cap" somewhere, so every club
        # looked like a cap conversation (2026-08-10).
        heads = [(i["headline"] or "").lower() for i in items]
        stake_hits = defaultdict(int)
        for h in heads:
            for t in _STAKE_TERMS:
                if t in h:
                    stake_hits[t] += 1
        # A stake term that IS part of the cluster key is not a stake:
        # "chris sale" is a pitcher, not a franchise sale.
        stakes = sorted(t for t, n in stake_hits.items()
                        if n >= 2 and t not in key)
        # A cluster keyed ON a stake phrase carries that stake by definition;
        # the "t not in key" guard above (which exists so "chris sale" is not a
        # franchise sale) would otherwise strip its only stake.
        if key in _STAKE_TERMS:
            stakes = sorted(set(stakes) | {key})
        # A conversation has a STAKE. Without one, recurrence is just a team
        # name appearing in box scores — which is what stage 1 returned before
        # this guard (top 14 were all clubs).
        if not stakes:
            continue
        leagues = defaultdict(int)
        for i in items:
            if i["league"] != "unclassified":
                leagues[i["league"]] += 1
        league = max(leagues, key=leagues.get) if leagues else "unclassified"

        features = {
            "items": len(items),
            "outlets": len(outlets),
            "days": len(days),
            "social": len(social),
            "articles": len(articles),
            # The property that matters most: people are TALKING about the same
            # thing that got REPORTED. Either alone is weaker signal.
            "convergence": bool(social and articles),
            "stakes": stakes[:6],
        }
        # Stake and convergence dominate; recurrence only breaks ties. Ranking
        # by recurrence alone surfaced clubs, not conversations.
        score = (min(len(stakes), 5) * 3.0
                 + (5.0 if features["convergence"] else 0.0)
                 + len(days) * 1.0
                 + len(outlets) * 1.0
                 + min(len(items), 12) * 0.25)
        out.append({
            "key": key, "league": league, "score": round(score, 2),
            "features": features,
            "evidence": [{"source": i["source"], "headline": i["headline"][:160],
                          "url": i["url"], "published": i["published"]}
                         for i in sorted(items, key=lambda r: r["published"] or "",
                                         reverse=True)[:8]],
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


# ---------------------------------------------------------------- stage 2

_JUDGE_SYSTEM = (
    "You decide which clusters of sports news are IMPORTANT CONVERSATIONS "
    "worth a news card, and which are just things that happened. "
    "A conversation is a story people argue about: money, rules, power, "
    "access, a fight over how the sport works. It persists across days and "
    "outlets. A result, a highlight, an injury report, a transaction notice or "
    "a routine preview is NOT a conversation, however many times it appears. "
    "You are given APPROVED examples (conversations the editor accepted, "
    "including ones he named himself — these are the strongest signal of what "
    "he considers important) and REJECTED examples. Infer the boundary from "
    "the CONTRAST between them; do not apply a fixed rule and never just echo "
    "an example's wording. "
    "For each candidate output whether to propose it, a short human title "
    "(2-4 words, the label above the card), a `seed` search phrase that would "
    "actually retrieve this conversation's chatter on a social search (plain "
    "words people post, not a headline), and one sentence of rationale naming "
    "the stake. "
    "Be strict: proposing a non-conversation costs the editor's time. If in "
    "doubt, drop it. "
    'Output STRICT JSON only: {"candidates": [{"key": "<the key you were '
    'given>", "propose": true|false, "title": "...", "seed": "...", '
    '"rationale": "..."}, ...]} — one entry per candidate you were given.'
)


def _exemplars(con):
    """Positive and negative labels — the training data for the selector."""
    approved = con.execute(
        """SELECT title, seed, league, origin FROM news_conversations
           WHERE active=1 ORDER BY origin='dictated' DESC, created_at DESC LIMIT 12"""
    ).fetchall()
    rejected = con.execute(
        """SELECT key, title, note FROM news_topic_candidates
           WHERE status='rejected' ORDER BY decided_at DESC LIMIT 10""").fetchall()
    parts = []
    if approved:
        parts.append("APPROVED conversations — more of this:\n" + "\n".join(
            "- [%s] %s (chatter: %s)%s" % (
                r["league"], r["title"], r["seed"],
                "  <- named by the editor himself" if r["origin"] == "dictated" else "")
            for r in approved))
    if rejected:
        parts.append("REJECTED candidates — not conversations:\n" + "\n".join(
            "- %s%s" % (r["title"] or r["key"],
                        (" (%s)" % r["note"]) if r["note"] else "")
            for r in rejected))
    return "\n\n".join(parts)


def judge(con, candidates):
    """Ask the model which candidates are conversations, given the labels."""
    if not candidates:
        return {}
    blocks = []
    for c in candidates:
        f = c["features"]
        ev = "\n".join("   - [%s] %s" % (e["source"], e["headline"])
                       for e in c["evidence"][:6])
        blocks.append(
            "### %s (league: %s)\n"
            "   recurrence: %d items over %d days, %d independent outlets; "
            "social=%d articles=%d converged=%s; stakes seen: %s\n%s"
            % (c["key"], c["league"], f["items"], f["days"], f["outlets"],
               f["social"], f["articles"], f["convergence"],
               ", ".join(f["stakes"]) or "none", ev))
    marks = _exemplars(con)
    user = ("%s\n\nCandidates to judge:\n\n%s" % (marks, "\n\n".join(blocks))
            if marks else "Candidates to judge:\n\n%s" % "\n\n".join(blocks))
    raw = _deepseek_chat(_JUDGE_SYSTEM, user, max_tokens=4000)
    if not raw:
        return None
    t = raw.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    try:
        parsed = json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except Exception:
            return None
    return {c.get("key"): c for c in parsed.get("candidates", []) if c.get("key")}


# ---------------------------------------------------------------- commands

def run(dry_run=False, window_days=_WINDOW_DAYS, no_judge=False):
    _init_db()
    con = _db()
    cands = cluster(con, window_days)
    print("Stage 1 — %d clusters cleared recurrence/independence/persistence"
          % len(cands))
    top = cands[:_MAX_CANDIDATES]
    for c in top:
        f = c["features"]
        print("  %-28s %5.1f  %dd/%do/%di conv=%s %s"
              % (c["key"][:28], c["score"], f["days"], f["outlets"], f["items"],
                 "y" if f["convergence"] else "n", ",".join(f["stakes"][:3])))
    if dry_run or no_judge or not top:
        print("(stage 2 skipped)")
        return
    verdicts = judge(con, top)
    if verdicts is None:
        print("Stage 2 FAILED (model returned nothing parseable) — no writes")
        return
    kept = 0
    for c in top:
        v = verdicts.get(c["key"]) or {}
        if not v.get("propose"):
            continue
        existing = con.execute(
            "SELECT id, status FROM news_topic_candidates WHERE key=?",
            (c["key"],)).fetchone()
        if existing and existing["status"] != "proposed":
            continue  # already decided; do not re-propose a rejected topic
        row = (c["key"], c["league"], v.get("title", "")[:60], v.get("seed", ""),
               v.get("rationale", ""), json.dumps(c["features"]), c["score"],
               json.dumps(c["evidence"]))
        if existing:
            con.execute(
                """UPDATE news_topic_candidates SET league=?, title=?, seed=?,
                   rationale=?, features=?, score=?, evidence=? WHERE id=?""",
                row[1:] + (existing["id"],))
        else:
            con.execute(
                """INSERT INTO news_topic_candidates
                   (key, league, title, seed, rationale, features, score, evidence)
                   VALUES (?,?,?,?,?,?,?,?)""", row)
        kept += 1
        print("  PROPOSED  %-22s %s — %s" % (c["key"][:22], v.get("title"),
                                             v.get("rationale", "")[:80]))
    con.commit()
    print("Stage 2 — %d of %d proposed" % (kept, len(top)))


def list_candidates(con, status="proposed"):
    rows = con.execute(
        "SELECT * FROM news_topic_candidates WHERE status=? ORDER BY score DESC",
        (status,)).fetchall()
    if not rows:
        print("no %s candidates" % status)
        return
    for r in rows:
        f = json.loads(r["features"] or "{}")
        print("[%d] %-22s %-7s score %.1f — %s" % (r["id"], r["title"], r["league"],
                                                   r["score"], r["rationale"]))
        print("     key=%s seed=%r  (%s items / %s days / %s outlets, converged=%s)"
              % (r["key"], r["seed"], f.get("items"), f.get("days"),
                 f.get("outlets"), f.get("convergence")))
        for e in json.loads(r["evidence"] or "[]")[:3]:
            print("     - [%s] %s" % (e["source"], e["headline"][:100]))
        print()


def decide(con, cand_id, verdict, note=""):
    r = con.execute("SELECT * FROM news_topic_candidates WHERE id=?",
                    (cand_id,)).fetchone()
    if not r:
        print("no candidate %s" % cand_id)
        return
    con.execute(
        "UPDATE news_topic_candidates SET status=?, note=?, decided_at=datetime('now') WHERE id=?",
        (verdict, note, cand_id))
    if verdict == "approved":
        conv_id = re.sub(r"[^a-z0-9]+", "-", "%s-%s" % (r["league"], r["key"])).strip("-")[:40]
        con.execute(
            """INSERT INTO news_conversations(id, league, title, seed, origin, note)
               VALUES (?,?,?,?, 'discovered', ?)
               ON CONFLICT(id) DO UPDATE SET active=1, title=excluded.title,
                 seed=excluded.seed""",
            (conv_id, r["league"], r["title"], r["seed"] or r["key"], note))
        print("approved -> conversation %s (%s) seed=%r" % (conv_id, r["title"], r["seed"]))
    else:
        print("rejected %s — kept as a negative example" % (r["title"] or r["key"]))
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="stage 1 only, no writes")
    ap.add_argument("--no-judge", action="store_true", help="skip the model call")
    ap.add_argument("--days", type=int, default=_WINDOW_DAYS)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--status", default="proposed")
    ap.add_argument("--approve", type=int)
    ap.add_argument("--reject", type=int)
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    _init_db()
    con = _db()
    if args.list:
        list_candidates(con, args.status)
        return
    if args.approve:
        decide(con, args.approve, "approved", args.note)
        return
    if args.reject:
        decide(con, args.reject, "rejected", args.note)
        return
    run(dry_run=args.dry_run, window_days=args.days, no_judge=args.no_judge)


if __name__ == "__main__":
    main()
