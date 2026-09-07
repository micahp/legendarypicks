#!/usr/bin/env python3
"""published_roster.py: the stored roster a resolver can consult without a network call.

WHY.

`_resolve_player_for_ingest` has four steps and then gives up, writing the name to
`unresolved_players`. Giving up is right compared with minting a shadow row, which is what it
replaced, but it means every prop for that person is dropped. Measured on prod 2026-09-06:

    all leagues, by source        names    attempts
      bovada                      1,254     873,559
      statcast                      398      13,823
      underdog                        228     5,641
      espn_roster                     254       403
      nhle.com                        204       395
      rotowire                        195       620

Two things that measurement settles. It is not a sportsbook-vocabulary problem: `espn_roster`
itself fails on 254 names, so our spine is missing people ESPN's own feed names. And the
873,559 Bovada attempts are the same unresolvable names retried every thirty minutes for
months, because the queue records a miss and nothing ever acts on it.

So the answer is not another repair script. It is a fifth resolution step: consult the roster
the publisher already published. A row created that way is the OPPOSITE of a shadow. It is
born carrying an identity and a position.

WHY A TABLE AND NOT A FETCH. The resolver runs inside `/api/props/ingest`, a request handler,
and a serving path must never wait on a publisher; that is the 2026-08-24 lesson where a
batch fan-out put 26 ESPN refusals onto uvicorn. `ingest_published_rosters.py` fills this
table on a registry cadence, and the resolver only ever reads it.

PUBLISHER-AGNOSTIC ON PURPOSE. Every league names its own source: MLS, Liga MX and Leagues
Cup take FotMob because that is built and proven; NFL would take nflverse, MLB the MLB API.
Each is a row here, not a branch in the resolver.

HOW IT REFUSES. Exactly one match, or nothing. A name in two squads is two people until a
publisher says otherwise, and guessing between them is how 124 of 317 MLB "duplicate" groups
turned out to be two different humans.
"""
import collections
import re
import sqlite3
import unicodedata
from typing import Iterable, Optional, Tuple

DDL = """
CREATE TABLE IF NOT EXISTS published_roster (
    league            TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_player_key TEXT NOT NULL,
    name              TEXT NOT NULL,
    name_folded       TEXT NOT NULL,
    team              TEXT,
    position          TEXT,
    position_group    TEXT,
    team_code         TEXT,
    player_id         INTEGER,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (league, source, source_player_key)
);
CREATE INDEX IF NOT EXISTS ix_published_roster_lookup
    ON published_roster(league, name_folded);

-- Every spelling a publisher prints for one of its own people, not just the display one.
-- mlssoccer.com prints "Jake Davis" and files him at /players/jacob-davis/; both are the
-- same publisher naming the same person, and storing only the first is what forced six
-- hand-written aliases on 2026-09-06.
CREATE TABLE IF NOT EXISTS published_roster_name (
    league            TEXT NOT NULL,
    source            TEXT NOT NULL,
    source_player_key TEXT NOT NULL,
    name              TEXT NOT NULL,
    name_folded       TEXT NOT NULL,
    PRIMARY KEY (league, source, source_player_key, name_folded)
);
CREATE INDEX IF NOT EXISTS ix_published_roster_name_lookup
    ON published_roster_name(league, name_folded);
"""


def fold(value) -> str:
    """Accent-, case-, punctuation- AND space-insensitive.

    Everything but the letters goes, including spaces. A publisher's spelling of a name
    varies in exactly those characters and nowhere else: `Dje D'Avilla`, `Dje DAvilla` and
    `Djé D`Avilla` are one player, and turning punctuation into a SPACE (the first version of
    this) left them as three different keys. `Jean-Pierre` against `Jean Pierre` is the same
    problem with the opposite sign, and squashing settles both.

    It can theoretically join two different names, so uniqueness still decides: a folded name
    matching two roster rows resolves to nobody.
    """
    ascii_value = (unicodedata.normalize("NFKD", str(value or ""))
                   .encode("ascii", "ignore").decode("ascii"))
    return re.sub(r"[^a-z]+", "", ascii_value.lower())


# REVIEWED ALIASES: genuine disagreements no publisher roster currently resolves.
#
# `fold` removes accents, case, punctuation and spaces, which covers the variance a publisher
# actually produces. It deliberately does NOT cover a different NAME: a nickname (Willy for
# William), a transliteration (Lobzhanidze for Lobjanidze), a dropped surname (Vitor Costa for
# Vitor Costa de Brito). Reaching those needs a similarity threshold, and a threshold is a
# guess applied uniformly - the shape that turned 124 of 317 MLB "duplicate" groups into two
# different humans.
#
# So each one is reviewed once, by a person, against a published source, and written down
# here with that source. Anyone can check any line. It is deliberately NOT a database table:
# a judgment call belongs in version control where its reasoning and its reviewer travel with
# it, not in a row somebody later cannot trace.
#
# league -> {folded spelling we receive: (folded spelling the publisher uses, evidence)}
REVIEWED_ALIASES = {
    "mls": {
        # Georgian, transliterated two ways: en.wikipedia.org/wiki/Saba_Lobzhanidze against
        # rsl.com/players/saba-lobjanidze/. Same player, traded to RSL 2026-07-01.
        "sabalobzhanidze": ("sabalobjanidze", "rsl.com/players/saba-lobjanidze/ - Real Salt Lake"),
    },
}


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(DDL)
    columns = {row[1] for row in con.execute("PRAGMA table_info(published_roster)")}
    if "team_code" not in columns:
        con.execute("ALTER TABLE published_roster ADD COLUMN team_code TEXT")
    if "player_id" not in columns:
        con.execute("ALTER TABLE published_roster ADD COLUMN player_id INTEGER")


_SOURCE_PRIORITY = ("fotmob", "mlssoccer")


def _rank(source: str) -> int:
    """Which publisher's identity a collapsed person is returned under.

    FotMob leads because `player_game_logs_fotmob` joins on FotMob ids, so a player created
    under a FotMob key can be charted the day they are created. A publisher not named here
    sorts last rather than being refused: an unranked source is still a real identity.
    """
    return _SOURCE_PRIORITY.index(source) if source in _SOURCE_PRIORITY else len(_SOURCE_PRIORITY)


def _spellings(con: sqlite3.Connection, league: str, source: str, key: str,
               primary: str) -> set:
    """Every folded spelling one publisher prints for one of its people."""
    out = {primary}
    try:
        out.update(row[0] for row in con.execute(
            "SELECT name_folded FROM published_roster_name "
            "WHERE league=? AND source=? AND source_player_key=?", (league, source, key)))
    except sqlite3.Error:
        pass  # a database filled before the table existed still has the display spelling
    return {value for value in out if value}


def _candidates(con: sqlite3.Connection, league: str, keys) -> list:
    """Roster rows a folded name reaches, through any spelling its publisher prints."""
    placeholders = ",".join("?" * len(keys))
    sql = ("SELECT source, source_player_key, position, position_group, team, name, "
           "name_folded FROM published_roster WHERE league=? AND (name_folded IN ({0}) "
           "OR EXISTS (SELECT 1 FROM published_roster_name n WHERE n.league=published_roster"
           ".league AND n.source=published_roster.source AND n.source_player_key="
           "published_roster.source_player_key AND n.name_folded IN ({0})))").format(
               placeholders)
    try:
        return con.execute(sql, [league] + keys + keys).fetchall()
    except sqlite3.Error:
        pass
    try:  # no published_roster_name yet: the display spelling is all there is
        return con.execute(
            "SELECT source, source_player_key, position, position_group, team, name, "
            "name_folded FROM published_roster WHERE league=? AND name_folded IN ({})".format(
                placeholders), [league] + keys).fetchall()
    except sqlite3.Error:
        return []  # a database without the table simply has no published roster


def _twins(con: sqlite3.Connection, league: str, row, spellings: set) -> list:
    """The same person as another publisher files them.

    Two publishers share no id, so the evidence that two rows are one person has to come
    from what they both publish: the SAME CLUB and a spelling in common. Both halves are
    required. A shared spelling alone would merge two people of one name across two clubs,
    which is the 124-of-317 MLB failure; a shared club alone would merge a squad.

    A row without a team cannot be collapsed at all, and is left as its own person.

    The club comparison is done in Python over `fold`, not in SQL. SQLite's UPPER is
    ASCII-only, so `CF Montréal` upper-cased in here and upper-cased in there are two
    different strings, and the first version of this refused all 11 Montreal players it was
    written to resolve.
    """
    team = fold(row[4])
    if not team or not spellings:
        return []
    ordered = sorted(spellings)
    placeholders = ",".join("?" * len(ordered))
    sql = ("SELECT r.source, r.source_player_key, r.position, r.position_group, r.team, "
           "r.name, r.name_folded FROM published_roster r WHERE r.league=? "
           "AND r.source<>? AND (r.name_folded IN ({0}) "
           "OR EXISTS (SELECT 1 FROM published_roster_name n WHERE n.league=r.league "
           "AND n.source=r.source AND n.source_player_key=r.source_player_key "
           "AND n.name_folded IN ({0})))").format(placeholders)
    try:
        found = con.execute(sql, [league, row[0]] + ordered + ordered).fetchall()
    except sqlite3.Error:
        return []
    return [other for other in found if fold(other[4]) == team]


def lookup(con: sqlite3.Connection, league: str, name: str,
           team: Optional[str] = None) -> Optional[Tuple[str, str, str, str, str]]:
    """(source, source_player_key, position, position_group, published_name), or None.

    The published NAME is returned deliberately. A caller creating a player should store the
    publisher's spelling, not the sportsbook's: we are resolving BY the publisher's identity,
    so their rendering of the name is the fact and the book's is a display artifact. Folding
    is only ever a lookup key and never reaches a stored name.

    Team NARROWS when it is given and it helps; it never excludes the only candidate we have.
    A sportsbook's team string is often absent or its own vocabulary, so requiring it would
    refuse real players for a reason that says more about the publisher than the person.

    UNIQUENESS IS JUDGED OVER PEOPLE, NOT ROWS. With two publishers loaded for one league the
    same person matches twice, and the older rule read that as ambiguity and refused. So
    matching rows are first collapsed into people by `_twins`, and only then does exactly one
    person, or nothing, decide the answer.
    """
    folded = fold(name)
    if not folded:
        return None
    keys = [folded]
    alias = (REVIEWED_ALIASES.get(league) or {}).get(folded)
    if alias:
        keys.append(alias[0])
    rows = _candidates(con, league, keys)
    if not rows:
        return None
    if len(rows) > 1 and team:
        narrowed = [r for r in rows if (r[4] or "").strip().upper() == team.strip().upper()]
        if len(narrowed) == 1:
            rows = narrowed

    people = []  # each entry: (identity set, best row)
    for row in rows:
        cluster = {(row[0], row[1]): row}
        for twin in _twins(con, league, row,
                           _spellings(con, league, row[0], row[1], row[6])):
            cluster[(twin[0], twin[1])] = twin
        # Absorb EVERY cluster this one overlaps, not the first: a row can bridge two
        # clusters built earlier, and stopping at the first would report one person as two
        # and refuse a name we can answer.
        overlapping = [c for c in people if c.keys() & cluster.keys()]
        for existing in overlapping:
            cluster.update(existing)
            people.remove(existing)
        people.append(cluster)
    if len(people) != 1:
        return None
    best = min(people[0].values(), key=lambda r: (_rank(r[0]), r[0]))
    return (best[0], best[1], best[2], best[3], best[5])


def lookup_player(con: sqlite3.Connection, league: str, name: str,
                  team: Optional[str] = None) -> Optional[int]:
    """Return one identity already published by the roster job, or None.

    This is the request-path contract. It reads the durable ``player_id`` crosswalk and
    never computes a cross-publisher identity or creates a player. Roster ingestion owns
    both operations. A database that has not received the additive columns simply has no
    published identity yet and fails closed into the unresolved queue.
    """
    folded = fold(name)
    if not folded:
        return None
    keys = [folded]
    alias = (REVIEWED_ALIASES.get(league) or {}).get(folded)
    if alias:
        keys.append(alias[0])
    placeholders = ",".join("?" * len(keys))
    sql = ("SELECT DISTINCT r.player_id, r.team_code FROM published_roster r "
           "JOIN players p ON p.id=r.player_id AND p.league=r.league "
           "WHERE r.league=? AND r.player_id IS NOT NULL AND "
           "(r.name_folded IN ({0}) OR EXISTS (SELECT 1 FROM published_roster_name n "
           "WHERE n.league=r.league AND n.source=r.source AND "
           "n.source_player_key=r.source_player_key AND n.name_folded IN ({0})))").format(
               placeholders)
    try:
        rows = con.execute(sql, [league] + keys + keys).fetchall()
    except sqlite3.Error:
        return None
    if len(rows) > 1 and team:
        wanted = str(team).strip().upper()
        narrowed = [row for row in rows if str(row[1] or "").strip().upper() == wanted]
        if len({row[0] for row in narrowed}) == 1:
            rows = narrowed
    owners = {int(row[0]) for row in rows}
    if len(owners) == 1:
        return next(iter(owners))

    # Compatibility for leagues that still have one roster publisher. Their stable source
    # crosswalk predates ``published_roster.player_id`` and is already durable; using it does
    # not recompute a cross-publisher identity. Once a league has multiple publishers, only
    # roster publication may collapse them and this fallback refuses.
    try:
        source_count = con.execute(
            "SELECT COUNT(DISTINCT source) FROM published_roster WHERE league=?",
            (league,)).fetchone()[0]
    except sqlite3.Error:
        return None
    if source_count != 1:
        return None
    published = lookup(con, league, name, team)
    if not published:
        return None
    source, source_key = published[:2]
    try:
        row = con.execute(
            "SELECT s.player_id FROM player_source_ids s JOIN players p ON p.id=s.player_id "
            "AND p.league=s.league WHERE s.source=? AND s.league=? AND s.source_player_key=?",
            (source, league, source_key)).fetchone()
    except sqlite3.Error:
        return None
    return int(row[0]) if row else None


def _identity_components(con: sqlite3.Connection, league: str,
                         touched: Optional[Iterable[Tuple[str, str]]] = None):
    """Connected publisher rows, joined only by shared spelling and published club."""
    columns = ("source", "source_player_key", "name", "name_folded", "team",
               "team_code", "position", "position_group", "player_id")
    raw = con.execute(
        "SELECT {} FROM published_roster WHERE league=?".format(",".join(columns)),
        (league,)).fetchall()
    rows = [dict(zip(columns, row)) for row in raw]
    names = collections.defaultdict(set)
    for row in rows:
        key = (row["source"], row["source_player_key"])
        names[key].add(row["name_folded"])
    for source, key, spelling in con.execute(
            "SELECT source,source_player_key,name_folded FROM published_roster_name "
            "WHERE league=?", (league,)):
        names[(source, key)].add(spelling)

    parent = {i: i for i in range(len(rows))}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(left, right):
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    shared = collections.defaultdict(list)
    for i, row in enumerate(rows):
        if not row["team_code"]:
            continue
        for spelling in names[(row["source"], row["source_player_key"])]:
            shared[(row["team_code"], spelling)].append(i)
    for indexes in shared.values():
        for offset, left in enumerate(indexes):
            for right in indexes[offset + 1:]:
                if rows[left]["source"] != rows[right]["source"]:
                    union(left, right)

    groups = collections.defaultdict(list)
    for i, row in enumerate(rows):
        groups[find(i)].append(row)
    if touched is None:
        return list(groups.values()), names
    touched = set(touched)
    return [group for group in groups.values()
            if any((row["source"], row["source_player_key"]) in touched for row in group)], names


def publish_identities(con: sqlite3.Connection, league: str, now: str,
                       touched: Optional[Iterable[Tuple[str, str]]] = None) -> dict:
    """Publish roster-owned canonical IDs and source crosswalks.

    Stable source IDs win. Names only discover an unbound candidate, after which the
    published team narrows ambiguity. Every refusal is counted; safe components remain
    additive so one namesake does not discard the rest of a league's identities.
    """
    components, names = _identity_components(con, league, touched)
    players = [dict(zip(("id", "name", "team"), row)) for row in con.execute(
        "SELECT id,name,team FROM players WHERE league=?", (league,)).fetchall()]
    players_by_name = collections.defaultdict(list)
    for player in players:
        players_by_name[fold(player["name"])].append(player)

    # Which clubs each player has actually PLAYED for, from their own game logs. This is
    # the evidence that separates a transfer from a bad row: `players.team` is a
    # last-known value with no timestamp, so it cannot say on its own whether it is stale
    # history or simply wrong. One grouped read, league-scoped.
    logged_teams = collections.defaultdict(set)
    try:
        for player_id, team in con.execute(
                "SELECT g.player_id, g.team FROM player_game_logs g JOIN players p "
                "ON p.id=g.player_id WHERE p.league=? AND g.team IS NOT NULL "
                "GROUP BY g.player_id, g.team", (league,)):
            logged_teams[int(player_id)].add(str(team).strip().upper())
    except sqlite3.Error:
        pass  # a database without game logs simply offers no corroboration
    stats = collections.Counter(components=len(components))
    failure_examples = []

    def refuse(reason, component):
        stats[reason] += 1
        if len(failure_examples) < 20:
            failure_examples.append({
                "reason": reason,
                "names": sorted({row["name"] for row in component}),
                "teams": sorted({row["team"] for row in component if row["team"]}),
                "source_keys": sorted(
                    "{}:{}".format(row["source"], row["source_player_key"])
                    for row in component),
            })
    source_owners = {}
    keys_by_player_source = collections.defaultdict(set)
    for source, key, player_id in con.execute(
            "SELECT source,source_player_key,player_id FROM player_source_ids "
            "WHERE league=?", (league,)):
        source_owners[(source, key)] = int(player_id)
        keys_by_player_source[(int(player_id), source)].add(key)

    def component_priority(component):
        """Resolve facts before questions so output is independent of row order."""
        source_keys = {(row["source"], row["source_player_key"]) for row in component}
        if (any(row["player_id"] is not None for row in component)
                or any(key in source_owners for key in source_keys)):
            priority = 0
        else:
            team_codes = {row["team_code"] for row in component if row["team_code"]}
            spellings = set().union(*(
                names[(row["source"], row["source_player_key"])] for row in component))
            candidates = {player["id"]: player for spelling in spellings
                          for player in players_by_name.get(spelling, ())}
            same_team = ({pid for pid, player in candidates.items()
                          if len(team_codes) == 1
                          and str(player["team"] or "").upper()
                          == next(iter(team_codes)).upper()})
            if len(same_team) == 1:
                priority = 1
            elif not candidates:
                priority = 2
            else:
                priority = 3
        first = min((row["source"], row["source_player_key"]) for row in component)
        return priority, first

    components.sort(key=component_priority)

    for component in components:
        source_keys = {(row["source"], row["source_player_key"]) for row in component}
        owners = {int(row["player_id"]) for row in component if row["player_id"] is not None}
        owners.update(source_owners[key] for key in source_keys if key in source_owners)
        valid_owners = {row[0] for row in con.execute(
            "SELECT id FROM players WHERE league=? AND id IN ({})".format(
                ",".join("?" * len(owners))), [league] + sorted(owners))} if owners else set()
        if owners != valid_owners or len(owners) > 1:
            refuse("conflicts", component)
            continue

        team_codes = {row["team_code"] for row in component if row["team_code"]}
        if len(team_codes) > 1:
            refuse("conflicts", component)
            continue
        team_code = next(iter(team_codes)) if team_codes else None
        spellings = set().union(*(
            names[(row["source"], row["source_player_key"])] for row in component))
        name_candidates = {player["id"]: player for spelling in spellings
                           for player in players_by_name.get(spelling, ())}

        if owners:
            player_id = next(iter(owners))
            if not team_code:
                team_code = next((player["team"] for player in players
                                  if player["id"] == player_id), None)
            stats["duplicate_candidates"] += len(set(name_candidates) - {player_id})
        else:
            if not team_code:
                refuse("missing_team", component)
                continue
            # A source-native ID is stronger than a name. If this candidate is already
            # bound to a different key from the same publisher, this roster row names a
            # different person even when the display strings are identical (the two David
            # Ruiz records in MLS are the concrete case).
            candidates = {
                pid: player for pid, player in name_candidates.items()
                if all(not keys_by_player_source[(pid, row["source"])]
                       or row["source_player_key"] in keys_by_player_source[
                           (pid, row["source"])]
                       for row in component)
            }
            narrowed = {pid: player for pid, player in candidates.items()
                        if str(player["team"] or "").upper() == team_code.upper()}
            if len(narrowed) == 1:
                candidates = narrowed
            elif len(narrowed) > 1:
                refuse("ambiguous", component)
                continue
            elif len(candidates) == 1:
                # A unique name at a different club is USUALLY a transfer, not a namesake.
                # The first version refused all of these as "team_conflicts", which
                # compared two different things and called the difference a failure:
                # `players.team` is where we last saw someone, the publisher's team is
                # where they are now, and a player who moves clubs does not retroactively
                # change which club his old game logs belong to.
                #
                # So ask the logs, which are dated and cannot be stale in the same way:
                #
                #   publisher's club appears in their logs  -> they already play there;
                #       our stored team is the wrong one (STALE_TEAM). Bind, and say so.
                #   our stored team appears in their logs   -> that club is real history
                #       and the publisher has the newer fact (TRANSFER). Bind.
                #   neither club appears                    -> nothing corroborates either
                #       claim, so transfer and namesake are still indistinguishable.
                #       This is the only one that is genuinely unsafe (UNVERIFIED_TEAM).
                only_id, only_player = next(iter(candidates.items()))
                played = logged_teams.get(only_id, set())
                stored = str(only_player["team"] or "").strip().upper()
                if team_code.upper() in played:
                    stats["stale_team"] += 1
                elif stored and stored in played:
                    stats["transfers"] += 1
                else:
                    refuse("unverified_team", component)
                    continue
            elif candidates:
                # More than one unbound namesake at other clubs. Picking one would be the
                # guess this whole path exists to refuse.
                refuse("ambiguous", component)
                continue
            elif name_candidates:
                # Every name candidate was rejected because the SAME publisher already
                # assigns it a different native key. That is positive evidence that this
                # roster row is a namesake, so creating the second person is safe.
                candidates = {}
            if candidates:
                player_id = next(iter(candidates))
                stats["matched"] += 1
            else:
                best = min(component, key=lambda row: (_rank(row["source"]), row["source"]))
                cur = con.execute(
                    "INSERT INTO players(name,team,league,position,position_group,active,updated_at) "
                    "VALUES(?,?,?,?,?,1,?)",
                    (best["name"], team_code, league, best["position"],
                     best["position_group"], now))
                player_id = int(cur.lastrowid)
                players_by_name[fold(best["name"])].append(
                    {"id": player_id, "name": best["name"], "team": team_code})
                stats["inserted"] += 1

        conflict = any(
            keys_by_player_source[(player_id, row["source"])] - {row["source_player_key"]}
            for row in component)
        if conflict:
            refuse("conflicts", component)
            continue

        best = min(component, key=lambda row: (_rank(row["source"]), row["source"]))
        con.execute(
            "UPDATE players SET team=COALESCE(NULLIF(team,''),?), "
            "position=COALESCE(NULLIF(position,''),?), "
            "position_group=COALESCE(NULLIF(position_group,''),?), active=1, updated_at=? "
            "WHERE id=?",
            (team_code, best["position"], best["position_group"], now, player_id))
        for row in component:
            con.execute(
                "INSERT INTO player_source_ids(source,league,source_player_key,player_id,"
                "first_seen,last_seen) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(source,league,source_player_key) DO UPDATE SET last_seen=excluded.last_seen",
                (row["source"], league, row["source_player_key"], player_id, now, now))
            source_owners[(row["source"], row["source_player_key"])] = player_id
            keys_by_player_source[(player_id, row["source"])].add(row["source_player_key"])
            con.execute(
                "UPDATE published_roster SET player_id=?, team_code=COALESCE(team_code,?) "
                "WHERE league=? AND source=? "
                "AND source_player_key=?",
                (player_id, team_code, league, row["source"], row["source_player_key"]))
            stats["source_ids"] += 1
        stats["published"] += 1
    result = dict(stats)
    result["failure_examples"] = failure_examples
    return result
