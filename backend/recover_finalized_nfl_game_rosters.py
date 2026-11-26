#!/usr/bin/env python3
"""Build 2026 Weeks 2-9 game-day rosters from official NFL gamebooks.

The NFL gamebook's Lineups, Substitutions, Did Not Play, and Not Active sections
define the realized game-day roster. nflverse weekly rosters are used only as
the GSIS identity crosswalk; their status field is retained for reconciliation
and never overrides the official gamebook.

Gamebooks are published after games. This output is retrospective roster truth,
not proof that each status was observed before a model's forecast cutoff.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from team_codes import normalize_optional

SEASON = 2026
FIRST_WEEK = 2
LAST_WEEK = 9
GAMEBOOK_FIELDS = (
    "game_id", "week", "team", "gsis_id", "player_name", "jersey_number",
    "gamebook_position", "actual_gameday_status", "gamebook_roster_role",
    "weekly_source_status", "identity_match_method", "gamebook_url",
    "gamebook_sha256",
)
ROLE_RANGES = ("START", "SUB", "DNP", "INA")
PLAYER_RE = re.compile(
    r"(?<![A-Za-z0-9])(3QB|[A-Z]{1,5}(?:/[A-Z]{1,5})?)\s+"
    r"(\d{1,2})\s+([A-Z][A-Za-z]*\.[A-Za-z][A-Za-z.'’-]*)"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(value: str | None) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def read_schedule(path: Path) -> dict[str, dict]:
    games = {}
    teams_seen = set()
    with path.open(newline="") as source:
        for row in csv.DictReader(source):
            if (int(row["season"]) != SEASON or row["game_type"] != "REG"
                    or not FIRST_WEEK <= int(row["week"]) <= LAST_WEEK):
                continue
            game_id = row["game_id"]
            if game_id in games:
                raise ValueError("duplicate scheduled game: " + game_id)
            away = normalize_optional("nfl", row["away_team"])
            home = normalize_optional("nfl", row["home_team"])
            if not away or not home or away == home:
                raise ValueError("invalid scheduled teams: " + game_id)
            games[game_id] = {
                "week": int(row["week"]), "away": away, "home": home,
                "gsis": str(row["gsis"]),
            }
            teams_seen.update(((int(row["week"]), away), (int(row["week"]), home)))
    if len(games) != 120 or len(teams_seen) != 240:
        raise ValueError("schedule must contain 120 games and 240 team-games; got "
                         + str(len(games)) + " and " + str(len(teams_seen)))
    return games


def load_weekly_identity(path: Path) -> dict[tuple[int, str], list[dict]]:
    import pyarrow.parquet as pq

    required = {
        "season", "team", "week", "game_type", "status", "gsis_id",
        "full_name", "first_name", "last_name", "jersey_number", "position",
    }
    available = set(pq.ParquetFile(path).schema.names)
    if not required.issubset(available):
        raise ValueError("weekly roster is missing fields: "
                         + ", ".join(sorted(required - available)))
    columns = sorted(required)
    result = defaultdict(list)
    for row in pq.read_table(path, columns=columns).to_pylist():
        if (row["season"] != SEASON or row["game_type"] != "REG"
                or row["week"] is None
                or not FIRST_WEEK <= int(row["week"]) <= LAST_WEEK
                or not row["gsis_id"] or not row["full_name"]):
            continue
        row["team"] = normalize_optional("nfl", row["team"])
        result[(int(row["week"]), row["team"])].append(row)
    return result


def page_words(pdf: Path) -> tuple[float, list[tuple[float, float, str]]]:
    process = subprocess.run(
        ["pdftotext", "-bbox", "-f", "1", "-l", "1", str(pdf), "-"],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    root = ET.fromstring(process.stdout)
    page = next((item for item in root.iter() if item.tag.endswith("page")), None)
    if page is None:
        raise ValueError("pdftotext returned no page for " + pdf.name)
    width = float(page.attrib["width"])
    words = [
        (float(item.attrib["yMin"]), float(item.attrib["xMin"]), item.text or "")
        for item in page.iter()
        if item.tag.endswith("word")
    ]
    return width, sorted(words)


def grouped_lines(words: list[tuple[float, float, str]]) -> list[tuple[float, list[tuple[float, str]]]]:
    lines = []
    for y, x, text in words:
        if not lines or abs(lines[-1][0] - y) > 1.5:
            lines.append([y, [(x, text)]])
        else:
            lines[-1][1].append((x, text))
    return [(line[0], line[1]) for line in lines]


def roster_sections(words: list[tuple[float, float, str]]) -> dict[str, tuple[float, float]]:
    headings = {}
    for y, row in grouped_lines(words):
        text = " ".join(word for _, word in sorted(row))
        if text == "Lineups":
            headings["START"] = y
        elif text.count("Substitutions") == 2:
            headings["SUB"] = y
        elif text.count("Did Not Play") == 2:
            headings["DNP"] = y
        elif text.count("Not Active") == 2:
            headings["INA"] = y
        elif text.startswith("Field Goals"):
            headings["END"] = y
    if set(headings) != {"START", "SUB", "DNP", "INA", "END"}:
        raise ValueError("gamebook roster headings missing: " + str(headings))
    if not headings["START"] < headings["SUB"] < headings["DNP"] < headings["INA"] < headings["END"]:
        raise ValueError("gamebook roster headings out of order: " + str(headings))
    return {
        "START": (headings["START"], headings["SUB"]),
        "SUB": (headings["SUB"], headings["DNP"]),
        "DNP": (headings["DNP"], headings["INA"]),
        "INA": (headings["INA"], headings["END"]),
    }


def source_surname(row: dict) -> str:
    last = norm(row.get("last_name"))
    if last:
        return last
    parts = (row.get("full_name") or "").split()
    return norm(parts[-1]) if parts else ""


def resolve_player(team_rows: list[dict], jersey: int, short_name: str) -> tuple[dict, str]:
    surname = norm(short_name.split(".", 1)[1])
    if not surname:
        raise ValueError("gamebook player has no surname: " + short_name)
    by_surname = [
        row for row in team_rows
        if source_surname(row).startswith(surname) or surname.startswith(source_surname(row))
    ]
    exact_number = [row for row in by_surname if row.get("jersey_number") == jersey]
    if len(exact_number) == 1:
        return exact_number[0], "team_week_jersey_surname"
    if len(by_surname) == 1:
        return by_surname[0], "team_week_unique_surname"
    raise ValueError("unresolved/ambiguous gamebook identity: " + short_name
                     + " #" + str(jersey) + " candidates="
                     + repr([(r.get("gsis_id"), r.get("full_name"), r.get("jersey_number"))
                             for r in (exact_number or by_surname)]))


def extract_gamebook(pdf: Path, game_id: str, schedule_row: dict,
                     source_hash: str, team_rows: dict) -> tuple[list[dict], dict]:
    width, words = page_words(pdf)
    split = width / 2.0
    lines = grouped_lines(words)
    ranges = roster_sections(words)
    parsed = defaultdict(list)
    for role, (low, high) in ranges.items():
        for index, team in enumerate((schedule_row["away"], schedule_row["home"])):
            side_words = [
                (y, x, text)
                for y, row in lines if low < y < high
                for x, text in row
                if (x < split if index == 0 else x >= split)
            ]
            section_text = " ".join(text for _, _, text in sorted(side_words))
            for position, jersey_text, player_text in PLAYER_RE.findall(section_text):
                jersey = int(jersey_text)
                player, match_method = resolve_player(
                    team_rows[(schedule_row["week"], team)], jersey, player_text
                )
                parsed[(team, role)].append({
                    "gsis_id": str(player["gsis_id"]),
                    "player_name": str(player["full_name"]),
                    "jersey_number": jersey,
                    "gamebook_position": position,
                    "role": role,
                    "weekly_status": player.get("status") or "",
                    "identity_match_method": match_method,
                })

    output, coverage = [], {"teams": {}}
    for team in (schedule_row["away"], schedule_row["home"]):
        team_rows_out = []
        counts = Counter()
        seen = set()
        for role in ROLE_RANGES:
            entries = parsed[(team, role)]
            for player in entries:
                if player["gsis_id"] in seen:
                    raise ValueError("duplicate player in gamebook roster: "
                                     + game_id + " " + team + " " + player["gsis_id"])
                seen.add(player["gsis_id"])
                counts[role] += 1
                active = role != "INA"
                row = {
                    "game_id": game_id, "week": schedule_row["week"], "team": team,
                    "gsis_id": player["gsis_id"], "player_name": player["player_name"],
                    "jersey_number": player["jersey_number"],
                    "gamebook_position": player["gamebook_position"],
                    "actual_gameday_status": "ACTIVE" if active else "INACTIVE",
                    "gamebook_roster_role": {
                        "START": "starter", "SUB": "substitute",
                        "DNP": "did_not_play", "INA": "not_active",
                    }[role],
                    "weekly_source_status": player["weekly_status"],
                    "identity_match_method": player["identity_match_method"],
                    "gamebook_url": schedule_row["url"],
                    "gamebook_sha256": source_hash,
                }
                team_rows_out.append(row)
        active_count = counts["START"] + counts["SUB"] + counts["DNP"]
        inactive_count = counts["INA"]
        if counts["START"] != 22:
            raise ValueError("gamebook starters != 22: " + game_id + " " + team
                             + " " + str(counts["START"]))
        if not 47 <= active_count <= 49:
            raise ValueError("unexpected active roster size: " + game_id + " " + team
                             + " " + str(active_count))
        third_qbs = [player for role in ROLE_RANGES if role != "INA"
                     for player in parsed[(team, role)]
                     if player["gamebook_position"] == "3QB"]
        if active_count == 49 and len(third_qbs) != 1:
            raise ValueError("49-player active roster must identify one emergency 3QB: "
                             + game_id + " " + team)
        if not 4 <= inactive_count <= 8:
            raise ValueError("unexpected inactive list size: " + game_id + " " + team
                             + " " + str(inactive_count))
        output.extend(team_rows_out)
        coverage["teams"][team] = {
            "active": active_count, "inactive": inactive_count,
            "starters": counts["START"], "substitutions": counts["SUB"],
            "did_not_play": counts["DNP"],
        }
    return output, coverage


def fetch_gamebooks(games: dict[str, dict], directory: Path) -> list[dict]:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for game_id, schedule_row in sorted(games.items()):
        url = "https://www.nflgsis.com/{}/REG/{:02d}/{}/Gamebook.pdf".format(
            SEASON, schedule_row["week"], schedule_row["gsis"]
        )
        path = directory / (game_id + ".pdf")
        if not path.exists():
            request = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; LegendaryPicksRosterResearch/1.0)"
            })
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read()
                last_modified = response.headers.get("Last-Modified", "")
            if not body.startswith(b"%PDF") or len(body) < 10_000 or len(body) > 5_000_000:
                raise ValueError("invalid NFL gamebook response: " + url)
            path.write_bytes(body)
        else:
            last_modified = ""
        manifest.append({
            "game_id": game_id, "week": schedule_row["week"],
            "away_team": schedule_row["away"], "home_team": schedule_row["home"],
            "gsis": schedule_row["gsis"], "url": url,
            "bytes": path.stat().st_size, "sha256": sha256(path),
            "last_modified": last_modified,
        })
    return manifest


def write_csv(path: Path, rows: list[dict], fields: tuple[str, ...] | list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def build(args) -> None:
    schedule = read_schedule(args.schedule_csv)
    manifest = list(csv.DictReader(args.gamebook_manifest.open(newline="")))
    if len(manifest) != 120 or {row["game_id"] for row in manifest} != set(schedule):
        raise ValueError("gamebook manifest must exactly cover all 120 scheduled games")
    identities = load_weekly_identity(args.weekly_roster)
    output, game_coverage = [], {}
    source_conflicts = []
    for source in manifest:
        game_id = source["game_id"]
        pdf = args.gamebooks_dir / (game_id + ".pdf")
        if not pdf.is_file() or sha256(pdf) != source["sha256"]:
            raise ValueError("gamebook missing or SHA-256 mismatch: " + game_id)
        schedule_row = dict(schedule[game_id])
        expected_url = "https://www.nflgsis.com/{}/REG/{:02d}/{}/Gamebook.pdf".format(
            SEASON, schedule_row["week"], schedule_row["gsis"]
        )
        if source["url"] != expected_url:
            raise ValueError("gamebook URL does not match GSIS schedule row: " + game_id)
        schedule_row["url"] = source["url"]
        rows, coverage = extract_gamebook(
            pdf, game_id, schedule_row, source["sha256"], identities
        )
        output.extend(rows)
        game_coverage[game_id] = coverage
        for row in rows:
            if ((row["actual_gameday_status"] == "INACTIVE")
                    != (row["weekly_source_status"] == "INA")):
                source_conflicts.append({
                    "game_id": row["game_id"], "week": row["week"],
                    "team": row["team"], "gsis_id": row["gsis_id"],
                    "player_name": row["player_name"],
                    "gamebook_status": row["actual_gameday_status"],
                    "nflverse_weekly_status": row["weekly_source_status"],
                    "gamebook_url": row["gamebook_url"],
                    "gamebook_sha256": row["gamebook_sha256"],
                })
    if len(output) != len({(r["game_id"], r["team"], r["gsis_id"]) for r in output}):
        raise ValueError("duplicate game/team/GSIS roster keys")
    if len(game_coverage) != 120:
        raise ValueError("not all 120 games were parsed")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output.sort(key=lambda row: (row["week"], row["game_id"], row["team"],
                                 row["actual_gameday_status"], row["jersey_number"],
                                 row["gsis_id"]))
    write_csv(args.out_dir / "finalized-game-day-rosters.csv", output, GAMEBOOK_FIELDS)
    write_csv(args.out_dir / "nflverse-vs-gamebook-status-conflicts.csv",
              source_conflicts, (
                  "game_id", "week", "team", "gsis_id", "player_name",
                  "gamebook_status", "nflverse_weekly_status", "gamebook_url",
                  "gamebook_sha256",
              ))
    with (args.out_dir / "official-gamebooks-source-manifest.csv").open(
            "w", newline="", encoding="utf-8") as destination:
        fields = ("game_id", "week", "away_team", "home_team", "gsis", "url",
                  "bytes", "sha256", "last_modified")
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest)
    active_counts = Counter(v["active"] for game in game_coverage.values()
                            for v in game["teams"].values())
    inactive_counts = Counter(v["inactive"] for game in game_coverage.values()
                              for v in game["teams"].values())
    coverage = {
        "season": SEASON, "weeks": [FIRST_WEEK, LAST_WEEK],
        "game_count": len(game_coverage), "team_game_count": 240,
        "roster_player_game_rows": len(output),
        "active_player_game_rows": sum(
            1 for row in output if row["actual_gameday_status"] == "ACTIVE"
        ),
        "inactive_player_game_rows": sum(1 for row in output
                                          if row["actual_gameday_status"] == "INACTIVE"),
        "active_roster_size_distribution": dict(sorted(active_counts.items())),
        "inactive_list_size_distribution": dict(sorted(inactive_counts.items())),
        "weekly_source_status_conflicts": len(source_conflicts),
        "weekly_identity_source_sha256": sha256(args.weekly_roster),
        "all_gamebooks_hash_verified": True,
        "all_player_id_joins_resolved": True,
        "forecast_cutoff_eligibility": "not established; NFL gamebooks are postgame sources",
        "identity_source": "nflverse roster_weekly_2026.parquet (GSIS ID, team, week, jersey, name)",
        "roster_status_source": "NFL GSIS official gamebook, page 1 roster sections",
        "source_manifest": "official-gamebooks-source-manifest.csv",
        "player_rows": "finalized-game-day-rosters.csv",
        "conflict_rows": "nflverse-vs-gamebook-status-conflicts.csv",
        "games": game_coverage,
    }
    (args.out_dir / "finalized-roster-coverage.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("Games:", len(game_coverage), "team-games: 240 roster rows:", len(output))
    print("Active roster size distribution:", dict(sorted(active_counts.items())))
    print("Inactive list size distribution:", dict(sorted(inactive_counts.items())))
    print("Weekly roster status conflicts:", len(source_conflicts))
    print("Identity joins unresolved: 0; gamebook hashes verified: 120/120")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-csv", type=Path, required=True)
    parser.add_argument("--weekly-roster", type=Path, required=True)
    parser.add_argument("--gamebook-manifest", type=Path, required=True)
    parser.add_argument("--gamebooks-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
