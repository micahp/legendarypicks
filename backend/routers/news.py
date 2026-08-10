"""routers/news.py — league news endpoints (news engine).

Serves what ingest_league_news.py collected into `news_items`. DB-first:
this router never touches ESPN or any network — collection happens out-of-band.

Surface model (matches the News page):
  GET /api/news              catch-all, grouped per league (Home tab)
  GET /api/news/narratives   one narrative per league (must precede /{league})
  GET /api/news/{league}     single league
"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from typing import Optional
from _core import *

router = APIRouter()

# `notable` = a story about one of the sport's biggest names that matched no
# transaction rule. It is news on the strength of who it is about.
_GRANULAR_LAYERS = ("trade", "staff", "injury", "notable")
_SERVE_LAYERS = ("narrative",) + _GRANULAR_LAYERS
_NARRATIVES_PER_LEAGUE = 6
_GRANULAR_PER_LEAGUE = 12


_HANDLE_RE = __import__("re").compile(r"^\[@([^\]]+)\]\s*")


def _item(r) -> dict:
    """One board row. X posts carry their handle in the headline as
    `[@AdamSchefter] ...`; move it into the source label so the card reads
    "@AdamSchefter" rather than the bare "x"."""
    headline, source = r["headline"], r["source"]
    if source == "x":
        m = _HANDLE_RE.match(headline or "")
        if m:
            source = "@" + m.group(1)
            headline = _HANDLE_RE.sub("", headline)
    return {
        "id": r["id"],
        "league": r["league"],
        "headline": headline,
        "url": r["url"],
        "source": source,
        "published": r["published"],
        "layer": r["layer"],
        "key_player": r["key_player"],
    }


def _utc_iso(v) -> str:
    """SQLite's datetime('now') writes naive UTC ("2026-08-10 00:31:56").

    The browser parses that shape as LOCAL time, so a card generated an hour
    ago read as being from the future and the relative stamp said "now"
    forever. Serve it with the offset the value actually has (2026-08-09).
    """
    s = (v or "").strip()
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return s
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _conv_card(r) -> dict:
    """One conversation card (AI-generated) as the API serves it."""
    return {
        "conv_id": r["conv_id"],
        "league": r["league"],
        "title": r["title"],
        "narrative": r["narrative"],
        "fan_voice": r["fan_voice"],
        "paragraph": r["paragraph"],
        "sources": json.loads(r["sources"] or "[]"),
        "generated_at": _utc_iso(r["generated_at"]),
        "source_count": r["source_count"],
    }


def _league_report(league: Optional[str] = None) -> dict:
    """Per-league grouping for the league tabs.

    `conversations` = the AI conversation cards for that league (one per
    important conversation — each gets to breathe, Micah 2026-08-07);
    `narratives`/`granular` = the classified items feeding them.
    """
    with closing(_db()) as con:
        if league:
            rows = con.execute(
                """SELECT * FROM news_items
                   WHERE league=? AND league != 'unclassified'
                     AND source NOT IN ('bluesky','x-search')
                     AND layer IN ('narrative','trade','staff','injury','notable')
                   ORDER BY published DESC LIMIT 60""",
                (league,),
            ).fetchall()
            groups = {league: rows}
        else:
            rows = con.execute(
                """SELECT * FROM news_items
                   WHERE league != 'unclassified'
                     AND source NOT IN ('bluesky','x-search')
                     AND layer IN ('narrative','trade','staff','injury','notable')
                   ORDER BY published DESC LIMIT 300"""
            ).fetchall()
            groups = {}
            for r in rows:
                groups.setdefault(r["league"], []).append(r)

        # AI-generated conversation cards (news_narratives), keyed by conv_id
        ai_rows = con.execute("SELECT * FROM news_narratives").fetchall()
        convs_by_league: dict = {}
        for r in ai_rows:
            convs_by_league.setdefault(r["league"], []).append(_conv_card(r))

    out = {}
    # A league with AI conversation cards but only bluesky chatter (no
    # real-article rows) must still appear — the conversation is the point
    # (Micah: chatter IS the signal).
    for lg in convs_by_league:
        out.setdefault(lg, {"conversations": [], "narratives": [], "granular": [], "other": 0})
    for lg, rows in groups.items():
        narratives = [r for r in rows if r["layer"] == "narrative"][:_NARRATIVES_PER_LEAGUE]
        granular = [r for r in rows if r["layer"] in _GRANULAR_LAYERS][:_GRANULAR_PER_LEAGUE]
        entry = out.setdefault(lg, {"conversations": [], "narratives": [], "granular": [], "other": 0})
        entry["narratives"] = [_item(r) for r in narratives]
        entry["granular"] = [_item(r) for r in granular]
        entry["other"] = max(0, len(rows) - len(narratives) - len(granular))
    # Conversations for leagues that also had grouped items.
    for lg, cards in convs_by_league.items():
        out.setdefault(lg, {"conversations": [], "narratives": [], "granular": [], "other": 0})[
            "conversations"] = cards
    return out


@router.get("/api/news")
def news_catch_all(league: Optional[str] = Query(None, description="Filter to one league")):
    """Catch-all feed (Home tab). `conversations` = every AI conversation card,
    each with its own anchor + fan voice (each gets to breathe — we do NOT
    merge a league's conversations into one summary). `leagues` = per-league
    grouping for the league tabs. Optionally ?league=nfl for a single league."""
    if league:
        return {
            "generated": datetime.now(timezone.utc).isoformat(),
            "leagues": _league_report(league.strip().lower()),
        }
    with closing(_db()) as con:
        rows = con.execute(
            """SELECT * FROM news_narratives ORDER BY generated_at DESC"""
        ).fetchall()
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "conversations": [_conv_card(r) for r in rows],
        "leagues": _league_report(),
    }


@router.get("/api/news/narratives")
def news_narratives():
    """Every AI conversation card — what people are actually talking about,
    with the source headlines each was grounded in (LinkedIn-trending)."""
    with closing(_db()) as con:
        rows = con.execute(
            "SELECT * FROM news_narratives ORDER BY league, generated_at DESC"
        ).fetchall()
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "narratives": [_conv_card(r) for r in rows],
    }


@router.get("/api/news/runs")
def news_narratives_runs(conv_id: Optional[str] = Query(None, description="Filter to one conversation")):
    """Every saved generation run for comparison — never overwritten."""
    with closing(_db()) as con:
        if conv_id:
            rows = con.execute(
                "SELECT * FROM news_narratives_runs WHERE conv_id=? ORDER BY generated_at DESC",
                (conv_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM news_narratives_runs ORDER BY conv_id, generated_at DESC"
            ).fetchall()
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "runs": [_conv_card(r) for r in rows],
    }


@router.get("/api/news/{league}")
def news_for_league(league: str):
    """Single-league feed: conversation cards + granular (trades/staff/injuries)."""
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "leagues": _league_report(league.strip().lower()),
    }
