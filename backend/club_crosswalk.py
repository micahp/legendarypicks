#!/usr/bin/env python3
"""club_crosswalk.py — learn a club's code from the roster, not from its name.

WHY.

`published_roster.team_code` is what lets `publish_identities` bind a roster row to a
person, and it was produced by `link_prop_games._norm_team`, a static map that only covers
MLS. Measured on prod 2026-09-07:

    league   roster rows   with no team_code   unbound
    lcup           1035               1035        1035   (100%)
    ligamx          483                483          65
    mls            1835                  1           1

So 1,100 identities could never be published, and nothing raised: a missing join key does
not error, it silently matches nothing and the job reports success.

WHY NOT JUST EXTEND THE MAP. Because the two publishers do not name clubs the same way and
never will. `league_clubs` holds both halves already, FotMob names against numeric ids and
ESPN names against the short codes `players.team` uses, but joining them ON THE NAME
bridges 2 of 11 Liga MX clubs and 2 of 25 MLS ones. ESPN files nicknames: `Rayados`,
`Panzas Verdes`, `La Franja`, `Rojos`. No amount of name normalisation reaches those.

WHAT WORKS. The squad. A club is identified far better by the twenty-five people in it
than by what anybody calls it. For each club a publisher names, look at the players already
bound to that club and take the code they already carry:

    Chivas        -> GDL   19 of 19
    Pumas         -> UNAM  27 of 27
    Tigres        -> UANL  22 of 23
    Liga MX: 18 of 18 clubs, worst agreement 22/23

And it is learned across leagues rather than per league, because a club is the same club in
every competition it enters. Leagues Cup had ZERO bound players and looked unreachable; all
36 of its clubs are MLS or Liga MX clubs, and all 36 resolve from what those two teach.

THE SEED. Binding needs a code and learning needs bindings, so this could have had nothing
to start from. It does not: `player_source_ids` already bound 418 Liga MX roster rows by
publisher id, with no team involved, and that is the seed the rest is learned from.

HOW IT REFUSES. A code is learned only from at least `MIN_OVERLAP` bound players at
`MIN_AGREEMENT` agreement, and a code claimed by two different clubs is dropped rather than
assigned to whichever appeared first. A club we cannot learn keeps returning "", which is
the same "unknown" the caller already handles, never a guess.
"""
import collections
import os
import sqlite3
import sys
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from link_prop_games import _norm_team
from published_roster import fold

# A squad is ~25 people. Three is enough that a single mis-bound player cannot mint a code,
# and low enough that a club we only partly know still resolves.
MIN_OVERLAP = 3
MIN_AGREEMENT = 0.8

# Leagues where `players.team` is not a club and must never teach this crosswalk.
#
# UFC deliberately reuses the column to carry the OPPONENT: `ingest_ufc_fight_stats/roster.py`
# says so in as many words, and on prod 242 of 248 UFC team values are another fighter's
# name, 232 of them reciprocal pairs. Tennis stores no team at all, which is the correct
# answer for an individual sport, and is listed here so the reason is written down rather
# than depending on the column staying empty.
#
# Nothing in these leagues reaches `published_roster` today, so this changes no current
# result. It is here because a column named `team` holding something that is not a team is
# exactly the trap a generic cross-league reader falls into, and this is a generic
# cross-league reader.
INDIVIDUAL_SPORTS = frozenset({"ufc", "atp", "wta", "tennis"})


def learn(con: sqlite3.Connection) -> Dict[object, str]:
    """What the bound rosters teach, keyed two ways.

    `(league, folded club)` for the league that taught it, and bare `folded club` as a
    cross-league fallback so a competition with no bindings of its own can inherit.

    UNIQUENESS IS PER LEAGUE, because a code only has to be unambiguous where it is used.
    `ATL` is Atlanta United in MLS and Atlante in Liga MX, and both are correct. Judging
    that globally threw away BOTH, which is how the first run of this resolved 17 of 18
    Liga MX clubs and blamed the one club that was never the problem. The cross-league
    fallback still drops it, and it should: in Leagues Cup, where both clubs play, `ATL`
    genuinely does not identify one of them.
    """
    votes = collections.defaultdict(collections.Counter)
    try:
        rows = con.execute(
            "SELECT pr.league, pr.team, p.team FROM published_roster pr "
            "JOIN players p ON p.id = pr.player_id "
            "WHERE pr.team IS NOT NULL AND COALESCE(p.team,'') <> ''").fetchall()
    except sqlite3.Error:
        return {}  # a database without either table simply teaches nothing
    for league, club, code in rows:
        if league in INDIVIDUAL_SPORTS:
            continue
        folded = fold(club)
        if folded:
            votes[(league, folded)][str(code).strip().upper()] += 1

    per_league = {}
    for key, counter in votes.items():
        code, agreed = counter.most_common(1)[0]
        if agreed >= MIN_OVERLAP and agreed / sum(counter.values()) >= MIN_AGREEMENT:
            per_league[key] = code

    # Within one league, a code naming two clubs means we learned something wrong, and
    # knowing neither beats binding a squad to the wrong club.
    by_league = collections.defaultdict(collections.Counter)
    for (league, _folded), code in per_league.items():
        by_league[league][code] += 1
    learned = {key: code for key, code in per_league.items()
               if by_league[key[0]][code] == 1}

    # The cross-league fallback: a club is the same club wherever it plays. Dropped where
    # two different clubs would answer to one code, which is the Atlante case.
    globally = collections.defaultdict(set)
    for (_league, folded), code in learned.items():
        globally[folded].add(code)
    owners = collections.Counter(
        next(iter(codes)) for codes in globally.values() if len(codes) == 1)
    for folded, codes in globally.items():
        if len(codes) == 1 and owners[next(iter(codes))] == 1:
            learned[folded] = next(iter(codes))
    return learned


def resolve(name: str, league: str, learned: Dict[str, str]) -> str:
    """A club's code, or "" when we do not know it.

    The static map wins where it has an answer: it is the publisher's own vocabulary,
    committed and reviewable, and it does not depend on the state of the database. The
    learned crosswalk only fills the leagues that map never covered.
    """
    mapped = _norm_team(name, league)
    if mapped:
        return mapped
    folded = fold(name)
    return learned.get((league, folded)) or learned.get(folded, "")


def main(argv=None):
    """Print what the current database teaches, so it can be checked by hand."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("LP_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "data", "picks.db"))
    args = parser.parse_args(argv)
    con = sqlite3.connect("file:{}?mode=ro".format(args.db), uri=True)
    learned = learn(con)
    print("{}: learned {} club codes".format(args.db, len(learned)))
    for league in ("mls", "ligamx", "lcup"):
        clubs = [row[0] for row in con.execute(
            "SELECT DISTINCT team FROM published_roster WHERE league=? AND team IS NOT NULL",
            (league,))]
        resolved = [(c, resolve(c, league, learned)) for c in sorted(clubs)]
        unknown = [c for c, code in resolved if not code]
        print("  {:<7} {}/{} clubs resolve{}".format(
            league, len(resolved) - len(unknown), len(resolved),
            "; unknown: " + ", ".join(unknown) if unknown else ""))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
