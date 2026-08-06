"""routers/news.py — league news endpoints (news engine).

Serves what ingest_league_news.py collected into `news_items`. DB-first:
this router never touches ESPN or any network — collection happens out-of-band.

Surface model (matches the News page):
  GET /api/news              catch-all, grouped per league (Home tab)
  GET /api/news/narratives   one narrative per league (must precede /{league})
  GET /api/news/{league}     single league
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from typing import Optional
from _core import *

router = APIRouter()

_GRANULAR_LAYERS = ("trade", "staff", "injury")
_SERVE_LAYERS = ("narrative",) + _GRANULAR_LAYERS
_NARRATIVES_PER_LEAGUE = 6
_GRANULAR_PER_LEAGUE = 12


def _item(r) -> dict:
    return {
        "id": r["id"],
        "headline": r["headline"],
        "url": r["url"],
        "source": r["source"],
        "published": r["published"],
        "layer": r["layer"],
        "key_player": r["key_player"],
    }


def _league_report(league: Optional[str] = None) -> dict:
    with closing(_db()) as con:
        if league:
            rows = con.execute(
                """SELECT * FROM news_items
                   WHERE league=? AND layer IN ('narrative','trade','staff','injury')
                   ORDER BY published DESC LIMIT 60""",
                (league,),
            ).fetchall()
            groups = {league: rows}
        else:
            rows = con.execute(
                """SELECT * FROM news_items
                   WHERE layer IN ('narrative','trade','staff','injury')
                   ORDER BY published DESC LIMIT 300"""
            ).fetchall()
            groups = {}
            for r in rows:
                groups.setdefault(r["league"], []).append(r)

    out = {}
    for lg, rows in groups.items():
        narratives = [r for r in rows if r["layer"] == "narrative"][:_NARRATIVES_PER_LEAGUE]
        granular = [r for r in rows if r["layer"] in _GRANULAR_LAYERS][:_GRANULAR_PER_LEAGUE]
        out[lg] = {
            "narratives": [_item(r) for r in narratives],
            "granular": [_item(r) for r in granular],
            "other": max(0, len(rows) - len(narratives) - len(granular)),
        }
    return out


@router.get("/api/news")
def news_catch_all(league: Optional[str] = Query(None, description="Filter to one league")):
    """Catch-all feed (Home tab). Optionally ?league=nfl for a single league."""
    if league:
        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "leagues": _league_report(league.strip().lower()),
        }
    return {"generated": datetime.now(timezone.utc).isoformat(), "leagues": _league_report()}


@router.get("/api/news/narratives")
def news_narratives():
    """One narrative per league — the meta-story each league is telling."""
    report = _league_report()
    narratives = []
    for lg in sorted(report):
        n = report[lg]["narratives"]
        if n:
            narratives.append({
                "league": lg,
                "headline": n[0]["headline"],
                "url": n[0]["url"],
                "source": n[0]["source"],
                "published": n[0]["published"],
            })
    return {"generated": datetime.now(timezone.utc).isoformat(), "narratives": narratives}


@router.get("/api/news/{league}")
def news_for_league(league: str):
    """Single-league feed: narratives + granular (trades/staff/injuries)."""
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "leagues": _league_report(league.strip().lower()),
    }
