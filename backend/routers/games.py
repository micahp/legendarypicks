"""routers/games.py — games endpoints. Handlers only; shared code lives in _core."""
import datetime as dt
import html
import json
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from typing import Optional
from _core import *
from team_stats_contract import build_team_aggregates
from provenance import publishers_for

router = APIRouter()

_SCHEDULE_DATES_CONTRACT = "league-schedule-dates-v1"
_NFL_SCHEDULE_WEEKS_CONTRACT = "nfl-schedule-weeks-v1"
_NFL_SCHEDULE_WEEK_CONTRACT = "nfl-schedule-week-v1"
_SCHEDULE_SEARCH_RANGES = {
    # Keep every ESPN range comfortably below its 1,000-event response cap.
    # A full NBA season in one 280-day request can otherwise truncate before
    # the games nearest the anchor (especially when searching backwards).
    "future": (
        (0, 14),
        (15, 45),
        (46, 90),
        (91, 150),
        (151, 210),
        (211, 270),
        (271, 330),
        (331, 370),
    ),
    "past": (
        (-14, -1),
        (-45, -15),
        (-90, -46),
        (-150, -91),
        (-210, -151),
        (-270, -211),
        (-330, -271),
        (-370, -331),
    ),
}
_SCHEDULE_CANDIDATE_LIMIT = 64
_MIN_VIEWER_OFFSET = dt.timezone(dt.timedelta(hours=-12))
_MAX_VIEWER_OFFSET = dt.timezone(dt.timedelta(hours=14))


def _parse_anchor_date(anchor: Optional[str]) -> dt.date:
    if anchor is None:
        return dt.date.today()
    try:
        parsed = dt.date.fromisoformat(anchor)
    except (TypeError, ValueError):
        raise HTTPException(400, "anchor must be YYYY-MM-DD")
    if parsed.isoformat() != anchor:
        raise HTTPException(400, "anchor must be YYYY-MM-DD")
    return parsed


def _default_nfl_season(anchor: dt.date) -> int:
    return anchor.year - 1 if anchor.month <= 2 else anchor.year


def _flatten_nfl_weeks(phases):
    return [week for phase in phases for week in phase.get("weeks", [])]


def _default_nfl_week(weeks, anchor: dt.date):
    if not weeks:
        return None, "none"
    anchor_text = anchor.isoformat()
    starts = [str(week.get("start_time") or "")[:10] for week in weeks]
    if anchor_text < starts[0]:
        return weeks[0], "next"
    for index, week in enumerate(weeks):
        next_start = starts[index + 1] if index + 1 < len(starts) else None
        if next_start is not None and anchor_text < next_start:
            return week, "current"
        if next_start is None:
            end_text = str(week.get("end_time") or "")[:10]
            return week, "current" if anchor_text <= end_text else "latest"
    return weeks[-1], "latest"


def _event_start(value):
    """Parse an absolute ESPN start time, returning ``None`` for junk."""
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _is_guaranteed_directional_start(value, anchor: dt.date, direction: str):
    """Whether every real viewer timezone places ``value`` past the anchor.

    The browser remains authoritative for its local calendar. This conservative
    check only tells the backend when it has searched far enough: a future start
    must still be after ``anchor`` at UTC-12, while a past start must already be
    before it at UTC+14. Boundary starts are retained for the browser but do not
    prematurely stop discovery.
    """
    parsed = _event_start(value)
    if parsed is None:
        return False
    if direction == "future":
        return parsed.astimezone(_MIN_VIEWER_OFFSET).date() > anchor
    return parsed.astimezone(_MAX_VIEWER_OFFSET).date() < anchor


def _cap_schedule_candidates(starts, anchor: dt.date, direction: str):
    ordered = sorted(set(starts))
    if len(ordered) <= _SCHEDULE_CANDIDATE_LIMIT:
        return ordered

    guaranteed = [
        value
        for value in ordered
        if _is_guaranteed_directional_start(value, anchor, direction)
    ]
    if direction == "future":
        selected = ordered[:_SCHEDULE_CANDIDATE_LIMIT]
        if guaranteed and not any(value in selected for value in guaranteed):
            selected[-1] = guaranteed[0]
    else:
        selected = ordered[-_SCHEDULE_CANDIDATE_LIMIT:]
        if guaranteed and not any(value in selected for value in guaranteed):
            selected[0] = guaranteed[-1]
    return sorted(set(selected))


# How stale our own last read may be before the serving path stops trusting it.
# The schedule timer runs every 10 minutes and the live poller every minute, so
# anything past this means a timer is not running -- and a dead timer must
# degrade to calling the publisher, not quietly serve a half-hour-old score.
# Staleness that nobody can see is worse than a slow page: a frozen board looks
# exactly like a correct one.
_SNAPSHOT_MAX_AGE = 15 * 60


def _scoreboard_snapshot(league: str, game_date: str):
    """Our stored slate for this day, or None to fall through to the publisher.

    None means one of two things, and both of them are honest reasons to ask
    upstream: we have never fetched this (league, date), or what we hold is
    older than `_SNAPSHOT_MAX_AGE`. An empty list is different -- it is the
    publisher having told us there are no games -- and it is served as such.
    """
    try:
        import scoreboard_store
        stored = scoreboard_store.read(league, game_date)
    except Exception as exc:
        print(f"[scores] snapshot unreadable league={league} date={game_date}: "
              f"{type(exc).__name__}: {exc}")
        return None
    if stored is None:
        return None
    age = stored.get("age_seconds")
    if age is None:
        return None
    if age > _SNAPSHOT_MAX_AGE and not _nothing_newer_to_have(league, game_date):
        return None
    return stored["games"], age


def _nothing_newer_to_have(league: str, game_date: str) -> bool:
    """Is this snapshot old because a timer died, or because it is finished?

    The age ceiling exists to catch a dead timer. It must not also retire the
    days the ingest is deliberately not refreshing -- an out-of-season league,
    a day where every game is final, a slate the publisher said was empty. Those
    go hours or months without a write BY DESIGN, and falling through to ESPN
    for them would put back exactly the per-request upstream call this replaced,
    on the leagues that need it least.
    """
    try:
        import league_activity
        import scoreboard_store
        if league_activity.plays_on(league, game_date) is False:
            return True
        wanted, _ = scoreboard_store.needs_refresh(league, game_date)
        return not wanted
    except Exception:
        # Unknown is not "fine". Fall through and ask the publisher.
        return False


def _games_from_db(league: str, game_date: str):
    """Return completed publisher results in the scoreboard's shared shape.

    ``team_game_results.game_date`` is day-precision data.  Keep it that way:
    inventing ``T00:00:00Z`` would move the result onto the prior viewer-local
    day throughout the Americas.  The browser recognizes a date-only value and
    keeps it in the backend bucket that was requested.

    A game is usable only when the published result holds exactly one home row
    and one away row with reciprocal scores.  A partial or contradictory pair
    is not a scoreboard result and is reported rather than rendered.
    """
    try:
        with closing(_db()) as con:
            rows = con.execute(
                "SELECT game_id, game_date, team, opponent, home_away,"
                " score_for, score_against, status"
                " FROM team_game_results WHERE league=? AND game_date=?"
                " AND status='completed'"
                " ORDER BY game_id, home_away, team",
                (league.lower(), game_date),
            ).fetchall()
    except sqlite3.Error as exc:
        print(
            f"[scores] DB fallback unavailable league={league.lower()} "
            f"date={game_date} error={type(exc).__name__}: {exc}"
        )
        return []

    grouped = {}
    for row in rows:
        grouped.setdefault(str(row["game_id"]), []).append(row)

    games = []
    rejected = []
    for game_id, pair in grouped.items():
        homes = [row for row in pair if row["home_away"] == "home"]
        aways = [row for row in pair if row["home_away"] == "away"]
        if len(homes) != 1 or len(aways) != 1:
            rejected.append(game_id)
            continue
        home, away = homes[0], aways[0]
        if (
            home["score_for"] is None
            or away["score_for"] is None
            or home["score_against"] != away["score_for"]
            or away["score_against"] != home["score_for"]
        ):
            rejected.append(game_id)
            continue

        games.append({
            "game_id": game_id,
            "date": str(home["game_date"]),
            "date_precision": "day",
            "state": "post",
            "completed": True,
            "status": home["status"],
            "home": {"abbrev": home["team"], "score": home["score_for"]},
            "away": {"abbrev": away["team"], "score": away["score_for"]},
        })

    if rejected:
        print(
            f"[scores] DB fallback rejected {len(rejected)} unpaired or "
            f"contradictory games league={league.lower()} date={game_date}: "
            f"{','.join(rejected[:10])}"
        )
    return games


# The tables that make a season worth offering. A standings year the rest of
# the app cannot follow up on — no players, no logs, no team aggregates — is a
# table attached to nothing.
_SEASON_EVIDENCE_TABLES = ("player_stats", "player_game_logs", "team_game_results")


def seasons_we_hold(league: str):
    """Seasons this league actually has data for in OUR tables.

    ESPN will serve 24-25 years of standings for every league. Measured
    2026-08-17 we hold one to three seasons each, so the picker was offering two
    decades of tables that connect to nothing else on the site — pick 2003 and
    the Stats tab, the game logs and the props all have nothing to say.

    A missing table is not an empty answer: it means we cannot tell what we hold,
    so it is skipped rather than counted as zero.
    """
    held = set()
    lg = (league or "").lower()
    try:
        with closing(_db()) as con:
            names = {row[0] for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            for table in _SEASON_EVIDENCE_TABLES:
                if table not in names:
                    continue
                try:
                    held.update(
                        row[0] for row in con.execute(
                            f"SELECT DISTINCT season FROM {table}"
                            " WHERE league=? AND season IS NOT NULL",
                            (lg,),
                        ) if isinstance(row[0], int)
                    )
                except sqlite3.Error:
                    continue
    except sqlite3.Error as exc:
        print(f"[standings] cannot read held seasons league={lg}: {type(exc).__name__}: {exc}")
        return set()
    return held


def _offer_only_seasons_we_hold(payload, league: str):
    """Narrow a standings envelope's `available_seasons` to years we hold.

    The season being SERVED is always offered even when we hold nothing for it —
    it is what is on screen, and dropping it would leave the pill naming a year
    that is not in its own option list. Everything else has to earn its place by
    having data behind it.
    """
    if not isinstance(payload, dict):
        return payload
    offered = payload.get("available_seasons")
    if not isinstance(offered, list) or not offered:
        return payload
    held = seasons_we_hold(league)
    served = payload.get("season")
    kept = [year for year in offered if year in held or year == served]
    if served is not None and served not in kept:
        kept.append(served)
    payload["available_seasons"] = sorted(set(kept), reverse=True)
    return payload


def _strength_from_db(league: str):
    """Latest ESPN-published strength snapshot, without deriving missing fields."""
    try:
        with closing(_db()) as con:
            rows = con.execute(
                "SELECT captured_at, abbrev, win_pct, differential, wins, losses"
                " FROM strength_snap WHERE league=? AND captured_at=("
                " SELECT MAX(captured_at) FROM strength_snap WHERE league=?"
                ") ORDER BY win_pct DESC, abbrev",
                (league.lower(), league.lower()),
            ).fetchall()
    except sqlite3.Error as exc:
        print(
            f"[strength] DB fallback unavailable league={league.lower()} "
            f"error={type(exc).__name__}: {exc}"
        )
        return []

    return [
        {
            "abbrev": row["abbrev"],
            "name": None,
            "wins": row["wins"],
            "losses": row["losses"],
            "win_pct": row["win_pct"],
            "differential": row["differential"],
            "streak": None,
            "last10": None,
            "games_played": None,
            "captured_at": row["captured_at"],
            "source": "strength_snap",
        }
        for row in rows
        if row["abbrev"] and row["win_pct"] is not None
    ]


def _local_event_starts(league: str, anchor: dt.date, direction: str):
    """Event start instants we already hold, for the day arrows.

    The board's ``‹`` and ``›`` asked ESPN on every click, so when the host
    refused, the arrow silently did nothing and the board simply would not move
    past a certain day. Measured 2026-08-18: `schedule-dates` returned
    `source: unavailable` with a 403 for every league, and going back before
    Sunday was impossible -- with UFC 330 sitting in our own database the whole
    time.

    Only sources carrying a real INSTANT are read. `team_game_results` is day
    precision on purpose, and turning `2026-08-16` into midnight UTC would move
    the event onto the previous local day throughout the Americas, which is the
    same mistake `_games_from_db` refuses to make. The contract promises
    instants and the browser converts them, so a fabricated one is worse than a
    missing one.
    """
    horizon = dt.timedelta(days=370)
    if direction == "past":
        low, high = anchor - horizon, anchor + dt.timedelta(days=1)
    else:
        low, high = anchor - dt.timedelta(days=1), anchor + horizon
    try:
        with closing(_db()) as con:
            rows = con.execute(
                "SELECT start_time FROM scoreboard_snapshots"
                "  WHERE league=? AND start_time IS NOT NULL"
                "        AND substr(start_time,1,10) BETWEEN ? AND ?"
                " UNION"
                " SELECT start_time FROM prop_games"
                "  WHERE league=? AND start_time IS NOT NULL"
                "        AND substr(start_time,1,10) BETWEEN ? AND ?",
                (league, low.isoformat(), high.isoformat(),
                 league, low.isoformat(), high.isoformat()),
            ).fetchall()
    except sqlite3.Error as exc:
        print(f"[schedule-dates] local starts unavailable league={league}: "
              f"{type(exc).__name__}: {exc}")
        return []
    return sorted({str(row[0]) for row in rows if row[0]})


def _schedule_candidates(league: str, anchor: dt.date, direction: str):
    attempts = []
    candidates = []
    for start_delta, end_delta in _SCHEDULE_SEARCH_RANGES[direction]:
        start_date = anchor + dt.timedelta(days=start_delta)
        end_date = anchor + dt.timedelta(days=end_delta)
        starts = espn.schedule_event_starts(league, start_date, end_date)
        candidates.extend(starts)
        attempts.append({
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "event_starts_found": len(starts),
        })
        if any(
            _is_guaranteed_directional_start(value, anchor, direction)
            for value in starts
        ):
            break
    return _cap_schedule_candidates(candidates, anchor, direction), attempts


def _attach_cod_detail_ids(matches):
    """Add a PandaScore detail id only when the fixture identity resolves.

    BreakingPoint remains the scoreboard source and keeps its own ``game_id``.
    The dedicated CoD detail route is PandaScore-backed, so expose that separate
    id after the shared esports matcher verifies both opponents and match time.
    Unresolved fixtures intentionally stay without a detail id.
    """
    try:
        from routers.esports.pandascore import _iso_to_ms, _ps_enrich
    except Exception as exc:
        print(f"[sports_service] CoD detail identity unavailable ({exc})")
        return matches

    for match in matches:
        # Rows already reconciled (EWC bracket rows carry a PandaScore id from the indexed
        # bracket graph) must not trigger a second, per-row fuzzy lookup.
        if match.get("detail_game_id"):
            continue
        home = (match.get("home") or {}).get("name")
        away = (match.get("away") or {}).get("name")
        near_ms = _iso_to_ms(match.get("date"))
        if not home or not away or not near_ms:
            continue
        try:
            identity = _ps_enrich(
                home,
                away,
                include_running=True,
                near_ms=near_ms,
                league="Call of Duty",
            )
        except Exception as exc:
            print(f"[sports_service] CoD detail identity failed for {match.get('game_id')} ({exc})")
            continue
        if identity and identity.get("_ps_id") is not None:
            match["detail_game_id"] = str(identity["_ps_id"])
    return matches

@router.get("/")
def root():
    return {"service": "Legendary Picks Sports API", "version": "2.0.0",
            "source": "ESPN", "leagues": sorted(espn.LEAGUES)}


# Both paths, and `/api/health` is the one that matters: the Next dev server
# proxies ONLY `/api/*`, so bare `/health` through a tunnel hits the frontend and
# returns its 404 page. A health endpoint you cannot reach from the URL you are
# actually looking at is not one you will ever use -- which is why this took a
# walk through /proc on 2026-08-17 instead of one curl.
@router.get("/api/health")
@router.get("/health")
def health():
    """Which database is this process actually serving, and how stale is it?

    `{"status": "ok"}` was the whole response, and "ok" was true of every server
    on this box at once -- prod, dev, and a worktree serving a throwaway snapshot
    in /tmp. On 2026-08-17 a dev tunnel showed "2 games, 104 props" and looked
    frozen; the cause was that its backend pointed at
    `/tmp/lp-mls-ncaaf-standings-runtime.VgZl9x/picks.db`, a copy taken at 11:16
    on Aug 15 so the worktree could not corrupt the real dev DB. Correct
    isolation, no visible signal: it answered 200 and looked like the app. Finding
    it meant walking /proc for the listening pid's LP_DB_PATH.

    A health check that cannot distinguish those three is not a health check, it
    is a liveness ping wearing the name. So say the two things that actually
    identify a deployment: WHICH file, and HOW FRESH.

    Deliberately cheap -- two MAX() lookups on indexed timestamp columns, because
    this gets polled. Failures degrade to null rather than 500ing: a health
    endpoint that raises when one table is missing tells you less than one that
    answers with the fields it could read.
    """
    info = {"status": "ok", "db_path": DB, "db_mtime": None,
            "newest_prop_captured": None, "newest_game_date": None}
    try:
        con = _db()
    except Exception as exc:
        info["status"] = "degraded"
        info["error"] = "%s: %s" % (type(exc).__name__, exc)
        return info
    try:
        info["db_mtime"] = dt.datetime.fromtimestamp(
            os.path.getmtime(DB), dt.timezone.utc).isoformat()
    except Exception:
        pass
    for key, sql in (("newest_prop_captured", "SELECT MAX(captured_at) FROM props"),
                     ("newest_game_date", "SELECT MAX(date) FROM prop_games")):
        try:
            info[key] = con.execute(sql).fetchone()[0]
        except Exception:
            pass
    return info


@router.get("/api/coverage")
def coverage():
    """The enablement registry: which (league, season) pairs may be offered at all.

    Returns EVERY row, not just the complete ones. A client needs to distinguish
    "this league exists and we cannot vouch for it yet" from "this league does not
    exist" — they are different states and they read differently to a user.

    A (league, season) with no row here is `unverified`, which is the default and is
    never good. See docs/DATA-COVERAGE-CONTRACT.md §4.

    Each row also carries `publishers`: the external sources whose rows actually
    back that league, measured from the data rather than declared. Note that the
    row's own `source` column describes the *verdict* ("reconcile_totals+
    espn_core_api"), not the data — conflating the two is how NHL came to hold
    ESPN-keyed team rows and nhle.com-keyed player rows with nothing saying so.
    More than one publisher is not an error; it is a count of vocabulary
    boundaries this league's joins have to cross.
    """
    with closing(_db()) as con:
        try:
            rows = con.execute(
                "SELECT league, season, status, expected_teams, fetched_teams,"
                " expected_games, fetched_games, paired_games, paired_stat_games,"
                " failure_count, season_start, season_end, completed_at, source,"
                " checked_through"
                " FROM team_stats_coverage ORDER BY league, season"
            ).fetchall()
        except sqlite3.Error:
            # No table is not an error; it means nothing has been verified.
            return []
        pubs = {}
        for r in rows:
            league = r["league"]
            if league not in pubs:
                try:
                    pubs[league] = publishers_for(con, league)
                except sqlite3.Error:
                    pubs[league] = []
    out = []
    for r in rows:
        d = dict(r)
        # Never let an unrecognised status read as permission. Anything outside the
        # three-value vocabulary is treated as unverified rather than passed through.
        # `in_progress` is a season that passes every check but has not ended yet;
        # its row carries `checked_through`, the date its claim actually reaches.
        # It belongs in this list and leaving it out is not a safe default — the
        # guard would rewrite a verified live season to "we cannot vouch for this"
        # and the fix would be invisible end to end.
        if d.get("status") not in ("complete", "in_progress", "partial", "unverified"):
            d["status"] = "unverified"
        d["publishers"] = pubs.get(d["league"], [])
        out.append(d)
    return out


@router.get("/api/ufc/rankings")
def ufc_rankings():
    """UFC rankings — reads cached ufc_rankings table populated by
    ingest_ufc_rankings.py (live scrape, never on the request path)."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT division, rank, fighter, is_champion FROM ufc_rankings "
                "ORDER BY division, rank"
            ).fetchall()
        except sqlite3.OperationalError as exc:
            raise HTTPException(
                503,
                "UFC rankings data unavailable: production data has not been promoted",
            ) from exc

    if not rows:
        raise HTTPException(
            503,
            "UFC rankings data unavailable: production data is empty",
        )

    # Separate P4P from weight divisions
    p4p_men, p4p_women = [], []
    divisions: dict = {}  # division_name -> {champion, ranked: [{rank, fighter}]}

    for r in rows:
        div = r["division"]
        rank = r["rank"]
        raw_fighter = r["fighter"]
        if not isinstance(div, str) or not isinstance(rank, int):
            continue
        if not isinstance(raw_fighter, str) or not raw_fighter.strip():
            continue
        fighter = html.unescape(raw_fighter)
        if "Pound-for-Pound" in div:
            entry = {"rank": rank, "fighter": fighter}
            if r["is_champion"]:
                entry["champion"] = True
            if "Women" in div:
                p4p_women.append(entry)
            else:
                p4p_men.append(entry)
        else:
            if div not in divisions:
                divisions[div] = {"division": div, "champion": "", "ranked": []}
            if r["is_champion"]:
                divisions[div]["champion"] = fighter
            else:
                divisions[div]["ranked"].append(
                    {"rank": rank, "fighter": fighter}
                )

    # Sort P4P by rank (champion=rank 0 first)
    p4p_men.sort(key=lambda x: x["rank"])
    p4p_women.sort(key=lambda x: x["rank"])

    # Order divisions: men's weight classes first, then women's
    MEN_ORDER = [
        "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
        "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight",
    ]
    WOMEN_ORDER = ["Women's Strawweight", "Women's Flyweight", "Women's Bantamweight"]
    ordered = []
    for d in MEN_ORDER:
        if d in divisions:
            divisions[d]["ranked"].sort(key=lambda x: x["rank"])
            ordered.append(divisions[d])
    for d in WOMEN_ORDER:
        if d in divisions:
            divisions[d]["ranked"].sort(key=lambda x: x["rank"])
            ordered.append(divisions[d])

    expected_divisions = set(MEN_ORDER + WOMEN_ORDER)
    populated_divisions = {
        division["division"] for division in ordered if division["ranked"]
    }
    if (
        not p4p_men
        or not p4p_women
        or populated_divisions != expected_divisions
    ):
        raise HTTPException(
            503,
            "UFC rankings data unavailable: production data is incomplete",
        )

    return {
        "pound_for_pound": {"men": p4p_men, "women": p4p_women},
        "divisions": ordered,
    }


@router.get("/api/ufc/fighter/{player_id}/form")
def ufc_fighter_form(player_id: int):
    """Lazy ESPN-backed last-five form for one internal UFC fighter."""
    with closing(_db()) as con:
        con.row_factory = sqlite3.Row
        player = con.execute(
            "SELECT id, name, espn_id FROM players WHERE id=? AND league='ufc'",
            (player_id,),
        ).fetchone()
        if not player:
            raise HTTPException(404, "UFC fighter not found")
        date_row = con.execute(
            """SELECT pg.date
               FROM props p JOIN prop_games pg ON pg.id=p.game_id
               WHERE p.player_id=? AND pg.league='ufc'
               ORDER BY ABS(julianday(pg.date) - julianday('now')) LIMIT 1""",
            (player_id,),
        ).fetchone()

    athlete_id = str(player["espn_id"] or "")
    canonical_name = player["name"]
    if not athlete_id:
        match = espn.ufc_athlete(player["name"], date_row["date"] if date_row else None)
        if not match:
            return {
                "player_id": player_id,
                "fighter": player["name"],
                "source": "espn",
                "fights": [],
            }
        athlete_id = match["id"]
        canonical_name = match["name"]
        # Persist the source crosswalk only when it is not already owned by a
        # different UFC row. The endpoint never fabricates or merges players.
        with closing(_db()) as con:
            owner = con.execute(
                "SELECT id FROM players WHERE league='ufc' AND espn_id=?",
                (athlete_id,),
            ).fetchone()
            if owner is None or owner[0] == player_id:
                con.execute("UPDATE players SET espn_id=? WHERE id=?", (athlete_id, player_id))
                con.commit()

    try:
        fights = espn.ufc_fight_history(athlete_id, limit=5)
    except Exception as exc:
        raise HTTPException(502, "ESPN UFC fight history unavailable") from exc
    return {
        "player_id": player_id,
        "fighter": canonical_name,
        "espn_id": athlete_id,
        "source": "espn",
        "fights": fights,
    }


@router.get("/api/{league}/games")
def get_games(league: str, date: Optional[str] = Query(None, description="YYYY-MM-DD (default today)")):
    if league.lower() == "cod":
        # Call of Duty League — breakingpoint.gg (persists completed matches)
        # Falls back to cdl_client if breakingpoint is unreachable
        try:
            import breakingpoint_client
            matches = breakingpoint_client.get_cod_matches(date_str=date)
            if matches:
                # EWC bracket rows: reconcile against the indexed PandaScore codmw EWC window
                # (once per refresh) so raw "TBD" participants never reach the scoreboard. Non-EWC
                # CDL rows pass through unchanged. See routers/esports/cod_ewc.py.
                from routers.esports.cod_ewc import reconcile_cod_matches
                matches = reconcile_cod_matches(matches)
                return _attach_cod_detail_ids(matches)
        except Exception as e:
            print(f"[sports_service] breakingpoint failed ({e}), falling back to cdl_client")
        import cdl_client
        return _attach_cod_detail_ids(cdl_client.get_matches(date_str=date))
    lg = league.lower()
    data_source = "espn"
    requested_date = date or dt.date.today().isoformat()
    try:
        is_completed_day = date is not None and dt.date.fromisoformat(date) < dt.date.today()
    except ValueError:
        is_completed_day = False

    games = _games_from_db(lg, requested_date) if is_completed_day else None
    snapshot_age = None
    if games:
        data_source = "team_game_results"
    else:
        # Rung 1 is now OUR OWN last read of the publisher, not the publisher.
        # `ingest_scoreboards.py` refreshes the slate on a timer and re-reads
        # only what is in flight, so the page costs a SQLite read and the
        # upstream spend stops scaling with how many people are on the site.
        # Measured 2026-08-18: a cold board was 22 ESPN requests, and the
        # serving process answers its own per-host ceiling with a 60 second
        # sleep, so the board stalled itself every few loads.
        snapshot = _scoreboard_snapshot(lg, requested_date)
        if snapshot is not None:
            games, snapshot_age = snapshot
            data_source = "scoreboard_snapshots"
    if games is None or (not games and data_source == "espn"):
        try:
            games = espn.games(league, date)
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as exc:
            games = _games_from_db(lg, requested_date)
            data_source = "team_game_results" if games else "unavailable"
            if not games:
                # Third rung. We persist FINISHED games, so on the day itself
                # the DB has nothing and the board goes blank — which is exactly
                # when ESPN's per-host request COUNT runs out. Bovada is a
                # different host with the same slate, and its per-event endpoint
                # carries score and clock. It never invents one: a game it
                # cannot vouch for arrives with score None and renders as a dash.
                try:
                    import scoreboard_fallback
                    games = scoreboard_fallback.bovada_games(lg, requested_date)
                    if games:
                        data_source = "bovada"
                except Exception as fallback_exc:
                    print(f"[scores] bovada fallback failed league={lg}: "
                          f"{type(fallback_exc).__name__}: {fallback_exc}")
                    games = []
            print(
                f"[scores] publisher unavailable league={lg} date={requested_date} "
                f"error={type(exc).__name__}: {exc}; "
                f"fallback_games={len(games)} source={data_source}"
            )

    # ── finished-game final score: prefer our captured final ───────────────
    # The schedule above is ESPN-first because live and upcoming games are not
    # persisted.  For a post-state game, however, prefer OUR captured final
    # (scoring_plays, then team_game_results) over the scoreboard tick. These
    # helpers are DB-only; they make no additional ESPN request.
    if data_source == "espn":
        for g in games:
            if g.get("state") != "post":
                continue
            final = _final_score_from_db(lg, g["game_id"])
            if final:
                if g.get("home"):
                    g["home"]["score"] = final["home"]
                if g.get("away"):
                    g["away"]["score"] = final["away"]
    # "Write the preview whenever we find out about the game." That used to mean
    # this handler, because the page load was the fetch. It is not any more: the
    # ingest is where we find out, so `ingest_scoreboards.py` kicks the stories
    # and this only covers the path where the handler did call the publisher
    # itself. Leaving it on the snapshot path as well would put the generation
    # back into the request that the snapshot exists to keep cheap.
    if data_source == "espn" and lg in ("nba", "nhl", "mlb", "nfl"):
        kick_game_stories(lg, games)
    max_age = 15 if data_source == "unavailable" else 30
    headers = {
        "Cache-Control": f"public, max-age={max_age}",
        "X-LP-Data-Source": data_source,
    }
    if snapshot_age is not None:
        # How old the publisher's answer is, not how old the response is. A
        # score with no age is a claim about now that we cannot support.
        headers["X-LP-Data-Age"] = str(snapshot_age)
    return JSONResponse(content=games, headers=headers)


@router.get("/api/{league}/schedule-dates")
def get_schedule_dates(
    league: str,
    anchor: Optional[str] = Query(None, description="Viewer-local YYYY-MM-DD"),
):
    """Bounded event-start candidates for resolving an empty schedule day.

    Event starts stay as absolute ISO instants. The browser converts them to
    its own local calendar before choosing the nearest future date or, when no
    future event exists in the verified horizon, the most recent past date.
    """
    lg = league.lower()
    if lg not in espn.LEAGUES:
        raise HTTPException(404, f"unsupported league {lg!r}")
    anchor_date = _parse_anchor_date(anchor)

    # Answer from what we hold before asking the publisher. Each arrow click used
    # to cost an ESPN request per league, so the navigation had exactly the
    # disease the board just had: a cost that scales with user traffic, and a
    # dead end the moment the host refuses. A direction we can already answer is
    # answered for free; one we cannot still asks.
    local_future = _local_event_starts(lg, anchor_date, "future")
    local_past = _local_event_starts(lg, anchor_date, "past")
    if local_future and local_past:
        return JSONResponse(
            content={
                "contract": _SCHEDULE_DATES_CONTRACT,
                "league": lg,
                "anchor_date": anchor_date.isoformat(),
                "event_start_timezone": "UTC",
                "available": True,
                "source": "local",
                "future_event_starts": _cap_schedule_candidates(
                    local_future, anchor_date, "future"),
                "past_event_starts": _cap_schedule_candidates(
                    local_past, anchor_date, "past"),
                "search": {"future": [], "past": [], "max_horizon_days": 370},
            },
            headers={"Cache-Control": "public, max-age=60"},
        )

    try:
        future_starts, future_search = _schedule_candidates(lg, anchor_date, "future")
        past_starts, past_search = _schedule_candidates(lg, anchor_date, "past")
    except Exception as exc:
        print(
            f"[schedule-dates] publisher unavailable league={lg} "
            f"anchor={anchor_date.isoformat()} error={type(exc).__name__}: {exc}"
        )
        # A refusal is not a reason to answer with nothing when we hold half the
        # answer. Whatever direction we can serve locally is served, and the
        # response still says the publisher was unavailable so a caller can tell
        # a partial answer from a complete one.
        have_local = bool(local_future or local_past)
        return JSONResponse(
            content={
                "contract": _SCHEDULE_DATES_CONTRACT,
                "league": lg,
                "anchor_date": anchor_date.isoformat(),
                "event_start_timezone": "UTC",
                "available": have_local,
                "source": "local" if have_local else "unavailable",
                "error": "publisher_unavailable",
                "future_event_starts": _cap_schedule_candidates(
                    local_future, anchor_date, "future") if local_future else [],
                "past_event_starts": _cap_schedule_candidates(
                    local_past, anchor_date, "past") if local_past else [],
                "search": {
                    "future": [],
                    "past": [],
                    "max_horizon_days": 370,
                },
            },
            headers={"Cache-Control": "public, max-age=15"},
        )

    return JSONResponse(
        content={
            "contract": _SCHEDULE_DATES_CONTRACT,
            "league": lg,
            "anchor_date": anchor_date.isoformat(),
            "event_start_timezone": "UTC",
            "available": True,
            "source": "espn",
            "future_event_starts": future_starts,
            "past_event_starts": past_starts,
            "search": {
                "future": future_search,
                "past": past_search,
                "max_horizon_days": 370,
            },
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/nfl/schedule-weeks")
def get_nfl_schedule_weeks(
    season: Optional[int] = Query(None, ge=2000, le=2100),
    anchor: Optional[str] = Query(None, description="Viewer-local YYYY-MM-DD"),
):
    """ESPN's ordered NFL phase/week catalog and the default week for an anchor date."""
    anchor_date = _parse_anchor_date(anchor)
    selected_season = season if season is not None else _default_nfl_season(anchor_date)
    if selected_season < 2000 or selected_season > 2100:
        raise HTTPException(400, "season must be between 2000 and 2100")
    try:
        phases = espn.nfl_schedule_weeks(selected_season)
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week catalog unavailable") from exc

    weeks = _flatten_nfl_weeks(phases)
    default_week, default_reason = _default_nfl_week(weeks, anchor_date)
    if default_week is None:
        raise HTTPException(502, "NFL schedule week catalog is empty")
    return JSONResponse(
        content={
            "contract": _NFL_SCHEDULE_WEEKS_CONTRACT,
            "league": "nfl",
            "season": selected_season,
            "anchor_date": anchor_date.isoformat(),
            "navigation": "week",
            "phases": phases,
            "weeks": weeks,
            "default_week_key": default_week["key"],
            "default_reason": default_reason,
        },
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/nfl/schedule-week")
def get_nfl_schedule_week(
    season: int = Query(..., ge=2000, le=2100),
    season_type: int = Query(..., ge=1, le=3),
    week: int = Query(..., ge=1, le=25),
):
    """One NFL week of games, keyed by ESPN season type and week number."""
    if season < 2000 or season > 2100:
        raise HTTPException(400, "season must be between 2000 and 2100")
    if season_type not in (1, 2, 3):
        raise HTTPException(400, "season_type must be 1, 2, or 3")
    if week < 1 or week > 25:
        raise HTTPException(400, "week must be between 1 and 25")
    try:
        phases = espn.nfl_schedule_weeks(season)
    except (TypeError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week catalog unavailable") from exc

    selected = next(
        (
            candidate
            for candidate in _flatten_nfl_weeks(phases)
            if candidate["season_type"] == season_type and candidate["week"] == week
        ),
        None,
    )
    if selected is None:
        raise HTTPException(404, "NFL schedule week not found")
    try:
        week_games = espn.nfl_schedule_week_games(season, season_type, week)
    except Exception as exc:
        raise HTTPException(502, "NFL schedule week games unavailable") from exc

    return JSONResponse(
        content={
            "contract": _NFL_SCHEDULE_WEEK_CONTRACT,
            "league": "nfl",
            "season": season,
            "navigation": "week",
            "selected_week": selected,
            "games": week_games,
        },
        headers={"Cache-Control": "public, max-age=20"},
    )


@router.get("/api/{league}/strength")
def get_strength(league: str):
    """Teams ranked by quality (win%, differential, streak, last-10) — the selection prior."""
    try:
        rows = espn.team_strength(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as exc:
        rows = _strength_from_db(league)
        data_source = "strength_snap" if rows else "unavailable"
        print(
            f"[strength] publisher unavailable league={league.lower()} "
            f"error={type(exc).__name__}: {exc}; fallback_rows={len(rows)} "
            f"source={data_source}"
        )
        return JSONResponse(
            content=rows,
            headers={
                "Cache-Control": "public, max-age=30",
                "X-LP-Data-Source": data_source,
            },
        )
    _snapshot_strength(league.lower(), rows)
    return JSONResponse(
        content=rows,
        headers={
            "Cache-Control": "public, max-age=300",
            "X-LP-Data-Source": "espn",
        },
    )


@router.get("/api/{league}/standings")
def get_standings(league: str, season: int = None):
    """Group/division standings. For World Cup: group tables during the group
    stage; the canonical knockout bracket/results once the season phase leaves
    'Group' (progression gate via espn.wc_is_knockout — never serve stale groups
    once knockouts have begun)."""
    lg = league.lower()
    if lg == "ncaaf":
        # Conference-grouped tables - CFB's /standings payload has no
        # rank/gamesPlayed/losses keys; the record lives in `overall` and
        # entries arrive pre-ordered by conference standing. See
        # espn_client.ncaaf_conference_standings.
        try:
            return espn.ncaaf_conference_standings()
        except ValueError as e:
            raise HTTPException(404, str(e))
        except HTTPException:
            raise
        except Exception:
            # An unreachable publisher rendered as a 500 stacktrace here. There
            # is no conference-standings snapshot to fall back to, so this stays
            # fail-closed — but it says why, the way the MLS branch does, rather
            # than surfacing "Internal Server Error" to the page.
            raise HTTPException(503, "NCAAF standings unavailable: publisher unreachable")
    if lg == "mls":
        # Eastern/Western tables read from the publisher, carrying the season
        # they belong to. This replaced a DB rollup on 2026-08-17: the rollup's
        # arithmetic was exact (verified against ESPN's published 2025 table,
        # 30/30 teams, zero disagreements) but it served `MAX(season)` of what
        # our tables hold, and they only ever hold a COMPLETED season — so in
        # mid-August it served the 2025 final table, unlabelled.
        #
        # Same doctrine as the World Cup branch below: a standings surface may
        # not serve a table from a season that is over while a season is being
        # played. Upstream failure is a 503 with a reason, never a fall-through
        # to last year (fail-loudly: the stale table is the plausible output
        # that hides the defect).
        try:
            return _offer_only_seasons_we_hold(
                espn.mls_conference_standings(season=season), lg
            )
        except ValueError as e:
            raise HTTPException(503, f"MLS standings unavailable: {e}")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "MLS standings unavailable: publisher unreachable")
    if lg != "wc":
        # The envelope, not the bare row list: a standings table with nothing
        # naming its season is the defect this fixes. /api/{league}/strength
        # keeps the list shape — it is the selection prior, has its own DB
        # fallback, and several callers index it directly.
        try:
            return _offer_only_seasons_we_hold(
                espn.team_strength_standings(lg, season=season), lg
            )
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as exc:
            # This page used to read /strength, which degrades to the last
            # published snapshot when the publisher is unreachable. ESPN 403s
            # this box routinely, so moving the page here without carrying the
            # fallback across turned a degraded table into a 500.
            #
            # A snapshot cannot answer "which season is this", so it is served
            # with season=None and no selectable years: the table renders
            # without a pill rather than under a year we are guessing. And a
            # snapshot is never served for an EXPLICITLY requested season — it
            # is not that season, and quietly substituting it is the stale-table
            # failure this route already refuses for MLS.
            if season is not None:
                raise HTTPException(
                    503, f"{lg} standings for {season} unavailable: publisher unreachable"
                )
            rows = _strength_from_db(lg)
            print(
                f"[standings] publisher unavailable league={lg} "
                f"error={type(exc).__name__}: {exc}; fallback_rows={len(rows)}"
            )
            if not rows:
                raise HTTPException(503, f"{lg} standings unavailable: publisher unreachable")
            return JSONResponse(
                content={"league": lg, "season": None, "season_label": None,
                         "available_seasons": [], "teams": rows},
                headers={"Cache-Control": "public, max-age=30",
                         "X-LP-Data-Source": "strength_snap"},
            )
    # WC: group tables are ONLY valid during the Group phase. Once knockouts
    # have begun, serve the canonical bracket ONLY — never stale group tables.
    # The no-stale-group fallback: if the bracket is empty/unavailable while
    # knockouts are live, return 503 rather than silently serving yesterday's
    # Group standings (the swallowed-exception fall-through that regressed here).
    # Any upstream failure on the knockout path (phase lookup or bracket fetch)
    # becomes 503 too — never an uncaught 500, never a stale-group fall-through.
    try:
        knockout = espn.wc_is_knockout()
    except Exception:
        # Phase lookup failed — we cannot confirm groups are still valid, so do
        # NOT fall through to group_standings (that would serve stale tables).
        raise HTTPException(503, "World Cup phase lookup unavailable")
    if knockout:
        try:
            bracket = espn.wc_knockout_standings()
        except HTTPException:
            raise  # preserve an already-shaped HTTP error from the client layer
        except Exception:
            raise HTTPException(503, "World Cup knockout bracket unavailable")
        if bracket.get("rounds"):
            return bracket
        raise HTTPException(503, "World Cup knockout bracket is unavailable")
    # Group phase — serve group tables
    try:
        return espn.group_standings(league)
    except ValueError as e:
        raise HTTPException(404, str(e))
@router.get("/api/wc/knockout")
def wc_knockout():
    """World Cup knockout bracket — the SAME canonical {rounds:[...]} shape as
    /api/wc/standings during knockouts. Single source of truth:
    espn.wc_knockout_standings(). Returns {rounds:[{round, matches:[{game_id,
    date, home:{abbrev,name}, away:{abbrev,name}, homeScore, awayScore, winner,
    status, state}]}]}."""
    try:
        return espn.wc_knockout_standings()
    except Exception as e:
        raise HTTPException(404, str(e))


@router.get("/api/wc/{game_id}/context")
def wc_context(
    game_id: str,
    limit: int = Query(8, ge=1, le=100),
    phase: Optional[str] = Query(None),
):
    """Phase-aware WC catch-up plus receipt-backed booth episodes.

    With no phase, episodes come from the current match phase. The Booth tab
    may request a past phase on interaction without downloading the whole
    broadcast on initial render.
    """
    allowed_phases = {
        "pregame", "first_half", "halftime", "second_half",
        "extra_time", "penalties", "final",
    }
    if phase is not None and phase not in allowed_phases:
        raise HTTPException(400, f"phase must be one of {sorted(allowed_phases)}")
    import wc_context as _wcc
    ctx = _wcc.build_context(game_id, limit=limit, phase=phase)
    if not ctx:
        raise HTTPException(404, "no context for this game")
    return ctx


@router.get("/api/wc/{game_id}/context/episodes/{episode_id}")
def wc_context_episode(game_id: str, episode_id: str):
    """Full receipt stack for one episode, fetched only when a user expands it."""
    import wc_context as _wcc
    detail = _wcc.get_episode_detail(game_id, episode_id)
    if detail is None:
        # A normal list request primes this bounded derived cache. Rebuild once
        # after a worker restart so an already-open browser can still expand.
        _wcc.build_context(game_id, limit=1)
        detail = _wcc.get_episode_detail(game_id, episode_id)
    if detail is None:
        raise HTTPException(404, "episode not found")
    return detail


@router.get("/api/cod/{game_id}/context")
def cod_game_context(game_id: str, limit: int = Query(12, ge=1, le=100)):
    """Grounded Call of Duty match context from PandaScore history, the existing
    esports slate, and timestamp-matched CDL booth reads."""
    import cod_context as _cod
    ctx = _cod.build_context(game_id, limit=limit)
    if not ctx:
        raise HTTPException(404, "no Call of Duty context for this game")
    return ctx


# Broadcast tapes live in the sibling prediction-market-trading repo. Leagues Cup
# watchers write <YYYYMMDD>_LCUP_<AWAY><HOME>_{transcript,signals}.jsonl there.
_BROADCAST_DIR = "/root/prediction-market-trading/data/broadcast"

_SIGNAL_TAGS = {
    "tilt": "Mentality", "lockin": "Mentality", "fatigue": "Fatigue",
    "tactical": "Tactical", "morale": "Mentality", "momentum": "Momentum",
}


@router.get("/api/lcup/{game_id}/context")
def lcup_game_context(game_id: str, limit: int = Query(12, ge=1, le=100)):
    """Leagues Cup booth: live Spanish radio transcript + soft-signal reads for
    the game, straight from the broadcast_alpha tapes (legacy insights shape,
    newest first). 404 when no watcher is running for this game."""
    import espn_client as _espn
    try:
        summary = _espn.summary("lcup", game_id)
    except Exception:
        raise HTTPException(404, "no context for this game")
    comp = (summary.get("header", {}).get("competitions") or [{}])[0]
    date = (comp.get("date") or "")[:10].replace("-", "")
    abbrevs = {}
    for c in comp.get("competitors", []):
        abbrevs[c.get("homeAway")] = (c.get("team") or {}).get("abbreviation", "")
    if not date or not abbrevs.get("home") or not abbrevs.get("away"):
        raise HTTPException(404, "no context for this game")
    tag = f"{date}_LCUP_{abbrevs['away']}{abbrevs['home']}"

    insights = []

    # Soft signals (DeepSeek-extracted claims) — richer, prefer them first.
    spath = os.path.join(_BROADCAST_DIR, f"{tag}_signals.jsonl")
    if os.path.exists(spath):
        for line in open(spath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
            except Exception:
                continue
            if not s.get("quote"):
                continue
            insights.append({
                "id": f"{tag}-sig-{len(insights)}",
                "tag": _SIGNAL_TAGS.get((s.get("type") or "").lower(), "Momentum"),
                "subject": s.get("subject", "Broadcast"),
                "quote": s["quote"],
                "strength": int(s.get("strength") or 1),
                "ts": s.get("ts"),
                "analysis": (s.get("direction") or "") and f"Booth lean: {s['direction']}",
            })

    # Raw transcript lines — the booth's evidence even before extraction runs.
    # Skip silence/noise lines (whisper renders dead air as dots/single chars).
    tpath = os.path.join(_BROADCAST_DIR, f"{tag}_transcript.jsonl")
    if os.path.exists(tpath):
        for line in open(tpath, encoding="utf-8", errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except Exception:
                continue
            text = (t.get("text") or "").strip()
            if not text:
                continue
            words = [w for w in text.split() if any(ch.isalnum() for ch in w)]
            if len(words) < 2:
                continue
            insights.append({
                "id": f"{tag}-tx-{len(insights)}",
                "tag": "Live",
                "subject": "Radio",
                "quote": text,
                "strength": 1,
                "ts": t.get("ts"),
            })

    if not insights:
        raise HTTPException(404, "no booth data for this game yet")
    insights.sort(key=lambda i: i.get("ts") or "", reverse=True)
    return {"insights": insights[:limit]}


# Free English radio for Leagues Cup — ESPN 106.3 West Palm (WUUB-FM), Inter
# Miami's official English-language radio partner (airs every Inter Miami game).
# amperwave HLS won't play in Chrome's <audio>, so the relay transcodes to MP3
# with ffmpeg and streams it — one ffmpeg per listener.
_LCUP_RADIO = {
    "lcup": "https://live.amperwave.net/manifest/goodkarma-wuubfmaac-hlsc2.m3u8?source=tunein&source=TuneIn&gdpr=0&us_privacy=1YNY",
}


@router.get("/api/stream/{league}")
def stream_league_audio(league: str):
    from fastapi.responses import StreamingResponse
    import subprocess

    url = _LCUP_RADIO.get(league.lower())
    if not url:
        raise HTTPException(404, "no audio stream for this league")
    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", url, "-vn",
         "-ac", "1", "-ar", "44100", "-b:a", "96k", "-f", "mp3", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )

    def gen():
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            try:
                proc.kill()
            except Exception:
                pass

    return StreamingResponse(gen(), media_type="audio/mpeg",
                             headers={"Cache-Control": "no-store"})


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
    is_final = out["state"] == "post"
    # Final score from OUR DB (scoring_plays) — only when the game is actually over.
    if is_final:
        try:
            out["final_score"] = _final_score_from_db(lg, game_id)
        except Exception:
            pass
    # Read from DB
    _read_game_detail_from_db(lg, game_id, out)

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
            out["final_score"] = _final_score_from_db(lg, game_id)

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
