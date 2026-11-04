"""P3: defensive matchup component (SLC v2 Milestone 3): yards per opportunity allowed, with opponent adjustment.

Outcomes: yards per target allowed to WR, TE and RB (receiving), yards per carry allowed to RB (rushing), and yards per pass
attempt allowed to QB (passing). Each outcome is modelled as efficiency (yards per opportunity) with volume reported separately.
Touchdown rates are not modelled here; they are sparse and need a separate, strongly shrunk model.

Estimate for defense D in game t: the shrunk mean residual over D's usable earlier games this season, added to the league
prior-season rate, plus the target offense's prior-season strength adjustment. Residuals subtract each earlier game's own
offense adjustment. Opponent strength comes from the prior season only, so no in-season information about the opponent
enters the adjustment.

Shrinkage: K_YARDS = 8 pseudo-games for efficiency. Touchdown rates (not evaluated here) would use K_TD = 40.
"""
import datetime as dt
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'slc-v2-p2-usage-2026-11-02'))
import p2_usage as p2  # noqa: E402

K_YARDS = 8
K_TD = 40


def usable(game, cutoff):
    return p2.usable(game, cutoff)


def _adjustment(offense, opponent_adjust, league_strength):
    if opponent_adjust is None:
        return 0.0
    return opponent_adjust.get(offense, league_strength) - league_strength


def defense_feature(history, target, league, opponent_adjust, k=K_YARDS, league_strength=None):
    cutoff = target['kickoff'] - dt.timedelta(hours=1)
    rows = [g for g in history if g['defense'] == target['defense'] and g['season'] == target['season']
            and usable(g, cutoff)]
    empty = [g for g in rows if not g['opportunities']]
    observed = [g for g in rows if g['opportunities']]
    residuals = []
    for g in observed:
        adjust = _adjustment(g['offense'], opponent_adjust, league_strength)
        residuals.append(g['yards'] - league - adjust)
    effect = sum(residuals) / (len(residuals) + k) if residuals else 0.0
    if observed:
        volume = sum(g['opportunities'] for g in observed) / len(observed)
    else:
        volume = 0.0
    prediction = league + _adjustment(target['offense'], opponent_adjust, league_strength) + effect
    return {
        'defense': target['defense'], 'season': target['season'], 'game_id': target['game_id'],
        'games_used': len(observed), 'game_ids_used': [g['game_id'] for g in observed],
        'empty_defense_games': len(empty), 'volume_mean': volume, 'effect': effect,
        'prediction': prediction, 'cutoff': cutoff,
    }
