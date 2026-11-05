#!/usr/bin/env python3
"""shadow_recovered.py -- recovered pregame designations for the shadow arm, from cutoff-supported article text only.

For each team-game whose injury article is published before the cutoff (article_timestamps.csv, team_game_matrix.csv)
and whose article was not edited after the cutoff, every nflverse 2025 player is searched in the cached article text.
A player gets a status only when a designation word (out, doubtful, questionable, ruled out) sits within 40
characters of the name and no negation word (lifted, cleared, returned, upgraded, full participation, removed,
activated, back) sits in the same window. Nothing is read from nflverse's final status here: it is used only to
size the coverage at the end, never to choose a status.

Output: shadow_recovered.csv (one row per player with a recovered status) and shadow_recovered_sample.txt
(random contexts for a manual precision check).

Usage: python3 shadow_recovered.py [--cache-dir DIR] [--sample N]
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import os
import random
import re
import sys
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
INJURIES = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw/injuries/injuries_2025.parquet"
STATUS = {"out": "Out", "ruled out": "Out", "doubtful": "Doubtful", "questionable": "Questionable"}
DESIGNATION = re.compile(r"\b(ruled out|out|doubtful|questionable)\b")
NEGATION = re.compile(r"\b(lifted|cleared|returned|upgraded|full participation|removed|activated|back|return to practice|limited|participat\w*|practice|physically unable|pup|not be|will not)\b")
SUFFIX = re.compile(r"\s+(jr\.?|sr\.?|ii|iii|iv)$", re.I)


def norm(text):
    text = html.unescape(text).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", text).lower()


def visible_text(page):
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return norm(re.sub(r"<[^>]+>", " ", page))


def status_for(text, name):
    """Recovered status for the name in this text, or (None, reason) when the context is ambiguous.

    The designation word nearest to the name wins, so "rule out three, cb X questionable" reads X as questionable.
    """
    statuses = []
    for m in re.finditer(re.escape(name), text):
        start, end = m.start(), m.end()
        window_start = max(0, start - 40)
        window = text[window_start: end + 40]
        if NEGATION.search(window):
            statuses.append((None, "negated"))
            continue
        best = None
        for d in DESIGNATION.finditer(window):
            s, e = window_start + d.start(), window_start + d.end()
            gap = 0 if (s < end and e > start) else (start - e if e <= start else s - end)
            if best is None or gap < best[0]:
                best = (gap, STATUS[d.group(1)])
        statuses.append((best[1], "designation") if best else (None, "not_designated"))
    if not statuses:
        return None, "not_designated"
    values = {s for s, _ in statuses if s}
    if len(values) == 1:
        return values.pop(), "designation"
    if not values:
        return None, "not_designated"
    return None, "conflicting_or_negated"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "lp-inj-resolve-cache"))
    ap.add_argument("--sample", type=int, default=15)
    a = ap.parse_args(argv)

    inj = pd.read_parquet(INJURIES)
    inj = inj[inj.week.between(1, 9) & inj.report_status.isin(["Out", "Doubtful", "Questionable"])]
    arts = {r["url"]: r for r in csv.DictReader(open(os.path.join(HERE, "article_timestamps.csv")))}
    matrix = {(r["game_id"], r["team"]): r for r in csv.DictReader(open(os.path.join(HERE, "team_game_matrix.csv")))}
    cov = list(csv.DictReader(open(os.path.join(HERE, "coverage-by-game.csv"))))

    rows, reasons, contexts = [], Counter(), []
    for r in cov:
        key = (r["game_id"], r["team"])
        mx = matrix[key]
        if mx["strict_timestamp_ok"] != "True":
            continue
        cutoff = dt.datetime.fromisoformat(mx["cutoff_utc"])
        for d, u in zip([x for x in r["report_dates"].split("; ") if x], [x for x in r["report_urls"].split("; ") if x]):
            art = arts.get(u)
            if not art or not art["published_utc"] or dt.datetime.fromisoformat(art["published_utc"]) >= cutoff:
                continue
            if art["modified_utc"] and dt.datetime.fromisoformat(art["modified_utc"]) > cutoff:
                reasons["edited_after_cutoff"] += 1
                continue
            path = os.path.join(a.cache_dir, hashlib.sha1(u.encode()).hexdigest() + ".html")
            if not os.path.exists(path):
                reasons["not_cached"] += 1
                continue
            text = visible_text(open(path, encoding="utf-8", errors="replace").read())
            players = inj[(inj.team == r["team"]) & (inj.week == int(r["week"]))]
            for _, p in players.iterrows():
                name = norm(SUFFIX.sub("", p.full_name.strip()))
                status, why = status_for(text, name)
                reasons[why] += 1
                if status:
                    rows.append([r["week"], r["game_id"], r["team"], p.gsis_id, p.full_name, status, u,
                                 art["published_utc"], mx["cutoff_utc"]])
                    contexts.append((p.full_name, status, text, name))

    with open(os.path.join(HERE, "shadow_recovered.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["week", "game_id", "team", "gsis_id", "player", "recovered_status", "article_url",
                    "published_utc", "cutoff_utc"])
        w.writerows(rows)

    random.seed(11)
    with open(os.path.join(HERE, "shadow_recovered_sample.txt"), "w") as f:
        for name, status, text, key in random.sample(contexts, min(a.sample, len(contexts))):
            i = text.find(key)
            f.write("%s | recovered %s | %s\n\n" % (name, status, text[max(0, i - 110): i + len(key) + 110]))

    print("recovered designations: %d player rows across %d team-games" % (
        len(rows), len({(x[1], x[2]) for x in rows})))
    for k, v in sorted(reasons.items()):
        print("  %-26s %d" % (k, v))
    print("by status:", dict(Counter(x[5] for x in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
