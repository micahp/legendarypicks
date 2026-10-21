"""Storage for FBS model previews, locks, grades and ratings.

Deliberately separate from the picks databases, exactly like the NHL model store: this is a
read-only model surface, and nothing here can move a pick, a price or a locked forecast.

Invariants
  * A lock is written once, inside its T-90 window [kickoff - LOCK_LEAD, kickoff), with
    lock_protocol = 't90'. Its probability, kickoff and lock time are immutable (triggers).
  * A preview is display-only. It is replaced on every run, is never graded, and is never
    copied into fbs_forecasts.
  * Nothing locks after kickoff. A previewed game that reaches kickoff with no lock is
    recorded once in fbs_lock_events as missed_t90_window.
  * Rows written before this protocol have lock_protocol = 'legacy'. Their kickoffs were
    stored as midnight UTC, so their lock times and late flags are not provable. They stay
    visible, labelled, and are excluded from the official record. They are not converted.
  * Grading only fills result, home_score, away_score, graded_at_utc; it never touches a
    probability.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3

LOCK_LEAD = dt.timedelta(minutes=90)
LOCK_PROTOCOL = "t90"
LEGACY_PROTOCOL = "legacy"
MISSED_EVENT = "missed_t90_window"

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
    lock_protocol TEXT,
    result INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    graded_at_utc TEXT,
    PRIMARY KEY (game_id, model)
);
CREATE INDEX IF NOT EXISTS fbs_forecasts_season ON fbs_forecasts(season, kickoff_utc);
CREATE TABLE IF NOT EXISTS fbs_previews (
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
    previewed_at_utc TEXT NOT NULL,
    PRIMARY KEY (game_id, model)
);
CREATE TABLE IF NOT EXISTS fbs_lock_events (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    kickoff_utc TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type = 'missed_t90_window'),
    recorded_at_utc TEXT NOT NULL,
    PRIMARY KEY (game_id, model, event_type)
);
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

# Created after migration: they name lock_protocol, which an older database lacks until then.
TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS fbs_forecast_lock_immutable
BEFORE UPDATE OF p_home, fair_home, fair_away, kickoff_utc, locked_at_utc, late,
    lock_protocol, model_version ON fbs_forecasts
BEGIN SELECT RAISE(ABORT, 'FBS locked forecasts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_forecast_no_delete
BEFORE DELETE ON fbs_forecasts
BEGIN SELECT RAISE(ABORT, 'FBS forecasts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_lock_event_immutable
BEFORE UPDATE ON fbs_lock_events
BEGIN SELECT RAISE(ABORT, 'FBS lock events are immutable'); END;
"""


def open_db(path: str = DEFAULT_DB, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path)
        con.executescript(SCHEMA)
        _migrate(con)
        con.executescript(TRIGGERS)
        con.commit()
    con.row_factory = sqlite3.Row
    return con


def _migrate(con: sqlite3.Connection) -> None:
    """Add lock_protocol to databases created before it. Existing rows are labelled legacy."""
    columns = {row[1] for row in con.execute("PRAGMA table_info(fbs_forecasts)")}
    if "lock_protocol" not in columns:
        con.execute("ALTER TABLE fbs_forecasts ADD COLUMN lock_protocol TEXT")
        con.execute("UPDATE fbs_forecasts SET lock_protocol = ? WHERE lock_protocol IS NULL",
                    (LEGACY_PROTOCOL,))


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def american_from_probability(p: float) -> int | None:
    """Fair American price for a probability. Model odds, not a market price."""
    if p is None or not (0.0 < p < 1.0):
        return None
    if p >= 0.5:
        return -int(round(100.0 * p / (1.0 - p)))
    return int(round(100.0 * (1.0 - p) / p))


def _protocol(row: sqlite3.Row) -> str:
    # A database that has not been migrated has no column; every row in it predates the protocol.
    if "lock_protocol" in row.keys() and row["lock_protocol"]:
        return row["lock_protocol"]
    return LEGACY_PROTOCOL


def upsert_previews(con: sqlite3.Connection, rows: list[dict],
                    now: dt.datetime | None = None) -> int:
    """Display-only forecasts until kickoff. A preview never locks; the lock path decides that.

    Inside the lock window a preview is still written, so a game whose lock is not taken
    stays visible as a preview and can be recorded as missed at kickoff.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    written = 0
    for row in rows:
        if now >= parse_time(row["kickoff_utc"]):
            continue
        con.execute(
            "INSERT INTO fbs_previews(game_id,model,season,kickoff_utc,home_team,away_team,"
            " home_team_id,away_team_id,model_version,p_home,fair_home,fair_away,fitted_through,"
            " previewed_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(game_id,model) DO UPDATE SET kickoff_utc=excluded.kickoff_utc,"
            " home_team=excluded.home_team, away_team=excluded.away_team,"
            " home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id,"
            " model_version=excluded.model_version, p_home=excluded.p_home,"
            " fair_home=excluded.fair_home, fair_away=excluded.fair_away,"
            " fitted_through=excluded.fitted_through, previewed_at_utc=excluded.previewed_at_utc",
            (row["game_id"], row["model"], row["season"], row["kickoff_utc"],
             row["home_team"], row["away_team"], row.get("home_team_id"), row.get("away_team_id"),
             row["model_version"], row["p_home"],
             american_from_probability(row["p_home"]),
             american_from_probability(1.0 - row["p_home"]),
             row.get("fitted_through"), now.isoformat()),
        )
        written += 1
    con.commit()
    return written


def lock_forecasts(con: sqlite3.Connection, rows: list[dict],
                   now: dt.datetime | None = None) -> dict:
    """Insert each forecast once, and only inside its T-90 window. Returns counts."""
    now = now or dt.datetime.now(dt.timezone.utc)
    report = {"inserted": 0, "existing": 0, "not_due": 0, "after_kickoff": 0}
    for row in rows:
        kickoff = parse_time(row["kickoff_utc"])
        if now < kickoff - LOCK_LEAD:
            report["not_due"] += 1
            continue
        if now >= kickoff:
            report["after_kickoff"] += 1
            continue
        cursor = con.execute(
            "INSERT OR IGNORE INTO fbs_forecasts"
            "(game_id,model,season,kickoff_utc,home_team,away_team,home_team_id,away_team_id,"
            " model_version,p_home,fair_home,fair_away,fitted_through,created_at_utc,"
            " locked_at_utc,late,lock_protocol) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
            (row["game_id"], row["model"], row["season"], row["kickoff_utc"],
             row["home_team"], row["away_team"], row.get("home_team_id"), row.get("away_team_id"),
             row["model_version"], row["p_home"],
             american_from_probability(row["p_home"]),
             american_from_probability(1.0 - row["p_home"]),
             row.get("fitted_through"), now.isoformat(), now.isoformat(), LOCK_PROTOCOL),
        )
        report["inserted" if cursor.rowcount else "existing"] += 1
    con.commit()
    return report


def record_missed_windows(con: sqlite3.Connection, now: dt.datetime | None = None) -> int:
    """Previewed games that reached kickoff with no lock. Recorded once, never backfilled."""
    now = now or dt.datetime.now(dt.timezone.utc)
    locked = {(row[0], row[1]) for row in con.execute(
        "SELECT game_id, model FROM fbs_forecasts WHERE lock_protocol = ?", (LOCK_PROTOCOL,))}
    missed = 0
    for row in con.execute("SELECT game_id, model, season, kickoff_utc FROM fbs_previews").fetchall():
        if (row["game_id"], row["model"]) in locked or now < parse_time(row["kickoff_utc"]):
            continue
        cursor = con.execute(
            "INSERT OR IGNORE INTO fbs_lock_events"
            "(game_id,model,season,kickoff_utc,event_type,recorded_at_utc) VALUES(?,?,?,?,?,?)",
            (row["game_id"], row["model"], row["season"], row["kickoff_utc"], MISSED_EVENT,
             now.isoformat()),
        )
        missed += cursor.rowcount
    con.commit()
    return missed


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


def pending_grades(con: sqlite3.Connection, now: dt.datetime) -> list[tuple[str, str]]:
    """Games with a forecast, no result yet, and a kickoff that has passed."""
    rows = con.execute("SELECT DISTINCT game_id, kickoff_utc FROM fbs_forecasts WHERE result IS NULL").fetchall()
    return [(row[0], row[1]) for row in rows if parse_time(row[1]) < now]


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
    brier = sum((r["p_home"] - r["result"]) ** 2 for r in graded) / len(graded)
    eps = 1e-12
    log_loss = -sum(r["result"] * math.log(max(r["p_home"], eps))
                    + (1 - r["result"]) * math.log(max(1 - r["p_home"], eps))
                    for r in graded) / len(graded)
    correct = sum(1 for r in graded if (r["p_home"] >= 0.5) == (r["result"] == 1))
    return {"graded": len(graded), "brier": round(brier, 4),
            "log_loss": round(log_loss, 4), "accuracy": round(correct / len(graded), 4)}


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                       (name,)).fetchone() is not None


def _game_shell(game_id: str, kickoff: str, home: str, away: str) -> dict:
    return {"game_id": game_id, "kickoff_utc": kickoff, "home_team": home, "away_team": away,
            "status": None, "locked_at_utc": None, "late": False, "result": None, "models": {}}


def export_payload(con: sqlite3.Connection, season: int) -> dict:
    rows = con.execute("SELECT * FROM fbs_forecasts WHERE season=? ORDER BY kickoff_utc",
                       (season,)).fetchall()
    previews = []
    missed = set()
    if _table_exists(con, "fbs_previews"):
        previews = con.execute("SELECT * FROM fbs_previews WHERE season=? ORDER BY kickoff_utc",
                               (season,)).fetchall()
        missed = {(r[0], r[1]) for r in con.execute(
            "SELECT game_id, model FROM fbs_lock_events WHERE season=? AND event_type=?",
            (season, MISSED_EVENT))}
    missed_games = {game_id for game_id, _ in missed}

    records = {}
    for model in MODEL_IDS:
        model_rows = [r for r in rows if r["model"] == model]
        official = [r for r in model_rows if _protocol(r) == LOCK_PROTOCOL and not r["late"]]
        records[model] = {**_score(official), "forecasts": len(official),
                          "legacy": sum(1 for r in model_rows if _protocol(r) == LEGACY_PROTOCOL),
                          "late": sum(1 for r in model_rows if r["late"]),
                          "missed": sum(1 for _, m in missed if m == model)}

    games: dict[str, dict] = {}
    for row in rows:
        game = games.setdefault(row["game_id"], _game_shell(
            row["game_id"], row["kickoff_utc"], row["home_team"], row["away_team"]))
        game["status"] = "locked" if _protocol(row) == LOCK_PROTOCOL else "legacy"
        game["locked_at_utc"] = game["locked_at_utc"] or row["locked_at_utc"]
        game["late"] = game["late"] or bool(row["late"])
        if row["result"] is not None and game["result"] is None:
            game["result"] = {"home_score": row["home_score"], "away_score": row["away_score"],
                              "home_win": bool(row["result"])}
        game["models"][row["model"]] = {
            "p_home": round(row["p_home"], 4),
            "p_away": round(1.0 - row["p_home"], 4),
            "fair_home": row["fair_home"], "fair_away": row["fair_away"],
            "model_version": row["model_version"],
            "fitted_through": row["fitted_through"],
            "locked_at_utc": row["locked_at_utc"],
        }

    locked_games = set(games)
    for row in previews:
        if row["game_id"] in locked_games:
            continue
        game = games.setdefault(row["game_id"], _game_shell(
            row["game_id"], row["kickoff_utc"], row["home_team"], row["away_team"]))
        game["status"] = "missed" if row["game_id"] in missed_games else "preview"
        if game["status"] == "preview":
            game["models"][row["model"]] = {
                "p_home": round(row["p_home"], 4),
                "p_away": round(1.0 - row["p_home"], 4),
                "fair_home": row["fair_home"], "fair_away": row["fair_away"],
                "model_version": row["model_version"],
                "fitted_through": row["fitted_through"],
                "previewed_at_utc": row["previewed_at_utc"],
            }
    ratings = [dict(r) for r in con.execute(
        "SELECT * FROM fbs_ratings WHERE season=? ORDER BY rating DESC", (season,)).fetchall()]
    meta = {r["key"]: json.loads(r["value"]) for r in con.execute(
        "SELECT key,value FROM fbs_model_meta").fetchall()}
    ordered = sorted(games.values(), key=lambda g: g["kickoff_utc"])
    return {
        "league": "ncaaf",
        "default_model": DEFAULT_MODEL,
        "models": [{"id": m, "label": MODEL_LABELS[m], "note": MODEL_NOTES[m]} for m in MODEL_IDS],
        "records": records,
        "season": season,
        "games": ordered,
        "ratings": ratings,
        "meta": meta,
        "state": "available" if ordered else "awaiting_first_lock",
        "source": "standalone FBS model database",
    }
