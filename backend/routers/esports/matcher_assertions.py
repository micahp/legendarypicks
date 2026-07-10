"""Focused regression assertions for esports team identity, match clustering, and PS enrichment.

Run from the backend directory:

    venv/bin/python routers/esports/matcher_assertions.py

The cases are intentionally synthetic: they test matcher policy without depending on live APIs or
mutable tournament data.
"""

import os
import sys


BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BACKEND)

from routers.esports import pandascore, slate  # noqa: E402
from routers.esports.common import _canon_team_x  # noqa: E402


def _assert(condition, label):
    if not condition:
        raise AssertionError(label)
    print(f"[PASS] {label}")


def _row(team_a, team_b, league, start=1_783_500_000_000, origin="bovada"):
    return {
        "title": "CS2",
        "league": league,
        "teamA": team_a,
        "teamB": team_b,
        "startTime": start,
        "_origin": origin,
    }


def _indexed_match(team_a, team_b, scheduled_at, score_a, score_b, winner="a"):
    op0 = {"id": 101, "name": team_a, "acronym": None, "slug": None}
    op1 = {"id": 202, "name": team_b, "acronym": None, "slug": None}
    match = {
        "id": 9001,
        "status": "finished",
        "scheduled_at": scheduled_at,
        "opponents": [{"opponent": op0}, {"opponent": op1}],
        "results": [{"team_id": 101, "score": score_a}, {"team_id": 202, "score": score_b}],
        "winner_id": 101 if winner == "a" else 202,
        "streams_list": [],
        "league": {"name": "Regression League"},
    }
    n0, n1 = pandascore._ps_names(op0), pandascore._ps_names(op1)
    tk0 = [t for t in (pandascore._tokset(n) for n in n0) if t]
    tk1 = [t for t in (pandascore._tokset(n) for n in n1) if t]
    cs0 = {_canon_team_x(team_a)}
    cs1 = {_canon_team_x(team_b)}
    return match, op0, op1, n0, n1, tk0, tk1, cs0, cs1


def _team_policy_assertions():
    positives = [
        ("9z", "9z Globant"),
        ("Keyd", "Keyd Stars"),
        ("LVLUP", "Level UP"),
        ("NIP", "Ninjas in Pyjamas"),
        ("Anyone's Legend", "AG.AL International"),
        ("SYF", "SYGaming"),
        ("WBT", "Wrotberry"),
        ("Beşiktaş", "Besiktas"),
        ("TeamOrangeGaming", "Team Orange"),
        ("TheBoys", "The Boys"),
        ("JPlay", "Just Players"),
        ("BakS eSports", "BAKS Esports"),
        ("JUMBO TEAM", "Jumbo Team"),
    ]
    negatives = [
        ("MIBR", "MIBR LOS"),
        ("G2", "G2 HEL"),
        ("Team Secret", "Team Secret Whales"),
        ("GAM Esports", "GamerLegion"),
        ("GamerLegion", "Legion"),
        ("paiN", "Ready"),
        ("Pain Gaming", "paiN Academy"),
        ("ex-Marsborne", "Marsborne"),
        ("ex-Vexa", "Vexa"),
        ("LP", "largadosypelados"),
    ]
    for left, right in positives:
        _assert(slate._same_team(left, right), f"team aliases merge: {left} == {right}")
    for left, right in negatives:
        _assert(not slate._same_team(left, right), f"distinct teams stay split: {left} != {right}")


def _match_scope_assertions():
    league_a = "CCT South America — Series 3 2026 (Playoffs)"
    league_b = "CCT 2026 South America Series 3 (Playoffs)"
    lp = _row("Imperial", "LP", league_a)
    full = _row("Imperial", "largadosypelados", league_b, origin="carry")
    lp.update(finishedAt=1_783_505_000_000, finished=True, resultUnknown=True,
              winner=None, score=None)
    full.update(finishedAt=1_783_505_000_000, finished=True, resultUnknown=False,
                winner="a", score={"a": 2, "b": 0})
    _assert(slate._same_match_relaxed(lp, full), "LP merges only at same league and time")
    clustered = slate._cluster([lp, full])
    _assert(len(clustered) == 1, "LP duplicate clusters to one card")
    _assert(clustered[0].get("winner") == "a" and clustered[0].get("score") == {"a": 2, "b": 0}
            and clustered[0].get("resultUnknown") is False,
            "resolved full-name twin promotes an unknown LP archive")

    different_series = _row("Imperial", "largadosypelados",
                            "CCT 2026 South America Series 4 (Playoffs)", origin="carry")
    _assert(not slate._same_match_relaxed(lp, different_series),
            "LP does not merge across different league series")
    late = _row("Imperial", "largadosypelados", league_b,
                start=lp["startTime"] + slate._RELAXED_MERGE_MS + 1, origin="carry")
    _assert(not slate._same_match_relaxed(lp, late), "LP does not merge outside the time window")

    main = _row("Shared Opponent", "FaZe", league_a)
    academy = _row("Shared Opponent", "FaZe Academy", league_b, origin="carry")
    _assert(not slate._same_match_relaxed(main, academy),
            "same-league fallback keeps academy squads distinct")
    org = _row("Shared Opponent", "Marsborne", league_a)
    departed = _row("Shared Opponent", "ex-Marsborne", league_b, origin="carry")
    _assert(not slate._same_match_relaxed(org, departed),
            "same-league fallback keeps departed rosters distinct")


def _pandascore_assertions():
    scheduled = "2026-07-09T15:00:00Z"
    near_ms = pandascore._iso_to_ms(scheduled)
    original = pandascore._ps_indexed
    try:
        mibr = _indexed_match("MIBR LOS", "AG.AL International", scheduled, 2, 0)
        pandascore._ps_indexed = lambda include_running: [mibr]
        result = pandascore._ps_enrich("MIBR", "Anyone's Legend", include_running=False,
                                      near_ms=near_ms)
        _assert(result is not None, "PS allows lexical MIBR + canonical AG.AL evidence per side")
        _assert(result["winner"] == "a" and result["score"] == {"a": 2, "b": 0},
                "PS aligns the MIBR/AG.AL winner and score")

        syf = _indexed_match("Hero JiuJing", "SYGaming", scheduled, 3, 1)
        pandascore._ps_indexed = lambda include_running: [syf]
        result = pandascore._ps_enrich("Hero Jiujing", "SYF", include_running=False,
                                      near_ms=near_ms)
        _assert(result is not None, "PS resolves the SYF/SYGaming alias")
        _assert(result["winner"] == "a" and result["score"] == {"a": 3, "b": 1},
                "PS aligns the Hero Jiujing/SYF winner and score")

        too_far = near_ms + 37 * 3600 * 1000
        _assert(pandascore._ps_enrich("Hero Jiujing", "SYF", include_running=False,
                                     near_ms=too_far) is None,
                "PS alias matching still obeys the rematch time guard")
    finally:
        pandascore._ps_indexed = original


if __name__ == "__main__":
    _team_policy_assertions()
    _match_scope_assertions()
    _pandascore_assertions()
    print("\nAll matcher assertions passed.")
