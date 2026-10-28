"""Identity onboarding for MLS: when a publisher key may create a person, bind a key, or wait in the queue.

Fixed rules (the cutover contract):
- A permanent source-ID bind identifies a person. Name and club never justify a merge or a bind on their own.
- A NEW person is created only when both publishers list the same name at the same club, no existing MLS player
  has that name, and both publishers' dates of birth agree on at least one date. Everything else is queued.
- A key that belongs to a person already known through another key is a REKEY. It is bound only when the dates of
  birth agree, otherwise it is queued and the person stays current through the other key, flagged.
- Onboarding writes only players, player_source_ids, identity_evidence and identity_onboarding_queue.
  It never changes a historical game log, prop, settlement, or team game result.
"""
import datetime as dt

from published_roster import fold

LEAGUE = "mls"
SOURCES = ("mlssoccer", "fotmob")
BIND_LEAGUES = ("mls", "lcup")


def ensure_schema(con):
    con.execute("""CREATE TABLE IF NOT EXISTS identity_evidence(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id INTEGER NOT NULL,
        source TEXT NOT NULL,
        source_player_key TEXT NOT NULL,
        field TEXT NOT NULL,
        value TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        UNIQUE(player_id, source, source_player_key, field))""")
    con.execute("""CREATE TABLE IF NOT EXISTS identity_onboarding_queue(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        league TEXT NOT NULL,
        source TEXT NOT NULL,
        source_player_key TEXT NOT NULL,
        name TEXT,
        team TEXT,
        reason TEXT NOT NULL,
        player_id INTEGER,
        status TEXT NOT NULL DEFAULT 'open',
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        UNIQUE(league, source, source_player_key))""")


def _queue(con, source, key, name, team, reason, player_id, now):
    con.execute("""INSERT INTO identity_onboarding_queue(league, source, source_player_key, name, team, reason,
            player_id, status, first_seen, last_seen) VALUES(?,?,?,?,?,?,?,'open',?,?)
        ON CONFLICT(league, source, source_player_key) DO UPDATE SET reason=excluded.reason,
            name=excluded.name, team=excluded.team, player_id=excluded.player_id, status='open',
            last_seen=excluded.last_seen""",
                (LEAGUE, source, key, name, team, reason, player_id, now, now))


def _bind(con, source, key, player_id, now):
    con.execute("INSERT INTO player_source_ids(source, league, source_player_key, player_id, first_seen, last_seen) "
                "VALUES(?,?,?,?,?,?)", (source, LEAGUE, key, player_id, now, now))


def _evidence(con, player_id, source, key, dob, now):
    con.execute("INSERT INTO identity_evidence(player_id, source, source_player_key, field, value, observed_at) "
                "VALUES(?,?,?,'dob',?,?) ON CONFLICT(player_id, source, source_player_key, field) "
                "DO UPDATE SET value=excluded.value, observed_at=excluded.observed_at",
                (player_id, source, key, dob, now))


def _dates(lookup, source, key):
    """Dates of birth the publisher reports for this key, as ISO strings. A failed or missing lookup is none."""
    if lookup is None:
        return []
    try:
        found = lookup(source, key)
    except Exception:  # an unreachable publisher corroborates nothing; the key is queued, never guessed
        return []
    return sorted({str(d) for d in (found or []) if d})


def corroborated_dob(first, second):
    """(date, reason). A date of birth is accepted only when each publisher gives exactly one reading and the two agree.

    One publisher with two readings is not one interpretation. An MLS page whose day and month can be read either way
    gives two dates, and nothing here chooses between them. Two single readings that differ are a conflict. In every
    case where the rule does not accept, nothing is written, and the identity goes to review.
    """
    if not first or not second:
        return None, "dob_missing"
    if len(first) > 1 or len(second) > 1:
        return None, "dob_ambiguous"
    if first != second:
        return None, "dob_not_corroborated"
    return first[0], None


def _player_names(con):
    """Folded name -> [player ids] for every MLS player."""
    names = {}
    for pid, name in con.execute("SELECT id, name FROM players WHERE league=?", (LEAGUE,)):
        names.setdefault(fold(name), []).append(pid)
    return names


def _mls_keys(con):
    """player_id -> {source: key} for MLS binds only."""
    keys = {}
    for source, key, pid in con.execute(
            "SELECT source, source_player_key, player_id FROM player_source_ids WHERE league=?", (LEAGUE,)):
        keys.setdefault(pid, {})[source] = str(key)
    return keys


def onboard(con, squads, lookup, now):
    """Decide every unbound publisher key in these squads. Returns what was created, rekeyed and queued."""
    out = {"created": [], "rekeyed": [], "queued": []}
    bound = {(s, str(k)) for s, k in con.execute(
        "SELECT source, source_player_key FROM player_source_ids WHERE league IN (?,?)", BIND_LEAGUES)}
    members = {}  # (source, key) -> squad row, for keys in these squads
    for src in SOURCES:
        for m in squads.get(src) or []:
            members[(src, str(m["source_player_key"]))] = m
    unbound = [m for (src, key), m in sorted(members.items()) if (src, key) not in bound]
    if not unbound:
        _resolve_queue(con)
        return out

    squad_keys = set(members)
    names = _player_names(con)
    mls_keys = _mls_keys(con)
    remaining = []

    # 1. Rekeys: a new key whose person is still current through another key, and who has lost this publisher's key.
    for m in unbound:
        src, key = m["source"], str(m["source_player_key"])
        f = fold(m["name"])
        candidates = []
        for pid in names.get(f, ()):
            keys = mls_keys.get(pid, {})
            other = [(s, k) for s, k in keys.items() if s != src and (s, k) in squad_keys]
            lost_here = src not in keys or (src, keys[src]) not in squad_keys
            if other and lost_here and members[other[0]]["team"] == m["team"]:
                candidates.append((pid, other[0]))
        if len(candidates) > 1:
            _queue(con, src, key, m["name"], m["team"], "ambiguous_rekey", None, now)
            out["queued"].append({"source": src, "source_player_key": key, "reason": "ambiguous_rekey"})
            continue
        if not candidates:
            remaining.append(m)
            continue
        pid, (osrc, okey) = candidates[0]
        mine = _dates(lookup, src, key)
        theirs = _dates(lookup, osrc, okey)
        dob, _reason = corroborated_dob(mine, theirs)
        if dob is not None:
            _bind(con, src, key, pid, now)
            _evidence(con, pid, src, key, dob, now)
            out["rekeyed"].append({"player_id": pid, "source": src, "from": None, "to": key})
        else:
            _queue(con, src, key, m["name"], m["team"], "rekey_unverified", pid, now)
            out["queued"].append({"source": src, "source_player_key": key, "reason": "rekey_unverified",
                                  "player_id": pid})

    # 2. New people: the same name at the same club from both publishers, with corroborated dates of birth.
    groups = {}
    for m in remaining:
        groups.setdefault((fold(m["name"]), m["team"]), []).append(m)
    for (f, team), rows in sorted(groups.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        sources = sorted(r["source"] for r in rows)
        if len(rows) == 1:
            _queue(con, rows[0]["source"], str(rows[0]["source_player_key"]), rows[0]["name"], team,
                   "single_source_unverified", None, now)
            out["queued"].append({"source": rows[0]["source"], "source_player_key": str(rows[0]["source_player_key"]),
                                  "reason": "single_source_unverified"})
            continue
        if len(rows) != 2 or sources != sorted(SOURCES):
            for r in rows:
                _queue(con, r["source"], str(r["source_player_key"]), r["name"], team, "ambiguous_group", None, now)
                out["queued"].append({"source": r["source"], "source_player_key": str(r["source_player_key"]),
                                      "reason": "ambiguous_group"})
            continue
        if names.get(f):
            reason = "namesake_exists"
        else:
            reason = None
        pair = {r["source"]: r for r in rows}
        keys = {s: str(pair[s]["source_player_key"]) for s in SOURCES}
        if reason is None:
            dates = {s: _dates(lookup, s, keys[s]) for s in SOURCES}
            dob, reason = corroborated_dob(dates["mlssoccer"], dates["fotmob"])
        if reason is not None:
            for s in SOURCES:
                _queue(con, s, keys[s], pair[s]["name"], team, reason, None, now)
                out["queued"].append({"source": s, "source_player_key": keys[s], "reason": reason})
            continue
        cur = con.execute(
            "INSERT INTO players(name, team, league, position, position_group, active, updated_at) "
            "VALUES(?,?,?,?,?,1,?)",
            (pair["mlssoccer"]["name"], team, LEAGUE, pair["mlssoccer"].get("position"),
             pair["mlssoccer"].get("position_group"), now))
        pid = int(cur.lastrowid)
        for s in SOURCES:
            _bind(con, s, keys[s], pid, now)
            _evidence(con, pid, s, keys[s], dob, now)
        names.setdefault(f, []).append(pid)
        out["created"].append(pid)

    _resolve_queue(con)
    return out


def _resolve_queue(con):
    """A queued key that is now bound is no longer waiting. The row stays, marked resolved."""
    bound = {(s, str(k)) for s, k in con.execute(
        "SELECT source, source_player_key FROM player_source_ids WHERE league IN (?,?)", BIND_LEAGUES)}
    for row_id, source, key in con.execute(
            "SELECT id, source, source_player_key FROM identity_onboarding_queue WHERE league=? AND status='open'",
            (LEAGUE,)).fetchall():
        if (source, key) in bound:
            con.execute("UPDATE identity_onboarding_queue SET status='resolved' WHERE id=?", (row_id,))


# --- the production date-of-birth lookups --------------------------------------------

_SLUGS = {}


def default_lookup(source, key, on=None):
    """Dates of birth from the publishers, for onboarding. FotMob: one date. MLS: each reading its printed age fits.

    Reads the publisher's own public pages. Tests replace this with a fake; the decision logic does not change.
    """
    import identity_audit_mls as audit
    on = on or dt.date.today()
    if source == "fotmob":
        born, _note = audit.fotmob_dob(key)
        return [born.isoformat()] if born else []
    if not _SLUGS:
        _SLUGS.update(audit.mls_key_to_slug())
    slug = _SLUGS.get(key)
    if slug is None:
        return []
    page = audit.mls_page(slug)
    if not page:
        return []
    found = []
    for month, day in ((page["first"], page["second"]), (page["second"], page["first"])):
        try:
            born = dt.date(page["year"], month, day)
        except ValueError:
            continue
        age = on.year - born.year - ((on.month, on.day) < (born.month, born.day))
        if age in (page["shown_age"], page["shown_age"] - 1):
            found.append(born.isoformat())
    return sorted(set(found))
