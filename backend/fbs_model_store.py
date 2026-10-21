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

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sqlite3

from fbs_lifecycle import NO_WINDOW_LIFECYCLES, is_lockable

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
CREATE TABLE IF NOT EXISTS fbs_fixture_revisions (
    game_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    season INTEGER NOT NULL,
    kickoff_utc TEXT NOT NULL,
    home_team TEXT,
    away_team TEXT,
    home_team_id TEXT,
    away_team_id TEXT,
    neutral_site INTEGER,
    observed_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (game_id, revision)
);
CREATE TABLE IF NOT EXISTS fbs_game_status (
    game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    revision INTEGER NOT NULL,
    lifecycle TEXT NOT NULL,
    status_name TEXT,
    observed_utc TEXT NOT NULL,
    source TEXT NOT NULL,
    grading_state TEXT NOT NULL,
    reason TEXT,
    pregame_lifecycle TEXT,
    pregame_observed_utc TEXT
);
CREATE TABLE IF NOT EXISTS fbs_window_outcomes (
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    season INTEGER NOT NULL,
    kickoff_utc TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('missed_t90_window', 'blocked_unverified_at_cutoff',
                                             'window_not_eligible')),
    lifecycle_at_cutoff TEXT,
    reason TEXT,
    recorded_at_utc TEXT NOT NULL,
    PRIMARY KEY (game_id, model)
);
CREATE TABLE IF NOT EXISTS fbs_unresolved (
    game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    kickoff_utc TEXT NOT NULL,
    reason TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_attempt_utc TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_utc TEXT NOT NULL,
    alert_state TEXT NOT NULL,
    resolved_utc TEXT
);
CREATE TABLE IF NOT EXISTS fbs_run_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subsystem TEXT NOT NULL,
    status TEXT NOT NULL,
    started_utc TEXT NOT NULL,
    detail TEXT
);
"""

# Created after migration: they name lock_protocol, which an older database lacks until then.
TRIGGERS = """
DROP TRIGGER IF EXISTS fbs_forecast_lock_immutable;
DROP TRIGGER IF EXISTS fbs_forecast_no_delete;
DROP TRIGGER IF EXISTS fbs_lock_event_immutable;
DROP TRIGGER IF EXISTS fbs_window_outcome_immutable;
CREATE TRIGGER IF NOT EXISTS fbs_forecast_lock_immutable
BEFORE UPDATE OF p_home, fair_home, fair_away, kickoff_utc, locked_at_utc, late,
    lock_protocol, model_version, kickoff_revision ON fbs_forecasts
BEGIN SELECT RAISE(ABORT, 'FBS locked forecasts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_forecast_no_delete
BEFORE DELETE ON fbs_forecasts
BEGIN SELECT RAISE(ABORT, 'FBS forecasts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_lock_event_immutable
BEFORE UPDATE ON fbs_lock_events
BEGIN SELECT RAISE(ABORT, 'FBS lock events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_window_outcome_immutable
BEFORE UPDATE ON fbs_window_outcomes
BEGIN SELECT RAISE(ABORT, 'FBS window outcomes are immutable'); END;
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
    if "kickoff_revision" not in columns:
        con.execute("ALTER TABLE fbs_forecasts ADD COLUMN kickoff_revision INTEGER NOT NULL DEFAULT 1")
    status_columns = {row[1] for row in con.execute("PRAGMA table_info(fbs_game_status)")}
    for column in ("pregame_lifecycle", "pregame_observed_utc"):
        if column not in status_columns:
            con.execute("ALTER TABLE fbs_game_status ADD COLUMN %s TEXT" % column)


def begin(con: sqlite3.Connection) -> None:
    """Open one write transaction now, so that a step's writes commit or roll back together."""
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")


def _readonly(path: str) -> sqlite3.Connection:
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def _table_digest(path: str, table: str, columns: list[str]) -> tuple[int, str]:
    """Row count and a digest over the named columns, in key order. Used to prove existing rows are unchanged."""
    con = _readonly(path)
    try:
        digest, count = hashlib.sha256(), 0
        for row in con.execute("SELECT %s FROM %s ORDER BY game_id, model" % (", ".join(columns), table)):
            digest.update(repr(tuple(row)).encode())
            count += 1
        return count, digest.hexdigest()
    finally:
        con.close()


def migrate(path: str, backup_dir: str) -> dict:
    """Bring one database to the current schema, with evidence. A backup is written first. Every column that
    fbs_forecasts had before is then compared row by row: any change raises, and the backup is left in place.
    Run it on a copy first; the operational file is migrated only with explicit authorization."""
    con = _readonly(path)
    try:
        before_tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        before_columns = [r[1] for r in con.execute("PRAGMA table_info(fbs_forecasts)")]
    finally:
        con.close()
    count_before, digest_before = _table_digest(path, "fbs_forecasts", before_columns)

    os.makedirs(backup_dir, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = os.path.join(backup_dir, "%s.pre-migrate-%s" % (os.path.basename(path), stamp))
    if os.path.exists(backup):
        raise RuntimeError("backup already exists, refusing to overwrite it: %s" % backup)
    source, target = _readonly(path), sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    open_db(path).close()                 # SCHEMA, then _migrate, then TRIGGERS: the migration itself

    count_after, digest_after = _table_digest(path, "fbs_forecasts", before_columns)
    if (count_after, digest_after) != (count_before, digest_before):
        raise RuntimeError("migration changed existing fbs_forecasts rows (%d -> %d); restore from %s"
                           % (count_before, count_after, backup))
    con = _readonly(path)
    try:
        after_tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        protocols = dict(con.execute("SELECT lock_protocol, COUNT(*) FROM fbs_forecasts GROUP BY 1").fetchall())
    finally:
        con.close()
    if before_tables - after_tables:
        raise RuntimeError("migration dropped tables: %s" % sorted(before_tables - after_tables))
    if integrity != "ok":
        raise RuntimeError("integrity_check after migration: %s" % integrity)
    return {"backup": backup, "forecast_rows_before": count_before, "forecast_rows_after": count_after,
            "existing_columns_digest": digest_after, "tables_added": sorted(after_tables - before_tables),
            "lock_protocols": protocols, "integrity": integrity}


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
                    now: dt.datetime | None = None, commit: bool = True) -> int:
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
    if commit:
        con.commit()
    return written


def lock_forecasts(con: sqlite3.Connection, rows: list[dict],
                   now: dt.datetime | None = None, commit: bool = True) -> dict:
    """Insert each forecast once, only inside its T-90 window, and only for a scheduled game whose
    kickoff is the current fixture revision. Returns counts. A started or unverified game never locks."""
    now = now or dt.datetime.now(dt.timezone.utc)
    report = {"inserted": 0, "existing": 0, "not_due": 0, "after_kickoff": 0,
              "blocked_status": 0, "blocked_revision": 0}
    for row in rows:
        kickoff = parse_time(row["kickoff_utc"])
        if now < kickoff - LOCK_LEAD:
            report["not_due"] += 1
            continue
        if now >= kickoff:
            report["after_kickoff"] += 1
            continue
        status = game_status(con, row["game_id"])
        if status is None or not is_lockable(status["lifecycle"], kickoff, now):
            report["blocked_status"] += 1
            continue
        fixture = current_fixture(con, row["game_id"])
        if fixture is None or parse_time(fixture["kickoff_utc"]) != kickoff:
            report["blocked_revision"] += 1
            continue
        if (fixture["home_team_id"], fixture["away_team_id"]) != (str(row.get("home_team_id")), str(row.get("away_team_id"))):
            report["blocked_status"] += 1      # the opponent changed: never the same fixture
            continue
        cursor = con.execute(
            "INSERT OR IGNORE INTO fbs_forecasts"
            "(game_id,model,season,kickoff_utc,home_team,away_team,home_team_id,away_team_id,"
            " model_version,p_home,fair_home,fair_away,fitted_through,created_at_utc,"
            " locked_at_utc,late,lock_protocol,kickoff_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
            (row["game_id"], row["model"], row["season"], row["kickoff_utc"],
             row["home_team"], row["away_team"], row.get("home_team_id"), row.get("away_team_id"),
             row["model_version"], row["p_home"],
             american_from_probability(row["p_home"]),
             american_from_probability(1.0 - row["p_home"]),
             row.get("fitted_through"), now.isoformat(), now.isoformat(), LOCK_PROTOCOL,
             fixture["revision"]),
        )
        report["inserted" if cursor.rowcount else "existing"] += 1
    if commit:
        con.commit()
    return report


def window_outcome(status: dict | None) -> tuple[str, str | None, str]:
    """Classify a window that closed without a lock. Exactly one outcome per game and model.

    missed_t90_window: the game was verified scheduled before its kickoff, so the window existed, and no
    lock was written. blocked_unverified_at_cutoff: no verified pregame status existed, so the game was
    never eligible to lock. window_not_eligible: postponed, delayed, suspended, cancelled or another
    non-window status before kickoff.
    """
    if status is None:
        return "blocked_unverified_at_cutoff", None, "no_status_observed"
    if status.get("reason") == "identity_changed":
        return "blocked_unverified_at_cutoff", status.get("pregame_lifecycle"), "identity_changed"
    pregame = status.get("pregame_lifecycle")
    if pregame is None or pregame == "unknown":
        return "blocked_unverified_at_cutoff", pregame, "pregame_status_unverified"
    if pregame in NO_WINDOW_LIFECYCLES:
        return "window_not_eligible", pregame, pregame
    if pregame == "scheduled":
        return "missed_t90_window", pregame, "scheduled_and_unlocked"
    return "blocked_unverified_at_cutoff", pregame, "pregame_status_not_scheduled"


def record_missed_windows(con: sqlite3.Connection, now: dt.datetime | None = None,
                          commit: bool = True) -> dict:
    """Classify every previewed game whose current kickoff has passed without a lock. Recorded once."""
    now = now or dt.datetime.now(dt.timezone.utc)
    locked = {(row[0], row[1]) for row in con.execute(
        "SELECT game_id, model FROM fbs_forecasts WHERE lock_protocol = ?", (LOCK_PROTOCOL,))}
    recorded = {(row[0], row[1]) for row in con.execute("SELECT game_id, model FROM fbs_window_outcomes")}
    counts = {"missed_t90_window": 0, "blocked_unverified_at_cutoff": 0, "window_not_eligible": 0}
    for row in con.execute("SELECT game_id, model, season, kickoff_utc FROM fbs_previews").fetchall():
        key = (row["game_id"], row["model"])
        if key in locked or key in recorded:
            continue
        fixture = current_fixture(con, row["game_id"])
        kickoff_text = fixture["kickoff_utc"] if fixture else row["kickoff_utc"]
        if now < parse_time(kickoff_text):
            continue
        outcome, lifecycle, reason = window_outcome(game_status(con, row["game_id"]))
        con.execute(
            "INSERT INTO fbs_window_outcomes(game_id,model,season,kickoff_utc,outcome,lifecycle_at_cutoff,"
            " reason,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?)",
            (row["game_id"], row["model"], row["season"], kickoff_text, outcome, lifecycle, reason,
             now.isoformat()))
        counts[outcome] += 1
    if commit:
        con.commit()
    return counts


def grade_forecasts(con: sqlite3.Connection, results: dict[str, dict],
                    now: dt.datetime | None = None, commit: bool = True) -> int:
    """Fill outcomes for games whose final result is confirmed. Never touches a probability.
    Voided and quarantined games are never graded."""
    now = now or dt.datetime.now(dt.timezone.utc)
    graded = 0
    for game_id, result in results.items():
        home_score, away_score = result.get("home_score"), result.get("away_score")
        if home_score is None or away_score is None:
            continue
        status = game_status(con, game_id)
        if status and status["grading_state"] in ("void", "quarantined"):
            continue
        outcome = 1 if home_score > away_score else 0
        cursor = con.execute(
            "UPDATE fbs_forecasts SET result=?, home_score=?, away_score=?, graded_at_utc=? "
            "WHERE game_id=? AND result IS NULL AND kickoff_utc < ?",
            (outcome, home_score, away_score, now.isoformat(), game_id,
             now.isoformat()),
        )
        if cursor.rowcount:
            con.execute("UPDATE fbs_game_status SET grading_state='graded', lifecycle='completed', "
                        "reason=NULL WHERE game_id=?", (game_id,))
        graded += cursor.rowcount
    if commit:
        con.commit()
    return graded


def pending_grades(con: sqlite3.Connection, now: dt.datetime) -> list[tuple[str, str]]:
    """Locked, ungraded games whose kickoff has passed, and which are due for a grading attempt.

    Legacy rows are never graded. Voided and quarantined games are excluded. An unresolved game is
    retried only when its backoff has elapsed.
    """
    rows = con.execute(
        "SELECT DISTINCT f.game_id, f.kickoff_utc FROM fbs_forecasts f "
        "WHERE f.result IS NULL AND f.lock_protocol = ? "
        "AND NOT EXISTS (SELECT 1 FROM fbs_game_status s WHERE s.game_id = f.game_id "
        "                AND s.grading_state IN ('void', 'quarantined', 'graded'))",
        (LOCK_PROTOCOL,)).fetchall()
    due_at = {row[0]: parse_time(row[1]) for row in con.execute(
        "SELECT game_id, next_attempt_utc FROM fbs_unresolved WHERE resolved_utc IS NULL")}
    return [(row[0], row[1]) for row in rows
            if parse_time(row[1]) < now and due_at.get(row[0], now) <= now]


def store_ratings(con: sqlite3.Connection, rows: list[dict], as_of: str, commit: bool = True) -> int:
    for row in rows:
        con.execute(
            "INSERT INTO fbs_ratings(season,team_id,team,conference,rating,games_used,as_of_utc)"
            " VALUES(?,?,?,?,?,?,?) ON CONFLICT(season,team_id) DO UPDATE SET"
            " team=excluded.team, conference=excluded.conference, rating=excluded.rating,"
            " games_used=excluded.games_used, as_of_utc=excluded.as_of_utc",
            (row["season"], row["team_id"], row["team"], row.get("conference"),
             row.get("rating"), row.get("games_used"), as_of),
        )
    if commit:
        con.commit()
    return len(rows)


def set_meta(con: sqlite3.Connection, commit: bool = True, **values) -> None:
    for key, value in values.items():
        con.execute("INSERT INTO fbs_model_meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)))
    if commit:
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


def current_fixture(con: sqlite3.Connection, game_id: str) -> dict | None:
    row = con.execute("SELECT * FROM fbs_fixture_revisions WHERE game_id = ? "
                      "ORDER BY revision DESC LIMIT 1", (game_id,)).fetchone()
    return dict(row) if row else None


def observe_fixture(con: sqlite3.Connection, rec: dict, now: dt.datetime, source: str) -> dict:
    """Record a fixture revision when the kickoff moves. A changed team identity is never accepted as
    the same fixture: it is reported and the stored revision is left as it was."""
    now = now or dt.datetime.now(dt.timezone.utc)
    kickoff = parse_time(rec["kickoff_utc"]).isoformat()
    home_id, away_id = str(rec.get("home_team_id")), str(rec.get("away_team_id"))
    current = current_fixture(con, rec["game_id"])
    if current is None:
        revision, changed, identity_changed = 1, False, False
    elif (current["home_team_id"], current["away_team_id"]) != (home_id, away_id):
        revision, changed, identity_changed = current["revision"], False, True
    elif parse_time(current["kickoff_utc"]) != parse_time(kickoff):
        revision, changed, identity_changed = current["revision"] + 1, True, False
    else:
        revision, changed, identity_changed = current["revision"], False, False
    if current is None or changed:
        con.execute(
            "INSERT INTO fbs_fixture_revisions(game_id,revision,season,kickoff_utc,home_team,away_team,"
            " home_team_id,away_team_id,neutral_site,observed_utc,source) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (rec["game_id"], revision, int(rec["season"]), kickoff, rec.get("home_team"),
             rec.get("away_team"), home_id, away_id, int(bool(rec.get("neutral_site"))),
             now.isoformat(), source))
    current = current_fixture(con, rec["game_id"])
    return {"revision": revision, "kickoff_utc": current["kickoff_utc"], "changed": changed,
            "identity_changed": identity_changed}


def game_status(con: sqlite3.Connection, game_id: str) -> dict | None:
    row = con.execute("SELECT * FROM fbs_game_status WHERE game_id = ?", (game_id,)).fetchone()
    return dict(row) if row else None


def set_game_status(con: sqlite3.Connection, game_id: str, season: int, revision: int, lifecycle: str,
                    status_name: str | None, observed_utc: str, source: str, grading_state: str,
                    reason: str | None = None, commit: bool = True, pregame: bool | None = None) -> None:
    """Upsert a game's current status. A graded game keeps its grading state; nothing un-grades it.

    An observation made before the current kickoff is a pregame observation, and it snapshots the
    pregame lifecycle that the window classification reads. The flag is derived, not left to callers.
    """
    if pregame is None:
        fixture = current_fixture(con, game_id)
        pregame = fixture is not None and parse_time(observed_utc) < parse_time(fixture["kickoff_utc"])
    pregame_lifecycle = lifecycle if pregame else None
    pregame_observed = observed_utc if pregame else None
    con.execute(
        "INSERT INTO fbs_game_status(game_id,season,revision,lifecycle,status_name,observed_utc,source,"
        " grading_state,reason,pregame_lifecycle,pregame_observed_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(game_id) DO UPDATE SET revision=excluded.revision, lifecycle=excluded.lifecycle,"
        " status_name=excluded.status_name, observed_utc=excluded.observed_utc, source=excluded.source,"
        " grading_state=CASE WHEN fbs_game_status.grading_state='graded' THEN 'graded'"
        "                    ELSE excluded.grading_state END,"
        " reason=excluded.reason,"
        " pregame_lifecycle=CASE WHEN ? THEN excluded.pregame_lifecycle ELSE fbs_game_status.pregame_lifecycle END,"
        " pregame_observed_utc=CASE WHEN ? THEN excluded.pregame_observed_utc"
        "                           ELSE fbs_game_status.pregame_observed_utc END",
        (game_id, season, revision, lifecycle, status_name, observed_utc, source, grading_state, reason,
         pregame_lifecycle, pregame_observed, 1 if pregame else 0, 1 if pregame else 0))
    if commit:
        con.commit()


def set_grading_state(con: sqlite3.Connection, game_id: str, grading_state: str, reason: str,
                      observed_utc: str, source: str, commit: bool = True) -> None:
    """Void or quarantine a game. The stored forecast and any lock are not changed."""
    con.execute("UPDATE fbs_game_status SET grading_state=?, reason=?, observed_utc=?, source=? "
                "WHERE game_id=? AND grading_state != 'graded'",
                (grading_state, reason, observed_utc, source, game_id))
    if commit:
        con.commit()


def record_unresolved(con: sqlite3.Connection, game_id: str, season: int, kickoff_utc: str,
                      reason: str, now: dt.datetime, commit: bool = True, lock_risk: bool = False) -> dict:
    """Keep a game that could not be classified in a visible queue, with a bounded retry schedule.

    A pregame failure (lock_risk) is visible at once: the game could lock and cannot be verified. Any
    unresolved game is alerted 24 hours after kickoff. Alerts only ever escalate. Nothing here
    classifies the game as completed, cancelled or missed.
    """
    from fbs_lifecycle import alert_due, next_attempt
    row = con.execute("SELECT * FROM fbs_unresolved WHERE game_id = ?", (game_id,)).fetchone()
    attempts = (row["attempts"] + 1) if row else 1
    first_seen = row["first_seen_utc"] if row else now.isoformat()
    kickoff = parse_time(kickoff_utc)
    rank = {"none": 0, "lock_risk": 1, "alerted": 2}
    if alert_due(kickoff, now):
        candidate = "alerted"
    elif lock_risk and now < kickoff:
        candidate = "lock_risk"
    else:
        candidate = "none"
    previous = row["alert_state"] if row else "none"
    alert = candidate if rank[candidate] > rank[previous] else previous
    due = next_attempt(attempts, now)
    con.execute(
        "INSERT INTO fbs_unresolved(game_id,season,kickoff_utc,reason,first_seen_utc,last_attempt_utc,"
        " attempts,next_attempt_utc,alert_state,resolved_utc) VALUES(?,?,?,?,?,?,?,?,?,NULL)"
        " ON CONFLICT(game_id) DO UPDATE SET reason=excluded.reason, last_attempt_utc=excluded.last_attempt_utc,"
        " attempts=excluded.attempts, next_attempt_utc=excluded.next_attempt_utc,"
        " alert_state=excluded.alert_state, resolved_utc=NULL",
        (game_id, season, kickoff_utc, reason, first_seen, now.isoformat(), attempts, due.isoformat(), alert))
    if commit:
        con.commit()
    return {"game_id": game_id, "reason": reason, "attempts": attempts, "alert_state": alert,
            "next_attempt_utc": due.isoformat()}


def resolve_unresolved(con: sqlite3.Connection, game_id: str, now: dt.datetime, commit: bool = True) -> None:
    con.execute("UPDATE fbs_unresolved SET resolved_utc=? WHERE game_id=? AND resolved_utc IS NULL",
                (now.isoformat(), game_id))
    if commit:
        con.commit()


def unresolved_queue(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM fbs_unresolved WHERE resolved_utc IS NULL ORDER BY kickoff_utc").fetchall()]


def record_run(con: sqlite3.Connection, subsystem: str, status: str, detail: dict,
               now: dt.datetime, commit: bool = True) -> None:
    """A truthful per-subsystem report: what ran, what it concluded, and why it stopped."""
    con.execute("INSERT INTO fbs_run_reports(subsystem,status,started_utc,detail) VALUES(?,?,?,?)",
                (subsystem, status, now.isoformat(), json.dumps(detail, sort_keys=True, default=str)))
    if commit:
        con.commit()


def last_runs(con: sqlite3.Connection) -> dict:
    out = {}
    for row in con.execute("SELECT subsystem, status, started_utc, detail FROM fbs_run_reports ORDER BY id"):
        out[row["subsystem"]] = {"status": row["status"], "started_utc": row["started_utc"],
                                 "detail": json.loads(row["detail"] or "{}")}
    return out


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
    outcomes = {}
    if _table_exists(con, "fbs_window_outcomes"):
        outcomes = {(r[0], r[1]): r[2] for r in con.execute(
            "SELECT game_id, model, outcome FROM fbs_window_outcomes WHERE season=?", (season,))}
    missed_games = {game_id for game_id, _ in missed}
    for (game_id, model), outcome in outcomes.items():
        if outcome == "missed_t90_window":
            missed.add((game_id, model))

    statuses = {}
    if _table_exists(con, "fbs_game_status"):
        statuses = {r["game_id"]: dict(r) for r in con.execute(
            "SELECT * FROM fbs_game_status WHERE season=?", (season,)).fetchall()}
    void_games = {g for g, st in statuses.items() if st["grading_state"] == "void"}
    quarantined = {g for g, st in statuses.items() if st["grading_state"] == "quarantined"}
    unresolved = unresolved_queue(con) if _table_exists(con, "fbs_unresolved") else []

    records = {}
    for model in MODEL_IDS:
        model_rows = [r for r in rows if r["model"] == model]
        official = [r for r in model_rows if _protocol(r) == LOCK_PROTOCOL and not r["late"]
                    and r["game_id"] not in void_games and r["game_id"] not in quarantined]
        windows = {name: sum(1 for (g, m), o in outcomes.items() if m == model and o == name)
                   for name in ("missed_t90_window", "blocked_unverified_at_cutoff", "window_not_eligible")}
        windows["locked"] = len(official)
        records[model] = {**_score(official), "forecasts": len(official),
                          "legacy": sum(1 for r in model_rows if _protocol(r) == LEGACY_PROTOCOL),
                          "late": sum(1 for r in model_rows if r["late"]),
                          "missed": sum(1 for _, m in missed if m == model),
                          "void": sum(1 for r in model_rows if r["game_id"] in void_games and _protocol(r) == LOCK_PROTOCOL),
                          "quarantined": sum(1 for r in model_rows if r["game_id"] in quarantined),
                          "unresolved": sum(1 for u in unresolved if u["season"] == season and u["game_id"] in {r["game_id"] for r in model_rows}),
                          "windows": windows}

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
            "kickoff_revision": row["kickoff_revision"],
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
    for game_id, game in games.items():
        status = statuses.get(game_id, {})
        game["lifecycle"] = status.get("lifecycle")
        game["grading_state"] = status.get("grading_state")
        game["status_reason"] = status.get("reason")
        game["pregame_lifecycle"] = status.get("pregame_lifecycle")
        game["kickoff_revision"] = status.get("revision")
    ratings = [dict(r) for r in con.execute(
        "SELECT * FROM fbs_ratings WHERE season=? ORDER BY rating DESC", (season,)).fetchall()]
    meta = {r["key"]: json.loads(r["value"]) for r in con.execute(
        "SELECT key,value FROM fbs_model_meta").fetchall()}
    meta["unresolved"] = unresolved
    meta["runs"] = last_runs(con) if _table_exists(con, "fbs_run_reports") else {}
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Migrate an FBS model database, with a backup and evidence.")
    parser.add_argument("--migrate", metavar="DB", required=True)
    parser.add_argument("--backup-dir", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(migrate(args.migrate, args.backup_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
