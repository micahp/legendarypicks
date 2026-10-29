"""Per-game target and carry share distributions (Dirichlet-multinomial), fitted on the prior season only (research, not adopted).

Each game's shares over the eligible receivers (or carriers) are one Dirichlet draw with concentration phi times the player's base
share (floored at player_shares.FLOOR). The draw is made once per game and seed, so every play in that game shares it; the receiver or
carrier for a play is then drawn from those shares. phi is a method-of-moments fit: for each player, phi = b(1 - b) / var - 1, where b
is the player's season share and var is his variance of share across the team's games, averaged over games and players. Only the
season before the cutoff is used.
"""
import hashlib
import random
import sqlite3
import statistics
from collections import defaultdict

import player_shares as ps

FLOOR = ps.FLOOR
MIN_GAMES = 15  # a team's games with a sample for a player's variance; a 17-game season has 17
BASE_RANGE = (0.05, 0.5)  # players outside this share range do not give a stable variance estimate
PHI_RANGE = (1.0, 500.0)
ROLE_SQL = {'receive': ("receiver_player_id", "pass"), 'carry': ("rusher_player_id", "run")}


def _rng(text):
    return random.Random(int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], 'big'))


def fit(db, season, role):
    """{'phi': concentration, 'base': {(team, gsis): season share}, 'players': how many players gave an estimate}."""
    column, play_type = ROLE_SQL[role]
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=10)
    try:
        rows = con.execute(
            f"SELECT game_id, posteam, {column} FROM nfl_pbp WHERE season = ? AND week <= 18 AND play_type = ? "
            f"AND posteam IS NOT NULL AND {column} IS NOT NULL", (int(season), play_type)).fetchall()
    finally:
        con.close()
    team_games = defaultdict(lambda: defaultdict(int))  # (game, team) -> player -> plays
    team_total, player_total, player_team = defaultdict(int), defaultdict(int), defaultdict(lambda: defaultdict(int))
    for game, team, player in rows:
        team_games[(game, team)][player] += 1
        team_total[team] += 1
        player_total[player] += 1
        player_team[player][team] += 1
    games_by_team = defaultdict(list)
    for (game, team), counts in team_games.items():
        games_by_team[team].append(counts)
    base = {}
    estimates = []
    for player, total in player_total.items():
        team = max(player_team[player], key=player_team[player].get)
        share = total / team_total[team]
        base[(team, player)] = share
        if not BASE_RANGE[0] <= share <= BASE_RANGE[1]:
            continue
        xs = [counts.get(player, 0) / sum(counts.values()) for counts in games_by_team[team]]
        if len(xs) < MIN_GAMES:
            continue
        var = statistics.pvariance(xs)
        if var <= 0:
            continue
        estimates.append((share * (1 - share) / var - 1, len(xs)))
    if not estimates:
        raise ValueError(f'no {role} share estimates in {season}: nothing to fit a concentration from')
    weight = sum(n for _phi, n in estimates)
    phi = sum(phi_p * n for phi_p, n in estimates) / weight
    return {'phi': min(max(phi, PHI_RANGE[0]), PHI_RANGE[1]), 'base': base, 'players': len(estimates), 'season': int(season)}


def load(db, cutoff):
    """The table the chooser reads, from the season before the cutoff: {'phi': {role: phi}, 'base': {role: {(team, gsis): share}}}."""
    season = int(cutoff) - 1
    fitted = {role: fit(db, season, role) for role in ROLE_SQL}
    return {'phi': {role: fitted[role]['phi'] for role in fitted},
            'base': {role: fitted[role]['base'] for role in fitted},
            'season': season, 'players': {role: fitted[role]['players'] for role in fitted}}


def game_shares(table, team, game_id, eligible, role, seed_text):
    """One Dirichlet draw over the eligible players for this game: alpha = phi times each player's base share, floored."""
    phi = table['phi'][role]
    base = table['base'][role]
    alphas = {gsis: phi * max(base.get((team, gsis), 0.0), FLOOR) for gsis in eligible}
    rng = _rng(f'{seed_text}:{game_id}:{team}:{role}')
    draws = {gsis: rng.gammavariate(alpha, 1.0) for gsis, alpha in alphas.items()}
    total = sum(draws.values())
    if total <= 0:  # every gamma draw underflowed: the floor cannot make this happen for phi >= 1, but never divide by zero
        return {gsis: 1.0 / len(eligible) for gsis in eligible}
    return {gsis: value / total for gsis, value in draws.items()}
