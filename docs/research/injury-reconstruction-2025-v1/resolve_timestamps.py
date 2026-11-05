#!/usr/bin/env python3
"""resolve_timestamps.py -- publisher timezone calibration, article timestamps and the 2025 team-game matrix.

Inputs: coverage-by-game.csv (from sitemap_coverage.py) and the nflverse 2025 schedule (kickoffs in Eastern).

Timestamps come from each article's own machine-readable metadata (JSON-LD datePublished and dateModified, which
carry an explicit UTC offset). A publisher's timezone is calibrated only from pages where the visible date line
can be compared with that machine-readable time; nothing is inferred from a team's location. A publisher whose
calibration is missing or conflicting is tz_unresolved, and its articles cannot enter the strict set.

Cutoff: kickoff minus 90 minutes, in UTC. A publication within 120 seconds of the cutoff is boundary; it stays
out of the strict set unless second-level metadata settles it. Content version is kept apart from publication
time: a current page whose dateModified is after the cutoff may not show what existed at publication, and a page
with no dateModified has an unknown version. Strictness is decided per article (article_evidence.csv: published
before the cutoff AND dateModified not after it). A team-game is strict only with at least one strict report article
and no report article that cannot establish a pregame version.

Articles dated two or more days before kickoff need no fetch: they precede the cutoff in any timezone, and they
are marked pre_cutoff_by_date.

Usage: python3 resolve_timestamps.py [--plan] [--cache-dir DIR]
  --plan  count the fetches and stop, without touching the network.
"""
import argparse
import csv
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict

import pandas as pd
import pytz

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = "/root/lp-snapshots/nfl-backfill-2026-10-27/raw/schedules/games.parquet"
CANDIDATE_ZONES = ["America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"]
BOUNDARY_SECONDS = 120
CALIBRATION_EXTRA = 3
UA = "Mozilla/5.0 (research timestamp resolver)"
ARTICLE_TYPES = {"NewsArticle", "Article", "BlogPosting", "WebPage"}
VISIBLE = re.compile(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? (\d{1,2}), (\d{4}) at (\d{1,2}):(\d{2}) ([AP]M)")
ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?Z")
MONTHS = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def parse_iso_utc(text):
    m = ISO.search(text or "")
    if not m:
        return None
    return dt.datetime(*map(int, m.groups()), tzinfo=pytz.utc)


def parse_visible(text):
    m = VISIBLE.search(text)
    if not m:
        return None
    mon, day, year, hour, minute, ampm = m.groups()
    hour = int(hour) % 12 + (12 if ampm == "PM" else 0)
    return dt.datetime(int(year), MONTHS[mon[:3]], int(day), hour, int(minute))


def jsonld_article(page):
    """The article's own JSON-LD object: an article type whose headline matches og:title, else the only one."""
    og = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    og_title = html.unescape(og.group(1)).strip() if og else ""
    found = []
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if isinstance(obj, dict) and obj.get("@type") in ARTICLE_TYPES and obj.get("datePublished"):
                found.append(obj)
    matched = [o for o in found if html.unescape(o.get("headline", "")).strip() == og_title]
    if len(matched) == 1:
        return matched[0], "headline_matches_og_title"
    if not matched and len(found) == 1:
        return found[0], "only_article_object"
    return None, "ambiguous_or_missing" if found else "no_article_jsonld"


def fetch(url, cache_dir, delay, state):
    path = os.path.join(cache_dir, hashlib.sha1(url.encode()).hexdigest() + ".html")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    if state["sent"] is not None:
        time.sleep(delay)
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read().decode("utf-8", "replace")
            state["sent"] = (state["sent"] or 0) + 1
            with open(path, "w", encoding="utf-8") as f:
                f.write(body)
            return body
        except urllib.error.HTTPError as exc:
            last = "HTTP %d" % exc.code
            if exc.code == 404:
                break
        except Exception as exc:  # network errors are retried, then reported by the caller
            last = type(exc).__name__
        time.sleep(delay * (2 ** attempt))
    raise RuntimeError("%s: %s" % (url, last))


def load_games():
    sched = pd.read_parquet(SCHEDULE)
    sched = sched[(sched.season == 2025) & (sched.game_type == "REG")]
    games = {}
    for _, g in sched.iterrows():
        day = dt.date.fromisoformat(str(g.gameday)[:10])
        hh, mm = map(int, str(g.gametime).split(":")[:2])
        kickoff = pytz.timezone("America/New_York").localize(dt.datetime(day.year, day.month, day.day, hh, mm)).astimezone(pytz.utc)
        games[g.game_id] = {"kickoff": kickoff, "cutoff": kickoff - dt.timedelta(minutes=90), "gameday": day,
                            "week": int(g.week), "home": g.home_team, "away": g.away_team}
    return games


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--cache-dir", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "lp-inj-resolve-cache"))
    a = ap.parse_args(argv)
    os.makedirs(a.cache_dir, exist_ok=True)

    games = load_games()
    rows = list(csv.DictReader(open(os.path.join(HERE, "coverage-by-game.csv"))))
    team_games = []
    needed = {}  # url -> sitemap date
    for r in rows:
        g = games.get(r["game_id"])
        if g is None:
            raise SystemExit("no kickoff for %s" % r["game_id"])
        refs = []
        for kind, dates_col, urls_col in (("report", "report_dates", "report_urls"), ("inactives", "inactives_dates", "inactives_urls")):
            dates = [d for d in r[dates_col].split("; ") if d]
            urls = [u for u in r[urls_col].split("; ") if u]
            for d, u in zip(dates, urls):
                refs.append((kind, u, d))
                days_before = (g["gameday"] - dt.date.fromisoformat(d)).days
                if days_before < 2:
                    needed[u] = d
        team_games.append((r, g, refs))

    domains = sorted({re.sub(r"^https?://www\.", "", u).split("/")[0] for u in needed})
    extra = {}
    for line in csv.DictReader(open(os.path.join(HERE, "articles-matched.csv"))):
        if line["date"].startswith("2025-10") and line["url"] not in needed:
            dom = re.sub(r"^https?://www\.", "", line["url"]).split("/")[0]
            extra.setdefault(dom, [])
            if len(extra[dom]) < CALIBRATION_EXTRA:
                extra[dom].append(line["url"])
    to_fetch = list(needed) + [u for lst in extra.values() for u in lst]
    print("team-game sides: %d; articles needing a fetch: %d; calibration extras: %d; total fetches: %d" % (
        len(team_games), len(needed), sum(len(v) for v in extra.values()), len(to_fetch)))
    if a.plan:
        return 0

    state = {"sent": None}
    pages, failures = {}, []
    for u in to_fetch:
        try:
            pages[u] = fetch(u, a.cache_dir, a.delay, state)
        except RuntimeError as exc:
            failures.append(str(exc))
    print("requests sent: %d; failed: %d" % (state["sent"] or 0, len(failures)))

    info = {}
    for u, page in pages.items():
        obj, how = jsonld_article(page)
        vis = parse_visible(page)
        info[u] = {
            "domain": re.sub(r"^https?://www\.", "", u).split("/")[0],
            "jsonld": how,
            "headline": (obj or {}).get("headline", ""),
            "published_raw": (obj or {}).get("datePublished", ""),
            "published_utc": parse_iso_utc((obj or {}).get("datePublished", "")),
            "modified_utc": parse_iso_utc((obj or {}).get("dateModified", "")),
            "visible": vis,
        }

    # Publisher timezone: the zone that reproduces every visible date line from the machine-readable time.
    zone_votes = defaultdict(lambda: Counter())
    samples = defaultdict(int)
    for u, i in info.items():
        if i["published_utc"] is None or i["visible"] is None:
            continue
        samples[i["domain"]] += 1
        for z in CANDIDATE_ZONES:
            local = i["published_utc"].astimezone(pytz.timezone(z)).replace(tzinfo=None)
            if abs((local - i["visible"]).total_seconds()) < 60:
                zone_votes[i["domain"]][z] += 1
    zone_for = {}
    with open(os.path.join(HERE, "publisher_tz.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["domain", "samples", "zone", "matching_samples", "status"])
        for dom in sorted(set(i["domain"] for i in info.values())):
            n = samples[dom]
            matches = {z: c for z, c in zone_votes[dom].items() if c == n and n > 0}
            if n and len(matches) == 1:
                zone = next(iter(matches))
                zone_for[dom] = zone
                status = "calibrated"
            else:
                zone = ""
                status = "unresolved (samples %d, matching zones %s)" % (n, sorted(matches) or "none")
            w.writerow([dom, n, zone, matches.get(zone, 0) if zone else 0, status])

    # Classify every article used by a team-game, and write the article table.
    with open(os.path.join(HERE, "article_timestamps.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["url", "domain", "sitemap_date", "fetched", "jsonld", "headline", "published_raw", "published_utc",
                    "modified_utc", "visible_line", "zone", "zone_status"])
        all_urls = sorted(set(needed) | set(u for lst in extra.values() for u in lst))
        for u in all_urls:
            i = info.get(u)
            if i is None:
                w.writerow([u, re.sub(r"^https?://www\.", "", u).split("/")[0], needed.get(u, ""), "failed", "", "", "", "", "", "", "", ""])
                continue
            zone = zone_for.get(i["domain"], "")
            w.writerow([u, i["domain"], needed.get(u, ""), "yes", i["jsonld"], i["headline"], i["published_raw"],
                        i["published_utc"].isoformat() if i["published_utc"] else "",
                        i["modified_utc"].isoformat() if i["modified_utc"] else "",
                        i["visible"].isoformat() if i["visible"] else "", zone,
                        "calibrated" if zone else "unresolved"])

    def classify(url, date_str, g):
        i = info.get(url)
        if i is not None and i["published_utc"] is not None:
            # Explicit UTC from the page's own metadata: comparing with the cutoff needs no timezone at all.
            delta = (g["cutoff"] - i["published_utc"]).total_seconds()
            return ("pre_cutoff" if delta > 0 else "post_cutoff"), i["modified_utc"]
        if i is not None and i["visible"] is not None:
            # Minute precision only: the publisher's zone is required, and a time within two minutes is a boundary.
            zone = zone_for.get(i["domain"])
            if not zone:
                return "tz_unresolved", None
            pub = pytz.timezone(zone).localize(i["visible"]).astimezone(pytz.utc)
            delta = (g["cutoff"] - pub).total_seconds()
            if abs(delta) < BOUNDARY_SECONDS:
                return "boundary", None
            return ("pre_cutoff" if delta > 0 else "post_cutoff"), None
        if i is not None:
            return "no_timestamp", None
        days_before = (g["gameday"] - dt.date.fromisoformat(date_str)).days
        if days_before >= 2:
            return "pre_cutoff_by_date", None
        return "fetch_failed", None

    def content_state(modified, cutoff):
        # No dateModified (or no fetch) means the version that existed at publication is unknown.
        if modified is None:
            return "unverified"
        return "modified_after_cutoff" if modified > cutoff else "modified_before_cutoff"

    def iso(value):
        return value.isoformat() if value else ""

    # Strictness is decided per article: published before the cutoff by its own metadata AND its current
    # dateModified not after the cutoff. A team-game is strict only when it has a strict report article and no
    # report article that cannot establish a pregame version.
    out_rows, evidence = [], []
    summary = Counter()
    for r, g, refs in team_games:
        counts = {"report": Counter(), "inactives": Counter()}
        strict_urls, unresolved = [], Counter()
        for kind, u, d in refs:
            if re.search(r"/news/updates-", u):
                counts[kind]["rolling_page_entries_unparsed"] += 1
                evidence.append([r["game_id"], r["team"], kind, u, d, "rolling_page_entries_unparsed", "", "",
                                 g["cutoff"].isoformat(), "unverified", False])
                if kind == "report":
                    unresolved["rolling_page_entries_unparsed"] += 1
                continue
            status, modified = classify(u, d, g)
            counts[kind][status] += 1
            i = info.get(u) or {}
            state = content_state(modified, g["cutoff"]) if status in ("pre_cutoff", "pre_cutoff_by_date") else "not_applicable"
            strict = status == "pre_cutoff" and state == "modified_before_cutoff"
            evidence.append([r["game_id"], r["team"], kind, u, d, status, iso(i.get("published_utc")), iso(modified),
                             g["cutoff"].isoformat(), state, strict])
            if kind == "report":
                if strict:
                    strict_urls.append(u)
                elif status in ("pre_cutoff", "pre_cutoff_by_date", "boundary", "tz_unresolved", "no_timestamp", "fetch_failed"):
                    unresolved[status if status != "pre_cutoff" else "pre_cutoff_" + state] += 1

        def headline(kind):
            c = counts[kind]
            if c["pre_cutoff"] or c["pre_cutoff_by_date"]:
                return "pre_cutoff_verified" if c["pre_cutoff"] else "pre_cutoff_by_date_only"
            for key in ("boundary", "tz_unresolved", "no_timestamp", "post_cutoff", "rolling_page_entries_unparsed"):
                if c[key]:
                    return key
            return "none_found"

        inj, ina = headline("report"), headline("inactives")
        strict = bool(strict_urls) and not unresolved
        row = [g["week"], r["game_id"], r["team"], r["opponent"], g["cutoff"].isoformat(), inj, ina,
               len(strict_urls), ";".join(sorted(unresolved)) or "none", strict]
        out_rows.append(row)
        summary[("injury", inj)] += 1
        summary[("inactives", ina)] += 1
        summary[("strict", strict)] += 1

    with open(os.path.join(HERE, "team_game_matrix.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["week", "game_id", "team", "opponent", "cutoff_utc", "injury_designations", "inactives",
                    "report_strict_articles", "report_unresolved", "strict_timestamp_ok"])
        w.writerows(out_rows)

    with open(os.path.join(HERE, "article_evidence.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["game_id", "team", "kind", "url", "sitemap_date", "classification", "published_utc",
                    "modified_utc", "cutoff_utc", "content_state", "strict"])
        w.writerows(evidence)

    print("\nmatrix: %d team-game sides" % len(out_rows))
    for key in sorted(summary, key=lambda k: (k[0], str(k[1]))):
        print("  %-10s %-32s %d" % (key[0], key[1], summary[key]))
    if failures:
        print("FETCH FAILURES (%d):" % len(failures))
        for item in failures[:20]:
            print("  " + item)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
