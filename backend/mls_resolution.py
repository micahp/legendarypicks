"""Membership-gated identity resolution for MLS, and for Leagues Cup through its home person.

Every resolver path answers the same question: is this person on the club, as of this date? Current answers come from
the latest published snapshot. Historical answers come from the newest snapshot captured on or before the date. When no
snapshot covers the date, the answer is NONE. A historical club is never invented.

The gate is off until the cutover is authorized. Production calls the legacy resolver until CUTOVER_ENABLED is set.
"""
import datetime as dt

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


def members_as_of(con, as_of=None):
    """{player_id: {"team": club, "status": roster_status}} for the snapshot that answers this date, or None.

    None means no snapshot covers the date. Callers must treat that as "not a current or known member".
    """
    day = _day(as_of)
    if day is None:
        row = con.execute("SELECT id FROM roster_snapshots WHERE league=? AND status='published'",
                          (LEAGUE,)).fetchone()
    else:
        row = con.execute(
            "SELECT id FROM roster_snapshots WHERE league=? AND substr(captured_at,1,10) <= ? "
            "ORDER BY captured_at DESC, id DESC LIMIT 1", (LEAGUE, day)).fetchone()
    if row is None:
        return None
    return {int(pid): {"team": team, "status": status} for pid, team, status in con.execute(
        "SELECT player_id, team, roster_status FROM roster_memberships WHERE snapshot_id=?", (row[0],))}


def current_team(con, player_id):
    """The club a person is on now, from the latest snapshot. Never players.team or a publisher row."""
    members = members_as_of(con)
    if members is None or player_id not in members:
        return None
    return members[player_id]["team"]


def _is_mls_player(con, player_id):
    row = con.execute("SELECT league FROM players WHERE id=?", (player_id,)).fetchone()
    return row is not None and row[0] == LEAGUE


def resolve(con, name, team, league, as_of, legacy):
    """Resolve a name to (player_id, confidence), or (None, None). Only called when CUTOVER_ENABLED."""
    members = members_as_of(con, as_of)
    if members is None:
        return NO_MATCH
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

    # 3. Reviewed alias.
    alias = con.execute("SELECT player_id FROM name_alias WHERE alias_norm=?", (nname,)).fetchone()
    if alias and alias[0] in members and _is_mls_player(con, alias[0]):
        return (alias[0], "high")

    # 4. The publisher's roster names, read from the stored table, and only people on the club.
    folded = published_roster.fold(name)
    pids = {int(pid) for (pid,) in con.execute(
        "SELECT DISTINCT r.player_id FROM published_roster r WHERE r.league=? AND r.player_id IS NOT NULL "
        "AND (r.name_folded=? OR EXISTS (SELECT 1 FROM published_roster_name n WHERE n.league=r.league "
        "AND n.source=r.source AND n.source_player_key=r.source_player_key AND n.name_folded=?))",
        (LEAGUE, folded, folded))}
    pids = {pid for pid in pids if pid in members}
    if len(pids) == 1:
        return (pids.pop(), "high")
    return NO_MATCH
