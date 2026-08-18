"""editor helpers from the narrative pipeline."""
import re
import json
import os
import sys
import sqlite3
import datetime
import hashlib
import argparse


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

# A declined/failed conversation wipes its served news_narratives row — that's
# the "some are missing now" mechanism. The full served card that vanished is
# appended here so the editor can review what was lost during the run (Micah
# 2026-08-09: "during the run it should document the full of what cards were
# deleted just log it to a file and we can read that file when we run the
# review"). Run history keeps the OLD version, but not that it was SERVED then
# dropped — this log is that record.
_DELETIONS_LOG = os.environ.get("LP_NEWS_DELETIONS_LOG") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "news-deletions.log")

_BODY_CHARS = 600

_SHOW_ANCHORS = 6    # of those, reserved for published articles

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
