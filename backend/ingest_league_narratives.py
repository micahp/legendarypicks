#!/usr/bin/env python3
"""ingest_league_narratives.py — AI-generated league narratives (LinkedIn style).

Turns each league's collected chatter (news_items layer='narrative', from
Bluesky search posts + real headlines) into a one-line "what everyone's talking
about" narrative with supporting points — the DeepSeek pass on top of the
collector. Output goes to news_narratives (one row per league), served by
routers/news.py.

Run AFTER ingest_league_news.py. No ESPN hosts involved; the only network is
the DeepSeek chat API (key via _core._deepseek_key, 1 call per league).

Usage:
  LP_DB_PATH=/path/to/db python3 ingest_league_narratives.py [--leagues nfl,mlb] [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import _deepseek_chat, _init_db  # noqa: E402

_MAX_SOURCES = 6
_MIN_ITEMS = 2  # fewer than this and there's no "chatter" to summarize

_SYSTEM = (
    "You are the narrative desk for a sports news app. Given a league's recent "
    "headlines (real, from real sources), write what people are actually talking "
    "about in that league right now. Output STRICT JSON only, no prose around it: "
    '{"narrative": "<one sentence, under 25 words, present tense>", '
    '"points": ["<2-3 short supporting phrases, each under 12 words>"]}. '
    "Ground ONLY in the provided headlines. Do not invent topics, facts, or names "
    "not present in the list. Do not speculate about what might happen."
)


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


def _load_chatter(con, leagues):
    """league -> list of {headline, url, source, published} (narrative layer only)."""
    out = {}
    for lg in leagues:
        rows = con.execute(
            """SELECT headline, url, source, published FROM news_items
               WHERE league=? AND layer='narrative' AND url != ''
               ORDER BY published DESC LIMIT ?""",
            (lg, _MAX_SOURCES),
        ).fetchall()
        out[lg] = [dict(r) for r in rows]
    return out


def _generate(league, items):
    numbered = "\n".join(
        "%d. %s [%s]" % (i + 1, it["headline"], it["source"])
        for i, it in enumerate(items)
    )
    user = "League: %s\n\nRecent headlines people are talking about:\n%s" % (league, numbered)
    # High token ceiling + one retry: the reasoning model sometimes burns the
    # whole budget on hidden reasoning and returns empty content (the _core.py
    # quirk) — a tight max_tokens makes that failure intermittent.
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=4000)
        parsed = _parse_response(raw)
        if parsed and parsed.get("narrative"):
            points = [str(p) for p in parsed.get("points", [])][:3]
            return {
                "narrative": parsed["narrative"].strip(),
                "points": points,
                "sources": [{"headline": it["headline"], "url": it["url"], "source": it["source"]}
                            for it in items],
                "source_count": len(items),
            }
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", default="nfl,mlb,mls,ncaaf",
                    help="comma list of leagues to generate narratives for")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    _init_db()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    leagues = [l.strip() for l in args.leagues.split(",") if l.strip()]
    chatter = _load_chatter(con, leagues)

    print("League narrative generation — %d DeepSeek calls (1 per league with >= %d sources)" %
          (_MIN_ITEMS, _MIN_ITEMS))
    written = 0
    for lg in leagues:
        items = chatter.get(lg, [])
        if len(items) < _MIN_ITEMS:
            print("  %-6s skipped (%d sources < %d)" % (lg, len(items), _MIN_ITEMS))
            continue
        gen = _generate(lg, items)
        if gen is None:
            print("  %-6s FAILED to generate (model returned nothing parseable)" % lg)
            continue
        if args.dry_run:
            print("  %-6s [dry-run] %s" % (lg, gen["narrative"][:90]))
            continue
        con.execute(
            """INSERT INTO news_narratives(league, narrative, points, sources, source_count)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(league) DO UPDATE SET
                 narrative=excluded.narrative, points=excluded.points,
                 sources=excluded.sources, source_count=excluded.source_count,
                 generated_at=datetime('now')""",
            (lg, gen["narrative"], json.dumps(gen["points"]),
             json.dumps(gen["sources"]), gen["source_count"]),
        )
        written += 1
        print("  %-6s %s" % (lg, gen["narrative"][:90]))
    con.commit()
    con.close()
    print("Wrote %d league narratives to news_narratives" % written)


if __name__ == "__main__":
    main()
