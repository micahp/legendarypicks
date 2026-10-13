"""Lightweight, game-title-scoped slates for Predict and league pages.

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
LEAGUE_SCHEMA_VERSION = "esports-league-v1"
MAX_MATCHES = 50
MAX_LEAGUE_MATCHES = 30
MAX_RESULTS = 16

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

_LEAGUE_MATCH_FIELDS = (
    "matchKey",
    "startTime",
    "endTime",
    "live",
    "state",
    "title",
    "league",
    "teamA",
    "teamB",
    "favorite",
    "watch",
    "score",
    "finished",
    "finishedAt",
    "winner",
    "resultUnknown",
    "model",
    "logoA",
    "logoB",
    "minorLeague",
    "tier",
    "prominence",
    "psId",
    "streamKey",
    "eventId",
)

_RESULT_FIELDS = (
    "matchKey",
    "startTime",
    "title",
    "league",
    "teamA",
    "teamB",
    "score",
    "finished",
    "finishedAt",
    "winner",
    "resultUnknown",
    "logoA",
    "logoB",
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


def _title_options(all_matches: List[Any]) -> List[Dict[str, Any]]:
    open_by_title: Dict[str, List[Dict[str, Any]]] = {
        display: [] for display in _TITLE_SLUG
    }
    result_counts = {display: 0 for display in _TITLE_SLUG}
    for match in all_matches:
        if not isinstance(match, dict):
            continue
        display = match.get("title")
        if display not in open_by_title:
            continue
        if match.get("finished"):
            result_counts[display] += 1
        elif _is_pickable(match):
            open_by_title[display].append(match)

    options = []
    for slug, display in _ESPORTS_TITLES.items():
        rows = open_by_title.get(display, [])
        starts = [
            row.get("startTime") for row in rows
            if isinstance(row.get("startTime"), (int, float))
        ]
        options.append({
            "slug": slug,
            "label": display,
            "match_count": len(rows),
            "live_count": sum(bool(row.get("live")) for row in rows),
            "result_count": result_counts.get(display, 0),
            "next_start": min(starts) if starts else None,
        })
    return options


def _default_title_slug(options: List[Dict[str, Any]]) -> str:
    selected = next(
        (row for row in options if row["live_count"] > 0),
        next((row for row in options if row["match_count"] > 0), options[0]),
    )
    return selected["slug"]


def build_predict_slate(
    upcoming: Optional[Dict[str, Any]],
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Project the shared slate into a bounded Predict-page payload."""

    data = upcoming if isinstance(upcoming, dict) else {}
    all_matches = data.get("matches") if isinstance(data.get("matches"), list) else []
    normalized_title = " ".join(str(title or "").strip().lower().replace("_", " ").split())
    all_titles = normalized_title in {"all", "all esports"}
    requested_slug = None if all_titles else _title_slug(title)
    if title and not all_titles and not requested_slug:
        raise ValueError("unsupported esports title")

    title_options = _title_options(all_matches)

    if requested_slug is None and not all_titles:
        requested_slug = _default_title_slug(title_options)

    selected_display = "All Esports" if all_titles else _ESPORTS_TITLES[requested_slug]
    supported_displays = set(_TITLE_SLUG)
    selected_matches = sorted(
        [
            match for match in all_matches
            if isinstance(match, dict)
            and (
                match.get("title") in supported_displays
                if all_titles
                else match.get("title") == selected_display
            )
            and _is_pickable(match)
        ],
        key=lambda row: (not bool(row.get("live")), _start_sort(row)),
    )
    visible = selected_matches[:MAX_MATCHES]

    return {
        "schema_version": SCHEMA_VERSION,
        "selected_title": {
            "slug": "all" if all_titles else requested_slug,
            "label": selected_display,
        },
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


def build_league_slate(
    upcoming: Optional[Dict[str, Any]],
    title: Optional[str] = None,
) -> Dict[str, Any]:
    """Return one title's live/scheduled desk plus a bounded result history."""

    data = upcoming if isinstance(upcoming, dict) else {}
    all_matches = data.get("matches") if isinstance(data.get("matches"), list) else []
    requested_slug = _title_slug(title)
    if title and not requested_slug:
        raise ValueError("unsupported esports title")
    options = _title_options(all_matches)
    requested_slug = requested_slug or _default_title_slug(options)
    display = _ESPORTS_TITLES[requested_slug]
    selected = [
        match for match in all_matches
        if isinstance(match, dict)
        and match.get("title") == display
        and str(match.get("teamA") or "").strip()
        and str(match.get("teamB") or "").strip()
    ]
    schedule = sorted(
        (match for match in selected if not match.get("finished")),
        key=lambda row: (not bool(row.get("live")), _start_sort(row)),
    )
    results = sorted(
        (match for match in selected if match.get("finished")),
        key=lambda row: (
            row.get("finishedAt")
            if isinstance(row.get("finishedAt"), (int, float))
            else row.get("startTime")
            if isinstance(row.get("startTime"), (int, float))
            else 0
        ),
        reverse=True,
    )
    visible_schedule = schedule[:MAX_LEAGUE_MATCHES]
    visible_results = results[:MAX_RESULTS]

    def public_match(match: Dict[str, Any]) -> Dict[str, Any]:
        return {field: match.get(field) for field in _LEAGUE_MATCH_FIELDS}

    def public_result(match: Dict[str, Any]) -> Dict[str, Any]:
        return {field: match.get(field) for field in _RESULT_FIELDS}

    return {
        "schema_version": LEAGUE_SCHEMA_VERSION,
        "selected_title": {"slug": requested_slug, "label": display},
        "titles": options,
        "matches": [public_match(match) for match in visible_schedule],
        "results": [public_result(match) for match in visible_results],
        "match_count": len(schedule),
        "result_count": len(results),
        "has_more_matches": len(schedule) > len(visible_schedule),
        "has_more_results": len(results) > len(visible_results),
        "building": bool(data.get("building")),
        "error": data.get("error"),
        "source": data.get("source"),
    }


@router.get("/api/esports/predict")
def predict_slate(
    title: Optional[str] = Query(
        None,
        description="Game-title slug or alias, or all for every supported title.",
    ),
):
    try:
        return build_predict_slate(esports_upcoming(), title=title)
    except ValueError as exc:
        allowed = "all, " + ", ".join(_ESPORTS_TITLES)
        raise HTTPException(400, "title must be one of: {}".format(allowed)) from exc


@router.get("/api/esports/league/{title}")
def league_slate(title: str):
    try:
        return build_league_slate(esports_upcoming(), title=title)
    except ValueError as exc:
        allowed = ", ".join(_ESPORTS_TITLES)
        raise HTTPException(400, "title must be one of: {}".format(allowed)) from exc


@router.get("/api/esports/titles")
def esports_titles():
    """Registered esports titles with counts derived from the shared slate.

    The Esports league hub uses this for title discovery instead of reconstructing
    title identity in the client: the slug/label registry is the backend's
    (`_ESPORTS_TITLES`), and the counts come from the same cached slate the board
    reads. No new collector, no external request.
    """
    data = esports_upcoming()
    all_matches = data.get("matches") if isinstance(data.get("matches"), list) else []
    return {"titles": _title_options(all_matches)}
