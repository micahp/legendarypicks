"""generate helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse

# The 2026-08-18 split dropped the `_core` import the pre-split file carried, so
# both call sites here died on `NameError: name '_deepseek_chat' is not defined`.
# Nothing caught it because news-collect.sh was ALSO calling a deleted file path,
# so this module never ran.
from _core import _deepseek_chat  # noqa: E402
from .content import _prompt_items  # noqa: E402
from .parsing import _parse_response  # noqa: E402
from .prompt import _SYSTEM  # noqa: E402
from .quality import _cited_sources, _drafts  # noqa: E402
from .timeline import _numbered  # noqa: E402

_BATCH_MAX_TOKENS = 24000  # reasoning shares this budget; 10000 truncated 13 cards

# One card, not thirteen — but reasoning_effort=high spends the ceiling BEFORE
# the answer, so the floor is set by the reasoning, not by the output size.
# Measured 2026-08-17: a comparable single call spent 6362 reasoning tokens.
_SINGLE_MAX_TOKENS = 12000

_BATCH_CHUNK = 4           # fallback width when the wide batch will not parse

def _generate(conv, items, marks=""):
    # Real (non-bluesky) items carry their URL so the model can cite the exact
    # article it grounded in; bluesky posts are signal only (never a chip).
    # Same selection as the batch path, so citation numbers mean the same thing
    # on both — and so a single-conversation run cannot be shown a different
    # pool than a batched one.
    items = _prompt_items(items)
    numbered = _numbered(items)
    user = "%sToday is %s.\n\nConversation: %s (%s)\n\nRecent chatter:\n%s" % (
        marks, datetime.date.today().isoformat(), conv["title"], conv["league"],
        numbered)
    # Social posts feed the model's signal but are never shown as receipts —
    # only real articles the model actually cited become source chips. A
    # conversation whose chatter is ALL social still gets a card — that
    # chatter IS the signal (e.g. MLS relegation/promotion talk) — it just
    # renders with no source chips rather than being dropped entirely.
    # _SINGLE_MAX_TOKENS, not 4000. Reasoning shares this budget and spends it
    # first, so a ceiling the reasoning alone can exhaust returns an EMPTY answer
    # with finish_reason='length' -- which `_parse_response` cannot tell from a
    # malformed one, so this loop burned the ceiling TWICE and called it
    # unparseable. Measured on discover_topics' judge call, the same shape and
    # the same day: 4000 -> reasoning_tokens 4000, content length 0.
    # _BATCH_MAX_TOKENS above already carried this lesson ("10000 truncated 13
    # cards"); it just never reached this path.
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=_SINGLE_MAX_TOKENS)
        parsed = _parse_response(raw)
        if parsed is None:
            continue  # unparseable — retry once
        if not parsed.get("narrative"):
            return {"declined": True}
        sources = _cited_sources(items, parsed)
        return {
            "narrative": parsed["narrative"].strip(),
            "narrative_drafts": _drafts(parsed, "narrative"),
            "fan_voice": str(parsed.get("fan_voice") or "").strip(),
            "fan_voice_drafts": _drafts(parsed, "fan_voice"),
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
        numbered = _numbered(_prompt_items(items))
        header = "### %s (%s) — %s" % (conv["id"], conv["league"], conv["title"])
        blocks.append(("%s%s\n%s" % (marks, header, numbered)) if marks else
                      ("%s\n%s" % (header, numbered)))
    user = (
        "Today is %s.\n\n" % datetime.date.today().isoformat() +
        "Here are ALL the conversations to write cards for. They are part of "
        "one batch: read every block, then write every card. The titles MUST "
        "be varied across the batch — different verbs, different structures, "
        "different cadence. If two cards would sound alike, rephrase one. "
        "Decline (null) only for a block whose chatter is genuinely unrelated. "
        # source_urls MUST be in this schema. It was missing, and since the
        # batch prompt's schema is what the model actually follows, nine of
        # twelve cards came back with no receipts at all while their pools held
        # three to six real articles each (2026-08-10).
        "Output STRICT JSON: {\"conv_id\": {\"narrative\": ..., \"fan_voice\": "
        "..., \"paragraph\": ..., \"source_ids\": [<n>, ...]}, ...}\n"
        "source_ids are the NUMBERS of the real (non-social) items above that "
        "THIS card actually grounds in — just the integers from the numbered "
        "list, e.g. [1, 4]. Cite every article you drew a fact from; empty "
        "list only when the card is built purely from social chatter.\n\n"
        + "\n\n".join(blocks)
    )
    for attempt in (0, 1):
        raw = _deepseek_chat(_SYSTEM, user, max_tokens=_BATCH_MAX_TOKENS)
        parsed = _parse_response(raw)
        if parsed is None:
            continue
        return parsed
    return None

def _generate_batch_chunked(convs_with_marks, size=_BATCH_CHUNK):
    """One call for the whole set, falling back to chunks if that fails.

    Measured 2026-08-10: 3 conversations parse fine, 13 come back unparseable.
    DeepSeek runs at reasoning_effort=high and reasoning shares the max_tokens
    budget, so a wide batch spends it thinking and the JSON arrives truncated.
    A whole run of stale cards is the worst outcome — worse than losing some
    cross-card title variety — so retry in chunks before giving up.
    """
    parsed = _generate_batch(convs_with_marks)
    if parsed is not None:
        return parsed
    if len(convs_with_marks) <= size:
        return None
    print("  batch of %d unparseable — retrying in chunks of %d"
          % (len(convs_with_marks), size))
    merged = {}
    for i in range(0, len(convs_with_marks), size):
        chunk = convs_with_marks[i:i + size]
        got = _generate_batch(chunk)
        if got:
            merged.update(got)
        else:
            print("    chunk %d-%d failed" % (i, i + len(chunk)))
    return merged or None
