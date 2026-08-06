"""routers/games.py — games endpoints. Handlers only; shared code lives in _core."""
import datetime as dt
import html
import json
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from team_stats_contract import build_team_aggregates
from provenance import publishers_for

router = APIRouter()

_SCHEDULE_DATES_CONTRACT = "league-schedule-dates-v1"
_NFL_SCHEDULE_WEEKS_CONTRACT = "nfl-schedule-weeks-v1"
_NFL_SCHEDULE_WEEK_CONTRACT = "nfl-schedule-week-v1"
_SCHEDULE_SEARCH_RANGES = {
    # Keep every ESPN range comfortably below its 1,000-event response cap.
    # A full NBA season in one 280-day request can otherwise truncate before
    # the games nearest the anchor (especially when searching backwards).
    "future": (
        (0, 14),
        (15, 45),
        (46, 90),
        (91, 150),
        (151, 210),
        (211, 270),
        (271, 330),
        (331, 370),
    ),
    "past": (
        (-14, -1),
        (-45, -15),
        (-90, -46),
        (-150, -91),
        (-210, -151),
        (-270, -211),
        (-330, -271),
        (-370, -331),
    ),
}
_SCHEDULE_CANDIDATE_LIMIT = 64
_MIN_VIEWER_OFFSET = dt.timezone(dt.timedelta(hours=-12))
_MAX_VIEWER_OFFSET = dt.timezone(dt.timedelta(hours=14))


def _parse_anchor_date(anchor: Optional[str]) -> dt.date:
    if anchor is None:
        return dt.date.today()
    try:
        parsed = dt.date.fromisoformat(anchor)
    except (TypeError, ValueError):
        raise HTTPException(400, "anchor must be YYYY-MM-DD")
    if parsed.isoformat() != anchor:
        raise HTTPException(400, "anchor must be YYYY-MM-DD")
    return parsed


def _default_nfl_season(anchor: dt.date) -> int:
    return anchor.year - 1 if anchor.month <= 2 else anchor.year


def _flatten_nfl_weeks(phases):
    return [week for phase in phases for week in phase.get("weeks", [])]


def _default_nfl_week(weeks, anchor: dt.date):
    if not weeks:
        return None, "none"
    anchor_text = anchor.isoformat()
    starts = [str(week.get("start_time") or "")[:10] for week in weeks]
    if anchor_text < starts[0]:
        return weeks[0], "next"
    for index, week in enumerate(weeks):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        if next_start is not None and anchor_text < next_start:
            return week, "current"
        if next_start is None:
            end_text = str(week.get("end_time") or "")[:10]
            return week, "current" if anchor_text <= end_text else "latest"
    return weeks[-1], "latest"


def _event_start(value):
    """Parse an absolute ESPN start time, returning ``None`` for junk."""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _is_guaranteed_directional_start(value, anchor: dt.date, direction: str):
    """Whether every real viewer timezone places ``value`` past the anchor.

    The browser remains authoritative for its local calendar. This conservative
    check only tells the backend when it has searched far enough: a future start
    must still be after ``anchor`` at UTC-12, while a past start must already be
    before it at UTC+14. Boundary starts are retained for the browser but do not
    prematurely stop discovery.
    """
    parsed = _event_start(value)
    if parsed is None:
        return False
    if direction == "future":
        return parsed.astimezone(_MIN_VIEWER_OFFSET).date() > anchor
    return parsed.astimezone(_MAX_VIEWER_OFFSET).date() < anchor


def _cap_schedule_candidates(starts, anchor: dt.date, direction: str):
    ordered = sorted(set(starts))
    if len(ordered) <= _SCHEDULE_CANDIDATE_LIMIT:
        return ordered

    guaranteed = [
        value
        for value in ordered
        if _is_guaranteed_directional_start(value, anchor, direction)
    ]
    if direction == "future":
        selected = ordered[:_SCHEDULE_CANDIDATE_LIMIT]
        if guaranteed and not any(value in selected for value in guaranteed):
            selected[-1] = guaranteed[0]
    else:
        selected = ordered[-_SCHEDULE_CANDIDATE_LIMIT:]
        if guaranteed and not any(value in selected for value in guaranteed):
            selected[0] = guaranteed[-1]
    return sorted(set(selected))


def _schedule_candidates(league: str, anchor: dt.date, direction: str):
    attempts = []
    candidates = []
    for start_delta, end_delta in _SCHEDULE_SEARCH_RANGES[direction]:
        start_date = anchor + dt.timedelta(days=start_delta)
        end_date = anchor + dt.timedelta(days=end_delta)
        starts = espn.schedule_event_starts(league, start_date, end_date)
        candidates.extend(starts)
        attempts.append({
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "event_starts_found": len(starts),
        })
        if any(
            _is_guaranteed_directional_start(value, anchor, direction)
            for value in starts
        ):
            break
    return _cap_schedule_candidates(candidates, anchor, direction), attempts


def _attach_cod_detail_ids(matches):
    """Add a PandaScore detail id only when the fixture identity resolves.

    BreakingPoint remains the scoreboard source and keeps its own ``game_id``.
    The dedicated CoD detail route is PandaScore-backed, so expose that separate
    id after the shared esports matcher verifies both opponents and match time.
    Unresolved fixtures intentionally stay without a detail id.
    """
    try:
        from routers.esports.pandascore import _iso_to_ms, _ps_enrich
    except Exception as exc:
        print(f"[sports_service] CoD detail identity unavailable ({exc})")
        return matches

    for match in matches:
        # Rows already reconciled (EWC bracket rows carry a PandaScore id from the indexed
        # bracket graph) must not trigger a second, per-row fuzzy lookup.
        if match.get("detail_game_id"):
            continue
        home = (match.get("home") or {}).get("name")
        away = (match.get("away") or {}).get("name")
        near_ms = _iso_to_ms(match.get("date"))
        if not home or not away or not near_ms:
            continue
        try:
            identity = _ps_enrich(
                home,
                away,
                include_running=True,
                near_ms=near_ms,
                league="Call of Duty",
            )
        except Exception as exc:
            print(f"[sports_service] CoD detail identity failed for {match.get('game_id')} ({exc})")
            continue
        if identity and identity.get("_ps_id") is not None:
            match["detail_game_id"] = str(identity["_ps_id"])
    return matches

@router.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/coverage")
def coverage():
    """The enablement registry: which (league, season) pairs may be offered at all.

    Returns EVERY row, not just the complete ones. A client needs to distinguish
    "this league exists and we cannot vouch for it yet" from "this league does not
    exist" — they are different states and they read differently to a user.

    A (league, season) with no row here is `unverified`, which is the default and is
    never good. See docs/DATA-COVERAGE-CONTRACT.md §4.

    Each row also carries `publishers`: the external sources whose rows actually
    back that league, measured from the data rather than declared. Note that the
    row's own `source` column describes the *verdict* ("reconcile_totals+
    espn_core_api"), not the data — conflating the two is how NHL came to hold
    ESPN-keyed team rows and nhle.com-keyed player rows with nothing saying so.
    More than one publisher is not an error; it is a count of vocabulary
    boundaries this league's joins have to cross.
    """
    with closing(_db()) as con:
        try:
            rows = con.execute(
                "SELECT league, season, status, expected_teams, fetched_teams,"
                " expected_games, fetched_games, paired_games, paired_stat_games,"
                " failure_count, season_start, season_end, completed_at, source,"
                " checked_through"
                " FROM team_stats_coverage ORDER BY league, season"
            ).fetchall()
        except sqlite3.Error:
            # No table is not an error; it means nothing has been verified.
            return []
        pubs = {}
        for r in rows:
            league = r["league"]
            if league not in pubs:
                try:
                    pubs[league] = publishers_for(con, league)
                except sqlite3.Error:
                    pubs[league] = []
    out = []
    for r in rows:
        d = dict(r)
        # Never let an unrecognised status read as permission. Anything outside the
        # three-value vocabulary is treated as unverified rather than passed through.
        # `in_progress` is a season that passes every check but has not ended yet;
        # its row carries `checked_through`, the date its claim actually reaches.
        # It belongs in this list and leaving it out is not a safe default — the
        # guard would rewrite a verified live season to "we cannot vouch for this"
        # and the fix would be invisible end to end.
        if d.get("status") not in ("complete", "in_progress", "partial", "unverified"):
            d["status"] = "unverified"
        d["publishers"] = pubs.get(d["league"], [])
        out.append(d)
    return out


@router.get("/api/ufc/rankings")
def ufc_rankings():
    """UFC rankings — reads cached ufc_rankings table populated by
    ingest_ufc_rankings.py (live scrape, never on the request path)."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT division, rank, fighter, is_champion FROM ufc_rankings "
                "ORDER BY division, rank"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                503,
                "UFC rankings data unavailable: production data has not been promoted",
            ) from exc

    if not rows:
        raise HTTPException(
            503,
            "UFC rankings data unavailable: production data is empty",
        )

    # Separate P4P from weight divisions
    p4p_men, p4p_women = [], []
    divisions: dict = {}  # division_name -> {champion, ranked: [{rank, fighter}]}

    for r in rows:
        div = r["division"]
        rank = r["rank"]
        raw_fighter = r["fighter"]
        if not isinstance(div, str) or not isinstance(rank, int):
            continue
        if not isinstance(raw_fighter, str) or not raw_fighter.strip():
            continue
        fighter = html.unescape(raw_fighter)
        if "Pound-for-Pound" in div:
            entry = {"rank": rank, "fighter": fighter}
            if r["is_champion"]:
                entry["champion"] = True
            if "Women" in div:
                p4p_women.append(entry)
            else:
                p4p_men.append(entry)
        else:
            if div not in divisions:
                divisions[div] = {"division": div, "champion": "", "ranked": []}
            if r["is_champion"]:
                divisions[div]["champion"] = fighter
            else:
                divisions[div]["ranked"].append(
                    {"rank": rank, "fighter": fighter}
                )

    # Sort P4P by rank (champion=rank 0 first)
    p4p_men.sort(key=lambda x: x["rank"])
    p4p_women.sort(key=lambda x: x["rank"])

    # Order divisions: men's weight classes first, then women's
    MEN_ORDER = [
        "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
        "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
    ]
    WOMEN_ORDER = ["Women's Strawweight", "Women's Flyweight", "Women's Bantamweight"]
    ordered = []
    for d in MEN_ORDER:
        if d in divisions:
            divisions[d]["ranked"].sort(key=lambda x: x["rank"])
            ordered.append(divisions[d])
    for d in WOMEN_ORDER:
        if d in divisions:
            divisions[d]["ranked"].sort(key=lambda x: x["rank"])
            ordered.append(divisions[d])

    expected_divisions = set(MEN_ORDER + WOMEN_ORDER)
    populated_divisions = {
        division["division"] for division in ordered if division["ranked"]
    }
    if (
        not p4p_men
        or not p4p_women
        or populated_divisions != expected_divisions
    ):
        raise HTTPException(
            503,
            "UFC rankings data unavailable: production data is incomplete",
        )

    return {
        "pound_for_pound": {"men": p4p_men, "women": p4p_women},
        "divisions": ordered,
    }


@router.get("/api/ufc/fighter/{player_id}/form")
def ufc_fighter_form(player_id: int):
    """Lazy ESPN-backed last-five form for one internal UFC fighter."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        player = con.execute(
            "SELECT id, name, espn_id FROM players WHERE id=? AND league='ufc'",
            (player_id,),
        ).fetchone()
        if not player:
            raise HTTPException(404, "UFC fighter not found")
        date_row = con.execute(
            """SELECT pg.date
               FROM props p JOIN prop_games pg ON pg.id=p.game_id
               WHERE p.player_id=? AND pg.league='ufc'
               ORDER BY ABS(julianday(pg.date) - julianday('now')) LIMIT 1""",
            (player_id,),
        ).fetchone()

    athlete_id = str(player["espn_id"] or "")
    canonical_name = player["name"]
    if not athlete_id:
        match = espn.ufc_athlete(player["name"], date_row["date"] if date_row else None)
        if not match:
            return {
                "player_id": player_id,
                "fighter": player["name"],
                "source": "espn",
                "fights": [],
            }
        athlete_id = match["id"]
        canonical_name = match["name"]
        # Persist the source crosswalk only when it is not already owned by a
        # different UFC row. The endpoint never fabricates or merges players.
        with closing(_db()) as con:
            owner = con.execute(
                "SELECT id FROM players WHERE league='ufc' AND espn_id=?",
                (athlete_id,),
            ).fetchone()
            if owner is None or owner[0] == player_id:
                con.execute("UPDATE players SET espn_id=? WHERE id=?", (athlete_id, player_id))
                con.commit()

    try:
        fights = espn.ufc_fight_history(athlete_id, limit=5)
    except Exception as exc:
        raise HTTPException(502, "ESPN UFC fight history unavailable") from exc
    return {
        "player_id": player_id,
        "fighter": canonical_name,
        "espn_id": athlete_id,
        "source": "espn",
        "fights": fights,
    }


@router.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — breakingpoint.gg (persists completed matches)
        # Falls back to cdl_client if breakingpoint is unreachable
        try:
            import breakingpoint_client
            matches = breakingpoint_client.get_cod_matches(date_str=date)
            if matches:
                # EWC bracket rows: reconcile against the indexed PandaScore codmw EWC window
                # (once per refresh) so raw "TBD" participants never reach the scoreboard. Non-EWC
                # CDL rows pass through unchanged. See routers/esports/cod_ewc.py.
                from routers.esports.cod_ewc import reconcile_cod_matches
                matches = reconcile_cod_matches(matches)
                return _attach_cod_detail_ids(matches)
        except Exception as e:
            print(f"[sports_service] breakingpoint failed ({e}), falling back to cdl_client")
        import cdl_client
        return _attach_cod_detail_ids(cdl_client.get_matches(date_str=date))
    try:
        games = espn.games(league, date)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # ── finished-game final score: DB-first, no ESPN on the request path ──
    # For a post-state game, prefer OUR captured final (scoring_plays) over the
    # scoreboard tick. DB-only — no per-request ESPN calls. If the DB has no record
    # (we never snapshotted it), leave the scoreboard score as-is. An occasional
    # out-of-band job can reconcile DB vs ESPN; the page request never does.
    lg = league.lower()
    for g in games:
        if g.get("state") != "post":
            continue
        final = _final_score_from_db(lg, g["game_id"])
        if final:
            if g.get("home"):
                g["home"]["score"] = final["home"]
            if g.get("away"):
                g["away"]["score"] = final["away"]
    # "Write the preview whenever we find out about the game": loading the scoreboard is
    # exactly when we find out, so warm the AI-story cache in the background here. Non-
    # blocking — the games response returns now; stories generate in daemon threads.
    if lg in ("nba", "nhl", "mlb", "nfl"):
        kick_game_stories(lg, games)
    return JSONResponse(content=games, headers={"Cache-Control": "public, max-age=30"})


@router.get("/api/{league}/schedule-dates")
def get_schedule_dates(
    league: str,
    anchor: Optional[str] = Query(None, description="Viewer-local YYYY-MM-DD"),
):
    """Bounded event-start candidates for resolving an empty schedule day.

    Event starts stay as absolute ISO instants. The browser converts them to
    its own local calendar before choosing the nearest future date or, when no
    future event exists in the verified horizon, the most recent past date.
    """
    lg = league.lower()
    if lg not in espn.LEAGUES:
        raise HTTPException(404, f"unsupported league {lg!r}")
    anchor_date = _parse_anchor_date(anchor)

    try:
        future_starts, future_search = _schedule_candidates(lg, anchor_date, "future")
        past_starts, past_search = _schedule_candidates(lg, anchor_date, "past")
    except Exception as exc:
        raise HTTPException(502, "schedule date discovery unavailable") from exc

    return JSONResponse(
        content={
            "contract": _SCHEDULE_DATES_CONTRACT,
            "league": lg,
            "anchor_date": anchor_date.isoformat(),
            "event_start_timezone": "UTC",
            "future_event_starts": future_starts,
            "past_event_starts": past_starts,
            "search": {
                "future": future_search,
                "past": past_search,
                "max_horizon_days": 370,
            },
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/nfl/schedule-weeks")
def get_nfl_schedule_weeks(
    season: Optional[int] = Query(None, ge=2000, le=2100),
    anchor: Optional[str] = Query(None, description="Viewer-local YYYY-MM-DD"),
):
    """ESPN's ordered NFL phase/week catalog and the default week for an anchor date."""
    anchor_date = _parse_anchor_date(anchor)
    selected_season = season if season is not None else _default_nfl_season(anchor_date)
    if selected_season < 2000 or selected_season > 2100:
        raise HTTPException(400, "season must be between 2000 and 2100")
    try:
        phases = espn.nfl_schedule_weeks(selected_season)
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week catalog unavailable") from exc

    weeks = _flatten_nfl_weeks(phases)
    default_week, default_reason = _default_nfl_week(weeks, anchor_date)
    if default_week is None:
        raise HTTPException(502, "NFL schedule week catalog is empty")
    return JSONResponse(
        content={
            "contract": _NFL_SCHEDULE_WEEKS_CONTRACT,
            "league": "nfl",
            "season": selected_season,
            "anchor_date": anchor_date.isoformat(),
            "navigation": "week",
            "phases": phases,
            "weeks": weeks,
            "default_week_key": default_week["key"],
            "default_reason": default_reason,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/nfl/schedule-week")
def get_nfl_schedule_week(
    season: int = Query(..., ge=2000, le=2100),
    season_type: int = Query(..., ge=1, le=3),
    week: int = Query(..., ge=1, le=25),
):
    """One NFL week of games, keyed by ESPN season type and week number."""
    if season < 2000 or season > 2100:
        raise HTTPException(400, "season must be between 2000 and 2100")
    if season_type not in (1, 2, 3):
        raise HTTPException(400, "season_type must be 1, 2, or 3")
    if week < 1 or week > 25:
        raise HTTPException(400, "week must be between 1 and 25")
    try:
        phases = espn.nfl_schedule_weeks(season)
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week catalog unavailable") from exc

    selected = next(
        (
            candidate
            for candidate in _flatten_nfl_weeks(phases)
            if candidate["season_type"] == season_type and candidate["week"] == week
        ),
        None,
    )
    if selected is None:
        raise HTTPException(404, "NFL schedule week not found")
    try:
        week_games = espn.nfl_schedule_week_games(season, season_type, week)
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week games unavailable") from exc

    return JSONResponse(
        content={
            "contract": _NFL_SCHEDULE_WEEK_CONTRACT,
            "league": "nfl",
            "season": season,
            "navigation": "week",
            "selected_week": selected,
            "games": week_games,
        },
        headers={"Cache-Control": "public, max-age=20"},
    )


@router.get("/api/{league}/strength")
def get_strength(league: str):
    """Teams ranked by quality (win%, differential, streak, last-10) — the selection prior."""
    try:
        rows = espn.team_strength(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    _snapshot_strength(league.lower(), rows)
    return rows


@router.get("/api/{league}/standings")
def get_standings(league: str):
    """Group/division standings. For World Cup: group tables during the group
    stage; the canonical knockout bracket/results once the season phase leaves
    'Group' (progression gate via espn.wc_is_knockout — never serve stale groups
    once knockouts have begun)."""
    if league.lower() != "wc":
        try:
            return espn.team_strength(league)
        except ValueError as e:
            raise HTTPException(404, str(e))
    # WC: group tables are ONLY valid during the Group phase. Once knockouts
    # have begun, serve the canonical bracket ONLY — never stale group tables.
    # The no-stale-group fallback: if the bracket is empty/unavailable while
    # knockouts are live, return 503 rather than silently serving yesterday's
    # Group standings (the swallowed-exception fall-through that regressed here).
    # Any upstream failure on the knockout path (phase lookup or bracket fetch)
    # becomes 503 too — never an uncaught 500, never a stale-group fall-through.
    try:
        knockout = espn.wc_is_knockout()
    except Exception:
        # Phase lookup failed — we cannot confirm groups are still valid, so do
        # NOT fall through to group_standings (that would serve stale tables).
        raise HTTPException(503, "World Cup phase lookup unavailable")
    if knockout:
        try:
            bracket = espn.wc_knockout_standings()
        except HTTPException:
            raise  # preserve an already-shaped HTTP error from the client layer
        except Exception:
            raise HTTPException(503, "World Cup knockout bracket unavailable")
        if bracket.get("rounds"):
            return bracket
        raise HTTPException(503, "World Cup knockout bracket is unavailable")
    # Group phase — serve group tables
    try:
        return espn.group_standings(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
@router.get("/api/wc/knockout")
def wc_knockout():
    """World Cup knockout bracket — the SAME canonical {rounds:[...]} shape as
    /api/wc/standings during knockouts. Single source of truth:
    espn.wc_knockout_standings(). Returns {rounds:[{round, matches:[{game_id,
    date, home:{abbrev,name}, away:{abbrev,name}, homeScore, awayScore, winner,
    status, state}]}]}."""
    try:
        return espn.wc_knockout_standings()
    except Exception as e:
        raise HTTPException(404, str(e))


@router.get("/api/wc/{game_id}/context")
def wc_context(
    game_id: str,
    limit: int = Query(8, ge=1, le=100),
    phase: Optional[str] = Query(None),
):
    """Phase-aware WC catch-up plus receipt-backed booth episodes.

    With no phase, episodes come from the current match phase. The Booth tab
    may request a past phase on interaction without downloading the whole
    broadcast on initial render.
    """
    allowed_phases = {
        "pregame", "first_half", "halftime", "second_half",
        "extra_time", "penalties", "final",
    }
    if phase is not None and phase not in allowed_phases:
        raise HTTPException(400, f"phase must be one of {sorted(allowed_phases)}")
    import wc_context as _wcc
    ctx = _wcc.build_context(game_id, limit=limit, phase=phase)
    if not ctx:
        raise HTTPException(404, "no context for this game")
    return ctx


@router.get("/api/wc/{game_id}/context/episodes/{episode_id}")
def wc_context_episode(game_id: str, episode_id: str):
    """Full receipt stack for one episode, fetched only when a user expands it."""
    import wc_context as _wcc
    detail = _wcc.get_episode_detail(game_id, episode_id)
    if detail is None:
        # A normal list request primes this bounded derived cache. Rebuild once
        # after a worker restart so an already-open browser can still expand.
        _wcc.build_context(game_id, limit=1)
        detail = _wcc.get_episode_detail(game_id, episode_id)
    if detail is None:
        raise HTTPException(404, "episode not found")
    return detail


@router.get("/api/cod/{game_id}/context")
def cod_game_context(game_id: str, limit: int = Query(12, ge=1, le=100)):
    """Grounded Call of Duty match context from PandaScore history, the existing
    esports slate, and timestamp-matched CDL booth reads."""
    import cod_context as _cod
    ctx = _cod.build_context(game_id, limit=limit)
    if not ctx:
        raise HTTPException(404, "no Call of Duty context for this game")
    return ctx


# Broadcast tapes live in the sibling prediction-market-trading repo. Leagues Cup
# watchers write <YYYYMMDD>_LCUP_<AWAY><HOME>_{transcript,signals}.jsonl there.
_BROADCAST_DIR = "/root/prediction-market-trading/data/broadcast"

_SIGNAL_TAGS = {
    "tilt": "Mentality", "lockin": "Mentality", "fatigue": "Fatigue",
    "tactical": "Tactical", "morale": "Mentality", "momentum": "Momentum",
}


@router.get("/api/lcup/{game_id}/context")
def lcup_game_context(game_id: str, limit: int = Query(12, ge=1, le=100)):
    """Leagues Cup booth: live Spanish radio transcript + soft-signal reads for
    the game, straight from the broadcast_alpha tapes (legacy insights shape,
    newest first). 404 when no watcher is running for this game."""
    import espn_client as _espn
    try:
        summary = _espn.summary("lcup", game_id)
    except Exception:
        raise HTTPException(404, "no context for this game")
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    date = (comp.get("date") or "")[:10].replace("-", "")
    abbrevs = {}
    for c in comp.get("competitors", []):
        abbrevs[c.get("homeAway")] = (c.get("team") or {}).get("abbreviation", "")
    if not date or not abbrevs.get("home") or not abbrevs.get("away"):
        raise HTTPException(404, "no context for this game")
    tag = f"{date}_LCUP_{abbrevs['away']}{abbrevs['home']}"

    insights = []

    # Soft signals (DeepSeek-extracted claims) — richer, prefer them first.
    spath = os.path.join(_BROADCAST_DIR, f"{tag}_signals.jsonl")
    if os.path.exists(spath):
        for line in open(spath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except Exception:
                continue
            if not s.get("quote"):
                continue
            insights.append({
                "id": f"{tag}-sig-{len(insights)}",
                "tag": _SIGNAL_TAGS.get((s.get("type") or "").lower(), "Momentum"),
                "subject": s.get("subject", "Broadcast"),
                "quote": s["quote"],
                "strength": int(s.get("strength") or 1),
                "ts": s.get("ts"),
                "analysis": (s.get("direction") or "") and f"Booth lean: {s['direction']}",
            })

    # Raw transcript lines — the booth's evidence even before extraction runs.
    tpath = os.path.join(_BROADCAST_DIR, f"{tag}_transcript.jsonl")
    if os.path.exists(tpath):
        for line in open(tpath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            text = (t.get("text") or "").strip()
            if not text:
                continue
            insights.append({
                "id": f"{tag}-tx-{len(insights)}",
                "tag": "Live",
                "subject": "Radio",
                "quote": text,
                "strength": 1,
                "ts": t.get("ts"),
            })

    if not insights:
        raise HTTPException(404, "no booth data for this game yet")
    insights.sort(key=lambda i: i.get("ts") or "", reverse=True)
    return {"insights": insights[:limit]}


@router.get("/api/{league}/team-stats")
def get_team_stats(league: str, game_id: Optional[str] = Query(None)):
    """Per-game team boxscore totals for NBA/NHL/NFL."""
    if league.lower() not in ("nba", "nhl", "nfl"):
        raise HTTPException(400, "team-stats is for nba/nhl/nfl only")
    sql = "SELECT * FROM team_game_stats WHERE league=?"
    params = [league.lower()]
    if game_id:
        sql += " AND game_id=?"
        params.append(game_id)
    sql += " ORDER BY captured_at DESC LIMIT 200"
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/{league}/team-aggregates")
def get_team_aggregates(league: str):
    """Season team aggregates with league-specific categories and coverage."""
    lg = league.lower()
    try:
        with closing(_db()) as con:
            con.row_factory = sqlite3.Row
            return build_team_aggregates(con, lg)
    except sqlite3.OperationalError:
        with closing(sqlite3.connect(":memory:")) as con:
            return build_team_aggregates(con, lg)


@router.get("/api/{league}/strength/{team}")
def get_team_strength(league: str, team: str):
    try:
        m = espn.team_strength_map(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    row = m.get(team.upper())
    if not row:
        raise HTTPException(404, f"team {team!r} not found in {league}")
    return row


@router.get("/api/{league}/boxscore/{game_id}")
def get_boxscore(league: str, game_id: str):
    try:
        result = espn.boxscore(league, game_id)
        # Persist team stats + scoring plays + game context (NBA+NHL only)
        lg = league.lower()
        if lg in ("nba", "nhl"):
            try: _snapshot_boxscore_full(lg, game_id)
            except Exception: pass  # snapshot failure must not break the API response
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/api/{league}/game/{game_id}/detail")
def get_game_detail(league: str, game_id: str):
    """NBA/NHL game detail: persisted team stats, scoring timeline, venue, and strength priors."""
    lg = league.lower()
    # Full box-score detail (team stats + scoring timeline) is NBA/NHL only. Other leagues
    # (MLB etc.) still get minimal context — teams, score, state — via the ESPN fallback
    # below, so the game page renders a real matchup header + story + props instead of bailing.
    has_boxscore = lg in ("nba", "nhl")
    out = {"game_id": game_id, "league": lg,
           "team_stats": [], "scoring_plays": [], "context": None, "strength": {},
           "final_score": None, "live_score": None, "state": None}
    # Game state up front so we NEVER label a live/upcoming game "final".
    try:
        _gr = espn.game_result(league, game_id)
        out["state"] = _gr.get("state")
    except Exception:
        _gr = {}
    is_final = out["state"] == "post"
    # Final score from OUR DB (scoring_plays) — only when the game is actually over.
    if is_final:
        try:
            out["final_score"] = _final_score_from_db(lg, game_id)
        except Exception:
            pass
    # Read from DB
    _read_game_detail_from_db(lg, game_id, out)

    # ── Fallback: when boxscore snapshots were never captured (empty DB),
    #     pull team names + scores from ESPN's scoreboard/game_result so the
    #     detail page shows real data instead of AWAY/HOME placeholders. ──
    if not out["team_stats"] and not out["context"]:
        # First, try to populate the DB via the boxscore snapshot pipeline
        # so both this request and future ones get full data.
        if has_boxscore:
            try:
                _snapshot_boxscore_full(lg, game_id)
            except Exception:
                pass  # snapshot may fail for pre-game, which is fine

        # Re-query the DB now that snapshot has run
        _read_game_detail_from_db(lg, game_id, out)
        if is_final:
            out["final_score"] = _final_score_from_db(lg, game_id)

        # If DB is still empty (e.g. pre-game or snapshot failed),
        # fall back to ESPN's scoreboard summary for minimal context + scores
        if not out["context"]:
            try:
                result = espn.game_result(league, game_id)
                scores = result.get("scores", {})
                home_abbrev = ""
                away_abbrev = ""
                try:
                    summary = _fetch_summary(lg, game_id)
                    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
                    for c in comp.get("competitors", []):
                        ab = c.get("team", {}).get("abbreviation", "")
                        if c.get("homeAway") == "home":
                            home_abbrev = ab
                        else:
                            away_abbrev = ab
                    if not scores:
                        for c in comp.get("competitors", []):
                            ab = c.get("team", {}).get("abbreviation", "")
                            sc = _num(c.get("score"))
                            if ab and sc is not None:
                                scores[ab] = int(sc)
                except Exception:
                    if len(scores) == 2:
                        score_keys = sorted(scores.keys())
                        home_abbrev = score_keys[0]
                        away_abbrev = score_keys[1]

                if scores and len(scores) == 2:
                    abbrevs = list(scores.keys())
                    if home_abbrev and away_abbrev and home_abbrev in scores and away_abbrev in scores:
                        sc = {"home": scores[home_abbrev], "away": scores[away_abbrev]}
                    else:
                        sc = {"home": scores[abbrevs[0]], "away": scores[abbrevs[1]]}
                    # Only "final" when the game is over; otherwise it's the live score.
                    if is_final:
                        out["final_score"] = sc
                    else:
                        out["live_score"] = sc

                if home_abbrev or away_abbrev:
                    out["context"] = {
                        "venue_name": "", "venue_city": "",
                        "attendance": None, "officials": [],
                        "home_team": home_abbrev, "away_team": away_abbrev,
                    }
            except Exception:
                pass  # ESPN fallback failed — return whatever we have

        # Strength priors for whatever teams we ended up with
        if out["context"]:
            for ab in [out["context"]["home_team"], out["context"]["away_team"]]:
                if not ab:
                    continue
                try:
                    if ab not in out["strength"]:
                        out["strength"][ab] = espn.team_strength_map(lg).get(ab)
                except Exception:
                    pass
    else:
        # DB had data — strength priors for both teams
        if out["context"]:
            for ab in [out["context"]["home_team"], out["context"]["away_team"]]:
                if not ab: continue
                try:
                    out["strength"][ab] = espn.team_strength_map(lg).get(ab)
                except Exception:
                    pass

    return out


# ── Per-tab lazy endpoints: boxscore, play-by-play, game info ──
# These serve live ESPN /summary data per tab, additive to the DB-snapshot
# /api/{league}/game/{game_id}/detail path that stays as-is for NBA/NHL.


def _summary_not_started(sm):
    """True if the game hasn't started (ESPN status state == 'pre'). Without this, a scheduled
    game's box score renders the rosters with all-zero stats — indistinguishable from a final."""
    try:
        return sm["header"]["competitions"][0]["status"]["type"]["state"] == "pre"
    except Exception:
        return False


@router.get("/api/{league}/game/{game_id}/boxscore")
def get_game_boxscore(league: str, game_id: str):
    """Live per-tab box score: team stats + player stat tables (US sports) or
    team match stats + lineups (soccer). Returns {available: false} for unsupported leagues."""
    lg = league.lower()
    if lg in ("atp", "wta", "ufc", "cod"):
        return {"available": False}

    try:
        sm = espn.summary(league, game_id)
    except Exception:
        return {"available": False}

    if not sm or not sm.get("boxscore"):
        return {"available": False}
    if _summary_not_started(sm):
        return {"available": False, "notStarted": True}
    bs = sm["boxscore"]

    # ── Soccer (WC / Leagues Cup / MLS) shape ──
    if lg in ("wc", "lcup", "mls"):
        team_stats_raw = []
        for t in bs.get("teams", []):
            ha = t.get("homeAway", "")
            for s in t.get("statistics", []):
                team_stats_raw.append({
                    "label": s.get("name", ""),
                    "home": s.get("displayValue", "") if ha == "home" else None,
                    "away": s.get("displayValue", "") if ha == "away" else None,
                })
        # Merge home/away values per label
        merged: dict = {}
        for ts in team_stats_raw:
            label = ts["label"]
            if label not in merged:
                merged[label] = {"label": label, "home": "", "away": ""}
            if ts["home"] is not None:
                merged[label]["home"] = ts["home"]
            if ts["away"] is not None:
                merged[label]["away"] = ts["away"]
        team_stats = list(merged.values())

        try:
            lups = espn.lineups(league, game_id)
        except Exception:
            lups = []
        def _pos(p):  # ESPN position is an object {name,displayName,abbreviation}; emit the abbrev string
            pos = p.get("position")
            return pos.get("abbreviation", "") if isinstance(pos, dict) else (pos or "")
        lineups = [{"side": lu["side"], "formation": lu["formation"],
                     "players": [{"num": p.get("jersey"), "name": p.get("name"), "pos": _pos(p)}
                                 for p in lu["players"]]} for lu in lups]

        return {"available": True, "teamStats": team_stats, "lineups": lineups}

    # ── US team sports (mlb, nfl, nba, nhl) ──
    # Team totals
    teams = []
    for t in bs.get("teams", []):
        ti = t.get("team", {})
        teams.append({
            "name": ti.get("displayName", ""),
            "abbrev": ti.get("abbreviation", ""),
            "stats": [{"label": s.get("name", ""), "value": s.get("displayValue", "")}
                      for s in t.get("statistics", [])],
        })

    # Player stat tables
    players = []
    for pgrp in bs.get("players", []):
        team_info = pgrp.get("team", {})
        team_abbr = team_info.get("abbreviation", "")
        for sg in pgrp.get("statistics", []):
            group_name = (sg.get("type") or "").capitalize()
            labels = sg.get("labels", [])
            rows = []
            for ath in sg.get("athletes", []):
                a = ath.get("athlete", {})
                rows.append({
                    "name": a.get("displayName", ""),
                    "position": (a.get("position") or {}).get("abbreviation", ""),
                    "stats": ath.get("stats", []),
                })
            players.append({
                "team": team_abbr,
                "group": group_name,
                "columns": labels,
                "rows": rows,
            })

    return {"available": True, "teams": teams, "players": players}


@router.get("/api/{league}/game/{game_id}/playbyplay")
def get_game_playbyplay(league: str, game_id: str):
    """Live per-tab play-by-play: chrono plays (US sports) or key events (soccer)."""
    lg = league.lower()
    if lg in ("atp", "wta", "ufc", "cod"):
        return {"available": False}

    try:
        sm = espn.summary(league, game_id)
    except Exception:
        return {"available": False}

    if not sm:
        return {"available": False}

    # ── Soccer (WC / Leagues Cup / MLS) shape ──
    if lg in ("wc", "lcup", "mls"):
        try:
            ev = espn.match_events(league, game_id)
        except Exception:
            ev = {"key_events": [], "commentary": []}

        events = []
        for ke in ev.get("key_events", []):
            etype = "var"
            ke_type = ((ke.get("type") or {}).get("text") or "").lower()
            if "goal" in ke_type or "penalty" in ke_type:
                etype = "goal"
            elif "card" in ke_type or "yellow" in ke_type or "red" in ke_type:
                etype = "card"
            elif "sub" in ke_type:
                etype = "sub"

            # clock.displayValue is like "12'", "45'+2", or "" (kickoff). Take the leading number
            # (stoppage "+2" dropped) so events order correctly instead of collapsing to 0'.
            clock = (ke.get("clock") or {}).get("displayValue", "") or ""
            digits = "".join(c for c in clock.split("+")[0] if c.isdigit())
            minute = int(digits) if digits else 0

            team = ""
            if ke.get("team"):
                team = ke["team"].get("abbreviation", "")

            events.append({
                "minute": minute,
                "type": etype,
                "text": ke.get("text", ""),
                "team": team,
            })

        # Sort by minute
        events.sort(key=lambda e: e["minute"])
        return {"available": True, "events": events}

    # ── US team sports ──
    plays_raw = sm.get("plays")
    if not plays_raw:
        return {"available": False}

    periods = []
    current_period = None
    current_label = ""
    current_plays: list = []

    for p in plays_raw:
        pd = p.get("period") or {}
        pd_num = pd.get("number", 0)
        pd_label = pd.get("displayValue", "")

        if pd_num != current_period:
            if current_period is not None:
                periods.append({"label": current_label, "plays": current_plays})
            current_period = pd_num
            current_label = pd_label
            current_plays = []

        clock = (p.get("clock") or {}).get("displayValue", "")
        current_plays.append({
            "clock": clock,
            "text": p.get("text", ""),
            "scoreAway": p.get("awayScore"),
            "scoreHome": p.get("homeScore"),
            "scoringPlay": bool(p.get("scoringPlay", False)),
        })

    if current_period is not None:
        periods.append({"label": current_label, "plays": current_plays})

    return {"available": True, "periods": periods}


@router.get("/api/{league}/game/{game_id}/gameinfo")
def get_game_gameinfo(league: str, game_id: str):
    """Live per-tab game info: venue, attendance, officials, odds, weather (NFL), broadcasts."""
    lg = league.lower()
    if lg in ("atp", "wta", "ufc", "cod"):
        return {"available": False}

    try:
        sm = espn.summary(league, game_id)
    except Exception:
        return {"available": False}

    if not sm:
        return {"available": False}

    gi = sm.get("gameInfo") or {}
    if not gi:
        return {"available": False}

    venue_data = gi.get("venue") or {}
    officials = [o.get("displayName", "") for o in (gi.get("officials") or [])]

    # Broadcasts
    broadcasts = []
    broadcast_list = gi.get("broadcasts", []) or []
    for b in broadcast_list:
        names = b.get("names", [])
        if names:
            broadcasts.extend(names)
        elif b.get("name"):
            broadcasts.append(b["name"])

    # Also check header.competitions[0].broadcasts
    header = sm.get("header", {})
    comp = (header.get("competitions") or [{}])[0]
    for b in (comp.get("broadcasts") or []):
        names = b.get("names", [])
        if names:
            broadcasts.extend(names)
        elif b.get("name"):
            broadcasts.append(b["name"])
    # Dedupe
    broadcasts = list(dict.fromkeys(broadcasts))

    # Odds
    odds_data = {}
    if comp.get("odds"):
        odds_data = comp["odds"][0] if comp["odds"] else {}
    # Try competitors for odds
    if not odds_data:
        for c in comp.get("competitors", []):
            if c.get("odds"):
                odds_data = c["odds"]
                break

    spread = odds_data.get("details") or odds_data.get("spread") or ""
    over_under = odds_data.get("overUnder") or odds_data.get("over_under") or ""
    favorite = odds_data.get("favorite", "")
    if not favorite:
        for c in comp.get("competitors", []):
            if c.get("favorite"):
                favorite = c.get("team", {}).get("abbreviation", "")

    # Weather (NFL)
    weather = None
    if lg == "nfl":
        w = gi.get("weather") or {}
        if w:
            weather = {
                "temperature": w.get("temperature"),
                "condition": w.get("condition") or w.get("displayValue"),
                "wind": w.get("wind") or w.get("windSpeed"),
            }

    result: dict = {
        "available": True,
        "venue": venue_data.get("fullName", ""),
        "city": (venue_data.get("address") or {}).get("city", ""),
        "attendance": gi.get("attendance"),
        "capacity": venue_data.get("capacity") or gi.get("capacity"),
        "officials": officials,
        "odds": {"spread": spread, "overUnder": over_under, "favorite": favorite},
        "broadcasts": broadcasts,
    }
    if weather:
        result["weather"] = weather

    return result


@router.get("/api/{league}/team/{team}/roster")
def get_roster(league: str, team: str):
    try:
        result = espn.roster(league, team)
        # Persist roster (NBA+NHL only)
        lg = league.lower()
        if lg in ("nba", "nhl"):
            try: _snapshot_rosters(lg, team.upper(), result)
            except Exception: pass
        return result
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/api/predictions")
def submit_prediction(pred: PredictionIn):
    league = pred.league.lower()
    if league not in espn.LEAGUES:
        raise HTTPException(404, f"unsupported league {pred.league!r}")
    correct = _evaluate(league, pred.game_id, pred.predicted_winner)
    with closing(_db()) as con:
        cur = con.execute(
            "INSERT INTO predictions(league,game_id,predicted_winner,created_at,correct) VALUES(?,?,?,?,?)",
            (league, pred.game_id, pred.predicted_winner.upper(),
             dt.datetime.now(dt.timezone.utc).isoformat(),
             None if correct is None else int(correct)))
        con.commit()
        pid = cur.lastrowid
    return {"id": pid, "league": league, "game_id": pred.game_id,
            "predicted_winner": pred.predicted_winner.upper(), "correct": correct}


@router.get("/api/predictions")
def list_predictions(league: Optional[str] = Query(None, description="Filter by league (nba, mlb, nhl, nfl, etc.)")):
    sql = "SELECT * FROM predictions"
    params = []
    if league:
        sql += " WHERE league = ?"
        params.append(league.lower())
    sql += " ORDER BY id"
    out = []
    with closing(_db()) as con:
        for r in con.execute(sql, params).fetchall():
            correct = r["correct"]
            if correct is None:                     # re-grade: the game may have finished since
                correct = _evaluate(r["league"], r["game_id"], r["predicted_winner"])
                if correct is not None:
                    con.execute("UPDATE predictions SET correct=? WHERE id=?", (int(correct), r["id"]))
            out.append({"id": r["id"], "league": r["league"], "game_id": r["game_id"],
                        "predicted_winner": r["predicted_winner"], "correct": correct})
        con.commit()
    accuracy = None
    graded = [p for p in out if p["correct"] is not None]
    if graded:
        accuracy = round(sum(1 for p in graded if p["correct"]) / len(graded), 4)
    return {"predictions": out, "graded": len(graded), "accuracy": accuracy}
