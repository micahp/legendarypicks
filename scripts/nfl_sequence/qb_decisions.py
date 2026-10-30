"""Pregame QB target-role, scramble, and run-role decisions from cutoff-safe nflverse play data.

The table is keyed by team and passer so a quarterback's former team's target
system is not silently assigned to his new roster. A sparse QB cell backs off
to that team's prior-season cell, then to the league cell. Every decision is
made before the outcome row is sampled.
"""
import hashlib
import json
import math
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import e0_single_play as e0

MODEL_VERSION = 'slc-qb-decisions-v2'
FIRST_SEASON = 2022
SHRINKAGE = 20.0
TARGET_ROLES = ('RB', 'WR', 'TE', 'Other')
QB_RUN_STYLE_MIN_SUPPORT = 20
SCRAMBLE_SUPPORT_MIN = {'exact_cell': 10, 'down_field': 25, 'down_distance': 25, 'field_zone': 50,
                        'league_intent': 50}


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
            f"AND COALESCE(p.penalty,0) != 1 AND COALESCE(p.two_point_attempt,0) != 1 "
            f"AND (p.qb_dropback=1 OR (p.pass_attempt=1 AND p.passer_player_id IS NOT NULL)) "
            f"ORDER BY p.game_id,p.play_id", seasons).fetchall()
        run_rows = con.execute(
            f"SELECT p.season,p.game_id,p.posteam,p.rusher_player_id,p.down,p.ydstogo,p.yardline_100,"
            f"p.rush_attempt,p.qb_scramble,p.qb_dropback,p.two_point_attempt,p.penalty,s.position "
            f"FROM nfl_pbp p LEFT JOIN (SELECT nfl_gsis_id, MIN(position) AS position FROM players "
            f"WHERE lower(league)='nfl' GROUP BY nfl_gsis_id) s ON s.nfl_gsis_id=p.rusher_player_id "
            f"WHERE p.season IN ({marks}) AND p.week BETWEEN 1 AND 18 AND p.play_type='run' "
            f"AND p.rush_attempt=1 AND p.posteam IS NOT NULL AND p.down BETWEEN 1 AND 4 "
            f"AND p.ydstogo IS NOT NULL AND p.yardline_100 IS NOT NULL "
            f"AND COALESCE(p.penalty,0) != 1 AND COALESCE(p.two_point_attempt,0) != 1 "
            f"ORDER BY p.game_id,p.play_id", seasons).fetchall()
    finally:
        con.close()

    qb_cell = defaultdict(Counter)
    team_cell = defaultdict(Counter)
    league_cell = defaultdict(Counter)
    target_qb_cell = defaultdict(Counter)
    target_team_cell = defaultdict(Counter)
    target_league_cell = defaultdict(Counter)
    qb_run_player_cell = defaultdict(Counter)
    qb_run_team_cell = defaultdict(Counter)
    qb_run_league_cell = defaultdict(Counter)
    qb_run_player_all = defaultdict(Counter)
    qb_run_team_all = defaultdict(Counter)
    qb_run_league_all = Counter()
    row_target_roles = {}
    total_dropbacks = 0
    missing_qb_ids = 0
    scramble_rows = 0
    missing_scrambler_ids = 0
    non_qb_passers = 0
    target_rows = 0
    unmapped_target_positions = 0

    primary_counts = defaultdict(Counter)
    for season, game_id, _play_id, team, qb, dropback, *_rest in rows:
        if qb is not None and dropback == 1:
            primary_counts[(season, game_id, team)][qb] += 1
    primary_qb = {}
    ambiguous_primary_qb_games = 0
    for key, counts in primary_counts.items():
        maximum = max(counts.values())
        leaders = sorted(qb for qb, count in counts.items() if count == maximum)
        if len(leaders) == 1:
            primary_qb[key] = leaders[0]
        else:
            ambiguous_primary_qb_games += 1

    primary_qb_non_scramble_run_rows = 0
    qb_run_opportunities = 0
    for (season, game_id, team, rusher, down, togo, yardline, rush_attempt, scramble,
         dropback, two_point, penalty, position) in run_rows:
        if (rush_attempt != 1 or scramble == 1 or dropback == 1
                or two_point == 1 or penalty == 1 or position == 'QB' and rusher is None):
            continue
        qb = primary_qb.get((season, game_id, team))
        if qb is None:
            continue
        # A different QB's relief snaps cannot be assigned to the primary passer's style profile.
        if position == 'QB' and rusher != qb:
            continue
        cell = cell_of(down, togo, yardline)
        action = 'qb' if position == 'QB' and rusher == qb else 'other'
        qb_run_player_cell[(team, qb, cell)][action] += 1
        qb_run_team_cell[(team, cell)][action] += 1
        qb_run_league_cell[cell][action] += 1
        qb_run_player_all[(team, qb)][action] += 1
        qb_run_team_all[team][action] += 1
        qb_run_league_all[action] += 1
        qb_run_opportunities += 1
        primary_qb_non_scramble_run_rows += int(action == 'qb')

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
        'qb_run_player_cell': sorted((team, qb, cell, sorted(counts.items()))
                                     for (team, qb, cell), counts in qb_run_player_cell.items()),
        'qb_run_team_cell': sorted((team, cell, sorted(counts.items()))
                                   for (team, cell), counts in qb_run_team_cell.items()),
    }
    sha = hashlib.sha256(json.dumps(digest_rows, separators=(',', ':'), sort_keys=True).encode()).hexdigest()
    return {
        'model_version': MODEL_VERSION, 'cutoff_season': cutoff, 'source_seasons': seasons,
        'qb_cell': dict(qb_cell), 'team_cell': dict(team_cell), 'league_cell': dict(league_cell),
        'target_qb_cell': dict(target_qb_cell), 'target_team_cell': dict(target_team_cell),
        'target_league_cell': dict(target_league_cell), 'row_target_roles': row_target_roles,
        'qb_run_player_cell': dict(qb_run_player_cell), 'qb_run_team_cell': dict(qb_run_team_cell),
        'qb_run_league_cell': dict(qb_run_league_cell), 'qb_run_player_all': dict(qb_run_player_all),
        'qb_run_team_all': dict(qb_run_team_all), 'qb_run_league_all': qb_run_league_all,
        'sha256': sha, 'source_counts': {
            'qb_dropbacks_in_model_state': total_dropbacks,
            'qb_dropbacks_missing_id': missing_qb_ids,
            'qb_scrambles_missing_qb_identity': missing_scrambler_ids,
            'non_qb_passers_excluded': non_qb_passers,
            'qb_scrambles': scramble_rows,
            'primary_qb_run_opportunities': qb_run_opportunities,
            'primary_qb_non_scramble_run_rows': primary_qb_non_scramble_run_rows,
            'qb_run_profile_qb_units': len(qb_run_player_all),
            'ambiguous_primary_qb_games_skipped': ambiguous_primary_qb_games,
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


def _qb_run_rate(counts, prior, strength=SHRINKAGE):
    total = sum(counts.values())
    if total == 0:
        return prior, 0
    return (counts.get('qb', 0) + strength * prior) / (total + strength), total


def qb_run_role_style(table, team, qb, cell):
    """Player-specific non-scramble QB run-role tendency relative to the team prior.

    QB run rows exclude explicit scrambles, kneels, dropbacks, penalties, and two-point
    plays. The source does not identify QB sneaks separately, so the residual may include
    sneaks. Exposure is ordinary team run plays in games where this QB led the team in
    dropbacks. Sparse player rates shrink toward the team's rate.
    """
    player_cell = table.get('qb_run_player_cell')
    team_cell = table.get('qb_run_team_cell')
    league_cell = table.get('qb_run_league_cell')
    player_all = table.get('qb_run_player_all')
    team_all = table.get('qb_run_team_all')
    league_all = table.get('qb_run_league_all')
    if not all(value is not None for value in (player_cell, team_cell, league_cell,
                                                player_all, team_all, league_all)):
        return None
    league_n = sum(league_all.values())
    league_rate = league_all.get('qb', 0) / league_n if league_n else 0.0
    league_exact = league_cell.get(cell, Counter())
    league_exact_n = sum(league_exact.values())
    league_cell_rate = (league_exact.get('qb', 0) / league_exact_n
                        if league_exact_n else league_rate)
    team_overall, team_overall_n = _qb_run_rate(team_all.get(team, Counter()), league_rate)
    team_exact = team_cell.get((team, cell), Counter())
    team_rate, team_exact_n = _qb_run_rate(team_exact, league_cell_rate)
    player_key = (team, qb)
    own_overall, own_overall_n = _qb_run_rate(player_all.get(player_key, Counter()), team_overall)
    own_exact = player_cell.get((team, qb, cell), Counter())
    own_exact_n = sum(own_exact.values())

    if own_exact_n:
        own_rate, _ = _qb_run_rate(own_exact, team_rate)
        reference_rate = team_rate
        support_level = ('player_exact_cell' if own_exact_n >= QB_RUN_STYLE_MIN_SUPPORT
                         else 'player_exact_cell_shrunk')
        support_n = own_exact_n
    elif own_overall_n >= QB_RUN_STYLE_MIN_SUPPORT:
        own_rate, reference_rate = own_overall, team_overall
        support_level = 'player_all_context'
        support_n = own_overall_n
    elif own_overall_n:
        return {
            'support_level': 'team_only', 'support_n': own_overall_n,
            'player_context_support_n': 0, 'player_total_support_n': own_overall_n,
            'team_context_support_n': team_exact_n, 'team_total_support_n': team_overall_n,
            'league_context_support_n': league_exact_n,
            'team_probability': team_rate, 'reference_probability': team_rate,
            'player_probability': own_overall,
            'style_odds_ratio': 1.0, 'adjusted': False,
        }
    else:
        return None

    eps = 1e-6
    log_odds_ratio = (math.log(max(eps, own_rate) / max(eps, 1.0 - own_rate))
                      - math.log(max(eps, reference_rate) / max(eps, 1.0 - reference_rate)))
    return {
        'support_level': support_level, 'support_n': support_n,
        'player_context_support_n': own_exact_n, 'player_total_support_n': own_overall_n,
        'team_context_support_n': team_exact_n, 'team_total_support_n': team_overall_n,
        'league_context_support_n': league_exact_n,
        'team_probability': team_rate, 'reference_probability': reference_rate,
        'player_probability': own_rate,
        'style_log_odds_ratio': log_odds_ratio, 'style_odds_ratio': math.exp(log_odds_ratio),
        'adjusted': False,
    }


def adjust_qb_run_role(table, team, qb, down, togo, yardline, role_probabilities, seed_text):
    """Adjust only the QB share of the run-role distribution using this QB's prior style."""
    style = qb_run_role_style(table, team, qb, cell_of(down, togo, yardline))
    if style is None:
        return None, None
    observed_base_probability = max(0.0, min(1.0, role_probabilities.get('QB', 0.0)))
    base_probability = observed_base_probability
    base_probability_fallback = None
    if base_probability in (0.0, 1.0):
        team_reference = style.get('reference_probability')
        if team_reference is None or team_reference in (0.0, 1.0):
            style.update({'base_qb_probability': observed_base_probability,
                          'adjustment_base_probability': observed_base_probability,
                          'adjusted_qb_probability': observed_base_probability, 'adjusted': False})
            return None, style
        base_probability = team_reference
        base_probability_fallback = 'historical_team_run_rate'
    ratio = style.get('style_odds_ratio', 1.0)
    if ratio <= 0 or abs(math.log(ratio)) < 1e-12 or sum(
            max(0.0, probability) for role, probability in role_probabilities.items() if role != 'QB') == 0:
        style.update({'base_qb_probability': observed_base_probability,
                      'adjustment_base_probability': base_probability,
                      'base_probability_fallback': base_probability_fallback,
                      'adjusted_qb_probability': base_probability, 'adjusted': False})
        return None, style
    logit = math.log(base_probability) - math.log1p(-base_probability) + math.log(ratio)
    adjusted = (1.0 / (1.0 + math.exp(-logit)) if logit >= 0
                else math.exp(logit) / (1.0 + math.exp(logit)))
    non_qb = {role: max(0.0, probability) for role, probability in role_probabilities.items() if role != 'QB'}
    non_qb_total = sum(non_qb.values())
    adjusted_probabilities = {'QB': adjusted}
    if non_qb_total:
        adjusted_probabilities.update({role: probability * (1.0 - adjusted) / non_qb_total
                                       for role, probability in non_qb.items()})
    roles = sorted(adjusted_probabilities)
    rng = _rng(seed_text)
    chosen = rng.choices(roles, weights=[adjusted_probabilities[role] for role in roles], k=1)[0]
    style.update({'base_qb_probability': observed_base_probability,
                  'adjustment_base_probability': base_probability,
                  'base_probability_fallback': base_probability_fallback,
                  'adjusted_qb_probability': adjusted,
                  'adjusted': abs(adjusted - base_probability) > 1e-9})
    return chosen, style


def scramble_support_level(table, cell):
    """Return the first supported historical scramble context, without changing scramble intent."""
    support = table.get('scramble_support')
    if support is None:
        n = sum(table.get('league_cell', {}).get(cell, {}).values())
        return ('exact_cell', n) if cell in (table.get('scramble_cells') or set()) and n >= SCRAMBLE_SUPPORT_MIN['exact_cell'] \
            else (None, 0)
    down, distance, field = cell
    candidates = (
        ('exact_cell', support['exact_cell']['scrambles'].get(cell, 0)),
        ('down_field', support['down_field']['scrambles'].get((down, field), 0)),
        ('down_distance', support['down_distance']['scrambles'].get((down, distance), 0)),
        ('field_zone', support['field_zone']['scrambles'].get(field, 0)),
        ('league_intent', support.get('league_intent', {}).get('scrambles', 0)),
    )
    for level, n in candidates:
        if n >= SCRAMBLE_SUPPORT_MIN[level]:
            return level, n
    return None, 0


def scramble_backoff_rate(table, level, cell):
    support = table.get('scramble_support') or {}
    down, distance, field = cell
    key = {'exact_cell': cell, 'down_field': (down, field), 'down_distance': (down, distance),
           'field_zone': field}.get(level)
    counts = support.get(level, {})
    if level == 'league_intent':
        scrambles = counts.get('scrambles', 0)
        dropbacks = counts.get('dropbacks', 0)
    else:
        scrambles = counts.get('scrambles', {}).get(key, 0)
        dropbacks = counts.get('dropbacks', {}).get(key, 0)
    return scrambles / dropbacks if dropbacks else 0.0


def draw(table, team, qb, down, togo, yardline, available_roles, seed_text, allow_scramble_backoff=False):
    """Draw a QB action and, if passing, a target role before the outcome is selected."""
    cell = cell_of(down, togo, yardline)
    p_scramble, scramble_n = _scramble_probability(table, team, qb, cell)
    if allow_scramble_backoff:
        support_level, support_n = scramble_support_level(table, cell)
        scramble_supported = support_level is not None
        if scramble_supported and p_scramble <= 0:
            p_scramble = scramble_backoff_rate(table, support_level, cell)
    else:
        support_level, support_n = None, 0
        scramble_supported = table.get('scramble_cells') is None or cell in table['scramble_cells']
    if not scramble_supported:
        p_scramble = 0.0
    rng = _rng(seed_text)
    is_scramble = rng.random() < p_scramble
    out = {'action': 'scramble' if is_scramble else 'pass',
           'scramble_probability': p_scramble, 'scramble_history_n': scramble_n}
    if not scramble_supported:
        out['scramble_fallback'] = 'no_eligible_scramble_rows_in_cell'
    elif allow_scramble_backoff:
        out['scramble_fallback'] = None if support_level == 'exact_cell' else support_level
        out['scramble_support_level'] = support_level
        out['scramble_fallback_support_n'] = support_n
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
        'source': ('nfl_pbp qb_dropback, qb_scramble, pass_attempt, rush_attempt, penalty, '
                   'two_point_attempt and play_type; canonical QB, rusher and receiver positions joined by GSIS id'),
        'source_sha256': table['sha256'], 'shrinkage_strength': SHRINKAGE,
        'source_counts': dict(table['source_counts']),
        'scramble_definition': 'qb_scramble among nflverse qb_dropback rows; scrambler identity uses rusher_player_id joined by GSIS id when its canonical position is QB',
        'qb_run_role_definition': ('primary-QB rush_attempt rows with play_type=run, excluding explicit scrambles, '
                                   'dropbacks, penalties and two-point attempts; qb_kneel rows are excluded by play_type. '
                                   'The residual can include QB sneaks because the source does not identify them separately.'),
        'qb_run_role_exposure': ('team run plays in games where the QB had the most recorded dropbacks; '
                                  'ties between primary passers are excluded'),
        'qb_run_role_style': 'player-versus-team log-odds adjustment to the team QB run-role prior, with 20-opportunity shrinkage',
        'qb_run_role_style_shrinkage': SHRINKAGE,
        'qb_run_role_minimum_player_support': QB_RUN_STYLE_MIN_SUPPORT,
        'qb_sneak_classification': {
            'status': 'unavailable',
            'reason': 'the nfl_pbp table used by this fit has no qb_sneak field or play description, so sneaks cannot be separated in this model input',
            'included_in_qb_run_role_residual': True,
        },
        'transfer_rule': 'QB decision histories remain keyed by team and passer; a new team uses its team and league priors',
    }
