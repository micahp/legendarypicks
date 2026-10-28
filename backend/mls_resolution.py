"""Membership-gated identity resolution for MLS, and for Leagues Cup through its home person.

Every answer comes from ONE piece of evidence: the membership snapshot that covers the date. Current answers use the
latest published snapshot. Historical answers use the newest snapshot captured on or before the date. Nothing here reads
an observation row (published_roster): a stale row can no longer propose a person. When no snapshot covers the date, the
answer is NONE. A historical club is never invented.

The snapshot stores, for each member, the publisher keys that identify them, the club, and the publisher's own name
spelling. Name matching therefore uses the spellings the snapshot itself holds.

The gate is off until the cutover is authorized. Production keeps the legacy resolver until CUTOVER_ENABLED is set.
"""
import datetime as dt
import json

import published_roster

CUTOVER_ENABLED = False
LEAGUE = "mls"
NO_MATCH = (None, None)


def _day(as_of):
    if as_of is None:
        return None
    if isinstance(as_of, dt.datetime):
        as_of = as_of.date()
    if isinstance(as_of, dt.date):
        return as_of.isoformat()
    return str(as_of)[:10]


def _snapshot(con, as_of=None):
    """(snapshot_id, payload dict) for the snapshot that answers this date, or None."""
    day = _day(as_of)
    if day is None:
        row = con.execute("SELECT id, source_payload FROM roster_snapshots WHERE league=? AND status='published'",
                          (LEAGUE,)).fetchone()
    else:
        row = con.execute(
            "SELECT id, source_payload FROM roster_snapshots WHERE league=? AND substr(captured_at,1,10) <= ? "
            "ORDER BY captured_at DESC, id DESC LIMIT 1", (LEAGUE, day)).fetchone()
    if row is None:
        return None
    return int(row[0]), json.loads(row[1])


def membership_evidence(con, as_of=None):
    """{player_id: evidence} for the snapshot that answers this date, or None when no snapshot covers it.

    Each evidence record holds: keys (publisher -> key), team (the club), name (the publisher's spelling), position,
    and roster_status ("active", "carried" or "held").
    """
    found = _snapshot(con, as_of)
    if found is None:
        return None
    _sid, payload = found
    out = {}
    for m in payload.get("memberships", []):
        out[int(m["player_id"])] = {"keys": dict(m.get("keys") or {}), "team": m["team"],
                                    "name": m.get("display_name") or "", "position": m.get("position"),
                                    "roster_status": m.get("roster_status", "active")}
    return out


def evidence_match(record, position_group=""):
    """(source, key, position, group, published_name) for a member's snapshot record, preferring the MLS key.

    The same shape published_roster.lookup returns, so callers switch sources without changing their logic.
    """
    if record is None or not record["keys"]:
        return None
    source = "mlssoccer" if "mlssoccer" in record["keys"] else sorted(record["keys"])[0]
    return (source, str(record["keys"][source]), record["position"] or "", position_group or "", record["name"])


def members_as_of(con, as_of=None):
    """{player_id: {"team": club, "status": roster_status}} for the snapshot that answers this date, or None.

    None means no snapshot covers the date. Callers must treat that as "not a current or known member".
    """
    evidence = membership_evidence(con, as_of)
    if evidence is None:
        return None
    return {pid: {"team": ev["team"], "status": ev["roster_status"]} for pid, ev in evidence.items()}


def current_team(con, player_id):
    """The club a person is on now, from the latest snapshot. Never players.team or a publisher row."""
    members = members_as_of(con)
    if members is None or player_id not in members:
        return None
    return members[player_id]["team"]


def club_now_sql(player_id, league, legacy, mls_missing, upcoming=None):
    """SQL for the club a player is on now, for display and attribution.

    With the cutover off, returns `legacy` unchanged, so production's SQL does not change. With it on, an MLS player
    in the latest snapshot gets that membership's club. An MLS player who is not a current member gets `mls_missing`
    (never the stale stored club). `upcoming` limits the membership answer to rows where it is true; other rows keep
    `legacy`, so past games still show the club they played for.
    """
    if not CUTOVER_ENABLED:
        return legacy
    current = ("{lg} = 'mls' AND EXISTS (SELECT 1 FROM roster_snapshots cs WHERE cs.league = 'mls' "
               "AND cs.status = 'published')").format(lg=league)
    if upcoming:
        current += " AND ({})".format(upcoming)
    member = ("(SELECT cm.team FROM roster_memberships cm JOIN roster_snapshots cs2 ON cs2.id = cm.snapshot_id "
              "WHERE cm.player_id = {pid} AND cs2.league = 'mls' AND cs2.status = 'published')").format(pid=player_id)
    return "(CASE WHEN {cur} THEN COALESCE({m}, {miss}) ELSE {leg} END)".format(
        cur=current, m=member, miss=mls_missing, leg=legacy)


def _is_mls_player(con, player_id):
    row = con.execute("SELECT league FROM players WHERE id=?", (player_id,)).fetchone()
    return row is not None and row[0] == LEAGUE


def resolve(con, name, team, league, as_of, legacy):
    """Resolve a name to (player_id, confidence), or (None, None). Only called when CUTOVER_ENABLED."""
    evidence = membership_evidence(con, as_of)
    if evidence is None:
        return NO_MATCH
    members = {pid: {"team": ev["team"]} for pid, ev in evidence.items()}
    if league == "lcup":
        result = legacy(con, name, team, league)
        pid = result[0]
        if pid is None:
            return NO_MATCH
        if _is_mls_player(con, pid) and pid not in members:
            return NO_MATCH  # the home MLS person has left the club: not a Leagues Cup candidate either
        return result
    if league != LEAGUE:
        return legacy(con, name, team, league)

    from _core import _folded_name_index, _normalize_name, _pick_one

    nname = _normalize_name(name)
    nteam = team.strip().upper() if team else ""

    def row(pid):
        return {"id": pid, "team": members[pid]["team"]}

    # 1. Exact name.
    rows = [row(pid) for (pid,) in con.execute(
        "SELECT id FROM players WHERE name=? AND league=?", (name, LEAGUE)) if pid in members]
    picked = _pick_one(rows, nteam, set(), False) if rows else None
    if picked is not None:
        return (picked, "high")

    # 2. Normalized name, at the club the person is on now.
    if nteam:
        cands = [row(pid) for (pid,) in con.execute(
            "SELECT id FROM players WHERE LOWER(REPLACE(name,'.','')) LIKE ? AND league=?",
            ("%{}%".format(nname.replace(" ", "%")), LEAGUE)) if pid in members]
        cands = [c for c in cands if c["team"].strip().upper() == nteam]
        if len(cands) == 1:
            return (cands[0]["id"], "high")

    # 2b. Folded name on both sides.
    rows = [row(r["id"]) for r in _folded_name_index(con, LEAGUE).get(nname, []) if r["id"] in members]
    picked = _pick_one(rows, nteam, set(), False) if rows else None
    if picked is not None:
        return (picked, "high")

    # 3. Reviewed alias. Accepted only for a current member.
    alias = con.execute("SELECT player_id FROM name_alias WHERE alias_norm=?", (nname,)).fetchone()
    if alias and alias[0] in members and _is_mls_player(con, alias[0]):
        return (alias[0], "high")

    # 4. The publisher's own spelling, as the snapshot holds it, for current members only.
    folded = published_roster.fold(name)
    pids = {pid for pid, ev in evidence.items() if published_roster.fold(ev["name"]) == folded}
    if len(pids) == 1:
        return (pids.pop(), "high")
    return NO_MATCH
