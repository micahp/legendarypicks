"""Independent mechanical checks for the deterministic story templates.

This audits the renderer's prose against the unrendered fact bundle. It does not
use the renderer's selected numeric values as the source of truth.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from story_engine import LEAGUE_SIZE, LEAGUE_TEAM_NAMES, TEAM_CITIES


COUNT_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
               "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _input_evidence(facts: dict[str, Any]):
    for team in (facts.get("teams") or {}).values():
        yield from team.get("evidence") or []
    for team in facts.get("league_standings") or []:
        yield from team.get("evidence") or []
    for player in facts.get("players") or []:
        yield from player.get("evidence") or []
        yield from player.get("season_logs") or []
    yield from facts.get("matchup_evidence") or []


def _prior_evidence(facts: dict[str, Any]):
    for team in (facts.get("teams") or {}).values():
        yield from team.get("evidence") or []
    for team in facts.get("league_standings") or []:
        yield from team.get("evidence") or []
    for player in facts.get("players") or []:
        yield from player.get("evidence") or []
        yield from player.get("season_logs") or []


def _selected_rows_linked(selected: list[dict], facts: dict[str, Any]) -> bool:
    available_rows: dict[str, list[dict]] = {}
    for row in _input_evidence(facts):
        available_rows.setdefault(str(row.get("id")), []).append(row)
    standings_ids = {str(row.get("id")) for team in facts.get("league_standings") or []
                     for row in team.get("evidence") or []}
    for fact in selected:
        ids = {str(value) for value in fact.get("evidence_ids") or []}
        evidence = fact.get("evidence") or []
        if not ids or not evidence or ids != {str(row.get("id")) for row in evidence}:
            return False
        for row in evidence:
            source_ids = {str(value) for value in row.get("source_ids") or []}
            if source_ids:
                if not source_ids.issubset(standings_ids):
                    return False
            elif row not in available_rows.get(str(row.get("id")), []):
                return False
    return True


def _outcomes(rows: list[dict], cutoff: str) -> list[str]:
    as_of = _time(cutoff)
    eligible = [row for row in rows if row.get("available_at") and _time(row["available_at"])
                and as_of and _time(row["available_at"]) <= as_of]
    eligible.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("id") or "")))
    return ["W" if row["for"] > row["against"] else "L" if row["for"] < row["against"] else "T"
            for row in eligible if row.get("for") is not None and row.get("against") is not None]


def _record_and_streak_facts_recompute(selected: list[dict], facts: dict[str, Any],
                                       cutoff: str) -> bool:
    for fact in selected:
        if fact.get("kind") not in {"record", "streak"}:
            continue
        team = str(fact.get("team") or "")
        source_rows = ((facts.get("teams", {}).get(team) or {}).get("evidence") or [])
        expected_ids = {str(row.get("id")) for row in source_rows
                        if row.get("available_at") and _time(row["available_at"])
                        and _time(row["available_at"]) <= _time(cutoff)}
        selected_ids = {str(row.get("id")) for row in fact.get("evidence") or []}
        if not expected_ids or selected_ids != expected_ids:
            return False
        outcomes = _outcomes(source_rows, cutoff)
        if fact.get("kind") == "record":
            record = f"{outcomes.count('W')}-{outcomes.count('L')}"
            if outcomes.count("T"):
                record += f"-{outcomes.count('T')}"
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
            match = re.search(r"(\d+)-game (winning|losing|tied) streak$",
                              str(fact.get("description", "")))
            if length < 2 or not direction or not match or int(match[1]) != length \
                    or match[2] != direction:
                return False
    return True


def _nearest_team(story: str, offset: int, facts: dict[str, Any]) -> str | None:
    names = LEAGUE_TEAM_NAMES.get(str(facts.get("league", "")).lower(), {})
    sentence_start = max(story.rfind(mark, 0, offset) for mark in ".!?;") + 1
    sentence_ends = [position for position in (story.find(mark, offset) for mark in ".!?;")
                     if position >= 0]
    sentence_end = min(sentence_ends, default=len(story))
    sentence = story[sentence_start:sentence_end]
    relative_offset = offset - sentence_start
    candidates = []
    number = re.match(r"\d{1,2}-\d{1,2}(?:-\d{1,2})?", story[offset:])
    token_end = relative_offset + len(number.group(0)) if number else relative_offset
    for code in (facts.get("teams") or {}):
        full = names.get(str(code), "")
        aliases = {TEAM_CITIES.get(str(code), ""), full,
                   full.rsplit(" ", 1)[-1] if full else ""}
        for alias in (value for value in aliases if value):
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                                     sentence, re.IGNORECASE):
                before = match.end() <= relative_offset
                gap = (sentence[match.end():relative_offset] if before
                       else sentence[token_end:match.start()])
                distance = abs(match.start() - relative_offset)
                if distance <= 65:
                    candidates.append((len(re.findall(r"\w+", gap)), 0 if before else 1,
                                       distance, str(code)))
    if not candidates:
        return None
    best = min(candidate[:3] for candidate in candidates)
    codes = {code for words, direction, distance, code in candidates
             if (words, direction, distance) == best}
    return next(iter(codes)) if len(codes) == 1 else None


def _record_and_streak_claims_match(story: str, facts: dict[str, Any], selected: list[dict]) -> bool:
    records = {}
    for fact in selected:
        if fact.get("kind") == "record":
            source_rows = ((facts.get("teams", {}).get(str(fact.get("team"))) or {}).get("evidence") or [])
            outcomes = _outcomes(source_rows, facts["as_of"])
            value = f"{outcomes.count('W')}-{outcomes.count('L')}"
            if outcomes.count("T"):
                value += f"-{outcomes.count('T')}"
            records[str(fact.get("team"))] = value
    for match in re.finditer(r"(?<!\d)(\d{1,2}-\d{1,2}(?:-\d{1,2})?)(?!\d)", story):
        team = _nearest_team(story, match.start(), facts)
        if team is None or records.get(team) != match[1]:
            return False

    count_pattern = r"one|two|three|four|five|six|seven|eight|nine|ten|\d+"
    patterns = (
        re.compile(rf"\b(?P<count>{count_pattern})-game (?P<direction>winning|losing|tied) streak\b", re.I),
        re.compile(rf"\b(?P<verb>won|lost|dropped|tied) (?P<count>{count_pattern}) (?:straight|in a row)\b", re.I),
        re.compile(r"\b(?P<verb>won|lost|dropped|tied) its last game\b", re.I),
    )
    for pattern in patterns:
        for match in pattern.finditer(story):
            team = _nearest_team(story, match.start(), facts)
            outcomes = _outcomes((facts.get("teams", {}).get(team) or {}).get("evidence") or [],
                                 facts["as_of"]) if team else []
            if not outcomes:
                return False
            result = ("W" if match.groupdict().get("direction", "").lower() == "winning" else
                      "L" if match.groupdict().get("direction", "").lower() == "losing" else
                      "T" if match.groupdict().get("direction", "").lower() == "tied" else
                      {"won": "W", "lost": "L", "dropped": "L", "tied": "T"}[match["verb"].lower()])
            count_word = match.groupdict().get("count")
            count = COUNT_WORDS.get(count_word.lower(), int(count_word) if count_word.isdigit() else None) \
                if count_word else 1
            if count is None or len(outcomes) < count or outcomes[-count:] != [result] * count:
                return False
    return True


def _head_to_head_claims_recompute(story: str, facts: dict[str, Any], selected: list[dict]) -> bool:
    prior_meetings = [fact for fact in selected if fact.get("kind") == "head_to_head"]
    claims = list(re.finditer(
        r"\balready beat\s+(?P<loser>.+?)\s+(?P<winner_score>\d+)-(?P<loser_score>\d+)\s+"
        r"on (?P<date>[A-Z][a-z]{2}\.\s+\d{1,2})\b", story, re.I))
    if len(prior_meetings) != len(claims):
        return False
    for fact, claim in zip(prior_meetings, claims):
        evidence = fact.get("evidence") or []
        evidence_ids = {str(row.get("id")) for row in evidence}
        if len(evidence) != 2 or len(evidence_ids) != 1:
            return False
        game_id = next(iter(evidence_ids))
        team_rows = []
        for code in (facts.get("away"), facts.get("home")):
            row = next((item for item in (facts.get("teams", {}).get(code) or {}).get("evidence") or []
                        if str(item.get("id")) == game_id), None)
            if row is not None:
                team_rows.append((str(code), row))
        if len(team_rows) != 2:
            return False
        first, second = team_rows
        if first[1].get("opponent") != second[0] or second[1].get("opponent") != first[0]:
            return False
        first_score, second_score = first[1].get("for"), second[1].get("for")
        if first_score is None or second_score is None or first_score == second_score:
            return False
        winner, loser = (first, second) if first_score > second_score else (second, first)
        winner_score, loser_score = int(winner[1]["for"]), int(loser[1]["for"])
        expected_city = TEAM_CITIES.get(loser[0], "")
        date = str(winner[1].get("date") or "")[:10]
        try:
            expected_date = datetime.fromisoformat(date).strftime("%b. %-d")
        except ValueError:
            return False
        if (not expected_city or claim.group("loser").strip().lower() != expected_city.lower()
                or int(claim.group("winner_score")) != winner_score
                or int(claim.group("loser_score")) != loser_score
                or claim.group("date").replace(" ", "") != expected_date.replace(" ", "")):
            return False
    return True


def _rank_claims_recompute(facts: dict[str, Any], selected: list[dict]) -> bool:
    rank_facts = [fact for fact in selected if fact.get("kind") == "league_rank"]
    story_has_rank_claim = bool(re.search(r"\bdead last\b|\btop four\b", facts.get("story", ""), re.I))
    if not rank_facts:
        return not story_has_rank_claim
    league = str(facts.get("league", "")).lower()
    rows = facts.get("league_standings") or []
    expected = LEAGUE_SIZE.get(league)
    if expected is None or len(rows) != expected or len({r.get("code") for r in rows}) != expected:
        return False
    ranked = []
    evidence_ids = set()
    for team in rows:
        evidence = [row for row in (team.get("evidence") or [])
                    if row.get("available_at") and _time(row["available_at"])
                    and _time(row["available_at"]) <= _time(facts["as_of"])]
        outcomes = []
        points_for = points_against = 0
        for row in evidence:
            if row.get("for") is None or row.get("against") is None:
                continue
            scored, allowed = int(row["for"]), int(row["against"])
            outcomes.append("W" if scored > allowed else "L" if scored < allowed else "T")
            points_for += scored
            points_against += allowed
            evidence_ids.add(str(row.get("id")))
        if not outcomes or len(outcomes) != int(team.get("games") or 0):
            return False
        wins, losses, ties = outcomes.count("W"), outcomes.count("L"), outcomes.count("T")
        ranked.append({"code": str(team.get("code")),
                       "win_pct": (wins + 0.5 * ties) / len(outcomes),
                       "differential": (points_for - points_against) / len(outcomes)})
    ranked.sort(key=lambda row: (-row["win_pct"], -row["differential"], row["code"]))
    for fact in rank_facts:
        rank = next((index for index, row in enumerate(ranked, 1) if row["code"] == fact.get("team")), None)
        source_ids = {str(value) for row in fact.get("evidence") or []
                      for value in row.get("source_ids", [])}
        if rank != fact.get("rank") or fact.get("league_size") != expected or source_ids != evidence_ids:
            return False
    story = str(facts.get("story") or "")
    if re.search(r"\bdead last\b", story, re.I):
        team = _nearest_team(story, re.search(r"\bdead last\b", story, re.I).start(), facts)
        if not any(fact.get("team") == team and fact.get("rank") == expected for fact in rank_facts):
            return False
    if re.search(r"\btop four\b", story, re.I):
        if sum(fact.get("rank", expected + 1) <= 4 for fact in rank_facts) < 2:
            return False
    return True


def _player_rows(player: dict, cutoff: str) -> list[dict]:
    limit = _time(cutoff)
    rows = [row for row in player.get("evidence") or [] if row.get("available_at")
            and _time(row["available_at"]) and limit and _time(row["available_at"]) <= limit]
    return sorted(rows, key=lambda row: (str(row.get("date") or ""),
                                         _time(row.get("available_at"))), reverse=True)[:5]


def _stat(rows: list[dict], key: str) -> list[float]:
    return [float(row["stats"][key]) for row in rows
            if row.get("stats") and row["stats"].get(key) is not None]


def _stats_complete(rows: list[dict], keys: tuple[str, ...], count: int) -> bool:
    return len(rows) >= count and all(
        any((row.get("stats") or {}).get(key) is not None for key in keys)
        for row in rows[:count])


def _shown(value: float, decimals: int = 1) -> str:
    rounded = round(float(value), decimals)
    return str(int(rounded)) if rounded.is_integer() else f"{rounded:.{decimals}f}"


def _count_is(word: str, count: int) -> bool:
    parsed = COUNT_WORDS.get(word.lower())
    if parsed is None and word.isdigit():
        parsed = int(word)
    return parsed == count


def _player_claim_matches(story: str, facts: dict[str, Any], fact: dict) -> bool:
    identity = str(fact.get("id", "")).partition(":")[2]
    player = next((row for row in facts.get("players") or []
                   if str(row.get("player_id", row.get("name"))) == identity
                   and row.get("name") == fact.get("player") and row.get("team") == fact.get("team")), None)
    if player is None:
        return False
    parts = re.split(r"\s+while\s+|,\s+and\s+", story, flags=re.I)
    clause = next((part for part in parts if str(fact.get("player", "")).lower() in part.lower()), "")
    if not clause:
        return False
    rows = _player_rows(player, facts["as_of"])
    league = str(facts.get("league", "")).lower()
    if league == "nba":
        points, assists, rebounds = (_stat(rows, key) for key in ("PTS", "AST", "REB"))
        match = re.search(r"has scored (\d+) and (\d+) in his last two", clause, re.I)
        if match:
            return (_stats_complete(rows, ("PTS", "points"), 2) and len(points) >= 2
                    and [round(v) for v in points[:2]] == [int(match[1]), int(match[2])])
        match = re.search(r"has scored at least (\d+) in each of his last five, including a (\d+)-point night", clause, re.I)
        if match:
            return (_stats_complete(rows, ("PTS", "points"), 5) and len(points) >= 5
                    and all(v >= int(match[1]) for v in points[:5])
                    and round(max(points[:5])) == int(match[2]))
        match = re.search(r"is averaging ([0-9.]+) points and ([0-9.]+) assists over his last five games, including a (\d+)-point (?:outing|night)", clause, re.I)
        if match:
            return (_stats_complete(rows, ("PTS", "points"), 5)
                    and _stats_complete(rows, ("AST", "assists"), 5)
                    and len(points) >= 5 and len(assists) >= 5
                    and _shown(sum(points[:5]) / 5) == match[1]
                    and _shown(sum(assists[:5]) / 5) == match[2]
                    and round(max(points[:5])) == int(match[3]))
        match = re.search(r"has put up ([0-9, ]+(?: and [0-9]+)?) in (\w+) of his last five", clause, re.I)
        if match:
            values = [int(value) for value in re.findall(r"\d+", match[1])]
            actual = [int(v) for v in points[:5] if v >= 35]
            return (_stats_complete(rows, ("PTS", "points"), 5)
                    and actual == values and _count_is(match[2], len(actual)))
        match = re.search(r"is averaging ([0-9.]+) points and ([0-9.]+) assists over his last five", clause, re.I)
        if match:
            return (_stats_complete(rows, ("PTS", "points"), 5)
                    and _stats_complete(rows, ("AST", "assists"), 5)
                    and len(points) >= 5 and len(assists) >= 5
                    and _shown(sum(points[:5]) / 5) == match[1]
                    and _shown(sum(assists[:5]) / 5) == match[2])
        match = re.search(r"has scored at least 23 in (each|one|two|three|four|five) of his last five", clause, re.I)
        if match:
            expected = 5 if match[1].lower() == "each" else COUNT_WORDS.get(match[1].lower())
            return (_stats_complete(rows, ("PTS", "points"), 5)
                    and len(points) >= 5 and sum(v >= 23 for v in points[:5]) == expected)
        match = re.search(r"has scored 20 or more in (each|one|two|three|four) of his last four, including ([\d, ]+)", clause, re.I)
        if match:
            recent = points[:4]
            values = [int(v) for v in re.findall(r"\d+", match[2])]
            expected = 4 if match[1].lower() == "each" else COUNT_WORDS.get(match[1].lower())
            return _stats_complete(rows, ("PTS", "points"), 4) and len(recent) == 4 \
                and sum(v >= 20 for v in recent) == expected \
                and [int(v) for v in recent if v >= 20] == values
        match = re.search(r"is averaging ([0-9.]+) (assists|rebounds) over his last five", clause, re.I)
        if match:
            values = assists if match[2].lower() == "assists" else rebounds
            keys = ("AST", "assists") if match[2].lower() == "assists" else ("REB", "rebounds")
            return _stats_complete(rows, keys, 5) and len(values) >= 5 \
                and _shown(sum(values[:5]) / 5) == match[1]
        return False

    receiving, rushing, passing = (_stat(rows, key) for key in ("rec_yds", "rush_yds", "pass_yds"))
    match = re.search(r"topping 100 receiving yards in (\w+) of his last five games", clause, re.I)
    if match:
        count = sum(value >= 100 for value in receiving[:5])
        return _stats_complete(rows, ("rec_yds", "receiving_yards"), 5) \
            and count >= 3 and _count_is(match[1], count)
    match = re.search(r"has topped 100 rushing yards in one of his last four games", clause, re.I)
    if match:
        return _stats_complete(rows, ("rush_yds", "rushing_yards"), 4) \
            and any(value >= 100 for value in rushing[:4])
    match = re.search(r"has thrown for 300 yards in (\w+) of his last five games", clause, re.I)
    if match:
        count = sum(value >= 300 for value in passing[:5])
        return _stats_complete(rows, ("pass_yds", "passing_yards"), 5) \
            and count >= 2 and _count_is(match[1], count)
    match = re.search(r"has rushed for (\d+) yards and (\w+) touchdowns", clause, re.I)
    if match and player.get("season_totals_complete"):
        totals = {"rush_yds": 0.0, "rush_td": 0.0}
        cutoff = _time(facts["as_of"])
        for row in player.get("season_logs") or []:
            available = _time(row.get("available_at"))
            if not available or not cutoff or available > cutoff:
                continue
            stats = row.get("stats") or {}
            totals["rush_yds"] += float(stats.get("rush_yds") or 0)
            totals["rush_td"] += float(stats.get("rush_td") or 0)
        shown_tds = COUNT_WORDS.get(match[2].lower())
        if shown_tds is None and match[2].isdigit():
            shown_tds = int(match[2])
        return int(totals["rush_yds"]) == int(match[1]) and int(totals["rush_td"]) == shown_tds
    match = re.search(r"has found the end zone in (\w+) of his last five games", clause, re.I)
    if match:
        count = sum(float((row.get("stats") or {}).get("rec_td") or 0)
                    + float((row.get("stats") or {}).get("rush_td") or 0) > 0
                    for row in rows[:5])
        return _stats_complete(rows, ("rec_td", "receiving_touchdowns", "rush_td", "rushing_touchdowns"), 5) \
            and count >= 3 and _count_is(match[1], count)
    carries = _stat(rows, "carries")
    match = re.search(r"has carried the ball 20 or more times in (\w+) of his last five games", clause, re.I)
    if match:
        count = sum(value >= 20 for value in carries[:5])
        return _stats_complete(rows, ("carries",), 5) and count >= 3 and _count_is(match[1], count)
    targets = _stat(rows, "targets")
    match = re.search(r"has seen at least eight targets in (\w+) of his last five games", clause, re.I)
    if match:
        count = sum(value >= 8 for value in targets[:5])
        return _stats_complete(rows, ("targets",), 5) and count >= 3 and _count_is(match[1], count)
    match = re.search(r"is coming off a (\d+)-yard receiving game", clause, re.I)
    if match:
        if not rows:
            return False
        latest_stats = rows[0].get("stats") or {}
        latest = next((latest_stats[key] for key in ("rec_yds", "receiving_yards")
                       if latest_stats.get(key) is not None), None)
        return latest is not None and int(round(float(latest))) == int(match[1])
    match = re.search(r"has topped 100 receiving yards in (\w+) of his last (\w+) games", clause, re.I)
    if match:
        count = sum(value >= 100 for value in receiving)
        return (_stats_complete(rows, ("rec_yds", "receiving_yards"), len(rows))
                and count > 0 and _count_is(match[1], count) and _count_is(match[2], len(rows)))
    return False


def _player_attribution_matches(story: str, facts: dict[str, Any], selected: list[dict]) -> bool:
    matchup = {str(code) for code in (facts.get("teams") or {})}
    league_names = LEAGUE_TEAM_NAMES.get(str(facts.get("league", "")).lower(), {})
    for fact in selected:
        if fact.get("kind") != "player_form":
            continue
        player, code = str(fact.get("player") or ""), str(fact.get("team") or "")
        if not player or code not in matchup:
            return False
        clause = next((part for part in re.split(r"\s+while\s+|,\s+and\s+", story, flags=re.I)
                       if player.lower() in part.lower()), "")
        if not clause:
            return False
        city = TEAM_CITIES.get(code, "")
        full = league_names.get(code, "")
        nickname = full.rsplit(" ", 1)[-1] if full else ""
        same_city = any(other != code and TEAM_CITIES.get(other) == city for other in matchup)
        options = (full, nickname) if same_city else (city, full, nickname)
        if not any(value and value.lower() in clause.lower() for value in options):
            return False
    return True


def audit_story(result: dict[str, Any], facts: dict[str, Any]) -> dict[str, bool]:
    """Recompute every supported template claim and return the rubric audit gates."""
    story = str(result.get("story") or "")
    manifest = result.get("manifest") or {}
    selected = manifest.get("selected_facts") or []
    cutoff = _time(facts.get("as_of"))
    kickoff = _time(facts.get("start_utc"))
    evidence = list(_input_evidence(facts))
    cutoff_safe = bool(cutoff and kickoff and cutoff < kickoff) and all(
        row.get("available_at") and _time(row["available_at"]) and _time(row["available_at"]) <= cutoff
        for row in evidence
    )
    target = str(facts.get("game_id") or "")
    target_absent = all(str(row.get("game_id") or row.get("id") or "") != target
                        for row in _prior_evidence(facts))
    player_facts = [fact for fact in selected if fact.get("kind") == "player_form"]
    player_claims = all(_player_claim_matches(story, facts, fact) for fact in player_facts)
    return {
        "nonempty_story": bool(story.strip()),
        "selected_facts_have_linked_source_rows": _selected_rows_linked(selected, facts),
        "team_record_and_streak_claims_recompute": (
            _record_and_streak_facts_recompute(selected, facts, facts.get("as_of", ""))
            and _record_and_streak_claims_match(story, facts, selected)),
        "head_to_head_claims_recompute": _head_to_head_claims_recompute(story, facts, selected),
        "league_rank_claims_recompute": _rank_claims_recompute({**facts, "story": story}, selected),
        "player_stat_claims_recompute": player_claims,
        "player_team_attribution_matches_prose": _player_attribution_matches(story, facts, selected),
        "all_input_evidence_is_cutoff_safe": cutoff_safe,
        "target_game_absent_from_prior_evidence": target_absent,
        "player_team_codes_match_matchup": all(
            fact.get("team") in {facts.get("away"), facts.get("home")} for fact in player_facts),
    }
