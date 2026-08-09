#!/usr/bin/env python3
"""ingest_league_narratives.py — AI-generated league conversations.

Turns each CONVERSATION's collected chatter (news_items tagged with conv_id,
from Bluesky search posts + real headlines) into a two-layer card:
  - `narrative` — the NEWS ANCHOR: the official, high-importance story
    (a commissioner's decision, a signing, a rule change, a lawsuit).
  - `fan_voice` — what fans are SAYING and WANTING around it, WITH the
    evidence backing them (the packed stadium, the player quote, the
    lower-division energy). Fans have a voice: just because the league
    decided something does not mean fans agree or have stopped wanting the
    alternative, and the site shows why they're right (Micah, 2026-08-07).

Each conversation is its own row and gets to breathe — we do NOT merge all of
a league's conversations into one summary card. (The league summary is a
future pass over the conversation set, not this script's job.)

Output goes to news_narratives (one row per conv_id), served by routers/news.py.

Run AFTER ingest_league_news.py. No ESPN hosts involved; the only network is
the DeepSeek chat API (key via _core._deepseek_key, 1 call per conversation).

Usage:
  LP_DB_PATH=/path/to/db python3 ingest_league_narratives.py [--convs mls-pro-rel] [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import _deepseek_chat, _init_db  # noqa: E402
from ingest_league_news import CONVERSATIONS  # noqa: E402

_MAX_SOURCES = 12
_MIN_ITEMS = 2  # fewer than this and there's no "chatter" to summarize

_SYSTEM = (
    "You are the narrative desk for a sports news app. You are given the "
    "chatter around ONE important conversation in a league — real headlines "
    "and what people are posting. Write the card for it as a short paragraph. "
    "The paragraph must do two things: "
    "1) LEAD with the NEWS ANCHOR: the official, high-importance story "
    "(a commissioner's decision, a signing, a rule change, a lawsuit). State "
    "it plainly — this is what actually happened. "
    "2) Then carry the FAN VOICE with attribution. Fans have a voice: just "
    "because the league/commissioner decided something does not mean fans "
    "agree or have stopped wanting the alternative. Attribute their side "
    "explicitly — \"Fans argue…\", \"Supporters point to…\", \"Critics say…\" — "
    "and name the evidence (the packed stadium, the lower-division crowds, "
    "the player quote, a poll number) so the reader sees WHY they have a "
    "point. It must never sound like the app itself is making the fan's claim. "
    "`narrative` is the card's TITLE — one sentence that names the CONVERSATION "
    "anchored on the official story. Lead with the news event but frame it as "
    "the story people are talking about — the reader should see what the fight "
    "is, not just what happened. "
    "Write it in plain, literal news language (Strunk & White: omit needless "
    "words, prefer the standard to the offbeat). State who did what — subject, "
    "plain verb, object. NO idioms, NO puns, NO metaphors: never \\\"cranks the "
    "pressure cooker\\\", \\\"holds the line\\\", \\\"holds off\\\", \\\"locks in\\\", \\\"reality bites\\\", "
    "\\\"slams the door\\\", \\\"roars on\\\". \\\"Browns pick artificial turf for new "
    "stadium\\\" is right; \\\"Browns lock in turf\\\" is not. "
    "Spell out jargon — never abbreviate: write \\\"promotion and relegation\\\", "
    "not \\\"pro/rel\\\"; a reader skimming a title must not have to decode a "
    "shortened term. "
    "CRITICAL — vary the VOICE and STRUCTURE across cards. Do NOT copy the same "
    "template for every league. These are all acceptable shapes; pick the one "
    "that fits THIS conversation, and never reuse a shape you already used: "
    "- \\\"Skubal trade to Dodgers reignites the salary-cap debate\\\" (event → "
    "debate) "
    "- \\\"NHL free agency leaves proven players unsigned as cap money dries up\\\" "
    "(statement about the situation) "
    "- \\\"MLS commissioner rules out promotion and relegation, but fan demand "
    "for it grows\\\" "
    "(decision → but → fan pushback) "
    "- \\\"Worlds ticket resale prices hit $169,000 amid scalping complaints\\\" "
    "(controversy → concrete number) "
    "Vary the CADENCE too, not just the verb: some titles can use a colon, "
    "some a question, some a short clause — but all plain and literal, no "
    "figurative verbs. If two titles in the same "
    "run would open with the same kind of subject (a team, a league body, a "
    "commissioner), rephrase one so the openings differ. "
    "The title must never be a bare wire headline (\"Tigers traded Skubal to "
    "the Dodgers\"). It must name the conversation. But the phrasing, verb, and "
    "structure should feel different for each league — no two titles should "
    "read like they came off the same assembly line. "
    "`paragraph` is the BODY — the fan voice + context prose that follows "
    "the title; it must NOT restate the anchor sentence, because the title "
    "already said it. Write it like ESPN news copy: plain, everyday words "
    "(say 'deal', 'agreed', 'said', 'told' — not 'cited as a key factor', "
    "'a product of', 'adds weight to the criticism'). Name the actual people "
    "and keep the concrete numbers from the items (a player's name, a poll "
    "percentage, a count of stadiums, an injury, a dollar figure) — do NOT "
    "abstract them into summary nouns ('the imbalance', 'the criticism', "
    "'fan passion'). Spell out jargon everywhere — never write 'pro/rel' or "
    "other abbreviations in the body either; write 'promotion and relegation'. "
    "Omit needless words: no filler adjectives like "
    "'procedural', 'initial', 'formal', 'significant', 'key' when the plain "
    "noun carries it — never 'took a procedural step forward', never 'initial "
    "procedural move' ('the league took the first step toward adding a team "
    "in Las Vegas', not 'the league took the initial procedural move toward "
    "adding a franchise in Las Vegas'). When the items name several players "
    "or teams involved, name several of them — do not collapse the story "
    "into one example. If the items mention an injury to a named player, "
    "include it. It is fine to use more words and more sentences; give "
    "the prose room to flow. Do not stack three facts into one compressed "
    "sentence with colons — one fact per clause, comma-connected, and if a "
    "sentence gets crowded, split it. A longer sentence that reads easily "
    "beats a short one the reader has to unpack. "
    "Output STRICT JSON only: "
    '{"narrative": "<one sentence: the conversation, anchored on the news — '
    'the title; unique voice, not a repeated template>", '
    '"fan_voice": "<the attributed fan side, one sentence>", '
    '"paragraph": "<2-4 sentences of plain ESPN-style body prose — fan voice '
    'with evidence, concrete names and numbers, room to flow; do NOT repeat '
    'the narrative>", '
    "Only if the items are truly unrelated (no shared theme at all) output "
    '{"narrative": null}. '
    "Ground ONLY in the provided items. Do not invent topics, facts, or names "
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


def _load_chatter(con, conv):
    """Items for one conversation: the tagged bluesky chatter + the league's
    real-article narrative headlines.

    The conversation's bluesky posts are tagged with conv_id by the collector
    and are the fan-voice signal. Real-article headlines for the league
    (narrative layer, non-bluesky) are added as the OFFICIAL ANCHOR material
    the fan posts are reacting to — a conversation whose chatter is all
    social still needs the real story to anchor the card (MLB salary-cap had
    zero real articles in its tagged bucket, so the desk had nothing to anchor
    on and correctly declined rather than fabricate; Micah 2026-08-07).
    """
    conv_id, league = conv["id"], conv["league"]
    rows = con.execute(
        """SELECT headline, url, source, published FROM news_items
           WHERE conv_id=? AND url != ''
           ORDER BY published DESC LIMIT ?""",
        (conv_id, _MAX_SOURCES),
    ).fetchall()
    out = [dict(r) for r in rows]
    # Real-article anchors: league's narrative layer, not bluesky, that carry
    # the conversation's seed terms (fallback: any league narrative article).
    seed_terms = [t for t in conv["seed"].split() if len(t) > 3]
    like = " OR ".join("headline LIKE ?" for _ in seed_terms) or "1=1"
    params = ["%" + t + "%" for t in seed_terms]
    anchors = con.execute(
        """SELECT headline, url, source, published FROM news_items
           WHERE league=? AND layer='narrative' AND source != 'bluesky'
             AND url != '' AND (%s)
           ORDER BY published DESC LIMIT 5""" % like,
        [league] + params,
    ).fetchall()
    seen = {r["url"] for r in out}
    for r in anchors:
        if r["url"] not in seen:
            out.append(dict(r))
            seen.add(r["url"])
    return out


def _generate(conv, items):
    numbered = "\n".join(
        "%d. %s [%s]" % (i + 1, it["headline"], it["source"])
        for i, it in enumerate(items)
    )
    user = "Conversation: %s (%s)\n\nRecent chatter:\n%s" % (
        conv["title"], conv["league"], numbered)
    # Social posts feed the model's signal but are never shown as receipts —
    # only real articles become source chips (Micah, 2026-08-06). A
    # conversation whose chatter is ALL social still gets a card — that
    # chatter IS the signal (e.g. MLS relegation/promotion talk) — it just
    # renders with no source chips rather than being dropped entirely.
    real_sources = [it for it in items if it["source"] != "bluesky"]
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=4000)
        parsed = _parse_response(raw)
        if parsed is None:
            continue  # unparseable — retry once
        if not parsed.get("narrative"):
            return {"declined": True}
        return {
            "narrative": parsed["narrative"].strip(),
            "fan_voice": str(parsed.get("fan_voice") or "").strip(),
            "paragraph": str(parsed.get("paragraph") or "").strip(),
            "sources": [{"headline": it["headline"], "url": it["url"], "source": it["source"]}
                        for it in real_sources],
            "source_count": len(real_sources),
        }
    return None


def _generate_batch(convs_with_items):
    """One DeepSeek call for the WHOLE set of conversations.

    Per-conversation calls each see only their own chatter, so the model
    cannot coordinate variety — it grabbed the same metaphor example for
    MLB and MLS ("cranks the pressure cooker to a boil"). A batch call shows
    every conversation and every title at once, so the model must vary the
    voice and cadence across the set (Micah, 2026-08-07: "do they all sound
    the same?"). Output: {conv_id: {narrative, fan_voice, paragraph}}
    or {conv_id: null} when a conversation is genuinely unrelated chatter.
    """
    blocks = []
    for conv, items in convs_with_items:
        # Dedupe by headline first — the collector stores the same post from
        # multiple feeds (duplicate Kupp posts were crowding out the Will
        # Anderson injury item and the model never saw it).
        seen_h = set()
        unique = []
        for it in items:
            h = (it["headline"] or "").strip()
            if h in seen_h:
                continue
            seen_h.add(h)
            unique.append(it)
        numbered = "\n".join(
            "%d. %s [%s]" % (i + 1, it["headline"], it["source"])
            for i, it in enumerate(unique[:10])
        )
        blocks.append("### %s (%s) — %s\n%s" % (
            conv["id"], conv["league"], conv["title"], numbered))
    user = (
        "Here are ALL the conversations to write cards for. They are part of "
        "one batch: read every block, then write every card. The titles MUST "
        "be varied across the batch — different verbs, different structures, "
        "different cadence. If two cards would sound alike, rephrase one. "
        "Decline (null) only for a block whose chatter is genuinely unrelated. "
        "Output STRICT JSON: {\"conv_id\": {\"narrative\": ..., \"fan_voice\": "
        "..., \"paragraph\": ...}, ...}\n\n"
        + "\n\n".join(blocks)
    )
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=6000)
        parsed = _parse_response(raw)
        if parsed is None:
            continue
        return parsed
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--convs", default="",
                    help="comma list of conv ids to generate (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
    _init_db()
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    if args.convs:
        wanted = set(c.strip() for c in args.convs.split(",") if c.strip())
        convs = [c for c in CONVERSATIONS if c["id"] in wanted]
    else:
        convs = CONVERSATIONS

    print("Conversation generation — %d conversations (%s)" % (len(convs), "1 batch DeepSeek call" if len(convs) > 1 else "1 per-conversation call"))

    # Load chatter for every conversation once; keep the ones with enough items.
    loaded = []
    for conv in convs:
        items = _load_chatter(con, conv)
        if len(items) < _MIN_ITEMS:
            print("  %-18s skipped (%d sources < %d)" % (conv["id"], len(items), _MIN_ITEMS))
            continue
        loaded.append((conv, items))

    # Batch path: ONE model call across all conversations so the model can
    # vary titles against each other (per-call generation repeats templates).
    results = {}
    if len(loaded) > 1:
        parsed = _generate_batch(loaded)
        if parsed is None:
            # A totally failed batch must NOT wipe the live cards: leave the
            # old set serving and report. Per-conversation failures below
            # still delete only that conversation's stale card.
            print("  BATCH FAILED (model returned nothing parseable after retry) — keeping existing cards")
            results = {}
            for conv, items in loaded:
                results[conv["id"]] = {"declined": False, "keep": True}
        else:
            for conv, items in loaded:
                entry = parsed.get(conv["id"])
                if not entry or not entry.get("narrative"):
                    results[conv["id"]] = {"declined": True}
                    continue
                real_sources = [it for it in items if it["source"] != "bluesky"]
                results[conv["id"]] = {
                    "narrative": entry["narrative"].strip(),
                    "fan_voice": str(entry.get("fan_voice") or "").strip(),
                    "paragraph": str(entry.get("paragraph") or "").strip(),
                    "sources": [{"headline": it["headline"], "url": it["url"], "source": it["source"]}
                                for it in real_sources],
                    "source_count": len(real_sources),
                }
    else:
        for conv, items in loaded:
            gen = _generate(conv, items)
            if gen is None:
                print("  %-18s FAILED (model returned nothing parseable after retry)" % conv["id"])
                continue
            results[conv["id"]] = gen

    written = 0
    for conv, items in loaded:
        gen = results.get(conv["id"])
        if gen is None or gen.get("declined"):
            # A conversation that declines/fails this run must not keep
            # serving an old card (which may carry bluesky source chips).
            if not args.dry_run:
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            print("  %-18s no narrative worth mentioning" % conv["id"])
            continue
        if gen.get("keep"):
            continue
        if args.dry_run:
            print("  %-18s [dry-run] %s" % (conv["id"], gen["narrative"][:80]))
            continue
        con.execute(
            """INSERT INTO news_narratives(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conv_id) DO UPDATE SET
                league=excluded.league, title=excluded.title,
                narrative=excluded.narrative, fan_voice=excluded.fan_voice,
                paragraph=excluded.paragraph, sources=excluded.sources,
                source_count=excluded.source_count,
                generated_at=datetime('now')""",
            (conv["id"], conv["league"], conv["title"], gen["narrative"],
             gen.get("fan_voice", ""), gen.get("paragraph", ""),
             json.dumps(gen["sources"]), gen["source_count"]),
        )
        # Append to run history — every generation is kept, never overwritten,
        # so versions can be compared (Micah, 2026-08-07).
        con.execute(
            """INSERT INTO news_narratives_runs(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (conv["id"], conv["league"], conv["title"], gen["narrative"],
             gen.get("fan_voice", ""), gen.get("paragraph", ""),
             json.dumps(gen["sources"]), gen["source_count"]),
        )
        written += 1
        print("  %-18s %s" % (conv["id"], gen["narrative"][:80]))
    con.commit()
    con.close()
    print("Wrote %d conversation cards to news_narratives" % written)


if __name__ == "__main__":
    main()
