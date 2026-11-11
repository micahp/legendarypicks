"""Pick the lead and supporting angles for one preview.

Pure and deterministic. The same bundle always gives the same plan.
"""
from __future__ import annotations

from typing import Any, Dict, List

from preview_context import season_stage

MAX_SUPPORTING = 3


def build_plan(bundle: Dict[str, Any],
               candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    game = bundle["game"]
    season = bundle.get("season", {})
    stage = season_stage(game["league"], season.get("games_completed"),
                         season.get("games_scheduled"))
    lead = candidates[0] if candidates else None
    supporting: List[Dict[str, Any]] = []
    seen_kinds = {lead["kind"]} if lead else set()
    for candidate in candidates[1:]:
        if len(supporting) >= MAX_SUPPORTING:
            break
        if candidate["kind"] in seen_kinds:
            continue  # one angle per kind keeps the story coherent
        seen_kinds.add(candidate["kind"])
        supporting.append(candidate)
    evidence_ids = sorted({e["id"] for c in ([lead] if lead else []) + supporting
                           for e in c["evidence"]})
    return {
        "game_id": game["id"],
        "as_of": bundle["as_of"],
        "season_stage": stage,
        "lead_angle": lead["id"] if lead else None,
        "supporting_angles": [c["id"] for c in supporting],
        "evidence_ids": evidence_ids,
        "candidates_considered": len(candidates),
        "quality_status": "needs-independent-audit",
    }
