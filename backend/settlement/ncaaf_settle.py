"""ncaaf_settle.py — NCAAF settlement: the durable CFBD log first, ESPN second.

Step 5 of the 2026-10-02 repair order. Before this module NCAAF fell through to
the generic site-boxscore path, which graded from one live ESPN request and left
every prop whose athlete did not appear as an undiagnosed `pending`.

Three behaviors, all measured before being trusted:

1. DB-first. `player_game_logs` already stores CFBD's published per-athlete line
   for completed games under the game's ESPN event id, keyed by the athlete's
   ESPN id (`source_player_key`). When the prop's athlete has such a row and the
   row carries every stat the market needs, the grade comes from the stored
   line and costs no request.

2. Bounded ESPN fallback. Only the props the CFBD row could not answer fall
   through to the site boxscore — at most one request per game, the same bound
   the generic path had. The fallback keeps the generic extractor's DNP rule
   unchanged: a zero is graded only when another boxscore category proves the
   same stable athlete appeared; an athlete absent from the whole boxscore stays
   pending because a possible DNP must not become a losing over or a winning
   under on our guess.

3. Durable attempt reasons. The generic path's pending/unmappable/error counts
   were aggregate console lines that the journal rotation destroyed (the
   diagnosis could not reconstruct eight props' outcomes for exactly this
   reason). Every NCAAF prop attempt lands in `settlement_attempts` with its
   stage, terminal category, and reason; a repeat attempt with an unchanged
   state writes nothing, so the table grows only when a prop's state changes.

Markets the CFBD line cannot answer stay on the fallback by construction. The
CFBD ingest publishes no kicking group, no completions half of C/ATT, no carry
count, and no kick/punt return or defensive touchdown component — so
pass_completions, rush_attempts, total_touchdowns and the three kicking markets
never grade from `player_game_logs` here (measured: ingest_cfbd_logs._STAT_MAP
carries att, pass_yds, pass_td, intc, rush_yds, rush_td, rec, rec_yds, rec_td
and the def_* names only).
"""
import datetime as dt
import json
import sqlite3

from settlement.market_mapping import (
    MARKET_ALIASES,
    normalize_market,
    resolve_market,
    resolve_compound_market,
)
from settlement.boxscore_extract import (
    _find_player_stat,
    _find_player_compound_stat,
    _player_appeared,
)
from settlement.grading import _grade_actual

# Canonical NCAAF market -> the CFBD stat keys whose sum is the published value.
_CFBD_MARKETS = {
    "passing_yards": ("pass_yds",),
    "passing_touchdowns": ("pass_td",),
    "interceptions_thrown": ("intc",),
    "pass_attempts": ("att",),
    "rushing_yards": ("rush_yds",),
    "rushing_touchdowns": ("rush_td",),
    "receiving_yards": ("rec_yds",),
    "receptions": ("rec",),
    "passing_rushing_yards": ("pass_yds", "rush_yds"),
    "rushing_receiving_yards": ("rush_yds", "rec_yds"),
    "rushing_receiving_touchdowns": ("rush_td", "rec_td"),
}


def _canonical(league: str, raw_market: str) -> str:
    canonical = normalize_market(raw_market)
    return MARKET_ALIASES.get(canonical, canonical)


def _ensure_attempt_table(con: sqlite3.Connection) -> bool:
    con.execute("""CREATE TABLE IF NOT EXISTS settlement_attempts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prop_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        attempted_at TEXT NOT NULL,
        stage TEXT NOT NULL,
        terminal TEXT NOT NULL,
        reason TEXT,
        actual_value REAL,
        hit INTEGER)""")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_settlement_attempts_prop "
        "ON settlement_attempts(prop_id, id)")
    return True


def _record_attempts(con: sqlite3.Connection, game_id: int, attempts: list) -> None:
    """Persist one attempt row per prop whose (stage, terminal, reason) changed."""
    _ensure_attempt_table(con)
    known = {}
    prop_ids = tuple(a["prop_id"] for a in attempts)
    placeholders = ",".join("?" * len(prop_ids))
    for row in con.execute(
            "SELECT prop_id, stage, terminal, reason FROM settlement_attempts "
            f"WHERE prop_id IN ({placeholders}) ORDER BY id DESC", prop_ids):
        if row["prop_id"] not in known:
            known[row["prop_id"]] = (row["stage"], row["terminal"], row["reason"])
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    fresh = [a for a in attempts
             if known.get(a["prop_id"]) != (a["stage"], a["terminal"], a["reason"])]
    if fresh:
        con.executemany(
            "INSERT INTO settlement_attempts(prop_id, game_id, attempted_at, "
            "stage, terminal, reason, actual_value, hit) VALUES (?,?,?,?,?,?,?,?)",
            [(a["prop_id"], game_id, now, a["stage"], a["terminal"],
              a["reason"], a.get("actual_value"), a.get("hit")) for a in fresh])
        con.commit()


def _cfbd_rows(con: sqlite3.Connection, espn_event_id: str) -> dict:
    """{espn athlete id: stats dict} for this event. Team rows (negative ids)
    are skipped: a prop never prices the team entity, and its stats line would
    otherwise shadow a missing athlete."""
    has_table = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='player_game_logs'").fetchone()
    if not has_table or not espn_event_id:
        return {}
    rows = {}
    for row in con.execute(
            "SELECT source_player_key, stats FROM player_game_logs "
            "WHERE league='ncaaf' AND game_id=? AND CAST(source_player_key AS INTEGER)>0",
            (str(espn_event_id),)):
        try:
            rows[str(row["source_player_key"])] = json.loads(row["stats"] or "{}")
        except (TypeError, ValueError):
            continue
    return rows


def _cfbd_value(stats: dict, keys) -> "float | None":
    """The published value, or None when any needed key is absent.

    A present key grades even when the value is 0: CFBD publishes zeros inside
    a group it covers. An absent key is not evidence of zero — the group may
    simply not have been published for this athlete — so that case falls to the
    ESPN fallback instead of inventing a number from silence.
    """
    total = 0.0
    for key in keys:
        value = stats.get(key)
        if value is None:
            return None
        total += value
    return total


def _settle_ncaaf_props(con: sqlite3.Connection, game, props: list,
                        boxscore_loader) -> dict:
    """Grade one NCAAF game's unsettled props: CFBD line first, ESPN second.

    One attempt row per prop per pass: stage and terminal describe where the
    prop ended, and the reason is the trail of what each stage did with it.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    attempts, unresolved, settled = {}, [], 0

    cfbd = _cfbd_rows(con, game["espn_event_id"])
    for prop in props:
        canonical = _canonical("ncaaf", prop["market"])
        keys = _CFBD_MARKETS.get(canonical)
        row = cfbd.get(str(prop["espn_id"] or ""))
        if keys and row is not None:
            actual = _cfbd_value(row, keys)
            if actual is not None:
                if _grade_actual(con, prop, actual, now):
                    settled += 1
                    attempts[prop["id"]] = {
                        "prop_id": prop["id"], "stage": "cfbd",
                        "terminal": "settled", "reason": "cfbd_line",
                        "actual_value": actual, "hit": None}
                else:
                    attempts[prop["id"]] = {
                        "prop_id": prop["id"], "stage": "cfbd",
                        "terminal": "unmappable", "reason": "unhandled_side",
                        "actual_value": actual, "hit": None}
                    unresolved.append(prop)
            else:
                attempts[prop["id"]] = {
                    "prop_id": prop["id"], "stage": "cfbd",
                    "terminal": "pending", "reason": "cfbd_row_missing_stat"}
                unresolved.append(prop)
        else:
            reasons = []
            if not keys:
                reasons.append("market_not_published_by_cfbd")
            if row is None:
                reasons.append("no_cfbd_row")
            attempts[prop["id"]] = {
                "prop_id": prop["id"], "stage": "cfbd", "terminal": "pending",
                "reason": "+".join(reasons)}
            unresolved.append(prop)
    con.commit()

    if not unresolved:
        _record_attempts(con, game["id"], list(attempts.values()))
        return {"settled": settled, "void": 0, "unmappable": 0,
                "pending": 0, "errors": 0}

    def _fail(terminal, message):
        for prop in unresolved:
            prior = attempts.get(prop["id"], {})
            trail = "+".join(x for x in (prior.get("reason"), message) if x)
            attempts[prop["id"]] = {
                "prop_id": prop["id"], "stage": "espn_fallback",
                "terminal": terminal, "reason": trail}
        _record_attempts(con, game["id"], list(attempts.values()))

    # ── Bounded ESPN fallback: one boxscore request for what CFBD lacked. ──
    try:
        box = boxscore_loader()
    except Exception as e:
        _fail("error", f"boxscore_pull_failed: {e}")
        return {"settled": settled, "void": 0, "unmappable": 0,
                "pending": _unsettled_count(con, game["id"]), "errors": 1,
                "error_msg": f"game {game['id']}: boxscore pull failed: {e}"}
    if not box:
        _fail("error", "empty_boxscore_returned")
        return {"settled": settled, "void": 0, "unmappable": 0,
                "pending": _unsettled_count(con, game["id"]), "errors": 1,
                "error_msg": f"game {game['id']}: empty boxscore returned"}

    settled_fb = unmappable = pending = 0
    for prop in unresolved:
        prior = attempts.get(prop["id"], {})
        mapping = resolve_market("ncaaf", prop["market"])
        if mapping is None:
            unmappable += 1
            attempts[prop["id"]] = {
                "prop_id": prop["id"], "stage": "espn_fallback",
                "terminal": "unmappable", "reason": _trail(prior, "no_market_mapping")}
            continue
        category, stat_key = mapping
        if category is None:
            components = resolve_compound_market("ncaaf", prop["market"])
            if not components:
                unmappable += 1
                attempts[prop["id"]] = {
                    "prop_id": prop["id"], "stage": "espn_fallback",
                    "terminal": "unmappable",
                    "reason": _trail(prior, "compound_without_components")}
                continue
            actual = _find_player_compound_stat(
                box, prop["player_name"], prop["player_team"],
                [c[0] for c in components], [c[1] for c in components],
                espn_id=prop["espn_id"], missing_as_zero=True)
        else:
            actual = _find_player_stat(
                box, prop["player_name"], prop["player_team"],
                category, stat_key, espn_id=prop["espn_id"])

        # The DNP rule: zero only when another boxscore category proves the
        # same stable athlete appeared; absent from the whole boxscore the
        # prop stays pending rather than guessing a participation.
        if (actual is None and _player_appeared(
                box, prop["player_name"], prop["player_team"],
                espn_id=prop["espn_id"])):
            actual = 0.0

        if actual is None:
            pending += 1
            attempts[prop["id"]] = {
                "prop_id": prop["id"], "stage": "espn_fallback",
                "terminal": "pending",
                "reason": _trail(prior, "athlete_absent_from_boxscore")}
            continue

        if _grade_actual(con, prop, actual, now):
            settled_fb += 1
            attempts[prop["id"]] = {
                "prop_id": prop["id"], "stage": "espn_fallback",
                "terminal": "settled", "reason": _trail(prior, "espn_boxscore"),
                "actual_value": actual, "hit": None}
        else:
            unmappable += 1
            attempts[prop["id"]] = {
                "prop_id": prop["id"], "stage": "espn_fallback",
                "terminal": "unmappable", "reason": _trail(prior, "unhandled_side")}
    con.commit()
    _record_attempts(con, game["id"], list(attempts.values()))
    return {"settled": settled + settled_fb, "void": 0,
            "unmappable": unmappable, "pending": pending, "errors": 0}


def _trail(prior: dict, reason: str) -> str:
    prior_reason = prior.get("reason")
    return f"{prior_reason}+{reason}" if prior_reason else reason


def _unsettled_count(con: sqlite3.Connection, game_id: int) -> int:
    return int(con.execute("""
        SELECT COUNT(*) FROM props p
        LEFT JOIN prop_results pr ON pr.prop_id=p.id
        WHERE p.game_id=? AND pr.prop_id IS NULL
    """, (game_id,)).fetchone()[0])
