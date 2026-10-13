"""nfl_seeding.py -- NFL playoff seeding for one conference, by the NFL's own tiebreaking procedure.

Source: nfl.com "NFL Tiebreaking Procedures" (https://www.nfl.com/standings/tie-breaking-procedures),
fetched 2026-10-11; the text is kept in docs/REFERENCE-nfl-tiebreaking-procedures-2026-10-11.md.
Every step below is that page's step, in that page's order. Nothing is skipped: the points steps,
net touchdowns and the coin toss are all here.

Seeds: four division winners, then wild cards (3 since 2020, 2 before). Division winners are
ordered by record, ties by the wild-card procedure ("To determine home-field priority among
division winners, apply Wild Card tiebreakers"). Wild cards are named one at a time.

Division ties (two clubs, or three or more):
  1 head-to-head (record in games among the clubs)   2 division record   3 common games
  4 conference record   5 strength of victory   6 strength of schedule
  7 combined ranking among conference teams in points scored and allowed
  8 combined ranking among all teams   9 net points in common games   10 net points, all games
  11 net touchdowns, all games   12 coin toss
Wild-card ties, clubs from different divisions:
  two clubs:  head-to-head if applicable, conference record, common games (min 4), SoV, SoS,
              combined ranking (conference), combined ranking (all), net points in conference
              games, net points (all), net touchdowns, coin toss
  three+:     step 1 keeps only the highest-ranked club of each division (by the division
              tiebreaker, and that within-division order is kept for every later wild card);
              then head-to-head SWEEP (one club beat each other club, or lost to each), and the
              same list from conference record on.
Restarts ("Other Tie-Breaking Procedures"): whenever a step eliminates clubs, the clubs still tied
start over at step 1 of the two-club format (two left) or of the three-club format (three or more;
for wild cards that is step 2, the division reduction having been applied). When one club wins a
tiebreaker, the others start over the same way to be ordered among themselves.

Values the page defines elsewhere: ties count as half a win; combined ranking adds the two
positions, lowest wins, tied teams share a position ("if Team A and Team B are tied for first ...
each is assigned 1, and if Team C is third its ranking will still be 3"). Strength of victory and
schedule are in nfl_standings.

Not applicable is not the same as tied: head-to-head when the clubs did not play, a sweep when no
club swept, common games with fewer than four opponents (wild card), net touchdowns when the input
has no touchdown counts. Such a step is passed over, as the page says ("if applicable").

Coin toss: with an `rng`, a real random draw; without one, alphabetical, so a historical check is
reproducible. Either way the toss is recorded in COIN_FLAGS. DECISIONS records which step decided
each tie, so a result can be explained.
"""
from __future__ import annotations

import nfl_standings as st

COIN_FLAGS = []
DECISIONS = []
EPS = 1e-12


def _pct(rec):
    w, l, t = rec
    n = w + l + t
    return (w + 0.5 * t) / n if n else None


# ── step values: dict code -> number, higher is better; None means not applicable ────────────────

def _h2h(group, teams):
    codes = {t.code for t in group}
    out = {}
    for t in group:
        p = _pct(t.record(lambda r: r.opp in codes and r.opp != t.code))
        if p is None:
            return None
        out[t.code] = p
    return out


def _h2h_two(group, teams):
    a, b = group
    if st.head_to_head(a, b) is None:
        return None                                   # "head-to-head, if applicable"
    return _h2h(group, teams)


def _sweep(group, teams):
    """One club beat each of the others, or lost to each of the others."""
    codes = {t.code for t in group}
    for t in group:
        others = codes - {t.code}
        rs = [r for r in t.results if r.opp in others]
        if {r.opp for r in rs} != others:
            continue
        if all(r.outcome == "W" for r in rs):
            return {u.code: (1.0 if u is t else 0.0) for u in group}
        if all(r.outcome == "L" for r in rs):
            return {u.code: (0.0 if u is t else 1.0) for u in group}
    return None


def _division(group, teams):
    return {t.code: _pct(st.division_record(t, teams)) for t in group}


def _conference(group, teams):
    return {t.code: _pct(st.conference_record(t, teams)) for t in group}


def _common_set(group):
    return set.intersection(*[st.opponents(t) for t in group]) - {t.code for t in group}


def _common(minimum):
    def step(group, teams):
        common = _common_set(group)
        if not common or len(common) < minimum:
            return None
        out = {t.code: _pct(t.record(lambda r: r.opp in common)) for t in group}
        return None if any(v is None for v in out.values()) else out
    return step


def _sov(group, teams):
    return {t.code: st.strength_of_victory(t, teams) for t in group}


def _sos(group, teams):
    return {t.code: st.strength_of_schedule(t, teams) for t in group}


def _positions(values, higher_better):
    """Competition ranking: tied teams share the position, the next team keeps its own."""
    out = {}
    for code, v in values.items():
        better = sum(1 for w in values.values() if (w > v + EPS if higher_better else w < v - EPS))
        out[code] = better + 1
    return out


def _combined_ranking(conference_only):
    def step(group, teams):
        conf = group[0].conference
        pool = [t for t in teams.values() if not conference_only or t.conference == conf]
        pf = {t.code: sum(r.pts_for for r in t.results) for t in pool}
        pa = {t.code: sum(r.pts_against for r in t.results) for t in pool}
        rf, ra = _positions(pf, True), _positions(pa, False)
        return {t.code: -(rf[t.code] + ra[t.code]) for t in group}
    return step


def _net_points(scope):
    def step(group, teams):
        if scope == "common":
            common = _common_set(group)
            if not common:
                return None
            keep = lambda t, r: r.opp in common
        elif scope == "conference":
            keep = lambda t, r: teams[r.opp].conference == t.conference
        else:
            keep = lambda t, r: True
        return {t.code: sum(r.pts_for - r.pts_against for r in t.results if keep(t, r))
                for t in group}
    return step


def _net_touchdowns(group, teams):
    out = {}
    for t in group:
        if any(r.tds_for is None or r.tds_against is None for r in t.results):
            return None
        out[t.code] = sum(r.tds_for - r.tds_against for r in t.results)
    return out


DIVISION_STEPS = [
    ("head-to-head", _h2h), ("division record", _division), ("common games", _common(1)),
    ("conference record", _conference), ("strength of victory", _sov),
    ("strength of schedule", _sos), ("combined ranking, conference", _combined_ranking(True)),
    ("combined ranking, all", _combined_ranking(False)),
    ("net points, common games", _net_points("common")), ("net points, all", _net_points("all")),
    ("net touchdowns", _net_touchdowns),
]
_WC_TAIL = [
    ("conference record", _conference), ("common games (min 4)", _common(4)),
    ("strength of victory", _sov), ("strength of schedule", _sos),
    ("combined ranking, conference", _combined_ranking(True)),
    ("combined ranking, all", _combined_ranking(False)),
    ("net points, conference", _net_points("conference")), ("net points, all", _net_points("all")),
    ("net touchdowns", _net_touchdowns),
]
WILDCARD_TWO = [("head-to-head", _h2h_two)] + _WC_TAIL
WILDCARD_MULTI = [("head-to-head sweep", _sweep)] + _WC_TAIL


def _coin(group, rng):
    codes = tuple(sorted(t.code for t in group))
    COIN_FLAGS.append(codes)
    if rng is None:
        return sorted(group, key=lambda t: t.code)[0]
    return group[rng.randrange(len(group))]


def winner(group, teams, kind, rng=None):
    """The club that wins a tie among `group`. kind: 'division' or 'wildcard' (clubs from
    different divisions, the division reduction already applied)."""
    group = list(group)
    if len(group) == 1:
        return group[0]
    if kind == "division":
        steps = DIVISION_STEPS
    else:
        steps = WILDCARD_TWO if len(group) == 2 else WILDCARD_MULTI
    for name, fn in steps:
        vals = fn(group, teams)
        if vals is None or any(v is None for v in vals.values()):
            continue                                  # not applicable to this group
        best = max(vals.values())
        keep = [t for t in group if vals[t.code] >= best - EPS]
        if len(keep) == len(group):
            continue
        if len(keep) == 1:
            DECISIONS.append((tuple(sorted(t.code for t in group)), name, keep[0].code))
            return keep[0]
        return winner(keep, teams, kind, rng)          # eliminated clubs: the rest restart
    w = _coin(group, rng)
    DECISIONS.append((tuple(sorted(t.code for t in group)), "coin toss", w.code))
    return w


def order(group, teams, kind, rng=None):
    """Order a group tied on record: find the winner, then the rest start over."""
    rest, out = list(group), []
    while rest:
        w = winner(rest, teams, kind, rng)
        out.append(w)
        rest = [t for t in rest if t is not w]
    return out


def _by_record(group):
    blocks = {}
    for t in group:
        blocks.setdefault(round(t.pct, 9), []).append(t)
    return [blocks[k] for k in sorted(blocks, reverse=True)]


def division_order(members, teams, rng=None):
    """All clubs of one division, best first, by record then the division tiebreaker."""
    out = []
    for block in _by_record(members):
        out.extend(order(block, teams, "division", rng))
    return out


def seeds_for_conference(teams, conference, n_seeds=7, rng=None):
    """[(seed, code)] for one conference, seed 1 first. n_seeds: 7 since 2020, 6 before."""
    if n_seeds not in (6, 7):
        raise ValueError("n_seeds must be 6 or 7")
    conf = [t for t in teams.values() if t.conference == conference]
    by_div = {}
    for t in conf:
        by_div.setdefault(t.division, []).append(t)
    if len(by_div) != 4:
        raise ValueError("%s has %d divisions, expected 4" % (conference, len(by_div)))
    div_rank = {}
    winners = []
    for div in sorted(by_div):
        ranked = division_order(by_div[div], teams, rng)
        winners.append(ranked[0])
        for i, t in enumerate(ranked):
            div_rank[t.code] = i
    seeded = []
    for block in _by_record(winners):
        seeded.extend(order(block, teams, "wildcard", rng))   # all different divisions
    pool = [t for t in conf if t not in winners]
    for _ in range(n_seeds - 4):
        top = _by_record(pool)[0]
        if len(top) == 1:
            pick = top[0]
        elif len({t.division for t in top}) == 1:
            pick = min(top, key=lambda t: div_rank[t.code])     # division tiebreaker
        else:
            reduced = {}
            for t in sorted(top, key=lambda t: div_rank[t.code]):
                reduced.setdefault(t.division, t)              # highest-ranked per division
            pick = winner(list(reduced.values()), teams, "wildcard", rng)
        seeded.append(pick)
        pool.remove(pick)
    return [(i + 1, t.code) for i, t in enumerate(seeded)]


def n_seeds_for(season):
    """Seven seeds per conference since the 2020 season, six before."""
    return 7 if season >= 2020 else 6
