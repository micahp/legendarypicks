"""The current-season update of the participation field from published snap counts (research, opt-in, not adopted).

A live forecast has no current-season participation (who was on the field each snap), but nflverse publishes each player's
offensive snaps per game. Before a game in week W, the snap counts of the team's games in weeks before W update the
lineup table fitted on earlier seasons in two ways:

- Grouping tilt: the team's RB (with FB), TE and WR snaps per team snap give a target mean count per class, blended with
  the table's mean as (N0 * table + G * snap counts) / (N0 + G), G the team's earlier games. The grouping draw is tilted
  exponentially, p(g) * exp(lambda . n(g)), with lambda set so the team's table mix has that mean
  (participation_field.Field.group_tilt). Line counts are left out: snap counts reproduce participation's line count
  poorly (r = 0.15 per team-game, 2016 to 2025) but its TE (0.98), WR (0.97) and RB (0.85) counts well. Selected on 2019
  to 2021 and scored on 2022 to 2025 (docs/research/participation-model-2026-11-02/WEEKLY-BACKTEST-RESULTS-2026-11-04.md).
- Player weight: each player's share of his team's offensive snaps in the earlier games he was active for, blended with the
  table's expected on-field rate for him as (N0 * table + G_p * share) / (N0 + G_p), G_p his active games. His draw weight
  is multiplied by blend / table (participation_field.Field.player_weight). On 2022 to 2025, week over week, this
  lowers the error of player snap shares from 0.203 to 0.155 (mean absolute error per player-game; WEEKLY-PLAYER-
  BACKTEST-RESULTS-2026-11-04.md).

The snap counts file (SCHEMA) holds one season's published counts by week; nothing from the game's week or later is used.
"""
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import participation_field as pf

SCHEMA = 'lp.nfl.snap-counts.v1'


def snap_team(code):
    """The nflverse spelling of a club (snap counts and weekly rosters keep STL, OAK, SD before the moves), through
    backend/team_codes.py. Raises on an unknown code."""
    return pf.nfl_team_codes.to_nflverse(code)


SNAP_CLASS = {'RB': 'RB', 'FB': 'RB', 'TE': 'TE', 'WR': 'WR'}
TEAM_MIX_PRIOR_PLAYS = 50.0  # pseudo-plays of the league mix in a team's table mix (the tilt's reference mix)
GROUP_N0 = 8.0  # selected on 2019 to 2021 (weekly_backtest.py, arm A2)
PLAYER_N0 = 1.0  # selected on 2019 to 2021, the smallest of the grid (weekly_player_backtest.py); None turns it off
WEIGHT_RANGE = (0.02, 50.0)  # a player weight outside this is clipped and counted


class SnapCounts:
    """One season's published snap counts: team snaps, player offensive snaps and the active roster by week."""

    def __init__(self, data, sha256):
        if data.get('schema') != SCHEMA:
            raise ValueError(f"snap counts schema is {data.get('schema')!r}, expected {SCHEMA!r}")
        self.sha256 = sha256
        self.season = int(data['season'])
        # Team-keyed tables go through nfl_team_codes.TeamKeyed: the file uses nflverse codes, callers may hold either.
        self.team_snaps = pf.TeamKeyed((((team, int(week)), float(snaps)) for team, week, snaps in data['team_snaps']),
                                       team_at=0)
        self.player = pf.TeamKeyed(team_at=0)  # (team, week) -> gsis_id -> offensive snaps
        self.position = {}
        for team, week, pid, pos, snaps in data['player_snaps']:
            self.player.setdefault((team, int(week)), {})[pid] = float(snaps)
            self.position[pid] = pos
        self.active = pf.TeamKeyed((((team, int(week)), set(ids)) for team, week, ids in data['active']), team_at=0)
        self.coverage = data.get('coverage', {})

    @classmethod
    def load(cls, path, expected_sha256):
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise ValueError(f'snap counts {path} have sha256 {digest}, expected {expected_sha256}')
        return cls(json.loads(Path(path).read_text(encoding='utf-8')), digest)

    def weeks_before(self, team, week):
        """The team's games before `week` that have published team snaps."""
        team = pf.nfl_team_codes.to_db(team)  # the keys are database codes; compare in the same vocabulary
        return sorted(w for (t, w) in self.team_snaps if t == team and w < week)

    def class_shares(self, team, week):
        """(games, [RB, TE, WR snaps per team snap]) over the team's games before `week`."""
        weeks = self.weeks_before(team, week)
        total = sum(self.team_snaps[(team, w)] for w in weeks)
        by_class = Counter()
        for w in weeks:
            for pid, snaps in self.player.get((team, w), {}).items():
                cls = SNAP_CLASS.get(self.position.get(pid))
                if cls:
                    by_class[cls] += snaps
        return len(weeks), ([by_class[c] / total for c in pf.SKILL_CLASSES] if total else None)

    def player_share(self, team, week, pid):
        """(active games, share of team snaps in them) over the team's games before `week` with the player active."""
        games, snaps, team_total = 0, 0.0, 0.0
        for w in self.weeks_before(team, week):
            if pid in self.active.get((team, w), ()) or pid in self.player.get((team, w), {}):
                games += 1
                snaps += self.player.get((team, w), {}).get(pid, 0.0)
                team_total += self.team_snaps[(team, w)]
        return games, (snaps / team_total if team_total else 0.0)


def load_published(raw_dir, season, players_csv=None):
    """The SnapCounts data for one season from the nflverse release files: snap_counts_<season>.parquet (pfr ids) and
    roster_weekly_<season>.parquet (status ACT). pfr ids map to gsis ids through players.csv and then the weekly roster;
    the unmatched rows and their offensive snaps are counted in `coverage`, never dropped silently."""
    import csv
    import pyarrow.parquet as pq
    raw_dir = Path(raw_dir)
    roster = pq.read_table(raw_dir / 'weekly_rosters' / f'roster_weekly_{season}.parquet',
                           columns=['team', 'week', 'status', 'position', 'gsis_id', 'pfr_id']).to_pydict()
    pfr_to_gsis = {}
    if players_csv is not None:
        with open(players_csv, encoding='utf-8', newline='') as handle:
            for row in csv.DictReader(handle):
                if row.get('pfr_id') and row.get('gsis_id'):
                    pfr_to_gsis[row['pfr_id']] = row['gsis_id']
    active = defaultdict(set)
    for i in range(len(roster['team'])):
        if roster['pfr_id'][i] and roster['gsis_id'][i]:
            pfr_to_gsis.setdefault(roster['pfr_id'][i], roster['gsis_id'][i])
        if roster['status'][i] == 'ACT' and roster['gsis_id'][i]:
            active[(snap_team(roster['team'][i]), int(roster['week'][i]))].add(roster['gsis_id'][i])
    d = pq.read_table(raw_dir / 'snap_counts' / f'snap_counts_{season}.parquet',
                      columns=['week', 'team', 'pfr_player_id', 'position', 'offense_snaps', 'offense_pct']).to_pydict()
    implied = defaultdict(list)
    player = {}
    coverage = Counter()
    for i in range(len(d['team'])):
        team, week = snap_team(d['team'][i]), int(d['week'][i])
        snaps, pct = float(d['offense_snaps'][i] or 0.0), float(d['offense_pct'][i] or 0.0)
        if pct >= 0.5:
            implied[(team, week)].append(snaps / pct)
        if not snaps:
            continue
        pid = pfr_to_gsis.get(d['pfr_player_id'][i])
        skill = d['position'][i] in SNAP_CLASS
        coverage['offense_rows'] += 1
        coverage['offense_snaps'] += snaps
        if pid is None:
            coverage['unmatched_rows'] += 1
            coverage['unmatched_snaps'] += snaps
            coverage['unmatched_skill_snaps'] += snaps if skill else 0.0
            continue
        player[(team, week, pid)] = (d['position'][i], snaps)
    data = {'schema': SCHEMA, 'season': season,
            'team_snaps': sorted([team, week, round(statistics.median(v), 3)] for (team, week), v in implied.items()),
            'player_snaps': sorted([team, week, pid, pos, snaps] for (team, week, pid), (pos, snaps) in player.items()),
            'active': sorted([team, week, sorted(ids)] for (team, week), ids in active.items()),
            'coverage': dict(sorted(coverage.items()))}
    return data


def tilt_lambda(mix, target):
    """lambda with sum_g mix(g) exp(lambda . n(g)) n(g) / Z = target, n(g) the (RB, TE, WR) counts (damped Newton)."""
    vecs = {g: pf.class_vector(g) for g in mix}
    total = sum(mix.values())
    lam = [0.0] * len(pf.SKILL_CLASSES)
    for _ in range(50):
        w = {g: mix[g] / total * math.exp(sum(l * x for l, x in zip(lam, vecs[g]))) for g in mix}
        z = sum(w.values())
        mean = [sum(w[g] * vecs[g][i] for g in w) / z for i in range(len(lam))]
        grad = [m - t for m, t in zip(mean, target)]
        if max(abs(x) for x in grad) < 1e-6:
            break
        cov = [[sum(w[g] * (vecs[g][i] - mean[i]) * (vecs[g][j] - mean[j]) for g in w) / z + (1e-6 if i == j else 0.0)
                for j in range(len(lam))] for i in range(len(lam))]
        step = _solve(cov, grad)
        scale = min(1.0, 1.0 / max(1e-12, max(abs(s) for s in step)))
        lam = [max(-5.0, min(5.0, l - scale * s)) for l, s in zip(lam, step)]
    return lam


def _solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def team_mix(field, team):
    """The team's grouping mix in the table, with TEAM_MIX_PRIOR_PLAYS of the league's (readable groupings only)."""
    league = Counter()
    for (_t, group), w in field.team_plays.items():
        if pf.readable(group):
            league[group] += w
    total = sum(league.values())
    return Counter({g: field.team_plays.get((team, g), 0.0) + TEAM_MIX_PRIOR_PLAYS * v / total
                    for g, v in league.items() if v > 0})


def group_lambda(field, snaps, team, week, n0=GROUP_N0):
    """The tilt for one team before `week`, or None when it has no earlier game."""
    games, observed = snaps.class_shares(team, week)
    if not games or observed is None:
        return None
    mix = team_mix(field, team)
    total = sum(mix.values())
    prior = [sum(v * pf.class_vector(g)[i] for g, v in mix.items()) / total for i in range(len(pf.SKILL_CLASSES))]
    return tilt_lambda(mix, [(n0 * p + games * o) / (n0 + games) for p, o in zip(prior, observed)])


def table_rate(field, team, pid, pos, mix=None):
    """The player's expected on-field rate in the table: his rate in each grouping, averaged over the team's mix."""
    mix = team_mix(field, team) if mix is None else mix
    total = sum(mix.values())
    saved = field.player_weight.pop((team, pid), None)
    try:
        return sum(v * field.rate(pid, team, g, pos) for g, v in mix.items()) / total
    finally:
        if saved is not None:
            field.player_weight[(team, pid)] = saved


def player_weights(field, snaps, team, week, players, n0):
    """{(team, gsis_id): weight} for the skill players given ({'gsis_id', 'pos_abb'}), and the counts of what was done."""
    mix = team_mix(field, team)
    out, status = {}, Counter()
    for p in players:
        if p['pos_abb'] not in SNAP_CLASS:
            continue
        games, share = snaps.player_share(team, week, p['gsis_id'])
        if not games:
            status['no_earlier_active_game'] += 1
            continue
        base = table_rate(field, team, p['gsis_id'], p['pos_abb'], mix)
        weight = ((n0 * base + games * share) / (n0 + games)) / base if base > 0 else WEIGHT_RANGE[1]
        clipped = min(WEIGHT_RANGE[1], max(WEIGHT_RANGE[0], weight))
        status['clipped' if clipped != weight else 'weighted'] += 1
        out[(team, p['gsis_id'])] = clipped
    return out, status


def apply(field, snaps, week, rosters, player_n0, group_n0=GROUP_N0):
    """Set the field's grouping tilt and player weights for one game in `week`. rosters: {team: players}. Returns a record
    of what was used, for the ledger."""
    if snaps.season is None:
        raise ValueError('snap counts have no season')
    field.group_tilt, field.player_weight = pf.TeamKeyed(), pf.TeamKeyed(team_at=0)
    record = {'snap_counts_sha256': snaps.sha256, 'season': snaps.season, 'week': week, 'group_n0': group_n0,
              'player_n0': player_n0, 'teams': {}}
    for team, players in sorted(rosters.items()):
        weeks = snaps.weeks_before(team, week)
        lam = group_lambda(field, snaps, team, week, group_n0)
        if lam is not None:
            field.group_tilt[team] = tuple(lam)
        weights, status = ({}, Counter({'player_weights_off': 1})) if player_n0 is None else \
            player_weights(field, snaps, team, week, players, player_n0)
        field.player_weight.update(weights)
        record['teams'][team] = {'earlier_games': len(weeks), 'last_week_used': max(weeks) if weeks else None,
                                 'group_lambda': [round(x, 6) for x in lam] if lam is not None else None,
                                 'player_weights': {pid: round(w, 6) for (_t, pid), w in sorted(weights.items())},
                                 'player_status': dict(sorted(status.items()))}
    return record
