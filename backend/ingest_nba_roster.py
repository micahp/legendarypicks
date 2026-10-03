#!/usr/bin/env python3
"""Publish the current NBA rosters from nba.com itself.

NBA membership was one ESPN snapshot from 2026-08-04 (545 players): before training camps,
late free agency, two-way deals and any trade since. The league's own data hosts refuse this
box (cdn.nba.com 403, stats.nba.com tarpits even with the headers nba.com sends), but the
public team pages at www.nba.com/team/<team id> answer 200 and embed the official
commonteamroster in their __NEXT_DATA__ JSON: NBA player id, number, position, birth date
and HOW_ACQUIRED, plus the team's own TEAM_ABBREVIATION and SEASON_YEAR.

Modelled on ingest_nhl_roster.py, which is the pattern for this spine:

- the whole 30-team population is fetched and validated before a write opens;
- identity resolves by the NBA id first, through player_source_ids(source='nba.com');
  NOT through players.nba_id. Measured 2026-10-02 on both databases: that column holds ESPN
  athlete ids (hoopR's), equal to espn_id on every row that has both (320 prod, 331 dev), and
  no row holds a modern NBA person id. ingest_hoopR.py resolves by it, so it keeps its meaning
  and this publisher never writes it;
- a name is only ever a CANDIDATE, and binds with evidence: same team, or the team nba.com
  says the player was acquired from ("Traded from DET on 07/07/25") -- the published record
  of the move -- so a traded player binds instead of being minted twice;
- any conflict or unproven name fails the whole run closed; nothing is guessed;
- one atomic, versioned roster snapshot through roster_membership.publish_roster_snapshot,
  with the NBA id recorded in player_source_ids as the durable crosswalk.

The ESPN-only rows (329 on prod) are current players; binding their NBA id here is the
"roster is the crosswalk" rule: their squad identifies them better than their name.

SEASON: nba.com also publishes a bare SEASON "2026", the START year. Only SEASON_YEAR
"2026-27" is used, through season_keys (ESPN keys NBA by the end year).

Free-provider policy: one request a second, a real ceiling of 40 per run (30 are needed),
three consecutive refusals stop the run, and the run prints what it spent. Dry run by
default; --apply is required to write. Not in the scheduled registry until DEV and prod pass.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from typing import Mapping, Sequence

import paced_http

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_league_stats import _identity_name_key  # noqa: E402
from roster_membership import (  # noqa: E402
    normalized_source_payload,
    publish_roster_snapshot,
    require_roster_schema,
)
from season_keys import normalize_season  # noqa: E402
from team_codes import UnknownTeamCode, normalize  # noqa: E402

DB = os.environ.get("LP_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"
)
SOURCE = "nba.com"
SNAPSHOT_SOURCE = "nba.com:team-roster"
EXPECTED_TEAMS = 30
# The NBA's 30 franchise ids. Each page is checked to echo its own TEAM_ID back, so a
# moved or retired id fails loudly instead of silently dropping a team.
TEAM_IDS = tuple(range(1610612737, 1610612767))
TEAM_URL = "https://www.nba.com/team/{team_id}"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)

_FETCH = paced_http.Fetcher(
    min_interval=float(os.environ.get("LP_NBA_MIN_INTERVAL", "1.0")),
    retry_waits=(5.0, 20.0),
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"},
    timeout=30,
    host_budget=40,
)


# Birth date is the tie-breaker of last resort, read ONLY from a reviewed file: no live call to
# any other publisher. We store no birth dates, so a sole name candidate that team, transfer and
# move-date evidence cannot bind is checked by a human (nba.com's BIRTH_DATE against the person
# our row already is) and recorded there with provenance. Anything not in the file stays a
# failure and blocks the publish.
REVIEWED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "nba-identity-reviewed.json")


def _reviewed_birth_dates(path: str = REVIEWED_PATH) -> dict[str, dt.date]:
    """Reviewed birth dates keyed by the id our player row carries (espn_id or legacy nba_id)."""
    try:
        with open(path) as fh:
            entries = json.load(fh).get("nba") or {}
    except FileNotFoundError:
        return {}
    return {str(e["espn_id"]): dt.date.fromisoformat(e["espn_birth_date"]) for e in entries.values()}


def reviewed_birth_date(row_id) -> dt.date | None:
    return _reviewed_birth_dates().get(str(int(row_id)))


def nba_birth_date(value) -> dt.date | None:
    """nba.com publishes 'NOV 27, 1999'."""
    try:
        return dt.datetime.strptime(str(value or "").strip().title(), "%b %d, %Y").date()
    except ValueError:
        return None


class NBARosterError(RuntimeError):
    """The NBA roster population cannot be safely published."""


def _team_page(team_id: int) -> dict:
    body = _FETCH.fetch_text(TEAM_URL.format(team_id=team_id))
    match = _NEXT_DATA.search(body or "")
    if not match:
        raise NBARosterError(f"team {team_id}: page carries no __NEXT_DATA__")
    team = (json.loads(match.group(1)).get("props", {}).get("pageProps", {}) or {}).get("team")
    if not isinstance(team, dict):
        raise NBARosterError(f"team {team_id}: page carries no team object")
    return team


def season_from_span(span: str) -> int:
    """'2026-27' -> 2027, through season_keys, refusing anything but consecutive years."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(span or "").strip())
    if not match:
        raise NBARosterError(f"SEASON_YEAR {span!r} is not a YYYY-YY span")
    start = int(match.group(1))
    end = start // 100 * 100 + int(match.group(2))
    if end < start:          # 1999-00
        end += 100
    return normalize_season(SOURCE, "nba", f"{start}{end}")


def _position(value) -> str | None:
    text = str(value or "").strip().upper()
    return text or None


def fetch_population(fetch_page=_team_page) -> tuple[int, dict[str, list[dict]], dict]:
    """Every team's roster, validated, plus a spend report. Raises before any write."""
    rosters: dict[str, list[dict]] = {}
    seasons = set()
    spent = refused = consecutive = 0
    for team_id in TEAM_IDS:
        try:
            team = fetch_page(team_id)
            spent += 1
            consecutive = 0
        except Exception as exc:  # noqa: BLE001 -- counted, then fatal; never swallowed
            spent += 1
            refused += 1
            consecutive += 1
            if consecutive >= 3:
                raise NBARosterError(
                    f"three consecutive refusals from www.nba.com (last: team {team_id}: {exc}); "
                    f"stopped after {spent} requests") from exc
            raise NBARosterError(f"team {team_id} failed: {exc}") from exc
        info = team.get("info") or {}
        if int(info.get("TEAM_ID") or 0) != team_id:
            raise NBARosterError(f"team {team_id}: page reports TEAM_ID {info.get('TEAM_ID')!r}")
        try:
            code = normalize("nba", str(info.get("TEAM_ABBREVIATION") or ""))
        except UnknownTeamCode as exc:
            raise NBARosterError(f"team {team_id}: {exc}") from exc
        if code in rosters:
            raise NBARosterError(f"team code {code} published twice")
        seasons.add(season_from_span(info.get("SEASON_YEAR")))
        members = []
        seen = set()
        for row in team.get("roster") or []:
            pid = str(row.get("PLAYER_ID") or "").strip()
            name = str(row.get("PLAYER") or "").strip()
            if not pid.isdigit() or not name:
                raise NBARosterError(f"{code}: roster row without a player id or name: {row}")
            if pid in seen:
                raise NBARosterError(f"{code}: player {pid} listed twice")
            seen.add(pid)
            members.append({
                "player_id": pid, "name": name, "position": _position(row.get("POSITION")),
                "jersey": str(row.get("NUM") or "").strip() or None,
                "how_acquired": str(row.get("HOW_ACQUIRED") or "").strip() or None,
                "birth_date": row.get("BIRTH_DATE"),
            })
        if not members:
            raise NBARosterError(f"{code} published an empty roster")
        rosters[code] = members
    if len(rosters) != EXPECTED_TEAMS:
        raise NBARosterError(f"{len(rosters)} teams published; expected {EXPECTED_TEAMS}")
    if len(seasons) != 1:
        raise NBARosterError(f"teams disagree on the season: {sorted(seasons)}")
    return seasons.pop(), rosters, {"host": "www.nba.com", "requests": spent, "refused": refused}


_ACQUIRED_FROM = re.compile(r"\bfrom\s+([A-Z]{2,4})\b")


def acquired_from(how: str | None) -> str | None:
    """'Traded from DET on 07/07/25' -> 'DET' (normalized), else None."""
    match = _ACQUIRED_FROM.search(how or "")
    if not match:
        return None
    try:
        return normalize("nba", match.group(1))
    except UnknownTeamCode:
        return None


_MOVE_DATE = re.compile(r"\bon\s+(\d{2})/(\d{2})/(\d{2})\b")


def move_date(how: str | None) -> dt.date | None:
    """'Signed on 09/08/26' -> 2026-09-08. The publisher's dated transaction, else None."""
    match = _MOVE_DATE.search(how or "")
    if not match:
        return None
    month, day, year = (int(g) for g in match.groups())
    try:
        return dt.date(2000 + year, month, day)
    except ValueError:
        return None


def _normal_team(value) -> str | None:
    try:
        return normalize("nba", str(value or "")) if value else None
    except UnknownTeamCode:
        return None


def _choose_unbound_candidate(candidates, member: Mapping[str, object], bound=frozenset(),
                              known_since: dt.date | None = None, birth_date_of=None,
                              last_logged_team=None):
    """Bind a name-only candidate only with team or acquired-from evidence.

    `bound` holds player ids already crosswalked to some OTHER nba.com id: a same-name row
    already tied to a different NBA person is a different person.
    """
    unbound = [row for row in candidates if int(row["id"]) not in bound]
    if not unbound:
        # A same-name row with a DIFFERENT NBA id is a different person.
        return None, "insert"
    team = str(member["team"])
    same_team = [row for row in unbound if _normal_team(row["team"]) == team]
    if len(same_team) == 1:
        return same_team[0], "matched_team"
    previous = acquired_from(member.get("how_acquired"))
    if previous:
        moved = [row for row in unbound if _normal_team(row["team"]) == previous]
        if len(moved) == 1:
            return moved[0], "matched_acquired_from"
    # The publisher dates every move. A signing or trade AFTER the last roster we hold explains
    # exactly why our stored team differs, so a sole candidate of that name is the same person
    # who moved. A move dated BEFORE our snapshot does not explain the disagreement: our record
    # and the league's then genuinely conflict, and that stays a failure.
    moved_on = move_date(member.get("how_acquired"))
    if len(unbound) == 1 and known_since and moved_on and moved_on >= known_since:
        return unbound[0], "matched_moved_since_snapshot"
    # Our own published game logs: the sole candidate last appeared for the team nba.com lists.
    # Measured 2026-10-03 on PROD: Bradley Beal's row still read WSH (inactive, in no roster
    # snapshot) while its 2025-26 logs are six LAC games, and nba.com lists him LAC, "Signed on
    # 07/18/25". A move before our snapshot, so the tier above rightly declined it.
    if len(unbound) == 1 and last_logged_team is not None:
        logged = last_logged_team(unbound[0]["id"]) if "id" in unbound[0].keys() else None
        if logged and _normal_team(logged) == team:
            return unbound[0], "matched_last_logged_team"
    # Last resort, still evidence: the sole candidate's reviewed birth date equals nba.com's,
    # looked up by whichever id our row holds (players.nba_id is hoopR's ESPN athlete id).
    # Measured 2026-10-02: seven offseason signings ESPN's 08-04 roster still showed on their
    # old teams all matched to the day.
    theirs = nba_birth_date(member.get("birth_date"))
    if len(unbound) == 1 and theirs and birth_date_of is not None:
        row = unbound[0]
        espn_id = row["espn_id"] if "espn_id" in row.keys() and row["espn_id"] else (
            row["nba_id"] if "nba_id" in row.keys() else None)
        if espn_id and birth_date_of(espn_id) == theirs:
            return row, "matched_birth_date"
    return None, "ambiguous_name" if len(unbound) > 1 else "unverified_name"


def plan_population(connection: sqlite3.Connection,
                    rosters: Mapping[str, Sequence[Mapping[str, object]]],
                    birth_date_of=reviewed_birth_date) -> dict:
    """Plan every source identity without mutating the database."""
    connection.row_factory = sqlite3.Row
    require_roster_schema(connection)
    tables = {str(r[0]) for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "player_source_ids" not in tables:
        raise NBARosterError("player_source_ids is required")
    columns = {str(r[1]) for r in connection.execute("PRAGMA table_info(players)")}
    entity_scope = "COALESCE(entity_type,'player')='player'" if "entity_type" in columns else "1=1"

    players = {}
    by_name: dict[str, list] = collections.defaultdict(list)
    import name_aliases
    for row in connection.execute(
            f"SELECT id,name,team,position,espn_id,nba_id FROM players WHERE league='nba' AND {entity_scope}"):
        players[int(row["id"])] = row
        keys = {_identity_name_key(row["name"])}
        # Reviewed alternate names (data/name-aliases.json, keyed by ESPN id) widen who can be a
        # CANDIDATE; binding still needs evidence. Our "Kenyon Martin Jr." is nba.com's and
        # ESPN's "KJ Martin": without this he would have been minted a second time.
        for ext in {row["espn_id"], row["nba_id"]} - {None}:
            keys |= {_identity_name_key(a) for a in name_aliases.aliases_for("nba", ext)}
        for key in keys:
            by_name[key].append(row)
    durable = {str(r["source_player_key"]): int(r["player_id"]) for r in connection.execute(
        "SELECT source_player_key,player_id FROM player_source_ids WHERE source=? AND league='nba'",
        (SOURCE,))}
    # The date our newest held NBA roster was captured: the line a dated move must cross.
    last = connection.execute(
        "SELECT MAX(captured_at) FROM roster_snapshots WHERE league='nba' AND status='published'"
    ).fetchone()[0]
    known_since = dt.date.fromisoformat(str(last)[:10]) if last else None

    def last_logged_team(player_id):
        row = connection.execute(
            "SELECT team FROM player_game_logs WHERE player_id=? AND team IS NOT NULL "
            "ORDER BY game_date DESC LIMIT 1", (player_id,)).fetchone()
        return row[0] if row else None
    by_source: dict[str, list] = collections.defaultdict(list)
    for key, player_id in durable.items():
        if player_id in players:
            by_source[key].append(players[player_id])

    planned, failures, counts = [], [], collections.Counter()
    for team in sorted(rosters):
        for raw in rosters[team]:
            member = {**raw, "team": team}
            source_key = str(member["player_id"])
            exact = by_source.get(source_key, [])
            if len(exact) > 1:
                failures.append({**member, "reason": "duplicate_nba_com_crosswalk"})
                continue
            if exact:
                candidate, action = exact[0], "exact_id"
            else:
                bound_elsewhere = frozenset(pid for key, pid in durable.items() if key != source_key)
                candidate, action = _choose_unbound_candidate(
                    by_name.get(_identity_name_key(member["name"]), []), member, bound_elsewhere,
                    known_since, birth_date_of, last_logged_team)
                if action in ("ambiguous_name", "unverified_name"):
                    failures.append({**member, "reason": action})
                    continue
            if candidate is not None:
                owner = durable.get(source_key)
                if owner is not None and owner != int(candidate["id"]):
                    failures.append({**member, "reason": "source_crosswalk_conflict",
                                     "existing_player_id": owner, "planned_player_id": int(candidate["id"])})
                    continue
                player_id, write_action = int(candidate["id"]), "update"
            else:
                if source_key in durable:
                    failures.append({**member, "reason": "stranded_source_crosswalk",
                                     "existing_player_id": durable[source_key]})
                    continue
                player_id, write_action = None, "insert"
            counts[action] += 1
            planned.append({**member, "source_player_key": source_key,
                            "canonical_player_id": player_id, "write_action": write_action,
                            "evidence": action})
    return {"planned": planned, "failures": failures, "counts": dict(sorted(counts.items()))}


def publish_population(connection: sqlite3.Connection, *, season: int,
                       rosters: Mapping[str, Sequence[Mapping[str, object]]],
                       captured_at: str, apply: bool) -> dict:
    """Plan, then atomically publish a complete NBA roster snapshot."""
    if len(rosters) != EXPECTED_TEAMS or any(not rows for rows in rosters.values()):
        raise NBARosterError(f"roster population has {len(rosters)} teams; "
                             f"expected {EXPECTED_TEAMS} non-empty teams")
    plan = plan_population(connection, rosters)
    plan.update(teams=len(rosters), players=sum(len(r) for r in rosters.values()), season=season)
    plan["status"] = "identity_incomplete" if plan["failures"] else "ready"
    if plan["failures"] or not apply:
        return plan

    source_payload = normalized_source_payload("nba", rosters)
    try:
        connection.execute("BEGIN IMMEDIATE")
        columns = {str(r[1]) for r in connection.execute("PRAGMA table_info(players)")}
        entity_scope = "COALESCE(entity_type,'player')='player'" if "entity_type" in columns else "1=1"
        connection.execute(f"UPDATE players SET active=0,updated_at=? WHERE league='nba' AND {entity_scope}",
                           (captured_at,))
        memberships = []
        for item in plan["planned"]:
            if item["write_action"] == "insert":
                cursor = connection.execute(
                    "INSERT INTO players(name,league,team,position,active,updated_at) "
                    "VALUES(?,'nba',?,?,1,?)",
                    (item["name"], item["team"], item["position"], captured_at))
                player_id = int(cursor.lastrowid)
            else:
                player_id = int(item["canonical_player_id"])
                # Position stays as stored when nba.com omits it; the spine keeps one vocabulary
                # per column until the position normalization pass (DATA-SPINE.md) lands.
                connection.execute(
                    "UPDATE players SET team=?,active=1,updated_at=?,position=COALESCE(position,?) "
                    "WHERE id=? AND league='nba'",
                    (item["team"], captured_at, item["position"], player_id))
            existing = connection.execute(
                "SELECT player_id FROM player_source_ids WHERE source=? AND league='nba' AND source_player_key=?",
                (SOURCE, item["source_player_key"])).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO player_source_ids(source,league,source_player_key,player_id,first_seen,last_seen) "
                    "VALUES(?,'nba',?,?,?,?)",
                    (SOURCE, item["source_player_key"], player_id, captured_at, captured_at))
            elif int(existing[0]) == player_id:
                connection.execute(
                    "UPDATE player_source_ids SET last_seen=? WHERE source=? AND league='nba' AND source_player_key=?",
                    (captured_at, SOURCE, item["source_player_key"]))
            else:  # defensive repeat of the planner's refusal
                raise NBARosterError(f"NBA id {item['source_player_key']} changed owner")
            item["canonical_player_id"] = player_id
            memberships.append({
                "player_id": player_id, "source_player_key": item["source_player_key"],
                "team": item["team"], "position": item["position"], "jersey": item.get("jersey"),
                "roster_status": "active", "display_name": item["name"],
            })
        snapshot_id = publish_roster_snapshot(
            connection, league="nba", season=season, source=SNAPSHOT_SOURCE,
            captured_at=captured_at, source_payload=source_payload,
            team_count=EXPECTED_TEAMS, memberships=memberships)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    plan.update(status="published", snapshot_id=snapshot_id)
    return plan


def refresh(db_path: str, *, apply: bool = False) -> dict:
    season, rosters, spend = fetch_population()
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    connection = sqlite3.connect(db_path, timeout=60)
    connection.row_factory = sqlite3.Row
    try:
        result = publish_population(connection, season=season, rosters=rosters,
                                    captured_at=captured_at, apply=apply)
    finally:
        connection.close()
    result["spend"] = [spend]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = refresh(os.path.abspath(args.db), apply=args.apply)
    print(json.dumps({k: v for k, v in result.items() if k != "planned"}, indent=2, sort_keys=True,
                     default=str))
    if not args.apply:
        print("DRY RUN -- nothing written. Re-run with --apply.")
    return 2 if result["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
