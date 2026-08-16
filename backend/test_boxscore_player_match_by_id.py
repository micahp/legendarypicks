"""A prop is graded against the athlete the publisher names, not against a surname.

`_find_player_stat` matched an athlete when either the full name was a SUBSTRING
of the box score's display name, or — failing that — when the player's LAST TOKEN
appeared anywhere in it. Both are ambiguous where an exact key exists: ESPN puts
`athlete.id` on the same object as the stats.

The last-token rule is worse than it sounds. For "Michael Porter Jr." the token is
`"jr."`, which matches the first suffixed athlete on the team — a different person
entirely. Measured 2026-08-11: **1,568 players have a suffix as their match token**,
and NFL alone has **2,619 same-team surname groups**. This is latent rather than
live only because MLS/UFC resolve no markets today and MLB grades through the MLB
Stats API by `mlbam_id`; it goes live the day NBA/NFL/NHL props ship.

The substring rule fails too: "Will Smith" is a substring of "Will Smith Jr.", and
both catch on any name that contains another.

Order of preference, exact key first:

  1. `espn_id` on our row against `athlete.id` in the box score. No id in the box
     score means the player did not appear — a void, not a licence to guess.
  2. No `espn_id` on our row (MLB holds one for 852 of 2,441): exact name match
     after normalising case, punctuation and whitespace.
  3. Two athletes matching the same name: void. Fail closed.
"""
import settlement


def _box(*athletes, team="DEN"):
    return {"players": [{
        "team": {"abbreviation": team, "displayName": "Denver Nuggets"},
        "statistics": [{"name": "batting", "labels": ["AB", "R", "H", "RBI"],
                        "athletes": list(athletes)}],
    }]}


def _ath(name, stats, aid=None):
    a = {"displayName": name}
    if aid is not None:
        a["id"] = aid
    return {"athlete": a, "stats": stats}


PORTER = _ath("Michael Porter Jr.", ["4", "1", "2", "1"], aid="4278077")
BRAUN = _ath("Christian Braun", ["4", "0", "0", "0"], aid="4433134")
# The athlete the "jr." token reaches first when it is not Porter.
GORDON = _ath("Aaron Gordon Jr.", ["4", "3", "3", "3"], aid="3064290")


def test_the_publishers_id_decides():
    box = _box(GORDON, PORTER, BRAUN)
    assert settlement._find_player_stat(box, "Michael Porter Jr.", "DEN", "batting", "H",
                                        espn_id="4278077") == 2.0


def test_a_suffix_token_no_longer_reaches_a_different_person():
    """The bug, stated directly: "jr." matched the first suffixed athlete."""
    box = _box(GORDON, BRAUN)
    assert settlement._find_player_stat(box, "Michael Porter Jr.", "DEN", "batting", "H") is None


def test_an_id_that_is_not_in_the_box_score_is_a_dnp():
    box = _box(GORDON, BRAUN)
    assert settlement._find_player_stat(box, "Michael Porter Jr.", "DEN", "batting", "H",
                                        espn_id="4278077") is None


def test_the_id_wins_over_a_name_that_also_matches():
    """Two people can share a name; only one can share an id."""
    other = _ath("Will Smith", ["4", "0", "1", "0"], aid="111")
    ours = _ath("Will Smith", ["4", "2", "3", "2"], aid="222")
    assert settlement._find_player_stat(_box(other, ours, team="LAD"), "Will Smith", "LAD",
                                        "batting", "H", espn_id="222") == 3.0


def test_without_an_id_an_exact_name_still_resolves():
    """852 of 2,441 MLB players carry an espn_id; the rest must still grade."""
    box = _box(PORTER, BRAUN)
    assert settlement._find_player_stat(box, "Christian Braun", "DEN", "batting", "AB") == 4.0


def test_name_matching_ignores_case_punctuation_and_spacing():
    box = _box(PORTER)
    assert settlement._find_player_stat(box, "michael porter jr", "DEN", "batting", "H") == 2.0


def test_a_name_that_is_a_substring_of_another_does_not_match_it():
    """"Will Smith" used to match "Will Smith Jr." by substring."""
    box = _box(_ath("Will Smith Jr.", ["4", "1", "1", "1"]), team="LAD")
    assert settlement._find_player_stat(box, "Will Smith", "LAD", "batting", "H") is None


def test_two_athletes_with_the_same_name_and_no_id_void():
    box = _box(_ath("Will Smith", ["4", "0", "1", "0"]),
               _ath("Will Smith", ["4", "2", "3", "2"]), team="LAD")
    assert settlement._find_player_stat(box, "Will Smith", "LAD", "batting", "H") is None


def test_the_settle_path_selects_and_passes_the_espn_id_it_already_has():
    """Regression pin on the plumbing. The join to `players` was already there;
    only `name` and `team` were being read off it, so the exact key never left
    the database."""
    import inspect
    src = inspect.getsource(settlement.settle_game)
    assert "pl.espn_id" in src, "the query must select the id"
    assert "espn_id=prop[\"espn_id\"]" in src or "espn_id=prop['espn_id']" in src, \
        "and hand it to the matcher"
