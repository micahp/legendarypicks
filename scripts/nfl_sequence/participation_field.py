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
import math
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nfl_team_codes  # noqa: E402

TeamKeyed = nfl_team_codes.TeamKeyed  # every team-keyed table below: nflverse codes in the file, any spelling on lookup

SCHEMA = 'lp.nfl.participation-field.v4'  # v4 adds transitions conditioned on the call; v3 codes carry -OL<n>, -QB<n>
SCHEMAS = ('lp.nfl.participation-field.v2', 'lp.nfl.participation-field.v3', SCHEMA)
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


def class_vector(group):
    """The grouping's (RB, TE, WR) counts, the coordinates of the snap-count tilt."""
    counts = group_counts(group)
    return tuple(counts[cls] for cls in SKILL_CLASSES)


def leave_reference_rate(appearances, team_plays, position_prior, positions):
    """{class: the on-field mean of the shrunk on-field rate}: each (player, team, grouping) rate weighted by its
    appearances. The normaliser of leave_factor, so the mean factor over players on the field is about 1. The table's
    export writes it; positions maps gsis_id to position."""
    num, den = Counter(), Counter()
    for (pid, team, group), a in appearances.items():
        cls = SKILL.get(positions.get(pid))
        if cls is None or a <= 0:
            continue
        prior = position_prior.get((positions[pid], group), 0.0)
        plays = team_plays.get((team, group), 0.0)
        num[cls] += a * (a + PLAYER_PRIOR_PLAYS * prior) / (plays + PLAYER_PRIOR_PLAYS)
        den[cls] += a
    return {cls: num[cls] / den[cls] for cls in SKILL_CLASSES if den[cls]}


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


def offense_identities(roster):
    """{gsis_id: {'roles': {class: best rank}, 'pos_rank': best rank}}: one entry per player, with every offensive role he
    has. A WR listed twice as WR has the role WR once. A player listed as WR and PR has the role WR, since KR and PR rows
    give no role and so never overwrite a position. A WR/RB hybrid has both roles, and fills one slot per snap, whichever
    role the lineup gives him. Players with no skill or QB row are absent. The result does not depend on row order."""
    players = {}
    for p in roster:
        if p['pos_abb'] in SKILL:
            role = SKILL[p['pos_abb']]
        elif p['pos_abb'] == 'QB':
            role = 'QB'
        else:
            continue
        ident = players.setdefault(p['gsis_id'], {'roles': {}, 'pos_rank': p['pos_rank']})
        ident['roles'][role] = min(ident['roles'].get(role, p['pos_rank']), p['pos_rank'])
        ident['pos_rank'] = min(ident['pos_rank'], p['pos_rank'])
    return players


def starter_of(identities):
    """The QB who throws: the lowest-ranked QB role, ties by id, as starter_qb."""
    return starter_qb([{'gsis_id': gsis, 'pos_abb': 'QB', 'pos_rank': ident['roles']['QB']}
                       for gsis, ident in identities.items() if 'QB' in ident['roles']])


class Field:
    """The exported transition table. Every snap's outcome is counted in `status`, so a zero is printed, not hidden."""

    def __init__(self, data, sha256):
        if data.get('schema') not in SCHEMAS:
            raise ValueError(f"participation field schema is {data.get('schema')!r}, expected one of {SCHEMAS}")
        self.sha256 = sha256
        self.seasons = sorted(data.get('seasons') or [])  # the fit seasons; the engine refuses a game not after all of them
        self.teams = TeamKeyed((team, True) for team, _cell, _prev, _counts in data['team_transitions'])
        self.league_transitions = {(cell, prev): Counter(counts) for cell, prev, counts in data['league_transitions']}
        self.team_transitions = TeamKeyed((((team, cell, prev), Counter(counts))
                                           for team, cell, prev, counts in data['team_transitions']), team_at=0)
        self.marginal_by_cell = {}  # cell -> grouping -> weight, summed over the previous grouping
        for (cell, _prev), counts in self.league_transitions.items():
            self.marginal_by_cell.setdefault(cell, Counter()).update(counts)
        # v4: the same transitions split by the call (run or dropback), so the grouping depends on the call
        self.league_by_call = {(cell, call, prev): Counter(counts)
                               for cell, call, prev, counts in data.get('league_transitions_by_intent', [])}
        self.team_by_call = TeamKeyed((((team, cell, call, prev), Counter(counts))
                                       for team, cell, call, prev, counts in data.get('team_transitions_by_intent', [])),
                                      team_at=0)
        self.marginal_by_cell_call = {}
        for (cell, call, _prev), counts in self.league_by_call.items():
            self.marginal_by_cell_call.setdefault((cell, call), Counter()).update(counts)
        self.conditions_on_call = bool(self.league_by_call)
        self.leave_counts = {(kind, cls, bucket): (leaves, total)
                             for kind, cls, bucket, leaves, total in data['leave_counts']}
        self.leave_class = {}  # (kind, class) -> pooled leaves and player-snaps, the prior for each stint bucket
        for (kind, cls, _bucket), (leaves, total) in self.leave_counts.items():
            pooled = self.leave_class.get((kind, cls), (0.0, 0.0))
            self.leave_class[(kind, cls)] = (pooled[0] + leaves, pooled[1] + total)
        self.appearances = TeamKeyed((((pid, team, group), w) for pid, team, group, w in data['appearances']), team_at=1)
        self.team_plays = TeamKeyed((((team, group), w) for team, group, w in data['team_plays']), team_at=0)
        self.position_prior = {(pos, group): v for pos, group, v in data['position_prior']}
        # The current-season update from published snap counts (set per game by snap_update.apply; empty = no update):
        # team -> (lambda_RB, lambda_TE, lambda_WR), the exponential tilt of the grouping draw, and (team, gsis_id) -> a
        # multiplier on the player's on-field rate.
        self.group_tilt = TeamKeyed()
        self.player_weight = TeamKeyed(team_at=0)
        # A player's leave hazard scaled by ((1 - his rate) / (1 - his class's on-field mean rate)) ** leave_power, so a
        # regular leaves less often than a backup. 0 (no scaling) unless the table sets it.
        self.leave_power = float(data.get('leave_power', 0.0))
        self.leave_reference = dict(data.get('leave_reference_rate', {}))
        if self.leave_power and set(self.leave_reference) != set(SKILL_CLASSES):
            raise ValueError(f'leave_power needs a leave_reference_rate for {SKILL_CLASSES}, got {sorted(self.leave_reference)}')
        self.status = Counter()

    @classmethod
    def load(cls, path, expected_sha256):
        """Refuses a table whose hash differs from the one the run names, so the arm cannot silently change its input."""
        digest = sha256_file(path)
        if digest != expected_sha256:
            raise ValueError(f'participation field {path} has sha256 {digest}, expected {expected_sha256}')
        return cls(json.loads(Path(path).read_text(encoding='utf-8')), digest)

    def group_probs(self, team, cell, prev, call=None):
        """P(grouping | team, situation cell, previous grouping), and given the call ('run' or 'dropback') when the table
        has call-conditioned transitions. Empty when the cell has no league data. A call with no league data in the cell
        uses the unconditioned transition, counted in status."""
        probs = self._group_probs(team, cell, prev, call)
        lam = self.group_tilt.get(team)
        if lam is None or not probs:
            return probs
        weights = {g: p * math.exp(sum(l * x for l, x in zip(lam, class_vector(g)))) for g, p in probs.items()}
        total = sum(weights.values())
        return {g: w / total for g, w in weights.items()}

    def _group_probs(self, team, cell, prev, call):
        if call is not None and self.conditions_on_call:
            if self.marginal_by_cell_call.get((cell, call)):
                marginal = self.marginal_by_cell_call[(cell, call)]
                league_counts = self.league_by_call.get((cell, call, prev), Counter())
                team_counts = self.team_by_call.get((team, cell, call, prev), Counter())
                return self._shrunk(marginal, league_counts, team_counts)
            self.status['call_cell_missing'] += 1
        marginal = self.marginal_by_cell.get(cell)
        if not marginal:
            return {}
        return self._shrunk(marginal, self.league_transitions.get((cell, prev), Counter()),
                            self.team_transitions.get((team, cell, prev), Counter()))

    @staticmethod
    def _shrunk(marginal, league_counts, team_counts):
        """The team transition shrunk to the league transition, shrunk to the league's mix for the cell."""
        total = sum(marginal.values())
        n_league = sum(league_counts.values())
        league = {group: (league_counts[group] + LEAGUE_TRANSITION_PRIOR_PLAYS * marginal[group] / total)
                  / (n_league + LEAGUE_TRANSITION_PRIOR_PLAYS) for group in marginal}
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

    def draw_group(self, team, prev, cell, draw, call=None):
        """The grouping for one snap, from the transition out of the previous snap's grouping (START on a game's first),
        given the call when the table conditions on it."""
        probs = self.group_probs(team, cell, prev, call)
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

    def leave_factor(self, pid, team, group, pos, cls):
        """The player's multiplier on his class's leave hazard (leave_power > 0 only)."""
        r = min(0.99, self.rate(pid, team, group, pos))
        return ((1.0 - r) / (1.0 - self.leave_reference[cls])) ** self.leave_power

    def rate(self, pid, team, group, pos):
        prior = self.position_prior.get((pos, group), 0.0)
        appearances = self.appearances.get((pid, team, group), 0.0)
        plays = self.team_plays.get((team, group), 0.0)
        rate = (appearances + PLAYER_PRIOR_PLAYS * prior) / (plays + PLAYER_PRIOR_PLAYS)
        weight = self.player_weight.get((team, pid))
        return rate if weight is None else rate * weight

    def advance(self, team, lineup, group, roster, draw, prev_group=None, slots=None):
        """The skill lineup after one snap. `lineup` maps each skill player on the field to his stint, the number of
        consecutive snaps ending at the last snap, and `slots` maps him to the class (RB, TE, WR or QB) he filled. A player
        fills one slot per snap, whatever his roles, and his slot sets the position prior and the leave hazard used for him.
        Returns (next lineup, record); record['slots'] is the next `slots`. Only this method draws leaves and entrants.
        Rotation (the stint hazard) applies only when the grouping holds; a grouping change moves players by count."""
        if group is None or not readable(group):
            self.status['unsupported_grouping'] += 1
            return None, {'status': 'unsupported_grouping', 'group': group}
        identities = offense_identities(roster)
        starter = starter_of(identities)  # the passer is never in the lineup; a second QB is drawn from the other QBs
        eligible = {gsis: sorted(cls for cls in ident['roles'] if not (cls == 'QB' and gsis == starter))
                    for gsis, ident in identities.items()}
        ranks = {gsis: ident['pos_rank'] for gsis, ident in identities.items()}
        slots = dict(slots or {})

        def slot_of(pid):  # the class a player on the field fills: his last slot, if it is still one of his roles
            if pid not in eligible:
                return None
            if slots.get(pid) in eligible[pid]:
                return slots[pid]
            return eligible[pid][0] if len(eligible[pid]) == 1 else None

        def hazard(kind_, cls, stint, pid):
            base = self.leave_prob(kind_, cls, stint)
            if not self.leave_power or cls not in self.leave_reference:
                return base
            return min(1.0, base * self.leave_factor(pid, team, group, cls, cls))
        target = group_counts(group)
        leavers = set()
        kind = 'held' if prev_group == group else 'changed'
        for pid in sorted(lineup):
            cls = slot_of(pid)
            if cls is None:  # not a skill player on the roster any more, or no longer in a role he can fill
                leavers.add(pid)
            elif prev_group is not None and group_counts(prev_group)[cls] == target[cls] \
                    and draw.random() < hazard(kind, cls, lineup[pid], pid):  # rotation in a class whose count holds
                leavers.add(pid)
        for pid in sorted(lineup):  # churn in a class whose count changes, beyond the count change itself
            cls = slot_of(pid)
            if pid not in leavers and cls is not None and prev_group is not None \
                    and group_counts(prev_group)[cls] != target[cls] and draw.random() < hazard('swap', cls, 0, pid):
                leavers.add(pid)
        kept = {pid: stint for pid, stint in lineup.items() if pid not in leavers}
        kept_slot = {pid: slot_of(pid) for pid in kept}
        removed = set(leavers)
        count_removed, entrants, short = [], [], {}
        for cls in LINEUP_CLASSES:  # the grouping's counts: surplus leaves by hazard, deficit enters from the bench
            on = sorted(pid for pid in kept if kept_slot[pid] == cls)
            while len(on) > target[cls]:
                weights = [max(hazard(kind, cls, kept[pid], pid), FLOOR) for pid in on]
                pid = draw.choices(on, weights=weights, k=1)[0]
                on.remove(pid)
                del kept[pid]
                del kept_slot[pid]
                removed.add(pid)
                count_removed.append(pid)
            need = target[cls] - len(on)
            if need > 0:  # one bench entry per player, and only a player not already on the field can fill this slot
                bench = [{'gsis_id': pid, 'pos_rank': ranks[pid]} for pid in sorted(identities, key=lambda g: (ranks[g], g))
                         if cls in eligible[pid] and pid not in kept and pid not in removed]
                picked = self._weighted(bench, need, team, group, draw, cls)
                for player in picked:
                    kept[player['gsis_id']] = 0  # set to its stint below
                    kept_slot[player['gsis_id']] = cls
                    entrants.append(player['gsis_id'])
                if len(picked) < need:
                    short[cls] = need - len(picked)
        nxt = {pid: (lineup[pid] + 1 if pid in lineup else 1) for pid in kept}
        status = 'short' if short else 'ok'
        self.status[status] += 1
        return nxt, {'status': status, 'group': group, 'leavers': sorted(leavers),
                     'count_removed': count_removed, 'entrants': sorted(entrants), 'short': short,
                     'slots': dict(sorted(kept_slot.items()))}

    def _weighted(self, pool, k, team, group, draw, cls):
        """k distinct players, each drawn in proportion to his on-field rate at class `cls` for this team and grouping."""
        pool = list(pool)
        out = []
        for _ in range(min(k, len(pool))):
            weights = [max(self.rate(p['gsis_id'], team, group, cls), FLOOR) for p in pool]
            pick = draw.choices(pool, weights=weights, k=1)[0]
            out.append(pick)
            pool = [p for p in pool if p is not pick]
        return out
