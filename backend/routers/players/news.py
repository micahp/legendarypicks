"""news — players router news layer."""
import json
import math
import sqlite3
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from league_offering import offered_leagues, sql_league_filter
from league_stats import LEADERBOARD_LEAGUES, canonical_population_sql
from nfl_rankings import nfl_player_rank_context
from nfl_stat_derivations import with_derived as _with_derived
from nfl_news import (ROTOWIRE_LABEL, load_news_feed, load_player_news_page, load_sleeper_crosswalk, merge_player_news, resolve_rotowire_id)
from . import router



def _load_sleeper_crosswalk_pkg(*args, **kwargs):
    """Resolve `routers.players.load_sleeper_crosswalk` at call time (tests patch the package attr)."""
    from routers.players import load_sleeper_crosswalk as _pkg
    return _pkg(*args, **kwargs)


def _load_news_feed_pkg(*args, **kwargs):
    """Resolve `routers.players.load_news_feed` at call time (tests patch the package attr)."""
    from routers.players import load_news_feed as _pkg
    return _pkg(*args, **kwargs)


def _load_player_news_page_pkg(*args, **kwargs):
    """Resolve `routers.players.load_player_news_page` at call time (tests patch the package attr)."""
    from routers.players import load_player_news_page as _pkg
    return _pkg(*args, **kwargs)

def __db_pkg(*args, **kwargs):
    """Resolve `routers.players._db` at call time (tests patch the package attr)."""
    from routers.players import _db as _pkg
    return _pkg(*args, **kwargs)

@router.get("/api/player/{player_id}/news")
def player_news(player_id: int,
                limit: int = Query(10, ge=1, le=25)):
    """Fetch general NFL player reporting from ESPN search."""
    import json as _json
    import re
    import urllib.parse
    import urllib.request

    with closing(__db_pkg()) as con:
        p = con.execute("SELECT id,name,espn_id,league FROM players WHERE id=?", (player_id,)).fetchone()
        if not p:
            raise HTTPException(404, "Player not found")
        if p["league"] != "nfl":
            return {"player_id": player_id, "name": p["name"], "articles": []}
        espn_id = p["espn_id"]
        if not espn_id:
            return {"player_id": player_id, "name": p["name"], "articles": []}

    # ESPN's league news endpoint is a short rolling window and routinely drops
    # current player stories. Its search API is the player page's durable news
    # surface, including the ESPN athlete result and matching articles.
    search_name = re.sub(r"\s+(?:Jr\.?|Sr\.?|II|III|IV|V)$", "", p["name"], flags=re.I)
    url = "https://site.api.espn.com/apis/search/v2?" + urllib.parse.urlencode(
        {"query": search_name, "limit": max(limit, 20)}
    )
    try:
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "LegendaryPicks/0.7"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            data = _json.loads(response.read().decode())
    except Exception:
        return {"player_id": player_id, "name": p["name"], "articles": []}

    articles = []
    result_groups = data.get("results", []) if isinstance(data, dict) else []
    player_results = next(
        (group.get("contents", []) for group in result_groups if group.get("type") == "player"),
        [],
    )
    nfl_player_results = [
        candidate for candidate in player_results
        if str(candidate.get("uid") or "").startswith("s:20~l:28~a:")
    ]
    matched_athlete = [
        candidate for candidate in nfl_player_results
        if str(candidate.get("uid") or "").endswith(f"~a:{espn_id}")
    ]
    # Search articles are name-keyed, and the article group cannot be split by
    # name alone when ESPN returns several same-name NFL athletes (e.g. Josh
    # Allen BUF QB vs Josh Allen TB C vs Josh Hines-Allen). That is not a
    # reason to blank the tab: the profile's espn_id confirms exactly which
    # athlete is ours, and the per-article name filter below still applies.
    # Requiring exactly one NFL athlete for the query name would hide real
    # published news behind the empty state for every shared-name player.
    if len(matched_athlete) != 1:
        return {"player_id": player_id, "name": p["name"], "articles": []}
    article_results = next(
        (group.get("contents", []) for group in result_groups if group.get("type") == "article"),
        [],
    )
    player_tokens = re.findall(r"[a-z0-9]+", search_name.lower())
    for article in sorted(
        article_results,
        key=lambda candidate: str(candidate.get("date") or ""),
        reverse=True,
    ):
        link = article.get("link", {}).get("web")
        published = article.get("date")
        headline = article.get("displayName")
        if not link or not published or not headline:
            continue
        parsed_link = urllib.parse.urlparse(link)
        category_text = " ".join(
            str(category.get("description") or "")
            for category in article.get("categories", [])
        ).lower()
        if "/fantasy/" in parsed_link.path or "fantasy" in category_text:
            continue
        # ESPN search confirms the athlete separately, but its article group can
        # still contain broad first-name matches from other sports. Keep only NFL
        # stories whose returned metadata contains the player's complete name.
        if "/nfl/" not in parsed_link.path:
            continue
        evidence = " ".join(
            [headline, parsed_link.path]
            + [
                str(image.get("name") or image.get("caption") or "")
                for image in article.get("images", [])
            ]
        ).lower()
        evidence_tokens = set(re.findall(r"[a-z0-9]+", evidence))
        if not player_tokens or not all(token in evidence_tokens for token in player_tokens):
            continue
        images = [
            {"url": image.get("url"), "caption": image.get("caption") or image.get("name")}
            for image in article.get("images", [])
            if image.get("url")
        ][:1]
        byline = str(article.get("byline") or "").strip()
        articles.append(
            {
                "id": article.get("id"),
                "headline": headline,
                "description": f"By {byline}" if byline else "",
                "published": published,
                "lastModified": None,
                "link": link,
                "images": images,
            }
        )
        if len(articles) >= limit:
            break
    return {"player_id": player_id, "name": p["name"], "articles": articles}

@router.get("/api/player/{player_id}/fantasy-news")
def player_fantasy_news(player_id: int,
                        limit: int = Query(10, ge=1, le=25)):
    """Fetch player-specific RotoWire history for the fantasy draft surface."""
    with closing(__db_pkg()) as con:
        p = con.execute(
            """SELECT id,name,team,league,position,espn_id,nfl_gsis_id
               FROM players WHERE id=?""",
            (player_id,),
        ).fetchone()
        if not p:
            raise HTTPException(404, "Player not found")
        if p["league"] != "nfl":
            return {
                "player_id": player_id,
                "name": p["name"],
                "source": ROTOWIRE_LABEL,
                "data_status": "unsupported",
                "message": "Fantasy news is available for NFL players only.",
                "articles": [],
            }
        crosswalk = _load_sleeper_crosswalk_pkg()
        resolution = resolve_rotowire_id(con, p, crosswalk)

    source_player_id = resolution["source_player_id"]
    if source_player_id is None:
        message = crosswalk.get("message") or "Fantasy news identity could not be verified for this player."
        return {
            "player_id": player_id,
            "name": p["name"],
            "source": ROTOWIRE_LABEL,
            "data_status": "unavailable",
            "message": message,
            "source_updated_at": None,
            "articles": [],
        }

    feed = _load_news_feed_pkg()
    history = _load_player_news_page_pkg(source_player_id)
    articles = merge_player_news(source_player_id, feed, history, limit)
    if articles:
        status = "stale" if history["status"] == "stale" and feed["status"] != "ready" else "ready"
        message = history["message"] if status == "stale" else None
    elif history["status"] == "ready":
        status = "no_news"
        message = "No fantasy news is published for this player."
    else:
        status = "unavailable"
        message = history["message"] or feed["message"] or "Fantasy news is temporarily unavailable."

    response_articles = []
    for item in articles:
        response_articles.append(
            {
                "id": item["id"],
                "source_player_id": str(item["source_player_id"]),
                "headline": item["headline"],
                "notes": item["notes"],
                "analysis": item["analysis"],
                "injury_status": item["injury_status"] or None,
                "injury_type": item["injury_type"] or None,
                "injury_location": item["injury_location"] or None,
                "return_date": item["return_date"] or None,
                "published": item["published"],
                "link": item["link"],
            }
        )

    return {
        "player_id": player_id,
        "name": p["name"],
        "source": ROTOWIRE_LABEL,
        "data_status": status,
        "message": message,
        "source_updated_at": history["fetched_at"] or feed["fetched_at"],
        "articles": response_articles,
    }
