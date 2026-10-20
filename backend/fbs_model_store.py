"""Storage for FBS model forecasts, locks, grades and ratings.

Deliberately separate from the picks databases, exactly like the NHL model store: this is a
read-only model surface, and nothing here can move a pick, a price or a locked forecast.

Invariants
  * A forecast row is written once. `p_home` is never updated; a refit before kickoff inserts
    a new model_version, it does not rewrite history.
  * `locked_at_utc` is set on insert and is always earlier than kickoff. A forecast first seen
    after kickoff is stored with `locked_at_utc = NULL` and `late = 1` — it is a backtest row
    and is excluded from the live record.
  * Grading only fills `result`, `home_score`, `away_score`; it never touches a probability.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3

MODEL_IDS = ("g2", "c2", "g2h")
DEFAULT_MODEL = "g2h"
MODEL_LABELS = {
    "g2": "Basic Elo",
    "c2": "Drive + efficiency",
    "g2h": "Hierarchical",
}
MODEL_NOTES = {
    "g2": "Chronological Elo with home-field and a fitted margin scale.",
    "c2": "Flat ridge logistic on the G2 offset plus seven drive splits.",
    "g2h": "Hierarchical random intercepts per team-season within conference, same features.",
}
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fbs-model.dev.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS fbs_forecasts (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    kickoff_utc TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_team_id TEXT,
    away_team_id TEXT,
    model_version TEXT NOT NULL,
    p_home REAL NOT NULL,
    fair_home INTEGER,
    fair_away INTEGER,
    fitted_through TEXT,
    created_at_utc TEXT NOT NULL,
    locked_at_utc TEXT,
    late INTEGER NOT NULL DEFAULT 0,
    result INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    graded_at_utc TEXT,
    PRIMARY KEY (game_id, model)
);
CREATE INDEX IF NOT EXISTS fbs_forecasts_season ON fbs_forecasts(season, kickoff_utc);
CREATE TABLE IF NOT EXISTS fbs_ratings (
    season INTEGER NOT NULL,
    team_id TEXT NOT NULL,
    team TEXT NOT NULL,
    conference TEXT,
    rating REAL,
    games_used INTEGER,
    as_of_utc TEXT NOT NULL,
    PRIMARY KEY (season, team_id)
);
CREATE TABLE IF NOT EXISTS fbs_model_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def open_db(path: str = DEFAULT_DB, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path)
        con.executescript(SCHEMA)
        con.commit()
    con.row_factory = sqlite3.Row
    return con


def american_from_probability(p: float) -> int | None:
    """Fair American price for a probability. Model odds, not a market price."""
    if p is None or not (0.0 < p < 1.0):
        return None
    if p >= 0.5:
        return -int(round(100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def lock_forecasts(con: sqlite3.Connection, rows: list[dict],
                   now: dt.datetime | None = None) -> dict:
    """Insert forecasts once. Returns counts of new, existing and late rows."""
    now = now or dt.datetime.now(dt.timezone.utc)
    report = {"inserted": 0, "existing": 0, "late": 0}
    for row in rows:
        kickoff = dt.datetime.fromisoformat(row["kickoff_utc"].replace("Z", "+00:00"))
        late = kickoff <= now
        cursor = con.execute(
            "INSERT OR IGNORE INTO fbs_forecasts"
            "(game_id,model,season,kickoff_utc,home_team,away_team,home_team_id,away_team_id,"
            " model_version,p_home,fair_home,fair_away,fitted_through,created_at_utc,"
            " locked_at_utc,late) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["game_id"], row["model"], row["season"], row["kickoff_utc"],
             row["home_team"], row["away_team"], row.get("home_team_id"), row.get("away_team_id"),
             row["model_version"], row["p_home"],
             american_from_probability(row["p_home"]),
             american_from_probability(1.0 - row["p_home"]),
             row.get("fitted_through"), now.isoformat(),
             None if late else now.isoformat(), 1 if late else 0),
        )
        if cursor.rowcount:
            report["inserted"] += 1
            if late:
                report["late"] += 1
        else:
            report["existing"] += 1
    con.commit()
    return report


def grade_forecasts(con: sqlite3.Connection, results: dict[str, dict],
                    now: dt.datetime | None = None) -> int:
    """Fill outcomes for games whose result is known. Never touches a probability."""
    now = now or dt.datetime.now(dt.timezone.utc)
    graded = 0
    for game_id, result in results.items():
        home_score, away_score = result.get("home_score"), result.get("away_score")
        if home_score is None or away_score is None:
            continue
        outcome = 1 if home_score > away_score else 0
        cursor = con.execute(
            "UPDATE fbs_forecasts SET result=?, home_score=?, away_score=?, graded_at_utc=? "
            "WHERE game_id=? AND result IS NULL AND kickoff_utc < ?",
            (outcome, home_score, away_score, now.isoformat(), game_id,
             now.isoformat()),
        )
        graded += cursor.rowcount
    con.commit()
    return graded


def store_ratings(con: sqlite3.Connection, rows: list[dict], as_of: str) -> int:
    for row in rows:
        con.execute(
            "INSERT INTO fbs_ratings(season,team_id,team,conference,rating,games_used,as_of_utc)"
            " VALUES(?,?,?,?,?,?,?) ON CONFLICT(season,team_id) DO UPDATE SET"
            " team=excluded.team, conference=excluded.conference, rating=excluded.rating,"
            " games_used=excluded.games_used, as_of_utc=excluded.as_of_utc",
            (row["season"], row["team_id"], row["team"], row.get("conference"),
             row.get("rating"), row.get("games_used"), as_of),
        )
    con.commit()
    return len(rows)


def set_meta(con: sqlite3.Connection, **values) -> None:
    for key, value in values.items():
        con.execute("INSERT INTO fbs_model_meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))
    con.commit()


def _score(rows: list[sqlite3.Row]) -> dict:
    graded = [r for r in rows if r["result"] is not None]
    if not graded:
        return {"graded": 0, "brier": None, "log_loss": None, "accuracy": None}
    import math
    brier = sum((r["p_home"] - r["result"]) ** 2 for r in graded) / len(graded)
    eps = 1e-12
    log_loss = -sum(r["result"] * math.log(max(r["p_home"], eps))
                    + (1 - r["result"]) * math.log(max(1 - r["p_home"], eps))
                    for r in graded) / len(graded)
    correct = sum(1 for r in graded if (r["p_home"] >= 0.5) == (r["result"] == 1))
    return {"graded": len(graded), "brier": round(brier, 4),
            "log_loss": round(log_loss, 4), "accuracy": round(correct / len(graded), 4)}


def export_payload(con: sqlite3.Connection, season: int) -> dict:
    rows = con.execute("SELECT * FROM fbs_forecasts WHERE season=? ORDER BY kickoff_utc",
                       (season,)).fetchall()
    games: dict[str, dict] = {}
    records = {}
    for model in MODEL_IDS:
        model_rows = [r for r in rows if r["model"] == model]
        live = [r for r in model_rows if not r["late"]]
        records[model] = {**_score(live), "forecasts": len(live),
                          "late": sum(1 for r in model_rows if r["late"])}
    for row in rows:
        game = games.setdefault(row["game_id"], {
            "game_id": row["game_id"], "kickoff_utc": row["kickoff_utc"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "locked_at_utc": row["locked_at_utc"], "late": bool(row["late"]),
            "result": None if row["result"] is None else {
                "home_score": row["home_score"], "away_score": row["away_score"],
                "home_win": bool(row["result"])},
            "models": {},
        })
        game["models"][row["model"]] = {
            "p_home": round(row["p_home"], 4),
            "p_away": round(1.0 - row["p_home"], 4),
            "fair_home": row["fair_home"], "fair_away": row["fair_away"],
            "model_version": row["model_version"],
            "fitted_through": row["fitted_through"],
        }
    ratings = [dict(r) for r in con.execute(
        "SELECT * FROM fbs_ratings WHERE season=? ORDER BY rating DESC", (season,)).fetchall()]
    meta = {r["key"]: json.loads(r["value"]) for r in con.execute(
        "SELECT key,value FROM fbs_model_meta").fetchall()}
    return {
        "league": "ncaaf",
        "default_model": DEFAULT_MODEL,
        "models": [{"id": m, "label": MODEL_LABELS[m], "note": MODEL_NOTES[m]} for m in MODEL_IDS],
        "records": records,
        "season": season,
        "games": sorted(games.values(), key=lambda g: g["kickoff_utc"]),
        "ratings": ratings,
        "meta": meta,
        "state": "available" if games else "awaiting_first_lock",
        "source": "standalone FBS model database",
    }
