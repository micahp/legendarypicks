"""Lightweight, game-title-scoped slate for the esports Predict page.

The full ``/api/esports/upcoming`` payload powers the broadcast desk and carries
hundreds of live, scheduled, and historical rows.  Predict only needs the open
matches for one game title, so this module projects the existing cached slate
instead of rebuilding or fetching a second feed.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from .common import _ESPORTS_TITLES, _TITLE_SLUG
from .slate import esports_upcoming


router = APIRouter()

SCHEMA_VERSION = "esports-predict-v1"
MAX_MATCHES = 50

_TITLE_ALIASES = {
    "lol": "league-of-legends",
    "league of legends": "league-of-legends",
    "league-of-legends": "league-of-legends",
    "valorant": "valorant",
    "cs": "counter-strike-2",
    "cs2": "counter-strike-2",
    "counter strike 2": "counter-strike-2",
    "counter-strike-2": "counter-strike-2",
    "dota": "dota-2",
    "dota 2": "dota-2",
    "dota-2": "dota-2",
    "r6": "rainbow-six",
    "rainbow six": "rainbow-six",
    "rainbow-six": "rainbow-six",
    "kog": "king-of-glory",
    "king of glory": "king-of-glory",
    "king-of-glory": "king-of-glory",
    "ow": "overwatch",
    "overwatch": "overwatch",
    "cod": "call-of-duty",
    "call of duty": "call-of-duty",
    "call-of-duty": "call-of-duty",
}

_MATCH_FIELDS = (
    "matchKey",
    "teamA",
    "teamB",
    "title",
    "league",
    "startTime",
    "logoA",
    "logoB",
    "live",
    "finished",
    "favorite",
    "psId",
)


def _title_slug(value: Optional[str]) -> Optional[str]:
    if value is None or not str(value).strip():
        return None
    normalized = " ".join(str(value).strip().lower().replace("_", " ").split())
    slug = _TITLE_ALIASES.get(normalized)
    if slug:
        return slug
    return _TITLE_SLUG.get(str(value).strip())


def _is_pickable(match: Dict[str, Any]) -> bool:
    return bool(
        not match.get("finished")
        and str(match.get("teamA") or "").strip()
        and str(match.get("teamB") or "").strip()
    )


def _start_sort(match: Dict[str, Any]) -> float:
    value = match.get("startTime")
    return float(value) if isinstance(value, (int, float)) else float("inf")


def build_predict_slate(
    upcoming: Optional[Dict[str, Any]],
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Project the shared slate into a bounded Predict-page payload."""

    data = upcoming if isinstance(upcoming, dict) else {}
    all_matches = data.get("matches") if isinstance(data.get("matches"), list) else []
    requested_slug = _title_slug(title)
    if title and not requested_slug:
        raise ValueError("unsupported esports title")

    open_by_title: Dict[str, List[Dict[str, Any]]] = {
        display: [] for display in _TITLE_SLUG
    }
    for match in all_matches:
        if not isinstance(match, dict) or not _is_pickable(match):
            continue
        display = match.get("title")
        if display in open_by_title:
            open_by_title[display].append(match)

    title_options = []
    for slug, display in _ESPORTS_TITLES.items():
        rows = open_by_title.get(display, [])
        live_count = sum(bool(row.get("live")) for row in rows)
        starts = [_start_sort(row) for row in rows]
        next_start = min(starts) if starts else None
        if next_start == float("inf"):
            next_start = None
        title_options.append({
            "slug": slug,
            "label": display,
            "match_count": len(rows),
            "live_count": live_count,
            "next_start": next_start,
        })

    if requested_slug is None:
        selected = next(
            (row for row in title_options if row["live_count"] > 0),
            next((row for row in title_options if row["match_count"] > 0), title_options[0]),
        )
        requested_slug = selected["slug"]

    selected_display = _ESPORTS_TITLES[requested_slug]
    selected_matches = sorted(
        open_by_title.get(selected_display, []),
        key=lambda row: (not bool(row.get("live")), _start_sort(row)),
    )
    visible = selected_matches[:MAX_MATCHES]

    return {
        "schema_version": SCHEMA_VERSION,
        "selected_title": {"slug": requested_slug, "label": selected_display},
        "titles": title_options,
        "matches": [
            {field: match.get(field) for field in _MATCH_FIELDS}
            for match in visible
        ],
        "match_count": len(selected_matches),
        "has_more": len(selected_matches) > len(visible),
        "building": bool(data.get("building")),
        "error": data.get("error"),
        "source": data.get("source"),
    }


@router.get("/api/esports/predict")
def predict_slate(
    title: Optional[str] = Query(
        None,
        description="Game-title slug or alias, for example league-of-legends, cs2, or cod.",
    ),
):
    try:
        return build_predict_slate(esports_upcoming(), title=title)
    except ValueError as exc:
        allowed = ", ".join(_ESPORTS_TITLES)
        raise HTTPException(400, "title must be one of: {}".format(allowed)) from exc
