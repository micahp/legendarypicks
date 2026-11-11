"""Render a compact preview and a full article from a story plan.

Only claims from the candidates appear in the text. If there is no lead,
nothing is rendered. Nothing is invented, and no model is called. The same
inputs always give the same output.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

TEMPLATE_VERSION = "2026-11-11.1"
SMALL_SAMPLE_SENTENCE = "Only {} games have been played, so the sample is small."
SECTION_FOR_KIND = {
    "team_momentum": "what_changed",
    "emerging_player": "players_to_watch",
    "national_broadcast": "why_this_game",
    "lineup_shift": "lineup",
}


def _sentences_for(candidate: Dict[str, Any], plan: Dict[str, Any]) -> List[str]:
    sentences = [candidate["claim"] + "."]
    sentences += [text + "." for text in candidate.get("extra_sentences", [])]
    stage = plan["season_stage"]
    if stage["phase"] == "early_regular_season" and \
            candidate["kind"] == "team_momentum":
        sentences.append(SMALL_SAMPLE_SENTENCE.format(candidate["sample_games"]))
    return sentences


def _by_id(candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {c["id"]: c for c in candidates}


def preview_id(plan: Dict[str, Any]) -> str:
    payload = json.dumps({"plan": plan, "template": TEMPLATE_VERSION},
                         sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def render_compact(plan: Dict[str, Any],
                   candidates: List[Dict[str, Any]]) -> Optional[str]:
    """One to three sentences: the lead, then at most one supporting angle."""
    if not plan["lead_angle"]:
        return None
    index = _by_id(candidates)
    sentences = _sentences_for(index[plan["lead_angle"]], plan)
    if plan["supporting_angles"]:
        sentences += _sentences_for(index[plan["supporting_angles"][0]], plan)[:1]
    return " ".join(sentences[:3])


def render_article(plan: Dict[str, Any],
                   candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Headline, deck and sections, all built from the plan's angles."""
    if not plan["lead_angle"]:
        return None
    index = _by_id(candidates)
    lead = index[plan["lead_angle"]]
    ordered = [lead] + [index[i] for i in plan["supporting_angles"]]
    sections: Dict[str, List[str]] = {}
    for candidate in ordered:
        section = SECTION_FOR_KIND[candidate["kind"]]
        sections.setdefault(section, []).extend(_sentences_for(candidate, plan))
    return {
        "headline": lead["claim"],
        "deck": " ".join(_sentences_for(index[plan["supporting_angles"][0]], plan))
        if plan["supporting_angles"] else "",
        "sections": [{"id": key, "paragraph": " ".join(value)}
                     for key, value in sections.items()],
        "as_of": plan["as_of"],
        "story_plan": plan,
        "template_version": TEMPLATE_VERSION,
        "preview_id": preview_id(plan),
        "editorial_status": "needs-independent-audit",
    }
