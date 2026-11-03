"""CPU-only deterministic sports preview renderer.

Fact collection is read-only and cutoff-aware. Story selection and rendering do not
make network calls or import any model client. The returned evidence manifest is
kept separate from the published prose.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any


LEAGUE_SIZE = {"nba": 30, "nfl": 32}
RESEARCH_JARGON = re.compile(
    r"verified evidence|supplied deltas|relationship gate|metric alignment|"
    r"no eligible preview|source rows|no relationship cleared|evidence gate",
    re.IGNORECASE,
)

LEAGUE_TEAM_NAMES = {
    "nba": {
        "ATL": "Atlanta Hawks", "BKN": "Brooklyn Nets", "BOS": "Boston Celtics",
        "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
        "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
        "GS": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
        "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
        "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
        "NO": "New Orleans Pelicans", "NY": "New York Knicks", "OKC": "Oklahoma City Thunder",
        "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
        "POR": "Portland Trail Blazers", "SA": "San Antonio Spurs", "SAC": "Sacramento Kings",
        "TOR": "Toronto Raptors", "UTAH": "Utah Jazz", "WSH": "Washington Wizards",
    },
    "nfl": {
        "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
        "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
        "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
        "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
        "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
        "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
        "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
        "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
        "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
        "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
        "TEN": "Tennessee Titans", "WSH": "Washington Commanders",
    },
}
TEAM_CITIES = {
    "ATL": "Atlanta", "BKN": "Brooklyn", "BOS": "Boston", "CHA": "Charlotte",
    "CHI": "Chicago", "CLE": "Cleveland", "DAL": "Dallas", "DEN": "Denver",
    "DET": "Detroit", "GS": "Golden State", "HOU": "Houston", "IND": "Indianapolis",
    "LAC": "Los Angeles", "LAL": "Los Angeles", "MEM": "Memphis", "MIA": "Miami",
    "MIL": "Milwaukee", "MIN": "Minnesota", "NO": "New Orleans", "NY": "New York",
    "OKC": "Oklahoma City", "ORL": "Orlando", "PHI": "Philadelphia", "PHX": "Phoenix",
    "POR": "Portland", "SA": "San Antonio", "SAC": "Sacramento", "TOR": "Toronto",
    "UTAH": "Utah", "WSH": "Washington", "ARI": "Arizona", "BAL": "Baltimore",
    "BUF": "Buffalo", "CAR": "Carolina", "CIN": "Cincinnati", "GB": "Green Bay",
    "JAX": "Jacksonville", "KC": "Kansas City", "LAR": "Los Angeles", "LV": "Las Vegas",
    "NE": "New England", "NYG": "New York", "NYJ": "New York", "PIT": "Pittsburgh",
    "SEA": "Seattle", "SF": "San Francisco", "TB": "Tampa Bay", "TEN": "Tennessee",
}


def _utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: str | datetime) -> str:
    return _utc(value).isoformat(timespec="seconds").replace("+00:00", "Z")


def _available(evidence: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    cutoff = _utc(as_of)
    return [item for item in evidence if item.get("available_at") and _utc(item["available_at"]) <= cutoff]


def _record_text(team: dict[str, Any]) -> str:
    ties = int(team.get("ties") or 0)
    record = f"{team['wins']}-{team['losses']}" + (f"-{ties}" if ties else "")
    return record


def _count_word(value: int | float) -> str:
    words = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
             6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
    number = int(value)
    return words.get(number, str(number))


def _city(team: dict[str, Any]) -> str:
    if team.get("code") in TEAM_CITIES:
        return TEAM_CITIES[team["code"]]
    name = str(team.get("name") or "").strip()
    if name:
        return name.rsplit(" ", 1)[0] if len(name.split()) > 1 else name
    return str(team["code"])


def _team_name(code: str, league: str) -> str:
    return LEAGUE_TEAM_NAMES.get(str(league).lower(), {}).get(code, code)


def _nickname(team: dict[str, Any]) -> str:
    name = str(team.get("name") or "").strip()
    if name:
        return name.split()[-1]
    return str(team["code"])


def _team_fact(team: dict[str, Any], *, kind: str, description: str) -> dict[str, Any]:
    evidence = list(team.get("evidence") or [])
    return {
        "id": f"{kind}:{team['code']}", "kind": kind,
        "team": team["code"], "description": description,
        "evidence_ids": [str(item["id"]) for item in evidence],
        "evidence": evidence,
    }


def _recompute_team(team: dict[str, Any], code: str, as_of: str) -> dict[str, Any]:
    """Rebuild records and streaks from available scored game rows, not summary fields."""
    result = dict(team)
    rows = _available(list(team.get("evidence") or []), as_of)
    rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("id") or "")))
    wins = losses = ties = points_for = points_against = 0
    checked = []
    for row in rows:
        if row.get("for") is None or row.get("against") is None:
            continue
        mine, theirs = int(row["for"]), int(row["against"])
        outcome = "W" if mine > theirs else "L" if mine < theirs else "T"
        wins += outcome == "W"
        losses += outcome == "L"
        ties += outcome == "T"
        points_for += mine
        points_against += theirs
        checked.append({**row, "result": outcome})
    expected_games = int(team.get("games") or 0)
    complete = expected_games > 0 and len(checked) == expected_games
    result.update({
        "code": code, "wins": int(wins), "losses": int(losses), "ties": int(ties),
        "games": len(checked), "for": points_for, "against": points_against,
        "evidence": checked, "record_verified": complete,
    })
    outcomes = [row["result"] for row in checked]
    result["streak_result"] = outcomes[-1] if outcomes else None
    result["streak_length"] = 0
    if outcomes and complete:
        for outcome in reversed(outcomes):
            if outcome != outcomes[-1]:
                break
            result["streak_length"] += 1
    else:
        result["streak_result"] = None
    return result


def _verified_standings(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    league = str(bundle.get("league", "")).lower()
    expected = LEAGUE_SIZE.get(league)
    if expected is None or not bundle.get("as_of"):
        return []
    source_rows = bundle.get("league_standings") or []
    if len(source_rows) != expected or len({row.get("code") for row in source_rows}) != expected:
        return []
    rows = []
    for source in source_rows:
        code = source.get("code")
        if not code:
            return []
        row = _recompute_team(source, str(code), bundle["as_of"])
        if not row.get("record_verified") or row["games"] <= 0:
            return []
        row["win_pct"] = (row["wins"] + 0.5 * row["ties"]) / row["games"]
        row["differential"] = (row["for"] - row["against"]) / row["games"]
        rows.append(row)
    if sum(row["wins"] for row in rows) != sum(row["losses"] for row in rows):
        return []
    return sorted(rows, key=lambda row: (-row["win_pct"], -row["differential"], row["code"]))


def _league_is_complete(bundle: dict[str, Any]) -> bool:
    rows = _verified_standings(bundle)
    return len(rows) == LEAGUE_SIZE.get(str(bundle.get("league", "")).lower())


def _rank_fact(bundle: dict[str, Any], team: dict[str, Any]) -> dict[str, Any] | None:
    standings = _verified_standings(bundle)
    if not standings:
        return None
    target = next((row for row in standings if row["code"] == team["code"]), None)
    if target is None:
        return None
    target_rank = next(i for i, row in enumerate(standings, 1) if row["code"] == team["code"])
    coverage_evidence = [item for row in standings for item in (row.get("evidence") or [])]
    # A single snapshot marker covers the complete schedule-derived table while retaining its source IDs.
    fact_evidence = [{
        "id": f"{bundle['league']}-standings:{bundle.get('season', 'current')}:{bundle['as_of'][:10]}",
        "available_at": max((item["available_at"] for item in coverage_evidence), key=_utc),
        "source_ids": sorted({str(item["id"]) for item in coverage_evidence}),
        "team_count": len(standings),
    }]
    return {
        "id": f"league_rank:{team['code']}", "kind": "league_rank",
        "team": team["code"], "rank": target_rank, "league_size": len(standings),
        "description": f"{_city(team)} ranks {target_rank} of {len(standings)}",
        "evidence_ids": [fact_evidence[0]["id"]], "evidence": fact_evidence,
    }


def select_story_angle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Choose the game headline from team narratives before inspecting player stats."""
    away, home = bundle["teams"][bundle["away"]], bundle["teams"][bundle["home"]]
    teams = (away, home)
    perfect = [t for t in teams if t.get("record_verified") and t["wins"] >= 4 and t["losses"] == 0 and t.get("games", 0) >= 4]
    winless = [t for t in teams if t.get("record_verified") and t["wins"] == 0 and t["losses"] >= 4 and t.get("games", 0) >= 4]
    winning_streaks = [t for t in teams if t.get("streak_result") == "W" and t.get("streak_length", 0) >= 3]
    losing_streaks = [t for t in teams if t.get("streak_result") == "L" and t.get("streak_length", 0) >= 3]
    verified_last = [t for t in winless if (rank := _rank_fact(bundle, t)) and rank["rank"] == rank["league_size"]]
    top_four = [t for t in teams if (rank := _rank_fact(bundle, t)) and rank["rank"] <= 4]

    if perfect:
        lead = perfect[0]
        return {"kind": "undefeated", "lead_team": lead["code"], "teams": [t["code"] for t in teams]}
    if verified_last:
        # Give the streaking opponent the lead when the last-place side is visiting.
        other = next((t for t in teams if t["code"] != verified_last[0]["code"]), None)
        if other and other.get("streak_result") == "W" and other.get("streak_length", 0) >= 3:
            lead = other
        else:
            lead = verified_last[0]
        return {"kind": "winless_last", "lead_team": lead["code"], "teams": [t["code"] for t in teams]}
    if len(top_four) == 2:
        return {"kind": "top_four", "lead_team": home["code"], "teams": [t["code"] for t in teams]}
    if winning_streaks and losing_streaks:
        return {"kind": "streak_clash", "lead_team": home["code"], "teams": [t["code"] for t in teams]}
    if winning_streaks or losing_streaks:
        candidates = winning_streaks + losing_streaks
        lead = max(candidates, key=lambda t: t.get("streak_length", 0))
        kind = "winning_streak" if lead.get("streak_result") == "W" else "losing_streak"
        return {"kind": kind, "lead_team": lead["code"], "teams": [t["code"] for t in teams]}
    return {"kind": "records", "lead_team": home["code"], "teams": [t["code"] for t in teams]}


def _player_stats(player: dict[str, Any], as_of: str) -> dict[str, list[float]]:
    """Return cutoff-safe recent stat arrays, deriving them from the underlying game-log rows."""
    evidence = _available(list(player.get("evidence") or []), as_of)
    evidence.sort(key=lambda row: (str(row.get("date") or ""), _utc(row["available_at"])), reverse=True)
    evidence = evidence[:5]
    if not evidence:
        return {}
    league = str(player.get("league", "")).lower()
    mappings = ({"points": ("PTS", "points"), "assists": ("AST", "assists"),
                 "rebounds": ("REB", "rebounds")} if league == "nba" else {
                 "receiving_yards": ("rec_yds", "receiving_yards"),
                 "receiving_touchdowns": ("rec_td", "receiving_touchdowns"),
                 "receptions": ("rec", "receptions"),
                 "rushing_yards": ("rush_yds", "rushing_yards"),
                 "rushing_touchdowns": ("rush_td", "rushing_touchdowns"),
                 "carries": ("carries",), "targets": ("targets",),
                 "passing_yards": ("pass_yds", "passing_yards"),
                 "passing_touchdowns": ("pass_td", "passing_touchdowns")})
    result = {}
    for output, candidates in mappings.items():
        values = []
        for row in evidence:
            stats = row.get("stats") or {}
            value = next((stats[key] for key in candidates if key in stats and stats[key] is not None), None)
            if value is not None:
                values.append(float(value))
        if values:
            result[output] = values
    return result


def _player_season_totals(player: dict[str, Any], as_of: str) -> tuple[dict[str, float], list[dict[str, Any]]]:
    if not player.get("season_totals_complete"):
        return {}, []
    rows = _available(list(player.get("season_logs") or []), as_of)
    totals: dict[str, float] = defaultdict(float)
    for row in rows:
        stats = row.get("stats") or {}
        for source_key, output_key in (("rush_yds", "rush_yards"), ("rush_td", "rush_touchdowns"),
                                       ("rec_yds", "receiving_yards"), ("rec_td", "receiving_touchdowns"),
                                       ("pass_yds", "passing_yards"), ("pass_td", "passing_touchdowns")):
            if source_key in stats:
                totals[output_key] += float(stats[source_key] or 0)
    return dict(totals), rows


def _best_player(players: list[dict[str, Any]], as_of: str, league: str) -> dict[str, Any] | None:
    ranked = []
    for player in players:
        evidence = _available(list(player.get("evidence") or []), as_of)
        if not evidence:
            continue
        stats = _player_stats(player, as_of)
        score = 0.0
        if league == "nba":
            points = stats.get("points", [])
            assists = stats.get("assists", [])
            rebounds = stats.get("rebounds", [])
            if points:
                score += max(points) / 5
                score += sum(v >= 30 for v in points) * 2
                score += sum(v >= 35 for v in points) * 2
                score += max(0, (sum(points) / len(points) - 20) / 3)
            if assists:
                average_assists = sum(assists) / len(assists)
                score += max(0, (average_assists - 4) / 2)
                if average_assists >= 8:
                    score += 2
            if rebounds:
                average_rebounds = sum(rebounds) / len(rebounds)
                score += max(0, (average_rebounds - 7) / 2)
                if average_rebounds >= 10:
                    score += 2
        else:
            receiving = stats.get("receiving_yards", [])
            rushing = stats.get("rushing_yards", [])
            passing = stats.get("passing_yards", [])
            touchdowns = (stats.get("receiving_touchdowns", []) + stats.get("rushing_touchdowns", [])
                          + stats.get("passing_touchdowns", []))
            score += sum(v >= 100 for v in receiving) * 3
            score += sum(v >= 100 for v in rushing) * 2.5
            score += sum(v >= 300 for v in passing) * 2
            score += sum(v > 0 for v in touchdowns) * 1.5
            score += max(receiving or [0]) / 30
            score += max(rushing or [0]) / 35
            score += max(passing or [0]) / 45
            score += sum(v >= 8 for v in stats.get("targets", [])) * 1.5
            score += sum(v >= 20 for v in stats.get("carries", [])) * 1.5
        totals, _ = _player_season_totals(player, as_of)
        score += min(5, float(totals.get("rush_yards", 0)) / 100)
        score += min(5, float(totals.get("rush_touchdowns", 0)))
        if score > 0:
            ranked.append({"player": player, "score": score, "stats": stats})
    ranked.sort(key=lambda row: (-row["score"], row["player"].get("name", "")))
    return ranked[0] if ranked else None


def select_players(bundle: dict[str, Any], angle: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Choose up to two on-topic player facts after the team angle is fixed."""
    as_of = bundle["as_of"]
    league = str(bundle["league"]).lower()
    candidates = []
    for player in bundle.get("players", []):
        if player.get("team") not in (bundle["away"], bundle["home"]):
            continue
        evidence = _available(list(player.get("evidence") or []), as_of)
        stats = _player_stats(player, as_of)
        if not evidence or not stats:
            continue
        scored = _best_player([player], as_of, league)
        if not scored or scored["score"] < (4 if league == "nba" else 3):
            continue
        candidates.append({"player": player, "score": scored["score"], "stats": stats,
                           "evidence": evidence})
    candidates.sort(key=lambda row: (-row["score"], row["player"].get("name", "")))

    # Reserve room for each side when both have a meaningful performance.
    selected = []
    preferred = [angle.get("lead_team"), bundle["away"], bundle["home"]]
    for code in dict.fromkeys(item for item in preferred if item):
        side = next((row for row in candidates if row["player"]["team"] == code), None)
        if side:
            selected.append(side)
    if len(selected) < 2:
        selected_ids = {row["player"].get("player_id", row["player"]["name"]) for row in selected}
        additional = [row for row in candidates
                      if row["player"].get("player_id", row["player"]["name"]) not in selected_ids]
        selected.extend(additional[:2-len(selected)])
    selected.sort(key=lambda row: (0 if row["player"]["team"] == angle.get("lead_team") else 1,
                                   -row["score"], row["player"].get("name", "")))

    facts = []
    selected_ids = set()
    for row in selected:
        player = row["player"]
        identity = player.get("player_id", player["name"])
        selected_ids.add(identity)
        evidence_by_id = {str(item["id"]): item for item in row["evidence"]}
        totals, season_logs = _player_season_totals(player, as_of)
        evidence_by_id.update({str(item["id"]): item for item in season_logs})
        evidence = list(evidence_by_id.values())
        facts.append({
            "id": f"player_form:{identity}", "kind": "player_form",
            "player": player["name"], "team": player["team"],
            "description": f"{player['name']} recent form",
            "evidence_ids": [str(item["id"]) for item in evidence], "evidence": evidence,
            "stats": row["stats"], "season_totals": totals,
        })
    omitted = []
    for player in bundle.get("players", []):
        identity = player.get("player_id", player.get("name"))
        if identity in selected_ids:
            continue
        if player.get("team") not in (bundle["away"], bundle["home"]):
            continue
        player_evidence = _available(list(player.get("evidence") or []), as_of)
        reason = "recent production did not clear the story's player-performance threshold"
        if not player_evidence:
            reason = "no cutoff-safe player logs"
        omitted.append({"fact_id": f"player_form:{identity}", "reason": reason})
    return facts, omitted


def _number(value: float, decimals: int = 1) -> str:
    rounded = round(float(value), decimals)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.{decimals}f}"


def _nba_player_clause(fact: dict[str, Any]) -> str | None:
    stats = fact["stats"]
    pts = stats.get("points", [])
    ast = stats.get("assists", [])
    rebounds = stats.get("rebounds", [])
    name, team = fact["player"], fact["team"]
    city = _city({"code": team, "name": _team_name(team, "nba")})
    if len(pts) >= 2 and _recent_logs_complete(fact, ("PTS", "points"), 2) and min(pts[:2]) >= 30:
        return f"{city}'s {name} has scored {_number(pts[0], 0)} and {_number(pts[1], 0)} in his last two"
    if len(pts) >= 5 and _recent_logs_complete(fact, ("PTS", "points"), 5) \
            and sum(value >= 23 for value in pts[:5]) == 5 and max(pts[:5]) >= 35:
        return (f"{city}'s {name} has scored at least 23 in each of his last five, including a "
                f"{_number(max(pts[:5]), 0)}-point night")
    if len(pts) >= 5 and _recent_logs_complete(fact, ("PTS", "points"), 5) \
            and sum(value >= 35 for value in pts[:5]) >= 2 and not (
            pts[0] >= 30 and pts[1] >= 30):
        standout = [int(value) for value in pts[:5] if value >= 35]
        count = len(standout)
        score_text = ", ".join(map(str, standout[:-1])) + f" and {standout[-1]}"
        return f"{city}'s {name} has put up {score_text} in {_count_word(count)} of his last five"
    if len(pts) >= 5 and _recent_logs_complete(fact, ("PTS", "points"), 5) and max(pts[:5]) >= 40:
        average_pts = sum(pts[:5]) / len(pts[:5])
        average_ast = sum(ast[:5]) / len(ast[:5]) if len(ast) >= 5 else None
        if (average_pts >= 24 and average_ast is not None and average_ast >= 5
                and _recent_logs_complete(fact, ("AST", "assists"), 5)):
            nickname = _nickname({"code": team, "name": _team_name(team, "nba")})
            return (f"{nickname} star {name} is averaging {_number(average_pts)} points and "
                    f"{_number(average_ast)} assists over his last five games, including a "
                    f"{_number(max(pts[:5]), 0)}-point outing")
    if len(pts) >= 5 and _recent_logs_complete(fact, ("PTS", "points"), 5):
        average_pts = sum(pts[:5]) / len(pts[:5])
        average_ast = sum(ast[:5]) / len(ast[:5]) if len(ast) >= 5 else None
        if (average_pts >= 25 and average_ast is not None and average_ast >= 5
                and _recent_logs_complete(fact, ("AST", "assists"), 5)):
            return (f"{name} is averaging {_number(average_pts)} points and {_number(average_ast)} assists "
                    f"over his last five for {city}")
    if len(pts) >= 5 and _recent_logs_complete(fact, ("PTS", "points"), 5) \
            and sum(value >= 23 for value in pts[:5]) >= 4:
        count = sum(value >= 23 for value in pts[:5])
        frequency = "each of his last five" if count == 5 else "four of his last five"
        return f"{city}'s {name} has scored at least 23 in {frequency}"
    if len(pts) >= 4 and _recent_logs_complete(fact, ("PTS", "points"), 4) \
            and sum(value >= 20 for value in pts[:4]) >= 3 and max(pts[:4]) >= 30:
        count = sum(value >= 20 for value in pts[:4])
        scores = [int(value) for value in pts[:4] if value >= 20]
        frequency = "each of his last four" if count == 4 else f"{_count_word(count)} of his last four"
        return (f"{city}'s {name} has scored 20 or more in {frequency}, including "
                f"{', '.join(map(str, scores))}")
    if len(ast) >= 5 and _recent_logs_complete(fact, ("AST", "assists"), 5) \
            and sum(ast[:5]) / len(ast[:5]) >= 8:
        return f"{city}'s {name} is averaging {_number(sum(ast[:5]) / len(ast[:5]))} assists over his last five"
    if len(rebounds) >= 5 and _recent_logs_complete(fact, ("REB", "rebounds"), 5) \
            and sum(rebounds[:5]) / len(rebounds[:5]) >= 10:
        return f"{city}'s {name} is averaging {_number(sum(rebounds[:5]) / len(rebounds[:5]))} rebounds over his last five"
    if len(pts) >= 2 and _recent_logs_complete(fact, ("PTS", "points"), 2) \
            and pts[0] >= 30 and pts[1] >= 20:
        return f"{city}'s {name} has scored {int(pts[0])} and {int(pts[1])} in his last two"
    return None


def _recent_player_logs(fact: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {str(row.get("id")): row for row in fact.get("evidence") or []}
    return sorted(by_id.values(),
                  key=lambda row: (str(row.get("date") or ""), str(row.get("available_at") or "")),
                  reverse=True)


def _recent_logs_complete(fact: dict[str, Any], keys: tuple[str, ...], count: int) -> bool:
    rows = _recent_player_logs(fact)[:count]
    return len(rows) == count and all(
        any((row.get("stats") or {}).get(key) is not None for key in keys) for row in rows)


def _latest_log_value(fact: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    rows = _recent_player_logs(fact)
    if not rows:
        return None
    for key in keys:
        value = (rows[0].get("stats") or {}).get(key)
        if value is not None:
            return float(value)
    return None


def _nfl_player_clause(fact: dict[str, Any]) -> str | None:
    stats = fact["stats"]
    rec = stats.get("receiving_yards", [])
    rush = stats.get("rushing_yards", [])
    passing = stats.get("passing_yards", [])
    carries = stats.get("carries", [])
    targets = stats.get("targets", [])
    # A passing touchdown belongs to the receiver, not the quarterback who threw it.
    touchdown_arrays = [stats.get("receiving_touchdowns", []), stats.get("rushing_touchdowns", [])]
    td_length = max((len(values) for values in touchdown_arrays), default=0)
    touchdown_series = [sum(values[index] for values in touchdown_arrays if index < len(values))
                        for index in range(min(5, td_length))]
    name, team = fact["player"], fact["team"]
    city = _city({"code": team, "name": _team_name(team, "nfl")})
    if len(rec) >= 5 and _recent_logs_complete(fact, ("rec_yds", "receiving_yards"), 5) \
            and sum(value >= 100 for value in rec[:5]) >= 3:
        count = sum(value >= 100 for value in rec[:5])
        return (f"{name} has been on a tear for {city}, topping 100 receiving yards in "
                f"{_count_word(count)} of his last five games")
    if len(rush) >= 4 and _recent_logs_complete(fact, ("rush_yds", "rushing_yards"), 4) \
            and max(rush[:4]) >= 100:
        return f"{city}'s {name} has topped 100 rushing yards in one of his last four games"
    if len(passing) >= 5 and _recent_logs_complete(fact, ("pass_yds", "passing_yards"), 5) \
            and sum(value >= 300 for value in passing[:5]) >= 2:
        count = sum(value >= 300 for value in passing[:5])
        return f"{city}'s {name} has thrown for 300 yards in {_count_word(count)} of his last five games"
    totals = fact.get("season_totals") or {}
    if totals.get("rush_yards", 0) >= 300 and totals.get("rush_touchdowns", 0) >= 3:
        return (f"{city} counters with {name}, who has rushed for {int(totals['rush_yards'])} yards and "
                f"{_count_word(totals['rush_touchdowns'])} touchdowns")
    if touchdown_series and _recent_logs_complete(
            fact, ("rec_td", "receiving_touchdowns", "rush_td", "rushing_touchdowns"), 5) \
            and sum(value > 0 for value in touchdown_series[:5]) >= 3:
        count = sum(value > 0 for value in touchdown_series[:5])
        return f"{city}'s {name} has found the end zone in {_count_word(count)} of his last five games"
    if len(carries) >= 5 and _recent_logs_complete(fact, ("carries",), 5) \
            and sum(value >= 20 for value in carries[:5]) >= 3:
        count = sum(value >= 20 for value in carries[:5])
        return f"{city}'s {name} has carried the ball 20 or more times in {_count_word(count)} of his last five games"
    if len(targets) >= 5 and _recent_logs_complete(fact, ("targets",), 5) \
            and sum(value >= 8 for value in targets[:5]) >= 3:
        count = sum(value >= 8 for value in targets[:5])
        return f"{city}'s {name} has seen at least eight targets in {_count_word(count)} of his last five games"
    latest_receiving = _latest_log_value(fact, ("rec_yds", "receiving_yards"))
    if latest_receiving is not None and latest_receiving >= 100:
        return f"{city}'s {name} is coming off a {int(latest_receiving)}-yard receiving game"
    hundred_yard_games = sum(value >= 100 for value in rec)
    recent_logs = _recent_player_logs(fact)[:5]
    recency_complete = bool(recent_logs) and _recent_logs_complete(
        fact, ("rec_yds", "receiving_yards"), len(recent_logs))
    if hundred_yard_games and recency_complete:
        count = _count_word(hundred_yard_games)
        return (f"{city}'s {name} has topped 100 receiving yards in {count} of his last "
                f"{_count_word(len(rec))} games")
    return None


def _render_player_facts(facts: list[dict[str, Any]], league: str) -> tuple[str | None, list[dict[str, Any]]]:
    rendered = []
    accepted = []
    for fact in facts:
        clause = _nba_player_clause(fact) if league == "nba" else _nfl_player_clause(fact)
        if clause:
            rendered.append(clause)
            accepted.append(fact)
    if not rendered:
        return None, []
    if len(rendered) == 1:
        return rendered[0] + ".", accepted
    if league == "nba":
        if accepted[0]["team"] == accepted[1]["team"]:
            sentence = f"{rendered[0]}, and {rendered[1]}"
        else:
            sentence = f"{rendered[0]}, while {rendered[1]}"
    else:
        if accepted[0]["team"] == accepted[1]["team"]:
            sentence = f"{rendered[0]}, and {rendered[1]}"
        else:
            sentence = f"{rendered[0]}, while {rendered[1]}"
    return sentence + ".", accepted


def _h2h(bundle: dict[str, Any]) -> dict[str, Any] | None:
    away, home = bundle["teams"][bundle["away"]], bundle["teams"][bundle["home"]]
    away_rows = {str(row["id"]): row for row in away.get("evidence", []) if row.get("opponent") == home["code"]}
    for row in home.get("evidence", []):
        game_id = str(row.get("id"))
        other = away_rows.get(game_id)
        if other and int(row.get("for", -1)) == int(other.get("against", -2)) and int(row.get("against", -1)) == int(other.get("for", -2)):
            if int(row["for"]) == int(row["against"]):
                continue
            winner = away if int(other["for"]) > int(other["against"]) else home
            return {"game_id": game_id, "date": row.get("date"),
                    "winner": winner["code"], "loser": home["code"] if winner["code"] == away["code"] else away["code"],
                    "winner_score": int(other["for"] if winner["code"] == away["code"] else row["for"]),
                    "loser_score": int(other["against"] if winner["code"] == away["code"] else row["against"]),
                    "evidence": [other, row]}
    return None


def _lead(bundle: dict[str, Any], angle: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    league = str(bundle["league"]).lower()
    away, home = bundle["teams"][bundle["away"]], bundle["teams"][bundle["home"]]
    kind = angle["kind"]
    facts = []

    def add_record(team: dict[str, Any]) -> None:
        facts.append(_team_fact(team, kind="record", description=f"{team['name']} record {_record_text(team)}"))

    def add_streak(team: dict[str, Any]) -> None:
        if int(team.get("streak_length") or 0) < 2:
            return
        result = "winning" if team.get("streak_result") == "W" else "losing"
        facts.append(_team_fact(team, kind="streak", description=f"{team['name']} {team['streak_length']}-game {result} streak"))

    if kind == "undefeated":
        leader = bundle["teams"][angle["lead_team"]]
        opponent = home if leader["code"] == away["code"] else away
        add_record(leader)
        add_record(opponent)
        add_streak(opponent)
        opponent_form = _streak_phrase(opponent)
        form_clause = f", which {opponent_form}" if opponent_form else ""
        lead = (f"{_city(leader)} puts its undefeated {_record_text(leader)} start on the line against "
                f"{_city(opponent)}{form_clause} and sits at {_record_text(opponent)}.")
        return lead, facts
    if kind == "winless_last":
        loser = next(team for team in (away, home) if team["wins"] == 0 and team["losses"] >= 4)
        rank = _rank_fact(bundle, loser)
        other = home if loser["code"] == away["code"] else away
        if other["streak_result"] == "W" and other["streak_length"] >= 2:
            add_streak(other)
            lead = (f"{_city(other)} has won {_count_word(other['streak_length'])} straight entering its matchup with "
                    f"the winless {_nickname(loser)}, who sit dead last in the {league.upper()} at {_record_text(loser)}.")
        else:
            add_record(other)
            lead = (f"The winless {_nickname(loser)} sit dead last in the {league.upper()} at {_record_text(loser)}, "
                    f"and visit {_city(other)}, where the {_nickname(other)} are {_record_text(other)}.")
        add_record(loser)
        facts.append(rank)
        return lead, facts
    if kind == "top_four":
        add_record(away)
        add_record(home)
        facts.extend(_rank_fact(bundle, team) for team in (away, home))
        lead = (f"Two of the {league.upper()}'s top four teams meet in {_city(home)}, where the "
                f"{_record_text(home)} {_nickname(home)} host the {_record_text(away)} {_nickname(away)}.")
        return lead, facts
    if kind == "streak_clash":
        winner = next(team for team in (away, home) if team.get("streak_result") == "W")
        loser = next(team for team in (away, home) if team.get("streak_result") == "L")
        add_record(away)
        add_record(home)
        add_streak(winner)
        add_streak(loser)
        lead = (f"{_city(winner)} has won {_count_word(winner['streak_length'])} straight and sits at "
                f"{_record_text(winner)}, while {_city(loser)} has dropped {_count_word(loser['streak_length'])} "
                f"in a row at {_record_text(loser)}.")
        meeting = _h2h(bundle)
        if meeting and meeting["winner"] == winner["code"]:
            date_text = _date_text(meeting.get("date"))
            if winner["code"] == home["code"] and loser["code"] == away["code"]:
                lead = (f"{_city(winner)} has won {_count_word(winner['streak_length'])} straight at "
                        f"{_record_text(winner)} and already beat {_city(loser)} "
                        f"{_number(meeting['winner_score'], 0)}-{_number(meeting['loser_score'], 0)} on {date_text}; "
                        f"the {_record_text(loser)} visitors have lost {_count_word(loser['streak_length'])} in a row.")
            else:
                lead = (f"{_city(winner)} has won {_count_word(winner['streak_length'])} straight at "
                        f"{_record_text(winner)} and already beat {_city(loser)} "
                        f"{_number(meeting['winner_score'], 0)}-{_number(meeting['loser_score'], 0)} on {date_text}; "
                        f"{_city(loser)} has dropped {_count_word(loser['streak_length'])} in a row.")
            facts.append({"id": f"head_to_head:{meeting['game_id']}", "kind": "head_to_head",
                          "description": "prior meeting result", "evidence_ids": [str(row["id"]) for row in meeting["evidence"]],
                          "evidence": meeting["evidence"]})
        return lead, facts
    if kind == "winning_streak":
        lead_team = bundle["teams"][angle["lead_team"]]
        other = home if lead_team["code"] == away["code"] else away
        add_record(other)
        add_streak(lead_team)
        lead = (f"{_city(lead_team)} brings a {_count_word(lead_team['streak_length'])}-game winning streak into "
                f"its matchup with {_city(other)}, which is {_record_text(other)}.")
        return lead, facts
    if kind == "losing_streak":
        lead_team = bundle["teams"][angle["lead_team"]]
        other = home if lead_team["code"] == away["code"] else away
        add_record(lead_team)
        add_record(other)
        add_streak(lead_team)
        lead = (f"{_city(lead_team)} has dropped {_count_word(lead_team['streak_length'])} straight at "
                f"{_record_text(lead_team)} entering its matchup with {_city(other)}, which is "
                f"{_record_text(other)}.")
        return lead, facts
    if away["streak_length"] >= 2 and away.get("streak_result") == "W":
        add_record(away)
        add_record(home)
        add_streak(away)
        lead = (f"The {_record_text(away)} {_nickname(away)} bring a {_count_word(away['streak_length'])}-game winning streak "
                f"to {_city(home)}, where the {_nickname(home)} sit at {_record_text(home)}.")
    elif away["streak_length"] >= 2 and away.get("streak_result") == "L":
        add_record(away)
        add_record(home)
        add_streak(away)
        lead = (f"The {_record_text(away)} {_nickname(away)} have dropped {_count_word(away['streak_length'])} straight "
                f"entering {_city(home)}, where the {_nickname(home)} sit at {_record_text(home)}.")
    elif home["streak_length"] >= 2 and home.get("streak_result") == "W":
        add_record(away)
        add_record(home)
        add_streak(home)
        lead = (f"The {_record_text(away)} {_nickname(away)} visit {_city(home)}, where the {_record_text(home)} "
                f"{_nickname(home)} are riding a {_count_word(home['streak_length'])}-game winning streak.")
    elif home["streak_length"] >= 2 and home.get("streak_result") == "L":
        add_record(away)
        add_record(home)
        add_streak(home)
        lead = (f"The {_record_text(away)} {_nickname(away)} visit {_city(home)}, where the {_record_text(home)} "
                f"{_nickname(home)} have dropped {_count_word(home['streak_length'])} straight.")
    else:
        add_record(away)
        add_record(home)
        home_surface = "home court" if league == "nba" else "home turf"
        lead = (f"{_city(away)} brings a {_record_text(away)} record into {_city(home)}, where the "
                f"{_record_text(home)} {_nickname(home)} look to protect {home_surface}.")
    return lead, facts


def _streak_phrase(team: dict[str, Any]) -> str | None:
    result = team.get("streak_result")
    length = int(team.get("streak_length") or 0)
    if result == "W":
        return f"won {_count_word(length)} straight" if length >= 2 else "won its last game"
    if result == "L":
        return f"lost {_count_word(length)} straight" if length >= 2 else "lost its last game"
    if result == "T":
        return f"tied {_count_word(length)} straight" if length >= 2 else "tied its last game"
    return None


def _date_text(value: str | None) -> str:
    if not value:
        return "in their last meeting"
    try:
        parsed = date.fromisoformat(str(value)[:10])
        return parsed.strftime("%b. %-d")
    except (ValueError, TypeError):
        return "in their last meeting"


def render_story(bundle: dict[str, Any], angle: dict[str, Any], player_facts: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    lead, lead_facts = _lead(bundle, angle)
    player_sentence, used_players = _render_player_facts(player_facts, str(bundle["league"]).lower())
    sentences = [lead]
    if player_sentence:
        sentences.append(player_sentence)
    story = " ".join(sentences)
    if not 1 <= len(sentences) <= 3:
        raise ValueError("story renderer must produce one to three sentences")
    if RESEARCH_JARGON.search(story):
        raise ValueError("research-only language reached story rendering")
    selected = lead_facts + used_players
    return story, selected


def _record_unrendered_players(selected_candidates: list[dict[str, Any]],
                               used_facts: list[dict[str, Any]],
                               omitted: list[dict[str, str]]) -> None:
    used_ids = {fact["id"] for fact in used_facts if fact.get("kind") == "player_form"}
    for fact in selected_candidates:
        if fact["id"] not in used_ids:
            omitted.append({"fact_id": fact["id"], "reason": "available stats did not fit a natural preview sentence"})


def generate_story(bundle: dict[str, Any]) -> dict[str, Any]:
    """Select the team story, select useful players, then return prose and its private evidence manifest."""
    if not bundle.get("as_of") or not bundle.get("start_utc"):
        raise ValueError("as_of and start_utc are required")
    if _utc(bundle["as_of"]) >= _utc(bundle["start_utc"]):
        raise ValueError("story cutoff must precede the matchup start")
    teams = bundle.get("teams") or {}
    league = str(bundle["league"]).lower()
    clean_bundle = dict(bundle)
    clean_bundle["teams"] = {}
    for code in (bundle["away"], bundle["home"]):
        team = dict(teams.get(code) or {
            "code": code, "name": _team_name(code, league), "wins": 0, "losses": 0,
            "ties": 0, "games": 0, "evidence": [],
        })
        clean_bundle["teams"][code] = _recompute_team(team, code, bundle["as_of"])
    clean_bundle["league_standings"] = [
        {**row, "evidence": _available(list(row.get("evidence") or []), bundle["as_of"])}
        for row in (bundle.get("league_standings") or [])
    ]
    if not all(clean_bundle["teams"][code].get("record_verified") for code in (bundle["away"], bundle["home"])):
        best_player = _best_player(clean_bundle.get("players", []), bundle["as_of"], str(bundle["league"]))
        player_lead = best_player["player"]["team"] if best_player and best_player["score"] >= 8 else None
        angle = {"kind": "star_performance" if player_lead else "available_player_facts",
                 "lead_team": player_lead,
                 "teams": [bundle["away"], bundle["home"]]}
        player_facts, omitted = select_players(clean_bundle, angle)
        player_sentence, selected_players = _render_player_facts(player_facts, str(bundle["league"]).lower())
        _record_unrendered_players(player_facts, selected_players, omitted)
        home_city = _city(clean_bundle["teams"][bundle["home"]])
        away_city = _city(clean_bundle["teams"][bundle["away"]])
        matchup_evidence = _available(list(bundle.get("matchup_evidence") or []), bundle["as_of"])
        matchup_sentence = f"{home_city} hosts {away_city}."
        if player_sentence and player_lead:
            story = f"{player_sentence} {matchup_sentence}"
        elif player_sentence:
            story = f"{matchup_sentence} {player_sentence}"
        else:
            story = matchup_sentence
        selected = [{"id": f"scheduled_matchup:{bundle['away']}@{bundle['home']}",
                     "kind": "scheduled_matchup", "team": None,
                     "description": f"{home_city} hosts {away_city}",
                     "evidence_ids": [str(x["id"]) for x in matchup_evidence],
                     "evidence": matchup_evidence}] + selected_players
    else:
        angle = select_story_angle(clean_bundle)
        player_facts, omitted = select_players(clean_bundle, angle)
        story, selected = render_story(clean_bundle, angle, player_facts)
        _record_unrendered_players(player_facts,
                                   [fact for fact in selected if fact.get("kind") == "player_form"], omitted)
    manifest = {
        "selected_facts": [
            {key: value for key, value in fact.items() if key != "stats" and key != "season_totals"}
            for fact in selected
        ],
        "omitted_facts": omitted,
    }
    return {"story": story, "angle": angle, "manifest": manifest}


def _db_team_standings(connection: sqlite3.Connection, league: str, season: int, as_of: str,
                       target_game_id: str | None = None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    league = league.lower()
    is_nba = league == "nba"
    schedule = "nba_schedule" if is_nba else "nfl_schedule"
    roster = "nba_teams" if is_nba else "nfl_teams"
    try:
        roster_rows = list(connection.execute(f"SELECT * FROM {roster} WHERE season=?", (season,)))
        if is_nba:
            rows = list(connection.execute(
                """SELECT game_id,game_date,home_team,away_team,home_score,away_score,ingested_at
                   FROM nba_schedule WHERE season=? AND season_type='REG'
                   AND home_score IS NOT NULL AND away_score IS NOT NULL
                   AND COALESCE(sub_label,'') NOT IN ('Quarterfinal','Semifinal')
                   AND game_date<=? AND julianday(ingested_at)<=julianday(?)
                   AND (? IS NULL OR game_id<>?) ORDER BY game_date,game_id""",
                (season, _utc(as_of).date().isoformat(), as_of, target_game_id, target_game_id)))
            code_col, name_col = "team", "team_name"
        else:
            rows = list(connection.execute(
                """SELECT game_id,gameday AS game_date,home_team,away_team,home_score,away_score,ingested_at
                   FROM nfl_schedule WHERE season=? AND game_type='REG'
                   AND home_score IS NOT NULL AND away_score IS NOT NULL
                   AND gameday<=? AND julianday(ingested_at)<=julianday(?)
                   AND (? IS NULL OR game_id<>?) ORDER BY gameday,week,game_id""",
                (season, _utc(as_of).date().isoformat(), as_of, target_game_id, target_game_id)))
            code_col, name_col = "team", "team_name"
    except sqlite3.OperationalError:
        return {}, []
    expected = LEAGUE_SIZE[league]
    if len(roster_rows) != expected:
        return {}, []
    teams = {}
    for row in roster_rows:
        item = dict(row)
        code = str(item.get(code_col) or "")
        teams[code] = {"code": code, "name": item.get(name_col) or _team_name(code, league),
                       "wins": 0, "losses": 0, "ties": 0, "for": 0, "against": 0,
                       "games": 0, "results": [], "evidence": []}
    for row in rows:
        item = dict(row)
        for code, score, other_score, opponent in (
                (item["home_team"], int(item["home_score"]), int(item["away_score"]), item["away_team"]),
                (item["away_team"], int(item["away_score"]), int(item["home_score"]), item["home_team"])):
            if code not in teams:
                continue
            record = teams[code]
            result = "W" if score > other_score else "L" if score < other_score else "T"
            record[{"W": "wins", "L": "losses", "T": "ties"}[result]] += 1
            record["for"] += score
            record["against"] += other_score
            record["games"] += 1
            record["results"].append(result)
            record["evidence"].append({
                "id": str(item["game_id"]), "available_at": _iso_utc(item["ingested_at"]),
                "date": str(item["game_date"])[:10], "opponent": opponent,
                "result": result, "for": score, "against": other_score,
            })
    for team in teams.values():
        team["streak_result"] = team["results"][-1] if team["results"] else None
        team["streak_length"] = 0
        for result in reversed(team["results"]):
            if result != team["streak_result"]:
                break
            team["streak_length"] += 1
        team["win_pct"] = ((team["wins"] + 0.5 * team["ties"]) / team["games"] if team["games"] else 0.0)
        team["differential"] = ((team["for"] - team["against"]) / team["games"] if team["games"] else 0.0)
    ranked = sorted(teams.values(), key=lambda t: (-t["win_pct"], -t["differential"], t["code"]))
    for rank, team in enumerate(ranked, 1):
        team["rank"] = rank
    return teams, ranked


def _db_player_facts(connection: sqlite3.Connection, league: str, season: int,
                     away: str, home: str, as_of: str, target_game_id: str | None,
                     team_game_counts: dict[str, int]) -> list[dict[str, Any]]:
    try:
        rows = list(connection.execute(
            """SELECT l.id,l.player_id,p.name,l.league,l.season,l.game_id,l.game_date,l.team,
                      l.stats,l.ingested_at,l.game_type
               FROM player_game_logs l LEFT JOIN players p ON p.id=l.player_id
               WHERE l.league=? AND l.season=? AND l.team IN (?,?)
                 AND l.game_date<=? AND julianday(l.ingested_at)<=julianday(?)
                 AND (? IS NULL OR l.game_id<>?)
               ORDER BY l.game_date DESC,l.id DESC""",
            (league, season, away, home, _utc(as_of).date().isoformat(), as_of,
             target_game_id, target_game_id)))
    except sqlite3.OperationalError:
        return []
    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["player_id"] is None or not row["name"]:
            continue
        try:
            stats = json.loads(row["stats"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        fact = {
            "id": str(row["id"]), "available_at": _iso_utc(row["ingested_at"]),
            "date": str(row["game_date"])[:10], "game_id": str(row["game_id"]), "stats": stats,
        }
        fact["_team"] = str(row["team"])
        fact["_name"] = str(row["name"])
        by_player[str(row["player_id"])].append(fact)
    players = []
    for player_id, logs in by_player.items():
        team_codes = {row["_team"] for row in logs}
        # A player who changed teams is reported only with the team from the latest available log.
        team = logs[0]["_team"]
        logs = [row for row in logs if row["_team"] == team]
        for row in logs:
            row.pop("_team", None)
            row.pop("_name", None)
        name = next(row["name"] for row in rows if str(row["player_id"]) == player_id)
        players.append({
            "player_id": player_id, "name": name, "team": team, "league": league,
            "evidence": logs[:5], "season_logs": logs,
            "season_totals_complete": (
                bool(team_game_counts.get(team)) and len(logs) == team_game_counts[team]
                and len({row["game_id"] for row in logs}) == len(logs)
            ),
        })
    return players


def collect_story_facts(db_path: str | Path, game: dict[str, Any], *, as_of: str) -> dict[str, Any]:
    """Read cutoff-safe standings and recent player logs from the existing SQLite database.

    `game` supplies the scheduled matchup identity and start time, normally from a
    previously captured schedule row. This function never updates or creates tables.
    """
    if _utc(as_of) >= _utc(game["start_utc"]):
        raise ValueError("story cutoff must precede the matchup start")
    league = str(game["league"]).lower()
    if league not in LEAGUE_SIZE:
        raise ValueError(f"unsupported league: {league}")
    path = Path(db_path).resolve()
    uri = path.as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        teams, standings = _db_team_standings(
            connection, league, int(game["season"]), as_of, game.get("game_id"))
        players = _db_player_facts(
            connection, league, int(game["season"]), game["away"], game["home"], as_of,
            game.get("game_id"), {code: row["games"] for code, row in teams.items()})
    finally:
        connection.close()
    return {
        "league": league, "season": int(game["season"]), "game_id": game.get("game_id"),
        "away": game["away"], "home": game["home"], "start_utc": _iso_utc(game["start_utc"]),
        "as_of": _iso_utc(as_of), "teams": {code: teams[code] for code in (game["away"], game["home"]) if code in teams},
        "league_standings": standings, "players": players,
        "source": {"database": str(path), "mode": "read_only", "facts_are_cutoff_filtered": True},
    }
