"""Decision model v1 categories A to N as SLC pre-event decisions (research, not adopted).

The decision model (splits/decision_model.py, commit fd2a5aea) labels every scrimmage play in categories A to N and gives each team a
prior for each label by situation: the team's share of the label within the decision cell, shrunk to the league's share with K = 20.
This module makes those labels SLC's pre-event decisions:

- Before the outcome, each category that applies to the intent is drawn from the offense's prior for the play's situation cell
  (dropbacks: A, D, E, G, I, N; runs: B, C; both: F, H, J, K, L, M).
- The outcome pool is conditioned on the drawn labels. Each label multiplies the outcome weights by its lift, averaged over the labels
  in log space so the overlapping categories do not compound, and the drawn row is taken from the rows that carry the same labels.

The prior is built from the most recent season before the cutoff, as the decision model's own prior is (2025 for a 2026 forecast).
Charting categories (G to N) exist from 2022 on, so a cutoff before 2023 has no prior and fails loudly. Pass length comes from the
nflverse play-by-play release, the decision model's source. Every other label comes from the play-by-play and charting tables.
"""
import hashlib
import math
import random
import sqlite3
from collections import Counter, defaultdict

import e0_single_play as e0

CAT_ROLES = {
    'A': ['RB', 'WR', 'TE', 'Other'],
    'B': ['RB', 'QB', 'WR_TE', 'Other'],
    'C': ['guard', 'tackle', 'end'],
    'D': ['short', 'deep'],
    'E': ['left', 'middle', 'right'],
    'F': ['yes', 'no'],
    'G': ['yes', 'no'],
    'H': ['yes', 'no'],
    'I': ['yes', 'no'],
    'J': ['S', 'U', 'P'],
    'K': ['L', 'M', 'R'],
    'L': ['0', '1', '2', '3+'],
    'M': ['<=5', '6', '7', '8+'],
    'N': ['3-4', '5+'],
}
CATS = tuple(CAT_ROLES)
PASS_CATS = ('A', 'D', 'E', 'G', 'I', 'N')  # drawn on a dropback
RUN_CATS = ('B', 'C')  # drawn on a run
ALIGN_CATS = ('F', 'H', 'J', 'K', 'L', 'M')  # pre-snap alignment, drawn on either intent
K = 20.0  # the decision model's chosen shrinkage weight, from its 2025 validation
FIRST_CHARTED_SEASON = 2022  # FTN charting starts in 2022
PBP_PARQUET = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw/pbp/play_by_play_{season}.parquet'  # the decision model's source
PLAYERS_PARQUET = '/root/lp-snapshots/nfl-backfill-2026-10-27/raw/players/players.parquet'  # its position source


def role_of_receiver(pos):
    if pos in ('RB', 'FB'):
        return 'RB'
    if pos in ('WR', 'TE'):
        return pos
    return 'Other'


def role_of_rusher(pos):
    if pos == 'QB':
        return 'QB'
    if pos in ('RB', 'FB'):
        return 'RB'
    if pos in ('WR', 'TE'):
        return 'WR_TE'
    return 'Other'


def cell_of(down, togo, yl):
    """The decision model's cell: down, distance in three bands, and the red zone or not."""
    dist = 'short' if togo <= 3 else ('medium' if togo <= 7 else 'long')
    zone = 'red' if yl <= 20 else 'other'
    return f'{int(down)}|{dist}|{zone}'


def label_row(r):
    """Labels for one scrimmage play. `r` holds the fields load_rows selects; a category the play does not have is None."""
    out = {c: None for c in CATS}
    is_pass = r['is_pass']
    is_run = r['is_run'] and not r.get('qb_scramble', False)
    if is_pass and r['receiver_pos'] is not None:
        out['A'] = role_of_receiver(r['receiver_pos'])
    if is_run and r['rusher_pos'] is not None:
        out['B'] = role_of_rusher(r['rusher_pos'])
        if r['rusher_pos'] in ('RB', 'FB') and r['run_gap'] in ('guard', 'tackle', 'end'):
            out['C'] = r['run_gap']
    if is_pass and r['pass_length'] in ('short', 'deep'):
        out['D'] = r['pass_length']
    if is_pass and r['pass_location'] in ('left', 'middle', 'right'):
        out['E'] = r['pass_location']
    if r['shotgun'] is not None:
        out['F'] = 'yes' if int(r['shotgun']) == 1 else 'no'
    if is_pass and r['is_play_action'] is not None:
        out['G'] = 'yes' if int(r['is_play_action']) == 1 else 'no'
    if r['is_motion'] is not None:
        out['H'] = 'yes' if int(r['is_motion']) == 1 else 'no'
    if is_pass and r['n_blitzers'] is not None:
        out['I'] = 'yes' if int(r['n_blitzers']) >= 1 else 'no'
    if r['qb_location'] not in (None, '0'):
        out['J'] = r['qb_location']
    if r['starting_hash'] not in (None, '0'):
        out['K'] = r['starting_hash']
    if r['n_offense_backfield'] is not None:
        n = int(r['n_offense_backfield'])
        out['L'] = '3+' if n >= 3 else str(n)
    if r['n_defense_box'] is not None and int(r['n_defense_box']) != 0:
        n = int(r['n_defense_box'])
        out['M'] = '<=5' if n <= 5 else ('8+' if n >= 8 else str(n))
    if is_pass and r['n_pass_rushers'] is not None and int(r['n_pass_rushers']) >= 3:
        out['N'] = '3-4' if int(r['n_pass_rushers']) <= 4 else '5+'
    return out


def _positions():
    """gsis id -> position from the nflverse players release, the decision model's source. The database's position can differ for
    a player (one rusher is a WR there and an RB in this release), and the labels follow the decision model."""
    import pyarrow.parquet as pq
    table = pq.read_table(PLAYERS_PARQUET, columns=['gsis_id', 'position']).to_pydict()
    return dict(zip(table['gsis_id'], table['position']))


def _pass_length(seasons):
    """(game_id, play_id) -> 'short' or 'deep' from the nflverse play-by-play release (absent where the release has none)."""
    import pyarrow.parquet as pq
    out = {}
    for season in seasons:
        table = pq.read_table(PBP_PARQUET.format(season=season), columns=['game_id', 'play_id', 'pass_length']).to_pydict()
        for g, p, length in zip(table['game_id'], table['play_id'], table['pass_length']):
            if p is not None and length is not None:
                out[(g, int(p))] = length
    return out


def load_rows(db, seasons):
    """Labelled scrimmage plays for the given seasons, from the play-by-play joined to FTN charting. Regular season only."""
    seasons = sorted(int(s) for s in seasons)
    if not seasons or seasons[0] < FIRST_CHARTED_SEASON:
        raise ValueError(f'decision categories need FTN charting seasons ({FIRST_CHARTED_SEASON} on) before the cutoff')
    positions = _positions()
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        marks = ','.join('?' * len(seasons))
        rows = con.execute(
            f"SELECT p.game_id, p.play_id, p.season, p.posteam, p.pass_attempt, p.rush_attempt, p.qb_scramble, p.down, p.ydstogo, "
            f"p.yardline_100, p.pass_location, p.run_gap, p.shotgun, p.receiver_player_id, p.rusher_player_id, "
            f"c.starting_hash, c.qb_location, c.n_offense_backfield, c.n_defense_box, c.is_play_action, c.is_motion, "
            f"c.n_blitzers, c.n_pass_rushers FROM nfl_pbp p JOIN nfl_hist_ftn_charting c "
            f"ON c.nflverse_game_id = p.game_id AND c.nflverse_play_id = p.play_id "
            f"WHERE p.season IN ({marks}) AND p.week <= 18 AND p.play_type IN ('pass', 'run') AND p.posteam IS NOT NULL "
            f"AND p.down BETWEEN 1 AND 4 AND p.ydstogo IS NOT NULL AND p.yardline_100 IS NOT NULL", seasons).fetchall()
    finally:
        con.close()
    length = _pass_length(seasons)
    out = []
    for (g, p, season, team, pa, ru, scramble, down, togo, yl, ploc, rgap, shot, rec, rush,
         hash_, qbl, nob, ndb, pa_flag, motion, blitz, rushers) in rows:
        is_pass = pa == 1
        r = {'is_pass': is_pass, 'is_run': (ru == 1) and not is_pass and scramble != 1, 'qb_scramble': scramble == 1,
             'receiver_pos': positions.get(rec) if rec else None,
             'rusher_pos': positions.get(rush) if rush else None, 'pass_length': length.get((g, int(p))),
             'pass_location': ploc, 'run_gap': rgap, 'shotgun': shot, 'is_play_action': pa_flag, 'is_motion': motion,
             'n_blitzers': blitz, 'n_pass_rushers': rushers, 'qb_location': qbl, 'starting_hash': hash_,
             'n_offense_backfield': nob, 'n_defense_box': ndb}
        labels = label_row(r)
        if not any(labels.values()):
            continue
        out.append({'game_id': g, 'play_id': int(p), 'season': int(season), 'team': team,
                    'cell': cell_of(down, togo, yl), 'labels': labels, 'qb_scramble': scramble == 1})
    return out


def fit(rows, prior_season):
    """The prior table from the prior season's rows: league and team counts per category, cell and value."""
    league = {c: defaultdict(Counter) for c in CATS}
    team = {c: defaultdict(Counter) for c in CATS}
    for row in rows:
        if row['season'] != int(prior_season):
            continue
        for c, value in row['labels'].items():
            if value is None:
                continue
            league[c][row['cell']][value] += 1
            team[c][(row['team'], row['cell'])][value] += 1
    return {'league': league, 'team': team, 'k': K, 'prior_season': int(prior_season)}


def distribution(table, team, cell, cat):
    """P(value) for this team in this cell: team counts plus k times the league share, over the team's total plus k."""
    values = CAT_ROLES[cat]
    league = table['league'][cat].get(cell, Counter())
    league_total = sum(league.values())
    own = table['team'][cat].get((team, cell), Counter())
    own_total = sum(own.values())
    out = {}
    for v in values:
        league_share = league[v] / league_total if league_total else 1.0 / len(values)
        out[v] = (own[v] + table['k'] * league_share) / (own_total + table['k'])
    total = sum(out.values())
    return {v: share / total for v, share in out.items()}


def draw(table, team, down, togo, yl, intent, seed_text, only=None):
    """One label per applicable category, drawn before the outcome. None for a category with no prior in its cell.

    `only` limits the draw to those categories (the playbook input draws pass depth, pass location and run gap only)."""
    if intent == 'dropback':
        cats = [c for c in CATS if c in PASS_CATS or c in ALIGN_CATS]
    elif intent == 'run':
        cats = [c for c in CATS if c in RUN_CATS or c in ALIGN_CATS]
    else:
        return None
    if only is not None:
        cats = [c for c in cats if c in only]
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_text.encode()).digest()[:8], 'big'))
    cell = cell_of(down, togo, yl)
    out = {}
    for c in cats:
        if not table['league'][c].get(cell):
            out[c] = None  # no prior-season plays in this cell for this category
            continue
        shares = distribution(table, team, cell, c)
        values = list(shares)
        out[c] = rng.choices(values, weights=[shares[v] for v in values], k=1)[0]
    return out


def attach(rows, labelled):
    """Set row['labels'] on each pool row from its (game_id, play_id); an empty dict where the play has no charting."""
    by_key = {(r['game_id'], r['play_id']): r['labels'] for r in labelled}
    for row in rows:
        row['labels'] = by_key.get((row['game_id'], int(row['play_id'])), {})
    return rows


def label_key(cat, value):
    """The key a drawn label is looked up by in the sampler's lift tables."""
    return f'{cat}={value}'


def geometric_mean(values):
    """Average in log space. An empty list is a neutral 1.0."""
    if not values:
        return 1.0
    return math.exp(sum(math.log(v) for v in values) / len(values))
