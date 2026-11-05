#!/usr/bin/env python3
"""capture_cbs_weekly_projections.py -- CBS Sports' published weekly fantasy projections, as long rows.

One page per position (QB, RB, WR, TE, K), non-PPR, the current week (the "tp" view). Every stat cell becomes
one row: source, season and week, scoring, position, player, team, stat, value, fetched_at and url. The rows
are written to a CSV. This script does not write the database; a table for them needs review first.

Defenses (DST) are not parsed: their table headers do not line up with their cells.

Request budget (paced_http): one request per position, five to www.cbssports.com, spaced MIN_INTERVAL seconds
apart, host budget HOST_BUDGET so the job refuses rather than running past it, and a disk cache so a rerun
inside the TTL costs nothing. The count of requests actually sent is printed.

A failed page, a page with no week in its title, a player row that does not parse, or a row whose value count
does not match its headers is reported and makes the run exit 1 without writing the CSV. A partial file would
look complete.

Usage: python3 capture_cbs_weekly_projections.py --out projections.csv [--cache-dir DIR] [--delay 3.0]
"""
import argparse
import csv
import datetime as dt
import html
import os
import re
import sqlite3
import sys

import paced_http

POSITIONS = ("QB", "RB", "WR", "TE", "K")
URL = "https://www.cbssports.com/fantasy/football/stats/{pos}/2026/tp/projections/nonppr/"
SCORING = "nonppr"
MIN_INTERVAL = 3.0
HOST_BUDGET = 10
UA = "Mozilla/5.0 (lp projections capture)"
GROUP_HEADERS = {"Passing", "Rushing", "Misc", "Receiving", "Kicking", "Defense", "FG", "XP", "Player", "Team", ""}
NAME = re.compile(r"^(.+?)\s+(QB|RB|WR|TE|FB|K|DST|DEF)\s+([A-Z]{2,4})\s+(.+?)\s+(QB|RB|WR|TE|FB|K|DST|DEF)\s+[A-Z]{2,4}$")
WEEK = re.compile(r"Week (\d+)")
FIELDS = ["source", "season", "week", "scoring", "position", "player", "team", "stat", "value", "fetched_at_utc", "url"]


def text_of(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def stat_keys(page):
    """Column names from the header cells. The description decides the group: 'att  Pass Attempts' is pass_att."""
    keys = []
    for th in re.findall(r"<th[^>]*>(.*?)</th>", page, re.S):
        t = text_of(th)
        if t in GROUP_HEADERS:
            continue
        token, _, desc = t.partition(" ")
        desc = desc.lower()
        if "pass" in desc or "thrown" in desc:
            prefix = "pass_"
        elif "rush" in desc:
            prefix = "rush_"
        elif "receiv" in desc or desc.startswith("rec "):
            prefix = "rec_"
        else:
            prefix = ""
        keys.append(prefix + token)
    return keys


def parse_position(pos, page, fetched_at, url, week):
    keys = stat_keys(page)
    rows, issues, players = [], [], set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [text_of(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 2:
            continue
        name_cell, values = cells[0], cells[1:]
        m = NAME.match(name_cell)
        if not m:
            issues.append("%s: unparsed player cell %r" % (pos, name_cell[:60]))
            continue
        player, team = m.group(4), m.group(3)
        if len(values) != len(keys):
            issues.append("%s %s: %d values for %d headers" % (pos, player, len(values), len(keys)))
            continue
        players.add(player)
        for key, value in zip(keys, values):
            rows.append(["cbs", "2026", "week %d" % week, SCORING, pos, player, team, key, value, fetched_at, url])
    return rows, issues, len(players)


def store(db_path, rows):
    """INSERT OR IGNORE into external_projections (run migrate_cbs_projection_table.py first). Returns (inserted, offered)."""
    con = sqlite3.connect(db_path, timeout=60)
    try:
        before = con.total_changes
        for source, season, week, scoring, pos, player, team, stat, value, fetched_at, url in rows:
            try:
                number = float(value.replace(",", ""))
            except ValueError:
                number = None  # a dash or a blank cell: kept as published in value_text
            con.execute(
                "INSERT OR IGNORE INTO external_projections (source, season, week, scoring, position, player, team, "
                "stat, value_text, value, fetched_at_utc, url) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (source, int(season), int(week.split()[1]), scoring, pos, player, team, stat, value, number,
                 fetched_at, url))
        con.commit()
        return con.total_changes - before, len(rows)
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache-dir", default="/tmp/lp-cbs-projections-cache")
    ap.add_argument("--delay", type=float, default=MIN_INTERVAL)
    ap.add_argument("--db", help="also store the rows in external_projections of this database")
    ap.add_argument("--allow-prod", action="store_true",
                    help="required to write the production database (a path ending in picks.db)")
    a = ap.parse_args(argv)
    if a.db and os.path.basename(os.path.normpath(a.db)) == "picks.db" and not a.allow_prod:
        raise SystemExit("refusing the production database %s without --allow-prod" % a.db)

    os.makedirs(a.cache_dir, exist_ok=True)
    before = len(os.listdir(a.cache_dir))
    fetch = paced_http.Fetcher(min_interval=a.delay, retry_waits=(5.0, 30.0), timeout=60, cache_dir=a.cache_dir,
                               host_budget=HOST_BUDGET, on_exhausted="refuse", headers={"User-Agent": UA})
    rows, failures, summary = [], [], []
    for pos in POSITIONS:
        url = URL.format(pos=pos)
        try:
            page = fetch.text(url)
        except Exception as exc:  # reported, not swallowed: the run fails below
            failures.append("%s: fetch failed: %s" % (pos, exc))
            continue
        # The time the page was fetched is the time its cache entry was written, not the time of this run.
        cache_file = fetch._path("text:" + url)
        fetched_at = dt.datetime.fromtimestamp(os.path.getmtime(cache_file), dt.timezone.utc).replace(microsecond=0).isoformat()
        title = re.search(r"<title>([^<]*)</title>", page)
        week_match = WEEK.search(title.group(1) if title else "")
        if not week_match:
            failures.append("%s: no week in the page title" % pos)
            continue
        week = int(week_match.group(1))
        pos_rows, issues, players = parse_position(pos, page, fetched_at, url, week)
        failures.extend(issues)
        if players == 0:
            failures.append("%s: no players parsed" % pos)
        rows.extend(pos_rows)
        summary.append((pos, week, players, len(pos_rows)))
    spent = len(os.listdir(a.cache_dir)) - before

    for pos, week, players, n in summary:
        print("%-3s week %d: %d players, %d stat rows" % (pos, week, players, n))
    print("requests sent: %d (cache hits are free)" % spent)
    if failures:
        print("FAILED, nothing written:")
        for f in failures:
            print("  " + f)
        return 1
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(rows)
    print("wrote %d rows to %s" % (len(rows), a.out))
    if a.db:
        inserted, offered = store(a.db, rows)
        print("stored %d new rows in %s; %d already held" % (inserted, a.db, offered - inserted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
