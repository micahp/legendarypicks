#!/usr/bin/env python3
"""spine_merge.py -- one generic repair for a person recorded twice, any league.

Why generic. There are five one-off dedupers in this directory, each written for one
league during one incident, and every one of them silently orphans rows. Measured
2026-08-24 against the real schema:

  14 tables carry a player_id column
  5  of them declare a FOREIGN KEY, so 9 are unenforced and nothing raises
  dedupe_nfl.py           touches 3   (misses all EIGHT nfl_* tables)
  dedupe_mlb.py           touches 5
  merge_mls_prop_players.py touches 1

A hardcoded table list is wrong the day someone adds a table, and wrong quietly, because
an orphaned player_id is not an error anywhere -- the row just stops joining. So this
DISCOVERS the referencing columns from the schema every run: the foreign keys plus the
`*player_id` naming convention the unenforced tables follow. If a future table follows
neither, it will be missed, so `referencing_columns` is asserted against a known count in
the tests and that assertion is the thing that fails when the schema grows.

What it repairs. One league, one name, one row carrying a publisher id and one without.
That is a person recorded twice: the resolved row, and the row a name-keyed ingest minted
before anyone had an id for them. Prod held 547 such groups before any of today's work,
536 of them NFL.

A name is not the only way to find those two rows. When two rows in one league resolve to
the SAME published squad member -- `Willy Kumado` and `William Kumado` at San Diego, one
folded through a reviewed alias -- they are the same person on the publisher's own evidence,
and their names never match. That is STRICTER than name matching, not looser, so both
candidate sources feed the same keep/drop machinery below.

A publisher can also list one squad member twice. When its roster files two rows, or a row and an
unlinked key, under one folded name at one club, that is one person listed twice. It is found from
the roster, never from the name alone, and two rows with different ESPN, NBA, MLB, NHL or NFL ids are
two people whatever the roster says. An unlinked key is bound to a player only when that player
already holds a key from the same publisher.

What it refuses:
  - a name held by two rows that BOTH carry ids, unless the roster files both under that name at one
    club (two real players do share a name; NFL has 442 such groups and NCAAF 171, and they are the
    spine working)
  - a name held by more than one id-less row, or more than one id-carrying row, because
    which merges into which is then a guess
  - anything where the surviving row is not uniquely determined

Plan first, apply second, in one transaction, like every other ingest here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple
from nfl_identity import espn_assignment_conflict, load_espn_to_gsis

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    import published_roster
except ImportError:  # a database or checkout without it simply has no published rosters
    published_roster = None

_NO_MINT_LEAGUES = frozenset(getattr(published_roster, "NO_MINT_LEAGUES", ()))


def referencing_columns(con) -> List[Tuple[str, str]]:
    """Every (table, column) that holds a players.id, discovered from the schema.

    Two signals, unioned, because neither is sufficient: only 5 of the 14 tables declare
    the foreign key, and `nfl_adp` carries `espn_player_id` alongside `player_id`, which
    is NOT a players.id and must not be rewritten.
    """
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    found = []
    for table in tables:
        if table == "players":
            continue
        cols = {r[1] for r in con.execute("PRAGMA table_info('{}')".format(table))}
        by_fk = {r[3] for r in con.execute("PRAGMA foreign_key_list('{}')".format(table))
                 if r[2] == "players"}
        for col in sorted(cols):
            # `espn_player_id` holds a PUBLISHER's id, not ours. Rewriting it would
            # corrupt the very identity this repair exists to consolidate.
            if col in by_fk or (col == "player_id"):
                found.append((table, col))
    return sorted(found)


@dataclass
class Merge:
    league: str
    name: str
    keep_id: int
    drop_id: int
    keep_espn_id: str
    moved: Dict[str, int] = field(default_factory=dict)


@dataclass
class Bind:
    """A publisher key the rosters tie to a player, with no player_source_ids row naming it yet."""
    league: str
    source: str
    key: str
    player_id: int
    name: str


@dataclass
class MergePlan:
    merges: List[Merge] = field(default_factory=list)
    binds: List[Bind] = field(default_factory=list)
    refused: List[Tuple[str, str, str]] = field(default_factory=list)
    columns: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def mutations(self) -> int:
        return len(self.merges) + len(self.binds)


# The columns that hold a PUBLISHER's id for a player. `espn_id` is not special; it is simply
# the one this file happened to be written around. Widened 2026-09-06 because a row can be
# perfectly well resolved without ESPN ever having heard of it: `player_source_ids` already
# holds 1,470 rotowire, 131 underdog and 44 ufcstats bindings, and esports is 100% keyless by
# nature, so the old rule could never merge a cs2 or valorant duplicate at all.
_ID_COLUMNS = ("espn_id", "mlbam_id", "nfl_gsis_id", "nhl_id", "nba_id")


def _present_id_columns(con) -> Tuple[str, ...]:
    """Which publisher-id columns this database actually has.

    Discovered rather than assumed, for the same reason `referencing_columns` is: a database
    that predates a column, or a test fixture that only needs two of them, must not make the
    tool raise.
    """
    have = {row[1] for row in con.execute("PRAGMA table_info(players)")}
    return tuple(column for column in _ID_COLUMNS if column in have)


def publisher_identity(con, player_id: int, row=None):
    """A stable key naming this player at some publisher, or None.

    Any one of them is enough. Two rows are the same person when they share one, which is
    STRICTER than matching a name, not looser: a name is how 124 of 317 MLB "duplicate"
    groups turned out to be two different people.
    """
    if row is not None:
        for column in _ID_COLUMNS:
            value = (row[column] if column in row.keys() else None)
            if value is not None and str(value).strip():
                return "{}={}".format(column, str(value).strip())
    try:
        binding = con.execute(
            "SELECT source, source_player_key FROM player_source_ids WHERE player_id=? "
            "ORDER BY source, source_player_key LIMIT 1", (player_id,)).fetchone()
    except sqlite3.Error:
        return None  # a database without the table simply has no such bindings
    if binding:
        return "{}={}".format(binding[0], binding[1])
    return None


def _name_groups(con, league: Optional[str]) -> List[Tuple[str, str, List[int]]]:
    """(league, label, [player ids]) for every league+name held by more than one row."""
    where = "WHERE league = ?" if league else ""
    args: Sequence = (league,) if league else ()
    out = []
    for group in con.execute(
            "SELECT league, name, COUNT(*) n FROM players {} GROUP BY league, name "
            "HAVING n > 1".format(where), args).fetchall():
        ids = [r[0] for r in con.execute(
            "SELECT id FROM players WHERE league=? AND name=? ORDER BY id",
            (group["league"], group["name"]))]
        out.append((group["league"], group["name"], ids))
    return out


def _published_groups(con, league: Optional[str]) -> List[Tuple[str, str, List[int]]]:
    """The same thing, keyed on the published squad member two rows both resolve to.

    This is what finds a duplicate whose two names never match: `Willy Kumado` and
    `William Kumado` are one San Diego defender, and only the publisher can say so. It asks
    `published_roster.lookup`, so it inherits that module's fold, its uniqueness rule and its
    reviewed aliases rather than inventing a second opinion about who somebody is.
    """
    if published_roster is None:
        return []
    try:
        leagues = [league] if league else [
            r[0] for r in con.execute("SELECT DISTINCT league FROM published_roster")]
        columns = {row[1] for row in con.execute("PRAGMA table_info(players)")}
    except sqlite3.Error:
        return []  # no published roster here; the name-keyed pass is the whole plan
    if not {"team", "active"} <= columns:
        return []  # a schema this old cannot say who is on a squad today
    out = []
    for one in leagues:
        claims: Dict[Tuple[str, str], List[int]] = {}
        for row in con.execute(
                "SELECT id, name, team FROM players WHERE league=? AND active=1 ORDER BY id",
                (one,)).fetchall():
            match = published_roster.lookup(con, one, row["name"], row["team"])
            if match:
                claims.setdefault((match[0], match[1]), []).append(row["id"])
        for (source, key), ids in claims.items():
            if len(ids) > 1:
                out.append((one, "{}={}".format(source, key), ids))
    return out


def _roster_claims(con, league: Optional[str]) -> Dict[int, set]:
    """player id -> the (folded name, roster team) pairs the published rosters file under that player."""
    where = " AND league=?" if league else ""
    try:
        rows = con.execute(
            "SELECT player_id, name_folded, team FROM published_roster "
            "WHERE player_id IS NOT NULL" + where, (league,) if league else ()).fetchall()
    except sqlite3.Error:
        return {}  # a database without the published rosters has no roster evidence
    claims: Dict[int, set] = {}
    for row in rows:
        if row[2]:
            claims.setdefault(row[0], set()).add((row[1], row[2]))
    return claims


def _roster_clubs(con, league: Optional[str]) -> Dict[int, set]:
    """player id -> the club names and codes the published rosters file under that player.

    players.team holds a code (RBNY) and the rosters hold the full name (Red Bull New York), so a
    row is on its roster's club when its own team matches either.
    """
    where = " AND league=?" if league else ""
    try:
        rows = con.execute(
            "SELECT player_id, team, team_code FROM published_roster "
            "WHERE player_id IS NOT NULL" + where, (league,) if league else ()).fetchall()
    except sqlite3.Error:
        return {}
    clubs: Dict[int, set] = {}
    for row in rows:
        clubs.setdefault(row[0], set()).update(v for v in (row[1], row[2]) if v)
    return clubs


def _stable_conflict(rows) -> List[str]:
    """The publisher-id columns on which these rows hold two different values."""
    conflict = []
    for column in _ID_COLUMNS:
        values = {str(r[column]).strip() for r in rows
                  if column in r.keys() and r[column] is not None and str(r[column]).strip()}
        if len(values) > 1:
            conflict.append(column)
    return conflict


def _roster_double_groups(con, league: Optional[str]) -> List[Tuple[str, str, List[int]]]:
    """(league, label, [player ids]) for rows the published rosters file under one name at one club.

    The name alone would not group these: a publisher that lists a squad member twice gives two
    rows, or one row and one unlinked key, and the roster is what says they are one person.
    """
    by_claim: Dict[Tuple[str, str, str], List[int]] = {}
    for pid, pairs in _roster_claims(con, league).items():
        row = con.execute("SELECT league FROM players WHERE id=?", (pid,)).fetchone()
        if row is None:
            continue
        for folded, team in pairs:
            by_claim.setdefault((row[0], folded, team), []).append(pid)
    return [(lg, "{} ({})".format(folded, team), sorted(set(ids)))
            for (lg, folded, team), ids in by_claim.items() if len(set(ids)) > 1]


def _unbound_binds(con, league: Optional[str], merged_away) -> Tuple[List[Bind], List[Tuple[str, str, str]]]:
    """Publisher keys no player row names yet, that the rosters file under one player's name and club.

    A publisher that lists a squad member twice leaves one of the two keys without a player row,
    and the row it belongs to already carries that publisher's other key. The bind happens only
    when the player already holds a key from that same publisher, so a name and a club alone never
    attach a new publisher to someone.
    """
    claims = _roster_claims(con, league)
    where = " AND league=?" if league else ""
    try:
        unbound = con.execute(
            "SELECT league, source, source_player_key, name, name_folded, team FROM published_roster "
            "WHERE player_id IS NULL AND team IS NOT NULL AND team != ''" + where,
            (league,) if league else ()).fetchall()
    except sqlite3.Error:
        return [], []
    refused: List[Tuple[str, str, str]] = []
    per_owner: Dict[Tuple[str, int, str], List[Bind]] = {}
    for lg, source, key, name, folded, team in unbound:
        owners = sorted(pid for pid, pairs in claims.items() if (folded, team) in pairs)
        if not owners:
            continue  # nobody in the players table is this person: a new player, not a duplicate
        if len(owners) > 1:
            refused.append((lg, name, "{}={} is filed under {} players at {}; which one it belongs to is a guess"
                            .format(source, key, len(owners), team)))
            continue
        owner = owners[0]
        if owner in merged_away:
            continue
        owner_league = con.execute("SELECT league FROM players WHERE id=?", (owner,)).fetchone()
        if owner_league is None:
            continue
        # A competition borrows its people from their home league (published_roster.NO_MINT_LEAGUES),
        # so its keys bind to the home-league player. Anywhere else the league must match, and a
        # mismatch is reported rather than skipped quietly.
        borrows = lg in _NO_MINT_LEAGUES
        if owner_league[0] != lg and not borrows:
            refused.append((lg, name, "{}={} matches player {} by name and club, but that player is in {}; "
                            "not bound across leagues".format(source, key, owner, owner_league[0])))
            continue
        if borrows:
            held = con.execute(
                "SELECT 1 FROM published_roster WHERE source=? AND player_id=?", (source, owner)).fetchone()
        else:
            held = con.execute(
                "SELECT 1 FROM published_roster WHERE league=? AND source=? AND player_id=?",
                (lg, source, owner)).fetchone()
        if not held:
            refused.append((lg, name, "{}={} matches player {} by name and club, but {} lists no key for "
                            "them yet; not bound".format(source, key, owner, source)))
            continue
        per_owner.setdefault((lg, owner, source), []).append(Bind(lg, source, key, owner, name))
    binds: List[Bind] = []
    for (lg, owner, source), found in sorted(per_owner.items()):
        if len(found) > 1:
            refused.append((found[0].league, found[0].name,
                            "{} has {} unbound keys for player {}; which is the duplicate is a guess"
                            .format(source, len(found), owner)))
            continue
        binds.append(found[0])
    return binds, refused


def _keys_by_publisher(con, rows) -> Dict[str, set]:
    """publisher -> the set of keys these rows carry for it. Two keys means two people."""
    keys: Dict[str, set] = {}
    for row in rows:
        for column in _ID_COLUMNS:
            value = row[column] if column in row.keys() else None
            if value is not None and str(value).strip():
                keys.setdefault(column, set()).add(str(value).strip())
        for binding in con.execute(
                "SELECT source, source_player_key FROM player_source_ids WHERE player_id=?",
                (row["id"],)).fetchall():
            keys.setdefault(binding[0], set()).add(str(binding[1]))
    return keys


def _nfl_pair_conflict(rows, crosswalk):
    """Check the ESPN/GSIS pair that would exist after combining these rows."""
    espn_ids = {
        str(row["espn_id"]).strip()
        for row in rows
        if "espn_id" in row.keys() and str(row["espn_id"] or "").strip()
    }
    gsis_ids = {
        str(row["nfl_gsis_id"]).strip()
        for row in rows
        if "nfl_gsis_id" in row.keys() and str(row["nfl_gsis_id"] or "").strip()
    }
    if len(espn_ids) > 1 or len(gsis_ids) > 1:
        return "merge combines multiple ESPN or GSIS IDs"
    if not espn_ids or not gsis_ids:
        return None
    return espn_assignment_conflict(
        next(iter(espn_ids)), next(iter(gsis_ids)), crosswalk[0], crosswalk[1]
    )


def _identity_count(con, row) -> int:
    n = sum(1 for column in _ID_COLUMNS
            if column in row.keys() and row[column] is not None
            and str(row[column]).strip())
    return n + con.execute(
        "SELECT COUNT(*) FROM player_source_ids WHERE player_id=?", (row["id"],)).fetchone()[0]


def _moved(con, plan, player_id: int) -> Dict[str, int]:
    moved = {}
    for table, col in plan.columns:
        n = con.execute("SELECT COUNT(*) FROM {} WHERE {}=?".format(table, col),
                        (player_id,)).fetchone()[0]
        if n:
            moved[table] = n
    return moved


def build_plan(con, league: Optional[str] = None, limit: Optional[int] = None) -> MergePlan:
    con.row_factory = sqlite3.Row
    plan = MergePlan(columns=referencing_columns(con))
    player_columns = {row[1] for row in con.execute("PRAGMA table_info(players)")}
    nfl_crosswalk = (
        load_espn_to_gsis()
        if "nfl_gsis_id" in player_columns and league in (None, "nfl")
        else None
    )

    seen: set = set()
    clubs = _roster_clubs(con, league)
    # Roster groups go first. A pair a publisher double-lists is one person, and it has to be claimed
    # before the name pass sees the same two rows, calls them two people and skips them.
    groups = ([("roster",) + g for g in _roster_double_groups(con, league)]
              + [("name",) + g for g in _name_groups(con, league)]
              + [("published",) + g for g in _published_groups(con, league)])

    for origin, group_league, label, ids in groups:
        key = tuple(sorted(ids))
        if key in seen:
            continue  # a duplicate both sources found; one plan entry, not two
        seen.add(key)
        group = {"league": group_league, "name": label}
        rows = con.execute(
            "SELECT id, name, {} FROM players WHERE id IN ({}) ORDER BY id".format(
                ", ".join([c for c in ("team",) if c in player_columns]
                          + list(_present_id_columns(con) or ("espn_id",))),
                ",".join("?" * len(ids))), ids).fetchall()
        identity = {r["id"]: publisher_identity(con, r["id"], r) for r in rows}
        with_id = [r for r in rows if identity[r["id"]]]
        without = [r for r in rows if not identity[r["id"]]]

        if origin == "roster":
            # The publisher files these rows under one name at one club. Two keys it holds for one
            # squad member are a double listing, so the key-conflict refusal below does not apply.
            # Two different stable ids (ESPN, NBA, ...) are still two people, whatever the roster says.
            conflict = _stable_conflict(rows)
            if conflict:
                plan.refused.append((group["league"], group["name"],
                                     "{} differ on these rows; two people".format(", ".join(conflict))))
                continue
            if len(rows) != 2:
                plan.refused.append((group["league"], group["name"],
                                     "{} rows resolve here; which survives is a guess".format(len(rows))))
                continue
            # The row already on the roster's club survives. Then the row carrying more ids, then the
            # one more rows already point at, then age.
            on_roster = {r["id"]: (r["team"] if "team" in r.keys() else None) in clubs.get(r["id"], set())
                         for r in rows}
            ranked = sorted(rows, key=lambda r: (
                0 if on_roster[r["id"]] else 1,
                -_identity_count(con, r),
                -sum(_moved(con, plan, r["id"]).values()),
                r["id"]))
            keep, drop = ranked[0], ranked[1]
            if group_league == "nfl" and nfl_crosswalk:
                conflict = _nfl_pair_conflict((keep, drop), nfl_crosswalk)
                if conflict:
                    plan.refused.append((group["league"], group["name"],
                                         "NFL ESPN/GSIS identity check refused merge: {}".format(conflict)))
                    continue
            plan.merges.append(Merge(
                group["league"], group["name"], keep["id"], drop["id"],
                identity[keep["id"]] or label, _moved(con, plan, drop["id"])))
            if limit and len(plan.merges) >= limit:
                break
            continue

        if origin == "published":
            # These rows are grouped because the PUBLISHER named them as one squad member, so
            # "both carry an id" is not evidence of two people here -- one row can carry an
            # espn_id and the other a fotmob id and neither says anything about the other.
            # What would be evidence is two DIFFERENT keys from the SAME publisher, so that is
            # what this refuses on.
            keys = _keys_by_publisher(con, rows)
            conflict = sorted(p for p, values in keys.items() if len(values) > 1)
            if conflict:
                plan.refused.append((
                    group["league"], group["name"],
                    "{} names two keys for these rows; that is two people".format(
                        ", ".join(conflict))))
                continue
            if len(rows) != 2:
                plan.refused.append((group["league"], group["name"],
                                     "{} rows resolve here; which survives is a guess".format(
                                         len(rows))))
                continue
            # The survivor is the row already spelled the way the PUBLISHER spells it. Every
            # identity travels either way, because apply_plan carries them, so what the
            # choice actually decides is which name the person keeps -- and we are merging
            # these two rows BECAUSE the publisher named them as one squad member, so their
            # rendering is the fact and the sportsbook's is a display artifact. After that,
            # the row carrying more ids, then the one more rows already point at, then age.
            published_name = con.execute(
                "SELECT name FROM published_roster WHERE league=? AND source=? "
                "AND source_player_key=?",
                (group["league"],) + tuple(label.split("=", 1))).fetchone()
            wanted = published_roster.fold(published_name[0]) if published_name else None
            ranked = sorted(rows, key=lambda r: (
                0 if wanted and published_roster.fold(r["name"]) == wanted else 1,
                -_identity_count(con, r),
                -sum(_moved(con, plan, r["id"]).values()),
                r["id"]))
            keep, drop = ranked[0], ranked[1]
            if group_league == "nfl" and nfl_crosswalk:
                conflict = _nfl_pair_conflict((keep, drop), nfl_crosswalk)
                if conflict:
                    plan.refused.append((
                        group["league"], group["name"],
                        "NFL ESPN/GSIS identity check refused merge: {}".format(conflict),
                    ))
                    continue
            plan.merges.append(Merge(
                group["league"], group["name"], keep["id"], drop["id"],
                identity[keep["id"]] or label, _moved(con, plan, drop["id"])))
            if limit and len(plan.merges) >= limit:
                break
            continue

        if not without:
            continue  # distinct publisher ids: two real people, the spine working
        if not with_id:
            plan.refused.append((group["league"], group["name"],
                                 "every row is unresolved; nothing to merge into"))
            continue
        if len(with_id) > 1:
            # Reached only when an id-LESS row also exists: the "two real people, both
            # resolved" case returned above. Distinct publisher ids do not help here, because
            # the open question is which of them the unresolved row belongs to, and that is
            # exactly the guess this tool refuses to make.
            plan.refused.append((group["league"], group["name"],
                                 "{} rows carry ids; which one survives is a guess".format(
                                     len(with_id))))
            continue
        if len(without) > 1:
            plan.refused.append((group["league"], group["name"],
                                 "{} id-less rows; which merges in is a guess".format(
                                     len(without))))
            continue

        keep, drop = with_id[0], without[0]
        if group_league == "nfl" and nfl_crosswalk:
            conflict = _nfl_pair_conflict((keep, drop), nfl_crosswalk)
            if conflict:
                plan.refused.append((
                    group["league"], group["name"],
                    "NFL ESPN/GSIS identity check refused merge: {}".format(conflict),
                ))
                continue
        plan.merges.append(Merge(group["league"], group["name"], keep["id"], drop["id"],
                                 identity[keep["id"]], _moved(con, plan, drop["id"])))
        if limit and len(plan.merges) >= limit:
            break
    merged_away = {m.drop_id for m in plan.merges}
    binds, refused = _unbound_binds(con, league, merged_away)
    plan.binds.extend(binds)
    plan.refused.extend(refused)
    return plan


def render(plan: MergePlan, emit=print, show: int = 12) -> None:
    emit("  discovered {} player_id columns across the schema".format(len(plan.columns)))
    emit("  {} merges and {} key binds planned, {} refused".format(
        len(plan.merges), len(plan.binds), len(plan.refused)))
    by_league: Dict[str, int] = {}
    for m in plan.merges:
        by_league[m.league] = by_league.get(m.league, 0) + 1
    for lg, n in sorted(by_league.items(), key=lambda kv: -kv[1]):
        emit("    {:<7} {}".format(lg, n))
    for m in plan.merges[:show]:
        detail = ", ".join("{} x{}".format(t, n) for t, n in sorted(m.moved.items())) or "no rows"
        # The surviving id is no longer necessarily ESPN's, so print the key as it is
        # rather than labelling every publisher "espn".
        emit("    MERGE {:<6} {!r}: drop {} into {} (on {}) moving {}".format(
            m.league, m.name, m.drop_id, m.keep_id, m.keep_espn_id, detail))
    for b in plan.binds[:show]:
        emit("    BIND {:<6} {}={} ({!r}) to player {}".format(b.league, b.source, b.key, b.name, b.player_id))
    for league, name, why in plan.refused[:show]:
        emit("    REFUSE {:<6} {!r}: {}".format(league, name, why))


def apply_plan(con, plan: MergePlan) -> Dict[str, int]:
    """Repoint every reference, then delete the now-unreferenced row."""
    con.row_factory = sqlite3.Row
    counts = {"merged": 0, "rows_moved": 0, "aliases": 0, "ids_carried": 0, "bound": 0}
    present = _present_id_columns(con)
    nfl_crosswalk = (
        load_espn_to_gsis()
        if "nfl_gsis_id" in present and any(m.league == "nfl" for m in plan.merges)
        else None
    )
    for m in plan.merges:
        # Carry identities the survivor lacks BEFORE anything is deleted. A merge that drops
        # a publisher id makes the person harder to resolve than before it ran, which is the
        # opposite of the point, and it is also what the delete guard below would catch far
        # too late.
        drop_row = con.execute("SELECT * FROM players WHERE id=?", (m.drop_id,)).fetchone()
        keep_row = con.execute("SELECT * FROM players WHERE id=?", (m.keep_id,)).fetchone()
        if drop_row is not None and keep_row is not None:
            if m.league == "nfl" and nfl_crosswalk:
                conflict = _nfl_pair_conflict((keep_row, drop_row), nfl_crosswalk)
                if conflict:
                    raise ValueError(
                        "refusing NFL spine merge with conflicting ESPN/GSIS IDs: {}"
                        .format(conflict)
                    )
            for column in present:
                value = drop_row[column]
                if str(value or "").strip() and not str(keep_row[column] or "").strip():
                    # Clear the old owner before assigning the UNIQUE publisher id to the
                    # survivor. Doing this in the opposite order aborts on
                    # UNIQUE(espn_id, league) when the published spelling is the id-less
                    # row. The enclosing transaction restores both rows if the assignment
                    # fails, so there is no window where a committed identity disappears.
                    con.execute("UPDATE players SET {}=NULL WHERE id=?".format(column),
                                (m.drop_id,))
                    con.execute("UPDATE players SET {}=? WHERE id=?".format(column),
                                (value, m.keep_id))
                    counts["ids_carried"] += 1
        for table, col in plan.columns:
            cur = con.execute(
                "UPDATE OR IGNORE {} SET {}=? WHERE {}=?".format(table, col, col),
                (m.keep_id, m.drop_id))
            counts["rows_moved"] += cur.rowcount
        # A UNIQUE constraint can leave a row behind that UPDATE OR IGNORE skipped; it
        # would become an orphan pointing at a deleted player, so drop those explicitly.
        for table, col in plan.columns:
            con.execute("DELETE FROM {} WHERE {}=?".format(table, col), (m.drop_id,))
        cur = con.execute(
            "DELETE FROM players WHERE id=? AND league=? AND NULLIF(espn_id,'') IS NULL",
            (m.drop_id, m.league))
        counts["merged"] += cur.rowcount
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for b in plan.binds:
        con.execute(
            "INSERT INTO player_source_ids(source, league, source_player_key, player_id, first_seen, last_seen) "
            "VALUES(?,?,?,?,?,?)", (b.source, b.league, b.key, b.player_id, now, now))
        con.execute(
            "UPDATE published_roster SET player_id=? WHERE league=? AND source=? AND source_player_key=?",
            (b.player_id, b.league, b.source, b.key))
        counts["bound"] += 1
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # LP_DB_PATH is how every other tool on this box is pointed at a database,
    # and this one ignored it and defaulted to PROD. So
    # `LP_DB_PATH=data/picks.dev.db spine_merge.py --apply` read as a dev
    # rehearsal and would have merged rows in prod. A destructive tool must
    # never resolve to prod through the same variable the operator used to say
    # "not prod"; --db stays as the explicit override.
    ap.add_argument("--db", default=(os.environ.get("LP_DB_PATH")
                                     or os.path.join(HERE, "data", "picks.db")))
    ap.add_argument("--league")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--apply", action="store_true", help="without this it only reports")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.db):
        print("spine_merge: no database at {}".format(args.db), file=sys.stderr)
        return 2

    con = sqlite3.connect(args.db)
    try:
        plan = build_plan(con, args.league, args.limit)
        # Absolute, and printed before anything is written. A relative path
        # resolves against the cwd, so "data/picks.dev.db" in a log does not
        # identify a database -- and telling two environments apart by how good
        # their data looks is how a frozen snapshot passed for dev once already.
        print("db: {}".format(os.path.abspath(args.db)))
        render(plan)
        if not args.apply:
            print("  dry run; pass --apply to write")
            return 0
        if not plan.mutations:
            return 0
        with con:
            counts = apply_plan(con, plan)
        print("  applied: {merged} rows merged, {rows_moved} references moved, {bound} keys bound".format(**counts))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
