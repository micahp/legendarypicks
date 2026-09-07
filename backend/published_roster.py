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
import re
import sqlite3
import unicodedata
from typing import Optional, Tuple

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
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (league, source, source_player_key)
);
CREATE INDEX IF NOT EXISTS ix_published_roster_lookup
    ON published_roster(league, name_folded);
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


def ensure(con: sqlite3.Connection) -> None:
    con.executescript(DDL)


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
    """
    folded = fold(name)
    if not folded:
        return None
    try:
        rows = con.execute(
            "SELECT source, source_player_key, position, position_group, team, name "
            "FROM published_roster WHERE league=? AND name_folded=?",
            (league, folded)).fetchall()
    except sqlite3.Error:
        return None  # a database without the table simply has no published roster
    if not rows:
        return None
    if len(rows) > 1 and team:
        narrowed = [r for r in rows if (r[4] or "").strip().upper() == team.strip().upper()]
        if len(narrowed) == 1:
            rows = narrowed
    if len(rows) != 1:
        return None
    row = rows[0]
    return (row[0], row[1], row[2], row[3], row[5])
