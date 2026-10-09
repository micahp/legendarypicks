"""nfl_bracket_check.py -- do our seeds reproduce the playoff bracket that was actually played?

Published seed numbers are not in the database. What is in the database is the playoff schedule,
and seeds determine it:
  wild card:  2 v 7, 3 v 6, 4 v 5 in each conference (the higher seed is the home team)
  divisional: the 1 seed plays the lowest remaining seed; the other two play each other
              (re-seeding, the NFL rule since 2020)

So the check is: seeds computed from regular-season results alone must produce the same wild-card
pairings, and the same divisional pairings once the actual wild-card winners are used. A
misordered seed changes the pairings, so this fails when the seeding is wrong.

What this does NOT prove: it checks consequences, not the published numbers. Two seedings that
produce the same pairings are indistinguishable here.
"""
from __future__ import annotations

import nfl_seeding as sd
import nfl_standings as st



def team_map(con, season_for_map=2026):
    """code -> (conference, division) from nfl_teams. Valid for 2024-2026 (see nfl_standings)."""
    rows = con.execute("SELECT team, division FROM nfl_teams WHERE season = ?",
                       (season_for_map,)).fetchall()
    if len(rows) != 32:
        raise ValueError("nfl_teams has %d rows for %d, expected 32" % (len(rows), season_for_map))
    return {t: (st.conference_of(d), d) for t, d in rows}


def regular_games(con, season):
    return con.execute(
        "SELECT week, home_team, away_team, home_score, away_score FROM nfl_schedule "
        "WHERE season = ? AND game_type = 'REG' AND home_score IS NOT NULL "
        "AND away_score IS NOT NULL", (season,)).fetchall()


def playoff_games(con, season, game_type):
    return con.execute(
        "SELECT home_team, away_team, home_score, away_score FROM nfl_schedule "
        "WHERE season = ? AND game_type = ? ORDER BY game_id", (season, game_type)).fetchall()


def seeds_from_results(con, season):
    tmap = team_map(con)
    teams = st.build(tmap, regular_games(con, season))
    return {conf: sd.seeds_for_conference(teams, conf) for conf in ("AFC", "NFC")}


def expected_wild_card(seeds):
    """Unordered pairs (set of two codes) for 2v7, 3v6, 4v5 in one conference."""
    by = {s: c for s, c in seeds}
    return {frozenset((by[2], by[7])), frozenset((by[3], by[6])), frozenset((by[4], by[5]))}


def winners(games):
    out = set()
    for h, a, hs, as_ in games:
        out.add(h if hs > as_ else a)
    return out


def check(seeds_by_conf, wc_rows, div_rows, conf_of):
    """Return a report dict. ok is True only if every conference matches on both rounds."""
    report = {"ok": True, "conferences": {}}
    for conf in ("AFC", "NFC"):
        seeds = seeds_by_conf[conf]
        seeded = {c for _, c in seeds}
        conf_wc = [r for r in wc_rows if conf_of.get(r[0]) == conf]
        conf_div = [r for r in div_rows if conf_of.get(r[0]) == conf]
        wc_pairs = {frozenset((h, a)) for h, a, _, _ in conf_wc}
        exp_wc = expected_wild_card(seeds)
        wc_ok = wc_pairs == exp_wc
        played = {h for h, _, _, _ in conf_wc} | {a for _, a, _, _ in conf_wc}
        wc_field_ok = played == seeded - {seeds[0][1]}
        # divisional: the 1 seed plays the lowest-seeded WC winner; the other two play
        winners_wc = winners(conf_wc)
        by_seed = {c: s for s, c in seeds}
        ranked_winners = sorted(winners_wc, key=lambda c: by_seed.get(c, 99))
        top = seeds[0][1]
        if len(ranked_winners) == 3:
            lowest = ranked_winners[-1]
            middle = [c for c in ranked_winners if c not in (lowest,)]
            exp_div = {frozenset((top, lowest)), frozenset((middle[0], middle[1]))}
        else:
            exp_div = None
        div_pairs = {frozenset((h, a)) for h, a, _, _ in conf_div}
        div_ok = exp_div is not None and div_pairs == exp_div
        conf_ok = wc_ok and wc_field_ok and div_ok
        report["conferences"][conf] = {
            "seeds": seeds, "wild_card_pairs_match": wc_ok, "wild_card_field_match": wc_field_ok,
            "divisional_pairs_match": div_ok, "expected_wc": sorted(sorted(p) for p in exp_wc),
            "actual_wc": sorted(sorted(p) for p in wc_pairs),
            "expected_div": None if exp_div is None else sorted(sorted(p) for p in exp_div),
            "actual_div": sorted(sorted(p) for p in div_pairs), "ok": conf_ok,
        }
        report["ok"] = report["ok"] and conf_ok
    return report


def validate_season(con, season):
    seeds = seeds_from_results(con, season)
    tmap = team_map(con)
    conf_of = {t: c for t, (c, _) in tmap.items()}
    wc = playoff_games(con, season, "WC")
    dv = playoff_games(con, season, "DIV")
    return check(seeds, wc, dv, conf_of)
