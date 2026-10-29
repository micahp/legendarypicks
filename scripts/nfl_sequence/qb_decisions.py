"""Pregame QB target-role and scramble decisions from cutoff-safe nflverse play data.

The table is keyed by team and passer so a quarterback's former team's target
system is not silently assigned to his new roster. A sparse QB cell backs off
to that team's prior-season cell, then to the league cell. Every decision is
made before the outcome row is sampled.
"""
import hashlib
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import e0_single_play as e0

MODEL_VERSION = 'slc-qb-decisions-v1'
FIRST_SEASON = 2022
SHRINKAGE = 20.0
TARGET_ROLES = ('RB', 'WR', 'TE', 'Other')


def target_role(position):
    if position in ('RB', 'FB'):
        return 'RB'
    if position in ('WR', 'TE'):
        return position
    return 'Other'


def cell_of(down, togo, yardline):
    return (int(down), e0.ydstogo_bucket(togo), e0.yardline_bucket(yardline))


def _rng(seed_text):
    seed = int.from_bytes(hashlib.sha256(str(seed_text).encode()).digest()[:8], 'big')
    return random.Random(seed)


def _distribution(counts, prior, strength=SHRINKAGE, categories=TARGET_ROLES):
    prior_total = sum(prior.values())
    if prior_total <= 0:
        prior = {category: 1.0 / len(categories) for category in categories}
    else:
        prior = {category: prior.get(category, 0) / prior_total for category in categories}
    n = sum(counts.values())
    denominator = n + strength
    if denominator <= 0:
        return prior
    return {category: (counts.get(category, 0) + strength * prior[category]) / denominator
            for category in categories}


def load(db, cutoff_season):
    """Fit team/QB decision counts using regular-season rows strictly before cutoff_season."""
    cutoff = int(cutoff_season)
    seasons = list(range(FIRST_SEASON, cutoff))
    if not seasons:
        raise ValueError(f'QB decision model needs data from {FIRST_SEASON} or later before cutoff {cutoff}')
    marks = ','.join('?' for _ in seasons)
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        duplicate_positions = con.execute(
            "SELECT nfl_gsis_id FROM players WHERE lower(league)='nfl' AND nfl_gsis_id IS NOT NULL "
            "GROUP BY nfl_gsis_id HAVING COUNT(DISTINCT COALESCE(position,'')) > 1 LIMIT 1").fetchone()
        if duplicate_positions:
            raise ValueError(f'conflicting NFL positions for GSIS id {duplicate_positions[0]}')
        rows = con.execute(
            f"SELECT p.season,p.game_id,p.play_id,p.posteam,"
            f"COALESCE(CASE WHEN q.position='QB' THEN p.passer_player_id END, "
            f"CASE WHEN p.qb_scramble=1 AND s.position='QB' THEN p.rusher_player_id END),"
            f"p.qb_dropback,p.qb_scramble,"
            f"p.pass_attempt,p.receiver_player_id,p.down,p.ydstogo,p.yardline_100,r.position,"
            f"CASE WHEN q.position='QB' OR (p.qb_scramble=1 AND s.position='QB') THEN 'QB' "
            f"ELSE COALESCE(q.position,s.position) END "
            f"FROM nfl_pbp p LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            f"WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) r ON r.nfl_gsis_id=p.receiver_player_id "
            f"LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            f"WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) s ON s.nfl_gsis_id=p.rusher_player_id "
            f"LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            f"WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) q ON q.nfl_gsis_id=p.passer_player_id "
            f"WHERE p.season IN ({marks}) AND p.week BETWEEN 1 AND 18 AND p.posteam IS NOT NULL "
            f"AND p.down BETWEEN 1 AND 4 AND p.ydstogo IS NOT NULL AND p.yardline_100 IS NOT NULL "
            f"AND (p.qb_dropback=1 OR (p.pass_attempt=1 AND p.passer_player_id IS NOT NULL)) "
            f"ORDER BY p.game_id,p.play_id", seasons).fetchall()
    finally:
        con.close()

    qb_cell = defaultdict(Counter)
    team_cell = defaultdict(Counter)
    league_cell = defaultdict(Counter)
    target_qb_cell = defaultdict(Counter)
    target_team_cell = defaultdict(Counter)
    target_league_cell = defaultdict(Counter)
    row_target_roles = {}
    total_dropbacks = 0
    missing_qb_ids = 0
    scramble_rows = 0
    missing_scrambler_ids = 0
    non_qb_passers = 0
    target_rows = 0
    unmapped_target_positions = 0

    for season, game_id, play_id, team, qb, dropback, scramble, attempt, receiver, down, togo, yl, position, qb_position in rows:
        cell = cell_of(down, togo, yl)
        if dropback == 1:
            total_dropbacks += 1
            if qb_position is not None and qb_position != 'QB':
                non_qb_passers += 1
                continue
            if qb is None:
                missing_qb_ids += 1
                missing_scrambler_ids += int(scramble == 1)
            else:
                outcome = 'scramble' if scramble == 1 else 'pass'
                qb_cell[(team, qb, cell)][outcome] += 1
                team_cell[(team, cell)][outcome] += 1
                league_cell[cell][outcome] += 1
                scramble_rows += int(outcome == 'scramble')
        if attempt == 1 and qb is not None and qb_position == 'QB' and receiver is not None:
            role = target_role(position)
            key = (game_id, int(play_id))
            if key in row_target_roles and row_target_roles[key] != role:
                raise ValueError(f'conflicting target-role identity for {key}')
            row_target_roles[key] = role
            target_qb_cell[(team, qb, cell)][role] += 1
            target_team_cell[(team, cell)][role] += 1
            target_league_cell[cell][role] += 1
            target_rows += 1
            unmapped_target_positions += int(position is None)

    if not total_dropbacks:
        raise ValueError(f'no QB dropbacks in prior seasons {seasons}')
    digest_rows = {
        'qb_cell': sorted((team, qb, cell, sorted(counts.items()))
                          for (team, qb, cell), counts in qb_cell.items()),
        'team_cell': sorted((team, cell, sorted(counts.items()))
                            for (team, cell), counts in team_cell.items()),
        'target_qb_cell': sorted((team, qb, cell, sorted(counts.items()))
                                 for (team, qb, cell), counts in target_qb_cell.items()),
        'row_target_roles': sorted((game_id, play_id, role)
                                   for (game_id, play_id), role in row_target_roles.items()),
    }
    sha = hashlib.sha256(json.dumps(digest_rows, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    return {
        'model_version': MODEL_VERSION, 'cutoff_season': cutoff, 'source_seasons': seasons,
        'qb_cell': dict(qb_cell), 'team_cell': dict(team_cell), 'league_cell': dict(league_cell),
        'target_qb_cell': dict(target_qb_cell), 'target_team_cell': dict(target_team_cell),
        'target_league_cell': dict(target_league_cell), 'row_target_roles': row_target_roles,
        'sha256': sha, 'source_counts': {
            'qb_dropbacks_in_model_state': total_dropbacks,
            'qb_dropbacks_missing_id': missing_qb_ids,
            'qb_scrambles_missing_qb_identity': missing_scrambler_ids,
            'non_qb_passers_excluded': non_qb_passers,
            'qb_scrambles': scramble_rows,
            'target_rows_with_mapped_receiver_id': target_rows,
            'target_rows_without_position': unmapped_target_positions,
            'qb_team_units': len({(team, qb) for team, qb, _cell in qb_cell}),
        },
    }


def _scramble_probability(table, team, qb, cell):
    league = table['league_cell'].get(cell, Counter())
    league_n = sum(league.values())
    league_p = league.get('scramble', 0) / league_n if league_n else 0.0
    team_counts = table['team_cell'].get((team, cell), Counter())
    team_n = sum(team_counts.values())
    team_p = ((team_counts.get('scramble', 0) + SHRINKAGE * league_p) / (team_n + SHRINKAGE)
              if team_n + SHRINKAGE else league_p)
    own = table['qb_cell'].get((team, qb, cell), Counter())
    own_n = sum(own.values())
    return (own.get('scramble', 0) + SHRINKAGE * team_p) / (own_n + SHRINKAGE), own_n


def _target_distribution(table, team, qb, cell):
    league = table['target_league_cell'].get(cell, Counter())
    team_prior = _distribution(table['target_team_cell'].get((team, cell), Counter()), league)
    own = table['target_qb_cell'].get((team, qb, cell), Counter())
    return _distribution(own, team_prior), sum(own.values())


def draw(table, team, qb, down, togo, yardline, available_roles, seed_text):
    """Draw a QB action and, if passing, a target role before the outcome is selected."""
    cell = cell_of(down, togo, yardline)
    p_scramble, scramble_n = _scramble_probability(table, team, qb, cell)
    scramble_supported = table.get('scramble_cells') is None or cell in table['scramble_cells']
    if not scramble_supported:
        p_scramble = 0.0
    rng = _rng(seed_text)
    is_scramble = rng.random() < p_scramble
    out = {'action': 'scramble' if is_scramble else 'pass',
           'scramble_probability': p_scramble, 'scramble_history_n': scramble_n}
    if not scramble_supported:
        out['scramble_fallback'] = 'no_eligible_scramble_rows_in_cell'
    if is_scramble:
        return out
    roles = tuple(role for role in TARGET_ROLES if role in set(available_roles))
    if not roles:
        raise ValueError(f'QB {qb} has no eligible target roles on team {team}')
    distribution, target_n = _target_distribution(table, team, qb, cell)
    eligible_mass = sum(max(0.0, distribution[role]) for role in roles)
    if eligible_mass <= 0:
        role_probabilities = {role: 1.0 / len(roles) for role in roles}
        out['target_role_fallback'] = 'no_model_mass_for_available_roles'
    else:
        role_probabilities = {role: max(0.0, distribution[role]) / eligible_mass for role in roles}
    weights = [role_probabilities[role] for role in roles]
    out['target_role'] = rng.choices(roles, weights=weights, k=1)[0]
    out['target_role_probabilities'] = role_probabilities
    out['target_role_history_n'] = target_n
    return out


def row_target_role(table, row):
    """Published receiver-role label for a source play, or None when the target identity is absent."""
    return table['row_target_roles'].get((row.get('game_id'), int(row.get('play_id'))))


def manifest(table, git_commit):
    return {
        'model_version': table['model_version'], 'source_seasons': table['source_seasons'],
        'cutoff_season': table['cutoff_season'], 'git_commit': git_commit,
        'source_code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'source': 'nfl_pbp qb_dropback, qb_scramble, pass_attempt, passer_player_id and rusher_player_id; canonical QB and receiver positions joined by GSIS id',
        'source_sha256': table['sha256'], 'shrinkage_strength': SHRINKAGE,
        'source_counts': dict(table['source_counts']),
        'scramble_definition': 'qb_scramble among nflverse qb_dropback rows; scrambler identity uses rusher_player_id joined by GSIS id when its canonical position is QB',
        'transfer_rule': 'QB decision histories remain keyed by team and passer; a new team uses its team and league priors',
    }
