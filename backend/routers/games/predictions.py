"""Multi-sport prediction slates and anonymous pick ledger.

The legacy ``/api/predictions`` routes remain compatible. New product routes
reuse the esports/UFC pick semantics while reading sports slates and results
from persisted publisher snapshots only; opening the page never calls ESPN.
"""
import datetime as dt
import json
import time

from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from . import router


def _db():
    """Resolve `routers.games._db` at call time (see scoreboard.py `_db`)."""
    from routers.games import _db as _pkg_db
    return _pkg_db()


_SPORTS = (
    ("mlb", "MLB"),
    ("nba", "NBA"),
    ("nhl", "NHL"),
    ("nfl", "NFL"),
    ("ncaaf", "NCAAF"),
    ("mls", "MLS"),
    ("lcup", "Leagues Cup"),
    ("wc", "World Cup"),
    ("atp", "ATP"),
    ("wta", "WTA"),
)
_SPORT_LABELS = dict(_SPORTS)
_DRAW_LEAGUES = frozenset(("mls", "lcup", "wc"))
_GROUP_LABELS = {
    frozenset(("mls", "lcup", "wc")): "Soccer",
    frozenset(("atp", "wta")): "Tennis",
}
_CONTRARIAN_K = 1.0


def _json(payload, status=200):
    return JSONResponse(content=payload, status_code=status)


def _device_id(raw):
    value = str(raw or "").strip()
    return value or None


def _iso_to_ms(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _snapshot_match(league, row):
    try:
        game = json.loads(row["payload"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    home = game.get("home") or {}
    away = game.get("away") or {}
    game_id = str(game.get("game_id") or row["game_id"] or "").strip()
    start = game.get("date") or row["start_time"]
    state = row["state"] or game.get("state")
    lock_at = _iso_to_ms(start)
    if not game_id or not home.get("name") or not away.get("name") or lock_at is None:
        return None
    return {
        "matchKey": f"{league}:{game_id}",
        "gameId": game_id,
        "teamA": away["name"],
        "teamB": home["name"],
        "teamAId": str(away.get("abbrev") or away.get("id") or away["name"]),
        "teamBId": str(home.get("abbrev") or home.get("id") or home["name"]),
        "title": _SPORT_LABELS[league],
        "league": league,
        "startTime": lock_at,
        "logoA": away.get("logo"),
        "logoB": home.get("logo"),
        "seedA": away.get("seed"),
        "seedB": home.get("seed"),
        "live": state == "in",
        "finished": state == "post",
        "allowDraw": league in _DRAW_LEAGUES,
        "eventDate": row["game_date"],
        "source": "scoreboard_snapshots",
    }


def _prop_game_match(league, row):
    game_id = str(row["espn_event_id"] or "").strip()
    lock_at = _iso_to_ms(row["start_time"])
    if not game_id or not row["home"] or not row["away"] or lock_at is None:
        return None
    return {
        "matchKey": f"{league}:{game_id}",
        "gameId": game_id,
        "teamA": row["away"],
        "teamB": row["home"],
        "teamAId": row["away"],
        "teamBId": row["home"],
        "title": _SPORT_LABELS[league],
        "league": league,
        "startTime": lock_at,
        "logoA": None,
        "logoB": None,
        "seedA": None,
        "seedB": None,
        "live": False,
        "finished": False,
        "allowDraw": league in _DRAW_LEAGUES,
        "eventDate": row["date"],
        "source": "prop_games",
    }


def _sports_slate(league, now_ms=None):
    """Stored live matches plus the nearest upcoming day; never calls a publisher."""
    if league not in _SPORT_LABELS:
        raise ValueError(f"unsupported prediction league {league!r}")
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    now_iso = dt.datetime.fromtimestamp(
        now_ms / 1000, tz=dt.timezone.utc
    ).isoformat(timespec="seconds")
    today_date = dt.datetime.fromtimestamp(now_ms / 1000, tz=dt.timezone.utc).date()
    today = today_date.isoformat()
    yesterday = (today_date - dt.timedelta(days=1)).isoformat()
    with closing(_db()) as con:
        rows = con.execute(
            "SELECT game_date, game_id, payload, state, start_time"
            " FROM scoreboard_snapshots"
            " WHERE league=? AND ((state='in' AND game_date>=?) OR"
            " (state='pre' AND game_date>=? AND start_time>?))"
            " ORDER BY game_date, start_time, game_id",
            (league, yesterday, today, now_iso),
        ).fetchall()
        matches = [match for row in rows for match in [_snapshot_match(league, row)] if match]
        live_matches = [match for match in matches if match["live"]]
        upcoming_matches = [match for match in matches if not match["live"]]
        if not upcoming_matches:
            rows = con.execute(
                "SELECT date, home, away, espn_event_id, start_time"
                " FROM prop_games WHERE league=? AND date>=?"
                " AND espn_event_id IS NOT NULL AND espn_event_id!=''"
                " AND start_time IS NOT NULL ORDER BY date, start_time, id",
                (league, today),
            ).fetchall()
            upcoming_matches = [
                match for row in rows
                for match in [_prop_game_match(league, row)]
                if match and match["startTime"] > now_ms
                and all(existing["matchKey"] != match["matchKey"] for existing in live_matches)
            ]
    if not live_matches and not upcoming_matches:
        return [], None
    first_date = min((match["eventDate"] for match in upcoming_matches), default=None)
    slate = live_matches + [
        match for match in upcoming_matches if match["eventDate"] == first_date
    ]
    slate.sort(key=lambda match: (match["startTime"], match["matchKey"]))
    sources = {match["source"] for match in slate}
    return slate, next(iter(sources)) if len(sources) == 1 else "mixed"


def _requested_leagues(league=None, leagues=None, default="mlb"):
    if league and leagues:
        raise HTTPException(400, "choose league or leagues, not both")
    values = [league] if league else str(leagues or default).split(",")
    selected = []
    for value in values:
        slug = str(value or "").strip().lower()
        if not slug or slug in selected:
            continue
        if slug not in _SPORT_LABELS:
            raise HTTPException(404, f"unsupported prediction league {slug!r}")
        selected.append(slug)
    if not selected:
        raise HTTPException(400, "at least one prediction league is required")
    return selected


def _find_sports_match(league, match_key, now_ms=None):
    matches, _source = _sports_slate(league, now_ms=now_ms)
    return next((match for match in matches if match["matchKey"] == match_key), None)


def _signed_streak(results):
    sequence = [result for result in results if result in ("win", "loss")]
    if not sequence:
        return 0
    first = sequence[0]
    count = 0
    for result in sequence:
        if result != first:
            break
        count += 1
    return count if first == "win" else -count


def _tally(con, league, match_key):
    counts = {"A": 0, "B": 0, "D": 0}
    for row in con.execute(
        "SELECT side, COUNT(*) AS n FROM predictions"
        " WHERE league=? AND match_key=? AND device_id IS NOT NULL"
        " GROUP BY side",
        (league, match_key),
    ).fetchall():
        if row["side"] in counts:
            counts[row["side"]] = row["n"]
    return counts


def _published_outcome(league, game):
    """Return ``(side, reason)`` for a stored final.

    ``side`` is A/B/D for a graded result, ``void`` for a terminal tie in a
    league that did not offer a draw, and ``None`` only when the payload cannot
    yet be graded.  The reason keeps a malformed final distinct from a
    retryable missing snapshot in the settlement report.
    """
    if not isinstance(game, dict):
        return None, "payload_not_an_object"
    if game.get("state") != "post":
        return None, "payload_not_final"
    home = game.get("home") or {}
    away = game.get("away") or {}
    if not isinstance(home, dict) or not isinstance(away, dict):
        return None, "competitors_not_objects"
    away_won = away.get("winner") is True
    home_won = home.get("winner") is True
    if away_won and home_won:
        return None, "conflicting_winner_flags"

    try:
        away_score = float(away.get("score"))
        home_score = float(home.get("score"))
    except (TypeError, ValueError):
        away_score = home_score = None

    if away_score is not None and away_score == home_score:
        if away_won or home_won:
            return None, "winner_flag_conflicts_with_tied_score"
        if league in _DRAW_LEAGUES:
            return "D", None
        return "void", None

    if away_won:
        return "A", None
    if home_won:
        return "B", None
    if away_score is not None:
        return ("A", None) if away_score > home_score else ("B", None)
    return None, "winner_and_scores_missing"


def settle_sports_picks():
    """Settle open sports picks from stored finals and report every disposition."""
    now = int(time.time() * 1000)
    settled = 0
    voided = 0
    pending = 0
    unsettleable = []
    with closing(_db()) as con:
        open_rows = con.execute(
            "SELECT DISTINCT league, game_id, match_key FROM predictions"
            " WHERE device_id IS NOT NULL AND settled_at IS NULL"
        ).fetchall()
        for opened in open_rows:
            snapshot = con.execute(
                "SELECT payload FROM scoreboard_snapshots"
                " WHERE league=? AND game_id=? AND state='post'"
                " ORDER BY fetched_at DESC LIMIT 1",
                (opened["league"], opened["game_id"]),
            ).fetchone()
            if not snapshot:
                pending += 1
                continue
            try:
                game = json.loads(snapshot["payload"])
            except (TypeError, ValueError, json.JSONDecodeError):
                unsettleable.append({
                    "league": opened["league"], "gameId": opened["game_id"],
                    "matchKey": opened["match_key"], "reason": "invalid_snapshot_json",
                })
                continue
            outcome, reason = _published_outcome(opened["league"], game)
            if outcome is None:
                unsettleable.append({
                    "league": opened["league"], "gameId": opened["game_id"],
                    "matchKey": opened["match_key"], "reason": reason,
                })
                continue
            counts = _tally(con, opened["league"], opened["match_key"])
            total = sum(counts.values())
            for pick in con.execute(
                "SELECT id, side FROM predictions WHERE league=? AND match_key=?"
                " AND device_id IS NOT NULL AND settled_at IS NULL",
                (opened["league"], opened["match_key"]),
            ).fetchall():
                if outcome == "void":
                    con.execute(
                        "UPDATE predictions SET settled_at=?, result='void', points=NULL,"
                        " crowd_share_at_lock=NULL, correct=NULL WHERE id=?",
                        (now, pick["id"]),
                    )
                    settled += 1
                    voided += 1
                    continue
                won = pick["side"] == outcome
                share = counts.get(pick["side"], 0) / total if total else None
                points = 1.0 + _CONTRARIAN_K * (1.0 - share) if won and share is not None else (1.0 if won else 0.0)
                con.execute(
                    "UPDATE predictions SET settled_at=?, result=?, points=?,"
                    " crowd_share_at_lock=?, correct=? WHERE id=?",
                    (now, "win" if won else "loss", points, share, int(won), pick["id"]),
                )
                settled += 1
        con.commit()
    return {
        "settled": settled,
        "voided": voided,
        "pending": pending,
        "unsettleable": unsettleable,
    }


@router.get("/api/sports/predict")
def sports_predict_slate(
    league: Optional[str] = None,
    leagues: Optional[str] = None,
):
    selected_leagues = _requested_leagues(league, leagues)
    selected = []
    selected_sources = set()
    for lg in selected_leagues:
        matches, match_source = _sports_slate(lg)
        selected.extend(matches)
        if match_source:
            selected_sources.add(match_source)
    selected.sort(key=lambda match: (match["startTime"], match["matchKey"]))
    source = next(iter(selected_sources)) if len(selected_sources) == 1 else ("mixed" if selected_sources else None)
    options = []
    for slug, label in _SPORTS:
        matches, _ = _sports_slate(slug)
        options.append({
            "slug": slug, "label": label, "match_count": len(matches),
            "live_count": sum(1 for match in matches if match["live"]), "result_count": 0,
            "next_start": next((match["startTime"] for match in matches if not match["live"]), None),
        })
    selected_slug = selected_leagues[0] if len(selected_leagues) == 1 else ",".join(selected_leagues)
    selected_label = _SPORT_LABELS[selected_leagues[0]] if len(selected_leagues) == 1 else (
        _GROUP_LABELS.get(frozenset(selected_leagues))
        or " / ".join(_SPORT_LABELS[slug] for slug in selected_leagues)
    )
    return {
        "schema_version": "sports-predict-v1",
        "selected_title": {"slug": selected_slug, "label": selected_label},
        "titles": options,
        "matches": selected,
        "match_count": len(selected),
        "has_more": False,
        "building": False,
        "error": None,
        "source": source,
    }


@router.post("/api/sports/picks")
async def post_sports_pick(request: Request, x_device_id: Optional[str] = Header(None)):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, 400)
    try:
        data = await request.json()
    except Exception:
        data = {}
    league = str(data.get("league") or "").lower()
    match_key = str(data.get("matchKey") or "").strip()
    side = data.get("side")
    if league not in _SPORT_LABELS or not match_key:
        return _json({"error": "valid league and matchKey required"}, 400)
    if side not in ("A", "B", "D"):
        return _json({"error": "side must be A, B, or D"}, 400)
    match = _find_sports_match(league, match_key)
    if not match:
        return _json({"error": "game not found or already started"}, 404)
    if side == "D" and not match["allowDraw"]:
        return _json({"error": "draw is not an outcome for this league"}, 400)
    now = int(time.time() * 1000)
    if match["live"] or match["finished"] or match["startTime"] is None or now >= match["startTime"]:
        return _json({"error": "game is locked"}, 409)
    chosen = "Draw" if side == "D" else match["teamAId" if side == "A" else "teamBId"]
    created_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        # Serialize the read-then-write upsert. The additive migration preserves
        # legacy rows and cannot introduce a uniqueness constraint safely, so
        # the transaction owns the one-pick-per-device invariant.
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute(
            "SELECT id, settled_at FROM predictions"
            " WHERE device_id=? AND league=? AND match_key=? ORDER BY id DESC LIMIT 1",
            (device_id, league, match_key),
        ).fetchone()
        if existing and existing["settled_at"] is not None:
            return _json({"error": "already settled"}, 409)
        values = (
            chosen, created_iso, side, match["teamA"], match["teamB"],
            match["eventDate"], now, match["startTime"], match["gameId"],
        )
        if existing:
            con.execute(
                "UPDATE predictions SET predicted_winner=?, created_at=?, side=?,"
                " team_a=?, team_b=?, event_date=?, created_at_ms=?, lock_at=?,"
                " game_id=?, correct=NULL, result=NULL, points=NULL,"
                " crowd_share_at_lock=NULL WHERE id=?",
                values + (existing["id"],),
            )
        else:
            con.execute(
                "INSERT INTO predictions(league,game_id,predicted_winner,created_at,correct,"
                " device_id,match_key,side,team_a,team_b,event_date,created_at_ms,lock_at)"
                " VALUES(?,?,?,?,NULL,?,?,?,?,?,?,?,?)",
                (league, match["gameId"], chosen, created_iso, device_id, match_key,
                 side, match["teamA"], match["teamB"], match["eventDate"], now,
                 match["startTime"]),
            )
        con.commit()
    return _json({"matchKey": match_key, "league": league, "side": side, "lockAt": match["startTime"], "createdAt": now})


@router.get("/api/sports/picks/me")
def get_my_sports_picks(
    league: Optional[str] = None,
    x_device_id: Optional[str] = Header(None),
    leagues: Optional[str] = None,
):
    device_id = _device_id(x_device_id)
    if not device_id:
        return _json({"error": "device id required"}, 400)
    where = "device_id=?"
    params = [device_id]
    if league or leagues:
        selected_leagues = _requested_leagues(league, leagues)
        placeholders = ",".join("?" for _ in selected_leagues)
        where += f" AND league IN ({placeholders})"
        params.extend(selected_leagues)
    with closing(_db()) as con:
        rows = con.execute(
            "SELECT league,match_key,side,team_a,team_b,created_at_ms,lock_at,"
            " settled_at,result,points FROM predictions WHERE " + where
            + " ORDER BY created_at_ms DESC, id DESC",
            params,
        ).fetchall()
    picks = [{
        "matchKey": row["match_key"], "league": row["league"], "side": row["side"],
        "teamA": row["team_a"], "teamB": row["team_b"],
        "createdAt": row["created_at_ms"], "lockAt": row["lock_at"],
        "settledAt": row["settled_at"], "result": row["result"], "points": row["points"],
    } for row in rows]
    results = [
        row["result"]
        for row in sorted(
            (row for row in rows if row["settled_at"] is not None),
            key=lambda row: row["settled_at"],
            reverse=True,
        )
    ]
    return _json({
        "picks": picks,
        "record": {
            "wins": results.count("win"), "losses": results.count("loss"),
            "voids": results.count("void"), "streak": _signed_streak(results),
        },
    })


@router.post("/api/sports/picks/settle")
def settle_sports_picks_endpoint():
    """Run one settlement pass for a scheduled job or manual trigger."""
    return _json(settle_sports_picks())


@router.get("/api/sports/crowd")
def get_sports_crowd(league: str = Query(...), matchKey: str = Query(...)):
    lg = league.lower()
    if lg not in _SPORT_LABELS:
        return _json({"error": "unsupported league"}, 404)
    with closing(_db()) as con:
        counts = _tally(con, lg, matchKey)
    total = sum(counts.values())
    return _json({
        "countA": counts["A"], "countB": counts["B"], "countDraw": counts["D"],
        "total": total, "shareA": counts["A"] / total if total else None,
    })



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
