#!/usr/bin/env python3
"""Operator-run, published-first EWC 2026 Club Championship standings fetcher.

Single writer for ``backend/data/esports_ewc_standings.json``. Source: Liquipedia
MediaWiki API (terms explicitly allow access through the MediaWiki API; NO HTML page
scraping, NO request-path fetching). One ``action=parse`` call per run with gzip
Accept-Encoding and a descriptive User-Agent.

Pipeline (published-first):
  1. fetch  -> one MediaWiki parse call (prop=text|wikitext|revid, format=json)
  2. stage  -> current-stage=N from the wikitext; stageNcutoff=C selects the table
  3. parse  -> EVERY row of the current-stage table: rank, stable team-page slug
               (clubId), club name, bold total points, optional movement/logo.
               One unparseable row fails the whole run (exact complete population).
  4. validate -> revision present, stage/cutoff sane, unique clubIds, count ==
               sourceReportedClubs, numeric nonnegative points, publisher ordering
               (ranks non-decreasing, points non-increasing, equal points -> equal
               rank, fewer points -> strictly greater rank), plus the ewc snapshot
               validator (event, publishedAt, regression gate).
  5. publish -> atomic last-good replace (tmp + os.replace); a failed candidate is
               never readable and the previous run survives.

Usage (cwd=backend/, venv interpreter):
    venv/bin/python fetch_ewc_standings.py              # fetch, validate, publish
    venv/bin/python fetch_ewc_standings.py --dry-run    # fetch + validate, no write
    venv/bin/python fetch_ewc_standings.py --correction # allow a publisher point
                                                        # correction vs the last run
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request

from routers.esports import ewc
from routers.esports.common import _canon_team

API_URL = "https://liquipedia.net/esports/api.php"
PAGE = "Esports_World_Cup/2026/Club_Championship_Standings"
SOURCE_LABEL = "Liquipedia — EWC 2026 Club Championship"
SOURCE_URL = "https://liquipedia.net/esports/" + PAGE
USER_AGENT = "LegendaryPicks/1.0 (esports standings ingest; contact via github.com/legendarypicks)"
STANDINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "data", "esports_ewc_standings.json")
LOGO_INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", "esports_team_logos.json")


class StandingsSourceError(ValueError):
    """A source-parsing or population validation failure — the run must not publish."""


def normalize_logo_url(src):
    """Normalize a publisher (MediaWiki) image URL to an absolute HTTPS URL, else None.

    Handles protocol-relative (``//liquipedia.net/...``), relative (``/commons/...``),
    and absolute (``https://`` / ``http://``) forms. Anything else is not a usable
    logo URL and returns None.
    """
    if not src or not isinstance(src, str):
        return None
    s = src.strip()
    if not s:
        return None
    if s.startswith("//"):
        return "https:" + s
    if s.startswith("/"):
        return "https://liquipedia.net" + s
    if s.startswith("http://"):
        return "https://" + s[len("http://"):]
    if s.startswith("https://"):
        return s
    return None


def load_local_logo_index(path=None):
    """The maintained local logo index ({canonical team key: logo URL}, PandaScore-derived).

    Empty-string entries are cached negatives (the publisher has no crest) and are
    treated as absent. A missing/unreadable file is an empty index, never an error.
    """
    path = path or LOGO_INDEX_PATH
    try:
        with open(path) as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(v, str) and v.strip()}


def resolve_logo(club_name, publisher_logo, logos_map):
    """The snapshot logo for one club.

    The local index wins ONLY on an exact canonical-key match with a verified non-empty
    HTTPS URL (same identity function the index is built with). Ambiguous clubs are never
    matched by loose display-name guesses; otherwise the normalized publisher logo is kept.
    """
    if logos_map:
        key = _canon_team(club_name or "")
        if key and key in logos_map:
            local = logos_map[key]
            if local.startswith(("http://", "https://")):
                return local
    return publisher_logo


def fetch_source():
    """One MediaWiki parse call: rendered text + wikitext + revid (gzip, descriptive UA)."""
    query = urllib.parse.urlencode({
        "action": "parse",
        "page": PAGE,
        "prop": "text|wikitext|revid",
        "format": "json",
    })
    req = urllib.request.Request(API_URL + "?" + query, headers={
        "Accept-Encoding": "gzip",
        "User-Agent": USER_AGENT,
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    doc = json.loads(raw.decode("utf-8"))
    parse = doc.get("parse")
    if not parse:
        raise StandingsSourceError("source did not return a parse payload")
    revid = parse.get("revid")
    text = (parse.get("text") or {}).get("*")
    wikitext = (parse.get("wikitext") or {}).get("*")
    if not revid or not text or wikitext is None:
        raise StandingsSourceError("source payload missing revid/text/wikitext")
    return revid, text, wikitext


def parse_stage(wikitext):
    """current-stage=N -> stageNcutoff=C. Any miss is a malformed-stage error."""
    m = re.search(r"current-stage\s*=\s*(\d+)", wikitext or "")
    if not m:
        raise StandingsSourceError("malformed stage: current-stage not found in wikitext")
    stage = int(m.group(1))
    if stage < 1:
        raise StandingsSourceError("malformed stage: current-stage %d" % stage)
    m2 = re.search(r"stage%d\s*cutoff\s*=\s*(\d+)" % stage, wikitext or "")
    if not m2:
        raise StandingsSourceError("malformed stage: stage%dcutoff not found" % stage)
    cutoff = int(m2.group(1))
    if cutoff < 1:
        raise StandingsSourceError("malformed stage: stage%dcutoff %d" % (stage, cutoff))
    return stage, cutoff


def parse_rows(html, cutoff):
    """Parse EVERY row of the current-stage table (data-toggle-area-content=<cutoff>).

    Each row yields rank, clubId (stable Liquipedia team-page slug), clubName, numeric
    points, plus optional movement/logo. A single unparseable row fails the run —
    the population must be exact and complete, never silently partial.
    """
    rows_html = re.findall(r'<tr data-toggle-area-content="%d".*?</tr>' % cutoff, html or "", re.S)
    if not rows_html:
        raise StandingsSourceError(
            "malformed stage: no rows for data-toggle-area-content=%d" % cutoff)
    rows = []
    for row_html in rows_html:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
        m_rank = re.match(r"\s*(\d+)\s*\.", tds[0]) if tds else None
        rank = int(m_rank.group(1)) if m_rank else None
        links = list(re.finditer(r'<a href="/esports/([^"]+)" title="([^"]+)"', row_html))
        m_club = links[-1] if links else None
        club_id = m_club.group(1) if m_club else None
        club_name = m_club.group(2) if m_club else None
        m_mv = re.search(
            r'standings-position-indicator movement-(up|down|steady)"[^>]*>(?:<i[^>]*></i>)?'
            r"<span>(\d+)</span>", row_html)
        movement = None
        if m_mv:
            val = int(m_mv.group(2))
            movement = val if m_mv.group(1) == "up" else (-val if m_mv.group(1) == "down" else 0)
        tail = row_html[m_club.end():] if m_club else row_html
        m_points = re.search(r'<td style="font-weight:bold">(\d+)</td>', tail)
        points = int(m_points.group(1)) if m_points else None
        if None in (rank, club_id, club_name, points):
            raise StandingsSourceError(
                "unparseable standings row: rank=%r club=%r points=%r" % (rank, club_id, points))
        # The first image in the row is the club's team icon; normalize to HTTPS (may be
        # protocol-relative, relative, or absolute). Absent image -> logo stays None.
        m_logo = re.search(r'<img[^>]*src="([^"]+)"', row_html)
        logo = normalize_logo_url(m_logo.group(1)) if m_logo else None
        rows.append({
            "rank": rank,
            "clubId": club_id,
            "clubName": club_name,
            "logo": logo,
            "points": points,
            "eligibleTopEightCount": None,
            "titleWins": None,
            "eligibleToWin": None,
            "movement": movement,
        })
    return rows


def build_snapshot(rows, revid, stage, cutoff, fetched_at, correction=False, logos_map=None):
    """Assemble the snapshot with source attribution and a reproducible checksum.

    ``logos_map`` is the maintained local logo index (canonical team key -> URL); when a
    club has a verified non-empty local mapping it wins over the publisher logo, otherwise
    the normalized publisher logo (or None) is kept. Exact canonical-key matches only —
    never loose display-name guesses.
    """
    logos_map = logos_map or {}
    for row in rows:
        row["logo"] = resolve_logo(row.get("clubName"), row.get("logo"), logos_map)
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    published_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    snapshot = {
        "event": ewc.EVENT_ID,
        "publishedAt": published_at,
        "source": {
            "label": SOURCE_LABEL,
            "url": SOURCE_URL,
            "revision": revid,
            "stage": stage,
            "stageCutoff": cutoff,
            "fetchedAt": fetched_at,
            "publishedAt": published_at,
            # For this source the current-stage table IS the population: the reported and
            # fetched counts are both the parsed row count (90 at rev 15997).
            "sourceReportedClubs": len(rows),
            "fetchedClubs": len(rows),
            "checksum": hashlib.sha256(payload).hexdigest(),
        },
        "standings": rows,
    }
    if correction:
        snapshot["publisherCorrection"] = True
    return snapshot


def fetch_validated_snapshot(correction=False):
    """Fetch and fully validate one candidate without publishing it."""
    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    revid, html, wikitext = fetch_source()
    stage, cutoff = parse_stage(wikitext)
    rows = parse_rows(html, cutoff)
    snapshot = build_snapshot(rows, revid, stage, cutoff, fetched_at,
                              correction=correction,
                              logos_map=load_local_logo_index())
    ewc._validate_snapshot(snapshot)
    return snapshot


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + validate and print the source summary; do not publish")
    ap.add_argument("--correction", action="store_true",
                    help="allow a publisher point correction vs the last published run")
    args = ap.parse_args(argv)

    snapshot = fetch_validated_snapshot(correction=args.correction)
    source = snapshot["source"]
    rows = snapshot["standings"]

    print("stage %d (cutoff %d) at revision %d — %d clubs parsed"
          % (source["stage"], source["stageCutoff"], source["revision"], len(rows)))
    for r in rows[:10]:
        print("  %2d. %-24s %s" % (r["rank"], r["clubName"], r["points"]))

    if args.dry_run:
        print("[dry-run] not publishing — run without --dry-run to publish")
        return 0

    ewc.publish_standings(snapshot, path=STANDINGS_PATH)
    print("published -> %s (sourceReportedClubs=%d, checksum=%s)"
          % (STANDINGS_PATH, snapshot["source"]["sourceReportedClubs"],
             snapshot["source"]["checksum"][:12]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
