#!/usr/bin/env python3
"""Coverage of each NFL team's own injury and inactives articles, read from its live HTML article sitemap.

Tier 2 only: these are live pages, dated to the day. Nothing here is checked against an archive, so no row
is cutoff-verified. Raw sitemap HTML is cached so a rerun does not refetch.

For each regular-season game, a report is a matched article dated in the six days before kickoff (up to the
day before), and inactives is a matched article dated on the day before or the day of kickoff. A failed fetch
or a sitemap with rows that do not parse is reported as FAILED and makes the run exit 1.

Usage:
  python3 sitemap_coverage.py --cache-dir DIR --out-dir DIR [--months 2025-09:2026-01]
                              [--schedule games.parquet] [--delay 1.0]
"""
import argparse
import csv
import datetime as dt
import html
import os
import re
import sys
import time
import urllib.error
import urllib.request

import pandas as pd

TEAMS = [
    ("ARI", "azcardinals.com"), ("ATL", "atlantafalcons.com"), ("BAL", "baltimoreravens.com"),
    ("BUF", "buffalobills.com"), ("CAR", "panthers.com"), ("CHI", "chicagobears.com"),
    ("CIN", "bengals.com"), ("CLE", "clevelandbrowns.com"), ("DAL", "dallascowboys.com"),
    ("DEN", "denverbroncos.com"), ("DET", "detroitlions.com"), ("GB", "packers.com"),
    ("HOU", "houstontexans.com"), ("IND", "colts.com"), ("JAX", "jaguars.com"), ("KC", "chiefs.com"),
    ("LV", "raiders.com"), ("LAC", "chargers.com"), ("LA", "therams.com"), ("MIA", "miamidolphins.com"),
    ("MIN", "vikings.com"), ("NE", "patriots.com"), ("NO", "neworleanssaints.com"), ("NYG", "giants.com"),
    ("NYJ", "newyorkjets.com"), ("PHI", "philadelphiaeagles.com"), ("PIT", "steelers.com"), ("SF", "49ers.com"),
    ("SEA", "seahawks.com"), ("TB", "buccaneers.com"), ("TEN", "tennesseetitans.com"), ("WAS", "commanders.com"),
]

SCHEDULE = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw/schedules/games.parquet"

ROW = re.compile(r'<tr><td[^>]*>(\d{4}-\d{2}-\d{2})</td><td><a href="([^"]+)"[^>]*>(.*?)</a></td></tr>', re.S)
TR = re.compile(r"<tr>", re.I)

# Each term is matched against the title and the URL slug, with hyphens read as spaces.
# "injured reserve" alone matches none of these: "injured" is not "injury".
TERMS = {
    "injury": r"injur(y|ies)",
    "practice": r"practice",
    "inactive": r"inactive",
    "ruled out": r"rules? out|ruled out",
    "questionable": r"questionable",
    "doubtful": r"doubtful",
    "downgraded": r"downgrad",
}
REPORT_TERMS = {"injury", "ruled out", "questionable", "doubtful", "downgraded"}  # bare "practice" is not a report


def months(spec):
    start, end = spec.split(":")
    y, m = map(int, start.split("-"))
    ey, em = map(int, end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def fetch(url, delay):
    err = "unknown"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (lp-research coverage check)"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = "HTTP %d" % e.code
        except Exception as e:  # network errors are retried, then reported
            err = type(e).__name__
        time.sleep(delay * 2 ** attempt + 1)
    raise RuntimeError("%s: %s" % (url, err))


def parse(text, domain):
    rows = []
    for date, href, title in ROW.findall(text):
        title = html.unescape(re.sub(r"\s+", " ", title)).strip()
        url = href if href.startswith("http") else "https://www.%s%s" % (domain, href)
        rows.append((date, url, title))
    return rows, len(TR.findall(text))


def terms_for(title, url):
    text = (title + " " + url.rsplit("/", 1)[-1]).lower().replace("-", " ")
    text = text.replace("practice squad", " ")  # practice-squad signings are not practice reports
    return [name for name, pat in TERMS.items() if re.search(pat, text)]


def load_team_month(abbr, domain, month, cache_dir, delay):
    path = os.path.join(cache_dir, "%s_%s.html" % (abbr, month))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    y, m = month.split("-")
    text = fetch("https://www.%s/sitemap/html/articles/%s/%s" % (domain, y, m), delay)
    if text is None:
        return None
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    time.sleep(delay)
    return text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--months", default="2025-09:2026-01")
    ap.add_argument("--schedule", default=SCHEDULE)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()
    os.makedirs(args.cache_dir, exist_ok=True)
    os.makedirs(args.out_dir, exist_ok=True)

    failures = []
    articles = {}  # abbr -> list of (date, url, title, terms)
    for abbr, domain in TEAMS:
        articles[abbr] = []
        for month in months(args.months):
            try:
                text = load_team_month(abbr, domain, month, args.cache_dir, args.delay)
            except RuntimeError as e:
                failures.append("%s %s: %s" % (abbr, month, e))
                print("FAILED %s %s: %s" % (abbr, month, e), flush=True)
                continue
            if text is None:
                failures.append("%s %s: no sitemap (404)" % (abbr, month))
                print("FAILED %s %s: no sitemap (404)" % (abbr, month), flush=True)
                continue
            rows, tr_count = parse(text, domain)
            if tr_count and len(rows) != tr_count - 1:  # minus the header row
                failures.append("%s %s: parsed %d rows of %d" % (abbr, month, len(rows), tr_count - 1))
                print("FAILED %s %s: parsed %d rows of %d" % (abbr, month, len(rows), tr_count - 1), flush=True)
            matched = 0
            for date, url, title in rows:
                found = terms_for(title, url)
                if found:
                    matched += 1
                    articles[abbr].append((date, url, title, found))
            print("%s %s: %d articles, %d matched" % (abbr, month, len(rows), matched), flush=True)

    with open(os.path.join(args.out_dir, "articles-matched.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["team", "date", "url", "title", "terms"])
        for abbr in articles:
            for date, url, title, found in sorted(articles[abbr]):
                w.writerow([abbr, date, url, title, ";".join(found)])

    sched = pd.read_parquet(args.schedule)
    sched = sched[(sched.season == 2025) & (sched.game_type == "REG")]
    rows_out = []
    for _, g in sched.sort_values(["week", "game_id"]).iterrows():
        gameday = dt.date.fromisoformat(str(g.gameday)[:10])
        for team, opp in ((g.home_team, g.away_team), (g.away_team, g.home_team)):
            arts = articles.get(team, [])
            rep, ina, injury_rep = [], [], False
            for date, url, title, found in arts:
                d = dt.date.fromisoformat(date)
                if gameday - dt.timedelta(days=6) <= d < gameday and REPORT_TERMS & set(found):
                    rep.append((date, url))
                    injury_rep = injury_rep or "injury" in found
                if gameday - dt.timedelta(days=1) <= d <= gameday and "inactive" in found:
                    ina.append((date, url))
            flags = []
            if not rep:
                flags.append("no_report")
            elif not injury_rep:
                flags.append("no_injury_article")  # only ruled-out or questionable items, no injury report
            if not ina:
                flags.append("no_inactives")
            rows_out.append([int(g.week), g.game_id, team, opp, gameday.isoformat(),
                             len(rep), "; ".join(d for d, _ in rep), "; ".join(u for _, u in rep),
                             len(ina), "; ".join(d for d, _ in ina), "; ".join(u for _, u in ina),
                             ",".join(flags)])
    with open(os.path.join(args.out_dir, "coverage-by-game.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["week", "game_id", "team", "opponent", "gameday", "n_report", "report_dates", "report_urls",
                    "n_inactives", "inactives_dates", "inactives_urls", "flags"])
        w.writerows(rows_out)

    gaps = sum(1 for r in rows_out if r[11])
    print("games (team-sides): %d; with a gap flag: %d" % (len(rows_out), gaps))
    if failures:
        print("FAILURES: %d" % len(failures))
        for item in failures:
            print("  " + item)
        return 1
    print("no fetch or parse failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
