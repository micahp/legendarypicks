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
import datetime
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

# A declined/failed conversation wipes its served news_narratives row — that's
# the "some are missing now" mechanism. The full served card that vanished is
# appended here so the editor can review what was lost during the run (Micah
# 2026-08-09: "during the run it should document the full of what cards were
# deleted just log it to a file and we can read that file when we run the
# review"). Run history keeps the OLD version, but not that it was SERVED then
# dropped — this log is that record.
_DELETIONS_LOG = os.environ.get("LP_NEWS_DELETIONS_LOG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "news-deletions.log")


def _log_deletion(con, conv, reason):
    """Append the full served card being deleted to the deletions log. Reads
    the row BEFORE the delete (same connection, pre-commit, sees the served
    state). No-op if nothing was served for the conv."""
    row = con.execute(
        """SELECT narrative, fan_voice, paragraph, sources, source_count,
                  generated_at FROM news_narratives WHERE conv_id=?""",
        (conv["id"],)).fetchone()
    if not row:
        return  # nothing served to delete
    os.makedirs(os.path.dirname(_DELETIONS_LOG), exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    block = (
        "\n[{ts}] DELETED conv={cid} league={lg} reason={reason}\n"
        "  served-since: {since}\n"
        "  narrative: {narr}\n"
        "  fan_voice: {fv}\n"
        "  paragraph: {para}\n"
        "  sources: {src}\n"
        "  source_count: {sc}\n".format(
            ts=ts, cid=conv["id"], lg=conv["league"], reason=reason,
            since=row["generated_at"], narr=row["narrative"],
            fv=row["fan_voice"], para=row["paragraph"],
            src=row["sources"], sc=row["source_count"]))
    with open(_DELETIONS_LOG, "a", encoding="utf-8") as f:
        f.write(block)

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
    "Each numbered item is `N. HEADLINE [source]` and real (non-bluesky) "
    "articles also carry their URL after the source. "
    "Output STRICT JSON only: "
    '{"narrative": "<one sentence: the conversation, anchored on the news — '
    'the title; unique voice, not a repeated template>", '
    '"fan_voice": "<the attributed fan side, one sentence>", '
    '"paragraph": "<2-4 sentences of plain ESPN-style body prose — fan voice '
    'with evidence, concrete names and numbers, room to flow; do NOT repeat '
    'the narrative>", '
    '"source_urls": ["<url>", ...]}, where source_urls lists the URLs of the '
    "REAL (non-bluesky) articles from the items that THIS card actually grounds "
    "in — only those whose content you used for the anchor or the evidence. "
    "Empty list if the card is built from social chatter with no real article. "
    "Never invent a URL; only cite URLs that appear in the items. "
    "Only if the items are truly unrelated (no shared theme at all) output "
    '{"narrative": null}. '
    "Ground ONLY in the provided items. Do not invent topics, facts, or names "
    "not present in the list. Do not speculate about what might happen. "
    "The card follows THIS conversation's theme. The user may have marked "
    "prior cards for this conversation GOOD or BAD (an editor's pass — 'more "
    "of this' / 'less of that'); where those marks appear in the prompt they "
    "show what on-theme and off-theme LOOK like here. Infer the boundary from "
    "the contrast between the good and bad examples — do not apply a fixed "
    "rule, and never just echo a bad example's wording. With no marks yet, "
    "use the conversation title as the theme."
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
    recent real articles.

    The conversation's bluesky posts are tagged with conv_id by the collector
    and are the fan-voice signal. The league's recent real (non-bluesky)
    articles are added as OFFICIAL ANCHOR material the fan posts are reacting
    to — a conversation whose chatter is all social still needs the real story
    to anchor the card (MLB salary-cap had zero real articles in its tagged
    bucket, so the desk had nothing to anchor on and correctly declined rather
    than fabricate; Micah 2026-08-07).

    The anchor pool is the league's recent real articles — NOT a seed-word
    headline match. Seed-word matching was too narrow: the MLS pro/rel card is
    anchored by the "commissioner Berg in charge" article, but that headline
    contains neither "relegation" nor "promotion", so it never reached the card
    (2026-08-09). The model picks which of these it actually grounds in (see
    _generate), so a broad pool does not attach irrelevant receipts.
    """
    conv_id, league = conv["id"], conv["league"]
    rows = con.execute(
        """SELECT headline, url, source, published FROM news_items
           WHERE conv_id=? AND url != ''
           ORDER BY published DESC LIMIT ?""",
        (conv_id, _MAX_SOURCES),
    ).fetchall()
    out = [dict(r) for r in rows]
    anchors = con.execute(
        """SELECT headline, url, source, published FROM news_items
           WHERE league=? AND source != 'bluesky' AND url != ''
           ORDER BY published DESC LIMIT 8""",
        (league,),
    ).fetchall()
    seen = {r["url"] for r in out}
    for r in anchors:
        if r["url"] not in seen:
            out.append(dict(r))
            seen.add(r["url"])
    return out


def _cited_sources(items, parsed):
    """Resolve the model's cited source_urls to the real-article receipts.
    Only URLs that are actually in the (non-bluesky) items become chips — a
    hallucinated URL never reaches the card (Micah, 2026-08-09)."""
    real = {it["url"]: it for it in items if it["source"] != "bluesky" and it.get("url")}
    cited = parsed.get("source_urls") or []
    if isinstance(cited, str):
        cited = [cited]
    out = []
    for url in cited:
        it = real.get(url)
        if it:
            out.append({"headline": it["headline"], "url": it["url"], "source": it["source"]})
    return out


def _editor_marks(con, conv_id):
    """The user's good/bad verdicts on prior runs of this conversation, joined
    to the run cards. These are the few-shot 'editor preferences' — Micah
    2026-08-09: 'i just want to come in as an editor every now and then and
    say that was bad do less of that, this was good do more of this'. The
    model infers the on-theme/off-theme boundary from the CONTRAST between
    good and bad cards; no hardcoded rule. Returns a block to prepend to the
    user prompt, or '' when there are no marks yet (today's behavior)."""
    rows = con.execute(
        """SELECT f.verdict, r.narrative FROM news_card_feedback f
           JOIN news_narratives_runs r ON r.id = f.run_id
           WHERE f.conv_id=? ORDER BY f.created_at DESC LIMIT 6""",
        (conv_id,)).fetchall()
    good = [r["narrative"] for r in rows if r["verdict"] == "good"]
    bad = [r["narrative"] for r in rows if r["verdict"] == "bad"]
    if not good and not bad:
        return ""
    parts = []
    if good:
        parts.append("GOOD cards for this conversation — match this kind of "
                     "framing (more of this):\n" +
                     "\n".join("- %s" % n for n in good[:3]))
    if bad:
        parts.append("BAD cards — do NOT frame it this way (less of this):\n" +
                     "\n".join("- %s" % n for n in bad[:2]))
    return "Editor marks:\n" + "\n".join(parts) + "\n\n"


def _generate(conv, items, marks=""):
    # Real (non-bluesky) items carry their URL so the model can cite the exact
    # article it grounded in; bluesky posts are signal only (never a chip).
    numbered = "\n".join(
        "%d. %s [%s]%s" % (i + 1, it["headline"], it["source"],
                           (" " + it["url"]) if it["source"] != "bluesky" and it.get("url") else "")
        for i, it in enumerate(items)
    )
    user = "%sConversation: %s (%s)\n\nRecent chatter:\n%s" % (
        marks, conv["title"], conv["league"], numbered)
    # Social posts feed the model's signal but are never shown as receipts —
    # only real articles the model actually cited become source chips. A
    # conversation whose chatter is ALL social still gets a card — that
    # chatter IS the signal (e.g. MLS relegation/promotion talk) — it just
    # renders with no source chips rather than being dropped entirely.
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=4000)
        parsed = _parse_response(raw)
        if parsed is None:
            continue  # unparseable — retry once
        if not parsed.get("narrative"):
            return {"declined": True}
        sources = _cited_sources(items, parsed)
        return {
            "narrative": parsed["narrative"].strip(),
            "fan_voice": str(parsed.get("fan_voice") or "").strip(),
            "paragraph": str(parsed.get("paragraph") or "").strip(),
            "sources": sources,
            "source_count": len(sources),
        }
    return None


def _generate_batch(convs_with_marks):
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
    for conv, items, marks in convs_with_marks:
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
            "%d. %s [%s]%s" % (i + 1, it["headline"], it["source"],
                               (" " + it["url"]) if it["source"] != "bluesky" and it.get("url") else "")
            for i, it in enumerate(unique[:10])
        )
        header = "### %s (%s) — %s" % (conv["id"], conv["league"], conv["title"])
        blocks.append(("%s%s\n%s" % (marks, header, numbered)) if marks else
                      ("%s\n%s" % (header, numbered)))
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
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=10000)
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
        marks = _editor_marks(con, conv["id"])
        loaded.append((conv, items, marks))

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
            for conv, items, marks in loaded:
                results[conv["id"]] = {"declined": False, "keep": True}
        else:
            for conv, items, marks in loaded:
                entry = parsed.get(conv["id"])
                if not entry or not entry.get("narrative"):
                    results[conv["id"]] = {"declined": True}
                    continue
                sources = _cited_sources(items, entry)
                results[conv["id"]] = {
                    "narrative": entry["narrative"].strip(),
                    "fan_voice": str(entry.get("fan_voice") or "").strip(),
                    "paragraph": str(entry.get("paragraph") or "").strip(),
                    "sources": sources,
                    "source_count": len(sources),
                }
    else:
        for conv, items, marks in loaded:
            gen = _generate(conv, items, marks)
            if gen is None:
                print("  %-18s FAILED (model returned nothing parseable after retry)" % conv["id"])
                continue
            results[conv["id"]] = gen

    written = 0
    for conv, items, marks in loaded:
        gen = results.get(conv["id"])
        if gen is None or gen.get("declined"):
            # A conversation that declines/fails this run must not keep
            # serving an old card (which may carry bluesky source chips).
            # Log the full served card being dropped first, so the editor can
            # review what vanished (Micah 2026-08-09).
            reason = "model-failure" if gen is None else "model-declined"
            if not args.dry_run:
                _log_deletion(con, conv, reason)
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            print("  %-18s no narrative worth mentioning (%s)" % (conv["id"], reason))
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
