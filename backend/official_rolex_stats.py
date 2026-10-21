"""Official Rolex Shanghai Masters match-stat pages: labelled per-player aces and double faults (research, CP4).

The official page prints each player's name above the stat columns, so the labels come from the page itself.
Columns are read in the page's order: first listed name = left column.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ingest_provider_match_stats import parse_stats_text


def parse_official_text(text: str) -> Dict[str, Any]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    names: List[str] = []
    header = next((i for i, l in enumerate(lines) if l == "SERVICE STATS"), None)
    if header is not None:
        for line in lines[header + 1: header + 4]:
            if re.fullmatch(r"\d+|Aces|Double Faults|Break Points Won|\S+/\S+", line) or len(names) == 2:
                break
            names.append(line)
    stats = parse_stats_text(text)
    return {"names": names if len(names) == 2 else None, **stats}


def exact_pair_match(names: List[str], espn_games: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ESPN games whose two player names equal the official pair in either order (exact, case-insensitive)."""
    wanted = {n.strip().lower() for n in names}
    hits = []
    for game in espn_games:
        pair = {(game.get("home") or {}).get("name", "").strip().lower(),
                (game.get("away") or {}).get("name", "").strip().lower()}
        if pair == wanted:
            hits.append(game)
    return hits
