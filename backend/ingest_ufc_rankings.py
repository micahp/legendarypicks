#!/usr/bin/env python3
"""ingest_ufc_rankings.py — scrape ufc.com/rankings, cache to ufc_rankings table.

Stdlib only: urllib + re. Browser User-Agent. Idempotent: clears + rewrites each run.
"""

import json
import os
import re
import sqlite3
import sys
import urllib.request
from contextlib import closing
from datetime import datetime, timezone

DB_PATH = os.environ.get("LP_DB_PATH", "data/picks.dev.db")
URL = "https://www.ufc.com/rankings"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# ── fetch ────────────────────────────────────────────────────────────────────

def fetch_html():
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")

# ── parse ────────────────────────────────────────────────────────────────────

def parse_rankings(html: str):
    """Return list of {division, champion, fighters: [{rank, name}]}."""
    # Each ranking block: view-grouping-header followed by view-grouping-content
    # inside view-grouping divs.
    blocks = re.findall(
        r'<div class="view-grouping-header">(.*?)</div>\s*'
        r'<div class="view-grouping-content">(.*?)</table>',
        html, re.DOTALL,
    )

    results = []
    for header_raw, content in blocks:
        division = re.sub(r"<[^>]+>", "", header_raw).strip()
        division = division.replace("&#039;", "'")

        # Champion from caption h5 — <a> may have extra attrs like hreflang
        champ_match = re.search(
            r'<h5><a\b[^>]*href="/athlete/[^"]*"[^>]*>(.*?)</a></h5>', content
        )
        champion = champ_match.group(1).strip() if champ_match else ""

        # Ranked fighters from table rows — class varies: Meta uses
        # "weight-class-rank", Media uses "meta-weight-class-rank".
        fighters = re.findall(
            r'<td class="views-field views-field-(?:meta-)?weight-class-rank">\s*(\d+)\s*</td>\s*'
            r'<td class="views-field views-field-(?:meta-)?title"><a\b[^>]*href="/athlete/[^"]*"[^>]*>(.*?)</a>',
            content, re.DOTALL,
        )
        ranked = [{"rank": int(r), "name": n.strip()} for r, n in fighters]

        if champion or ranked:
            results.append(
                {"division": division, "champion": champion, "fighters": ranked}
            )

    return results

# ── db ────────────────────────────────────────────────────────────────────────

def ensure_table(con):
    con.execute(
        """CREATE TABLE IF NOT EXISTS ufc_rankings(
            division TEXT, rank INTEGER, fighter TEXT,
            is_champion INTEGER, captured_at TEXT)"""
    )


def store(con, rankings, captured_at):
    con.execute("DELETE FROM ufc_rankings")
    for div in rankings:
        if div["champion"]:
            con.execute(
                "INSERT INTO ufc_rankings VALUES (?,?,?,?,?)",
                (div["division"], 0, div["champion"], 1, captured_at),
            )
        for f in div["fighters"]:
            con.execute(
                "INSERT INTO ufc_rankings VALUES (?,?,?,?,?)",
                (div["division"], f["rank"], f["name"], 0, captured_at),
            )
    con.commit()

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Fetching {URL} ...", file=sys.stderr)
    html = fetch_html()
    all_rankings = parse_rankings(html)

    # UFC.com renders two ranking tabs in the same HTML: "Meta Rankings"
    # (algorithmic, blocks 0-12) then "Media Rankings" (official panel,
    # blocks 13-23). Media P4P sections are JS-loaded and not in the static
    # HTML, so we use Meta P4P (blocks 0 and 9) + Media divisions (13-23).
    # Each set has the same fighters; Media is the official panel.
    all_r = parse_rankings(html)
    # Meta P4P: blocks 0 (Men's) + 9 (Women's)
    p4p = [all_r[0], all_r[9]] if len(all_r) >= 10 else []
    # Media divisions: blocks 13-23 (8 men's + 3 women's)
    divs = all_r[13:] if len(all_r) >= 14 else []
    rankings = p4p + divs
    print(f"Parsed {len(all_r)} groups, using {len(rankings)} (P4P Meta + divisions Media)", file=sys.stderr)
    for r in rankings:
        print(f"  {r['division']}: champ={r['champion']}, {len(r['fighters'])} ranked", file=sys.stderr)

    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        ensure_table(con)
        store(con, rankings, captured_at)
        count = con.execute("SELECT COUNT(*) FROM ufc_rankings").fetchone()[0]
        print(f"Stored {count} rows in ufc_rankings", file=sys.stderr)

    # Also dump a JSON seed file for the fallback path
    seed_path = os.path.join(os.path.dirname(__file__), "data", "ufc_rankings_seed.json")
    os.makedirs(os.path.dirname(seed_path), exist_ok=True)
    with open(seed_path, "w") as f:
        json.dump(rankings, f, indent=2)
    print(f"Seed written to {seed_path}", file=sys.stderr)

    return rankings


if __name__ == "__main__":
    main()
