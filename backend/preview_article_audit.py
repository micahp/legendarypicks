"""Independent checks on a rendered preview.

The audit recomputes facts from the raw bundle. It does not trust the candidate
numbers it is checking. Any problem listed here blocks review.
"""
from __future__ import annotations

from typing import Any, Dict, List

from preview_angle_candidates import before_cutoff, team_momentum

# Phrases that need a real stake or a long record, never an early-season sample.
EARLY_SEASON_FORBIDDEN = (
    "season-defining", "contender", "must-win", "playoff implications",
    "clinch", "title favorite",
)
# Never let a text state that a listed player will take part.
PARTICIPATION_FORBIDDEN = ("will play", "will start", "is expected to play",
                           "is guaranteed")


def _texts(article: Dict[str, Any]) -> List[str]:
    parts = [article["headline"], article["deck"]]
    parts += [section["paragraph"] for section in article["sections"]]
    return [p for p in parts if p]


def audit(bundle: Dict[str, Any], candidates: List[Dict[str, Any]],
          article: Dict[str, Any]) -> List[str]:
    problems: List[str] = []
    as_of = bundle["as_of"]
    text = " ".join(_texts(article)).lower()
    by_id = {c["id"]: c for c in candidates}
    plan = article["story_plan"]

    # 1. Every cited fact must be visible at the cutoff.
    for candidate in candidates:
        for item in candidate["evidence"]:
            if not before_cutoff(item, as_of):
                problems.append("evidence after cutoff: " + item["id"])

    # 2. Plan must cite candidates that exist.
    for angle in [plan["lead_angle"]] + plan["supporting_angles"]:
        if angle and angle not in by_id:
            problems.append("plan cites unknown angle: " + angle)

    # 3. Streak claims are recomputed from the raw results.
    for candidate in candidates:
        if candidate["kind"] != "team_momentum":
            continue
        fresh = team_momentum(candidate["team"],
                              bundle["results"][candidate["team"]], as_of)
        if fresh is None or fresh["claim"] != candidate["claim"]:
            problems.append("streak does not match results: " + candidate["id"])

    # 4. Draft guard. A drafted player is never called undrafted.
    players = bundle.get("players", {})
    any_draft = any(p.get("draft") for p in players.values())
    if "undrafted" in text and any_draft:
        problems.append("text says undrafted but a draft record exists")
    if "overall" in text and not any_draft:
        problems.append("text cites a draft position with no draft record")

    # 5. National telecast claims need national = true at the cutoff.
    broadcast = bundle.get("broadcast") or {}
    if "nationally" in text and not (
            broadcast.get("national") is True and
            before_cutoff(broadcast, as_of)):
        problems.append("text says nationally televised without evidence")

    # 6. Points claims match the three most recent visible logs.
    for candidate in candidates:
        if candidate["kind"] != "emerging_player":
            continue
        logs = sorted(
            [g for g in players[candidate["player_id"]].get("game_logs", [])
             if before_cutoff(g, as_of)],
            key=lambda g: g["date"])[-3:]
        if [g["points"] for g in logs] != candidate["points"]:
            problems.append("points do not match logs: " + candidate["id"])

    # 7. Availability: never assert participation.
    for word in PARTICIPATION_FORBIDDEN:
        if word in text:
            problems.append("text asserts participation: " + word)

    # 8. Early-season text must avoid stake and clinch language.
    if plan["season_stage"]["phase"] == "early_regular_season":
        for word in EARLY_SEASON_FORBIDDEN:
            if word in text:
                problems.append("early-season text uses: " + word)

    return problems
