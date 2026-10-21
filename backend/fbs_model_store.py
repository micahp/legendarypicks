"""Storage for the NCAAF projection system: one projection per game and model, on one workflow.

  1. Projections are computed before kickoff and stored in fbs_projections. Each run replaces the latest one.
  2. Each model's projection is frozen at the lock cutoff, kickoff - LOCK_LEAD (T-90). The frozen row is copied
     from the stored projection, which was computed before the cutoff. Nothing is computed after the cutoff.
  3. Frozen rows are immutable (triggers). A frozen row's result is written once, from a verified final.
  4. Accuracy and history come from frozen, graded rows only.

Operational state (lifecycle, source failures, missed cutoffs, unresolved games) lives in its own tables and is
reported in diagnostics, never as a label on a projection. Rows written before the lock protocol are kept as data.
They are not projections, and they are excluded from the record. The module is deliberately separate from the
picks databases: nothing here can move a pick, a price or a frozen projection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import uuid

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
    kickoff_revision INTEGER NOT NULL DEFAULT 1,
    projected_at_utc TEXT,
    cutoff_utc TEXT,
    result INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    graded_at_utc TEXT,
    PRIMARY KEY (game_id, model)
);
CREATE INDEX IF NOT EXISTS fbs_forecasts_season ON fbs_forecasts(season, kickoff_utc);
CREATE TABLE IF NOT EXISTS fbs_projections (
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
    projected_at_utc TEXT NOT NULL,
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

# Created by initialize_new_db() and migrate() only. Normal opens never create or alter them.
TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS fbs_forecast_lock_immutable
BEFORE UPDATE OF season, home_team, away_team, home_team_id, away_team_id, p_home, fair_home, fair_away,
    kickoff_utc, locked_at_utc, projected_at_utc, cutoff_utc, late, lock_protocol, model_version,
    kickoff_revision ON fbs_forecasts
BEGIN SELECT RAISE(ABORT, 'FBS frozen projections are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_forecast_result_once
BEFORE UPDATE OF result ON fbs_forecasts
WHEN OLD.result IS NOT NULL
BEGIN SELECT RAISE(ABORT, 'FBS results are written once'); END;
CREATE TRIGGER IF NOT EXISTS fbs_forecast_no_delete
BEFORE DELETE ON fbs_forecasts
BEGIN SELECT RAISE(ABORT, 'FBS frozen projections are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_lock_event_immutable
BEFORE UPDATE ON fbs_lock_events
BEGIN SELECT RAISE(ABORT, 'FBS lock events are immutable'); END;
CREATE TRIGGER IF NOT EXISTS fbs_window_outcome_immutable
BEFORE UPDATE ON fbs_window_outcomes
BEGIN SELECT RAISE(ABORT, 'FBS window outcomes are immutable'); END;
""" 

SCHEMA_VERSION = 2
REQUIRED_TABLES = tuple(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", SCHEMA))
REQUIRED_COLUMNS = (
    ("fbs_forecasts", "lock_protocol"), ("fbs_forecasts", "kickoff_revision"),
    ("fbs_forecasts", "projected_at_utc"), ("fbs_forecasts", "cutoff_utc"), ("fbs_projections", "projected_at_utc"),
)
REQUIRED_TRIGGERS = tuple(re.findall(r"CREATE TRIGGER IF NOT EXISTS (\w+)", TRIGGERS))


class SchemaError(RuntimeError):
    """The database is not at SCHEMA_VERSION. `code` is migration_required or not_initialized, and the
    file has not been changed."""

    def __init__(self, code: str, message: str):
        super().__init__("%s: %s" % (code, message))
        self.code = code


def user_tables(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    """Column names of a table, or none when the table is absent. Reads only."""
    return {r[1] for r in con.execute("PRAGMA table_info(%s)" % table)}


def schema_state(con: sqlite3.Connection) -> str:
    """current | empty | legacy. Reads only."""
    tables = user_tables(con)
    if not tables:
        return "empty"
    version = con.execute("PRAGMA user_version").fetchone()[0]
    triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    columns_ok = all(column in table_columns(con, table) for table, column in REQUIRED_COLUMNS)
    if version == SCHEMA_VERSION and set(REQUIRED_TABLES) <= tables and set(REQUIRED_TRIGGERS) <= triggers \
            and columns_ok:
        return "current"
    return "legacy"


def _statements(script: str):
    """Each complete statement of a schema script, so it can run inside one explicit transaction."""
    buf = ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                yield buf.strip()
            buf = ""
    if buf.strip():
        raise ValueError("incomplete statement in schema script: %r" % buf[:80])


def open_db(path: str = DEFAULT_DB, readonly: bool = False) -> sqlite3.Connection:
    """Open an existing database. A writable open verifies the schema and never changes it: a database that
    is not at SCHEMA_VERSION raises SchemaError(migration_required) and its file is left as it was."""
    if readonly:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    else:
        if not os.path.exists(path):
            raise SchemaError("not_initialized", "%s does not exist; create a scratch database with initialize_new_db()" % path)
        con = sqlite3.connect(path)
        state = schema_state(con)
        if state != "current":
            con.close()
            if state == "empty":
                raise SchemaError("not_initialized", "%s has no tables; create it with initialize_new_db()" % path)
            raise SchemaError("migration_required", "%s is not at schema version %d; run the explicit migrate() "
                              "command with a backup first" % (path, SCHEMA_VERSION))
    con.row_factory = sqlite3.Row
    return con


def initialize_new_db(path: str) -> sqlite3.Connection:
    """Create a new database at SCHEMA_VERSION. Refuses any file that already has tables, so an existing
    database is never mistaken for an empty one."""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        probe = sqlite3.connect(path)
        try:
            if user_tables(probe):
                raise SchemaError("migration_required", "%s already has tables; use migrate() or open_db()" % path)
        finally:
            probe.close()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        for statement in list(_statements(SCHEMA)) + list(_statements(TRIGGERS)):
            con.execute(statement)
        con.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        con.execute("COMMIT")
    except Exception:
        if con.in_transaction:
            con.execute("ROLLBACK")
        con.close()
        raise
    con.row_factory = sqlite3.Row
    return con


def begin(con: sqlite3.Connection) -> None:
    """Open one write transaction now, so that a step's writes commit or roll back together."""
    if not con.in_transaction:
        con.execute("BEGIN IMMEDIATE")


def _digest(path_or_con, table: str, columns: list[str]) -> tuple[int, str]:
    """Row count and digest over the named columns, every row, in a fixed order."""
    own = isinstance(path_or_con, str)
    con = sqlite3.connect("file:%s?mode=ro" % path_or_con, uri=True) if own else path_or_con
    try:
        order = ", ".join(str(i + 1) for i in range(len(columns)))
        digest, count = hashlib.sha256(), 0
        for row in con.execute("SELECT %s FROM %s ORDER BY %s" % (", ".join('"%s"' % c for c in columns), table, order)):
            digest.update(repr(tuple(row)).encode())
            count += 1
        return count, digest.hexdigest()
    finally:
        if own:
            con.close()


def _exclusive_backup(path: str, backup_dir: str) -> str:
    """A new backup file, created exclusively: an existing backup is never overwritten."""
    os.makedirs(backup_dir, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = os.path.join(backup_dir, "%s.pre-migrate-%s-%s" % (os.path.basename(path), stamp, uuid.uuid4().hex[:8]))
    os.close(os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
    source = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    target = sqlite3.connect(backup)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    check = sqlite3.connect("file:%s?mode=ro" % backup, uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("backup failed integrity_check: %s" % backup)
    finally:
        check.close()
    return backup


def _upgrade_statements(con: sqlite3.Connection) -> None:
    """Bring an existing database forward inside the caller's transaction. Order matters: the legacy backfill and the
    new columns must exist before the immutability triggers do, or the backfill itself would be refused."""
    if "fbs_forecasts" in user_tables(con):
        columns = table_columns(con, "fbs_forecasts")
        if "lock_protocol" not in columns:
            con.execute("ALTER TABLE fbs_forecasts ADD COLUMN lock_protocol TEXT")
            con.execute("UPDATE fbs_forecasts SET lock_protocol = ? WHERE lock_protocol IS NULL", (LEGACY_PROTOCOL,))
        if "kickoff_revision" not in columns:
            con.execute("ALTER TABLE fbs_forecasts ADD COLUMN kickoff_revision INTEGER NOT NULL DEFAULT 1")
        for column in ("projected_at_utc", "cutoff_utc"):
            if column not in columns:
                con.execute("ALTER TABLE fbs_forecasts ADD COLUMN %s TEXT" % column)
    # Triggers are recreated, not kept: an IF NOT EXISTS keeps an older definition that may not cover new columns.
    for name in REQUIRED_TRIGGERS:
        con.execute("DROP TRIGGER IF EXISTS %s" % name)
    for statement in list(_statements(SCHEMA)) + list(_statements(TRIGGERS)):
        con.execute(statement)


def migrate(path: str, backup_dir: str) -> dict:
    """The only path that changes an existing database's schema. A backup is written first, to a new file.
    The schema change runs in one transaction, and it commits only if every table that existed before still has
    identical rows over its original columns. A database already at SCHEMA_VERSION is left untouched."""
    if not os.path.exists(path):
        raise SchemaError("not_initialized", "%s does not exist" % path)
    probe = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        state = schema_state(probe)
    finally:
        probe.close()
    if state == "current":
        return {"action": "none", "path": path, "schema_version": SCHEMA_VERSION}
    if state == "empty":
        raise SchemaError("not_initialized", "%s has no tables; use initialize_new_db()" % path)

    backup = _exclusive_backup(path, backup_dir)
    con = sqlite3.connect(path, isolation_level=None)
    try:
        before = {}
        for table in sorted(user_tables(con)):
            columns = [r[1] for r in con.execute("PRAGMA table_info(%s)" % table)]
            before[table] = (columns, _digest(con, table, columns))
        con.execute("BEGIN IMMEDIATE")
        try:
            _upgrade_statements(con)
            after = {}
            for table, (columns, _) in before.items():
                after[table] = _digest(con, table, columns)
            changed = [t for t in before if after[t] != before[t][1]]
            if changed:
                raise RuntimeError("migration would change existing rows in %s; nothing committed. backup: %s"
                                   % (changed, backup))
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("integrity_check failed after migration; nothing committed. backup: %s" % backup)
            if set(REQUIRED_TRIGGERS) - {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}:
                raise RuntimeError("required immutability triggers missing after migration; nothing committed")
            con.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
            con.execute("COMMIT")
        except Exception:
            if con.in_transaction:
                con.execute("ROLLBACK")
            raise
        lock_protocols = dict(con.execute("SELECT lock_protocol, COUNT(*) FROM fbs_forecasts GROUP BY 1").fetchall()) \
            if "fbs_forecasts" in before else {}
    finally:
        con.close()
    return {"action": "migrated", "path": path, "backup": backup, "schema_version": SCHEMA_VERSION,
            "tables": {t: {"rows": before[t][1][0], "digest": before[t][1][1]} for t in before},
            "tables_added": sorted(set(REQUIRED_TABLES) - set(before)),
            "lock_protocols": lock_protocols}


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


def cutoff_for(kickoff: dt.datetime) -> dt.datetime:
    """The lock cutoff for a kickoff: T-90 by default. Projections are stored only before it, and freezing starts at it."""
    return kickoff - LOCK_LEAD


def upsert_projections(con: sqlite3.Connection, rows: list[dict],
                       now: dt.datetime | None = None, commit: bool = True) -> int:
    """Store the latest pregame projection for each game and model.

    A projection is written only before the game's lock cutoff, so every projection a freeze can copy was computed
    before the cutoff. Each run replaces the previous projection. Frozen rows are never touched here.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    written = 0
    for row in rows:
        kickoff = parse_time(row["kickoff_utc"])
        if now >= cutoff_for(kickoff):
            continue
        con.execute(
            "INSERT INTO fbs_projections(game_id,model,season,kickoff_utc,home_team,away_team,"
            " home_team_id,away_team_id,model_version,p_home,fair_home,fair_away,fitted_through,"
            " projected_at_utc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(game_id,model) DO UPDATE SET kickoff_utc=excluded.kickoff_utc,"
            " home_team=excluded.home_team, away_team=excluded.away_team,"
            " home_team_id=excluded.home_team_id, away_team_id=excluded.away_team_id,"
            " model_version=excluded.model_version, p_home=excluded.p_home,"
            " fair_home=excluded.fair_home, fair_away=excluded.fair_away,"
            " fitted_through=excluded.fitted_through, projected_at_utc=excluded.projected_at_utc",
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


def freeze_projections(con: sqlite3.Connection, now: dt.datetime | None = None, commit: bool = True) -> dict:
    """Freeze each model's latest projection at the lock cutoff.

    A freeze copies the stored projection. It never computes a new one, so the frozen probability was computed before
    the cutoff. A projection is frozen once, and the frozen row is immutable. Each refusal is counted, so no skipped
    game is silent. Nothing is frozen before the cutoff, after kickoff, or for a game whose pregame status or
    fixture revision cannot be verified at this run.
    """
    now = now or dt.datetime.now(dt.timezone.utc)
    report = {"frozen": 0, "already_frozen": 0, "not_due": 0, "after_kickoff": 0,
              "blocked_status": 0, "blocked_revision": 0, "blocked_projection_time": 0}
    for row in con.execute("SELECT * FROM fbs_projections").fetchall():
        already = con.execute("SELECT 1 FROM fbs_forecasts WHERE game_id=? AND model=? AND lock_protocol=?",
                              (row["game_id"], row["model"], LOCK_PROTOCOL)).fetchone()
        if already:
            report["already_frozen"] += 1
            continue
        fixture = current_fixture(con, row["game_id"])
        if fixture is None:
            report["blocked_revision"] += 1
            continue
        kickoff = parse_time(fixture["kickoff_utc"])
        cutoff = cutoff_for(kickoff)
        if parse_time(row["kickoff_utc"]) != kickoff:
            report["blocked_revision"] += 1          # the projection was computed for another kickoff
            continue
        if (fixture["home_team_id"], fixture["away_team_id"]) != (row["home_team_id"], row["away_team_id"]):
            report["blocked_status"] += 1            # the opponent changed: never the same fixture
            continue
        if now >= kickoff:
            report["after_kickoff"] += 1
            continue
        if now < cutoff:
            report["not_due"] += 1
            continue
        status = game_status(con, row["game_id"])
        if status is None or not is_lockable(status["lifecycle"], kickoff, now):
            report["blocked_status"] += 1            # not a verified, unstarted, scheduled game
            continue
        if parse_time(row["projected_at_utc"]) >= cutoff:
            report["blocked_projection_time"] += 1   # defensive: a projection must predate its cutoff
            continue
        cursor = con.execute(
            "INSERT OR IGNORE INTO fbs_forecasts"
            "(game_id,model,season,kickoff_utc,home_team,away_team,home_team_id,away_team_id,"
            " model_version,p_home,fair_home,fair_away,fitted_through,created_at_utc,"
            " locked_at_utc,late,lock_protocol,kickoff_revision,projected_at_utc,cutoff_utc)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)",
            (row["game_id"], row["model"], row["season"], fixture["kickoff_utc"],
             row["home_team"], row["away_team"], row["home_team_id"], row["away_team_id"],
             row["model_version"], row["p_home"], row["fair_home"], row["fair_away"],
             row["fitted_through"], now.isoformat(), now.isoformat(), LOCK_PROTOCOL,
             fixture["revision"], row["projected_at_utc"], cutoff.isoformat()))
        report["frozen" if cursor.rowcount else "already_frozen"] += 1
    if commit:
        con.commit()
    return report


def window_outcome(status: dict | None) -> tuple[str, str | None, str]:
    """Classify a projected game whose cutoff passed without a frozen projection. Internal to diagnostics.

    missed_t90_window: the game was verified scheduled before its kickoff, but no projection was frozen.
    blocked_unverified_at_cutoff: no verified pregame status existed, so there was nothing to freeze.
    window_not_eligible: postponed, delayed, suspended, cancelled or another non-window status before kickoff.
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
        return "missed_t90_window", pregame, "scheduled_and_unfrozen"
    return "blocked_unverified_at_cutoff", pregame, "pregame_status_not_scheduled"


def record_missed_windows(con: sqlite3.Connection, now: dt.datetime | None = None,
                          commit: bool = True) -> dict:
    """Classify every projected game whose kickoff has passed without a frozen projection. Recorded once."""
    now = now or dt.datetime.now(dt.timezone.utc)
    frozen = {(row[0], row[1]) for row in con.execute(
        "SELECT game_id, model FROM fbs_forecasts WHERE lock_protocol = ?", (LOCK_PROTOCOL,))}
    recorded = {(row[0], row[1]) for row in con.execute("SELECT game_id, model FROM fbs_window_outcomes")}
    counts = {"missed_t90_window": 0, "blocked_unverified_at_cutoff": 0, "window_not_eligible": 0}
    for row in con.execute("SELECT game_id, model, season, kickoff_utc FROM fbs_projections").fetchall():
        key = (row["game_id"], row["model"])
        if key in frozen or key in recorded:
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
    # A game that reached its cutoff with a verified pregame status but was never projected (first seen inside
    # the window, or no run before the cutoff) is a missed cutoff for the whole game. Recorded under model "*".
    projected = {row[0] for row in con.execute("SELECT DISTINCT game_id FROM fbs_projections")}
    for status in con.execute("SELECT * FROM fbs_game_status WHERE pregame_lifecycle IS NOT NULL").fetchall():
        game_id = status["game_id"]
        if game_id in projected or (game_id, "*") in recorded:
            continue
        fixture = current_fixture(con, game_id)
        if fixture is None or now < parse_time(fixture["kickoff_utc"]):
            continue
        outcome, lifecycle, reason = window_outcome(dict(status))
        if outcome == "missed_t90_window":
            reason = "no_projection_before_cutoff"
        con.execute(
            "INSERT INTO fbs_window_outcomes(game_id,model,season,kickoff_utc,outcome,lifecycle_at_cutoff,"
            " reason,recorded_at_utc) VALUES(?,?,?,?,?,?,?,?)",
            (game_id, "*", status["season"], fixture["kickoff_utc"], outcome, lifecycle, reason, now.isoformat()))
        counts[outcome] += 1
    if commit:
        con.commit()
    return counts


def grade_forecasts(con: sqlite3.Connection, results: dict[str, dict],
                    now: dt.datetime | None = None, commit: bool = True) -> int:
    """Write the verified final result of each game onto its frozen projections. Never touches a probability.

    A result must carry verified=True, which only a confirmed final produces. Voided and quarantined games are
    never graded, and a result is written once (trigger). Legacy rows (stored before the lock protocol) are
    graded and counted the same way as frozen ones."""
    now = now or dt.datetime.now(dt.timezone.utc)
    graded = 0
    for game_id, result in results.items():
        if result.get("verified") is not True:
            raise ValueError("refusing to grade %s from an unverified result" % game_id)
        home_score, away_score = result.get("home_score"), result.get("away_score")
        if home_score is None or away_score is None:
            continue
        status = game_status(con, game_id)
        if status and status["grading_state"] in ("void", "quarantined"):
            continue
        outcome = 1 if home_score > away_score else 0
        cursor = con.execute(
            "UPDATE fbs_forecasts SET result=?, home_score=?, away_score=?, graded_at_utc=? "
            "WHERE game_id=? AND result IS NULL AND lock_protocol IN (?, ?) AND kickoff_utc < ?",
            (outcome, home_score, away_score, now.isoformat(), game_id, LOCK_PROTOCOL, LEGACY_PROTOCOL,
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
    """Locked or legacy, ungraded games whose kickoff has passed, and which are due for a grading attempt.

    A legacy row's kickoff is a date-only midnight stamp, so it is due a day after that stamp, when the
    game can have finished; the real kickoff is somewhere inside that day. Voided and quarantined games
    are excluded. An unresolved game is retried only when its backoff has elapsed.
    """
    rows = con.execute(
        "SELECT DISTINCT f.game_id, f.kickoff_utc, f.lock_protocol FROM fbs_forecasts f "
        "WHERE f.result IS NULL AND f.lock_protocol IN (?, ?) "
        "AND NOT EXISTS (SELECT 1 FROM fbs_game_status s WHERE s.game_id = f.game_id "
        "                AND s.grading_state IN ('void', 'quarantined', 'graded'))",
        (LOCK_PROTOCOL, LEGACY_PROTOCOL)).fetchall()
    due_at = {row[0]: parse_time(row[1]) for row in con.execute(
        "SELECT game_id, next_attempt_utc FROM fbs_unresolved WHERE resolved_utc IS NULL")}
    wait = {LOCK_PROTOCOL: dt.timedelta(0), LEGACY_PROTOCOL: dt.timedelta(days=1)}
    return [(row[0], row[1]) for row in rows
            if parse_time(row[1]) + wait[row[2]] < now and due_at.get(row[0], now) <= now]


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


def _projection_view(row: sqlite3.Row, frozen_at: str | None, projected_at: str) -> dict:
    return {"p_home": round(row["p_home"], 4), "p_away": round(1.0 - row["p_home"], 4),
            "fair_home": row["fair_home"], "fair_away": row["fair_away"],
            "model_version": row["model_version"], "fitted_through": row["fitted_through"],
            "projected_at_utc": projected_at, "frozen_at_utc": frozen_at}


def _history(graded: list[sqlite3.Row]) -> list[dict]:
    """Running accuracy and Brier after each graded, frozen projection, in kickoff order."""
    out, correct, brier = [], 0, 0.0
    for count, row in enumerate(graded, 1):
        correct += (row["p_home"] >= 0.5) == (row["result"] == 1)
        brier += (row["p_home"] - row["result"]) ** 2
        out.append({"game_id": row["game_id"], "kickoff_utc": row["kickoff_utc"], "p_home": round(row["p_home"], 4),
                    "home_win": bool(row["result"]), "home_score": row["home_score"],
                    "away_score": row["away_score"], "graded": count,
                    "accuracy": round(correct / count, 4), "brier": round(brier / count, 4)})
    return out


def export_payload(con: sqlite3.Connection, season: int) -> dict:
    """The public payload for one season, on one projection workflow.

    Projection cards get projections, game facts and, once verified, the final result. Records and history come only
    from graded projections, frozen or legacy. Operational state is under diagnostics, which no projection card reads.
    """
    base = {"league": "ncaaf", "default_model": DEFAULT_MODEL,
            "models": [{"id": m, "label": MODEL_LABELS[m], "note": MODEL_NOTES[m]} for m in MODEL_IDS],
            "season": season, "source": "standalone FBS model database"}
    if not set(REQUIRED_TABLES) <= user_tables(con):
        return {**base, "state": "migration_required", "games": [], "records": {}, "ratings": [], "meta": {},
                "diagnostics": {"schema_status": "migration_required"}}

    fixtures = {r["game_id"]: dict(r) for r in con.execute(
        "SELECT f.* FROM fbs_fixture_revisions f JOIN (SELECT game_id, MAX(revision) AS revision "
        "FROM fbs_fixture_revisions GROUP BY game_id) m ON m.game_id = f.game_id AND m.revision = f.revision "
        "WHERE f.season = ?", (season,)).fetchall()}
    projections = {(r["game_id"], r["model"]): r for r in con.execute(
        "SELECT * FROM fbs_projections WHERE season = ?", (season,)).fetchall()}
    frozen_rows = con.execute("SELECT * FROM fbs_forecasts WHERE season = ? AND lock_protocol = ? "
                              "ORDER BY kickoff_utc, model", (season, LOCK_PROTOCOL)).fetchall()
    frozen = {(r["game_id"], r["model"]): r for r in frozen_rows}
    stored_rows = con.execute("SELECT * FROM fbs_forecasts WHERE season = ? ORDER BY kickoff_utc, model",
                              (season,)).fetchall()
    legacy_rows = sum(1 for r in stored_rows if r["lock_protocol"] == LEGACY_PROTOCOL)
    statuses = {r["game_id"]: dict(r) for r in con.execute(
        "SELECT * FROM fbs_game_status WHERE season = ?", (season,)).fetchall()}

    games = []
    for game_id in sorted({g for g, _ in projections} | {g for g, _ in frozen}):
        if statuses.get(game_id, {}).get("grading_state") == "void":
            continue                                   # a voided game is not a projection
        models, result = {}, None
        for model in MODEL_IDS:
            row = frozen.get((game_id, model))
            if row is not None:
                models[model] = _projection_view(row, row["locked_at_utc"], row["projected_at_utc"])
                if row["result"] is not None and result is None:
                    result = {"home_score": row["home_score"], "away_score": row["away_score"],
                              "home_win": bool(row["result"])}
                continue
            row = projections.get((game_id, model))
            if row is not None:
                models[model] = _projection_view(row, None, row["projected_at_utc"])
        if not models:
            continue
        anchor = next(r for r in (frozen.get((game_id, m)) or projections.get((game_id, m)) for m in MODEL_IDS)
                      if r is not None)
        fixture = fixtures.get(game_id) or dict(anchor)
        games.append({
            "game_id": game_id, "season": season, "kickoff_utc": fixture["kickoff_utc"],
            "home_team": fixture["home_team"], "away_team": fixture["away_team"],
            "home_team_id": fixture["home_team_id"], "away_team_id": fixture["away_team_id"],
            "neutral_site": bool(fixture.get("neutral_site")), "result": result, "models": models,
        })
    games.sort(key=lambda g: g["kickoff_utc"])

    records = {}
    for model in MODEL_IDS:
        rows = [r for r in stored_rows if r["model"] == model]
        graded = sorted((r for r in rows if r["result"] is not None), key=lambda r: r["kickoff_utc"])
        records[model] = {**_score(rows), "frozen": len(rows), "history": _history(graded)}

    outcomes = con.execute("SELECT outcome, reason, COUNT(*) FROM fbs_window_outcomes WHERE season = ? "
                           "GROUP BY 1, 2", (season,)).fetchall()
    diagnostics = {
        "games": {g: {"lifecycle": st.get("lifecycle"), "grading_state": st.get("grading_state"),
                      "status_reason": st.get("reason"), "pregame_lifecycle": st.get("pregame_lifecycle"),
                      "revision": st.get("revision")} for g, st in statuses.items()},
        "cutoffs": {"%s|%s" % (row[0], row[1] or ""): row[2] for row in outcomes},
        "unresolved": [u for u in unresolved_queue(con) if u["season"] == season],
        "frozen_rows": len(frozen_rows),
        "legacy_rows": legacy_rows,
        "runs": last_runs(con),
    }
    ratings = [dict(r) for r in con.execute(
        "SELECT * FROM fbs_ratings WHERE season = ? ORDER BY rating DESC", (season,)).fetchall()]
    meta = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM fbs_model_meta").fetchall()}
    return {**base, "records": records, "games": games, "ratings": ratings, "meta": meta,
            "state": "available" if games else "awaiting_first_projection", "diagnostics": diagnostics}



def _before_record(record: str | None, scored: dict | None, side: str) -> str | None:
    """The record going into the game. A finished game's scoreboard record already counts
    that game, so its result is taken back out."""
    if not record or not scored:
        return record or None
    parts = record.split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        return record
    wins, losses = int(parts[0]), int(parts[1])
    mine, theirs = scored[side], scored["away" if side == "home" else "home"]
    if mine > theirs and wins > 0:
        wins -= 1
    elif mine < theirs and losses > 0:
        losses -= 1
    return "%d-%d" % (wins, losses)


def apply_scoreboard_details(payload: dict, live_db: str) -> dict:
    """Add the scoreboard's kickoff and each team's record going into the game.

    Display only. Stored kickoffs are immutable and are left as written; rows stored with a
    date-only (midnight UTC) kickoff show the scoreboard's time when it knows the game. A game
    the scoreboard does not know keeps the stored kickoff and has no record.
    """
    games = payload.get("games", [])
    for game in games:
        game.setdefault("home_record", None)
        game.setdefault("away_record", None)
    if not games or not os.path.exists(live_db):
        return payload
    try:
        con = sqlite3.connect("file:%s?mode=ro" % live_db, uri=True)
        try:
            marks = ",".join("?" * len(games))
            rows = con.execute("SELECT game_id, payload FROM scoreboard_snapshots WHERE league='ncaaf' "
                               "AND game_id IN (%s) ORDER BY fetched_at" % marks,
                               [g["game_id"] for g in games]).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return payload
    details = {str(game_id): json.loads(raw) for game_id, raw in rows}
    for game in games:
        data = details.get(game["game_id"])
        if not data:
            continue
        date = data.get("date")
        if "T00:00:00" in (game.get("kickoff_utc") or "") and date and "T" in date \
                and not date.endswith("T00:00Z"):
            game["kickoff_utc"] = date.replace("Z", ":00+00:00") if date.count(":") == 1 else date
        scored = None
        home, away = (data.get("home") or {}).get("score"), (data.get("away") or {}).get("score")
        if data.get("completed") and home is not None and away is not None:
            scored = {"home": float(home), "away": float(away)}
        game["home_record"] = _before_record((data.get("home") or {}).get("record"), scored, "home")
        game["away_record"] = _before_record((data.get("away") or {}).get("record"), scored, "away")
    games.sort(key=lambda g: g["kickoff_utc"])
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Create or migrate an FBS model database. Opens never migrate.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--init", metavar="DB", help="create a NEW scratch database at the current schema")
    action.add_argument("--migrate", metavar="DB", help="upgrade an existing database, with a backup")
    action.add_argument("--check", metavar="DB", help="report the schema state without changing anything")
    parser.add_argument("--backup-dir")
    args = parser.parse_args(argv)
    if args.init:
        initialize_new_db(args.init).close()
        print(json.dumps({"action": "initialized", "path": args.init, "schema_version": SCHEMA_VERSION}))
        return 0
    if args.migrate:
        if not args.backup_dir:
            parser.error("--migrate needs --backup-dir")
        print(json.dumps(migrate(args.migrate, args.backup_dir), indent=2, sort_keys=True, default=str))
        return 0
    probe = sqlite3.connect("file:%s?mode=ro" % args.check, uri=True)
    try:
        state = schema_state(probe)
    finally:
        probe.close()
    print(json.dumps({"path": args.check, "state": state, "schema_version": SCHEMA_VERSION}))
    return 0 if state == "current" else 5


if __name__ == "__main__":
    raise SystemExit(main())
