"""Per-game target and carry share distributions (Dirichlet-multinomial), fitted by maximum likelihood (research, not adopted).

For a team and a game with N opportunities (targets or carries), the players' counts are Dirichlet-multinomial with concentration
alpha_i = phi * b_i, where b_i is the player's share of that team's season opportunities. Fitting phi by maximum likelihood on the
game-level counts, with each game's own total N, accounts for the finite number of opportunities per game: the variance it implies is
the sampling variance of N draws plus the game-to-game variation in shares, and nothing is taken from one to the other by a moment
rule. A beta-binomial benchmark (each player's count alone, with the same phi) is fitted alongside, for comparison.

Counts are keyed by (team, player). A player who played for two teams has a separate base share and separate game counts for each, and
no usage is pooled across teams. Only the season before the cutoff is used.

Within a game the draw is made once per team and role. The receiver or rusher for each play is then drawn from that game's shares,
restricted to the eligible players (a player listed Out or Doubtful on the frozen injury report is not eligible; Questionable stays).
"""
import hashlib
import math
import random
import sqlite3
from collections import defaultdict

import player_shares as ps

FLOOR = ps.FLOOR
MIN_TEAM_GAMES = 2  # a team needs at least this many games with a sample of this role
PHI_GRID = [round(math.exp(math.log(1.0) + i * (math.log(1000.0) - math.log(1.0)) / 400), 6) for i in range(401)]
INELIGIBLE_STATUS = ('Out', 'Doubtful')
ROLE_SQL = {'receive': ('receiver_player_id', 'pass'), 'carry': ('rusher_player_id', 'run')}
MODEL_VERSION = 'dirichlet-multinomial-mle-v2'
ELIGIBILITY_RULE = ('a rostered player listed Out or Doubtful on the frozen injury report is not eligible; '
                    'Questionable and players with no report stay eligible; shares re-normalise over the eligible players')


def _rng(text):
    return random.Random(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], 'big'))


def team_game_counts(db, season, role):
    """{team: {game_id: {player: count}}} and {team: {player: season count}}, from the play-by-play of one season."""
    column, play_type = ROLE_SQL[role]
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(
            f"SELECT game_id, posteam, {column} FROM nfl_pbp WHERE season = ? AND week <= 18 AND play_type = ? "
            f"AND posteam IS NOT NULL AND {column} IS NOT NULL", (int(season), play_type)).fetchall()
    finally:
        con.close()
    games = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))  # team -> game -> player -> count
    season_counts = defaultdict(lambda: defaultdict(int))  # team -> player -> count
    for game, team, player in rows:
        games[team][game][player] += 1
        season_counts[team][player] += 1
    return games, season_counts


def base_shares(season_counts):
    """{(team, player): share of the team's season opportunities}. Within each team; never pooled across teams."""
    base = {}
    for team, players in season_counts.items():
        total = sum(players.values())
        for player, n in players.items():
            base[(team, player)] = n / total
    return base


def _dm_loglik(counts, total, alphas):
    """Log-likelihood of one team-game's counts under a Dirichlet-multinomial with concentrations alphas (zeros included).

    The multinomial coefficient total! / prod(n!) is part of the pmf and is included, so this is comparable with the multinomial."""
    a0 = sum(alphas.values())
    value = math.lgamma(total + 1) + math.lgamma(a0) - math.lgamma(a0 + total)
    for player, a in alphas.items():
        n = counts.get(player, 0)
        value += math.lgamma(n + a) - math.lgamma(a) - math.lgamma(n + 1)
    return value


def _bb_loglik(counts, total, base_share, phi):
    """Log-likelihood of each player's count alone under a beta-binomial with mean base_share and concentration phi (the benchmark)."""
    value = 0.0
    for player, b in base_share.items():
        a, c = phi * b, phi * (1.0 - b)
        n = counts.get(player, 0)
        value += (math.lgamma(total + 1) - math.lgamma(n + 1) - math.lgamma(total - n + 1)
                  + math.lgamma(n + a) + math.lgamma(total - n + c) + math.lgamma(a + c)
                  - math.lgamma(a) - math.lgamma(c) - math.lgamma(total + a + c))
    return value


def fit(db, season, role):
    """The concentration phi for one role, fitted by maximum likelihood on the season's team-game counts, with diagnostics."""
    games, season_counts = team_game_counts(db, season, role)
    return fit_from_counts(games, season_counts, season)


def fit_from_counts(games, season_counts, season):
    """The fit on counts already gathered: games is {team: {game: {player: count}}}, season_counts is {team: {player: count}}."""
    base = base_shares(season_counts)
    team_list = []  # (team, game, total, counts, roster-with-base) for every team-game with a sample
    for team, by_game in games.items():
        roster = {p: base[(team, p)] for p in season_counts[team]}
        for game, counts in by_game.items():
            total = sum(counts.values())
            if total > 0:
                team_list.append((team, game, total, dict(counts), roster))
    if len({t for t, *_ in team_list}) < 1:
        raise ValueError(f'no {role} team-games in {season}: nothing to fit a concentration from')
    best = None
    curve = []
    for phi in PHI_GRID:
        ll = 0.0
        for team, game, total, counts, roster in team_list:
            ll += _dm_loglik(counts, total, {p: phi * b for p, b in roster.items()})
        curve.append((phi, ll))
        if best is None or ll > best[1]:
            best = (phi, ll)
    phi_hat, ll_hat = best
    inside = [phi for phi, ll in curve if ll >= ll_hat - 1.92]  # profile-likelihood 95% interval on the grid
    bb_best = max(((phi, sum(_bb_loglik(c, t, r, phi) for _tm, _g, t, c, r in team_list)) for phi in PHI_GRID), key=lambda x: x[1])
    return {'phi': phi_hat, 'phi_interval': [min(inside), max(inside)], 'loglik': round(ll_hat, 3),
            'beta_binomial_phi': bb_best[0], 'beta_binomial_loglik': round(bb_best[1], 3),
            'team_games': len(team_list), 'teams': len({t for t, *_ in team_list}), 'base': base, 'season': int(season)}


def load(db, cutoff):
    """The table the chooser reads, from the season before the cutoff: {'phi': {role: phi}, 'base': {role: {(team, gsis): share}}}."""
    season = int(cutoff) - 1
    fitted = {role: fit(db, season, role) for role in ROLE_SQL}
    return {'phi': {role: fitted[role]['phi'] for role in fitted},
            'base': {role: fitted[role]['base'] for role in fitted},
            'fit': {role: {k: v for k, v in fitted[role].items() if k != 'base'} for role in fitted},
            'season': season, 'model': MODEL_VERSION}


def eligible_players(players, injury_report):
    """The players who can take an opportunity: rostered, and not listed Out or Doubtful on the frozen report."""
    status = {p['gsis_id']: p.get('report_status') for p in (injury_report or {}).get('players', [])}
    return [p for p in players if status.get(p['gsis_id']) not in INELIGIBLE_STATUS]


def game_shares(table, team, game_id, eligible, role, seed_text):
    """One Dirichlet draw over the eligible players for this team and game: alpha = phi times each player's base share, floored.

    The result is re-normalised over the eligible players only, so a player who is out does not take a share from the others."""
    phi = table['phi'][role]
    base = table['base'][role]
    alphas = {gsis: phi * max(base.get((team, gsis), 0.0), FLOOR) for gsis in eligible}
    rng = _rng(f'{seed_text}:{game_id}:{team}:{role}')
    draws = {gsis: rng.gammavariate(alpha, 1.0) for gsis, alpha in alphas.items()}
    total = sum(draws.values())
    if total <= 0:  # every gamma draw underflowed: never divide by zero
        return {gsis: 1.0 / len(eligible) for gsis in eligible}
    return {gsis: value / total for gsis, value in draws.items()}


def manifest(table, cutoff, git_commit):
    """What a share table is: the model version, the season it was fitted on, the cutoff it serves, the concentrations, and the rule."""
    if int(table['season']) != int(cutoff) - 1:
        raise ValueError(f"the table was fitted on {table['season']}; a {cutoff} forecast needs the season before it")
    return {'model_version': table['model'], 'source_season': int(table['season']), 'cutoff_season': int(cutoff),
            'git_commit': git_commit, 'eligibility_rule': ELIGIBILITY_RULE,
            'concentration': {role: dict(fit) for role, fit in table['fit'].items()}}
