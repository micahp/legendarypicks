#!/usr/bin/env python3
"""player_coverage.py -- how many of a team's game-week designations a pre-cutoff injury article actually names.

For each team-game whose injury article was published before the cutoff (from article_timestamps.csv and
team_game_matrix.csv), the cached article text is searched for every nflverse 2025 player listed Out, Doubtful or
Questionable that week. Two measures are kept apart:
  mentioned   the player's full name appears in the article text
  designated  the name appears with a designation word (out, doubtful, questionable, ruled out) within 160 characters

nflverse's game-week report status is the target, not the decision. A practice-only listing is not counted.
Articles edited after the cutoff are listed with content_flag=modified_after_cutoff and reported on their own.
The final inactives list is never used as an input here; it is only a diagnostic in resolve_timestamps.py.

Usage: python3 player_coverage.py [--cache-dir DIR]
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import os
import re
import sys
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
INJURIES = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw/injuries/injuries_2025.parquet"
TARGET = {"Out", "Doubtful", "Questionable"}
DESIGNATION = re.compile(r"\b(out|doubtful|questionable|ruled out)\b", re.I)
SUFFIX = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", re.I)


def norm(text):
    text = html.unescape(text).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).lower()


def visible_text(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", page)


def name_of(full):
    return norm(SUFFIX.sub("", full.strip()))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "lp-inj-resolve-cache"))
    a = ap.parse_args(argv)

    inj = pd.read_parquet(INJURIES)
    inj = inj[inj.week.between(1, 9) & inj.report_status.isin(TARGET)]
    arts = {r["url"]: r for r in csv.DictReader(open(os.path.join(HERE, "article_timestamps.csv")))}
    matrix = {(r["game_id"], r["team"]): r for r in csv.DictReader(open(os.path.join(HERE, "team_game_matrix.csv")))}
    cov = list(csv.DictReader(open(os.path.join(HERE, "coverage-by-game.csv"))))

    out, tally = [], Counter()
    for r in cov:
        key = (r["game_id"], r["team"])
        cutoff = dt.datetime.fromisoformat(matrix[key]["cutoff_utc"])
        pre = []
        for d, u in zip([x for x in r["report_dates"].split("; ") if x], [x for x in r["report_urls"].split("; ") if x]):
            art = arts.get(u)
            if not art or not art["published_utc"]:
                continue
            pub = dt.datetime.fromisoformat(art["published_utc"])
            if pub < cutoff:
                modified = dt.datetime.fromisoformat(art["modified_utc"]) if art["modified_utc"] else None
                flag = "modified_after_cutoff" if modified and modified > cutoff else "modified_before_cutoff" if modified else "no_modified_date"
                pre.append((u, flag))
        if not pre:
            continue
        players = inj[(inj.team == r["team"]) & (inj.week == int(r["week"]))]
        if players.empty:
            continue
        for u, flag in pre:
            path = os.path.join(a.cache_dir, hashlib.sha1(u.encode()).hexdigest() + ".html")
            if not os.path.exists(path):
                tally["article_not_cached"] += 1
                continue
            text = norm(visible_text(open(path, encoding="utf-8", errors="replace").read()))
            for _, p in players.iterrows():
                name = name_of(p.full_name)
                hits = [m.start() for m in re.finditer(re.escape(name), text)]
                mentioned = bool(hits)
                designated = any(DESIGNATION.search(text[max(0, h - 160): h + len(name) + 160]) for h in hits)
                out.append([r["game_id"], r["team"], r["week"], p.gsis_id, p.full_name, p.report_status,
                            p.report_primary_injury, u, flag, int(mentioned), int(designated)])
                tally[(flag, p.report_status, "designated" if designated else "mentioned" if mentioned else "missed")] += 1

    with open(os.path.join(HERE, "player_coverage.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "team", "week", "gsis_id", "player", "nflverse_status", "injury", "article_url",
                    "content_flag", "mentioned", "designated"])
        w.writerows(out)

    print("player rows (nflverse Out/Doubtful/Questionable, pre-cutoff articles): %d" % len(out))
    for status in ("Out", "Doubtful", "Questionable"):
        rows = [o for o in out if o[5] == status]
        if rows:
            d = sum(o[10] for o in rows)
            m = sum(o[9] for o in rows)
            print("  %-12s n=%d  designated=%d (%.0f%%)  mentioned=%d (%.0f%%)" % (
                status, len(rows), d, 100.0 * d / len(rows), m, 100.0 * m / len(rows)))
    flags = Counter(o[8] for o in out)
    print("content flags:", dict(flags))
    if tally["article_not_cached"]:
        print("articles not cached: %d" % tally["article_not_cached"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
