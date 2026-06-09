#!/usr/bin/env python3
"""sports_service.py — unified multi-league sports API (ESPN-backed) + prediction store.

ONE service. Replaces the old sportsipy-based `sports_service` and the NBA-only `nba_service`
(now a deprecation stub). All data flows through espn_client (free, reliable, every league).

What changed from the original:
  - real data for ALL leagues (was: dead sportsipy + a 1-game hardcoded fixture fallback)
  - predictions persisted to SQLite and graded against REAL finals (was: in-memory list vs fixture)
  - /strength endpoint: teams ranked by win% / differential / form — the quality prior shared
    with the prediction-market trading strategy (its only unfalsified edge: buy undervalued QUALITY)
"""
import os, sqlite3, datetime as dt
from contextlib import closing
from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import espn_client as espn

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")
ALLOWED_ORIGINS = os.environ.get("LP_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3007").split(",")

app = FastAPI(title="Legendary Picks Sports API", description="Multi-league sports data (ESPN)", version="2.0.0")
print(f"DEBUG: espn_client leagues: {sorted(espn.LEAGUES)}")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _init_db():
    with closing(_db()) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS predictions(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          league TEXT NOT NULL, game_id TEXT NOT NULL, predicted_winner TEXT NOT NULL,
          created_at TEXT NOT NULL, correct INTEGER);
        CREATE TABLE IF NOT EXISTS strength_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, abbrev TEXT NOT NULL,
          win_pct REAL, differential REAL, wins INTEGER, losses INTEGER);
        CREATE TABLE IF NOT EXISTS roster_snap(
          captured_at TEXT NOT NULL, league TEXT NOT NULL, team_abbrev TEXT NOT NULL,
          player_id TEXT NOT NULL, name TEXT, jersey TEXT, position TEXT);
        CREATE TABLE IF NOT EXISTS team_game_stats(
          league TEXT NOT NULL, game_id TEXT NOT NULL, captured_at TEXT NOT NULL,
          team_abbrev TEXT NOT NULL, home_away TEXT NOT NULL,
          fgm_fga TEXT, fg_pct REAL, tpm_tpa TEXT, tp_pct REAL,
          ftm_fta TEXT, ft_pct REAL, rebounds INTEGER, off_rebounds INTEGER,
          def_rebounds INTEGER, assists INTEGER, steals INTEGER, blocks INTEGER,
          turnovers INTEGER, fouls INTEGER, pts_off_to INTEGER,
          fast_break_pts INTEGER, pts_in_paint INTEGER, largest_lead INTEGER,
          lead_changes INTEGER, lead_pct REAL,
          shots INTEGER, blocked_shots INTEGER, hits INTEGER,
          takeaways INTEGER, giveaways INTEGER, faceoffs_won INTEGER,
          faceoff_pct REAL, powerplay_goals INTEGER, powerplay_opps INTEGER,
          powerplay_pct REAL, shorthanded_goals INTEGER,
          penalties INTEGER, penalty_min INTEGER);
        CREATE TABLE IF NOT EXISTS scoring_plays(
          league TEXT NOT NULL, game_id TEXT NOT NULL, play_id TEXT NOT NULL,
          captured_at TEXT NOT NULL, period INTEGER, period_disp TEXT,
          clock TEXT, away_score INTEGER, home_score INTEGER,
          team_abbrev TEXT, scorer_name TEXT, play_text TEXT, play_type TEXT);
        CREATE TABLE IF NOT EXISTS game_context(
          league TEXT NOT NULL, game_id TEXT NOT NULL PRIMARY KEY,
          captured_at TEXT NOT NULL, home_team TEXT, away_team TEXT,
          venue_name TEXT, venue_city TEXT, attendance INTEGER,
          officials TEXT);
        """)
        con.commit()


_init_db()


class PredictionIn(BaseModel):
    league: str
    game_id: str
    predicted_winner: str   # team abbreviation, e.g. "MIL"


@app.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


@app.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — real data from official CDL schedule page
        import cdl_client
        return cdl_client.get_matches(date_str=date)
    try:
        games = espn.games(league, date)
    except ValueError as e:
        raise HTTPException(404, str(e))
    # ── post-state reconciliation ──────────────────────────────────
    # Finished games must display their boxscore-reconciled FINAL score,
    # never a frozen live-scoreboard tick.  Walk every post-state game and
    # replace the scoreboard scores with the authoritative final from the
    # scoring_plays table or the ESPN summary endpoint.
    lg = league.lower()
    reconciled = 0
    for g in games:
        if g.get("state") != "post":
            continue
        final = _reconcile_final_score(lg, g["game_id"])
        if final:
            if g.get("home"):
                g["home"]["score"] = final["home"]
            if g.get("away"):
                g["away"]["score"] = final["away"]
            reconciled += 1
    return JSONResponse(content=games, headers={"Cache-Control": "no-store"})


@app.get("/api/{league}/strength")
def get_strength(league: str):
    """Teams ranked by quality (win%, differential, streak, last-10) — the selection prior."""
    try:
        rows = espn.team_strength(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    _snapshot_strength(league.lower(), rows)
    return rows


@app.get("/api/{league}/strength/{team}")
def get_team_strength(league: str, team: str):
    try:
        m = espn.team_strength_map(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    row = m.get(team.upper())
    if not row:
        raise HTTPException(404, f"team {team!r} not found in {league}")
    return row


@app.get("/api/{league}/boxscore/{game_id}")
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


@app.get("/api/{league}/game/{game_id}/detail")
def get_game_detail(league: str, game_id: str):
    """NBA/NHL game detail: persisted team stats, scoring timeline, venue, and strength priors."""
    lg = league.lower()
    if lg not in ("nba", "nhl"):
        raise HTTPException(400, "game detail only available for NBA and NHL")
    out = {"game_id": game_id, "league": lg,
           "team_stats": [], "scoring_plays": [], "context": None, "strength": {},
           "final_score": None}
    # ── authoritative final score (ESPN summary, not derived from plays) ──
    try:
        out["final_score"] = _reconcile_final_score(lg, game_id)
    except Exception:
        pass
    with closing(_db()) as con:
        # Team stats
        for r in con.execute(
            "SELECT * FROM team_game_stats WHERE league=? AND game_id=? ORDER BY home_away",
            (lg, game_id)
        ).fetchall():
            out["team_stats"].append({
                "team_abbrev": r["team_abbrev"], "home_away": r["home_away"],
                "fgm_fga": r["fgm_fga"], "fg_pct": r["fg_pct"],
                "tpm_tpa": r["tpm_tpa"], "tp_pct": r["tp_pct"],
                "ftm_fta": r["ftm_fta"], "ft_pct": r["ft_pct"],
                "rebounds": r["rebounds"], "off_rebounds": r["off_rebounds"],
                "def_rebounds": r["def_rebounds"], "assists": r["assists"],
                "steals": r["steals"], "blocks": r["blocks"],
                "turnovers": r["turnovers"], "fouls": r["fouls"],
                "fast_break_pts": r["fast_break_pts"], "pts_in_paint": r["pts_in_paint"],
                "largest_lead": r["largest_lead"],
                "shots": r["shots"], "blocked_shots": r["blocked_shots"],
                "hits": r["hits"], "takeaways": r["takeaways"],
                "giveaways": r["giveaways"], "faceoffs_won": r["faceoffs_won"],
                "faceoff_pct": r["faceoff_pct"],
                "powerplay_goals": r["powerplay_goals"], "powerplay_opps": r["powerplay_opps"],
                "penalties": r["penalties"], "penalty_min": r["penalty_min"],
            })
        # Scoring plays
        for r in con.execute(
            "SELECT * FROM scoring_plays WHERE league=? AND game_id=? ORDER BY period, clock",
            (lg, game_id)
        ).fetchall():
            out["scoring_plays"].append({
                "period": r["period"], "period_disp": r["period_disp"],
                "clock": r["clock"], "away_score": r["away_score"],
                "home_score": r["home_score"], "team_abbrev": r["team_abbrev"],
                "play_text": r["play_text"], "play_type": r["play_type"],
            })
        # Game context
        ctx = con.execute(
            "SELECT * FROM game_context WHERE league=? AND game_id=?",
            (lg, game_id)
        ).fetchone()
        if ctx:
            import json
            out["context"] = {
                "venue_name": ctx["venue_name"], "venue_city": ctx["venue_city"],
                "attendance": ctx["attendance"],
                "officials": json.loads(ctx["officials"] or "[]"),
                "home_team": ctx["home_team"], "away_team": ctx["away_team"],
            }
        # Strength priors for both teams
        for ab in [out["context"]["home_team"], out["context"]["away_team"]] if out["context"] else []:
            if not ab: continue
            try:
                out["strength"][ab] = espn.team_strength_map(lg).get(ab)
            except Exception:
                pass
    return out


@app.get("/api/{league}/team/{team}/roster")
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


@app.post("/api/predictions")
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


@app.get("/api/predictions")
def list_predictions():
    out = []
    with closing(_db()) as con:
        for r in con.execute("SELECT * FROM predictions ORDER BY id").fetchall():
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


def _evaluate(league, game_id, predicted_winner):
    """True/False vs the REAL final, or None if the game isn't final yet."""
    try:
        res = espn.game_result(league, game_id)
    except ValueError:
        return None
    if res["winner"] is None:
        return None
    return predicted_winner.upper() == res["winner"].upper()


def _reconcile_final_score(league: str, game_id: str):
    """Return {home: int, away: int} from authoritative boxscore data, or None.

    Priority: ESPN summary endpoint (the single source of truth for finished
    games) → persisted scoring_plays (fallback if ESPN is unreachable).
    The DB is never authoritative — a mid-game snapshot can miss final plays.
    """
    lg = league.lower()

    # 1) ESPN summary — authoritative final scores for any finished game
    try:
        summary = _fetch_summary(lg, game_id)
        header = summary.get("header", {})
        comp = (header.get("competitions") or [{}])[0]
        # Verify the game is actually final before trusting the scores
        st = comp.get("status", {}).get("type", {})
        if st.get("state") == "post":
            home_score = away_score = None
            for c in comp.get("competitors", []):
                sc = _num(c.get("score"))
                if c.get("homeAway") == "home":
                    home_score = sc
                else:
                    away_score = sc
            if home_score is not None and away_score is not None:
                # Snapshot boxscore so DB stays warm for detail pages
                try:
                    _snapshot_boxscore_full(lg, game_id)
                except Exception:
                    pass
                return {"home": int(home_score), "away": int(away_score)}
    except Exception:
        pass  # ESPN unreachable — fall through to DB fallback

    # 2) DB scoring_plays — fallback only (may be incomplete for mid-game snapshots).
    # Use MAX per side: cumulative game scores are monotonic non-decreasing, so the max IS the final.
    # (Do NOT order by `clock` — it is TEXT with mixed formats '8:44' vs '9.4', so a string sort picks
    #  the wrong play; and the clock counts DOWN, so "latest" is the smallest value, not the largest.)
    with closing(_db()) as con:
        row = con.execute(
            "SELECT MAX(home_score) AS home, MAX(away_score) AS away FROM scoring_plays "
            "WHERE league=? AND game_id=?",
            (lg, game_id),
        ).fetchone()
        if row and row["home"] is not None and row["away"] is not None:
            return {"home": int(row["home"]), "away": int(row["away"])}

    return None


def _snapshot_strength(league, rows):
    """Persist a strength snapshot so we accumulate history (the trading side wants the time series)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO strength_snap(captured_at,league,abbrev,win_pct,differential,wins,losses) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, r["abbrev"], r["win_pct"], r["differential"], r["wins"], r["losses"])
             for r in rows])
        con.commit()


# ---------------------------------------------------------------------------
# NEW: data-collection helpers (NBA+NHL only). Follow the _snapshot_strength pattern:
# grab ESPN data, INSERT into SQLite. Called from endpoints so every API hit
# persists. The trading side reads these tables directly.
# ---------------------------------------------------------------------------

def _parse_int(v):
    try: return int(v)
    except (TypeError, ValueError): return None

def _parse_real(v):
    try: return float(v)
    except (TypeError, ValueError): return None

def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _fetch_summary(league, game_id):
    """Raw ESPN summary payload for a single game. Returns the full JSON dict."""
    import json, urllib.request
    _, path = espn._check(league)
    url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={game_id}"
    req = urllib.request.Request(url, headers=espn._HDRS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def _extract_team_stats(league, game_id, summary):
    """Parse boxscore.teams[].statistics[] → list of {team_abbrev, home_away, stats_dict}."""
    bs = summary.get("boxscore", {})
    teams = bs.get("teams", [])
    if not teams:
        # fall back to header
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        teams = [{"team": c.get("team", {}),
                   "statistics": [],
                   "_homeAway": c.get("homeAway")}
                  for c in comp.get("competitors", [])]
    out = []
    for t in teams:
        team_info = t.get("team", {})
        abbrev = team_info.get("abbreviation", "")
        home_away = t.get("_homeAway") or t.get("homeAway", "")
        raw = {}
        for s in t.get("statistics", []):
            name = s.get("name")
            if name:
                raw[name] = s.get("displayValue")
        out.append({"team_abbrev": abbrev, "home_away": home_away, "stats": raw})
    return out


def _extract_scoring_plays(league, game_id, summary):
    """Parse plays[] filtered to scoringPlay=true → list of dicts."""
    plays = summary.get("plays", [])
    out = []
    for p in plays:
        if not p.get("scoringPlay"):
            continue
        period = p.get("period", {})
        clock = p.get("clock", {})
        ptype = p.get("type", {})
        # Determine scoring team from text: "[Team] Goal" / "[Player] made..."
        text = p.get("text", "")
        team_abbrev = ""
        scorer = ""
        # Try to extract team from competitors or text pattern
        comp = (summary.get("header", {}).get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        if p.get("homeScore", 0) > p.get("_prev_home", -1) if "_prev_home" in p else (len(out) > 0 and p["homeScore"] > out[-1]["home_score"]):
            # home scored
            for c in competitors:
                if c.get("homeAway") == "home":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        elif len(competitors) == 2:
            # away scored (or we guess from context)
            for c in competitors:
                if c.get("homeAway") == "away":
                    team_abbrev = c.get("team", {}).get("abbreviation", "")
        out.append({
            "play_id": str(p.get("id", "")),
            "period": _parse_int(period.get("number")) if period else None,
            "period_disp": period.get("displayValue", "") if period else "",
            "clock": clock.get("displayValue", "") if clock else "",
            "away_score": _parse_int(p.get("awayScore")),
            "home_score": _parse_int(p.get("homeScore")),
            "team_abbrev": team_abbrev,
            "scorer_name": scorer,
            "play_text": text,
            "play_type": ptype.get("text", "") if ptype else "",
        })
    return out


def _extract_game_context(league, game_id, summary):
    """Parse gameInfo + header → {venue_name, venue_city, attendance, officials, home/away}."""
    gi = summary.get("gameInfo", {})
    venue = gi.get("venue", {})
    officials = [o.get("displayName", "") for o in gi.get("officials", [])]
    header = summary.get("header", {})
    comp = (header.get("competitions") or [{}])[0]
    home_team = ""
    away_team = ""
    for c in comp.get("competitors", []):
        ab = c.get("team", {}).get("abbreviation", "")
        if c.get("homeAway") == "home":
            home_team = ab
        else:
            away_team = ab
    import json
    return {
        "venue_name": venue.get("fullName", ""),
        "venue_city": venue.get("address", {}).get("city", ""),
        "attendance": _parse_int(gi.get("attendance")),
        "officials": json.dumps(officials) if officials else "[]",
        "home_team": home_team,
        "away_team": away_team,
    }


# --- snapshot functions (same pattern as _snapshot_strength) ---

def _snapshot_rosters(league, team_abbrev, players):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT INTO roster_snap(captured_at,league,team_abbrev,player_id,name,jersey,position) "
            "VALUES(?,?,?,?,?,?,?)",
            [(now, league, team_abbrev, p["player_id"], p["name"], p["jersey"], p["position"])
             for p in players])
        con.commit()


def _snapshot_team_game_stats(league, game_id, team_stats_list):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        for t in team_stats_list:
            s = t["stats"]
            con.execute(
                "INSERT OR REPLACE INTO team_game_stats("
                "league,game_id,captured_at,team_abbrev,home_away,"
                "fgm_fga,fg_pct,tpm_tpa,tp_pct,ftm_fta,ft_pct,"
                "rebounds,off_rebounds,def_rebounds,assists,steals,blocks,"
                "turnovers,fouls,pts_off_to,fast_break_pts,pts_in_paint,"
                "largest_lead,lead_changes,lead_pct,"
                "shots,blocked_shots,hits,takeaways,giveaways,faceoffs_won,"
                "faceoff_pct,powerplay_goals,powerplay_opps,powerplay_pct,"
                "shorthanded_goals,penalties,penalty_min"
                ") VALUES(?,?,?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,?,  ?,?,?,  ?,?,?,?,?,?,  ?,?,?,?,  ?,?,?)",
                (league, game_id, now, t["team_abbrev"], t["home_away"],
                 s.get("fieldGoalsMade-fieldGoalsAttempted"), _parse_real(s.get("fieldGoalPct")),
                 s.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"), _parse_real(s.get("threePointFieldGoalPct")),
                 s.get("freeThrowsMade-freeThrowsAttempted"), _parse_real(s.get("freeThrowPct")),
                 _parse_int(s.get("totalRebounds")), _parse_int(s.get("offensiveRebounds")),
                 _parse_int(s.get("defensiveRebounds")), _parse_int(s.get("assists")),
                 _parse_int(s.get("steals")), _parse_int(s.get("blocks")),
                 _parse_int(s.get("turnovers")), _parse_int(s.get("fouls")),
                 _parse_int(s.get("turnoverPoints")), _parse_int(s.get("fastBreakPoints")),
                 _parse_int(s.get("pointsInPaint")), _parse_int(s.get("largestLead")),
                 _parse_int(s.get("leadChanges")), _parse_real(s.get("leadPercentage")),
                 _parse_int(s.get("shotsTotal")), _parse_int(s.get("blockedShots")),
                 _parse_int(s.get("hits")), _parse_int(s.get("takeaways")),
                 _parse_int(s.get("giveaways")), _parse_int(s.get("faceoffsWon")),
                 _parse_real(s.get("faceoffPercent")), _parse_int(s.get("powerPlayGoals")),
                 _parse_int(s.get("powerPlayOpportunities")), _parse_real(s.get("powerPlayPct")),
                 _parse_int(s.get("shortHandedGoals")), _parse_int(s.get("penalties")),
                 _parse_int(s.get("penaltyMinutes"))))
        con.commit()


def _snapshot_scoring_plays(league, game_id, plays):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.executemany(
            "INSERT OR IGNORE INTO scoring_plays("
            "league,game_id,play_id,captured_at,period,period_disp,clock,"
            "away_score,home_score,team_abbrev,scorer_name,play_text,play_type"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(league, game_id, p["play_id"], now,
              p["period"], p["period_disp"], p["clock"],
              p["away_score"], p["home_score"], p["team_abbrev"],
              p["scorer_name"], p["play_text"], p["play_type"])
             for p in plays])
        con.commit()


def _snapshot_game_context(league, game_id, ctx):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as con:
        con.execute(
            "INSERT OR REPLACE INTO game_context("
            "league,game_id,captured_at,home_team,away_team,"
            "venue_name,venue_city,attendance,officials"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (league, game_id, now,
             ctx["home_team"], ctx["away_team"],
             ctx["venue_name"], ctx["venue_city"],
             ctx["attendance"], ctx["officials"]))
        con.commit()


def _snapshot_boxscore_full(league, game_id):
    """One call snapshots team_game_stats + scoring_plays + game_context for a game."""
    try:
        summary = _fetch_summary(league, game_id)
    except Exception:
        return  # game not available yet (pre-game) — silently skip
    team_stats = _extract_team_stats(league, game_id, summary)
    if team_stats:
        _snapshot_team_game_stats(league, game_id, team_stats)
    plays = _extract_scoring_plays(league, game_id, summary)
    if plays:
        _snapshot_scoring_plays(league, game_id, plays)
    ctx = _extract_game_context(league, game_id, summary)
    _snapshot_game_context(league, game_id, ctx)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
