"""routers/games.py — games endpoints. Handlers only; shared code lives in _core."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *

router = APIRouter()

@router.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — breakingpoint.gg (persists completed matches)
        # Falls back to cdl_client if breakingpoint is unreachable
        try:
            import breakingpoint_client
            matches = breakingpoint_client.get_cod_matches(date_str=date)
            if matches:
                return matches
        except Exception as e:
            print(f"[sports_service] breakingpoint failed ({e}), falling back to cdl_client")
        import cdl_client
        return cdl_client.get_matches(date_str=date)
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
    """Group/division standings. For World Cup: returns group tables with draws."""
    if league.lower() != "wc":
        try:
            return espn.team_strength(league)
        except ValueError as e:
            raise HTTPException(404, str(e))
    try:
        return espn.group_standings(league)
    except ValueError as e:
        raise HTTPException(404, str(e))


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

