"""nfl_seeding.py -- NFL playoff seeding for one conference (SPEC A, 5.2-5.3).

Rules (5.2, NFL since 2020): 7 teams per conference. Seeds 1-4 are the four division winners,
ordered by record. Seeds 5-7 are the three best non-division-winners by record. Only seed 1 gets a
bye.

Tiebreakers (5.3). A tied group is ranked by a list of criteria in order. Each criterion sorts the
group by a value; teams with equal values stay tied and move to the next criterion, which is
evaluated against that subgroup only (the NFL restarts the procedure for the tied teams).

  same division:       head-to-head, division record, common games (min 4), conference record,
                       strength of victory, strength of schedule
  different divisions: head-to-head, conference record, common games (min 4), strength of victory,
                       strength of schedule
  coin flip:           if still tied when the list runs out. Not random here: alphabetical, and
                       recorded in COIN_FLAGS. Any flag must be reported with the result.

Head-to-head value for a group: a team's record in games against the other teams still tied.
If a team in the group has played none of them, head-to-head does not apply and is skipped.
Common games value: a team's record against the opponents every tied team has played. If fewer
than four such opponents exist, the criterion does not apply and is skipped.

DEVIATIONS TO VERIFY against the NFL Record & Fact Book, "Tie-Breaking Procedures" (not yet cited
by version): the official multi-team procedure eliminates teams one at a time and restarts the
two-team rule. The restart here is per criterion, not per team. For the wild-card cut, the official
procedure first reduces the group to the highest-ranked team of each division; that step is not
implemented. The bracket validation (A4 part 3) is the check on whether these choices matter.
"""
from __future__ import annotations

import nfl_standings as st

COIN_FLAGS = []


def _rec_pct(rec):
    w, l, t = rec
    n = w + l + t
    return (w + 0.5 * t) / n if n else None


def _h2h_value(team, group):
    codes = {t.code for t in group if t is not team}
    rs = [r for r in team.results if r.opp in codes]
    if not rs:
        return None
    return _rec_pct((sum(r.outcome == "W" for r in rs), sum(r.outcome == "L" for r in rs),
                     sum(r.outcome == "T" for r in rs)))


def _common_value(team, group, teams):
    common = set.intersection(*[st.opponents(t) for t in group])
    if len(common) < 4:
        return None
    return _rec_pct(team.record(lambda r: r.opp in common))


def _criteria(same_division, teams):
    """Ordered list of (name, value_fn(team, group)). Division and conference values are fixed
    per team; head-to-head and common games depend on the tied group."""
    crit = [("head-to-head", lambda t, g: _h2h_value(t, g))]
    if same_division:
        crit.append(("division record",
                     lambda t, g: _rec_pct(st.division_record(t, teams))))
    crit.append(("common games",
                 lambda t, g: _common_value(t, g, teams)))
    crit.append(("conference record",
                 lambda t, g: _rec_pct(st.conference_record(t, teams))))
    crit.append(("strength of victory",
                 lambda t, g: st.strength_of_victory(t, teams)))
    crit.append(("strength of schedule",
                 lambda t, g: st.strength_of_schedule(t, teams)))
    return crit


def rank_group(group, teams, same_division, criteria=None):
    """Order a tied group. Every team in `group` appears exactly once in the result."""
    crit = criteria if criteria is not None else _criteria(same_division, teams)
    return _rank(list(group), crit, teams)


def _rank(group, crit, teams):
    if len(group) <= 1:
        return group
    if not crit:
        COIN_FLAGS.append(tuple(sorted(t.code for t in group)))
        return sorted(group, key=lambda t: t.code)
    name, fn = crit[0]
    values = {t.code: fn(t, group) for t in group}
    if all(v is None for v in values.values()):
        return _rank(group, crit[1:], teams)
    if any(v is None for v in values.values()):
        # Criterion applies to some teams only. It cannot separate them fairly: skip it.
        return _rank(group, crit[1:], teams)
    order = sorted(group, key=lambda t: -values[t.code])
    out, i = [], 0
    while i < len(order):
        j = i
        while j < len(order) and abs(values[order[j].code] - values[order[i].code]) < 1e-12:
            j += 1
        block = order[i:j]
        if len(block) == 1:
            out.extend(block)
        else:
            out.extend(_rank(block, crit[1:], teams))
        i = j
    return out


def _group_by_pct(teams):
    ordered = sorted(teams, key=lambda t: -t.pct)
    groups, current = [], []
    for t in ordered:
        if current and abs(current[0].pct - t.pct) > 1e-12:
            groups.append(current)
            current = []
        current.append(t)
    if current:
        groups.append(current)
    return groups


def _order_block(group, teams):
    """Order by pct. Each tied group uses division criteria only if all its members share a
    division, which is the only case where a division record means anything."""
    out = []
    for g in _group_by_pct(group):
        same = len({t.division for t in g}) == 1
        out.extend(rank_group(g, teams, same_division=same))
    return out


def seeds_for_conference(teams, conference):
    """Seven seeds for one conference. Returns [(seed, code)], seed 1 first.

    teams: code -> Team from nfl_standings.build (all 32). Only `conference` is seeded.
    """
    COIN_FLAGS.clear()
    conf_teams = [t for t in teams.values() if t.conference == conference]
    by_div = {}
    for t in conf_teams:
        by_div.setdefault(t.division, []).append(t)

    winners = []
    for div, members in sorted(by_div.items()):
        top = _group_by_pct(members)[0]
        winners.extend(rank_group(top, teams, same_division=True)[:1])
    ordered_winners = _order_block(winners, teams)

    winner_codes = {w.code for w in winners}
    rest = [t for t in conf_teams if t.code not in winner_codes]
    wild = _order_block(rest, teams)[:3]

    final = ordered_winners + wild
    return [(i + 1, t.code) for i, t in enumerate(final)]
