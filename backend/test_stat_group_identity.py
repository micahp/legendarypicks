"""Identify an unnamed stat group by a label only it has, and never derive a
value the publisher already publishes.

Two defects in the same block of `_find_player_stat`, both dead for MLB today
(the MLB branch of settle_game returns before reaching the ESPN reader) and both
loaded for the day another league's props ship.

**1. Non-empty intersection is not identity.** ESPN sometimes returns
`name: None` for a stat group, so the group was identified by whether its labels
intersected a batting or pitching set at all. Those sets overlap:

    _BATTING_LABELS & _PITCHING_LABELS == {'BB', 'H', 'HR', 'K', 'R'}

A pitching line publishes H, R, BB, K and HR, so it satisfies the "batting"
test — and a request for a batter's hits would read the pitcher's hits allowed.
Identify on a label the other group does NOT have: AB/RBI/AVG for batting,
IP/ER/ERA for pitching.

**2. TB was derived as round(SLG x AB).** MLB publishes `totalBases` directly,
and this repo already reads it in `_MLB_BATTING_STATS`. A derivation where the
value is published is a reimplementation of someone else's definition with none
of their testing (published-first §1) — and this one is probably wrong on its own
terms: ESPN's AVG/OBP/SLG in a box score are season-to-date, so this multiplied a
season rate by a single game's at-bats. It is deleted rather than fixed: a box
score that does not report TB is a void.
"""
import settlement


def _group(labels, stats, name=None):
    return {"players": [{
        "team": {"abbreviation": "PHI", "displayName": "Philadelphia Phillies"},
        "statistics": [{"name": name, "labels": labels,
                        "athletes": [{"athlete": {"displayName": "Zack Wheeler", "id": "31005"},
                                      "stats": stats}]}],
    }]}


PITCHING_LABELS = ["IP", "H", "R", "ER", "BB", "K", "HR", "PC-ST", "ERA"]
PITCHING_STATS = ["6.0", "4", "2", "2", "1", "8", "1", "95-62", "3.21"]

BATTING_LABELS = ["AB", "R", "H", "RBI", "HR", "BB", "K", "AVG", "OBP", "SLG"]
BATTING_STATS = ["4", "1", "2", "1", "0", "0", "1", ".280", ".350", ".460"]


def test_a_pitching_line_does_not_answer_a_batting_question():
    """H is in both label sets. Asking for a batter's hits used to return the
    pitcher's hits ALLOWED — 4, not 2."""
    box = _group(PITCHING_LABELS, PITCHING_STATS)
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "batting", "H",
                                        espn_id="31005") is None


def test_a_batting_line_does_not_answer_a_pitching_question():
    box = _group(BATTING_LABELS, BATTING_STATS)
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "pitching", "K",
                                        espn_id="31005") is None


def test_an_unnamed_pitching_group_still_resolves_pitching():
    box = _group(PITCHING_LABELS, PITCHING_STATS)
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "pitching", "K",
                                        espn_id="31005") == 8.0


def test_an_unnamed_batting_group_still_resolves_batting():
    box = _group(BATTING_LABELS, BATTING_STATS)
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "batting", "RBI",
                                        espn_id="31005") == 1.0


def test_a_named_group_is_still_trusted():
    box = _group(PITCHING_LABELS, PITCHING_STATS, name="pitching")
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "pitching", "ER",
                                        espn_id="31005") == 2.0


def test_total_bases_is_never_derived_from_slugging():
    """SLG x AB = .460 x 4 = 1.84 -> 2. A plausible number, invented."""
    box = _group(BATTING_LABELS, BATTING_STATS)
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "batting", "TB",
                                        espn_id="31005") is None


def test_total_bases_is_read_when_it_is_published():
    labels = BATTING_LABELS + ["TB"]
    box = _group(labels, BATTING_STATS + ["5"])
    assert settlement._find_player_stat(box, "Zack Wheeler", "PHI", "batting", "TB",
                                        espn_id="31005") == 5.0
