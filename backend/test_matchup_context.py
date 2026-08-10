"""Tests for matchup_context — the pregame facts read off the ESPN summary payload.

Fixtures are trimmed from real 2026 Leagues Cup payloads (Santos at Chicago Fire,
401863605, final; Pachuca at Charlotte, 401863612, pre-kickoff) so the shapes are the
publisher's, not ones we invented.
"""
import matchup_context as mc


def _lfg(abbrev, name, results, league):
    """lastFiveGames entry. results are OLDEST FIRST, the way ESPN orders them."""
    return {
        "team": {"abbreviation": abbrev, "displayName": name},
        "events": [{"gameResult": r, "score": "1-0", "atVs": "vs",
                    "opponent": {"abbreviation": "OPP"},
                    "leagueAbbreviation": league} for r in results],
    }


def _group(division_header, teams, wins, losses, ties, played):
    return {
        "divisionHeader": division_header,
        "standings": {"entries": [
            {"team": t, "stats": [
                {"name": "wins", "value": w}, {"name": "losses", "value": l},
                {"name": "ties", "value": d}, {"name": "gamesPlayed", "value": p},
            ]} for t, w, l, d, p in zip(teams, wins, losses, ties, played)
        ]},
    }


def _payload():
    """Two-group cross-league tournament: Liga MX labelled, MLS not — as ESPN serves it."""
    return {
        "header": {
            "season": {"name": "2026 Leagues Cup, League Phase"},
            "competitions": [{"notes": [{"text": "Chicago Fire FC advances."}]}],
        },
        "lastFiveGames": [
            _lfg("CHI", "Chicago Fire FC", ["L", "L", "W", "W", "W"], "MLS"),
            _lfg("SAN", "Santos", ["L", "L", "L", "L", "L"], "Liga MX"),
        ],
        "standings": {"groups": [
            _group("Liga MX", ["Santos", "América"], [5, 6], [11, 11], [2, 1], [18, 18]),
            _group(None, ["Chicago Fire FC", "Austin FC"], [11, 11], [5, 6], [2, 1], [18, 18]),
        ]},
        "leaders": [
            {"team": {"displayName": "Chicago Fire FC"}, "leaders": [
                {"displayName": "Total Shots", "leaders": [
                    {"displayValue": "6", "athlete": {"displayName": "Robert Lewandowski"}}]},
            ]},
        ],
    }


def test_streak_is_stated_plainly():
    lines = "\n".join(mc.context_lines("lcup", "1", summary=_payload()))
    assert "Santos have lost 5 straight" in lines
    assert "Chicago Fire FC have won 3 straight" in lines


def test_form_is_most_recent_first():
    """ESPN orders lastFiveGames oldest-first. Reading it in publisher order would report
    Chicago's two old losses as its current run — the exact inversion this guards."""
    line = [l for l in mc._form(_payload()) if l.startswith("Chicago")][0]
    body = line.split("most recent first: ")[1]
    assert body.startswith("W "), body
    assert "have won 3 straight" in line


def test_origin_split_names_the_unlabelled_group_from_the_match():
    """ESPN labels Liga MX and leaves MLS as None. The label has to come from the clubs'
    own recent fixtures, not from a hardcoded assumption about which group is which."""
    line = mc._origin_split(_payload())[0]
    assert "Liga MX against MLS" in line
    assert "Liga MX clubs 11-22-3" in line
    assert "MLS clubs 22-11-3" in line
    assert "Across 36 matches" in line


def test_origin_split_silent_when_the_groups_describe_different_match_counts():
    """Two groups summing to different totals means they are not two halves of one set of
    cross-league fixtures, so the whole derivation is void — say nothing rather than a
    number that looks authoritative."""
    d = _payload()
    d["standings"]["groups"][1]["standings"]["entries"][0]["stats"][3]["value"] = 99
    assert mc._origin_split(d) == []


def test_origin_split_silent_for_an_ordinary_league_table():
    d = _payload()
    d["standings"]["groups"] = d["standings"]["groups"][:1]
    assert mc._origin_split(d) == []


def test_leaders_carry_the_publishers_own_value_wording():
    """Pre-kickoff ESPN writes 'Matches: 2, Goals: 2'; after full time it is a bare number.
    Reformatting either one risks asserting a per-match stat is a tournament total."""
    d = _payload()
    d["leaders"][0]["leaders"][0]["leaders"][0]["displayValue"] = "Matches: 2, Goals: 2"
    line = mc._leaders(d)[0]
    assert "Robert Lewandowski (Matches: 2, Goals: 2)" in line


def test_goals_outrank_shots_whatever_order_espn_used():
    """After full time ESPN puts Total Shots first, so taking the first category surfaced
    Lewandowski's 6 shots for Chicago while the club's scorer — Cuypers, 13 in 11 — never
    reached the desk. Production leads."""
    d = _payload()
    d["leaders"][0]["leaders"] = [
        {"displayName": "Total Shots", "leaders": [
            {"displayValue": "6", "athlete": {"displayName": "Robert Lewandowski"}}]},
        {"displayName": "Goals", "leaders": [
            {"displayValue": "Matches: 11, Goals: 13", "athlete": {"displayName": "Hugo Cuypers"}}]},
    ]
    line = mc._leaders(d)[0]
    assert line.index("Cuypers") < line.index("Lewandowski")


def test_an_unranked_category_keeps_its_published_place_behind_the_ranked_ones():
    d = _payload()
    d["leaders"][0]["leaders"] = [
        {"displayName": "Accurate Passes", "leaders": [
            {"displayValue": "76", "athlete": {"displayName": "Joel Waterman"}}]},
        {"displayName": "Goals", "leaders": [
            {"displayValue": "2", "athlete": {"displayName": "A Scorer"}}]},
    ]
    line = mc._leaders(d)[0]
    assert line.index("A Scorer") < line.index("Joel Waterman")


def test_phase_and_advancement_note():
    lines = mc._phase(_payload())
    assert "Competition: 2026 Leagues Cup, League Phase." in lines
    assert "Chicago Fire FC advances." in lines


def test_a_draw_run_is_not_a_streak():
    assert mc._streak(["D", "D", "D"]) == ""


def test_single_result_is_not_a_streak():
    assert mc._streak(["W", "L", "L"]) == ""


def test_everything_fails_soft_on_junk():
    for junk in ({}, {"standings": None}, {"lastFiveGames": [{}]}, {"leaders": [{"team": {}}]}):
        assert isinstance(mc.context_lines("lcup", "1", summary=junk), list)


def test_a_fetch_that_raises_yields_no_lines():
    def boom(league, game_id):
        raise RuntimeError("ESPN is down")
    assert mc.context_lines("lcup", "1", fetch=boom) == []
