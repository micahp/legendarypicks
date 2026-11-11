"""Season-stage context for enhanced pregame previews.

Pure functions. No I/O, no network, no model calls.

The stage adapters are examples, not universal rules. Each competition needs
its own adapter. A league without an adapter gets phase "unknown", and the
previews must not make stage claims for it.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Thresholds per competition. Add a league here only with an agreed rule.
STAGE_ADAPTERS: Dict[str, Dict[str, Any]] = {
    # The NBA regular season is 82 games. "Early" means the first 20.
    "nba": {"early_max_games_completed": 20},
}


def season_stage(league: str, games_completed: Optional[int],
                 games_scheduled: Optional[int]) -> Dict[str, Any]:
    """Classify the season stage, or say it is unknown. Never guess."""
    adapter = STAGE_ADAPTERS.get(league)
    if adapter is None:
        return {
            "phase": "unknown",
            "games_completed": games_completed,
            "games_scheduled": games_scheduled,
            "caveat": "no season-stage adapter for {}".format(league),
        }
    if games_completed is None or games_scheduled is None:
        return {
            "phase": "unknown",
            "games_completed": games_completed,
            "games_scheduled": games_scheduled,
            "caveat": "season counts missing",
        }
    if games_completed <= adapter["early_max_games_completed"]:
        return {
            "phase": "early_regular_season",
            "games_completed": games_completed,
            "games_scheduled": games_scheduled,
            "caveat": "limited sample",
        }
    return {
        "phase": "regular_season",
        "games_completed": games_completed,
        "games_scheduled": games_scheduled,
        # Playoff and standings stakes are not modeled yet.
        "caveat": "playoff and standings stakes not modeled",
    }
