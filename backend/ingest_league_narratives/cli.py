"""cli helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

from ingest_league_news import CONVERSATIONS
from narrative_variety import report as variety_report
from .anchor_routing import _MIN_ITEMS  # noqa: E402
from .content import _prompt_items  # noqa: E402
from .editor import _editor_marks, _log_deletion  # noqa: E402
from .generate import _generate, _generate_batch_chunked  # noqa: E402
from .parsing import _load_chatter  # noqa: E402
from .quality import _cited_sources, _drafts, _outlet_vocab, credited_outlets, had_publisher_material, speakers_shown, uncited_outlets, unsupported_allegation, voice_without_speakers  # noqa: E402
from .roles import is_social, social_leaks  # noqa: E402
from .timeline import newest_item, pool_key, split_by_age, stale_anchor  # noqa: E402

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--convs", default="",
                    help="comma list of conv ids to generate (default: all)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="regenerate even when the item pool has not changed")
    args = ap.parse_args()

    db_path = os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "picks.db")
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
    leaks = unchanged = 0
    for conv in convs:
        items = _load_chatter(con, conv)
        # A post that the `source` column calls published would be served as a
        # receipt. Say so — the guard keeps it out of the anchors either way,
        # but a silent guard means the source list never gets corrected.
        # Count the voice this conversation actually has. A card with none is
        # not an error — it just has no business writing a fan sentence — but
        # it is worth seeing, because a lane that is all bots means the
        # collector is following aggregators instead of people.
        shown = _prompt_items(items)
        if not speakers_shown(shown):
            print("    NO VOICE: %s — every post in the pool carries an "
                  "article; the card must not speak for fans" % conv["id"])
        for it in social_leaks(shown):
            leaks += 1
            print("    SOCIAL LEAK: source=%r is a post, not a publisher | %s"
                  % (it.get("source"), (it.get("headline") or "")[:60]))
        if len(items) < _MIN_ITEMS:
            print("  %-18s skipped (%d sources < %d)" % (conv["id"], len(items), _MIN_ITEMS))
            continue
        marks = _editor_marks(con, conv["id"])
        # Nothing new to say → say the same thing. A rewrite off an unchanged
        # pool can only change the WORDS, and a card whose title moves nightly
        # while the story stands still teaches a reader that a change means
        # nothing (Micah, 2026-08-12). --force regenerates anyway, which is what
        # you want after changing the prompt.
        key = pool_key(_prompt_items(items), marks)
        served = con.execute(
            "SELECT pool_key, generated_at FROM news_narratives WHERE conv_id=?",
            (conv["id"],)).fetchone()
        if served and served["pool_key"] == key and not args.force:
            unchanged += 1
            print("  %-18s unchanged — no new items since %s"
                  % (conv["id"], served["generated_at"]))
            continue
        loaded.append((conv, items, marks))

    # Batch path: ONE model call across all conversations so the model can
    # vary titles against each other (per-call generation repeats templates).
    results = {}
    if len(loaded) > 1:
        parsed = _generate_batch_chunked(loaded)
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
                # Resolve against the list the PROMPT numbered, not the raw
                # pool — see _prompt_items. These had drifted apart.
                sources = _cited_sources(_prompt_items(items), entry)
                results[conv["id"]] = {
                    "narrative": entry["narrative"].strip(),
                    "narrative_drafts": _drafts(entry, "narrative"),
                    "fan_voice": str(entry.get("fan_voice") or "").strip(),
                    "fan_voice_drafts": _drafts(entry, "fan_voice"),
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

    # Choose between the drafts BEFORE anything is written. Sameness is the one
    # defect a model cannot see from inside a single card: each sentence is
    # fine alone, and the reader meets them stacked on one page. Selection runs
    # in batch order, so the first card to use a shape keeps it and later cards
    # move to an alternate they already wrote — nothing is rewritten here, and
    # a card with no alternates simply keeps the model's own final.
    _order = [c["id"] for c, _i, _m in loaded if results.get(c["id"])
              and not results[c["id"]].get("declined")
              and not results[c["id"]].get("keep")]
    _resolved, _swaps = variety_resolve(
        [dict(results[cid], conv_id=cid) for cid in _order])
    for _card in _resolved:
        results[_card["conv_id"]].update(
            narrative=_card["narrative"], fan_voice=_card["fan_voice"])
    for _line in _swaps:
        print(_line)

    written = unattributed = ignored = stale = voiceless = 0
    surveyed = []
    namedrops = piled = 0
    for conv, items, marks in loaded:
        # The items the model was actually shown — every check below is
        # about what it saw, not about what sat unread in the pool.
        shown = _prompt_items(items)
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
        # A card must rest on published reporting. Social supplies the fan
        # voice; it never supplies the facts. Micah, 2026-08-10: "we need
        # trustworthy sources and can't expect the model to fact check every
        # post." This supersedes the earlier "chatter IS the signal" allowance
        # (2026-08-07) — chatter still shapes a card, it just cannot be the only
        # thing holding one up.
        # Judged on what the model was SHOWN, not on what sat unread in
        # the pool — the gate has to ask about the material the card was
        # actually written from.
        if not had_publisher_material(shown):
            print("  %-18s NOT SERVED — nothing published to stand on: %s"
                  % (conv["id"], gen["narrative"][:60]))
            if not args.dry_run:
                _log_deletion(con, conv, "no-publisher-material")
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            continue
        if unsupported_allegation(gen):
            print("  %-18s REFUSED — alleges something about people with no "
                  "publisher receipt: %s" % (conv["id"], gen["narrative"][:70]))
            if not args.dry_run:
                _log_deletion(con, conv, "unsupported-allegation")
                con.execute("DELETE FROM news_narratives WHERE conv_id=?", (conv["id"],))
            continue
        # Survey before the dry-run exit, not after the write. A dry run is
        # where you look at variety BEFORE committing a batch, so it has to see
        # the same cards a real run does — this used to report 0/0 because the
        # only append sat past the `continue` below.
        surveyed.append(dict(gen, conv_id=conv["id"]))
        if args.dry_run:
            print("  %-18s [dry-run] %s" % (conv["id"], gen["narrative"][:80]))
            print("  %-18s   drafts: %d title, %d fan | fan_voice: %s"
                  % ("", len(gen.get("narrative_drafts") or []),
                     len(gen.get("fan_voice_drafts") or []),
                     (gen.get("fan_voice") or "(none)")[:60]))
            continue
        con.execute(
            """INSERT INTO news_narratives(conv_id, league, title, narrative, fan_voice, paragraph, sources, source_count, pool_key, newest_item)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(conv_id) DO UPDATE SET
                league=excluded.league, title=excluded.title,
                narrative=excluded.narrative, fan_voice=excluded.fan_voice,
                paragraph=excluded.paragraph, sources=excluded.sources,
                source_count=excluded.source_count,
                pool_key=excluded.pool_key, newest_item=excluded.newest_item,
                generated_at=datetime('now')""",
            (conv["id"], conv["league"], conv["title"], gen["narrative"],
             gen.get("fan_voice", ""), gen.get("paragraph", ""),
             json.dumps(gen["sources"]), gen["source_count"],
             pool_key(shown, marks), newest_item(shown)),
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
        # Provenance the card claims in prose but cannot show. Reported, never
        # fatal — see uncited_outlets.
        loose = uncited_outlets(gen, _outlet_vocab(con))
        if loose:
            unattributed += 1
            print("    UNCITED OUTLET: names %s with no receipt for it"
                  % ", ".join(loose))
        # Mastheads in the subject slot. The chips already carry provenance, so
        # a second one is a digest of who wrote about the sport rather than a
        # story about it. Counted, never fatal — one attribution can be
        # legitimate when the reporting is itself the fact.
        credited = credited_outlets(gen, _outlet_vocab(con))
        namedrops += len(credited)
        if len(credited) > 1:
            piled += 1
            print("    MASTHEAD PILE-UP: attributes to %d outlets — %s"
                  % (len(credited), ", ".join(credited)))
        # A card that had reporting in front of it and cited none of it. Not
        # fatal either, but it is the signature of the six blind pools, so it
        # must be visible if it comes back.
        if not gen["source_count"] and had_publisher_material(shown):
            ignored += 1
            print("    IGNORED %d publisher items — card cites nothing"
                  % sum(1 for i in shown if not is_social(i)))
        # A card that reached past this week's reporting to stand on an old
        # article — how a 2025 feature became an August 2026 development.
        if stale_anchor(gen, shown):
            stale += 1
            print("    STALE ANCHOR: cites only background while %d "
                  "development(s) were shown"
                  % len(split_by_age(shown)[0]))
        # A constituency the card invented. Every other check governs where a
        # claim may come from; this one asks whether the party being quoted
        # was ever in the room.
        if voice_without_speakers(gen, shown):
            voiceless += 1
            print("    NO SPEAKER: speaks for fans with no post in the pool "
                  "| %s" % (gen.get("fan_voice") or "")[:70])
    # Sameness is the one defect that is invisible per card. Each of these
    # sentences is fine on its own; the reader meets them stacked on one page,
    # so the check has to run across the batch, after every card is written.
    for line in variety_report(surveyed):
        print(line)
    con.commit()
    con.close()
    print("Wrote %d conversation cards to news_narratives (%d unchanged, "
          "not rewritten)" % (written, unchanged))
    # Zero has to be said out loud, or "no warnings" and "never checked" look
    # identical in the log.
    print("Checks: %d social leaks, %d cards naming an uncited outlet, "
          "%d cards ignoring their own publisher items, "
          "%d cards anchored on background while newer reporting was shown, "
          "%d masthead attributions across %d cards piling them up, "
          "%d cards speaking for fans who were never in the pool"
          % (leaks, unattributed, ignored, stale, namedrops, piled, voiceless))
