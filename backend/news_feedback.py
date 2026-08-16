#!/usr/bin/env python3
"""news_feedback.py — the editor's pass over the news engine.

Micah 2026-08-09: "i don't want to define it. i just want to come in as an
editor every now and then and review topics and say that was bad do less of
that and this was good do more of this."

This is the thin handle for that. A verdict on a RUN (a specific generated
version of a conversation card) is the teaching signal — 'good' / 'bad'.
Good runs become positive few-shot examples the next generation matches;
bad runs become negatives it avoids (see _editor_marks in
ingest_league_narratives.py). No per-article labeling, no rule-writing —
the model infers the boundary from the contrast between good and bad cards.

Run history (news_narratives_runs) keeps every version, so you can mark
the Makhachev run good and the Pereira run bad for the same conversation.

Usage:
  # find runs to review (newest first, with any existing verdict):
  news_feedback.py --conv ufc-title-fight --list

  # the editorial verdict:
  news_feedback.py --run 42 --verdict good --note "title picture, not safety"
  news_feedback.py --run 39 --verdict bad  --note "safety tangent, confusing"

  # promote a good run to the SERVED card right now ('do more of this' now):
  news_feedback.py --serve 42

  # review the marks for a conversation:
  news_feedback.py --conv ufc-title-fight --show

  # per-conversation good/bad counts across the board:
  news_feedback.py --status
"""
import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _core import _init_db  # noqa: E402

_VERDICTS = ("good", "bad")


def _db_path():
    return os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")


def _deletions_log():
    return os.environ.get("LP_NEWS_DELETIONS_LOG") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "news-deletions.log")


def _connect():
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


def cmd_deletions():
    """Print the deletions log — the full served cards a run wiped (the
    'some are missing now' record). Read this during the editor's review."""
    path = _deletions_log()
    if not os.path.exists(path):
        print("No deletions logged yet (%s)." % path)
        return
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if not text.strip():
        print("Deletions log is empty (%s)." % path)
        return
    print(text)


def cmd_list(con, conv_id):
    rows = con.execute(
        """SELECT r.id, r.generated_at, r.narrative, r.source_count,
                  (SELECT group_concat(verdict) FROM news_card_feedback
                    WHERE run_id=r.id) AS verdicts
           FROM news_narratives_runs r
           WHERE r.conv_id=? ORDER BY r.generated_at DESC""",
        (conv_id,)).fetchall()
    if not rows:
        print("No runs for %s (the conversation may have declined every "
              "generation, or conv_id is wrong)." % conv_id)
        return
    print("Runs for %s (newest first):" % conv_id)
    for r in rows:
        tag = ""
        if r["verdicts"]:
            tag = "  [%s]" % r["verdicts"]
        print("  #%d  %s%s" % (r["id"], r["generated_at"], tag))
        print("       %s  (sources=%d)" % (r["narrative"][:96], r["source_count"]))


def cmd_verdict(con, run_id, verdict, note):
    if verdict not in _VERDICTS:
        sys.exit("verdict must be one of %s" % "/".join(_VERDICTS))
    row = con.execute(
        "SELECT conv_id, narrative FROM news_narratives_runs WHERE id=?",
        (run_id,)).fetchone()
    if not row:
        sys.exit("No run with id=%d (use --conv X --list to find ids)." % run_id)
    con.execute(
        """INSERT INTO news_card_feedback(run_id, conv_id, verdict, note)
           VALUES (?, ?, ?, ?)""",
        (run_id, row["conv_id"], verdict, note or ""))
    con.commit()
    print("Marked run #%d %s for %s." % (run_id, verdict.upper(), row["conv_id"]))
    print("  %s" % row["narrative"][:96])
    n = con.execute(
        "SELECT count(*) FROM news_card_feedback WHERE conv_id=? AND verdict=?",
        (row["conv_id"], verdict)).fetchone()[0]
    print("  %s now has %d %s mark(s) — next generation will %s." % (
        row["conv_id"], n, verdict,
        "match this framing" if verdict == "good" else "avoid this framing"))


def cmd_serve(con, run_id):
    """Promote a run's card to the served news_narratives row — 'do more of
    this' made immediate, without waiting for the next generation."""
    row = con.execute(
        """SELECT conv_id, league, title, narrative, fan_voice, paragraph,
                  sources, source_count FROM news_narratives_runs WHERE id=?""",
        (run_id,)).fetchone()
    if not row:
        sys.exit("No run with id=%d (use --conv X --list to find ids)." % run_id)
    con.execute(
        """INSERT INTO news_narratives(conv_id, league, title, narrative,
               fan_voice, paragraph, sources, source_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(conv_id) DO UPDATE SET
             league=excluded.league, title=excluded.title,
             narrative=excluded.narrative, fan_voice=excluded.fan_voice,
             paragraph=excluded.paragraph, sources=excluded.sources,
             source_count=excluded.source_count,
             generated_at=datetime('now')""",
        (row["conv_id"], row["league"], row["title"], row["narrative"],
         row["fan_voice"], row["paragraph"], row["sources"], row["source_count"]))
    con.commit()
    print("Serving run #%d for %s." % (run_id, row["conv_id"]))
    print("  %s" % row["narrative"][:96])


def cmd_show(con, conv_id):
    rows = con.execute(
        """SELECT f.verdict, f.note, f.created_at, r.narrative
           FROM news_card_feedback f
           JOIN news_narratives_runs r ON r.id = f.run_id
           WHERE f.conv_id=? ORDER BY f.created_at DESC""",
        (conv_id,)).fetchall()
    if not rows:
        print("No marks for %s yet." % conv_id)
        return
    print("Marks for %s (newest first):" % conv_id)
    for r in rows:
        print("  [%s] %s  %s" % (r["verdict"].upper(), r["created_at"],
                                 r["note"] or ""))
        print("       %s" % r["narrative"][:96])


def cmd_status(con):
    rows = con.execute(
        """SELECT conv_id,
                  sum(verdict='good') AS good,
                  sum(verdict='bad') AS bad
           FROM news_card_feedback GROUP BY conv_id ORDER BY conv_id"""
    ).fetchall()
    if not rows:
        print("No feedback recorded yet. Use --conv X --list then --run N "
              "--verdict good|bad.")
        return
    for r in rows:
        print("  %-20s good=%d  bad=%d" % (r["conv_id"], r["good"], r["bad"]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--conv", help="conversation id (for --list / --show)")
    ap.add_argument("--list", action="store_true", help="list runs for --conv")
    ap.add_argument("--run", type=int, help="run id to verdict (with --verdict)")
    ap.add_argument("--verdict", choices=_VERDICTS, help="mark the --run good|bad")
    ap.add_argument("--note", help="why (free text, optional)")
    ap.add_argument("--serve", type=int, help="promote run id to the served card")
    ap.add_argument("--show", action="store_true", help="show marks for --conv")
    ap.add_argument("--status", action="store_true",
                    help="per-conversation good/bad counts")
    ap.add_argument("--deletions", action="store_true",
                    help="print the deletions log (cards wiped during runs)")
    args = ap.parse_args()

    _init_db()
    con = _connect()
    if args.deletions:
        cmd_deletions()
    elif args.status:
        cmd_status(con)
    elif args.serve:
        cmd_serve(con, args.serve)
    elif args.run is not None and args.verdict:
        cmd_verdict(con, args.run, args.verdict, args.note)
    elif args.conv and args.show:
        cmd_show(con, args.conv)
    elif args.conv and args.list:
        cmd_list(con, args.conv)
    else:
        ap.print_help()
    con.close()


if __name__ == "__main__":
    main()
