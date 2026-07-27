"""nfl_name_aliases.py — name alias tables for NFL player identity resolution.

Two separate tables, kept apart because they are different kinds of fact
and they fail differently:

1. FIRST_NAME_ALIASES — familiar ↔ formal first names, bidirectional.
   A standard English nickname list seeded from the 5 missing players plus
   common US sports-name pairs.

2. FULL_NAME_ALIASES — whole-name → whole-name, for legal name changes only,
   where the surname itself moved. Exactly one entry.

These are read-side resolution fixes. No row in `players` is touched.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# FIRST_NAME_ALIASES — bidirectional first-name equivalence
# ---------------------------------------------------------------------------
# Each tuple declares two first names that refer to the same person.
# Order does not matter; the builder makes the relation symmetric and
# transitively closed so "mike ≡ michael" works in both directions and
# chains through intermediate forms (e.g. rob ↔ robert ↔ bob).
# ---------------------------------------------------------------------------

_FIRST_NAME_PAIRS: list[tuple[str, str]] = [
    # The five missing players (docs/TASK-nfl-name-aliases.md)
    ("gabe", "gabriel"),
    ("greg", "gregory"),
    ("mike", "michael"),
    ("scott", "scotty"),
    ("rob", "robert"),       # needed because Robbie Chosen is the alias target
    ("robbie", "robert"),    #   for Robby Anderson (FULL_NAME_ALIASES)
    ("robby", "robert"),

    # Standard English nickname list
    ("bill", "william"),
    ("bob", "robert"),
    ("chris", "christopher"),
    ("matt", "matthew"),
    ("nick", "nicholas"),
    ("tony", "anthony"),
    ("joe", "joseph"),
    ("dan", "daniel"),
    ("ben", "benjamin"),
    ("jim", "james"),
    ("steve", "stephen"),
    ("ken", "kenneth"),
    ("ron", "ronald"),
    ("tom", "thomas"),
    ("dave", "david"),
    ("pete", "peter"),
    ("tim", "timothy"),
    ("jeff", "jeffrey"),
    ("jon", "john"),
    ("john", "johnathan"),
    ("ed", "edward"),
    ("ted", "theodore"),
    ("rich", "richard"),
    ("rick", "richard"),
    ("pat", "patrick"),
    ("chuck", "charles"),
    ("fred", "frederick"),
    ("sam", "samuel"),
    ("josh", "joshua"),
    ("alex", "alexander"),
    ("andy", "andrew"),
    ("phil", "philip"),
    ("drew", "andrew"),
    ("nate", "nathan"),
    ("zach", "zachary"),
    ("ray", "raymond"),
    ("larry", "lawrence"),
    ("vic", "victor"),
    ("vinny", "vincent"),
    ("walt", "walter"),
    ("hank", "henry"),
    ("harry", "harold"),
    ("doug", "douglas"),
    ("don", "donald"),
    ("jerry", "gerald"),
    ("bert", "albert"),
    ("al", "albert"),
    ("ernie", "ernest"),
    ("gene", "eugene"),
    ("jack", "john"),
    ("max", "maxwell"),
    ("dick", "richard"),
]


def _build_first_name_aliases(pairs: list[tuple[str, str]]) -> dict[str, frozenset[str]]:
    """Build bidirectional equivalence from (a, b) pairs.

    Each name maps to a frozenset of all its equivalent forms (including itself).
    Symmetry is explicit and transitive closure is computed so chains like
    rob ↔ robert ↔ bob collapse into one class.
    """
    # Union of all names that appear in at least one pair
    all_names: set[str] = set()
    for a, b in pairs:
        all_names.add(a)
        all_names.add(b)

    # Union-Find over the set of names
    parent: dict[str, str] = {n: n for n in all_names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for a, b in pairs:
        union(a, b)

    # Collect equivalence classes
    classes: dict[str, set[str]] = {}
    for name in all_names:
        root = find(name)
        classes.setdefault(root, set()).add(name)

    # Build lookup: every name → its full class (as frozenset for immutability)
    result: dict[str, frozenset[str]] = {}
    for root, members in classes.items():
        fs = frozenset(members)
        for name in members:
            result[name] = fs

    return result


FIRST_NAME_ALIASES: dict[str, frozenset[str]] = _build_first_name_aliases(_FIRST_NAME_PAIRS)


def expand_first_names(first_name: str) -> frozenset[str]:
    """Return all known first-name variants for *first_name*, including itself.

    Returns a frozenset; if *first_name* is unknown the result is a singleton
    containing only it.
    """
    return FIRST_NAME_ALIASES.get(first_name, frozenset([first_name]))


# ---------------------------------------------------------------------------
# FULL_NAME_ALIASES — legal name changes (surname moved)
# ---------------------------------------------------------------------------
# Keys and values are *normalised* full names (lowercase, no suffixes/punctuation).
# See nfl_allday._norm_name for the exact normalisation.
#
# Verified entries:
#   Robby Anderson → Robbie Chosen  (2022 legal name change; Robby Anderson
#   no longer exists as a player identity — his row is "Robbie Chosen" WR/WAS)

FULL_NAME_ALIASES: dict[str, str] = {
    "robby anderson": "robbie chosen",
}
