"""routers/games/game_detail.py — per-game detail, boxscore, pbp, info, roster."""
from fastapi import HTTPException, Query
from typing import Optional
from _core import *
from team_stats_contract import build_team_aggregates
from . import router


def _db():
    """Resolve `routers.games._db` at call time (see scoreboard.py `_db`)."""
    from routers.games import _db as _pkg_db
    return _pkg_db()



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
           "final_score": None, "live_score": None, "state": None,
           "period": None, "clock": None, "status_detail": None}
    # Game state up front so we NEVER label a live/upcoming game "final".
    try:
        _gr = espn.game_result(league, game_id)
        out["state"] = _gr.get("state")
        out["period"] = _gr.get("period")
        out["clock"] = _gr.get("clock")
        out["status_detail"] = _gr.get("status_detail")
    except Exception:
        _gr = {}
    if out["state"] is None:
        # ESPN is the only thing that ever told this page a game was over, so a
        # walled host (403s are routine here) made every finished game render as
        # if it had not kicked off. For the leagues whose results we ingest by
        # season rather than capture live, the DB already knows: a
        # team_game_results row reaching status='completed' IS the published
        # final. Ask it rather than letting a fetch failure decide.
        #
        # Only 'completed' promotes to "post" — the invariant above still holds,
        # because that ingest never writes a row for a game still being played.
        try:
            out["state"] = _state_from_db(lg, game_id)
        except Exception:
            pass
        # team_game_results can lag a game that finished an hour ago: the
        # season-results ingest is a slow sweep, while the scoreboard snapshot
        # is written per-minute for live games and once per finished slate. If
        # the source of record has not caught up, the snapshot is the next DB
        # source that knows the game is over — still zero ESPN requests.
        if out["state"] is None:
            try:
                snap_state, snap_score = _state_and_score_from_snapshot(lg, game_id)
                if snap_state:
                    out["state"] = snap_state
                    if snap_state == "post" and snap_score:
                        out["final_score"] = snap_score
            except Exception:
                pass
    is_final = out["state"] == "post"
    # Final score from OUR DB (scoring_plays) — only when the game is actually over.
    # If the DB has no row yet (scoring_plays / team_game_results lag a game that
    # just finished), keep whatever the snapshot fallback already set rather than
    # clobbering it with None.
    if is_final:
        try:
            db_score = _final_score_from_db(lg, game_id)
            if db_score is not None:
                out["final_score"] = db_score
        except Exception:
            pass
    # Read from DB
    _read_game_detail_from_db(lg, game_id, out)

    # UFC finish detail (method/round/clock): the snapshot carries it for
    # fights captured after the finish. The frontend ScoreStrip/GameCard
    # render "DEC · R3 5:00" on the winner's line from these fields, so a
    # UFC game page shows how the fight ended, not just that it did.
    if out["state"] == "post" and lg == "ufc":
        try:
            snap_info = _snapshot_result_info(lg, game_id)
            if snap_info:
                out["outcome_method"] = snap_info.get("outcome_method")
                out["outcome_round"] = snap_info.get("outcome_round")
                out["outcome_clock"] = snap_info.get("outcome_clock")
        except Exception:
            pass

    # A DB context row means the ESPN fallback below is skipped, but the live
    # score is not persisted — fill it from ESPN whenever the game is live.
    if out["state"] == "in" and not out["live_score"]:
        try:
            result = espn.game_result(league, game_id)
            scores = result.get("scores", {})
            if scores and len(scores) == 2:
                # `scores` is keyed by ESPN abbreviation, so looking it up with a
                # team NAME missed and the fallback key "home" never existed in
                # it either — the score silently came back None. Take the sides
                # from ESPN's own homeAway flag instead of matching vocabularies.
                out["live_score"] = {
                    "home": result.get("home_score"),
                    "away": result.get("away_score"),
                }
                if out["live_score"]["home"] is None or out["live_score"]["away"] is None:
                    out["live_score"] = None
        except Exception:
            pass

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
            db_score = _final_score_from_db(lg, game_id)
            if db_score is not None:
                out["final_score"] = db_score

        # If DB is still empty (e.g. pre-game or snapshot failed),
        # fall back to ESPN's scoreboard summary for minimal context + scores
        if not out["context"]:
            try:
                result = espn.game_result(league, game_id)
                scores = result.get("scores", {})
                # game_result already reports which side is home, from ESPN's own
                # homeAway flag. This used to re-fetch the summary purely to read
                # that flag — a second request for a value we were handed — and
                # when the fetch failed it guessed home by ALPHABETICAL order of
                # the abbreviations, which is a coin flip wearing a sort().
                home_abbrev = result.get("home") or ""
                away_abbrev = result.get("away") or ""

                if result.get("home_score") is not None and result.get("away_score") is not None:
                    sc = {"home": result["home_score"], "away": result["away_score"]}
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

        # If ESPN is walled (routine on this host since 2026-08-04) the score
        # strip would still render AWAY/HOME placeholders. The scoreboard
        # snapshot always carries the team names it saw — last DB source before
        # giving up, still zero ESPN requests.
        if not out["context"]:
            try:
                snap_ctx = _context_from_snapshot(lg, game_id)
                if snap_ctx:
                    out["context"] = snap_ctx
            except Exception:
                pass

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
