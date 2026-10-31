"""Run the bounded, read-only narrative-event research audit.

All database reads use SQLite mode=ro. Network mode retains allowlisted publisher
metadata and structured play fields only; news bodies, descriptions, and play text
are discarded and never written to an artifact.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import narrative_event_knowledge as nek
import team_codes


NFL_WEEKS = (4, 5, 6, 7)
NFL_QUOTAS = {4: 13, 5: 13, 6: 12, 7: 12}
NBA_SEASON = 2027  # current schedule season used for upcoming pregame targets
NBA_EVENT_SEASON = 2026  # latest completed regular season available for the 100-game audit
NBA_REGULAR_GAMES = 50
NBA_ARTICLE_SAMPLE = 100
PBP_PAGE_LIMIT = 1000
ARTIFACT_ROOT = (Path(__file__).resolve().parents[1] / "docs" / "research" /
                 "narrative-event-knowledge-2026-10-31")
DISALLOWED_ARTIFACT_KEYS = {"body", "story", "text", "description", "content", "articlebody"}


class ResearchAuditError(RuntimeError):
    pass


def utc_now() -> str:
    return nek.iso_utc(datetime.now(timezone.utc))


def _utc_db(value: Any) -> str | None:
    if value is None:
        return None
    parsed = nek.parse_utc(value)
    if parsed:
        return nek.iso_utc(parsed)
    # SQLite datetime('now') values in this repository are UTC but omit an offset.
    try:
        naive = datetime.fromisoformat(str(value).replace(" ", "T"))
    except (TypeError, ValueError):
        return None
    if naive.tzinfo is None:
        naive = naive.replace(tzinfo=timezone.utc)
    return nek.iso_utc(naive)


def _json_write(path: Path, value: Any) -> None:
    _assert_metadata_only(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _jsonl_write(path: Path, rows: list[dict[str, Any]]) -> None:
    _assert_metadata_only(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _jsonl_read(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _network_spend_summary(path: Path) -> dict[str, Any]:
    request_counts = Counter()
    status_counts: dict[str, Counter] = defaultdict(Counter)
    if not path.is_file():
        return {"request_counts_by_host": {}, "status_counts_by_host": {}}
    for row in _jsonl_read(path):
        host = str(row.get("host") or "unknown")
        request_counts[host] += 1
        status_counts[host][str(row.get("status") or "unknown")] += 1
    return {"request_counts_by_host": dict(request_counts),
            "status_counts_by_host": {host: dict(counts)
                                      for host, counts in status_counts.items()}}


def _assert_metadata_only(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).replace("_", "").lower() in DISALLOWED_ARTIFACT_KEYS:
                raise ResearchAuditError(f"refusing article/play text field at {path}.{key}")
            _assert_metadata_only(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_metadata_only(child, f"{path}[{index}]")


def open_readonly(path: str | Path) -> sqlite3.Connection:
    db = Path(path).expanduser().resolve()
    if db.name == "picks.db":
        raise ResearchAuditError("refusing the production-named picks.db; pass the dev database explicitly")
    if not db.is_file():
        raise ResearchAuditError(f"database does not exist: {db}")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    if con.execute("PRAGMA query_only").fetchone()[0] != 1:
        con.close()
        raise ResearchAuditError("SQLite did not enter query-only mode")
    return con


def _spread_pick(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count >= len(rows):
        return rows[:]
    if count <= 0 or not rows:
        return []
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[i] for i in indices]


def _nba_code(value: str) -> str:
    return team_codes.normalize("nba", value)


def build_samples(con: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (50 NFL PBP sample, 50 NBA PBP + 100 NBA article sample)."""
    nfl_rows = [dict(row) for row in con.execute(
        """SELECT s.game_id AS source_game_id, CAST(s.espn AS TEXT) AS espn_event_id,
                  s.season, s.week, s.gameday AS game_date, s.away_team, s.home_team,
                  s.away_score, s.home_score
           FROM nfl_schedule s
           WHERE s.season=2026 AND s.game_type='REG' AND s.week BETWEEN 4 AND 7
             AND s.away_score IS NOT NULL AND s.home_score IS NOT NULL
             AND EXISTS (SELECT 1 FROM nfl_pbp p WHERE p.game_id=s.game_id)
           ORDER BY s.week, s.gameday, s.game_id""")]
    nfl_sample = []
    for week, quota in NFL_QUOTAS.items():
        selected = _spread_pick([r for r in nfl_rows if int(r["week"]) == week], quota)
        if len(selected) != quota:
            raise ResearchAuditError(f"NFL week {week}: expected {quota} PBP games, found {len(selected)}")
        nfl_sample.extend(selected)
    if len(nfl_sample) != 50 or any(not g["espn_event_id"] for g in nfl_sample):
        raise ResearchAuditError("NFL sample does not contain 50 games with ESPN IDs")
    for row in nfl_sample:
        row.update({"league": "nfl", "sample_role": "four_week_event_sample",
                    "season_phase": "regular", "game_page_id": row["espn_event_id"]})

    nba_population = [dict(row) for row in con.execute(
        """SELECT source_game_id,season,source_season AS season_year,espn_event_id,
                  game_date,home,away,home_score,away_score,game_type
           FROM nba_sportsdataverse_games
           WHERE source_season=? AND game_type='REG'
             AND home_score IS NOT NULL AND away_score IS NOT NULL
           ORDER BY game_date,source_game_id""", (NBA_EVENT_SEASON,))]
    if len(nba_population) < NBA_ARTICLE_SAMPLE:
        raise ResearchAuditError(
            f"NBA completed regular-season population has {len(nba_population)} games; need 100")
    nba_meta = []
    for row in _spread_pick(nba_population, NBA_ARTICLE_SAMPLE):
        row.update({"league": "nba", "game_id": str(row["espn_event_id"]),
                    "source_game_id": str(row["source_game_id"]),
                    "game_page_id": str(row["source_game_id"]),
                    "espn_event_id": str(row["espn_event_id"]),
                    "home_team": _nba_code(row["home"]), "away_team": _nba_code(row["away"]),
                    "start_utc": None, "season": NBA_EVENT_SEASON,
                    "season_phase": "regular", "sample_role": "article_coverage_sample"})
        nba_meta.append(row)
    nba_pbp_sample = [dict(row) for row in _spread_pick(nba_meta, NBA_REGULAR_GAMES)]
    for row in nba_pbp_sample:
        row["sample_role"] = "event_sample"
    if len(nba_meta) != NBA_ARTICLE_SAMPLE:
        raise ResearchAuditError(
            f"NBA article sample produced {len(nba_meta)} games; expected {NBA_ARTICLE_SAMPLE}")
    return nfl_sample, (nba_pbp_sample, nba_meta)


def _clean_metadata(value: Any, max_chars: int = 500) -> str | None:
    if isinstance(value, dict):
        for key in ("displayName", "name", "text", "title", "value"):
            if value.get(key) is not None:
                return _clean_metadata(value[key], max_chars)
        return None
    if isinstance(value, list):
        items = [_clean_metadata(item, max_chars) for item in value]
        return ", ".join(item for item in items if item)[:max_chars] or None
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:max_chars] or None


def _origin_class(publisher: str | None, byline: str | None, credit: str | None) -> str:
    signal = " ".join(str(v or "") for v in (publisher, byline, credit)).lower()
    if "data skrive" in signal or "sportradar" in signal or "automated" in signal:
        return "computer_assisted_disclosed"
    if re.search(r"\b(ap|associated press)\b", signal):
        return "ap_origin"
    return "unknown_origin"


_HEADLINE_THEMES = {
    "comeback": re.compile(r"\b(comeback|came back|rall(?:y|ied)|erase[sd]? .*deficit|trailed)\b", re.I),
    "clutch_execution": re.compile(r"\b(last.second|game.winning|walk.off|buzzer.beater|late.winner)\b", re.I),
    "fourth_down_strategy": re.compile(r"\b(fourth.down|4th.down|go.for.it)\b", re.I),
    "turnovers": re.compile(r"\b(turnover|interception|fumble|takeaway)s?\b", re.I),
    "defense": re.compile(r"\b(defen[cs]e|defensive|sack|shutout|pressure)\b", re.I),
    "player_outlier": re.compile(r"\b(record|career.high|scores? \d+|scores? .*points|three touchdowns)\b", re.I),
    "scoring_run": re.compile(r"\b(consecutive points|scoring run|points in a row|straight possessions)\b", re.I),
    "injury": re.compile(r"\b(injur(?:y|ed)|hurt|questionable|out for)\b", re.I),
}
_THEME_EVENT_CATEGORIES = {
    "comeback": {"comeback"},
    "clutch_execution": {"decisive_score", "clutch_events", "late_scoring_drive"},
    "fourth_down_strategy": {"fourth_down_attempts"},
    "turnovers": {"turnover_events"},
    "defense": {"turnover_events", "clutch_events"},
    "player_outlier": {"player_outlier"},
    "scoring_run": {"scoring_run"},
    "injury": set(),
}


def headline_theme_candidates(headline: str | None) -> list[str]:
    if not headline:
        return []
    return sorted(theme for theme, pattern in _HEADLINE_THEMES.items() if pattern.search(headline))


def _duplicate_key(row: dict[str, Any]) -> str | None:
    title = re.sub(r"[^a-z0-9]+", " ", str(row.get("headline") or "").lower()).strip()
    published = str(row.get("published_at") or "")[:10]
    if not title or not published:
        return None
    return f"{published}:{title}"


def _safe_url(url: Any) -> str | None:
    if not url:
        return None
    parts = urlsplit(str(url))
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_")]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path,
                       urlencode(query), ""))


def _article_metadata(*, league: str, game_id: str, game_date: str,
                      game_end: str | None, home_team: str, away_team: str,
                      publisher: str, headline: str | None, byline: str | None,
                      credit: str | None, published_at: str | None, url: str | None,
                      article_type: str | None, status: str,
                      sample_role: str, season_phase: str,
                      coverage_scope: str = "single_game") -> dict[str, Any]:
    pub = publisher or "unknown"
    clean_url = _safe_url(url)
    published = _utc_db(published_at) if published_at else None
    final_whistle = nek.parse_utc(game_end)
    published_dt = nek.parse_utc(published)
    delay = int((published_dt - final_whistle).total_seconds()) if final_whistle and published_dt else None
    return {
        "league": league,
        "game_id": str(game_id),
        "game_date": str(game_date),
        "home_team": home_team,
        "away_team": away_team,
        "publisher": pub,
        "headline": _clean_metadata(headline),
        "byline": _clean_metadata(byline, 250),
        "source_credit": _clean_metadata(credit, 250),
        "published_at": published,
        "url": clean_url,
        "article_type": _clean_metadata(article_type, 120),
        "origin_class": _origin_class(pub, byline, credit),
        "headline_theme_candidates": headline_theme_candidates(headline),
        "publication_delay_seconds_from_final_whistle": delay,
        "status": status,
        "coverage_scope": coverage_scope,
        "sample_role": sample_role,
        "season_phase": season_phase,
        "duplicate_key": _duplicate_key({"headline": headline, "published_at": published}),
    }


class _MetaHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            value = attrs.get("content")
            if key and value and key in {"og:title", "article:published_time", "datepublished"}:
                self.meta[key] = value[:500]
        if tag == "link" and (attrs.get("rel") or "").lower() == "canonical":
            self.canonical = attrs.get("href")


def nba_com_game_metadata(page_html: str, game: dict[str, Any]) -> dict[str, Any]:
    """Parse only story header metadata from NBA.com's embedded game JSON."""
    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', page_html, re.S | re.I)
    pageprops: dict[str, Any] = {}
    if match:
        try:
            payload = json.loads(match.group(1))
            pageprops = (((payload.get("props") or {}).get("pageProps")) or {})
        except (json.JSONDecodeError, AttributeError, TypeError):
            pageprops = {}
    story = pageprops.get("story") or {}
    header = story.get("header") or {}
    game_info = pageprops.get("game") or {}
    recap = game_info.get("gameRecap") or pageprops.get("gameRecap") or {}
    headline = _clean_metadata(header.get("headline") or recap.get("title"))
    byline = _clean_metadata(story.get("byline"), 250)
    credit = _clean_metadata(story.get("bytitle") or story.get("source"), 250)
    published = _clean_metadata(story.get("date"), 100)
    article_type = _clean_metadata(story.get("storyType") or recap.get("slug"), 120)
    url = recap.get("permalink") or f"https://www.nba.com/game/{game['game_page_id']}"
    state = "found" if headline else "no_story_metadata"
    result = _article_metadata(
        league="nba", game_id=str(game.get("espn_event_id") or game["game_page_id"]),
        game_date=game["game_date"],
        game_end=None, home_team=game["home_team"], away_team=game["away_team"],
        publisher="nba.com", headline=headline, byline=byline, credit=credit,
        published_at=published, url=url, article_type=article_type, status=state,
        sample_role=game["sample_role"], season_phase=game["season_phase"])
    result["publisher_game_id"] = str(game["game_page_id"])
    result["espn_event_id"] = game.get("espn_event_id")
    result["source_discovery"] = "nba.com_game_summary"
    return result


def espn_summary_metadata(payload: dict[str, Any], game: dict[str, Any]) -> dict[str, Any]:
    """Read allowlisted fields from the summary's article object; discard its story field."""
    article = payload.get("article") or {}
    if isinstance(article, list):
        article = article[0] if article else {}
    links = article.get("links") or {}
    if isinstance(links, dict):
        web = links.get("web") or {}
        url = web.get("href") if isinstance(web, dict) else None
    else:
        url = None
    result = _article_metadata(
        league="nfl", game_id=str(game["espn_event_id"]), game_date=game["game_date"],
        game_end=None, home_team=game["home_team"], away_team=game["away_team"],
        publisher=_clean_metadata(article.get("source"), 120) or "espn",
        headline=article.get("headline"), byline=article.get("byline"),
        credit=article.get("source"), published_at=article.get("published"), url=url,
        article_type=article.get("type"), status="found" if article.get("headline") else "no_article",
        sample_role=game["sample_role"], season_phase=game["season_phase"])
    result["source_discovery"] = "espn_nfl_summary"
    return result


def normalize_summary_timeline(payload: dict[str, Any], game: dict[str, Any],
                               captured_at: str) -> tuple[list[dict[str, Any]], str, str]:
    """Keep score/time/event IDs from ESPN summaries and discard narrative text."""
    league = str(game["league"]).lower()
    if league == "nba":
        raw_items = payload.get("plays") or []
        scope = "full_play_by_play"
    elif league == "nfl":
        raw_items = payload.get("scoringPlays") or []
        scope = "scoring_plays_only"
    else:
        raise ResearchAuditError(f"unsupported ESPN summary timeline league: {league}")
    if not raw_items:
        raise nek.NarrativeDataError(f"ESPN summary has no {scope} rows")

    competitions = (((payload.get("header") or {}).get("competitions")) or [])
    kickoff = nek.parse_utc((competitions[0].get("date") if competitions else None)
                            or game.get("start_utc"))
    if kickoff is None:
        raise nek.NarrativeDataError("ESPN summary lacks a timezone-aware scheduled start")
    source_time_basis = "scheduled_kickoff_plus_game_clock_estimate"

    def field(value: Any, *keys: str) -> Any:
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return value
        return value

    normalized_input = []
    for item in raw_items:
        period_value = field(item.get("period"), "number")
        clock_value = field(item.get("clock"), "displayValue")
        if clock_value is None:
            clock_value = field(item.get("clock"), "value")
        period = nek._optional_int(period_value, "period")
        clock_seconds = nek._clock_seconds(clock_value)
        if not period or clock_seconds is None:
            continue
        if league == "nfl":
            period_length, overtime_length, regulation_periods = 900, 600, 4
        else:
            period_length, overtime_length, regulation_periods = 720, 300, 4
        if period <= regulation_periods:
            elapsed = (period - 1) * period_length + (period_length - clock_seconds)
        else:
            elapsed = (regulation_periods * period_length +
                       (period - regulation_periods - 1) * overtime_length +
                       (overtime_length - clock_seconds))
        # ESPN wallclock timestamps can disagree with the authoritative game-clock order.
        # Use a monotonic scheduled-start + period-clock estimate for both leagues.
        wallclock = nek.iso_utc(kickoff + timedelta(seconds=elapsed))
        team = item.get("team") or {}
        if isinstance(team, dict):
            team = {"abbreviation": team.get("abbreviation") or team.get("displayName")}
        type_value = item.get("type") or {}
        type_label = field(type_value, "text")
        drive = item.get("drive") or {}
        drive_id = field(drive, "id")
        normalized_input.append({
            "id": item.get("id"), "period": {"number": period},
            "clock": {"displayValue": clock_value}, "wallclock": wallclock,
            "homeScore": item.get("homeScore"), "awayScore": item.get("awayScore"),
            "team": team, "type": {"text": type_label},
            "scoringPlay": bool(item.get("scoringPlay", league == "nfl")),
            "scoreValue": item.get("scoreValue"), "drive": {"id": drive_id} if drive_id else {},
            "start": item.get("start"), "isTurnover": bool(item.get("isTurnover")),
            "participants": [{"athlete": {"id": p.get("athlete", {}).get("id")}}
                             for p in item.get("participants") or []
                             if isinstance(p, dict) and isinstance(p.get("athlete"), dict)],
        })
    plays = nek.normalize_espn_plays(normalized_input, league=league,
                                    game_id=str(game["espn_event_id"]),
                                    captured_at=captured_at)
    if league == "nba":
        for play in plays:
            if play.get("team"):
                try:
                    play["team"] = _nba_code(play["team"])
                except ValueError:
                    play["team"] = None
    return plays, scope, source_time_basis


def nfl_week_metadata(page_html: str, week: int) -> dict[str, Any]:
    parser = _MetaHTML()
    parser.feed(page_html)
    return {
        "league": "nfl", "week": int(week), "publisher": "nfl.com",
        "source_discovery": "nfl.com_what_we_learned",
        "headline": parser.meta.get("og:title"),
        "published_at": _utc_db(parser.meta.get("article:published_time") or
                                 parser.meta.get("datepublished")),
        "url": _safe_url(parser.canonical) or
               f"https://www.nfl.com/news/2026-nfl-season-week-{week}-what-we-learned-from-sunday-s-games",
        "status": "found" if parser.meta.get("og:title") else "page_metadata_missing",
        "coverage_scope": "weekly_rollup",
        "article_body_retained": False,
    }


def _fetcher(paced_http, *, min_interval: float, budget: int, user_agent: str | None = None):
    headers = {"User-Agent": user_agent} if user_agent else None
    return paced_http.Fetcher(min_interval=min_interval, retry_waits=(), headers=headers,
                              timeout=30, cache_dir="", cache_ttl=0,
                              host_budget=budget, on_exhausted="sleep")


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "code", None)


def collect_core_pbp(games: list[dict[str, Any]], capture_stamp: str) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=3.0, budget=100)
    rows: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    whistles: dict[str, str] = {}
    calls = 0
    refused = False
    for index, game in enumerate(games, start=1):
        if refused:
            rows.append({"league": game["league"], "game_id": game["espn_event_id"],
                         "status": "not_requested_after_host_refusal"})
            continue
        sport = "football" if game["league"] == "nfl" else "basketball"
        event_id = game["espn_event_id"]
        url = (f"https://sports.core.api.espn.com/v2/sports/{sport}/leagues/"
               f"{game['league']}/events/{event_id}/competitions/{event_id}/plays"
               f"?limit={PBP_PAGE_LIMIT}")
        calls += 1
        try:
            payload = fetch.json(url, ttl=0)
            items = payload.get("items") or []
            page_count = int(payload.get("pageCount") or 1)
            if page_count != 1 or any(not isinstance(item, dict) or "$ref" in item for item in items):
                rows.append({"league": game["league"], "game_id": event_id,
                             "status": "incomplete_pagination_or_references",
                             "page_count": page_count})
                continue
            captured = utc_now()
            plays = nek.normalize_espn_plays(items, league=game["league"],
                                             game_id=event_id, captured_at=captured)
            if game["league"] == "nba":
                for play in plays:
                    if play.get("team"):
                        try:
                            play["team"] = _nba_code(play["team"])
                        except ValueError:
                            play["team"] = None
            try:
                derived = nek.derive_game_events(
                    league=game["league"], game_id=event_id,
                    home_team=game["home_team"], away_team=game["away_team"],
                    final_home_score=int(game["home_score"]),
                    final_away_score=int(game["away_score"]), plays=plays)
            except nek.NarrativeDataError as exc:
                rows.append({"league": game["league"], "game_id": event_id,
                             "status": "score_or_timeline_validation_failed",
                             "error_class": type(exc).__name__})
                continue
            if plays:
                whistles[event_id] = plays[-1]["occurred_at"]
            facts.extend(derived)
            rows.append({"league": game["league"], "game_id": event_id,
                         "status": "validated", "play_count": len(plays),
                         "event_time_basis": "publisher_wallclock",
                         "capture_at": captured,
                         "first_play_at": plays[0]["occurred_at"] if plays else None,
                         "last_play_at": plays[-1]["occurred_at"] if plays else None,
                         "source_url": url})
        except Exception as exc:
            rows.append({"league": game["league"], "game_id": event_id,
                         "status": "fetch_error", "http_status": _status_code(exc),
                         "error_class": type(exc).__name__})
            if _status_code(exc) in {403, 429}:
                refused = True
        if index % 10 == 0:
            print(f"ESPN Core PBP: {index}/{len(games)} games; {calls} requests", flush=True)
    return {"rows": rows, "facts": facts, "whistles": whistles,
            "requests": calls, "host": "sports.core.api.espn.com"}


def collect_summary_pbp(games: list[dict[str, Any]]) -> dict[str, Any]:
    """Use publisher summary timelines: full NBA plays, NFL score plays only."""
    import paced_http
    fetch = _fetcher(paced_http, min_interval=3.0, budget=100)
    rows: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    normalized_plays: list[dict[str, Any]] = []
    first_plays: dict[str, str] = {}
    last_plays: dict[str, str] = {}
    calls = 0
    refused = False
    for index, game in enumerate(games, start=1):
        event_id = str(game["espn_event_id"])
        if refused:
            rows.append({"league": game["league"], "game_id": event_id,
                         "status": "not_requested_after_host_refusal"})
            continue
        sport = "football" if game["league"] == "nfl" else "basketball"
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{game['league']}/summary"
               f"?event={event_id}")
        calls += 1
        try:
            payload = fetch.json(url, ttl=0)
            # The same response may contain an article object. Do not inspect or retain it.
            payload.pop("article", None)
            captured = utc_now()
            plays, scope, time_basis = normalize_summary_timeline(payload, game, captured)
            source = ("espn_site_summary_full_pbp" if scope == "full_play_by_play" else
                      "espn_site_summary_scoring_plays")
            derived = nek.derive_game_events(
                league=game["league"], game_id=event_id,
                home_team=game["home_team"], away_team=game["away_team"],
                final_home_score=int(game["home_score"]),
                final_away_score=int(game["away_score"]), plays=plays, source=source)
            status = "validated" if scope == "full_play_by_play" else "validated_scoring_timeline"
            facts.extend(derived)
            normalized_plays.extend(plays)
            first_at = plays[0]["occurred_at"] if plays else None
            last_at = plays[-1]["occurred_at"] if plays else None
            if game["league"] == "nba" and first_at and last_at:
                first_plays[event_id] = first_at
                last_plays[event_id] = last_at
            rows.append({"league": game["league"], "game_id": event_id,
                         "status": status, "timeline_scope": scope,
                         "event_time_basis": time_basis, "play_count": len(plays),
                         "capture_at": captured, "first_play_at": first_at,
                         "last_play_at": last_at, "source_url": url})
        except nek.NarrativeDataError as exc:
            rows.append({"league": game["league"], "game_id": event_id,
                         "status": "timeline_validation_failed",
                         "error_class": type(exc).__name__})
        except Exception as exc:
            rows.append({"league": game["league"], "game_id": event_id,
                         "status": "fetch_error", "http_status": _status_code(exc),
                         "error_class": type(exc).__name__})
            if _status_code(exc) in {403, 429}:
                refused = True
        if index % 10 == 0:
            print(f"ESPN site summary timelines: {index}/{len(games)} games; {calls} requests",
                  flush=True)
    return {"rows": rows, "facts": facts, "normalized_plays": normalized_plays,
            "first_plays": first_plays, "last_plays": last_plays,
            "requests": calls, "host": "site.api.espn.com"}


def collect_nfl_espn_articles(games: list[dict[str, Any]], *,
                              include_scoreboards: bool = True) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=3.0, budget=52,
                     user_agent="curl/8.5.0")
    rows = []
    calls = 0
    refused = False
    start_date = datetime.now(timezone.utc).strftime("%Y%m%d")
    nba_end = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y%m%d")
    nfl_end = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y%m%d")
    scoreboards = {"nba": [], "nfl": []}
    if include_scoreboards:
        for league, sport, end_date in (("nba", "basketball", nba_end), ("nfl", "football", nfl_end)):
            scoreboard_url = (f"https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
                              f"?dates={start_date}-{end_date}&limit=100")
            try:
                calls += 1
                scoreboards[league] = _scoreboard_games(fetch.json(scoreboard_url, ttl=0), league)
            except Exception as exc:
                if _status_code(exc) in {403, 429}:
                    refused = True
                    break
    for index, game in enumerate(games, start=1):
        if refused:
            rows.append({"league": "nfl", "game_id": game["espn_event_id"],
                         "status": "not_requested_after_host_refusal"})
            continue
        url = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
               f"?event={game['espn_event_id']}")
        try:
            calls += 1
            payload = fetch.json(url, ttl=0)
            rows.append(espn_summary_metadata(payload, game))
        except Exception as exc:
            rows.append({"league": "nfl", "game_id": game["espn_event_id"],
                         "publisher": "espn", "status": "fetch_error",
                         "http_status": _status_code(exc), "error_class": type(exc).__name__})
            if _status_code(exc) in {403, 429}:
                refused = True
        if index % 10 == 0:
            print(f"ESPN NFL article metadata: {index}/{len(games)} games; {calls} requests",
                  flush=True)
    return {"rows": rows, "nba_scoreboard_games": scoreboards["nba"],
            "nfl_scoreboard_games": scoreboards["nfl"],
            "requests": calls, "host": "site.api.espn.com"}


def _scoreboard_games(payload: dict[str, Any], league: str) -> list[dict[str, Any]]:
    out = []
    for event in payload.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        teams = {}
        for row in comp.get("competitors") or []:
            side = row.get("homeAway")
            team = row.get("team") or {}
            if side in {"home", "away"} and team.get("abbreviation"):
                teams[side] = team["abbreviation"]
        if len(teams) == 2:
            out.append({"league": league, "event_id": str(event.get("id")),
                        "date": event.get("date"), "home_team": teams["home"],
                        "away_team": teams["away"]})
    return out


def collect_nba_pages(games: list[dict[str, Any]]) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=2.0, budget=100,
                     user_agent="Mozilla/5.0 (compatible; LPResearch/1.0)")
    rows = []
    calls = 0
    refused = False
    for index, game in enumerate(games, start=1):
        if refused:
            rows.append({"league": "nba", "game_id": game["game_page_id"],
                         "status": "not_requested_after_host_refusal"})
            continue
        url = f"https://www.nba.com/game/{game['game_page_id']}"
        try:
            calls += 1
            page_html = fetch.text(url, ttl=0)
            # Only known article header fields are copied out; the HTML and its full
            # story JSON are discarded immediately after this call returns.
            rows.append(nba_com_game_metadata(page_html, game))
            del page_html
        except Exception as exc:
            rows.append({"league": "nba", "game_id": game["game_page_id"],
                         "publisher": "nba.com", "status": "fetch_error",
                         "http_status": _status_code(exc), "error_class": type(exc).__name__})
            if _status_code(exc) in {403, 429}:
                refused = True
        if index % 10 == 0:
            print(f"NBA.com metadata: {index}/{len(games)} games; {calls} requests", flush=True)
    return {"rows": rows, "requests": calls, "host": "www.nba.com"}


def collect_nfl_weeklies(weeks: tuple[int, ...] = NFL_WEEKS) -> dict[str, Any]:
    import paced_http
    fetch = _fetcher(paced_http, min_interval=2.0, budget=10,
                     user_agent="Mozilla/5.0 (compatible; LPResearch/1.0)")
    rows = []
    calls = 0
    refused = False
    for week in weeks:
        if refused:
            rows.append({"league": "nfl", "week": week, "publisher": "nfl.com",
                         "status": "not_requested_after_host_refusal",
                         "coverage_scope": "weekly_rollup"})
            continue
        url = (f"https://www.nfl.com/news/2026-nfl-season-week-{week}-"
               "what-we-learned-from-sunday-s-games")
        try:
            calls += 1
            page_html = fetch.text(url, ttl=0)
            rows.append(nfl_week_metadata(page_html, week))
            del page_html
        except Exception as exc:
            rows.append({"league": "nfl", "week": week, "publisher": "nfl.com",
                         "status": "fetch_error", "http_status": _status_code(exc),
                         "error_class": type(exc).__name__, "coverage_scope": "weekly_rollup"})
            if _status_code(exc) in {403, 429}:
                refused = True
    return {"rows": rows, "requests": calls, "host": "www.nfl.com"}


def _db_story_audit(con: sqlite3.Connection, games: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for league in ("nfl", "nba"):
        cols = [row[1] for row in con.execute("PRAGMA table_info(game_story)")]
        indexes = [tuple(row) for row in con.execute("PRAGMA index_list(game_story)")]
        counts = [tuple(row) for row in con.execute(
            "SELECT league, COUNT(*), SUM(has_stakes=1), SUM(deterministic=1) "
            "FROM game_story WHERE league=? GROUP BY league", (league,))]
        result[league] = {"columns": cols, "indexes": indexes, "current_counts": counts}
    current = []
    for game in games:
        story = con.execute(
            "SELECT generated_at,has_form,has_stakes,deterministic FROM game_story "
            "WHERE league=? AND game_id=?", (game["league"], str(game["espn_event_id"]))).fetchone()
        current.append({"league": game["league"], "game_id": str(game["espn_event_id"]),
                        "generated_at": story[0] if story else None,
                        "has_form": story[1] if story else None,
                        "has_stakes": story[2] if story else None,
                        "deterministic": story[3] if story else None,
                        "stored_version_count": 1 if story else 0,
                        "prior_preview_recoverable": False if story else None})
    news_counts = [tuple(row) for row in con.execute(
        "SELECT league,source,COUNT(*),COUNT(DISTINCT url) FROM news_items "
        "WHERE league IN ('nfl','nba') AND lower(source) LIKE '%espn%' "
        "GROUP BY league,source ORDER BY league,source")]
    result["sample_story_rows"] = current
    result["espn_news_metadata_counts"] = news_counts
    return result


def _story_versions_for_targets(con, targets: list[dict[str, Any]], as_of: str) -> list[dict[str, Any]]:
    out = []
    asof = nek.parse_utc(as_of)
    for target in targets:
        if not target.get("espn_event_id"):
            continue
        row = con.execute("SELECT story,generated_at FROM game_story WHERE league=? AND game_id=?",
                          (target["league"], str(target["espn_event_id"]))).fetchone()
        if not row:
            continue
        generated = nek.parse_utc(_utc_db(row["generated_at"]))
        kickoff = nek.parse_utc(target["start_utc"])
        if not generated or not kickoff or not asof or generated > asof or generated >= kickoff:
            continue
        out.append({"target_game_id": str(target["espn_event_id"]),
                    "league": target["league"], "story_kind": "pregame_preview",
                    "generator": "existing_game_story_cache", "generated_at": _utc_db(row["generated_at"]),
                    "preview": str(row["story"] or ""), "source_event_ids": []})
    return out


def _sample_game_story_versions(con, games, first_plays, last_plays) -> list[dict[str, Any]]:
    """Snapshot the one currently stored version with a timing-derived kind label."""
    out = []
    for game in games:
        game_id = str(game["espn_event_id"])
        row = con.execute("SELECT story,generated_at FROM game_story WHERE league=? AND game_id=?",
                          (game["league"], game_id)).fetchone()
        if not row:
            continue
        generated = nek.parse_utc(_utc_db(row["generated_at"]))
        start = nek.parse_utc(first_plays.get(game_id))
        end = nek.parse_utc(last_plays.get(game_id))
        if generated and start and generated < start:
            kind = "pregame_preview"
        elif generated and end and generated >= end:
            kind = "postgame_recap"
        else:
            kind = "timing_unknown_or_during_game"
        out.append({"target_game_id": game_id, "league": game["league"],
                    "story_kind": kind, "generator": "existing_game_story_cache",
                    "generated_at": _utc_db(row["generated_at"]),
                    "preview": str(row["story"] or ""), "source_event_ids": [],
                    "source_game_ids": [str(game.get("source_game_id") or game_id)],
                    "version_status": "only_current_row_recoverable"})
    return out


def _env_value(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    for path in ("/root/legendarypicks/.env", "/root/.hermes/.env"):
        try:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'") or default
        except OSError:
            continue
    return default


def _configured_inference_providers():
    """Mirror the repo's configured `_llm_chat` provider order without importing `_core`.

    `_core` calls `_init_db()` at import time; this research script must not initialize
    or write an application database just to use its model settings.
    """
    configured = (_env_value("LP_LLM_PROVIDERS", "nous,openrouter") or "nous,openrouter")
    model = _env_value("LP_LLM_MODEL", "deepseek/deepseek-v4.1-flash")
    providers = []
    for provider in (part.strip() for part in configured.split(",")):
        if provider == "nous":
            key = (_env_value("NOUS_PORTAL_KEY") or _env_value("NOUS_API_KEY"))
            if key:
                base = _env_value("NOUS_BASE_URL", "https://inference-api.nousresearch.com/v1")
                providers.append((provider, str(base).rstrip("/") + "/chat/completions", key))
        elif provider == "openrouter":
            key = _env_value("OPENROUTER_API_KEY")
            if key:
                providers.append((provider, "https://openrouter.ai/api/v1/chat/completions", key))
        elif provider == "deepseek":
            key = _env_value("DEEPSEEK_API_KEY")
            if key:
                providers.append((provider, "https://api.deepseek.com/v1/chat/completions", key))
    return model, providers


def _grounded_llm_preview(target: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the configured DeepSeek model to phrase a supplied, already-filtered fact set."""
    model, providers = _configured_inference_providers()
    if not providers:
        return {"status": "no_configured_provider", "preview": None, "cited_event_ids": []}
    system = (
        "Write a concise pregame sports preview from the supplied verified facts only. "
        "Use one or two sentences. Do not predict a winner, add statistics, infer injuries, "
        "or describe any game outcome beyond what a fact explicitly states. If the facts do "
        "not support a useful sentence, return an empty preview. Return JSON with exactly "
        "two keys: preview (string) and cited_event_ids (array of supplied event_id values)."
    )
    payload_facts = [{"event_id": f["event_id"], "category": f["category"], "team": f.get("team"),
                      "occurred_at": f["occurred_at"], "available_at": f["available_at"],
                      "calculation": f["calculation"],
                      "supporting_game_ids": f["supporting_game_ids"],
                      "supporting_event_ids": f["supporting_event_ids"]} for f in facts]
    user = json.dumps({"league": target["league"], "home_team": target["home_team"],
                       "away_team": target["away_team"], "facts": payload_facts},
                      ensure_ascii=False, sort_keys=True)
    body = json.dumps({"model": model, "temperature": 0.4, "max_tokens": 600,
                       "reasoning_effort": "none",
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}).encode("utf-8")
    tried = []
    for provider, endpoint, key in providers:
        req = urllib.request.Request(
            endpoint, data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                     "User-Agent": "legendarypicks-research/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                response_data = json.loads(response.read().decode("utf-8"))
            content = str(response_data["choices"][0]["message"].get("content") or "").strip()
        except urllib.error.HTTPError as exc:
            tried.append({"provider": provider, "status": int(exc.code)})
            if exc.code in {401, 402, 403}:
                continue
            continue
        except Exception as exc:
            tried.append({"provider": provider, "error_class": type(exc).__name__})
            continue
        try:
            decoded = json.loads(content)
            preview = str(decoded.get("preview") or "").strip()
            cited = decoded.get("cited_event_ids") or []
            allowed = {str(f["event_id"]) for f in facts}
            if not isinstance(cited, list) or not set(map(str, cited)).issubset(allowed):
                return {"status": "invalid_citation_ids", "preview": None,
                        "cited_event_ids": [], "provider": provider, "model": model}
            return {"status": "ok" if preview else "empty_preview", "preview": preview or None,
                    "cited_event_ids": sorted(set(map(str, cited))),
                    "provider": provider, "model": model}
        except (json.JSONDecodeError, AttributeError, TypeError):
            return {"status": "invalid_json", "preview": None, "cited_event_ids": [],
                    "provider": provider, "model": model}
    return {"status": "providers_failed", "preview": None, "cited_event_ids": [],
            "provider_attempts": tried, "model": model}


def _unsupported_numbers(preview: str | None, facts: list[dict[str, Any]]) -> list[str]:
    if not preview:
        return []
    allowed: set[str] = set()
    def gather(value):
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float)):
            allowed.add(str(int(value)) if float(value).is_integer() else str(value))
        elif isinstance(value, dict):
            for child in value.values(): gather(child)
        elif isinstance(value, list):
            for child in value: gather(child)
    for fact in facts:
        gather(fact.get("calculation", {}))
    found = re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", preview)
    return sorted(set(token for token in found if token not in allowed))


def _trigram_overlap(left: str | None, right: str | None) -> float:
    def grams(text):
        tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        return {tuple(tokens[i:i + 3]) for i in range(max(0, len(tokens) - 2))}
    a, b = grams(left), grams(right)
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 4)


def _future_nfl_targets(con: sqlite3.Connection, as_of: str, count: int = 12) -> list[dict[str, Any]]:
    date_cutoff = as_of[:10]
    out = []
    for row in con.execute(
            """SELECT CAST(espn AS TEXT) espn_event_id,game_id,season,gameday,away_team,home_team
               FROM nfl_schedule WHERE season=2026 AND game_type='REG' AND gameday>?
                 AND espn IS NOT NULL ORDER BY gameday,week,game_id LIMIT ?""",
            (date_cutoff, count)):
        item = dict(row)
        item.update({"league": "nfl", "game_date": item["gameday"],
                     "start_utc": f"{item['gameday']}T00:00:00Z",
                     "game_id": item["espn_event_id"]})
        out.append(item)
    return out


def _future_nba_targets(con: sqlite3.Connection, as_of: str, count: int = 12) -> list[dict[str, Any]]:
    out = []
    for row in con.execute(
            """SELECT game_id,game_date,start_utc,away_team,home_team
               FROM nba_schedule WHERE season=? AND season_type='REG' AND status=1
                 AND start_utc>? ORDER BY start_utc,game_id LIMIT ?""",
            (NBA_SEASON, as_of, count)):
        item = dict(row)
        item.update({"league": "nba", "game_page_id": str(item["game_id"]),
                     "game_id": None, "espn_event_id": None, "sample_role": "pregame_target",
                     "season_phase": "regular"})
        item["home_team"], item["away_team"] = (
            _nba_code(item["home_team"]), _nba_code(item["away_team"]))
        out.append(item)
    return out


def _attach_nba_event_ids(targets: list[dict[str, Any]],
                         scoreboard: list[dict[str, Any]]) -> None:
    for target in targets:
        if target.get("league") != "nba":
            continue
        expected_teams = frozenset((_nba_code(target["home_team"]), _nba_code(target["away_team"])))
        start = nek.parse_utc(target.get("start_utc"))
        matches = []
        for row in scoreboard:
            try:
                pair = frozenset((_nba_code(row["home_team"]), _nba_code(row["away_team"])))
            except (ValueError, TypeError):
                continue
            event_time = nek.parse_utc(row.get("date"))
            if not start or not event_time or pair != expected_teams:
                continue
            # The scoreboard and local schedule normally agree exactly; allow a
            # two-minute publisher rounding difference, never a name-only join.
            if abs((event_time - start).total_seconds()) <= 120:
                matches.append(row)
        if len(matches) == 1:
            target["espn_event_id"] = matches[0]["event_id"]
            target["game_id"] = matches[0]["event_id"]
            target["event_crosswalk_status"] = "unique_team_and_start_time"
        else:
            target["event_crosswalk_status"] = "ambiguous_or_unmatched"


def _attach_nfl_start_times(targets: list[dict[str, Any]], scoreboard: list[dict[str, Any]]) -> None:
    by_id = {str(row.get("event_id")): row for row in scoreboard if row.get("event_id")}
    for target in targets:
        row = by_id.get(str(target.get("espn_event_id")))
        start = nek.parse_utc(row.get("date")) if row else None
        if start:
            target["start_utc"] = nek.iso_utc(start)
            target["event_crosswalk_status"] = "schedule_espn_id_verified"
        else:
            target["event_crosswalk_status"] = "schedule_id_only_date_boundary"


def _standings_events(con: sqlite3.Connection, game: dict[str, Any], end_at: str,
                      available_at: str) -> list[dict[str, Any]]:
    """Record-only standings delta; no ranks, clinches, or tie-break claims."""
    league = game["league"]
    if league == "nfl":
        rows = [dict(r) for r in con.execute(
            """SELECT game_id,gameday,home_team,away_team,home_score,away_score
               FROM nfl_schedule WHERE season=? AND game_type='REG'
                 AND away_score IS NOT NULL AND home_score IS NOT NULL AND gameday<=?""",
            (int(game["season"]), game["game_date"]))]
        current_id = str(game["source_game_id"])
        id_key = "game_id"
        date_key = "gameday"
    else:
        rows = [dict(r) for r in con.execute(
            """SELECT source_game_id AS game_id,game_date,home AS home_team,away AS away_team,
                      home_score,away_score
               FROM nba_sportsdataverse_games WHERE source_season=? AND game_type='REG'
                 AND home_score IS NOT NULL AND away_score IS NOT NULL AND game_date<=?""",
            (int(game.get("season_year") or game["season"]), game["game_date"]))]
        current_id = str(game["source_game_id"])
        id_key = "game_id"
        date_key = "game_date"
    prior = [r for r in rows if str(r[id_key]) != current_id and str(r[date_key]) < game["game_date"]]
    selected = [r for r in rows if str(r[id_key]) == current_id]
    if len(selected) != 1:
        return []
    current = selected[0]
    facts = []
    for team, score_for, score_against in (
            (current["home_team"], current["home_score"], current["away_score"]),
            (current["away_team"], current["away_score"], current["home_score"])):
        prior_record = {"wins": 0, "losses": 0, "ties": 0}
        support_games = [str(current_id)]
        for row in prior:
            if team not in (row["home_team"], row["away_team"]):
                continue
            own = row["home_score"] if row["home_team"] == team else row["away_score"]
            opp = row["away_score"] if row["home_team"] == team else row["home_score"]
            prior_record["wins" if own > opp else "losses" if own < opp else "ties"] += 1
            support_games.append(str(row[id_key]))
        outcome = "win" if score_for > score_against else "loss" if score_for < score_against else "tie"
        post = dict(prior_record)
        post[{"win": "wins", "loss": "losses", "tie": "ties"}[outcome]] += 1
        event_id = f"{game['espn_event_id']}:standings:{team}"
        facts.append({
            "schema_version": nek.SCHEMA_VERSION, "league": league,
            "game_id": str(game["espn_event_id"]), "event_id": event_id,
            "category": "standings_record", "source": f"repository:{league}_schedule",
            "team": str(team), "occurred_at": end_at, "available_at": available_at,
            "supporting_game_ids": sorted(set(support_games)),
            "supporting_event_ids": sorted(set(support_games)),
            "calculation": {"record_before": prior_record, "game_outcome": outcome,
                            "record_after": post,
                            "previous_games_same_calendar_date_excluded": True,
                            "claim_scope": "win_loss_record_only"},
            "verified": True,
        })
    return facts


def _player_log_rows(con: sqlite3.Connection, games: list[dict[str, Any]],
                     first_plays: dict[str, str]):
    logs_by_game = defaultdict(list)
    all_players = set()
    game_lookup = {str(g["espn_event_id"]): g for g in games}
    for game in games:
        if game["league"] == "nba":
            db_game_id = str(game["espn_event_id"])
        else:
            db_game_id = str(game["source_game_id"])
        rows = list(con.execute(
            """SELECT id,player_id,league,season,game_type,game_id,game_date,team,
                      stats,source,source_player_key,ingested_at
               FROM player_game_logs WHERE league=? AND game_id=?""",
            (game["league"], db_game_id)))
        for row in rows:
            if row["player_id"] is None:
                continue
            item = dict(row)
            item["log_id"] = str(item.pop("id"))
            item["available_at"] = _utc_db(item.pop("ingested_at"))
            item["stats"] = json.loads(item["stats"] or "{}")
            item["player_id"] = str(item["player_id"])
            item["game_start"] = first_plays.get(str(game["espn_event_id"]))
            item["game_type"] = item.get("game_type") or "REG"
            item["fact_game_id"] = str(game["espn_event_id"])
            logs_by_game[db_game_id].append(item)
            all_players.add(item["player_id"])
    # Pull history by canonical ID; retain only allowlisted stats and required times.
    histories = []
    player_ids = sorted(all_players)
    for start in range(0, len(player_ids), 400):
        batch = player_ids[start:start + 400]
        marks = ",".join("?" for _ in batch)
        if not batch:
            continue
        for row in con.execute(
                f"""SELECT id,player_id,league,game_type,game_id,game_date,team,stats,
                           source,source_player_key,ingested_at
                    FROM player_game_logs WHERE player_id IN ({marks}) AND league IN ('nfl','nba')""",
                batch):
            item = dict(row)
            item["log_id"] = str(item.pop("id"))
            item["available_at"] = _utc_db(item.pop("ingested_at"))
            item["stats"] = json.loads(item["stats"] or "{}")
            item["player_id"] = str(item["player_id"])
            # Historical game dates have no trustworthy start timestamp. UTC midnight
            # is only an ordering aid; the separate observed-at cutoff decides eligibility.
            date = str(item.get("game_date") or "")[:10]
            item["game_start"] = f"{date}T00:00:00Z" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
            item["game_type"] = item.get("game_type") or "REG"
            histories.append(item)
    history_by_log_id = {row["log_id"]: row for row in histories}
    for game in games:
        db_game_id = str(game["espn_event_id"] if game["league"] == "nba" else game["source_game_id"])
        first = first_plays.get(str(game["espn_event_id"]))
        for target in logs_by_game.get(db_game_id, []):
            target["game_start"] = first
            if target["log_id"] in history_by_log_id:
                history_by_log_id[target["log_id"]]["game_start"] = first
    return logs_by_game, histories


def _add_player_facts(games, first_plays, whistles, con) -> list[dict[str, Any]]:
    log_games, histories = _player_log_rows(con, games, first_plays)
    facts = []
    for game in games:
        db_game_id = str(game["espn_event_id"] if game["league"] == "nba" else game["source_game_id"])
        target_logs = log_games.get(db_game_id, [])
        if not target_logs or not whistles.get(str(game["espn_event_id"])):
            continue
        first_play = first_plays.get(str(game["espn_event_id"]))
        last_play = whistles[str(game["espn_event_id"])]
        if not first_play or not last_play:
            continue
        available = max((row.get("available_at") for row in target_logs if row.get("available_at")),
                        default=None)
        if not available:
            continue
        # Translate each target log to an ESPN event game ID for the pure feature builder,
        # while keeping the database game ID as an explicit supporting source ID.
        for row in target_logs:
            row["game_id"] = db_game_id
        event_facts = nek.derive_player_outliers(
            league=game["league"], target_game_id=db_game_id, fact_game_id=str(game["espn_event_id"]),
            target_start=first_play, target_end=last_play, target_available_at=available,
            logs=histories)
        facts.extend(event_facts)
    return facts


def _render_deterministic_preview(target: dict[str, Any], context: list[dict[str, Any]],
                                  player_names: dict[str, str]) -> str:
    team_names = {target["home_team"].upper(): target["home_team"],
                  target["away_team"].upper(): target["away_team"]}
    parts = []
    for fact in context:
        team = fact.get("team")
        if fact["category"] == "comeback":
            amount = fact["calculation"]["largest_deficit_overcome"]
            parts.append(f"{team_names.get(team, team)} comes off a comeback that erased a {amount}-point deficit.")
        elif fact["category"] == "decisive_score" and fact["calculation"].get("play_type"):
            play_type = str(fact["calculation"]["play_type"])
            play_type = re.sub(r"\s*[-–]\s*\d+\s+of\s+\d+.*$", "", play_type, flags=re.I)
            play_type = re.sub(r"\b3\s*(?:[- ]\s*)?(?:pt|point)\b", "three-point", play_type, flags=re.I)
            play_type = re.sub(r"\b\d+\b", "", play_type)
            play_type = re.sub(r"\s+", " ", play_type).strip(" -").lower()
            if play_type:
                parts.append(f"{team_names.get(team, team)} won its previous game on a {play_type}.")
        elif fact["category"] == "fourth_down_attempts":
            c = fact["calculation"]
            parts.append(f"The previous game included {c['attempts']} fourth-down attempts, with {c['failed']} failed and {c['converted']} converted.")
        elif fact["category"] == "player_outlier":
            c = fact["calculation"]
            name = player_names.get(c["player_id"], f"Player {c['player_id']}")
            parts.append(f"{name} recorded {c['value']:g} {c['stat']} after averaging {c['prior_mean']:g} across {c['prior_games']} prior available games.")
        elif fact["category"] == "scoring_run" and fact["calculation"]["meets_highlight_threshold"]:
            parts.append(f"{team_names.get(team, team)} had a {fact['calculation']['points']}-point scoring run in its previous game.")
    return " ".join(parts[:3])


def _local_news_metadata_audit(con: sqlite3.Connection) -> dict[str, Any]:
    # `body` is intentionally absent from this projection.
    rows = [dict(row) for row in con.execute(
        "SELECT league,source,headline,url,published FROM news_items "
        "WHERE league IN ('nfl','nba') AND lower(source) LIKE '%espn%'")]
    out = {}
    for league in ("nfl", "nba"):
        subset = [r for r in rows if r["league"] == league]
        unique_keys = {_duplicate_key({"headline": r["headline"], "published_at": r["published"]})
                       for r in subset}
        out[league] = {"rows": len(subset), "unique_urls": len({r["url"] for r in subset}),
                       "distinct_headline_date_keys": sum(1 for key in unique_keys if key),
                       "sources": dict(Counter(r["source"] for r in subset))}
    return out


def _article_detector_comparison(metadata: list[dict[str, Any]], facts: list[dict[str, Any]],
                                 validated_games: set[tuple[str, str]]) -> list[dict[str, Any]]:
    by_game = defaultdict(set)
    for fact in facts:
        by_game[(fact["league"], str(fact["game_id"]))].add(fact["category"])
    out = []
    for row in metadata:
        if (row.get("coverage_scope", "single_game") != "single_game" or
                row.get("status") != "found" or
                (row["league"], str(row["game_id"])) not in validated_games):
            continue
        cats = by_game[(row["league"], str(row["game_id"]))]
        labels = row.get("headline_theme_candidates") or []
        hits, misses = [], []
        for label in labels:
            (hits if cats.intersection(_THEME_EVENT_CATEGORIES.get(label, set())) else misses).append(label)
        out.append({"league": row["league"], "game_id": str(row["game_id"]),
                    "publisher": row["publisher"], "origin_class": row["origin_class"],
                    "headline_theme_candidates": labels,
                    "detected_by_event_facts": hits,
                    "not_detected_by_event_facts": misses,
                    "detected_categories": sorted(cats),
                    "annotation_source": "headline_metadata_only"})
    return out


def _duplicate_audit(metadata: list[dict[str, Any]]) -> dict[str, Any]:
    groups = defaultdict(list)
    url_groups = defaultdict(list)
    for row in metadata:
        if row.get("status") != "found":
            continue
        key = row.get("duplicate_key") or _duplicate_key(row)
        if key:
            groups[key].append({"league": row.get("league"), "game_id": row.get("game_id"),
                                "publisher": row.get("publisher"), "url": row.get("url")})
        url = _safe_url(row.get("url"))
        if url:
            url_groups[url].append({"league": row.get("league"), "game_id": row.get("game_id"),
                                    "publisher": row.get("publisher"), "url": url})
    duplicates = [items for items in groups.values() if len(items) > 1]
    url_duplicates = [items for items in url_groups.values() if len(items) > 1]
    return {"articles_found": sum(1 for row in metadata if row.get("status") == "found"),
            "headline_date_comparable_articles": sum(len(group) for group in groups.values()),
            "unique_headline_date_keys": len(groups), "duplicate_groups": duplicates,
            "duplicate_article_copies": sum(len(group) - 1 for group in duplicates),
            "unique_urls": len(url_groups), "url_duplicate_groups": url_duplicates,
            "url_duplicate_copies": sum(len(group) - 1 for group in url_duplicates)}


def _report(*, story_audit, local_news, samples, publisher_rows, event_facts,
            article_checks, duplicate_audit, requests, capture_at, llm_status="not_run",
            blind_comparison_count=0, paired_targets_by_league=None,
            single_variant_targets_by_league=None, numeric_evidence_stats=None) -> str:
    nba_rows = [row for row in publisher_rows if row.get("source_discovery") == "nba.com_game_summary"]
    nfl_espn = [row for row in publisher_rows if row.get("source_discovery") == "espn_nfl_summary"]
    nfl_weekly = [row for row in publisher_rows if row.get("publisher") == "nfl.com"]
    event_counts = Counter((f["league"], f["category"]) for f in event_facts)
    validated = Counter((row["league"], row["status"]) for row in requests.get("pbp_rows", []))
    nba_found = sum(row.get("status") == "found" for row in nba_rows)
    nba_ap = sum(row.get("status") == "found" and row.get("origin_class") == "ap_origin"
                 for row in nba_rows)
    nfl_found = sum(row.get("status") == "found" for row in nfl_espn)
    nfl_ap = sum(row.get("status") == "found" and row.get("origin_class") == "ap_origin"
                 for row in nfl_espn)
    matched = sum(bool(row["detected_by_event_facts"]) for row in article_checks)
    labels = sum(len(row["headline_theme_candidates"]) for row in article_checks)
    hits = sum(len(row["detected_by_event_facts"]) for row in article_checks)
    delay_count = sum(row.get("publication_delay_seconds_from_final_whistle") is not None
                      for row in publisher_rows)
    nfl_validated = validated[("nfl", "validated")] + validated[("nfl", "validated_scoring_timeline")]
    nba_validated = validated[("nba", "validated")]
    validated_count = nfl_validated + nba_validated
    lines = [
        "# Narrative event knowledge: research audit",
        "",
        f"**Captured:** {capture_at}  ",
        "**Mode:** research only; no application database writes; publisher bodies and play descriptions were not retained.",
        "",
        "## Samples",
        "",
        f"- NFL event sample: {len(samples['nfl'])} completed regular-season games, weeks 4–7, stratified 13/13/12/12.",
        f"- NBA event sample: {len(samples['nba_pbp'])} completed regular-season games from the 2025–26 season, selected as an even subset of the article sample.",
        f"- NBA article sample: {len(samples['nba_metadata'])} completed regular-season games, selected evenly across the 1,230-game 2025–26 regular-season data population; the 50-game event sample is nested inside it.",
        "",
        "## Current storage and collector audit",
        "",
        "- `game_story` has a `(league, game_id)` key and no story-kind/version column. The generator deletes and replaces that row, so a stored postgame row cannot recover an earlier preview. When a current row exists, its saved text is only one version; the database cannot tell whether a preview was ever generated before the recap.",
        f"- Sampled current story rows: NFL {sum(r['league']=='nfl' and r['stored_version_count'] for r in story_audit['sample_story_rows'])}/{len(samples['nfl'])}; NBA {sum(r['league']=='nba' and r['stored_version_count'] for r in story_audit['sample_story_rows'])}/{len(samples['nba_pbp'])}. Historical overwritten-preview count is not observable from this schema.",
        f"- Existing ESPN-tagged `news_items` metadata: NFL {local_news['nfl']['rows']} rows / {local_news['nfl']['unique_urls']} URLs; NBA {local_news['nba']['rows']} rows / {local_news['nba']['unique_urls']} URLs. The collector has headline, URL, publisher and published time columns; body/description was excluded from this audit query.",
        "- The existing ESPN collector stores short descriptions in `news_items.body` and an optional story fetcher stores full ESPN story text. This prototype reads no `body` column and does not call the full-story collector.",
        "",
        "## Article coverage in this sample",
        "",
        f"- NBA.com game pages with recap header metadata: {nba_found}/{len(samples['nba_metadata'])}; pages with AP origin explicitly identified in byline/credit metadata: {nba_ap}/{len(samples['nba_metadata'])}.",
        f"- ESPN per-game NFL summaries with article headline metadata: {nfl_found}/{len(samples['nfl'])}; articles with AP origin explicitly identified by source/byline metadata: {nfl_ap}/{len(samples['nfl'])}.",
        f"- NFL.com *What We Learned* weekly pages found: {sum(r.get('status')=='found' for r in nfl_weekly)}/{len(NFL_WEEKS)} sampled week pages. These are week-level packages, not one independent article per game.",
        f"- Duplicate audit: {duplicate_audit['duplicate_article_copies']} duplicate copies in {len(duplicate_audit['duplicate_groups'])} duplicate normalized headline/date groups among {duplicate_audit['headline_date_comparable_articles']} records with both fields; {duplicate_audit['url_duplicate_copies']} exact-URL duplicate copies in {len(duplicate_audit['url_duplicate_groups'])} groups. Mirrored articles can still use distinct URLs.",
        "- Headline labels are candidate labels only. This audit did not read or store article descriptions or article bodies; it therefore cannot claim coverage of themes that appear only inside the story.",
        (f"- Headline/event detector: {hits}/{labels} headline-derived candidate labels were represented by a corresponding structured event category ({matched} articles had at least one detected candidate). This measures headline agreement only; it is not a journalist-theme recall estimate."
         if validated_count else
         "- Headline/event comparison was not evaluated because no sample game had a validated PBP timeline."),
        (f"- Publication delay is available for {delay_count} fetched records, computed from publication time to the last structured PBP play. Treat it as an observed timestamp difference, not a wire-service latency guarantee."
         if delay_count else
         "- Publication delay is unavailable: the available game-clock timestamps are estimates, not measured final-whistle times."),
        "",
        "## Deterministic event prototype",
        "",
        (f"- PBP collection status: {requests.get('pbp_collection_status', 'not_run')}. "
         "The earlier ESPN Core sample was stopped after a 403; this resumed run did not retry that host."
         if requests.get("pbp_collection_status") in {"skipped_after_prior_403",
                                                       "summary_endpoint_after_prior_core_403",
                                                       "summary_endpoint_checkpoint_after_prior_core_403"} else
         f"- PBP collection status: {requests.get('pbp_collection_status', 'not_run')}."),
        f"- Validated timelines: NFL scoring-play timelines {validated[('nfl','validated_scoring_timeline')]}/{len(samples['nfl'])}; NBA full-play timelines {nba_validated}/{len(samples['nba_pbp'])}.",
        "- Event timestamps are estimates from scheduled kickoff plus period clock. They order plays reproducibly but do not establish an observed final-whistle time.",
        ("- The event validator requires unique play IDs, timezone-aware event timestamps, nondecreasing scores, and a terminal score matching the repository schedule; games failing any check are excluded from verified facts."
         if validated_count else
         "- The event validator requires unique play IDs, timezone-aware event timestamps, nondecreasing scores, and a terminal score matching the repository schedule. No sample timelines reached validation in this run."),
        "- Categories are calculated from structured score snapshots: comeback magnitude, non-tied lead changes, scoring runs, late scoring events, and decisive lead changes. NFL summary data contains scoring plays only, so drive, turnover, and fourth-down facts are not inferred. NBA summary data provides full play rows; only event flags present in that source are used.",
        "- Player outliers use canonical `player_id` and prior logs whose ingestion timestamp is at or before the sample game's first play. The baseline is per-player and game-type, requires five prior available games, and is not role-adjusted. Incomplete availability timestamps are omitted.",
        f"- Event fact counts: {', '.join(f'{league} {category}={count}' for (league,category),count in sorted(event_counts.items())) or 'none'}.",
        "- Standings facts state only win/loss/tie records. Same-calendar-day prior games are excluded because exact order is not available in every local schedule source; no playoff-clinching or rank claims are inferred.",
        "",
        "## Pregame retrieval and story comparison",
        "",
        "- The retriever requires `occurred_at < target_start`, `available_at <= as_of`, a verified fact with supporting game/event IDs, and team/player relevance. It excludes the target game and uses a stable category/recency order.",
        "- The artifact writes separate `story_kind` values for existing pregame previews, deterministic event previews, and any grounded model versions; it does not write to `game_story`.",
        f"- LLM status: {llm_status}.",
        (f"- Blind target coverage: paired targets {', '.join(f'{league} {count}' for league, count in sorted((paired_targets_by_league or {}).items())) or 'none'}; single-variant targets {', '.join(f'{league} {count}' for league, count in sorted((single_variant_targets_by_league or {}).items())) or 'none'}. NBA upcoming rows lack an ESPN event-ID crosswalk, so an existing NBA preview could not be joined."
         if blind_comparison_count else ""),
        ("- Numeric evidence gate (preview-level): " + "; ".join(
            f"{variant} {counts['unsupported']}/{counts['evaluated']} previews contained a number absent from the supplied event calculations"
            for variant, counts in sorted((numeric_evidence_stats or {}).items())) + "."),
        ("- Blind comparison measurements are mechanical: held-out targets, evidence IDs, numerical claims, repeated wording, and cutoff leakage. Semantic relevance and whether a phrase is readable still require an actual blinded reviewer; no improvement claim is made without those ratings."
         if blind_comparison_count else
         "- No blind comparison rows were produced because no validated event facts were available for future-game context."),
        "",
        "## Rights and limits",
        "",
        "- AP says its structured news-data products cover AI training, retrieval and archive use. Public readability alone is not a bulk-training license; the corpus here retains metadata and links only. See [AP AI, tech and data](https://www.ap.org/who-we-serve/ai-tech-and-data/) and [AP source data](https://www.ap.org/intelligence/our-offerings/source-data/).",
        "- NBA.com terms restrict commercial use of stats and prohibit certain fantasy/gambling uses without consent. These research outputs are not wired into the product; obtain rights review before bulk reuse. See [NBA.com Terms of Use](https://www.nba.com/termsofuse).",
        "- The 100-game NBA article sample is systematic across one completed regular season, not a random sample. NFL covers four selected weeks, not a full season. Not-found pages mean unavailable at the requested page/endpoint during this run, not that the publisher has no article.",
        "",
        "## Network request count",
        "",
    ]
    for host, count in sorted(requests.get("actual_by_host", {}).items()):
        lines.append(f"- `{host}`: {count} requests.")
    if not requests.get("actual_by_host"):
        lines.append("- Network collection was not run.")
    spend = requests.get("all_attempt_spend", {})
    if spend.get("request_counts_by_host"):
        total = sum(spend["request_counts_by_host"].values())
        host_counts = ", ".join(f"{host} {count}"
                                 for host, count in sorted(spend["request_counts_by_host"].items()))
        lines.append(f"- All logged collection attempts, including the failed first pass and metadata re-fetch: {total} requests ({host_counts}). See `network-spend.jsonl` for HTTP statuses.")
    lines += ["", "See `sample_manifest.json`, `publisher_metadata.jsonl`, `event_records.jsonl`, `blind_comparison.jsonl`, and `blind_key.json` for the allowlisted audit records.", ""]
    return "\n".join(lines)


def _output_network_task(future, label):
    try:
        result = future.result()
    except Exception as exc:
        return {"task": label, "error_class": type(exc).__name__}
    return result


def run_audit(db_path: str, outdir: str | Path, *, network: bool = False,
              skip_core: bool = False, skip_scoreboards: bool = False,
              resume_checkpoints: bool = False,
              include_summary_pbp: bool = False,
              reuse_prior_llm: bool = False) -> dict[str, Any]:
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    con = open_readonly(db_path)
    try:
        nfl, (nba_pbp, nba_meta) = build_samples(con)
        event_games = nfl + nba_pbp
        metadata_start = utc_now()
        story_audit = _db_story_audit(con, event_games)
        local_news = _local_news_metadata_audit(con)
        prior_summary_rows_path = outdir / "checkpoint_summary_pbp_rows.jsonl"
        prior_nfl_summary_rows = []
        if (network and include_summary_pbp and resume_checkpoints and skip_core
                and prior_summary_rows_path.is_file()):
            prior_nfl_summary_rows = [row for row in _jsonl_read(prior_summary_rows_path)
                                      if row.get("league") == "nfl"]
        reuse_nfl_summary_checkpoint = (
            len(prior_nfl_summary_rows) == len(nfl) and
            all(row.get("status") == "validated_scoring_timeline"
                for row in prior_nfl_summary_rows))
        if network and include_summary_pbp:
            expected = {"sports.core.api.espn.com": 0 if skip_core else 100,
                        "site.api.espn.com": len(nba_pbp) if reuse_nfl_summary_checkpoint else 100,
                        "www.nba.com": 0, "www.nfl.com": 0}
        elif network:
            expected = {"sports.core.api.espn.com": 0 if skip_core else 100,
                        "site.api.espn.com": 50 + (0 if skip_scoreboards else 2),
                        "www.nba.com": 100, "www.nfl.com": 4}
        else:
            expected = {}
        _json_write(outdir / "sample_manifest.json", {
            "sample_as_of": "2026-10-31", "sample_design": {
                "nfl": {"games": len(nfl), "weeks": list(NFL_WEEKS), "quotas": NFL_QUOTAS},
                "nba_event": {"games": len(nba_pbp), "season_year": NBA_EVENT_SEASON,
                              "phase": "regular", "selection": "evenly spaced subset of the article sample"},
                "nba_article": {"games": len(nba_meta), "season_year": NBA_EVENT_SEASON,
                                 "regular": len(nba_meta), "preseason": 0,
                                 "population_finals": 1230,
                                 "selection": "evenly spaced across the completed regular-season population"}},
            "network_request_plan_by_host": expected if network else {},
            "network_execution_mode": ("checkpointed_nfl_plus_fresh_nba_summary_pbp"
                                       if reuse_nfl_summary_checkpoint else
                                       "checkpoint_publishers_plus_summary_pbp"
                                       if resume_checkpoints and include_summary_pbp
                                       else "resumed_from_checkpoints_no_new_requests" if resume_checkpoints
                                       else "network_collection" if network else "offline"),
            "network_requests_made_this_invocation": (sum(expected.values()) if network and include_summary_pbp
                                                       else 0 if resume_checkpoints or not network
                                                       else sum(expected.values())),
            "database": str(Path(db_path).resolve()),
            "database_mode": "read_only_query_only",
            "article_body_retained": False,
            "sample_games": event_games,
            "nba_article_games": nba_meta,
        })
        print(f"Prepared sample: {len(nfl)} NFL games, {len(nba_pbp)} NBA event games, "
              f"{len(nba_meta)} NBA article pages", flush=True)
        print(f"Database reads: story metadata and news_items metadata only; article body columns excluded.",
              flush=True)

        publisher_rows: list[dict[str, Any]] = []
        event_facts: list[dict[str, Any]] = []
        request_result: dict[str, Any] = {"pbp_rows": [], "actual_by_host": {}}
        whistles: dict[str, str] = {}
        first_play: dict[str, str] = {}
        observed_whistles: dict[str, str] = {}
        observed_first_play: dict[str, str] = {}
        normalized_plays: list[dict[str, Any]] = []
        summary_checkpoint_loaded = False
        if network:
            if resume_checkpoints:
                new_request_count = sum(expected.values()) if include_summary_pbp else 0
                print(f"Rebuilding from saved checkpoints; new network requests={new_request_count}.",
                      flush=True)
            else:
                planned_total = sum(expected.values())
                print("Network request budget before start:", json.dumps(expected, sort_keys=True),
                      f"total={planned_total}; request pacing is 2–3 seconds per host; no retries or disk caches.",
                      flush=True)
                if not skip_core:
                    print("The 100 Core requests are one limit=1000 PBP collection per sampled game; no bulk PBP endpoint was found. ESPN's site summary endpoint also returns a story field, which this code discards and never writes.", flush=True)
            import paced_http
            paced_http.SPEND_LOG = str(outdir / "network-spend.jsonl")
            if resume_checkpoints:
                for label, host in (("nfl_espn", "site.api.espn.com"),
                                    ("nba_pages", "www.nba.com"),
                                    ("nfl_weeklies", "www.nfl.com")):
                    rows = _jsonl_read(outdir / f"checkpoint_{label}_metadata.jsonl")
                    publisher_rows.extend(rows)
                    request_result["actual_by_host"][host] = sum(
                        row.get("status") not in {"not_requested_after_host_refusal", "fetch_error"}
                        for row in rows)
                if not skip_core:
                    core_rows = _jsonl_read(outdir / "checkpoint_pbp_rows.jsonl")
                    request_result["pbp_rows"] = core_rows
                    event_facts.extend(_jsonl_read(outdir / "checkpoint_event_records.jsonl"))
                    for row in core_rows:
                        if row.get("status") == "validated" and row.get("last_play_at"):
                            gid = str(row["game_id"])
                            whistles[gid] = row["last_play_at"]
                            first_play[gid] = row.get("first_play_at")
                            if row.get("event_time_basis") == "publisher_wallclock":
                                observed_whistles[gid] = row["last_play_at"]
                                observed_first_play[gid] = row.get("first_play_at")
                print("Loaded completed publisher metadata checkpoints.", flush=True)
                summary_rows_path = outdir / "checkpoint_summary_pbp_rows.jsonl"
                if summary_rows_path.is_file() and not include_summary_pbp:
                    summary_checkpoint_loaded = True
                    summary_rows = _jsonl_read(summary_rows_path)
                    request_result["pbp_rows"] = summary_rows
                    event_facts.extend(_jsonl_read(outdir / "checkpoint_summary_event_records.jsonl"))
                    normalized_plays = _jsonl_read(outdir / "checkpoint_summary_plays.jsonl")
                    for row in summary_rows:
                        if row.get("status") == "validated" and row.get("last_play_at"):
                            gid = str(row["game_id"])
                            whistles[gid] = row["last_play_at"]
                            first_play[gid] = row.get("first_play_at")
                            if row.get("event_time_basis") == "publisher_wallclock":
                                observed_whistles[gid] = row["last_play_at"]
                                observed_first_play[gid] = row.get("first_play_at")
                    request_result["actual_by_host"]["site.api.espn.com"] += sum(
                        row.get("status") not in {"not_requested_after_host_refusal", "fetch_error"}
                        for row in summary_rows)
                    print("Loaded completed summary timeline checkpoint.", flush=True)
            else:
                tasks = {}
                with ThreadPoolExecutor(max_workers=4) as pool:
                    if not skip_core:
                        tasks[pool.submit(collect_core_pbp, event_games, metadata_start)] = "core"
                    tasks[pool.submit(collect_nfl_espn_articles, nfl,
                                      include_scoreboards=not skip_scoreboards)] = "nfl_espn"
                    tasks[pool.submit(collect_nba_pages, nba_meta)] = "nba_pages"
                    tasks[pool.submit(collect_nfl_weeklies)] = "nfl_weeklies"
                    for future in as_completed(tasks):
                        result = _output_network_task(future, tasks[future])
                        if "error_class" in result:
                            _json_write(outdir / f"network_failure_{tasks[future]}.json", result)
                            print(f"{tasks[future]} task failed ({result['error_class']})", flush=True)
                            continue
                        label = tasks[future]
                        if label == "core":
                            _jsonl_write(outdir / "checkpoint_event_records.jsonl", result["facts"])
                            _jsonl_write(outdir / "checkpoint_pbp_rows.jsonl", result["rows"])
                        else:
                            _jsonl_write(outdir / f"checkpoint_{label}_metadata.jsonl", result["rows"])
                        request_result["actual_by_host"][result["host"]] = result["requests"]
                        if label == "core":
                            request_result["pbp_rows"] = result["rows"]
                            event_facts.extend(result["facts"])
                            whistles.update(result["whistles"])
                            for row in result["rows"]:
                                gid = row.get("game_id")
                                if row.get("status") == "validated" and row.get("last_play_at"):
                                    whistles[str(gid)] = row["last_play_at"]
                                    first_play[str(gid)] = row.get("first_play_at")
                                    if row.get("event_time_basis") == "publisher_wallclock":
                                        observed_whistles[str(gid)] = row["last_play_at"]
                                        observed_first_play[str(gid)] = row.get("first_play_at")
                        elif label == "nfl_espn":
                            publisher_rows.extend(result["rows"])
                            request_result["nba_future_scoreboard"] = result.get("nba_scoreboard_games", [])
                            request_result["nfl_future_scoreboard"] = result.get("nfl_scoreboard_games", [])
                        elif label in {"nba_pages", "nfl_weeklies"}:
                            publisher_rows.extend(result["rows"])
            if include_summary_pbp:
                summary_games = nba_pbp if reuse_nfl_summary_checkpoint else event_games
                summary_result = collect_summary_pbp(summary_games)
                if reuse_nfl_summary_checkpoint:
                    nfl_event_ids = {str(game["espn_event_id"]) for game in nfl}
                    prior_nfl_facts = [fact for fact in _jsonl_read(
                        outdir / "checkpoint_summary_event_records.jsonl")
                                       if fact.get("league") == "nfl"]
                    prior_nfl_plays = [play for play in _jsonl_read(
                        outdir / "checkpoint_summary_plays.jsonl")
                                       if str(play.get("game_id")) in nfl_event_ids]
                    for row in prior_nfl_summary_rows:
                        row["event_time_basis"] = "scheduled_kickoff_plus_game_clock_estimate"
                    summary_result["rows"] = prior_nfl_summary_rows + summary_result["rows"]
                    summary_result["facts"] = prior_nfl_facts + summary_result["facts"]
                    summary_result["normalized_plays"] = prior_nfl_plays + summary_result["normalized_plays"]
                    summary_result["requests"] += len(prior_nfl_summary_rows)
                _jsonl_write(outdir / "checkpoint_summary_pbp_rows.jsonl", summary_result["rows"])
                _jsonl_write(outdir / "checkpoint_summary_event_records.jsonl", summary_result["facts"])
                _jsonl_write(outdir / "checkpoint_summary_plays.jsonl", summary_result["normalized_plays"])
                request_result["pbp_rows"] = summary_result["rows"]
                event_facts.extend(summary_result["facts"])
                normalized_plays = summary_result["normalized_plays"]
                first_play.update(summary_result["first_plays"])
                whistles.update(summary_result["last_plays"])
                request_result["actual_by_host"][summary_result["host"]] = (
                    request_result["actual_by_host"].get(summary_result["host"], 0)
                    + summary_result["requests"])
            if include_summary_pbp and skip_core:
                request_result["pbp_collection_status"] = "summary_endpoint_after_prior_core_403"
            elif summary_checkpoint_loaded and skip_core:
                request_result["pbp_collection_status"] = "summary_endpoint_checkpoint_after_prior_core_403"
            elif skip_core:
                request_result["pbp_collection_status"] = "skipped_after_prior_403"
            else:
                request_result["pbp_collection_status"] = "attempted"
            request_result["all_attempt_spend"] = _network_spend_summary(
                outdir / "network-spend.jsonl")

        # Standings facts depend on validated final PBP timestamps, so derive them after fetch.
        if network:
            # Fill publication delay only where we measured the final play timestamp.
            for row in publisher_rows:
                final_whistle = observed_whistles.get(str(row.get("game_id")))
                published = nek.parse_utc(row.get("published_at"))
                final_at = nek.parse_utc(final_whistle)
                row["publication_delay_seconds_from_final_whistle"] = (
                    int((published - final_at).total_seconds()) if published and final_at else None)
            for game in event_games:
                end_at = whistles.get(str(game["espn_event_id"]))
                if end_at:
                    event_facts.extend(_standings_events(con, game, end_at, metadata_start))
            event_facts.extend(_add_player_facts(event_games, first_play, whistles, con))

        # Attach headline-only candidate labels to the structured event result.
        validated_games = {(str(row["league"]), str(row["game_id"]))
                           for row in request_result.get("pbp_rows", [])
                           if row.get("status") in {"validated", "validated_scoring_timeline"}}
        article_checks = _article_detector_comparison(publisher_rows, event_facts, validated_games)
        duplicate_audit = _duplicate_audit(publisher_rows)
        as_of = utc_now() if network else metadata_start
        targets = _future_nfl_targets(con, as_of) + _future_nba_targets(con, as_of)
        if network:
            _attach_nfl_start_times(targets, request_result.get("nfl_future_scoreboard", []))
            _attach_nba_event_ids(targets, request_result.get("nba_future_scoreboard", []))
        # Future NBA event IDs are not populated in nba_schedule. The locally available
        # ESPN IDs are not guessed; only exact ESPN IDs can join an existing preview row.
        existing_versions = _story_versions_for_targets(con, targets, as_of)
        story_versions = (_sample_game_story_versions(con, event_games,
                                                      observed_first_play, observed_whistles)
                          if network else []) + existing_versions
        prior_llm_versions = {}
        prior_story_path = outdir / "story_versions.jsonl"
        if reuse_prior_llm and prior_story_path.is_file():
            for prior in _jsonl_read(prior_story_path):
                if prior.get("generator") == "configured-deepseek-grounded":
                    prior_llm_versions[(prior.get("league"), prior.get("target_game_id"))] = prior
        player_names = {str(row[0]): row[1] for row in con.execute(
            "SELECT CAST(id AS TEXT),name FROM players WHERE league IN ('nfl','nba')")}
        blind_rows, key_rows, blind_metrics, llm_attempts = [], [], [], Counter()
        pair_number = 0
        for target in targets:
            target_id = str(target.get("espn_event_id") or target.get("game_id") or target.get("game_page_id"))
            cutoff = target.get("start_utc")
            ctx = nek.retrieve_pregame_context(
                event_facts, league=target["league"], target_game_id=target_id,
                target_start=cutoff, as_of=as_of,
                teams=[target["home_team"], target["away_team"]], limit=5)
            deterministic = _render_deterministic_preview(target, ctx, player_names)
            if deterministic:
                story_version = {"target_game_id": target_id, "league": target["league"],
                                 "story_kind": "pregame_preview", "generator": "deterministic-event-v1",
                                 "generated_at": as_of, "preview": deterministic,
                                 "source_event_ids": sorted({eid for fact in ctx
                                                             for eid in fact["supporting_event_ids"]}),
                                 "source_game_ids": sorted({gid for fact in ctx
                                                            for gid in fact["supporting_game_ids"]})}
                story_versions.append(story_version)
                existing = next((v for v in existing_versions
                                 if v["target_game_id"] == target_id and v["league"] == target["league"]), None)
                llm_version = None
                llm_status = "not_selected"
                if network and llm_attempts[target["league"]] < 5:
                    prior_llm = prior_llm_versions.get((target["league"], target_id))
                    current_source_ids = story_version["source_event_ids"]
                    if (reuse_prior_llm and prior_llm and
                            prior_llm.get("source_event_ids") == current_source_ids):
                        result = {"status": "reused_prior_grounded_preview",
                                  "preview": prior_llm.get("preview"),
                                  "cited_event_ids": prior_llm.get("cited_event_ids", []),
                                  "provider": prior_llm.get("provider"),
                                  "model": prior_llm.get("model")}
                        llm_status = result["status"]
                    elif reuse_prior_llm:
                        result = {"status": "no_matching_prior_grounded_preview",
                                  "preview": None, "cited_event_ids": []}
                        llm_status = result["status"]
                    else:
                        llm_attempts[target["league"]] += 1
                        result = _grounded_llm_preview(target, ctx)
                        llm_status = result["status"]
                    llm_text = result.get("preview")
                    unsupported = _unsupported_numbers(llm_text, ctx)
                    if llm_text and not result.get("cited_event_ids"):
                        llm_status, llm_text = "rejected_missing_citations", None
                    if llm_text and unsupported:
                        llm_status, llm_text = "rejected_unsupported_numbers", None
                    if llm_text and re.search(r"\b(will win|likely to win|should win|favou?red to win)\b",
                                              llm_text, re.I):
                        llm_status, llm_text = "rejected_prediction_language", None
                    blind_metrics.append({"target_game_id": target_id, "league": target["league"],
                                          "variant": "llm_grounded",
                                          "cited_event_ids": result.get("cited_event_ids", []),
                                          "unsupported_numeric_tokens": unsupported,
                                          "specificity_fact_count": len(result.get("cited_event_ids", [])),
                                          "relevant_context_fact_count": len(ctx),
                                          "cutoff_leakage": any(
                                              nek.parse_utc(f["occurred_at"]) >= nek.parse_utc(cutoff)
                                              or nek.parse_utc(f["available_at"]) > nek.parse_utc(as_of)
                                              for f in ctx),
                                          "status": llm_status,
                                          "provider": result.get("provider"), "model": result.get("model")})
                    if llm_text:
                        llm_version = {"target_game_id": target_id, "league": target["league"],
                                       "story_kind": "pregame_preview", "generator": "configured-deepseek-grounded",
                                       "generated_at": as_of, "preview": llm_text,
                                       "provider": result.get("provider"), "model": result.get("model"),
                                       "cited_event_ids": result.get("cited_event_ids", []),
                                       "source_event_ids": story_version["source_event_ids"],
                                       "source_game_ids": story_version["source_game_ids"]}
                        if llm_status == "reused_prior_grounded_preview":
                            llm_version["reused_from_prior_audit"] = True
                        story_versions.append(llm_version)
                blind_metrics.append({"target_game_id": target_id, "league": target["league"],
                                      "variant": "deterministic_event",
                                      "unsupported_numeric_tokens": _unsupported_numbers(deterministic, ctx),
                                      "specificity_fact_count": len(ctx),
                                      "relevant_context_fact_count": len(ctx),
                                      "cutoff_leakage": any(
                                          nek.parse_utc(f["occurred_at"]) >= nek.parse_utc(cutoff)
                                          or nek.parse_utc(f["available_at"]) > nek.parse_utc(as_of)
                                          for f in ctx), "status": "ok"})
                pair_number += 1
                blind_target_id = f"target-{pair_number:03d}"
                evidence_event_ids = sorted({eid for fact in ctx
                                             for eid in fact["supporting_event_ids"]})
                evidence_game_ids = sorted({gid for fact in ctx
                                            for gid in fact["supporting_game_ids"]})
                variants = [("existing_preview", existing), ("deterministic_event", story_version),
                            ("llm_grounded", llm_version)]
                available_variants = [(name, value) for name, value in variants if value]
                for left_index, (left_name, left_value) in enumerate(available_variants):
                    for right_name, right_value in available_variants[left_index + 1:]:
                        blind_metrics.append({"target_game_id": target_id,
                                              "league": target["league"],
                                              "variant_pair": [left_name, right_name],
                                              "repeated_information_trigram_jaccard": _trigram_overlap(
                                                  left_value.get("preview"), right_value.get("preview"))})
                for variant, value in variants:
                    if not value:
                        continue
                    blind_id = f"blind-{len(blind_rows)+1:04d}"
                    blind_rows.append({"blind_id": blind_id, "blind_target_id": blind_target_id,
                                       "league": target["league"], "preview": value["preview"],
                                       "source_event_ids": evidence_event_ids,
                                       "source_game_ids": evidence_game_ids})
                    key_rows.append({"blind_id": blind_id, "variant": variant,
                                     "blind_target_id": blind_target_id,
                                     "league": target["league"],
                                     "target_game_id": target_id,
                                     "generator": value.get("generator"),
                                     "story_kind": value.get("story_kind")})
                    if variant == "existing_preview":
                        blind_metrics.append({"target_game_id": target_id, "league": target["league"],
                                              "variant": variant,
                                              "unsupported_numeric_tokens": _unsupported_numbers(value["preview"], ctx),
                                              "cutoff_leakage": False, "status": "available"})
        # Each row is individually blinded; a fixed RNG seed makes the artifact reproducible.
        import random
        rng = random.Random(20261031)
        rng.shuffle(blind_rows)
        variants_by_target = defaultdict(set)
        blind_league_by_target = {}
        for row in key_rows:
            key = (row["blind_target_id"], row["league"])
            variants_by_target[key].add(row["variant"])
            blind_league_by_target[key] = row["league"]
        paired_targets_by_league = Counter(
            blind_league_by_target[key] for key, variants in variants_by_target.items()
            if len(variants) > 1)
        single_variant_targets_by_league = Counter(
            blind_league_by_target[key] for key, variants in variants_by_target.items()
            if len(variants) == 1)
        numeric_evidence_stats = defaultdict(lambda: {"evaluated": 0, "unsupported": 0})
        for metric in blind_metrics:
            variant = metric.get("variant")
            if variant not in {"existing_preview", "deterministic_event", "llm_grounded"}:
                continue
            if metric.get("status") not in {"available", "ok", "reused_prior_grounded_preview"}:
                continue
            numeric_evidence_stats[variant]["evaluated"] += 1
            if metric.get("unsupported_numeric_tokens"):
                numeric_evidence_stats[variant]["unsupported"] += 1
        _jsonl_write(outdir / "blind_comparison.jsonl", blind_rows)
        _json_write(outdir / "blind_key.json", key_rows)
        _jsonl_write(outdir / "event_records.jsonl", event_facts)
        _jsonl_write(outdir / "structured_plays.jsonl", normalized_plays)
        _jsonl_write(outdir / "publisher_metadata.jsonl", publisher_rows)
        _jsonl_write(outdir / "headline_event_agreement.jsonl", article_checks)
        _json_write(outdir / "database_audit.json", story_audit)
        _json_write(outdir / "duplicate_audit.json", duplicate_audit)
        _json_write(outdir / "network_request_counts.json", request_result)
        _jsonl_write(outdir / "blind_metrics.jsonl", blind_metrics)
        _jsonl_write(outdir / "story_versions.jsonl", story_versions)
        reused_llm_count = sum(v.get("reused_from_prior_audit") is True for v in story_versions)
        if reuse_prior_llm:
            llm_status = (f"{reused_llm_count} previously generated grounded previews reused; "
                          f"new model calls={sum(llm_attempts.values())}")
        else:
            llm_status = (f"{sum(llm_attempts.values())} bounded model calls attempted "
                          f"({llm_attempts['nfl']} NFL, {llm_attempts['nba']} NBA); "
                          f"valid LLM previews={sum(v.get('generator')=='configured-deepseek-grounded' for v in story_versions)}")
        report = _report(story_audit=story_audit, local_news=local_news,
                         samples={"nfl": nfl, "nba_pbp": nba_pbp, "nba_metadata": nba_meta},
                         publisher_rows=publisher_rows, event_facts=event_facts,
                         article_checks=article_checks, duplicate_audit=duplicate_audit,
                         requests=request_result, capture_at=as_of, llm_status=llm_status,
                         blind_comparison_count=len(blind_rows),
                         paired_targets_by_league=paired_targets_by_league,
                         single_variant_targets_by_league=single_variant_targets_by_league,
                         numeric_evidence_stats=numeric_evidence_stats)
        (outdir / "audit_report.md").write_text(report, encoding="utf-8")
        return {"outdir": str(outdir), "nfl_games": len(nfl), "nba_event_games": len(nba_pbp),
                "nba_article_games": len(nba_meta), "network_requests": request_result.get("actual_by_host", {}),
                "event_facts": len(event_facts), "publisher_rows": len(publisher_rows),
                "llm_attempts": dict(llm_attempts), "blind_rows": len(blind_rows)}
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="explicit dev database path; opened read-only")
    parser.add_argument("--out", default=str(ARTIFACT_ROOT), help="research artifact directory")
    parser.add_argument("--network", action="store_true",
                        help="fetch the bounded publisher/PBP metadata sample (up to 256 requests)")
    parser.add_argument("--skip-core", action="store_true",
                        help="do not request ESPN Core PBP; use after a prior 403")
    parser.add_argument("--skip-scoreboards", action="store_true",
                        help="do not request ESPN scoreboard endpoints")
    parser.add_argument("--resume-checkpoints", action="store_true",
                        help="rebuild artifacts from completed host checkpoints without network calls")
    parser.add_argument("--include-summary-pbp", action="store_true",
                        help="collect ESPN summary play data for the 50-game-per-league event sample")
    parser.add_argument("--reuse-prior-llm", action="store_true",
                        help="reuse still-grounded model previews from the existing story_versions artifact")
    args = parser.parse_args()
    try:
        result = run_audit(args.db, args.out, network=args.network,
                           skip_core=args.skip_core, skip_scoreboards=args.skip_scoreboards,
                           resume_checkpoints=args.resume_checkpoints,
                           include_summary_pbp=args.include_summary_pbp,
                           reuse_prior_llm=args.reuse_prior_llm)
    except Exception as exc:
        print(f"research audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
