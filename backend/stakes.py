"""stakes.py — what each team is playing for in THIS game.

The context layer generate_game_story was starving without (the Brazil/Norway lesson: a
knockout match previewed by reciting group-stage point differentials, because group records
were the only facts the model had). Every line returned here is a mathematically certain,
data-derived fact — no speculation, so the story prompt's no-invention rule holds.

Fail-soft by contract: any error → [] and the story simply gets no stakes lines this pass.
"""
import datetime as dt
import warnings
from contextlib import closing

import espn_client as espn
import team_codes

# Leagues with a stakes model. generate_game_story uses this to decide whether a cached
# pre-stakes story is final (league unsupported) or provisional (regenerate once, with stakes).
# NFL is not listed on purpose: its stakes are rarely certain, so a listed league would leave
# most NFL stories provisional and re-run their generation pipeline on every request (no LLM
# call). NFL stories still get stakes lines whenever they are written.
SUPPORTED = {"wc", "mlb", "nfl"}

# `site.web.api`, NOT `site.api`: the latter is walled from this box and 403s every time.
# This pointed at the walled host and so `_mlb` raised on every call since it was written,
# which the fail-soft contract below turned into an empty list. Measured 2026-08-19 from the
# spend log: 2,607 requests in one day, 403 every one, and every MLB story generated with no
# stakes lines at all. The two hosts serve the identical path (261 KB, both leagues).
_MLB_STANDINGS = "https://site.web.api.espn.com/apis/v2/sports/baseball/mlb/standings?level=3"


def for_matchup(league, ab_a, ab_b, season=None):
    """-> list of stakes strings for the two teams (either order). Empty when the league has
    no stakes model yet or data is unavailable. `season` is the regular-season year; NFL needs
    it, and a postseason game passes None because the NFL model describes the regular season."""
    league = (league or "").lower()
    try:
        if league == "wc":
            return _wc(ab_a, ab_b)
        if league == "mlb":
            return _mlb(ab_a, ab_b)
        if league == "nfl":
            return _nfl(ab_a, ab_b, season)
    except Exception as e:
        # Still fail-soft: a story without stakes beats no story. But it is no longer
        # SILENT. The whole point of this module is that stories were starving without it,
        # so "returns nothing" and "is broken" must not look the same from outside.
        warnings.warn(f"stakes: {league} lookup failed, story gets no stakes lines: {e!r}",
                      stacklevel=2)
        return []
    return []


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ── World Cup ────────────────────────────────────────────────────────────────────────────
# 2026 format: 12 groups, top 2 advance plus best third-placed teams — so "eliminated" is
# only certain in extreme cases; we assert only what the table makes certain (clinched
# top-2) and otherwise state position/points plainly.

def _wc(ab_a, ab_b):
    groups = espn.group_standings("wc")
    if not groups:
        return []
    lines = []
    complete = all(r["played"] >= 3 for g in groups for r in g["rows"]) if groups else False
    for ab in (ab_a, ab_b):
        for g in groups:
            for r in g["rows"]:
                if r["abbrev"] != ab:
                    continue
                if complete:
                    lines.append(
                        f"{r['name']} reached the knockouts finishing {_ord(r['rank'])} in "
                        f"{g['group']} ({r['wins']}-{r['draws']}-{r['losses']}, {r['points']} pts, "
                        f"{'+' if r['gd'] >= 0 else ''}{r['gd']} GD).")
                else:
                    lines.append(_wc_group_scenario(g, r))
    if complete and lines:
        lines.append("This is a knockout match: single elimination — the loser goes home.")
    return lines


def _wc_group_scenario(g, r):
    rows = g["rows"]
    remaining = lambda x: max(0, 3 - x["played"])
    others = [x for x in rows if x["abbrev"] != r["abbrev"]]
    # Clinched top-2: at most one other team can still reach a points total above ours.
    can_finish_above = sum(1 for x in others if x["points"] + 3 * remaining(x) > r["points"])
    if can_finish_above <= 1 and remaining(r) >= 0:
        return (f"{r['name']} have clinched a top-2 finish in {g['group']} "
                f"({r['points']} pts with {remaining(r)} to play).")
    return (f"{r['name']} sit {_ord(r['rank'])} in {g['group']} with {r['points']} pts and "
            f"{remaining(r)} group game(s) left — top 2 advance (plus best thirds).")


# ── MLB ──────────────────────────────────────────────────────────────────────────────────

def _mlb(ab_a, ab_b):
    d = espn._get(_MLB_STANDINGS, ttl=900)
    want = {ab_a, ab_b}
    lines = []
    for lg in d.get("children", []):
        for div in lg.get("children", []) or []:
            entries = div.get("standings", {}).get("entries", [])
            div_name = (div.get("name") or "").replace("American League", "AL").replace(
                "National League", "NL")
            for i, e in enumerate(entries):
                ab = (e.get("team") or {}).get("abbreviation")
                if ab not in want:
                    continue
                stats = {s.get("type"): s.get("displayValue") for s in e.get("stats", [])}
                gb = stats.get("gamesbehind", "-")
                seed = stats.get("playoffseed")
                seed_txt = ""
                if seed and seed.isdigit():
                    s_n = int(seed)
                    seed_txt = (f"; current playoff seed {s_n}" if s_n <= 6
                                else "; currently outside the playoff picture")
                if gb in ("-", "0"):
                    lines.append(f"{ab} lead the {div_name}{seed_txt}.")
                else:
                    lines.append(f"{ab} are {_ord(i + 1)} in the {div_name}, {gb} games back{seed_txt}.")
    return lines


# ── NFL ──────────────────────────────────────────────────────────────────────────────────
# Certain facts only, from the published schedule (nfl_schedule, nflverse) and the division
# map (nfl_teams). Seven seeds per conference: four division winners, then three wild cards,
# the best teams that did not win their division. Every claim is a strict inequality between
# what a team has already won and the most another team can still reach, so no tiebreaker can
# reverse it. A tie is half a win.

def _nfl(ab_a, ab_b, season):
    if season is None:
        return []
    from _core import _db
    with closing(_db()) as con:
        games = [dict(r) for r in con.execute(
            "SELECT home_team, away_team, home_score, away_score, gameday FROM nfl_schedule "
            "WHERE season=? AND game_type='REG'", (season,)).fetchall()]
        teams = {r["team"]: dict(r) for r in con.execute(
            "SELECT team, conference, division, team_name FROM nfl_teams WHERE season=?",
            (season,)).fetchall()}
    # A schedule that has not caught up with the calendar makes every "games left" count wrong,
    # so nothing is stated from it. Past games with no score are the symptom.
    today = str(espn._ny_date(dt.datetime.now(dt.timezone.utc)))
    behind = [g for g in games if not _nfl_scored(g) and g["gameday"] < today]
    if behind:
        warnings.warn(f"stakes: nfl {season} schedule has {len(behind)} past game(s) with no "
                      f"score, no NFL stakes this pass", stacklevel=2)
        return []
    lo, hi = _nfl_bounds(games, teams)
    lines = (_nfl_stake(team_codes.normalize("nfl", ab), teams, lo, hi) for ab in (ab_a, ab_b))
    return [line for line in lines if line]


def _nfl_scored(game):
    return game["home_score"] is not None and game["away_score"] is not None


def _nfl_bounds(games, teams):
    """-> (lo, hi): per team, the points it already has and the most it can still reach.
    A win is one point, a tie half a point; an unplayed game is worth up to one point."""
    lo = {t: 0.0 for t in teams}
    hi = {t: 0.0 for t in teams}
    for g in games:
        if not _nfl_scored(g):
            for team in (g["home_team"], g["away_team"]):
                hi[team] += 1
            continue
        home, away = g["home_score"], g["away_score"]
        for team, mine, theirs in ((g["home_team"], home, away), (g["away_team"], away, home)):
            points = 1.0 if mine > theirs else 0.5 if mine == theirs else 0.0
            lo[team] += points
            hi[team] += points
    return lo, hi


def _nfl_stake(team, teams, lo, hi):
    """-> one certain stake line for `team`, or None while the standings leave it open."""
    me = teams[team]
    name = me["team_name"] or team
    div = me["division"]
    rivals = [t for t in teams if t != team and teams[t]["division"] == div]
    if all(lo[team] > hi[r] for r in rivals):
        return f"{name} have clinched the {div} and a playoff spot."
    if not any(lo[r] > hi[team] for r in rivals):
        return None
    # No division title is possible now. Out of the playoffs if three teams are certain to
    # finish ahead of this one and certain not to win their own division: those three take the
    # wild cards before it can.
    def sure_non_winner(o):
        return any(lo[p] > hi[o] for p in teams
                   if p != o and teams[p]["division"] == teams[o]["division"])
    ahead = [o for o in teams
             if o != team and teams[o]["conference"] == me["conference"]
             and lo[o] > hi[team] and sure_non_winner(o)]
    if len(ahead) >= 3:
        return f"{name} are eliminated from the playoffs."
    return f"{name} can no longer win the {div}."
