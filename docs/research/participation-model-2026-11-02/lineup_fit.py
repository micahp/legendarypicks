"""Snap-to-snap skill lineups for the participation field: the fit (research).

A skill lineup is the set of RB, FB, TE and WR on the field for one team's offensive snap. The offensive line and the
quarterback are not modelled here. The fit reads the same scrimmage table as participation_model.py, and gives two parts:

- Grouping transitions: how often the grouping on this snap follows each grouping on the previous snap, in each
  situation cell. The simulator shrinks these toward the league and then toward the situation mix.
- Leave hazards: how often a skill player on the field leaves before the next snap, by position class and by the number
  of consecutive snaps he has already been on the field (his stint). This is the recent-workload term.

A lineup changes only through those two parts: a grouping change fixes the position counts, and a leave is replaced at the
same position class. Nothing here draws the whole lineup again each snap.
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))  # the runtime module the simulator loads
import participation_field as pf  # noqa: E402
import participation_labels as pl  # noqa: E402
import participation_model as pm  # noqa: E402

SKILL = {'RB': 'RB', 'FB': 'RB', 'TE': 'TE', 'WR': 'WR'}
SKILL_CLASSES = ('RB', 'TE', 'WR')
STINT_CAP = 6  # stints of six or more snaps share one hazard bucket
START = 'START'  # the previous grouping of a team's first offensive snap in a game


def group_counts(group):
    """The RB, TE, WR and second-QB counts of a grouping code, decoded by the runtime module so the fit and the simulator
    read the same code the same way (participation_field.group_counts)."""
    return pf.group_counts(group)


def sequences(rows, positions, snap_labels=False, recon=None):
    """{(season, game_id, team): [(group, cell, skill), ...]} in play order. skill is a frozenset of (gsis_id, class).
    snap_labels=True takes each player's class from the position listed on that snap, so a player with several roles
    keeps the role he had on each snap. Where the listed labels are missing (2022), the reconstructed position is used
    (participation_labels.aligned_labels). A player with no label from either source is left out of skill and is
    counted by the caller, never silently mispaired. Otherwise every snap uses the player's position from positions."""
    grouped = defaultdict(list)
    for row in rows:
        if snap_labels:
            skill = frozenset((pid, SKILL[label]) for pid, label, _source in pl.aligned_labels(row, recon)
                              if label in SKILL)
        else:
            skill = frozenset((pid, SKILL[positions[pid]]) for pid in row['ids'] if positions.get(pid) in SKILL)
        grouped[(int(row['season']), row['game_id'], row['posteam'])].append(
            (int(row['play_id']), row['group'], pm.cell_of(row), skill))
    return {key: [(group, cell, skill) for _, group, cell, skill in sorted(items, key=lambda item: item[0])]
            for key, items in grouped.items()}


def fit(seqs, seasons):
    """The export pieces: grouping transitions, team grouping transitions and leave counts, all recency weighted."""
    league_transitions = defaultdict(Counter)  # (cell, previous grouping) -> grouping -> weight
    team_transitions = defaultdict(Counter)  # (team, cell, previous grouping) -> grouping -> weight
    leave_counts = defaultdict(lambda: [0.0, 0.0])  # (kind, class, stint bucket) -> [leaves, player-snaps]
    swap_counts = defaultdict(lambda: [0.0, 0.0])  # class -> [leaves beyond the count change, player-snaps]
    checks = Counter()
    for (season, _game, team), seq in sorted(seqs.items()):
        if season not in seasons:
            continue
        w = pm.RECENCY[season]
        prev, prev_skill, prev_on, stint, prev_ok = START, None, set(), {}, False
        for group, cell, skill in seq:
            league_transitions[(cell, prev)][group] += w
            team_transitions[(team, cell, prev)][group] += w
            on = {pid for pid, _ in skill}
            counted = Counter(cls for _, cls in skill)
            checks['snaps'] += 1
            ok_now = all(counted[cls] == group_counts(group)[cls] for cls in SKILL_CLASSES)
            if not ok_now:
                checks['count_mismatch'] += 1
            if prev_skill is None:
                stint = {pid: 1 for pid in on}
            else:
                # Hazards are fitted only where both snaps match their grouping. A label contradiction is not a
                # substitution, and the simulator never produces one.
                if prev_ok and ok_now:
                    kind = 'held' if group == prev else 'changed'  # rotation is fitted apart for held and changed groupings
                    for pid, cls in prev_skill:  # a class whose count changes moves by count, so it is not rotation
                        if group_counts(group)[cls] != group_counts(prev)[cls]:
                            continue
                        bucket = (kind, cls, min(stint[pid], STINT_CAP))
                        leave_counts[bucket][1] += w
                        if pid not in on:
                            leave_counts[bucket][0] += w
                    for cls in SKILL_CLASSES:  # a class whose count changes also churns, beyond the count change itself
                        old, new = group_counts(prev)[cls], group_counts(group)[cls]
                        if old == new:
                            continue
                        players = [pid for pid, c in prev_skill if c == cls]
                        leaves = sum(1 for pid in players if pid not in on)
                        swap_counts[cls][0] += w * (leaves - max(0, old - new))
                        swap_counts[cls][1] += w * len(players)
                stint = {pid: stint[pid] + 1 if pid in prev_on else 1 for pid in on}
            prev, prev_skill, prev_on, prev_ok = group, skill, on, ok_now
    return {
        'league_transitions': [[cell, prev, dict(sorted(counts.items()))]
                               for (cell, prev), counts in sorted(league_transitions.items())],
        'team_transitions': [[team, cell, prev, dict(sorted(counts.items()))]
                             for (team, cell, prev), counts in sorted(team_transitions.items())],
        'leave_counts': [[kind, cls, bucket, round(leaves, 6), round(total, 6)]
                         for (kind, cls, bucket), (leaves, total) in sorted(leave_counts.items())]
                        + [['swap', cls, 0, round(excess, 6), round(total, 6)]
                           for cls, (excess, total) in sorted(swap_counts.items())],
        'checks': dict(sorted(checks.items())),
    }
