#!/usr/bin/env python3
"""build_pool.py -- candidate (article, player) pairs from strict pre-cutoff articles.

An article is in the pool only if article_evidence.csv marks it strict: published before the cutoff by its own
metadata AND its current dateModified not after the cutoff. The candidate players are that team's 2025 weekly
roster for the game's week, matched by full name. Injury status is never used to choose candidates, so the
pool is not selected on the outcome. nflverse's final designations appear nowhere in this file.

Output: pool.csv, one row per (article, rostered player whose full name appears in the article text), with a
flag for whether the article carries an official injury table.

Usage: python3 build_pool.py [--cache-dir DIR]
"""
import argparse
import csv
import datetime as dt
import hashlib
import os
import re
import sys
from collections import Counter

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROSTERS = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw/weekly_rosters/roster_weekly_2025.parquet"
SUFFIX = re.compile(r"\s+(jr|sr|ii|iii|iv)$")
FIELDS = ["game_id", "team", "week", "gsis_id", "player", "article_url", "published_utc", "modified_utc",
          "cutoff_utc", "has_status_table", "n_mentions"]


def key(text):
    """Comparison form of a name or article text: lower case, no periods, apostrophes or repeated spaces."""
    text = text.replace("’", "'").replace("‘", "'").replace(".", "").replace("'", "").lower()
    return re.sub(r"\s+", " ", text).strip()


def name_key(full):
    return SUFFIX.sub("", key(full))


def page_text(page):
    """Visible text with tags replaced by spaces; table cells stay in, so a table's names are found."""
    page = re.sub(r"<script.*?</script>|<style.*?</style>", " ", page, flags=re.S | re.I)
    return key(re.sub(r"<[^>]+>", " ", page).replace("&amp;", "&"))


def has_status_table(page):
    for tbl in re.findall(r"<table.*?</table>", page, re.S | re.I):
        head = " ".join(re.findall(r"<th[^>]*>(.*?)</th>", tbl, re.S | re.I)).lower()
        if "player" in head and "status" in head:
            return True
    return False


def load_roster(team, week):
    wr = pd.read_parquet(ROSTERS, columns=["season", "game_type", "team", "week", "gsis_id", "full_name"])
    wr = wr[(wr.season == 2025) & (wr.game_type == "REG") & (wr.team == team) & (wr.week == week)]
    return [(r.gsis_id, r.full_name) for r in wr.itertuples() if isinstance(r.full_name, str)]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", default="/tmp/lp-inj-resolve-cache")
    a = ap.parse_args(argv)

    matrix = {(r["game_id"], r["team"]): r for r in csv.DictReader(open(os.path.join(HERE, "team_game_matrix.csv")))}
    evidence = [r for r in csv.DictReader(open(os.path.join(HERE, "article_evidence.csv")))
                if r["kind"] == "report" and r["strict"] == "True"]
    arts = {}
    for r in evidence:
        arts.setdefault((r["game_id"], r["team"], r["url"]), r)

    rows, tally = [], Counter()
    for (game_id, team, url), ev in sorted(arts.items()):
        path = os.path.join(a.cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".html")
        if not os.path.exists(path):
            raise SystemExit("strict article not in cache: %s" % url)
        page = open(path, encoding="utf-8", errors="replace").read()
        text = page_text(page)
        week = int(matrix[(game_id, team)]["week"])
        table = has_status_table(page)
        roster = load_roster(team, week)
        tally["articles"] += 1
        tally["roster_players"] += len(roster)
        for gsis, full in roster:
            name = name_key(full)
            n = len(re.findall(r"(?<![a-z])" + re.escape(name) + r"(?![a-z])", text))
            if n:
                rows.append([game_id, team, week, gsis, full, url, ev["published_utc"], ev["modified_utc"],
                             ev["cutoff_utc"], int(table), n])
                tally["pairs"] += 1
        tally["articles_with_status_table"] += int(table)

    with open(os.path.join(HERE, "pool.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(rows)

    print("strict report articles: %d" % tally["articles"])
    print("  with an official status table: %d" % tally["articles_with_status_table"])
    print("roster players checked: %d" % tally["roster_players"])
    print("candidate pairs (name found in article): %d" % tally["pairs"])
    print("distinct team-games: %d" % len({(r[0], r[1]) for r in rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
