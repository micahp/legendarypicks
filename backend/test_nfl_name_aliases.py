"""Tests for nfl_name_aliases.py — alias tables and expansion helpers.

Run: backend/venv/bin/python -m pytest backend/test_nfl_name_aliases.py -q
"""

from routers.nfl_name_aliases import (
    FIRST_NAME_ALIASES,
    FULL_NAME_ALIASES,
    expand_first_names,
)


# ---------------------------------------------------------------------------
# FIRST_NAME_ALIASES — bidirectional equivalence
# ---------------------------------------------------------------------------


def test_mike_equals_michael_both_directions():
    """'mike' and 'michael' are in the same equivalence class."""
    assert "mike" in FIRST_NAME_ALIASES
    assert "michael" in FIRST_NAME_ALIASES
    assert FIRST_NAME_ALIASES["mike"] == FIRST_NAME_ALIASES["michael"]


def test_expand_michael_includes_mike():
    assert "mike" in expand_first_names("michael")


def test_expand_mike_includes_michael():
    assert "michael" in expand_first_names("mike")


def test_gabe_equals_gabriel():
    assert FIRST_NAME_ALIASES["gabe"] == FIRST_NAME_ALIASES["gabriel"]
    assert "gabriel" in expand_first_names("gabe")
    assert "gabe" in expand_first_names("gabriel")


def test_greg_equals_gregory():
    assert FIRST_NAME_ALIASES["greg"] == FIRST_NAME_ALIASES["gregory"]


def test_scott_equals_scotty():
    assert FIRST_NAME_ALIASES["scott"] == FIRST_NAME_ALIASES["scotty"]
    assert "scotty" in expand_first_names("scott")
    assert "scott" in expand_first_names("scotty")


def test_rob_variants_chain_transitively():
    """rob ↔ robert ↔ robby and rob ↔ robert ↔ robbie must collapse into one class."""
    variants = expand_first_names("rob")
    assert "robert" in variants
    assert "robby" in variants
    assert "robbie" in variants
    # All four point to the same class
    assert FIRST_NAME_ALIASES["rob"] == FIRST_NAME_ALIASES["robbie"]


def test_unknown_name_returns_singleton():
    """A name not in the table expands only to itself."""
    assert expand_first_names("xyzzy") == frozenset(["xyzzy"])


def test_expand_returns_frozenset_includes_self():
    for name in ["gabe", "mike", "greg", "rob", "scott"]:
        variants = expand_first_names(name)
        assert name in variants
        assert isinstance(variants, frozenset)


# ---------------------------------------------------------------------------
# FULL_NAME_ALIASES — legal name changes
# ---------------------------------------------------------------------------


def test_full_name_aliases_has_exactly_one_entry():
    assert len(FULL_NAME_ALIASES) == 1
    assert "robby anderson" in FULL_NAME_ALIASES
    assert FULL_NAME_ALIASES["robby anderson"] == "robbie chosen"
