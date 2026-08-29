#!/usr/bin/env python3
"""The scoreboard we last read from a publisher, so serving a page costs nothing.

Before this, `/api/{league}/games` called ESPN on every request. A cold `/scores`
load fanned out to 22 upstream requests (11 ESPN leagues x the viewer's today and
tomorrow), and `espn_client`'s Fetcher carries the process-wide per-host budget --
100 requests, then `time.sleep(60)`. That is a batch job's behaviour running
inside the serving process: measured 2026-08-18 on prod, 46 minutes of uptime and
almost no traffic produced **46 sixty-second pauses**, 38 of them inside a seven
second window, because the budget check is unguarded and every caller in flight
sleeps its own minute when the process crosses the ceiling. The board did not
break because ESPN refused us. It broke because we stalled ourselves, and the
cost of a page view scaled with our own traffic.

So publisher traffic is decoupled from user traffic. A timer writes here; the
serving path only reads. Page load becomes SQLite, and the upstream spend becomes
a constant nobody can push up by opening more tabs.

## What is stored, and what is not claimed

One row per game, holding the normalized shape the API already serves, plus:

  `fetched_at`  when the publisher told us this. Returned to the caller as an
                age, because a score with no age is a claim about now that we
                cannot support ([[feedback_stale_data_looks_clean]]).
  `start_time`  so the live poller can find the games that are under way
                without parsing every payload.

`scoreboard_refresh` records that a (league, date) was asked at all, separately
from what came back. "We fetched and the publisher published nothing" and "we
never asked" are different claims, and only the first is the publisher's. A read
of a day we never fetched returns None, and the caller falls through to the live
ladder rather than serving an empty board.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing

from espn_client.scoreboard import _slate_day
from history_refresh_common import BUSY_TIMEOUT_SECONDS

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db")

# A game still not final this long after its published start is not a live game
# any more, it is a row nobody closed out. Polling it forever would make a stuck
# state into a permanent request source.
LIVE_TAIL = dt.timedelta(hours=12)

# How long a (league, date) that published no games at all stays unasked. A day
# with no slate does not sprout one in ten minutes, but a postponement or a late
# addition is real, so this backs off rather than giving up.
EMPTY_BACKOFF = dt.timedelta(hours=3)

# How long a FUTURE slate that has not started stays unasked. Measured
# 2026-08-24: `needs_refresh` answered "N not final" for tomorrow on every
# league carrying a published slate, so the 10-minute schedule run re-fetched
# five leagues' unstarted slates 144 times a day each. The asymmetry is the
# giveaway -- a league publishing NOTHING for tomorrow got the 3h empty
# backoff, while a league publishing a schedule got no backoff at all, so the
# more a publisher told us the more we asked. "Not final" is the right question
# for today, where it means in flight; on a future date it only means "has not
# started yet". A postponement or an added match is real, which is why this
# backs off rather than skipping the day outright, and why any game already
# in flight or final overrides it entirely.
FUTURE_BACKOFF = dt.timedelta(hours=1)

SCHEMA = """
CREATE TABLE IF NOT EXISTS scoreboard_snapshots(
  league     TEXT NOT NULL,
  game_date  TEXT NOT NULL,
  game_id    TEXT NOT NULL,
  payload    TEXT NOT NULL,
  state      TEXT,
  start_time TEXT,
  fetched_at TEXT NOT NULL,
  source     TEXT,
  PRIMARY KEY(league, game_date, game_id)
);
CREATE INDEX IF NOT EXISTS idx_scoreboard_live
  ON scoreboard_snapshots(state, start_time);
CREATE TABLE IF NOT EXISTS scoreboard_refresh(
  league     TEXT NOT NULL,
  game_date  TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  game_count INTEGER NOT NULL,
  source     TEXT,
  PRIMARY KEY(league, game_date)
);
CREATE TABLE IF NOT EXISTS tennis_draw_snapshots(
  league        TEXT PRIMARY KEY,
  tournament_id TEXT NOT NULL,
  event_name    TEXT NOT NULL,
  bracket_url   TEXT,
  payload       TEXT NOT NULL,
  match_count   INTEGER NOT NULL,
  fetched_at    TEXT NOT NULL,
  source        TEXT
);
CREATE TABLE IF NOT EXISTS tennis_ranking_snapshots(
  tour             TEXT NOT NULL,
  captured_at      TEXT NOT NULL,
  espn_athlete_id  TEXT NOT NULL,
  player_id        INTEGER NOT NULL REFERENCES players(id),
  player_name      TEXT NOT NULL,
  rank             INTEGER NOT NULL,
  previous_rank    INTEGER,
  points           INTEGER,
  source           TEXT,
  PRIMARY KEY(tour, captured_at, espn_athlete_id),
  UNIQUE(tour, captured_at, rank)
);
CREATE INDEX IF NOT EXISTS idx_tennis_rankings_latest
  ON tennis_ranking_snapshots(tour, captured_at DESC, rank);
CREATE TABLE IF NOT EXISTS soccer_competition_snapshots(
  league       TEXT PRIMARY KEY,
  season       INTEGER NOT NULL,
  payload      TEXT NOT NULL,
  match_count  INTEGER NOT NULL,
  leader_count INTEGER NOT NULL,
  fetched_at   TEXT NOT NULL,
  source       TEXT
);
"""


def _db_path():
    """Resolved per call, not bound at import.

    The suite points LP_DB_PATH at a throwaway file and `conftest.py` restores
    it between tests, so a path captured at import time is whichever module
    happened to import this one first. It is also how a dev run and a prod run
    of the same ingest stay told apart.
    """
    return os.environ.get("LP_DB_PATH") or DB


def _db():
    # This store writes `scoreboard_snapshots` every minute, so it is one half of the
    # contention that made prod's props ingest 500 with `database is locked`. See the
    # note in `_core._db`: the 5s SQLite default is what gave up.
    con = sqlite3.connect(_db_path(), timeout=BUSY_TIMEOUT_SECONDS)
    con.row_factory = sqlite3.Row
    return con


def init(con=None):
    if con is not None:
        con.executescript(SCHEMA)
        return
    with closing(_db()) as own:
        own.executescript(SCHEMA)
        own.commit()


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(moment):
    return moment.isoformat(timespec="seconds")


def _today_for(league):
    """Today, on the same clock `game_date` is keyed by.

    This used to be `_now().date()`, the UTC date, compared against a
    `game_date` that is the America/New_York slate day for every league except
    tennis. The UTC date rolls over at 20:00 ET, so for the four hours from
    8pm to midnight Eastern -- prime time -- tonight's slate compared as
    STRICTLY LESS THAN today and the store answered "day is over and published
    no games". An empty slate that gained a late addition in that window could
    never pick it up, because the backoff that exists for exactly that case was
    skipped.

    `_slate_day` is the same function that decides `game_date`, so this asks the
    question on one ruler. It is league-aware on purpose: tennis buckets by UTC
    and must keep doing so.
    """
    now = _now()
    return _slate_day(league, _iso(now)) or now.date().isoformat()


def _normalize_start(value):
    """A stored start time must be comparable to `_iso(now)` as a string.

    Publishers hand us `2026-08-18T22:35Z`; `datetime.isoformat` writes
    `2026-08-18T22:35:00+00:00`. Those sort correctly against each other only as
    far as the minute, and the live query is a string range -- so the value is
    normalized once here rather than trusted to compare. A date-only value (the
    DB result path publishes day precision deliberately) has no instant and is
    stored as None, so it can never be mistaken for a game that has started.
    """
    if not value:
        return None
    text = str(value)
    if len(text) <= 10:
        return None
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return _iso(moment.astimezone(dt.timezone.utc))


def save(league, game_date, games, source="espn", con=None):
    """Replace the stored slate for one (league, date). Returns rows written.

    The day is replaced, not merged: a game the publisher has dropped (a
    postponement, a schedule correction) must disappear from our board too, and
    an upsert alone would leave it there forever.
    """
    league = league.lower()
    fetched_at = _iso(_now())
    own = con is None
    con = con or _db()
    try:
        init(con)
        keep = []
        for game in games or []:
            game_id = str(game.get("game_id") or "")
            if not game_id:
                # Without an id there is nothing to key on, and inventing one
                # would make the same game arrive twice on the next refresh.
                continue
            keep.append(game_id)
            con.execute(
                "INSERT INTO scoreboard_snapshots"
                " (league, game_date, game_id, payload, state, start_time, fetched_at, source)"
                " VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(league, game_date, game_id) DO UPDATE SET"
                "   payload=excluded.payload, state=excluded.state,"
                "   start_time=excluded.start_time, fetched_at=excluded.fetched_at,"
                "   source=excluded.source",
                (league, game_date, game_id, json.dumps(game),
                 game.get("state"), _normalize_start(game.get("date")),
                 fetched_at, source),
            )
        if keep:
            marks = ",".join("?" * len(keep))
            con.execute(
                f"DELETE FROM scoreboard_snapshots WHERE league=? AND game_date=?"
                f" AND game_id NOT IN ({marks})",
                [league, game_date] + keep,
            )
        else:
            con.execute(
                "DELETE FROM scoreboard_snapshots WHERE league=? AND game_date=?",
                (league, game_date),
            )
        con.execute(
            "INSERT INTO scoreboard_refresh (league, game_date, fetched_at, game_count, source)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(league, game_date) DO UPDATE SET"
            "   fetched_at=excluded.fetched_at, game_count=excluded.game_count,"
            "   source=excluded.source",
            (league, game_date, fetched_at, len(keep), source),
        )
        if own:
            con.commit()
        return len(keep)
    finally:
        if own:
            con.close()


def read(league, game_date, con=None):
    """The stored slate, or None if this (league, date) was never fetched.

    None is not an empty slate. A caller that cannot tell the difference will
    serve a blank board for a day nobody ever asked about.
    """
    league = league.lower()
    own = con is None
    con = con or _db()
    try:
        init(con)
        refresh = con.execute(
            "SELECT fetched_at, game_count, source FROM scoreboard_refresh"
            " WHERE league=? AND game_date=?",
            (league, game_date),
        ).fetchone()
        if refresh is None:
            return None
        rows = con.execute(
            "SELECT payload, fetched_at FROM scoreboard_snapshots"
            " WHERE league=? AND game_date=? ORDER BY start_time, game_id",
            (league, game_date),
        ).fetchall()
        games = []
        for row in rows:
            try:
                games.append(json.loads(row["payload"]))
            except (ValueError, TypeError):
                continue
        fetched_at = refresh["fetched_at"]
        try:
            moment = dt.datetime.fromisoformat(fetched_at)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=dt.timezone.utc)
            age = int((_now() - moment).total_seconds())
        except (ValueError, TypeError):
            age = None
        return {
            "games": games,
            "fetched_at": fetched_at,
            "age_seconds": age,
            "source": refresh["source"],
        }
    except sqlite3.Error as exc:
        print(f"[scoreboard_store] read failed league={league} date={game_date}: "
              f"{type(exc).__name__}: {exc}")
        return None
    finally:
        if own:
            con.close()


def save_tennis_draws(league, draws, source="espn", con=None):
    """Replace one tour's current major draw after validating it in full.

    Empty and ambiguous publisher responses leave the last good snapshot alone.
    The ingest treats those conditions as errors; this store never turns them
    into an apparently valid empty bracket.
    """
    league = str(league or "").lower()
    if league not in ("atp", "wta"):
        raise ValueError("tennis draw league must be atp or wta")
    draws = list(draws or [])
    if not draws:
        return 0
    if len(draws) != 1:
        raise ValueError(f"expected one current {league} draw, got {len(draws)}")
    draw = draws[0]
    matches = list(draw.get("matches") or [])
    ids = [str(match.get("game_id") or "") for match in matches]
    if (not draw.get("tournament_id") or not draw.get("event_name") or not matches
            or int(draw.get("match_count") or 0) != len(matches)
            or any(not game_id for game_id in ids) or len(set(ids)) != len(ids)
            or any(not match.get("round") for match in matches)):
        raise ValueError(f"invalid {league} draw snapshot")

    own = con is None
    con = con or _db()
    try:
        init(con)
        fetched_at = _iso(_now())
        con.execute(
            "INSERT INTO tennis_draw_snapshots"
            " (league, tournament_id, event_name, bracket_url, payload,"
            "  match_count, fetched_at, source) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(league) DO UPDATE SET"
            " tournament_id=excluded.tournament_id, event_name=excluded.event_name,"
            " bracket_url=excluded.bracket_url, payload=excluded.payload,"
            " match_count=excluded.match_count, fetched_at=excluded.fetched_at,"
            " source=excluded.source",
            (league, str(draw["tournament_id"]), str(draw["event_name"]),
             draw.get("bracket_url"), json.dumps(draw), len(matches),
             fetched_at, source),
        )
        if own:
            con.commit()
        return len(matches)
    finally:
        if own:
            con.close()


def read_tennis_draws(tour=None, con=None):
    """Return persisted draw snapshots for both tours or one requested tour."""
    if tour is not None:
        tour = str(tour).lower()
        if tour not in ("atp", "wta"):
            raise ValueError("tour must be atp or wta")
    own = con is None
    con = con or _db()
    try:
        init(con)
        sql = ("SELECT league, payload, fetched_at, source"
               " FROM tennis_draw_snapshots")
        params = ()
        if tour:
            sql += " WHERE league=?"
            params = (tour,)
        sql += " ORDER BY league"
        rows = con.execute(sql, params).fetchall()
        result = []
        now = _now()
        for row in rows:
            try:
                draw = json.loads(row["payload"])
            except (TypeError, ValueError):
                continue
            try:
                moment = dt.datetime.fromisoformat(row["fetched_at"])
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=dt.timezone.utc)
                age = int((now - moment).total_seconds())
            except (TypeError, ValueError):
                age = None
            draw.update({
                "fetched_at": row["fetched_at"],
                "age_seconds": age,
                "source": row["source"],
            })
            result.append(draw)
        return result
    except sqlite3.Error as exc:
        print(f"[scoreboard_store] read_tennis_draws failed: {type(exc).__name__}: {exc}")
        return []
    finally:
        if own:
            con.close()


def _tennis_name_key(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = value.encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", "", value)).strip()


def save_tennis_ranking_spine(tour, identities, con=None):
    """Atomically refresh the current top-150 identity population by ESPN id."""
    tour = str(tour or "").lower()
    if tour not in ("atp", "wta"):
        raise ValueError("tennis spine tour must be atp or wta")
    identities = list(identities or [])
    ids = [str(row.get("espn_id") or "") for row in identities]
    names = [str(row.get("name") or "").strip() for row in identities]
    name_keys = [_tennis_name_key(name) for name in names]
    if (len(identities) != 150 or any(not value for value in ids + names + name_keys)
            or len(set(ids)) != 150 or len(set(name_keys)) != 150
            or any(not isinstance(row.get("active"), bool) for row in identities)):
        raise ValueError(f"invalid {tour} top-150 identity population")

    own = con is None
    con = con or _db()
    try:
        init(con)
        columns = {row[1] for row in con.execute("PRAGMA table_info(players)").fetchall()}
        required = {"id", "name", "team", "league", "espn_id", "active", "updated_at"}
        if not required <= columns:
            raise ValueError(f"players table cannot hold {tour} ranking spine")
        existing = con.execute(
            "SELECT id,name,espn_id FROM players WHERE league=?", (tour,)
        ).fetchall()
        by_id = {}
        by_name = {}
        for row in existing:
            source_id = str(row["espn_id"] or "")
            if source_id:
                if source_id in by_id:
                    raise ValueError(f"duplicate existing {tour} ESPN id {source_id}")
                by_id[source_id] = row
            by_name.setdefault(_tennis_name_key(row["name"]), []).append(row)
        for source_id, name in zip(ids, names):
            current = by_id.get(source_id)
            conflicts = [
                row for row in by_name.get(_tennis_name_key(name), [])
                if current is None or row["id"] != current["id"]
            ]
            if conflicts:
                raise ValueError(
                    f"{tour} ESPN id {source_id} conflicts with another stored identity by name"
                )

        updated_at = _iso(_now())
        con.execute("UPDATE players SET active=0, updated_at=? WHERE league=?", (updated_at, tour))
        for identity in identities:
            source_id = str(identity["espn_id"])
            current = by_id.get(source_id)
            if current:
                con.execute(
                    "UPDATE players SET name=?,team=NULL,active=?,updated_at=? WHERE id=?",
                    (identity["name"], int(identity["active"]), updated_at, current["id"]),
                )
            else:
                con.execute(
                    "INSERT INTO players(name,team,league,espn_id,active,updated_at)"
                    " VALUES(?,NULL,?,?,?,?)",
                    (identity["name"], tour, source_id, int(identity["active"]), updated_at),
                )
        active = con.execute(
            "SELECT COUNT(*) FROM players WHERE league=? AND active=1", (tour,)
        ).fetchone()[0]
        if active != sum(int(row["active"]) for row in identities):
            raise ValueError(f"{tour} active spine count mismatch after publication")
        if own:
            con.commit()
        return {"published": 150, "inserted": sum(1 for value in ids if value not in by_id)}
    finally:
        if own:
            con.close()


def save_tennis_rankings(tour, rankings, source="espn", con=None):
    """Publish one complete ESPN top-150 snapshot keyed by athlete id.

    ESPN exposes only the current ranking week and caps the response at 150,
    even when a larger limit is requested.  Every capture is therefore kept:
    replacing a row by tour/player would erase the only history we can build.
    Names are display fields resolved from the canonical tennis spine; they
    are never identity keys.
    """
    tour = str(tour or "").lower()
    if tour not in ("atp", "wta"):
        raise ValueError("tennis ranking tour must be atp or wta")
    rankings = list(rankings or [])
    if len(rankings) != 150:
        raise ValueError(f"expected ESPN's complete {tour} top 150, got {len(rankings)}")

    athlete_ids = [str(row.get("espn_athlete_id") or "") for row in rankings]
    ranks = [row.get("rank") for row in rankings]
    if (any(not athlete_id for athlete_id in athlete_ids)
            or len(set(athlete_ids)) != len(athlete_ids)
            or any(not isinstance(rank, int) for rank in ranks)
            or sorted(ranks) != list(range(1, 151))):
        raise ValueError(f"invalid {tour} ranking identity or rank population")

    own = con is None
    con = con or _db()
    try:
        init(con)
        marks = ",".join("?" * len(athlete_ids))
        players = con.execute(
            "SELECT id, name, espn_id FROM players"
            f" WHERE league=? AND espn_id IN ({marks})",
            [tour] + athlete_ids,
        ).fetchall()
        by_espn_id = {str(row["espn_id"]): row for row in players}
        missing = [athlete_id for athlete_id in athlete_ids if athlete_id not in by_espn_id]
        if missing:
            raise ValueError(
                f"{tour} rankings resolve {len(rankings) - len(missing)} of {len(rankings)} "
                f"canonical athletes; refusing partial snapshot"
            )

        captured_at = _iso(_now())
        for row in rankings:
            athlete_id = str(row["espn_athlete_id"])
            player = by_espn_id[athlete_id]
            con.execute(
                "INSERT INTO tennis_ranking_snapshots"
                " (tour, captured_at, espn_athlete_id, player_id, player_name,"
                "  rank, previous_rank, points, source) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(tour, captured_at, espn_athlete_id) DO UPDATE SET"
                " player_id=excluded.player_id, player_name=excluded.player_name,"
                " rank=excluded.rank, previous_rank=excluded.previous_rank,"
                " points=excluded.points, source=excluded.source",
                (tour, captured_at, athlete_id, player["id"], player["name"],
                 row["rank"], row.get("previous_rank"), row.get("points"), source),
            )
        if own:
            con.commit()
        return len(rankings)
    finally:
        if own:
            con.close()


def read_tennis_rankings(tour=None, limit=150, con=None):
    """Read the latest complete capture for one or both tours."""
    if tour is not None:
        tour = str(tour).lower()
        if tour not in ("atp", "wta"):
            raise ValueError("tour must be atp or wta")
    limit = max(1, min(int(limit), 150))
    own = con is None
    con = con or _db()
    try:
        init(con)
        tours = [tour] if tour else ["atp", "wta"]
        result = []
        for selected in tours:
            latest = con.execute(
                "SELECT MAX(captured_at) AS captured_at"
                " FROM tennis_ranking_snapshots WHERE tour=?",
                (selected,),
            ).fetchone()
            captured_at = latest["captured_at"] if latest else None
            if not captured_at:
                continue
            rows = con.execute(
                "SELECT espn_athlete_id, player_id, player_name, rank,"
                " previous_rank, points FROM tennis_ranking_snapshots"
                " WHERE tour=? AND captured_at=? ORDER BY rank LIMIT ?",
                (selected, captured_at, limit),
            ).fetchall()
            try:
                moment = dt.datetime.fromisoformat(captured_at)
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=dt.timezone.utc)
                age = int((_now() - moment).total_seconds())
            except (TypeError, ValueError):
                age = None
            result.append({
                "tour": selected,
                "captured_at": captured_at,
                "age_seconds": age,
                "source": "espn_world_rankings",
                "rankings": [dict(row) for row in rows],
            })
        return result
    finally:
        if own:
            con.close()


def tennis_rankings_need_refresh(tour, max_age=dt.timedelta(hours=24), con=None):
    """Whether a tour lacks a capture made within the bounded daily cadence."""
    own = con is None
    con = con or _db()
    try:
        init(con)
        row = con.execute(
            "SELECT MAX(captured_at) AS captured_at"
            " FROM tennis_ranking_snapshots WHERE tour=?",
            (str(tour).lower(),),
        ).fetchone()
        if not row or not row["captured_at"]:
            return True
        moment = dt.datetime.fromisoformat(row["captured_at"])
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return _now() - moment >= max_age
    except (TypeError, ValueError):
        return True
    finally:
        if own:
            con.close()


def save_soccer_competition(snapshot, source="espn", con=None):
    """Replace one validated competition hub snapshot atomically."""
    snapshot = dict(snapshot or {})
    league = str(snapshot.get("league") or "").lower()
    if league not in ("mls", "lcup"):
        raise ValueError("soccer competition snapshot must be mls or lcup")
    season = snapshot.get("season")
    if league == "mls":
        groups = list(snapshot.get("groups") or [])
        rows = [row for group in groups for row in (group.get("rows") or [])]
        keys = [str(row.get("abbrev") or "") for row in rows]
        if (not isinstance(season, int) or not groups or not rows
                or any(not key for key in keys) or len(set(keys)) != len(keys)):
            raise ValueError("invalid MLS standings snapshot")
        match_ids = []
        leader_ids = []
    else:
        groups = []
        rounds = list(snapshot.get("rounds") or [])
        leaders = list(snapshot.get("leader_categories") or [])
        match_ids = [
            str(match.get("game_id") or "")
            for round_row in rounds
            for match in (round_row.get("matches") or [])
        ]
        leader_ids = [
            f"{category.get('key')}:{row.get('espn_athlete_id')}"
            for category in leaders
            for row in (category.get("leaders") or [])
        ]
        if (not isinstance(season, int) or not rounds or not match_ids
                or any(not match_id for match_id in match_ids)
                or len(set(match_ids)) != len(match_ids)
                or any(not value.split(":", 1)[-1] for value in leader_ids)
                or len(set(leader_ids)) != len(leader_ids)):
            raise ValueError("invalid Leagues Cup bracket or leaders snapshot")

    own = con is None
    con = con or _db()
    try:
        init(con)
        fetched_at = _iso(_now())
        con.execute(
            "INSERT INTO soccer_competition_snapshots"
            " (league, season, payload, match_count, leader_count, fetched_at, source)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(league) DO UPDATE SET season=excluded.season,"
            " payload=excluded.payload, match_count=excluded.match_count,"
            " leader_count=excluded.leader_count, fetched_at=excluded.fetched_at,"
            " source=excluded.source",
            (league, season, json.dumps(snapshot), len(match_ids), len(leader_ids),
             fetched_at, source),
        )
        if own:
            con.commit()
        return {
            "matches": len(match_ids),
            "leaders": len(leader_ids),
            "standings": len(rows) if league == "mls" else 0,
        }
    finally:
        if own:
            con.close()


def read_soccer_competition(league, con=None):
    """Read a persisted competition hub snapshot; never fetch a publisher."""
    own = con is None
    con = con or _db()
    try:
        init(con)
        row = con.execute(
            "SELECT payload, fetched_at, source FROM soccer_competition_snapshots"
            " WHERE league=?",
            (str(league).lower(),),
        ).fetchone()
        if not row:
            return None
        snapshot = json.loads(row["payload"])
        snapshot.update({"fetched_at": row["fetched_at"], "source": row["source"]})
        return snapshot
    except (sqlite3.Error, TypeError, ValueError) as exc:
        print(f"[scoreboard_store] read_soccer_competition failed: {type(exc).__name__}: {exc}")
        return None
    finally:
        if own:
            con.close()


def soccer_competition_need_refresh(league, max_age=dt.timedelta(hours=6), con=None):
    own = con is None
    con = con or _db()
    try:
        init(con)
        row = con.execute(
            "SELECT fetched_at FROM soccer_competition_snapshots WHERE league=?",
            (str(league).lower(),),
        ).fetchone()
        if not row:
            return True
        moment = dt.datetime.fromisoformat(row["fetched_at"])
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=dt.timezone.utc)
        return _now() - moment >= max_age
    except (TypeError, ValueError):
        return True
    finally:
        if own:
            con.close()


def live_targets(now=None, con=None):
    """(league, game_date) pairs holding a game that has started and is not final.

    This is what the live poller refreshes, and it is the whole reason polling
    is cheap: on a quiet morning it returns nothing and the poller spends zero
    requests, while during a slate it returns the one or two leagues actually
    playing rather than all eleven.
    """
    now = now or _now()
    floor = _iso(now - LIVE_TAIL)
    ceiling = _iso(now)
    own = con is None
    con = con or _db()
    try:
        init(con)
        rows = con.execute(
            "SELECT DISTINCT league, game_date FROM scoreboard_snapshots"
            " WHERE (state IS NULL OR state != 'post')"
            "   AND league != 'wc'"
            "   AND start_time IS NOT NULL"
            "   AND start_time <= ? AND start_time >= ?"
            " ORDER BY league, game_date",
            (ceiling, floor),
        ).fetchall()
        return [(row["league"], row["game_date"]) for row in rows]
    except sqlite3.Error as exc:
        print(f"[scoreboard_store] live_targets failed: {type(exc).__name__}: {exc}")
        return []
    finally:
        if own:
            con.close()


def needs_refresh(league, game_date, empty_backoff=EMPTY_BACKOFF, con=None,
                  future_backoff=FUTURE_BACKOFF):
    """Should the schedule run spend a request on this (league, date)?

    Being in season is not the same as having something new to say. Three cases
    the publisher has already answered, so re-asking buys nothing:

      never fetched      ask, always. A gap must cost a request, not a blank board.
      published nothing  a slate that came back empty is not going to fill in
                         within minutes. Backed off, but not abandoned -- a
                         postponement or a late addition still lands within
                         `empty_backoff`.
      every game final   nothing about a finished day can change. Yesterday's
                         board is fetched once and then never again.

    Returns (True/False, reason). The reason is printed, because a skipped
    request is a decision and an unexplained one is indistinguishable from a bug.
    """
    league = league.lower()
    own = con is None
    con = con or _db()
    try:
        init(con)
        refresh = con.execute(
            "SELECT fetched_at, game_count FROM scoreboard_refresh"
            " WHERE league=? AND game_date=?",
            (league, game_date),
        ).fetchone()
        if refresh is None:
            return True, "never fetched"
        try:
            moment = dt.datetime.fromisoformat(refresh["fetched_at"])
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=dt.timezone.utc)
            age = _now() - moment
        except (ValueError, TypeError):
            return True, "unreadable fetched_at"

        if not refresh["game_count"]:
            if game_date < _today_for(league):
                # An empty day that is OVER stays empty. The backoff exists for
                # a postponement or a late addition, and a finished day can
                # have neither -- so re-asking is a request per viewer for an
                # answer that is already fixed, which is the whole thing this
                # store exists to stop.
                return False, "day is over and published no games"
            if age >= empty_backoff:
                return True, f"empty, last asked {int(age.total_seconds() // 60)}m ago"
            return False, f"published no games {int(age.total_seconds() // 60)}m ago"

        unfinished = con.execute(
            "SELECT COUNT(*) FROM scoreboard_snapshots"
            " WHERE league=? AND game_date=? AND (state IS NULL OR state != 'post')",
            (league, game_date),
        ).fetchone()[0]
        if unfinished:
            started = con.execute(
                "SELECT COUNT(*) FROM scoreboard_snapshots"
                " WHERE league=? AND game_date=? AND state IN ('in', 'post')",
                (league, game_date),
            ).fetchone()[0]
            # `started` is what separates "has not begun" from "in flight". The
            # date comparison alone would not: `game_date` is a slate day, so a
            # game can still be running when the league's clock has rolled over.
            # One started game is enough to hand the day straight back to the
            # unfinished path it would otherwise have taken.
            if not started and game_date > _today_for(league):
                minutes = int(age.total_seconds() // 60)
                if age >= future_backoff:
                    return True, f"future slate, last asked {minutes}m ago"
                return False, f"future slate, none started, asked {minutes}m ago"
            return True, f"{unfinished} not final"
        return False, "every game final"
    except sqlite3.Error as exc:
        # A store that cannot answer must not be read as "nothing to do".
        return True, f"store unreadable: {type(exc).__name__}: {exc}"
    finally:
        if own:
            con.close()


def coverage(con=None):
    """One row per stored (league, date): count, age, source. For the audit."""
    own = con is None
    con = con or _db()
    try:
        init(con)
        return con.execute(
            "SELECT league, game_date, game_count, fetched_at, source"
            " FROM scoreboard_refresh ORDER BY game_date DESC, league"
        ).fetchall()
    finally:
        if own:
            con.close()
