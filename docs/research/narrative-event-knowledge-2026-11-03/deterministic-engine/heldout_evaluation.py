#!/usr/bin/env python3
"""Freeze and render a seeded, cutoff-safe sample of upcoming NFL and NBA games."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import re
import socket
import sqlite3
import statistics
import sys
import time
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))

from story_engine import LEAGUE_SIZE, LEAGUE_TEAM_NAMES, TEAM_CITIES, collect_story_facts, generate_story  # noqa: E402


ENGINE_SHA256 = "2791cd0fd723de721859b5d64dacd50646b6b6aed7697d5dedc24b1fa1924e92"
KNOWN_EXAMPLES = {
    "2026_08_CHI_SEA", "0022600164", "0022600165", "0022600167", "0022600168", "0022600169",
}
PREFLIGHT_GAMES = {"2026_09_JAX_BAL", "0022600173"}
EXAMPLES_PATH = ROOT / "docs/research/narrative-event-knowledge-2026-11-03/relevance-ranking/examples.jsonl"
OUT_DIR = Path(__file__).resolve().parent


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _known_example_ids(additional: set[str] | None = None) -> set[str]:
    known = set(KNOWN_EXAMPLES)
    if EXAMPLES_PATH.exists():
        for line in EXAMPLES_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                known.add(str(json.loads(line)["target_game_id"]))
    return known | PREFLIGHT_GAMES | (additional or set())


def _candidate_population(db_path: Path, cutoff: str, seed: int,
                          additional_exclusions: set[str] | None = None) -> tuple[dict, dict[str, list[dict]]]:
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        cutoff_time = _parse_utc(cutoff)
        cutoff_day = cutoff_time.date().isoformat()
        known_ids = _known_example_ids(additional_exclusions)
        nfl_rows = list(connection.execute(
            """SELECT game_id,season,week,gameday,weekday,gametime,away_team,home_team,
                      away_score,home_score,source,ingested_at
               FROM nfl_schedule
               WHERE season=2026 AND game_type='REG' AND gameday>=?
                 AND away_team IS NOT NULL AND home_team IS NOT NULL
                 AND away_score IS NULL AND home_score IS NULL
                 AND julianday(ingested_at)<=julianday(?)
               ORDER BY gameday,week,game_id""",
            (cutoff_day, cutoff),
        ))
        nba_rows = list(connection.execute(
            """SELECT game_id,season,season_type,game_date,start_utc,away_team,home_team,
                      label,sub_label,status,status_text,source,ingested_at
               FROM nba_schedule
               WHERE season=2027 AND season_type='REG' AND start_utc>?
                 AND away_team IS NOT NULL AND home_team IS NOT NULL
                 AND status=1
                 AND COALESCE(sub_label,'') NOT IN ('Quarterfinal','Semifinal')
                 AND julianday(ingested_at)<=julianday(?)
               ORDER BY start_utc,game_id""",
            (cutoff, cutoff),
        ))
    finally:
        connection.close()

    populations: dict[str, list[dict]] = {"nfl": [], "nba": []}
    excluded = {"previously_seen_or_preflight": [], "not_after_cutoff": []}

    for raw in nfl_rows:
        row = dict(raw)
        game_id = str(row["game_id"])
        if game_id in known_ids:
            excluded["previously_seen_or_preflight"].append(game_id)
            continue
        # nfl_schedule preserves the publisher's game date but not a UTC kickoff.
        # Midnight UTC on that published date is used only as a conservative cutoff boundary.
        boundary = f"{row['gameday']}T00:00:00Z"
        if _parse_utc(boundary) <= cutoff_time:
            excluded["not_after_cutoff"].append(game_id)
            continue
        row.update({
            "league": "nfl", "game_date": row["gameday"], "start_utc": boundary,
            "start_utc_basis": "published_gameday_midnight_utc_boundary",
        })
        populations["nfl"].append(row)

    for raw in nba_rows:
        row = dict(raw)
        game_id = str(row["game_id"])
        if game_id in known_ids:
            excluded["previously_seen_or_preflight"].append(game_id)
            continue
        if _parse_utc(str(row["start_utc"])) <= cutoff_time:
            excluded["not_after_cutoff"].append(game_id)
            continue
        row.update({"league": "nba", "start_utc_basis": "published_start_utc"})
        populations["nba"].append(row)

    for league, rows in populations.items():
        for row in rows:
            sample_key = hashlib.sha256(f"{seed}|{league}|{row['game_id']}".encode()).hexdigest()
            row["sample_key_sha256"] = sample_key
        rows.sort(key=lambda row: row["sample_key_sha256"])

    manifest = {
        "as_of": cutoff,
        "seed": seed,
        "sampling_method": "sort eligible game IDs by SHA-256(seed|league|game_id), take first N per league",
        "known_example_ids_excluded": sorted(known_ids),
        "preflight_game_ids_excluded": sorted(PREFLIGHT_GAMES),
        "additional_exclusions": sorted(additional_exclusions or set()),
        "excluded": {key: sorted(set(values)) for key, values in excluded.items()},
        "eligible_population_counts": {league: len(rows) for league, rows in populations.items()},
        "eligible_population": {
            league: [{key: value for key, value in row.items()} for row in rows]
            for league, rows in populations.items()
        },
    }
    return manifest, populations


def _input_evidence(facts: dict):
    for team in (facts.get("teams") or {}).values():
        yield from team.get("evidence") or []
    for team in facts.get("league_standings") or []:
        yield from team.get("evidence") or []
    for player in facts.get("players") or []:
        yield from player.get("evidence") or []
        yield from player.get("season_logs") or []
    yield from facts.get("matchup_evidence") or []


def _prior_evidence(facts: dict):
    for team in (facts.get("teams") or {}).values():
        yield from team.get("evidence") or []
    for team in facts.get("league_standings") or []:
        yield from team.get("evidence") or []
    for player in facts.get("players") or []:
        yield from player.get("evidence") or []
        yield from player.get("season_logs") or []


def _selected_evidence_is_linked(selected: list[dict], facts: dict) -> bool:
    available_ids = {str(row.get("id")) for row in _input_evidence(facts)}
    standings_ids = {
        str(row.get("id"))
        for team in facts.get("league_standings") or []
        for row in team.get("evidence") or []
    }
    for item in selected:
        ids = {str(value) for value in item.get("evidence_ids") or []}
        if not ids:
            return False
        evidence = item.get("evidence") or []
        if not evidence:
            return False
        if ids != {str(row.get("id")) for row in evidence}:
            return False
        for row in evidence:
            source_ids = {str(value) for value in row.get("source_ids") or []}
            if source_ids:
                if not source_ids.issubset(standings_ids):
                    return False
            elif str(row.get("id")) not in available_ids:
                # A scheduled matchup has no result row; its source is the frozen schedule record.
                if item.get("kind") != "scheduled_matchup":
                    return False
    return True


def _record_and_streak_claims_match(selected: list[dict]) -> bool:
    for fact in selected:
        if fact.get("kind") not in {"record", "streak"}:
            continue
        rows = sorted(fact.get("evidence") or [], key=lambda row: (row.get("date", ""), row.get("id", "")))
        outcomes = []
        for row in rows:
            if row.get("for") is None or row.get("against") is None:
                continue
            outcomes.append("W" if row["for"] > row["against"] else "L" if row["for"] < row["against"] else "T")
        if fact.get("kind") == "record":
            record = (f"{outcomes.count('W')}-{outcomes.count('L')}" +
                      (f"-{outcomes.count('T')}" if outcomes.count("T") else ""))
            if not str(fact.get("description", "")).endswith(f"record {record}"):
                return False
        else:
            result = outcomes[-1] if outcomes else None
            length = 0
            for outcome in reversed(outcomes):
                if outcome != result:
                    break
                length += 1
            direction = {"W": "winning", "L": "losing", "T": "tied"}.get(result)
            match = re.search(r"(\d+)-game (winning|losing|tied) streak$", str(fact.get("description", "")))
            if (length < 2 or direction is None or not match or int(match.group(1)) != length
                    or match.group(2) != direction):
                return False
    return True


def _rank_claims_recompute(facts: dict, selected: list[dict]) -> bool:
    rank_facts = [fact for fact in selected if fact.get("kind") == "league_rank"]
    if not rank_facts:
        return True
    league = str(facts.get("league", "")).lower()
    standings = facts.get("league_standings") or []
    expected_size = LEAGUE_SIZE.get(league)
    if expected_size is None or len(standings) != expected_size:
        return False
    ranked = []
    all_evidence_ids = set()
    for team in standings:
        rows = [row for row in team.get("evidence") or []
                if row.get("available_at") and _parse_utc(row["available_at"]) <= _parse_utc(facts["as_of"])]
        outcomes = []
        points_for = points_against = 0
        for row in rows:
            if row.get("for") is None or row.get("against") is None:
                continue
            scored, allowed = int(row["for"]), int(row["against"])
            outcomes.append("W" if scored > allowed else "L" if scored < allowed else "T")
            points_for += scored
            points_against += allowed
            all_evidence_ids.add(str(row.get("id")))
        if not outcomes:
            return False
        wins, losses, ties = outcomes.count("W"), outcomes.count("L"), outcomes.count("T")
        ranked.append({
            "code": str(team.get("code")),
            "win_pct": (wins + 0.5 * ties) / len(outcomes),
            "differential": (points_for - points_against) / len(outcomes),
        })
    ranked.sort(key=lambda row: (-row["win_pct"], -row["differential"], row["code"]))
    for fact in rank_facts:
        target_rank = next((index for index, row in enumerate(ranked, 1)
                            if row["code"] == fact.get("team")), None)
        evidence = fact.get("evidence") or []
        source_ids = {str(value) for row in evidence for value in row.get("source_ids", [])}
        if (target_rank != fact.get("rank") or fact.get("league_size") != expected_size
                or source_ids != all_evidence_ids):
            return False
    return True


def _player_attribution_matches(story: str, facts: dict, selected: list[dict]) -> bool:
    teams = (facts.get("teams") or {})
    matchup_codes = {str(code) for code in teams}
    league_names = LEAGUE_TEAM_NAMES.get(str(facts.get("league", "")).lower(), {})
    for fact in selected:
        if fact.get("kind") != "player_form":
            continue
        player_name = str(fact.get("player") or "")
        team_code = str(fact.get("team") or "")
        if not player_name or team_code not in matchup_codes:
            return False
        clause = next((part for part in re.split(r"\s+while\s+|,\s+and\s+", story, flags=re.IGNORECASE)
                       if player_name.lower() in part.lower()), "")
        if not clause:
            return False
        city = TEAM_CITIES.get(team_code, "")
        full_name = league_names.get(team_code, "")
        nickname = full_name.rsplit(" ", 1)[-1] if full_name else ""
        same_city_opponent = any(
            code != team_code and TEAM_CITIES.get(code) == city for code in matchup_codes
        )
        local = clause.lower()
        if same_city_opponent:
            if not any(term and term.lower() in local for term in (full_name, nickname)):
                return False
        elif not any(term and term.lower() in local for term in (city, full_name, nickname)):
            return False
    return True


COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _recent_player_rows(player: dict, cutoff: str) -> list[dict]:
    rows = [row for row in player.get("evidence") or []
            if row.get("available_at") and _parse_utc(row["available_at"]) <= _parse_utc(cutoff)]
    return sorted(rows, key=lambda row: (str(row.get("date") or ""), _parse_utc(row["available_at"])),
                  reverse=True)[:5]


def _stat_values(rows: list[dict], key: str) -> list[float]:
    return [float(row["stats"][key]) for row in rows
            if row.get("stats") and row["stats"].get(key) is not None]


def _display_number(value: float, decimals: int = 1) -> str:
    rounded = round(float(value), decimals)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.{decimals}f}"


def _number_word_matches(word: str, value: int) -> bool:
    return COUNT_WORDS.get(word.lower(), int(word) if word.isdigit() else None) == value


def _player_claim_matches(story: str, facts: dict, fact: dict) -> bool:
    identity = str(fact.get("id", "")).partition(":")[2]
    player = next((row for row in facts.get("players") or []
                   if str(row.get("player_id")) == identity and row.get("name") == fact.get("player")
                   and row.get("team") == fact.get("team")), None)
    if player is None:
        return False
    segments = re.split(r"\s+while\s+|,\s+and\s+", story, flags=re.IGNORECASE)
    clause = next((part for part in segments if fact["player"].lower() in part.lower()), "")
    if not clause:
        return False
    rows = _recent_player_rows(player, facts["as_of"])
    if str(facts.get("league", "")).lower() == "nba":
        points = _stat_values(rows, "PTS")
        assists = _stat_values(rows, "AST")
        rebounds = _stat_values(rows, "REB")
        match = re.search(r"has scored (\d+) and (\d+) in his last two", clause)
        if match:
            return len(points) >= 2 and [int(round(v)) for v in points[:2]] == [int(match[1]), int(match[2])]
        match = re.search(r"has scored at least (\d+) in each of his last five, including a (\d+)-point night", clause)
        if match:
            return (len(points) >= 5 and all(v >= int(match[1]) for v in points[:5])
                    and int(round(max(points[:5]))) == int(match[2]))
        match = re.search(r"is averaging ([0-9.]+) points and ([0-9.]+) assists over his last five games, including a (\d+)-point (?:outing|night)", clause)
        if match:
            return (len(points) >= 5 and len(assists) >= 5
                    and _display_number(sum(points[:5]) / 5) == match[1]
                    and _display_number(sum(assists[:5]) / 5) == match[2]
                    and int(round(max(points[:5]))) == int(match[3]))
        match = re.search(r"has put up ([0-9, ]+(?: and [0-9]+)?) in (\w+) of his last five", clause)
        if match:
            shown = [int(value) for value in re.findall(r"\d+", match[1])]
            values = [int(v) for v in points[:5] if v >= 35]
            return values == shown and _number_word_matches(match[2], len(values))
        match = re.search(r"is averaging ([0-9.]+) points and ([0-9.]+) assists over his last five", clause)
        if match:
            return (len(points) >= 5 and len(assists) >= 5
                    and _display_number(sum(points[:5]) / 5) == match[1]
                    and _display_number(sum(assists[:5]) / 5) == match[2])
        match = re.search(r"has scored at least 23 in (each|one|two|three|four|five) of his last five", clause)
        if match:
            count = sum(v >= 23 for v in points[:5])
            expected = 5 if match[1] == "each" else COUNT_WORDS.get(match[1])
            return len(points) >= 5 and count == expected
        match = re.search(r"has scored 20 or more in (each|one|two|three|four) of his last four, including ([\d, ]+)", clause)
        if match:
            values = [int(v) for v in re.findall(r"\d+", match[2])]
            recent = points[:4]
            count = sum(v >= 20 for v in recent)
            expected = 4 if match[1] == "each" else COUNT_WORDS.get(match[1])
            return (len(recent) >= 4 and count == expected
                    and [int(v) for v in recent if v >= 20] == values)
        match = re.search(r"is averaging ([0-9.]+) (assists|rebounds) over his last five", clause)
        if match:
            values = assists if match[2] == "assists" else rebounds
            return len(values) >= 5 and _display_number(sum(values[:5]) / 5) == match[1]
        return False

    receiving = _stat_values(rows, "rec_yds")
    rushing = _stat_values(rows, "rush_yds")
    passing = _stat_values(rows, "pass_yds")
    carries = _stat_values(rows, "carries")
    targets = _stat_values(rows, "targets")
    match = re.search(r"topping 100 receiving yards in (\w+) of his last five games", clause)
    if match:
        count = sum(value >= 100 for value in receiving[:5])
        return count >= 3 and _number_word_matches(match[1], count)
    match = re.search(r"has topped 100 rushing yards in one of his last four games", clause)
    if match:
        return any(value >= 100 for value in rushing[:4])
    match = re.search(r"has thrown for 300 yards in (\w+) of his last five games", clause)
    if match:
        count = sum(value >= 300 for value in passing[:5])
        return count >= 2 and _number_word_matches(match[1], count)
    match = re.search(r"has rushed for (\d+) yards and (\w+) touchdowns", clause)
    if match and player.get("season_totals_complete"):
        totals = {"rush_yds": 0.0, "rush_td": 0.0}
        for row in player.get("season_logs") or []:
            if _parse_utc(row["available_at"]) > _parse_utc(facts["as_of"]):
                continue
            stats = row.get("stats") or {}
            totals["rush_yds"] += float(stats.get("rush_yds") or 0)
            totals["rush_td"] += float(stats.get("rush_td") or 0)
        shown_tds = COUNT_WORDS.get(match[2], int(match[2]) if match[2].isdigit() else None)
        return int(totals["rush_yds"]) == int(match[1]) and int(totals["rush_td"]) == shown_tds
    match = re.search(r"has found the end zone in (\w+) of his last five games", clause)
    if match:
        count = sum(
            float((row.get("stats") or {}).get("rec_td") or 0)
            + float((row.get("stats") or {}).get("rush_td") or 0) > 0
            for row in rows[:5]
        )
        return count >= 3 and _number_word_matches(match[1], int(count))
    match = re.search(r"has carried the ball 20 or more times in (\w+) of his last five games", clause)
    if match:
        count = sum(value >= 20 for value in carries[:5])
        return count >= 3 and _number_word_matches(match[1], count)
    match = re.search(r"has seen at least eight targets in (\w+) of his last five games", clause)
    if match:
        count = sum(value >= 8 for value in targets[:5])
        return count >= 3 and _number_word_matches(match[1], count)
    match = re.search(r"is coming off a (\d+)-yard receiving game", clause)
    if match:
        return bool(receiving) and int(round(receiving[0])) == int(match[1])
    match = re.search(r"has topped 100 receiving yards in (\w+) of his last (\w+) games", clause)
    if match:
        count = sum(value >= 100 for value in receiving)
        denominator = COUNT_WORDS.get(match[2], int(match[2]) if match[2].isdigit() else None)
        return count > 0 and count == COUNT_WORDS.get(match[1]) and denominator == len(receiving)
    return False


def _all_player_claims_match(story: str, facts: dict, selected: list[dict]) -> bool:
    return all(_player_claim_matches(story, facts, fact)
               for fact in selected if fact.get("kind") == "player_form")


def _pattern(story: str, facts: dict) -> str:
    text = story.lower()
    names = set()
    for team in (facts.get("teams") or {}).values():
        code = team.get("code")
        full_name = LEAGUE_TEAM_NAMES.get(str(facts.get("league", "")).lower(), {}).get(code, "")
        names.add(str(team.get("name") or ""))
        names.add(full_name)
        names.add(str(code or ""))
        names.add(TEAM_CITIES.get(code, ""))
        names.add(full_name.rsplit(" ", 1)[-1] if full_name else "")
    for player in facts.get("players") or []:
        names.add(str(player.get("name") or ""))
    for name in sorted((name for name in names if name), key=len, reverse=True):
        text = re.sub(rf"(?<![a-z0-9]){re.escape(name.lower())}(?![a-z0-9])", "[entity]", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", "#", text)
    text = re.sub(r"[^a-z#\[\] ]+", " ", text)
    return re.sub(r"\s+", " ", text.split(".", 1)[0]).strip()


def run(args: argparse.Namespace) -> None:
    db_path = Path(args.db).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    engine_path = ROOT / "backend/story_engine.py"
    engine_sha = hashlib.sha256(engine_path.read_bytes()).hexdigest()
    if engine_sha != ENGINE_SHA256:
        raise RuntimeError(f"renderer changed after freeze: expected {ENGINE_SHA256}, found {engine_sha}")

    if not re.fullmatch(r"[a-z0-9_]+", args.run_name):
        raise ValueError("run name must contain only lowercase letters, numbers and underscores")
    prior_ids = set()
    if args.exclude_jsonl:
        for source_path in args.exclude_jsonl:
            with Path(source_path).open(encoding="utf-8") as previous:
                prior_ids.update(str(json.loads(line)["target_game_id"])
                                 for line in previous if line.strip())
    manifest, populations = _candidate_population(db_path, args.as_of, args.seed, prior_ids)
    insufficient = {league: len(rows) for league, rows in populations.items() if len(rows) < args.per_league}
    if insufficient:
        raise RuntimeError(f"eligible population too small for requested sample: {insufficient}")

    sample_by_league = {league: rows[:args.per_league] for league, rows in populations.items()}
    manifest["renderer_sha256"] = engine_sha
    manifest["evaluator_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    manifest["python_version"] = platform.python_version()
    manifest["sample_counts"] = {league: len(rows) for league, rows in sample_by_league.items()}
    manifest["sampled_games"] = [row for league in ("nfl", "nba") for row in sample_by_league[league]]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT_DIR / f"{args.run_name}_sampling_manifest.json"
    output_path = OUT_DIR / f"{args.run_name}_results.jsonl"
    summary_path = OUT_DIR / f"{args.run_name}_summary.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pattern_counts: Counter[str] = Counter()
    pattern_examples: dict[str, str] = {}
    timings = {"collection_ms": [], "render_ms": []}
    metrics = Counter()

    with output_path.open("w", encoding="utf-8") as output:
        for league in ("nfl", "nba"):
            for row in sample_by_league[league]:
                game = {
                    "league": league, "season": int(row["season"]), "game_id": str(row["game_id"]),
                    "away": str(row["away_team"]), "home": str(row["home_team"]),
                    "start_utc": str(row["start_utc"]),
                }
                started = time.perf_counter()
                facts = collect_story_facts(db_path, game, as_of=args.as_of)
                collected = time.perf_counter()
                facts["source"]["database"] = db_path.name
                facts["source"]["schedule_table"] = "nfl_schedule" if league == "nfl" else "nba_schedule"
                facts["source"]["schedule_ingested_at"] = row["ingested_at"]
                facts["source"]["schedule_source"] = row["source"]
                facts["source"]["target_start_basis"] = row["start_utc_basis"]
                facts["matchup_evidence"] = [{
                    "id": f"{facts['source']['schedule_table']}:{game['game_id']}",
                    "game_id": game["game_id"],
                    "available_at": row["ingested_at"],
                    "date": row.get("game_date"),
                    "source": row["source"],
                    "away": game["away"], "home": game["home"],
                }]

                def forbidden_call(*_args, **_kwargs):
                    raise AssertionError("generation attempted a network call")

                with patch("urllib.request.urlopen", side_effect=forbidden_call), \
                     patch("socket.create_connection", side_effect=forbidden_call):
                    result = generate_story(facts)
                rendered = time.perf_counter()
                collection_ms = round((collected - started) * 1000, 3)
                render_ms = round((rendered - collected) * 1000, 3)
                timings["collection_ms"].append(collection_ms)
                timings["render_ms"].append(render_ms)

                evidence_rows = list(_input_evidence(facts))
                timestamps_safe = all(
                    row.get("available_at") and _parse_utc(str(row["available_at"])) <= _parse_utc(args.as_of)
                    for row in evidence_rows
                )
                target_game_absent = all(
                    str(row.get("game_id") or row.get("id")) != game["game_id"]
                    for row in _prior_evidence(facts)
                )
                selected_facts = result["manifest"]["selected_facts"]
                player_teams_valid = all(
                    fact.get("team") in (game["away"], game["home"])
                    for fact in selected_facts if fact.get("kind") == "player_form"
                )
                player_claims_valid = _all_player_claims_match(result["story"], facts, selected_facts)
                player_attribution_valid = _player_attribution_matches(result["story"], facts, selected_facts)
                checks = {
                    "nonempty_story": bool(result.get("story", "").strip()),
                    "selected_facts_have_linked_source_rows": _selected_evidence_is_linked(selected_facts, facts),
                    "team_record_and_streak_claims_recompute": _record_and_streak_claims_match(selected_facts),
                    "league_rank_claims_recompute": _rank_claims_recompute(facts, selected_facts),
                    "player_stat_claims_recompute": player_claims_valid,
                    "player_team_attribution_matches_prose": player_attribution_valid,
                    "all_input_evidence_is_cutoff_safe": timestamps_safe,
                    "target_game_absent_from_prior_evidence": target_game_absent,
                    "player_team_codes_match_matchup": player_teams_valid,
                }
                pattern = _pattern(result["story"], facts)
                pattern_counts[pattern] += 1
                pattern_examples.setdefault(pattern, game["game_id"])
                metrics["empty_previews"] += not checks["nonempty_story"]
                metrics["unsupported_evidence_links"] += not checks["selected_facts_have_linked_source_rows"]
                metrics["record_or_streak_recompute_failures"] += not checks["team_record_and_streak_claims_recompute"]
                metrics["league_rank_recompute_failures"] += not checks["league_rank_claims_recompute"]
                metrics["player_stat_recompute_failures"] += not checks["player_stat_claims_recompute"]
                metrics["player_attribution_mismatches"] += not checks["player_team_attribution_matches_prose"]
                metrics["cutoff_violations"] += not checks["all_input_evidence_is_cutoff_safe"]
                metrics["target_game_leakage"] += not checks["target_game_absent_from_prior_evidence"]
                metrics["player_team_code_mismatches"] += not checks["player_team_codes_match_matchup"]

                evidence_bundle = json.loads(json.dumps(facts, ensure_ascii=False))
                record = {
                    "target_game_id": game["game_id"],
                    "league": league,
                    "season": game["season"],
                    "matchup": {"away": game["away"], "home": game["home"]},
                    "game_date": row.get("game_date"),
                    "start_utc": row["start_utc"],
                    "start_utc_basis": row["start_utc_basis"],
                    "as_of": args.as_of,
                    "schedule_ingested_at": row["ingested_at"],
                    "story": result["story"],
                    "angle": result["angle"],
                    "manifest": result["manifest"],
                    "mechanical_audit": checks,
                    "normalized_lead_pattern": pattern,
                    "timing_ms": {"collection": collection_ms, "render": render_ms},
                    "input_facts": evidence_bundle,
                }
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                output.flush()

    total = sum(len(rows) for rows in sample_by_league.values())
    repeated_patterns = [
        {"pattern": pattern, "count": count, "example_game_id": pattern_examples[pattern]}
        for pattern, count in pattern_counts.most_common()
    ]
    summary = {
        "as_of": args.as_of,
        "seed": args.seed,
        "sample_counts": {league: len(rows) for league, rows in sample_by_league.items()},
        "eligible_population_counts": manifest["eligible_population_counts"],
        "renderer_sha256": engine_sha,
        "evaluator_sha256": manifest["evaluator_sha256"],
        "python_version": platform.python_version(),
        "total_previews": total,
        "empty_previews": int(metrics["empty_previews"]),
        "unsupported_evidence_links": int(metrics["unsupported_evidence_links"]),
        "record_or_streak_recompute_failures": int(metrics["record_or_streak_recompute_failures"]),
        "league_rank_recompute_failures": int(metrics["league_rank_recompute_failures"]),
        "player_stat_recompute_failures": int(metrics["player_stat_recompute_failures"]),
        "player_attribution_mismatches": int(metrics["player_attribution_mismatches"]),
        "cutoff_violations": int(metrics["cutoff_violations"]),
        "target_game_leakage": int(metrics["target_game_leakage"]),
        "player_team_code_mismatches": int(metrics["player_team_code_mismatches"]),
        "unique_normalized_lead_patterns": len(pattern_counts),
        "previews_using_repeated_lead_patterns": sum(count for count in pattern_counts.values() if count > 1),
        "lead_patterns": repeated_patterns,
        "collection_ms_median": round(statistics.median(timings["collection_ms"]), 3),
        "render_ms_median": round(statistics.median(timings["render_ms"]), 3),
        "model_calls": 0,
        "network_calls": 0,
        "database_writes": 0,
        "evidence_preserved_in": output_path.name,
        "status": "generated; editorial ratings are recorded separately",
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"sampling_manifest": str(manifest_path), "results": str(output_path), "summary": summary}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Existing SQLite database, opened read-only")
    parser.add_argument("--as-of", default="2026-11-03T03:00:53Z")
    parser.add_argument("--seed", type=int, default=20261103)
    parser.add_argument("--per-league", type=int, default=50)
    parser.add_argument("--run-name", default="heldout")
    parser.add_argument("--exclude-jsonl", action="append",
                        help="Prior result JSONL whose game IDs must be excluded; repeat to add more")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
