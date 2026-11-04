#!/usr/bin/env python3
"""Week-over-week backtest of player snap shares from the lineup layer, 2022 to 2025 (research).

The grouping backtest (weekly_backtest.py) scored which grouping is on the field. This scores who: for every RB, FB, TE and
WR on a team's active roster (published weekly roster, status ACT) in a target game, the share of the team's offensive
snaps he plays, forecast from data available before that game's week, against the published nflverse share (offense_pct;
0 for an active player with no offensive snap).

The forecast runs the engine's own lineup code (participation_field.Field.advance) along the game's observed groupings,
RUNS times, starting from an empty lineup, and takes each player's mean share of the snaps. The groupings are given, so
this scores the player part of the layer only: the on-field rates (who enters) and the stint hazards (who leaves). Common
random numbers: run r of a team-game uses the same seed in every arm. The passer is the active QB with the most offensive
snaps in the team's earlier games this season (else the most in the previous season, else the lowest gsis id); he matters
only for groupings with a second QB.

Arms:
  P0  the table and code as they are now: the four seasons before the target, weighted 0.5 ** age
      (participation_model.RECENCY), and a leave hazard by class and stint only.
  P1  the grouping backtest's selected weights: the six seasons before the target, weighted 0.75 ** age.
  P1h P1 with a player-dependent leave hazard: the class hazard times ((1 - r) / (1 - c)) ** alpha, r the player's on-field
      rate and c his class's on-field mean rate (participation_field.Field.leave_factor). Found while building this
      backtest: on a 2021 sample the class-only hazard could not reproduce shares even given each player's share in the
      same game (mean absolute error 0.146; spread of shares 0.21 against 0.31 observed), because a regular leaves as
      often as a backup.
  P2  P1h plus each player's published snap share in the team's earlier games this season that he was active for
      (snap_update.player_weights).
  N   a reference that is not the lineup layer: the player's published share to date where he has an earlier active game
      this season, else P1h's forecast.

Selection, fixed before the 2022 to 2025 run, on 2019 to 2021 by mean absolute error: first alpha from ALPHAS (P1h, no
current-season data), then P2's N0 from N0S given that alpha.
Scores: mean absolute error and root mean squared error of the share per player-game, overall, by class, by part of the
season and for player-games with a positive observed share. Differences between arms have game-clustered bootstrap
intervals (a team-game is the cluster). Coverage is printed: the published skill snaps by players not on the active roster
(they cannot be drawn), and snap rows whose pfr id has no gsis id.

Usage: python3 weekly_player_backtest.py --prepare <inputs json> --raw <nflverse raw dir> --players-csv <players.csv>
       python3 weekly_player_backtest.py --tables <scrimmage_participation.csv.gz, 2016 to 2025> --inputs <inputs json>
           --players-csv <players.csv> --out <json> [--targets 2022,2023,2024,2025] [--tune 2019,2020,2021] [--runs 16]
           [--workers 1]
The first form reads the nflverse parquet files (snap counts, weekly rosters) once and writes them as JSON, so the run
needs no parquet reader.
"""
import argparse
import csv
import multiprocessing
import gzip
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / 'scripts' / 'nfl_sequence'))
import lineup_fit  # noqa: E402
import participation_field as pf  # noqa: E402
import participation_model as pm  # noqa: E402
import snap_update as su  # noqa: E402

FIRST_SEASON = 2016
P0, P1 = (0.5, 4), (0.75, 6)
N0S = (1, 2, 4, 8, 16, 32)
ALPHAS = (0.5, 1.0, 1.5, 2.0)
LINEUP_POS = {'QB', 'RB', 'FB', 'TE', 'WR'}
BOOT = 2000
KEEP = ('season', 'week', 'season_type', 'game_id', 'play_id', 'posteam', 'group', 'down', 'ydstogo', 'yardline_100',
        'qb_dropback')


def load_rows(path, seasons):
    """The rows participation_model.load_scrimmage keeps (same filters), with only the fields the fit reads."""
    rows = []
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            if int(row['season']) not in seasons or row['flag_defensive_label'] != '0':
                continue
            if row.get('flag_nonstandard_offense', '0') != '0':
                continue
            lean = {k: row[k] for k in KEEP}
            lean['ids'] = [x for x in row['offense_ids'].split(';') if x]
            rows.append(lean)
    return rows


def weights_for(target, decay, window):
    return {s: decay ** (target - 1 - s) for s in range(max(FIRST_SEASON, target - window), target)}


def fit_field(rows_by_season, seqs, positions, weights):
    seasons = set(weights)
    rows = [r for s in sorted(seasons) for r in rows_by_season[s]]
    fitted = lineup_fit.fit({k: v for k, v in seqs.items() if k[0] in seasons}, seasons, weights)
    rates = pm.fit_player_rates(rows, seasons, positions, weights)
    data = {'schema': pf.SCHEMA, 'seasons': sorted(seasons),
            'league_transitions': fitted['league_transitions'], 'team_transitions': fitted['team_transitions'],
            'league_transitions_by_intent': fitted['league_transitions_by_intent'],
            'team_transitions_by_intent': fitted['team_transitions_by_intent'], 'leave_counts': fitted['leave_counts'],
            'appearances': [[pid, team, group, w] for (pid, team, group), w in rates['appearances'].items()],
            'team_plays': [[team, group, w] for (team, group), w in rates['team_plays'].items()],
            'position_prior': [[pos, group, v] for (pos, group), v in rates['position_prior'].items()],
            'leave_reference_rate': pf.leave_reference_rate(rates['appearances'], rates['team_plays'],
                                                            rates['position_prior'], positions)}
    return pf.Field(data, 'backtest')


def period(season_type, week, last_regular):
    if season_type == 'POST':
        return 'post'
    return 'w01-04' if week <= 4 else 'w05-09' if week <= 9 else f'w10-{last_regular}'


def prepare(raw, players_csv, seasons):
    """{season: {'snaps': snap_update.load_published data, 'roster': [[team, week, gsis_id, position], ...] (status ACT,
    QB, RB, FB, TE and WR)}}."""
    import pyarrow.parquet as pq
    out = {}
    for season in seasons:
        r = pq.read_table(Path(raw) / 'weekly_rosters' / f'roster_weekly_{season}.parquet',
                          columns=['team', 'week', 'status', 'position', 'gsis_id']).to_pydict()
        roster = sorted([su.SNAP_TEAM.get(r['team'][i], r['team'][i]), int(r['week'][i]), r['gsis_id'][i], r['position'][i]]
                        for i in range(len(r['team']))
                        if r['status'][i] == 'ACT' and r['gsis_id'][i] and r['position'][i] in LINEUP_POS)
        out[str(season)] = {'snaps': su.load_published(raw, season, players_csv), 'roster': roster}
    return out


class Season:
    """One target season: its team-games (observed groupings), rosters and published snap counts."""

    def __init__(self, season, rows, inputs):
        self.season = season
        self.snaps = su.SnapCounts(inputs['snaps'], 'backtest')
        games = defaultdict(list)
        meta = {}
        for row in rows:
            key = (row['game_id'], row['posteam'])
            games[key].append((int(row['play_id']), row['group']))
            meta[key] = (int(row['week']), row['season_type'])
        self.games = [(meta[k][0], meta[k][1], k[0], k[1], [g for _p, g in sorted(v)]) for k, v in sorted(games.items())]
        self.last_regular = max(w for w, t, *_ in self.games if t == 'REG')
        self.roster = defaultdict(dict)  # (team, week) -> gsis_id -> position
        for team, week, pid, pos in inputs['roster']:
            self.roster[(team, week)][pid] = pos

    def players(self, team, week, prev_snaps):
        """The engine-shaped roster: the passer gets pos_rank 1, every other player 2."""
        roster = self.roster.get((team, week), {})
        qbs = [pid for pid, pos in roster.items() if pos == 'QB']

        def qb_key(pid):
            earlier = sum(self.snaps.player.get((team, w), {}).get(pid, 0.0) for w in self.snaps.weeks_before(team, week))
            return (-earlier, -prev_snaps.get(pid, 0.0), pid)
        starter = min(qbs, key=qb_key) if qbs else None
        return [{'gsis_id': pid, 'pos_abb': pos, 'pos_rank': 1 if pid == starter else 2}
                for pid, pos in sorted(roster.items())]


def simulate(field, team, groups, players, runs, key):
    """{gsis_id: mean share of the team-game's snaps} over `runs` lineup runs along the observed groupings."""
    on = Counter()
    status = Counter()
    n = 0
    for r in range(runs):
        draw = random.Random(f'{key}:{r}')
        lineup, prev = {}, None
        for group in groups:
            nxt, record = field.advance(team, lineup, group, players, draw, prev_group=prev)
            status[record['status']] += 1
            if nxt is None:
                continue
            lineup, prev = nxt, group
            n += 1
            on.update(lineup.keys())  # count the players on the field, not their stints
    return {pid: c / n for pid, c in on.items()} if n else {}, status


def score_season(season, field, arms, runs, prev_snaps):
    """[(team-game key, period, gsis_id, class, observed, {arm: forecast}, has_earlier_game)] and status counts.
    arms: {name: (alpha, n0)}; n0 None is no current-season update; 'N' is the share to date (needs 'P1h')."""
    out, status = [], Counter()
    snaps = season.snaps
    for week, season_type, game_id, team, groups in season.games:
        players = season.players(team, week, prev_snaps)
        team_snaps = snaps.team_snaps.get((team, week))
        if not players or not team_snaps:
            status['team_game_without_roster_or_snaps'] += 1
            continue
        skill = [p for p in players if p['pos_abb'] in su.SNAP_CLASS]
        published = snaps.player.get((team, week), {})
        status['published_skill_snaps'] += sum(s for pid, s in published.items()
                                               if su.SNAP_CLASS.get(snaps.position.get(pid)))
        status['published_skill_snaps_off_roster'] += sum(s for pid, s in published.items()
                                                          if su.SNAP_CLASS.get(snaps.position.get(pid))
                                                          and pid not in {p['gsis_id'] for p in skill})
        forecasts = {}
        for arm, spec in arms.items():
            if arm == 'N':
                continue
            alpha, n0 = spec
            field.leave_power = alpha
            field.player_weight = {}
            if n0 is not None:
                weights, st = su.player_weights(field, snaps, team, week, skill, n0)
                field.player_weight = weights
                status.update({f'{arm}:{k}': v for k, v in st.items()})
            shares, st = simulate(field, team, groups, players, runs, f'{game_id}:{team}')
            status.update({f'{arm}:lineup_{k}': v for k, v in st.items()})
            forecasts[arm] = shares
        field.player_weight, field.leave_power = {}, 0.0
        per = period(season_type, week, season.last_regular)
        for p in skill:
            pid = p['gsis_id']
            games, to_date = snaps.player_share(team, week, pid)
            f = {arm: forecasts[arm].get(pid, 0.0) for arm in forecasts}
            if 'N' in arms:
                f['N'] = to_date if games else f['P1h']
            out.append(((game_id, team), per, pid, su.SNAP_CLASS[p['pos_abb']],
                        published.get(pid, 0.0) / team_snaps, f, games > 0))
    return out, status


def summary(rows, arm, keep=lambda r: True):
    sel = [r for r in rows if keep(r)]
    if not sel:
        return None
    abs_err = sum(abs(r[5][arm] - r[4]) for r in sel) / len(sel)
    rmse = math.sqrt(sum((r[5][arm] - r[4]) ** 2 for r in sel) / len(sel))
    return {'mae': round(abs_err, 5), 'rmse': round(rmse, 5), 'n': len(sel),
            'mean_forecast': round(sum(r[5][arm] for r in sel) / len(sel), 5),
            'mean_observed': round(sum(r[4] for r in sel) / len(sel), 5)}


def report_arm(rows, arm):
    out = {'all': summary(rows, arm), 'observed_positive': summary(rows, arm, lambda r: r[4] > 0),
           'with_earlier_game': summary(rows, arm, lambda r: r[6])}
    for cls in pf.SKILL_CLASSES:
        out[f'class_{cls}'] = summary(rows, arm, lambda r, c=cls: r[3] == c)
    for per in sorted({r[1] for r in rows}):
        out[f'period_{per}'] = summary(rows, arm, lambda r, p=per: r[1] == p)
    return out


def diff_ci(rows, a, b, rng, keep=lambda r: True):
    """Mean absolute error of b minus a (negative: b is better), with a team-game bootstrap 95% interval."""
    clusters = defaultdict(lambda: [0.0, 0])
    for r in rows:
        if keep(r):
            c = clusters[r[0]]
            c[0] += abs(r[5][b] - r[4]) - abs(r[5][a] - r[4])
            c[1] += 1
    d = list(clusters.values())
    point = sum(x for x, _ in d) / sum(n for _, n in d)
    draws = []
    for _ in range(BOOT):
        pick = [d[rng.randrange(len(d))] for _ in d]
        draws.append(sum(x for x, _ in pick) / sum(n for _, n in pick))
    draws.sort()
    return {'mean': round(point, 5), 'ci95': [round(draws[int(0.025 * BOOT)], 5), round(draws[int(0.975 * BOOT) - 1], 5)],
            'team_games': len(d)}


CONTEXT = {}  # set in main before the worker pool forks, so the workers share the loaded table


def season_job(job):
    """Score one season: (season, season weights, arms) -> (season, rows, status, seconds)."""
    s, arm_weights, arms = job
    c = CONTEXT
    t = time.time()
    season = Season(s, c['rows_by_season'][s], c['inputs'][str(s)])
    season.games = season.games[::c['stride']]
    field = fit_field(c['rows_by_season'], c['seqs'], c['positions'], weights_for(s, *arm_weights))
    prev = Counter()
    if str(s - 1) in c['inputs']:
        for _t, _w, pid, pos, snaps in c['inputs'][str(s - 1)]['snaps']['player_snaps']:
            if pos == 'QB':
                prev[pid] += snaps
    out, st = score_season(season, field, arms, c['runs'], prev)
    st = dict(st)
    st['snap_coverage'] = season.snaps.coverage
    return s, out, st, time.time() - t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--prepare', type=Path, default=None, help='write the parquet inputs as JSON and stop')
    ap.add_argument('--raw', type=Path, default=None)
    ap.add_argument('--tables', type=Path, default=None)
    ap.add_argument('--inputs', type=Path, default=None)
    ap.add_argument('--players-csv', type=Path, required=True)
    ap.add_argument('--targets', default='2022,2023,2024,2025')
    ap.add_argument('--tune', default='2019,2020,2021')
    ap.add_argument('--runs', type=int, default=16)
    ap.add_argument('--stride', type=int, default=1, help='score every n-th team-game only (a quick check, not a result)')
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--out', type=Path, default=None)
    args = ap.parse_args()
    targets = [int(s) for s in args.targets.split(',')]
    tune = [int(s) for s in args.tune.split(',')]
    seasons = list(range(FIRST_SEASON, max(targets + tune) + 1))
    if args.prepare:
        data = prepare(args.raw, args.players_csv, seasons)
        args.prepare.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True))
        print(json.dumps({s: v['snaps']['coverage'] for s, v in data.items()}))
        return
    if not (args.tables and args.inputs and args.out):
        ap.error('a run needs --tables, --inputs and --out')
    t0 = time.time()
    rows = load_rows(args.tables, set(seasons))
    positions = pm.load_positions(args.players_csv.parent)
    rows_by_season = defaultdict(list)
    for row in rows:
        rows_by_season[int(row['season'])].append(row)
    seqs = lineup_fit.sequences(rows, positions, with_intent=True)
    del rows
    CONTEXT.update(rows_by_season=rows_by_season, seqs=seqs, positions=positions, stride=args.stride, runs=args.runs,
                   inputs=json.loads(args.inputs.read_text()))
    print(f'loaded {sum(len(v) for v in rows_by_season.values())} snaps in {time.time() - t0:.0f}s', flush=True)
    report = {'tables': str(args.tables), 'tables_sha256': pf.sha256_file(args.tables), 'inputs': str(args.inputs),
              'inputs_sha256': pf.sha256_file(args.inputs), 'players_csv_sha256': pf.sha256_file(args.players_csv),
              'runs': args.runs, 'stride': args.stride, 'targets': targets, 'tune': tune,
              'season_weights': {'P0': P0, 'P1': P1}, 'n0_grid': N0S, 'alpha_grid': ALPHAS}
    pool = multiprocessing.get_context('fork').Pool(args.workers) if args.workers > 1 else None

    def run(season_list, arm_weights, arms):
        jobs = [(s, arm_weights, arms) for s in season_list]
        results = pool.map(season_job, jobs) if pool else [season_job(j) for j in jobs]
        all_rows, status = [], {}
        for s, out, st, secs in sorted(results, key=lambda x: x[0]):
            all_rows += out
            status[s] = st
            print(f'  {s} {sorted(arms)} {len(out)} player-games {secs:.0f}s', flush=True)
        return all_rows, status

    # Tuning, on one fit per season: alpha first (with alpha 0 for reference), then N0 given alpha.
    tune_rows, tune_status = run(tune, P1, dict({'P1': (0.0, None)}, **{f'P1h_{a}': (a, None) for a in ALPHAS}))
    report['tune_alpha_mae'] = {arm: summary(tune_rows, arm)['mae'] for arm in ['P1'] + [f'P1h_{a}' for a in ALPHAS]}
    alpha = min(ALPHAS, key=lambda a: (report['tune_alpha_mae'][f'P1h_{a}'], a))
    print('tune alpha', report['tune_alpha_mae'], 'selected', alpha, flush=True)
    tune_rows, tune_status2 = run(tune, P1, {f'P2_{n0}': (alpha, n0) for n0 in N0S})
    report['tune_n0_mae'] = {f'P2_{n0}': summary(tune_rows, f'P2_{n0}')['mae'] for n0 in N0S}
    best = min(N0S, key=lambda n0: (report['tune_n0_mae'][f'P2_{n0}'], n0))
    report['selected'] = {'alpha': alpha, 'n0': best}
    report['tune_status'] = {'alpha': tune_status, 'n0': tune_status2}
    print('tune N0', report['tune_n0_mae'], 'selected', best, flush=True)
    del tune_rows

    p0_rows, p0_status = run(targets, P0, {'P0': (0.0, None)})
    rows_, status = run(targets, P1, {'P1': (0.0, None), 'P1h': (alpha, None), 'P2': (alpha, best), 'N': None})
    if len(rows_) != len(p0_rows):
        raise ValueError(f'P0 scored {len(p0_rows)} player-games and P1 {len(rows_)}')
    for r, r0 in zip(rows_, p0_rows):
        if r[:4] != r0[:4]:
            raise ValueError('P0 and P1 scored different player-games')
        r[5]['P0'] = r0[5]['P0']
    del p0_rows
    report['status'] = {'P0': p0_status, 'P1_P1h_P2_N': status}
    arms_out = ('P0', 'P1', 'P1h', 'P2', 'N')
    report['scores'] = {arm: report_arm(rows_, arm) for arm in arms_out}
    report['scores_by_season'] = {arm: {s: summary([r for r in rows_ if r[0][0][:4] == str(s)], arm)['mae']
                                        for s in targets} for arm in arms_out}
    rng = random.Random(20261104)
    report['differences_mae'] = {
        name: {'all': diff_ci(rows_, a, b, rng),
               'observed_positive': diff_ci(rows_, a, b, rng, lambda r: r[4] > 0),
               'with_earlier_game': diff_ci(rows_, a, b, rng, lambda r: r[6]),
               **{f'period_{p}': diff_ci(rows_, a, b, rng, lambda r, p=p: r[1] == p) for p in sorted({r[1] for r in rows_})}}
        for name, a, b in (('P1_minus_P0', 'P0', 'P1'), ('P1h_minus_P1', 'P1', 'P1h'), ('P2_minus_P1h', 'P1h', 'P2'),
                           ('N_minus_P2', 'P2', 'N'))}
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True))
    for arm in arms_out:
        print(arm, {k: v['mae'] for k, v in report['scores'][arm].items() if v})
    for name, v in report['differences_mae'].items():
        print(name, {p: (x['mean'], x['ci95']) for p, x in v.items()})


if __name__ == '__main__':
    main()
