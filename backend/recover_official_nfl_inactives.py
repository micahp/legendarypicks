#!/usr/bin/env python3
"""Recover official 2026 Sunday inactive *decisions* without fabrication.

Official NFL.com Sunday inactive roundups are historical evidence of the
pregame decisions. Their mutable full-page update time can be AFTER kickoff.
Such records are useful for retrospective final-roster reconstruction, but
are NOT labeled a source captured before the model's own pregame cutoff.

Team/player identity joins are strict and produce an unresolved review queue.
Week-specific nflverse rosters are identity crosswalks ONLY; they cannot prove
the NFL's 90-minute game-day inactive decision.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import re
import unicodedata
import urllib.request
from zoneinfo import ZoneInfo

from recover_nfl_injury_weeks import file_sha256, get_schedule_csv, string_utc
from team_codes import normalize_optional

ET = ZoneInfo("America/New_York")
TEAM_LABEL = {
    "CARDINALS": "ARI", "FALCONS": "ATL", "RAVENS": "BAL",
    "BILLS": "BUF", "PANTHERS": "CAR", "BEARS": "CHI",
    "BENGALS": "CIN", "BROWNS": "CLE", "COWBOYS": "DAL",
    "BRONCOS": "DEN", "LIONS": "DET", "PACKERS": "GB",
    "TEXANS": "HOU", "COLTS": "IND", "JAGUARS": "JAX",
    "CHIEFS": "KC", "RAIDERS": "LV", "CHARGERS": "LAC",
    "RAMS": "LAR", "DOLPHINS": "MIA", "VIKINGS": "MIN",
    "PATRIOTS": "NE", "SAINTS": "NO", "GIANTS": "NYG",
    "JETS": "NYJ", "EAGLES": "PHI", "STEELERS": "PIT",
    "49ERS": "SF", "SEAHAWKS": "SEA", "BUCCANEERS": "TB",
    "TITANS": "TEN", "COMMANDERS": "WSH",
}
OUTPUT_FIELDS = (
    "week", "game_id", "team", "player_text", "player_name",
    "gsis_id", "identity_status", "evidence_class",
    "source_url", "source_sha256", "page_published_utc",
    "page_updated_utc", "kickoff_utc", "cutoff_utc",
)


def normalized_name(value):
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold().replace("&", "and")
    value = re.sub(r"[^a-z0-9 ]+", "", value)
    tokens = value.split()
    while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        tokens.pop()
    return "".join(tokens)


def extract_name(li):
    text = " ".join(li.split())
    # Article positions are supplied as one prefix, not a player name.
    m = re.match(r"^[A-Za-z][A-Za-z/-]*\s+(.+)$", text)
    if not m:
        return text, ""
    name = re.sub(r"\s*\(emergency third QB\).*", "", m.group(1),
                  flags=re.IGNORECASE).strip()
    return text, name


def article_updated_at(html):
    """Use printed NFL.com dateline, never synthetic or filesystem timestamps."""
    from bs4 import BeautifulSoup
    source = BeautifulSoup(html, "html.parser")
    text = source.get_text(" ", strip=True)
    stamp_re = r"([A-Za-z]{3}\s+\d{1,2},\s+20\d{2}\s+at\s+\d{1,2}:\d{2}\s+[AP]M)"
    published = re.search(r"Published:\s*" + stamp_re, text)
    updated = re.search(r"Updated:\s*" + stamp_re, text)
    def parse(match):
        if not match:
            return None
        parsed = datetime.strptime(match.group(1), "%b %d, %Y at %I:%M %p")
        return parsed.replace(tzinfo=ET)
    return parse(published), parse(updated)


def parse_official_article(html):
    """Read only article-body team headings and explicit list items."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    found = defaultdict(list)
    for container in soup.select("div.nfl-c-article__container"):
        current = None
        for child in container.find_all("div", recursive=False):
            heading = child.find("h3")
            if heading:
                code = TEAM_LABEL.get(heading.get_text(" ", strip=True).upper().strip())
                current = normalize_optional("nfl", code) if code else None
                continue
            li = child.find_all("li")
            if current and li:
                for item in li:
                    raw, name = extract_name(item.get_text(" ", strip=True))
                    if name:
                        found[current].append({"raw": raw, "name": name})
                current = None
    return dict(found)


def identity_map(injury_csv, depth_csv, weekly_roster_parquet=None):
    """Team+week+strict canonical name -> GSIS, with no player-name guessing."""
    result = defaultdict(set)
    with injury_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["full_name"] and r["gsis_id"]:
                result[(int(r["week"]), r["team"],
                        normalized_name(r["full_name"]))].add(r["gsis_id"])
    with depth_csv.open(newline="") as f:
        for r in csv.DictReader(f):
            if r["player_name"] and r["gsis_id"]:
                result[(int(r["week"]), r["team"],
                        normalized_name(r["player_name"]))].add(r["gsis_id"])
    if weekly_roster_parquet:
        import pyarrow.parquet as pq
        fields = ["team", "week", "game_type", "full_name", "gsis_id"]
        have = set(pq.ParquetFile(weekly_roster_parquet).schema.names)
        if not set(fields).issubset(have):
            raise RuntimeError("week roster identity fields missing")
        for r in pq.read_table(weekly_roster_parquet, columns=fields).to_pylist():
            if (r["game_type"] == "REG" and r["week"] is not None
                    and 2 <= int(r["week"]) <= 9 and r["full_name"] and r["gsis_id"]):
                result[(int(r["week"]),
                        normalize_optional("nfl", str(r["team"])),
                        normalized_name(str(r["full_name"])))].add(str(r["gsis_id"]))
    return result


def download_html(url, destination):
    if not url.startswith("https://amp.nfl.com/news/"):
        raise ValueError("not an approved official NFL inactive article: " + url)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; LegendaryPicksHistoricalResearch/1.0)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        page = r.read()
    if len(page) < 1000:
        raise ValueError("official article download unexpectedly short")
    destination.write_bytes(page)
    return page.decode("utf-8")


def recover(sources, schedule, identity, article_html, source_hashes,
            cutoff_minutes=30):
    from datetime import timedelta
    records, indeces, audit = [], [], Counter()
    for spec in sources:
        week, url = int(spec["week"]), spec["url"]
        html = article_html[week]
        names = parse_official_article(html)
        published, updated = article_updated_at(html)
        audit["articles_downloaded"] += 1
        if not updated:
            audit["articles_without_page_update_time"] += 1
        for team, team_rows in sorted(names.items()):
            key = (week, team)
            match = schedule.get(key)
            if not match:
                audit["unexpected_article_team_week"] += 1
                continue
            kickoff = match["kickoff"]
            if kickoff.astimezone(ET).weekday() != 6:
                audit["article_for_non_sunday_game"] += 1
                continue
            cutoff = kickoff - timedelta(minutes=cutoff_minutes)
            # A page updated after kickoff can confirm actual inactives
            # retrospectively, but cannot establish our own pregame observation.
            before = updated is not None and updated <= cutoff
            evidence = ("official_article_updated_before_cutoff"
                        if before else "retrospective_official_inactives")
            ids, unresolved = [], []
            for player in team_rows:
                candidates = identity.get((week, team,
                                           normalized_name(player["name"])), set())
                if len(candidates) == 1:
                    pid = next(iter(candidates))
                    ids.append(pid)
                    ident = "exact_unique_team_week_name"
                else:
                    pid = ""
                    ident = "unresolved" if not candidates else "ambiguous"
                    unresolved.append(player["name"])
                records.append({
                    "week": week, "game_id": match["game_id"], "team": team,
                    "player_text": player["raw"], "player_name": player["name"],
                    "gsis_id": pid, "identity_status": ident,
                    "evidence_class": evidence, "source_url": url,
                    "source_sha256": source_hashes[week],
                    "page_published_utc": string_utc(published.astimezone(
                        __import__("datetime").timezone.utc)) if published else "",
                    "page_updated_utc": string_utc(updated.astimezone(
                        __import__("datetime").timezone.utc)) if updated else "",
                    "kickoff_utc": string_utc(kickoff),
                    "cutoff_utc": string_utc(cutoff),
                })
            audit["player_rows"] += len(team_rows)
            audit["unresolved_player_rows"] += len(unresolved)
            audit["source_team_games"] += 1
            if before:
                audit["article_updated_before_cutoff_team_games"] += 1
            else:
                audit["retrospective_article_team_games"] += 1
            if not unresolved:
                indeces.append({
                    "game_id": match["game_id"], "team": team,
                    "gsis_ids": sorted(set(ids)), "source_url": url,
                    "source_sha256": source_hashes[week],
                    "source_last_updated_at_utc":
                        string_utc(updated.astimezone(__import__("datetime").timezone.utc))
                        if updated else None,
                    "recovery_class": evidence,
                })
                audit["fully_identity_resolved_team_games"] += 1
            else:
                audit["team_games_needing_identity_review"] += 1
    return records, indeces, dict(audit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--schedule-csv", type=Path, required=True)
    ap.add_argument("--injury-csv", type=Path, required=True)
    ap.add_argument("--depth-csv", type=Path, required=True)
    ap.add_argument("--weekly-roster-parquet", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    sources = json.loads(args.sources.read_text())
    if set(int(s["week"]) for s in sources) != set(range(2,10)):
        raise ValueError("official Sunday source registry must cover Weeks 2-9")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    pages, hashes = {}, {}
    for s in sources:
        week, url = int(s["week"]), s["url"]
        path = args.out_dir / f"official-sunday-inactives-week-{week}.html"
        pages[week] = download_html(url, path)
        hashes[week] = file_sha256(path)
    rows, index, summary = recover(
        sources, get_schedule_csv(args.schedule_csv),
        identity_map(args.injury_csv, args.depth_csv, args.weekly_roster_parquet),
        pages, hashes)
    if len(rows) < 300 or summary["source_team_games"] < 60:
        raise RuntimeError("official article parser coverage below expected pilot floor")
    out = args.out_dir / "official-inactives-audit.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (args.out_dir / "official-inactives-matched-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n")
    manifest = {
        "season": 2026, "weeks": [2,9],
        "claim": "official reported pregame inactive decision, retrospectively retrieved, not always independently captured before kickoff",
        "source_articles": sources, "source_sha256_by_week": hashes,
        "roster_weekly_identity_only_not_availability": bool(args.weekly_roster_parquet),
        "summary": summary,
    }
    (args.out_dir / "official-inactives-coverage.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
