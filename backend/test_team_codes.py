"""Tests for backend/team_codes.py — no DB, no network."""

import pytest

from team_codes import (
    ALIASES,
    CANONICAL,
    CANONICAL_POSITIONS,
    NON_FRANCHISE,
    POSITION_ALIASES,
    UnknownPositionCode,
    UnknownTeamCode,
    is_canonical,
    normalize,
    normalize_optional,
    normalize_position,
    normalize_position_optional,
)

# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


def test_every_alias_target_is_canonical():
    """Every alias must map to a code that IS in CANONICAL for that league."""
    for league, alias_map in ALIASES.items():
        canonical_set = CANONICAL[league]
        for src, tgt in alias_map.items():
            assert tgt in canonical_set, (
                f"Alias {league}:{src} -> {tgt} but {tgt} is not canonical"
            )


def test_non_franchise_only_nba():
    """NON_FRANCHISE currently only has the 'nba' key."""
    assert set(NON_FRANCHISE) == {"nba"}


def test_non_franchise_codes_are_not_canonical():
    """STRIPES, STARS, WORLD are not canonical (even though normalize returns them)."""
    for code in NON_FRANCHISE["nba"]:
        assert not is_canonical("nba", code)


def test_position_alias_targets_are_canonical():
    """Every position alias target must be in CANONICAL_POSITIONS."""
    for league, alias_map in POSITION_ALIASES.items():
        for src, tgt in alias_map.items():
            assert tgt in CANONICAL_POSITIONS[league], (
                f"Position alias {league}:{src} -> {tgt} but {tgt} not canonical"
            )


# ---------------------------------------------------------------------------
# normalize — team codes
# ---------------------------------------------------------------------------


def test_every_canonical_normalizes_to_itself():
    """Every canonical code normalizes to itself across all four leagues."""
    for league, codes in CANONICAL.items():
        for code in codes:
            assert normalize(league, code) == code


def test_every_alias_normalizes_to_canonical():
    """Every alias normalizes to its canonical target."""
    for league, alias_map in ALIASES.items():
        for src, tgt in alias_map.items():
            assert normalize(league, src) == tgt


def test_normalize_zzz_raises():
    with pytest.raises(UnknownTeamCode):
        normalize("nfl", "ZZZ")


def test_normalize_lowercase_zzz_raises():
    with pytest.raises(UnknownTeamCode):
        normalize("nfl", "zzz")


def test_normalize_whitespace_raises():
    with pytest.raises(UnknownTeamCode):
        normalize("nfl", "  ")


def test_normalize_none_raises():
    with pytest.raises(UnknownTeamCode):
        normalize("nfl", None)


def test_normalize_trailing_space_stripped():
    """'LAR ' should succeed — strip before lookup."""
    assert normalize("nfl", "LAR ") == "LAR"


def test_normalize_lowercase_stripped():
    """'lar' -> 'LAR' (canonical, already present)."""
    assert normalize("nfl", "lar") == "LAR"


def test_la_to_lar_nfl():
    assert normalize("nfl", "LA") == "LAR"


def test_lak_to_la_nhl():
    assert normalize("nhl", "LAK") == "LA"


def test_az_in_mlb():
    assert normalize("mlb", "AZ") == "ARI"


def test_az_in_nfl():
    assert normalize("nfl", "AZ") == "ARI"


def test_az_in_nba_raises():
    """NBA has no AZ alias, and AZ is not a canonical NBA code."""
    with pytest.raises(UnknownTeamCode):
        normalize("nba", "AZ")


def test_unknown_league_raises():
    with pytest.raises(UnknownTeamCode):
        normalize("WNBA", "NYL")


# ---------------------------------------------------------------------------
# normalize_optional
# ---------------------------------------------------------------------------


def test_normalize_optional_none():
    assert normalize_optional("nfl", None) is None


def test_normalize_optional_empty_string():
    assert normalize_optional("nfl", "") is None


def test_normalize_optional_typo_raises():
    with pytest.raises(UnknownTeamCode):
        normalize_optional("nfl", "ZZZ")


def test_normalize_optional_valid():
    assert normalize_optional("nfl", "ARI") == "ARI"


# ---------------------------------------------------------------------------
# is_canonical
# ---------------------------------------------------------------------------


def test_is_canonical_true():
    assert is_canonical("nfl", "ARI") is True


def test_is_canonical_false_unknown():
    assert is_canonical("nfl", "ZZZ") is False


def test_is_canonical_false_alias():
    assert is_canonical("nfl", "LA") is False  # LA is an alias, not canonical


def test_is_canonical_non_franchise():
    """Non-franchise codes are NOT canonical."""
    assert is_canonical("nba", "STRIPES") is False
    assert is_canonical("nba", "STARS") is False
    assert is_canonical("nba", "WORLD") is False


def test_is_canonical_unknown_league():
    assert is_canonical("WNBA", "NYL") is False


# ---------------------------------------------------------------------------
# NBA non-franchise codes
# ---------------------------------------------------------------------------


def test_nba_non_franchise_normalize_passthrough():
    """Non-franchise codes normalize to themselves."""
    assert normalize("nba", "STRIPES") == "STRIPES"
    assert normalize("nba", "STARS") == "STARS"
    assert normalize("nba", "WORLD") == "WORLD"


def test_nba_non_franchise_normalize_case_insensitive():
    assert normalize("nba", "stripes") == "STRIPES"


# ---------------------------------------------------------------------------
# normalize_position
# ---------------------------------------------------------------------------


def test_normalize_position_k_to_pk():
    assert normalize_position("nfl", "K") == "PK"


def test_normalize_position_canonical_to_itself():
    assert normalize_position("nfl", "PK") == "PK"
    assert normalize_position("nfl", "QB") == "QB"
    assert normalize_position("nfl", "WR") == "WR"


def test_normalize_position_quarterback_raises():
    with pytest.raises(UnknownPositionCode):
        normalize_position("nfl", "QUARTERBACK")


def test_normalize_position_olb_to_lb():
    assert normalize_position("nfl", "OLB") == "LB"


def test_normalize_position_fs_to_s():
    assert normalize_position("nfl", "FS") == "S"


def test_normalize_position_ss_to_s():
    assert normalize_position("nfl", "SS") == "S"


def test_normalize_position_saf_to_s():
    assert normalize_position("nfl", "SAF") == "S"


def test_normalize_position_nt_to_dt():
    assert normalize_position("nfl", "NT") == "DT"


def test_normalize_position_ol_to_g():
    assert normalize_position("nfl", "OL") == "G"


def test_normalize_position_ilb_to_lb():
    assert normalize_position("nfl", "ILB") == "LB"


def test_normalize_position_mlb_to_lb():
    assert normalize_position("nfl", "MLB") == "LB"


def test_normalize_position_unknown_league_raises():
    with pytest.raises(UnknownPositionCode):
        normalize_position("nba", "PG")


def test_normalize_position_whitespace_raises():
    with pytest.raises(UnknownPositionCode):
        normalize_position("nfl", "  ")


def test_normalize_position_none_raises():
    with pytest.raises(UnknownPositionCode):
        normalize_position("nfl", None)


# ---------------------------------------------------------------------------
# normalize_position_optional
# ---------------------------------------------------------------------------


def test_normalize_position_optional_none():
    assert normalize_position_optional("nfl", None) is None


def test_normalize_position_optional_empty_string():
    assert normalize_position_optional("nfl", "") is None


def test_normalize_position_optional_typo_raises():
    with pytest.raises(UnknownPositionCode):
        normalize_position_optional("nfl", "ZZZ")


def test_normalize_position_optional_valid():
    assert normalize_position_optional("nfl", "QB") == "QB"


# ---------------------------------------------------------------------------
# All canonical position codes normalise to themselves
# ---------------------------------------------------------------------------


def test_all_canonical_positions_normalize_to_themselves():
    """Every canonical position normalizes to itself, except those that
    are alias sources (OLB->LB, etc.)."""
    for code in CANONICAL_POSITIONS["nfl"]:
        expected = POSITION_ALIASES["nfl"].get(code, code)
        assert normalize_position("nfl", code) == expected


# ---------------------------------------------------------------------------
# Edge: strip + uppercase for positions
# ---------------------------------------------------------------------------


def test_normalize_position_lowercase_stripped():
    assert normalize_position("nfl", "qb") == "QB"


def test_normalize_position_trailing_space():
    assert normalize_position("nfl", "QB ") == "QB"
