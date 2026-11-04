"""Skill lineups that carry from snap to snap, for SLC play calls (research, opt-in, not adopted).

With `--participation-field <table> --participation-field-sha256 <hash>` (rng protocol v2 only), the skill players on the
field form a lineup that persists across a team's offensive snaps. Each snap:

    lineup[t] = advance(lineup[t-1], grouping[t], roster, draws)

- grouping[t] is drawn from the team's transition from the previous grouping in the same situation cell. The team's
  transitions are shrunk to the league's, and the league's to the league's mix for the cell.
- A skill player on the field leaves with a hazard that depends on his position class and on his stint, the number of
  consecutive snaps he has already been on. A leave is replaced by a bench player at the same position class.
- A grouping change fixes the RB, TE and WR counts. The surplus leaves, and the deficit is filled from the bench.
- Bench players come from the full eligible roster, including players with no historical carries or targets. Their
  on-field rate has a position prior, so none is excluded by construction.

The table is written by docs/research/participation-model-2026-11-02/export_field.py from the 2022 to 2025 participation
files. It holds no 2026 data: the 2026 transitions and hazards are priors, as the owner chose (option A). The formulas here
are the ones in lineup_fit.py and export_field.py; test_participation_field.py checks the table loads and steps.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

SCHEMA = 'lp.nfl.participation-field.v3'  # v3 grouping codes carry -OL<n> and -QB<n>; v2 tables (two digits) still load
SCHEMAS = ('lp.nfl.participation-field.v2', SCHEMA)
PLAYER_PRIOR_PLAYS = 20.0  # shrinks a player's on-field rate to the position prior, as in participation_model.py
LEAGUE_TRANSITION_PRIOR_PLAYS = 20.0  # shrinks a league grouping transition to the league's mix for the cell
TEAM_TRANSITION_PRIOR_PLAYS = 50.0  # shrinks a team's grouping transition to the league's transition
HAZARD_PRIOR_PLAYS = 20.0  # shrinks a stint bucket's leave rate to its position class's rate
STINT_CAP = 6
MIN_CELL_PLAYS = 20.0  # a situation cell with fewer league plays borrows the nearest cell of the same down (supported_cell)
DISTANCES = ('short', 'mid', 'long', 'xl')
SKILL = {'RB': 'RB', 'FB': 'RB', 'TE': 'TE', 'WR': 'WR'}
SKILL_CLASSES = ('RB', 'TE', 'WR')
LINEUP_CLASSES = SKILL_CLASSES + ('QB',)  # 'QB' is a second QB on the field; the starter is the engine's passer
START = 'START'
FLOOR = 1e-9  # a zero weight still gets a draw, so no bench player is impossible by construction


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cell_of(down, togo, yl):
    """Down, distance and field bucket, the same buckets as participation_model.cell_of. Missing values are 'na'."""
    down = str(down) if down in (1, 2, 3, 4) else 'na'
    if togo is None:
        distance = 'na'
    else:
        distance = 'short' if togo <= 3 else 'mid' if togo <= 6 else 'long' if togo <= 9 else 'xl'
    if yl is None:
        field = 'na'
    else:
        field = 'red' if yl <= 20 else 'mid' if yl <= 50 else 'own' if yl <= 80 else 'deep'
    return f'{down}|{distance}|{field}'


def group_counts(group):
    """{'RB', 'TE', 'WR', 'QB'} for a grouping code. '12' is 1 RB (with FB), 2 TE and 2 WR; '12-OL6' has six linemen, so
    1 WR; '11-QB2' has a second QB, counted as 'QB', so 2 WR. The WR count is what the line, QBs, RBs and TEs leave of
    eleven. Raises ValueError for an unreadable code, no QB, or a negative WR count."""
    head, *suffixes = group.split('-')
    if len(head) != 2 or not head.isdigit():
        raise ValueError(f'unreadable grouping code {group!r}')
    line, qbs = 5, 1
    for suffix in suffixes:
        if suffix.startswith('OL') and suffix[2:].isdigit():
            line = int(suffix[2:])
        elif suffix.startswith('QB') and suffix[2:].isdigit():
            qbs = int(suffix[2:])
        else:
            raise ValueError(f'unreadable grouping code {group!r}')
    rb, te = int(head[0]), int(head[1])
    wr = 11 - line - qbs - rb - te
    if qbs < 1 or wr < 0:
        raise ValueError(f'grouping code {group!r} has {qbs} QBs and {wr} WRs')
    return {'RB': rb, 'TE': te, 'WR': wr, 'QB': qbs - 1}


def readable(group):
    try:
        group_counts(group)
        return True
    except (TypeError, ValueError):
        return False


def starter_qb(players):
    """The QB the engine throws with: the lowest depth rank among the players given, ties by id."""
    qbs = sorted((p for p in players if p['pos_abb'] == 'QB'), key=lambda p: (p['pos_rank'], p['gsis_id']))
    return qbs[0]['gsis_id'] if qbs else None


class Field:
    """The exported transition table. Every snap's outcome is counted in `status`, so a zero is printed, not hidden."""

    def __init__(self, data, sha256):
        if data.get('schema') not in SCHEMAS:
            raise ValueError(f"participation field schema is {data.get('schema')!r}, expected one of {SCHEMAS}")
        self.sha256 = sha256
        self.seasons = sorted(data.get('seasons') or [])  # the fit seasons; the engine refuses a game not after all of them
        self.teams = {team for team, _cell, _prev, _counts in data['team_transitions']}
        self.league_transitions = {(cell, prev): Counter(counts) for cell, prev, counts in data['league_transitions']}
        self.team_transitions = {(team, cell, prev): Counter(counts)
                                 for team, cell, prev, counts in data['team_transitions']}
        self.marginal_by_cell = {}  # cell -> grouping -> weight, summed over the previous grouping
        for (cell, _prev), counts in self.league_transitions.items():
            self.marginal_by_cell.setdefault(cell, Counter()).update(counts)
        self.leave_counts = {(kind, cls, bucket): (leaves, total)
                             for kind, cls, bucket, leaves, total in data['leave_counts']}
        self.leave_class = {}  # (kind, class) -> pooled leaves and player-snaps, the prior for each stint bucket
        for (kind, cls, _bucket), (leaves, total) in self.leave_counts.items():
            pooled = self.leave_class.get((kind, cls), (0.0, 0.0))
            self.leave_class[(kind, cls)] = (pooled[0] + leaves, pooled[1] + total)
        self.appearances = {(pid, team, group): w for pid, team, group, w in data['appearances']}
        self.team_plays = {(team, group): w for team, group, w in data['team_plays']}
        self.position_prior = {(pos, group): v for pos, group, v in data['position_prior']}
        self.status = Counter()

    @classmethod
    def load(cls, path, expected_sha256):
        """Refuses a table whose hash differs from the one the run names, so the arm cannot silently change its input."""
        digest = sha256_file(path)
        if digest != expected_sha256:
            raise ValueError(f'participation field {path} has sha256 {digest}, expected {expected_sha256}')
        return cls(json.loads(Path(path).read_text(encoding='utf-8')), digest)

    def group_probs(self, team, cell, prev):
        """P(grouping | team, situation cell, previous grouping). Empty when the cell has no league data."""
        marginal = self.marginal_by_cell.get(cell)
        if not marginal:
            return {}
        total = sum(marginal.values())
        league_counts = self.league_transitions.get((cell, prev), Counter())
        n_league = sum(league_counts.values())
        league = {group: (league_counts[group] + LEAGUE_TRANSITION_PRIOR_PLAYS * marginal[group] / total)
                  / (n_league + LEAGUE_TRANSITION_PRIOR_PLAYS) for group in marginal}
        team_counts = self.team_transitions.get((team, cell, prev), Counter())
        n_team = sum(team_counts.values())
        return {group: (team_counts[group] + TEAM_TRANSITION_PRIOR_PLAYS * league[group])
                / (n_team + TEAM_TRANSITION_PRIOR_PLAYS) for group in league}

    def supported_cell(self, cell):
        """The cell itself when the league has MIN_CELL_PLAYS plays there. Otherwise the same down and field bucket at the
        nearest distance that has them, then the same down's largest cell. None when the down has no supported cell. The
        caller records the substitution; the count is in `status`."""
        def plays(c):
            return sum(self.marginal_by_cell.get(c, {}).values())
        if plays(cell) >= MIN_CELL_PLAYS:
            return cell
        down, distance, field = cell.split('|')
        self.status['cell_fallback'] += 1
        if distance in DISTANCES:
            rank = DISTANCES.index(distance)
            near = sorted(DISTANCES, key=lambda d: (abs(DISTANCES.index(d) - rank), DISTANCES.index(d)))
            for other in near:
                if plays(f'{down}|{other}|{field}') >= MIN_CELL_PLAYS:
                    return f'{down}|{other}|{field}'
        same_down = [c for c in self.marginal_by_cell if c.startswith(f'{down}|') and plays(c) >= MIN_CELL_PLAYS]
        return max(same_down, key=lambda c: (plays(c), c)) if same_down else None

    def draw_group(self, team, prev, cell, draw):
        """The grouping for one snap, from the transition out of the previous snap's grouping (START on a game's first)."""
        probs = self.group_probs(team, cell, prev)
        if not probs:
            self.status['no_league_cell'] += 1
            return None
        groups = sorted(probs)
        return draw.choices(groups, weights=[probs[group] for group in groups], k=1)[0]

    def leave_prob(self, kind, cls, stint):
        """P(a skill player of this class leaves before the next snap) at his current stint. kind is 'held' when the
        grouping keeps, and 'changed' when it moves and this class's count does not."""
        bucket = 0 if kind == 'swap' else min(stint, STINT_CAP)  # swap churn is one rate per class, not per stint
        leaves, total = self.leave_counts.get((kind, cls, bucket), (0.0, 0.0))
        pooled_leaves, pooled_total = self.leave_class.get((kind, cls), (0.0, 0.0))
        prior = pooled_leaves / pooled_total if pooled_total else 0.0
        return max(0.0, leaves + HAZARD_PRIOR_PLAYS * prior) / (total + HAZARD_PRIOR_PLAYS)

    def rate(self, pid, team, group, pos):
        prior = self.position_prior.get((pos, group), 0.0)
        appearances = self.appearances.get((pid, team, group), 0.0)
        plays = self.team_plays.get((team, group), 0.0)
        return (appearances + PLAYER_PRIOR_PLAYS * prior) / (plays + PLAYER_PRIOR_PLAYS)

    def advance(self, team, lineup, group, roster, draw, prev_group=None):
        """The skill lineup after one snap. `lineup` maps each skill player on the field to his stint, the number of
        consecutive snaps ending at the last snap. Returns (next lineup, record). Only this method draws leaves and entrants.
        Rotation (the stint hazard) applies only when the grouping holds; a grouping change moves players by count."""
        if group is None or not readable(group):
            self.status['unsupported_grouping'] += 1
            return None, {'status': 'unsupported_grouping', 'group': group}
        starter = starter_qb(roster)  # the passer is never in the lineup; a second QB is drawn from the other QBs
        cls_of = {p['gsis_id']: SKILL[p['pos_abb']] for p in roster if p['pos_abb'] in SKILL}
        cls_of.update({p['gsis_id']: 'QB' for p in roster if p['pos_abb'] == 'QB' and p['gsis_id'] != starter})
        target = group_counts(group)
        leavers = set()
        kind = 'held' if prev_group == group else 'changed'
        for pid in sorted(lineup):
            cls = cls_of.get(pid)
            if cls is None:  # not a skill player on the roster any more
                leavers.add(pid)
            elif prev_group is not None and group_counts(prev_group)[cls] == target[cls] \
                    and draw.random() < self.leave_prob(kind, cls, lineup[pid]):  # rotation in a class whose count holds
                leavers.add(pid)
        for pid in sorted(lineup):  # churn in a class whose count changes, beyond the count change itself
            cls = cls_of.get(pid)
            if pid not in leavers and cls is not None and prev_group is not None \
                    and group_counts(prev_group)[cls] != target[cls] and draw.random() < self.leave_prob('swap', cls, 0):
                leavers.add(pid)
        kept = {pid: stint for pid, stint in lineup.items() if pid not in leavers}
        removed = set(leavers)
        count_removed, entrants, short = [], [], {}
        for cls in LINEUP_CLASSES:  # the grouping's counts: surplus leaves by hazard, deficit enters from the bench
            on = sorted(pid for pid in kept if cls_of.get(pid) == cls)
            while len(on) > target[cls]:
                weights = [max(self.leave_prob(kind, cls, kept[pid]), FLOOR) for pid in on]
                pid = draw.choices(on, weights=weights, k=1)[0]
                on.remove(pid)
                del kept[pid]
                removed.add(pid)
                count_removed.append(pid)
            need = target[cls] - len(on)
            if need > 0:
                bench = [p for p in sorted(roster, key=lambda p: (p['pos_rank'], p['gsis_id']))
                         if cls_of.get(p['gsis_id']) == cls and p['gsis_id'] not in kept and p['gsis_id'] not in removed]
                picked = self._weighted(bench, need, team, group, draw)
                for player in picked:
                    kept[player['gsis_id']] = 0  # set to its stint below
                    entrants.append(player['gsis_id'])
                if len(picked) < need:
                    short[cls] = need - len(picked)
        nxt = {pid: (lineup[pid] + 1 if pid in lineup else 1) for pid in kept}
        status = 'short' if short else 'ok'
        self.status[status] += 1
        return nxt, {'status': status, 'group': group, 'leavers': sorted(leavers),
                     'count_removed': count_removed, 'entrants': sorted(entrants), 'short': short}

    def _weighted(self, pool, k, team, group, draw):
        """k distinct players, each drawn in proportion to his on-field rate for this team and grouping."""
        pool = list(pool)
        out = []
        for _ in range(min(k, len(pool))):
            weights = [max(self.rate(p['gsis_id'], team, group, p['pos_abb']), FLOOR) for p in pool]
            pick = draw.choices(pool, weights=weights, k=1)[0]
            out.append(pick)
            pool = [p for p in pool if p is not pick]
        return out
