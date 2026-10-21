"""nfl_metrics.py -- scoring functions for the NFL backtest (SPEC A, 6.1 and the A3 questions).

Pure functions, no database. Conventions, fixed here so every report uses the same ones:
- Probabilities are P(home wins). Outcomes are 1 (home won) or 0 (away won). Ties are excluded
  by the caller and counted separately; these functions never see a tie.
- `spread_line` is the home team's expected margin: positive means the home team is favored.
  The home team covers when actual_margin > spread_line; equal is a push.
- Moneylines are American odds. The market probability is de-vigged by proportional
  normalization of the two implied probabilities. This is a stated choice, not the only one.
"""
from __future__ import annotations

import math
import random

EPS = 1e-12
CALIBRATION_MIN_N = 20


def brier(probs, outcomes):
    n = len(probs)
    if n == 0 or n != len(outcomes):
        raise ValueError("probs and outcomes must be the same non-zero length")
    return sum((p - y) ** 2 for p, y in zip(probs, outcomes)) / n


def log_loss(probs, outcomes):
    n = len(probs)
    if n == 0 or n != len(outcomes):
        raise ValueError("probs and outcomes must be the same non-zero length")
    total = 0.0
    for p, y in zip(probs, outcomes):
        p = min(max(p, EPS), 1.0 - EPS)
        total += -(y * math.log(p) + (1 - y) * math.log(1.0 - p))
    return total / n


def mae(pred, actual):
    n = len(pred)
    if n == 0 or n != len(actual):
        raise ValueError("pred and actual must be the same non-zero length")
    return sum(abs(p - a) for p, a in zip(pred, actual)) / n


def american_to_prob(odds):
    """Implied probability of one American moneyline, before removing the vig."""
    if odds is None:
        raise ValueError("odds is None")
    if odds == 0:
        raise ValueError("American odds cannot be 0")
    if odds < 0:
        return -odds / (-odds + 100.0)
    return 100.0 / (odds + 100.0)


def devig_home_prob(home_ml, away_ml):
    """Fair P(home wins) from a two-sided moneyline, proportional de-vig."""
    ph = american_to_prob(home_ml)
    pa = american_to_prob(away_ml)
    return ph / (ph + pa)


def calibration_bins(probs, outcomes, width=0.1):
    """Rows of (lo, hi, n, wins, win_rate, flagged). flagged = n < CALIBRATION_MIN_N.

    A probability of exactly 1.0 falls in the last bin. Empty bins are returned with n = 0.
    """
    if width <= 0 or width > 1:
        raise ValueError("width must be in (0, 1]")
    k = int(round(1.0 / width))
    bins = [[0, 0] for _ in range(k)]
    for p, y in zip(probs, outcomes):
        idx = min(int(p / width), k - 1)
        bins[idx][0] += 1
        bins[idx][1] += y
    rows = []
    for i, (n, wins) in enumerate(bins):
        lo, hi = i * width, (i + 1) * width
        rate = wins / n if n else None
        rows.append((round(lo, 10), round(hi, 10), n, wins, rate, n < CALIBRATION_MIN_N))
    return rows


def ats_result(actual_margin, spread_line):
    """'cover', 'miss' or 'push' for the home side against its spread."""
    diff = actual_margin - spread_line
    if abs(diff) < 1e-9:
        return "push"
    return "cover" if diff > 0 else "miss"


def pick_side(proj_margin, spread_line):
    """The model's against-the-spread side, shared by every spread-pick consumer.

    'home' when the projected home margin beats the line, 'away' when it does not, 'no_pick'
    when it sits exactly on the line (within the grading tolerance), 'no_line' when there is no
    usable spread. The lock payload and the grader both call this, so the pick shown before
    kickoff is the same pick graded after it.
    """
    if spread_line is None:
        return "no_line"
    if abs(proj_margin - spread_line) < 1e-9:
        return "no_pick"
    return "home" if proj_margin > spread_line else "away"


def grade_winner(p_home_win, actual_home, actual_away):
    """Straight-up grade of the win-probability favourite on a final score (a model metric, not
    the Model Pick). NFL ties remain 'tie'; None means the game is not final."""
    if actual_home is None or actual_away is None:
        return None
    if actual_home == actual_away:
        return "tie"
    if p_home_win is None or abs(p_home_win - 0.5) < 1e-9:
        return "no_pick"
    return "win" if (p_home_win > 0.5) == (actual_home > actual_away) else "loss"


# ---------------------------------------------------------------- NFL Model Pick
# docs/MODEL-PICK-RULES.md, "NFL order". One pick per game per model version, from the frozen lock
# inputs only. Every comparison uses TOL, as the rest of this module does.

TOL = 1e-9
STRONG, MID, WEAK = "strong", "mid", "weak"


def strength_tiers(per_game_margin):
    """Strong, mid or weak for each team, from points for minus points against per game.

    `per_game_margin` maps team -> (points for - points against) / games, for every team with at
    least one game. A team that is absent has no tier. Teams are ranked best first (ties by team
    code, values compared at the grading tolerance). With n ranked teams, the team at index i
    (0 = best) is strong when 3i < n and weak when 3i >= 2n, and mid otherwise. 32 teams give
    11 strong, 11 mid and 10 weak, because 32 does not split into thirds exactly.
    """
    n = len(per_game_margin)
    order = sorted(per_game_margin, key=lambda t: (-round(per_game_margin[t], 9), t))
    out = {}
    for i, team in enumerate(order):
        if 3 * i < n:
            out[team] = STRONG
        elif 3 * i >= 2 * n:
            out[team] = WEAK
        else:
            out[team] = MID
    return out


def _pick(market, side, line, rule, status="pick"):
    return {"market": market, "side": side, "line": line, "rule": rule, "status": status}


def _other(side):
    return "away" if side == "home" else "home"


def _strength_pick(fav, home_tier, away_tier, total_line, proj_total):
    """Rule 5: team strength decides what rules 1 to 4 left. `fav` is None for a pick'em."""
    if home_tier is not None and away_tier is not None:
        if {home_tier, away_tier} == {STRONG, WEAK}:
            return _pick("ml", "home" if home_tier == STRONG else "away", None, 5)
        if home_tier == away_tier == STRONG:
            return _pick("total", "over", _total_line("over", total_line, proj_total), 5)
        if home_tier == away_tier == WEAK:
            return _pick("total", "under", _total_line("under", total_line, proj_total), 5)
    if fav is None:
        return _pick(None, None, None, 5, status="no_pick")
    return _pick("ml", fav, None, 5)


def _total_line(side, total_line, proj_total):
    """The more conservative of the posted total and the projection: Over takes the lower."""
    proj = float(proj_total)
    if total_line is None:
        return proj
    posted = float(total_line)
    return min(posted, proj) if side == "over" else max(posted, proj)


def model_pick(spread, proj_margin, total_line, proj_total, home_tier=None, away_tier=None):
    """The Model Pick for one game from its frozen lock inputs.

    spread: the frozen Vegas spread in home convention (positive = home favoured), or None.
    proj_margin, proj_total: the model's projected home margin and total, as locked.
    total_line: the frozen posted total, or None (the projected total then stands in for it).
    home_tier, away_tier: 'strong', 'mid', 'weak', or None for a team with no games yet.

    Returns {market, side, line, rule, status}. market is 'spread', 'ml' or 'total'; side is
    'home', 'away', 'over' or 'under'; line is the picked side's number (home -7, away +2.5,
    Over 44). status is 'pick', 'no_line' (no spread, so no rule can run) or 'no_pick' (a pick'em
    with no favourite left over by rule 5). The first rule that applies decides.
    """
    if proj_margin is None or proj_total is None:
        raise ValueError("a locked projection needs both a margin and a total")
    if spread is None:
        return _pick(None, None, None, None, status="no_line")
    s, pm = float(spread), float(proj_margin)
    if abs(s) < TOL:
        fav, v = None, 0.0               # pick'em: rules 1 to 4 need a favourite, so go to rule 5
    elif s > 0:
        fav, v = "home", s
    else:
        fav, v = "away", -s
    if fav is not None:
        m = pm if fav == "home" else -pm  # the model's margin for the favourite
        if m >= 7 - TOL and m >= v - TOL:
            return _pick("spread", fav, -v, 1)           # favourite to cover at -V
        if v >= 7 - TOL or m >= 7 - TOL:
            return _pick("ml", fav, None, 2)             # favourite moneyline
        if v - m >= 3 - TOL:
            return _pick("spread", _other(fav), v, 3)    # underdog to cover at +V
        if m > TOL:
            return _pick("ml", fav, None, 4)             # favourite moneyline
    return _strength_pick(fav, home_tier, away_tier, total_line, proj_total)


def pick_label(pick, home, away):
    """The text a Model Pick reads as, built here so no page computes a side."""
    if pick["status"] == "no_line":
        return "No line"
    if pick["status"] == "no_pick":
        return "No pick"
    team = home if pick["side"] == "home" else away
    if pick["market"] == "spread":
        return "%s %s" % (team, _num(pick["line"], signed=True))
    if pick["market"] == "ml":
        return "%s ML" % team
    return "%s %s" % ("Over" if pick["side"] == "over" else "Under", _num(pick["line"]))


def _num(x, signed=False):
    text = ("%+.1f" if signed else "%.1f") % float(x)
    return text[:-2] if text.endswith(".0") else text


def grade_pick(pick, actual_home, actual_away):
    """'win', 'loss' or 'push' for a Model Pick on a final score; 'no_pick' and 'no_line' pass
    through as they were locked. None means the game is not final, so there is no grade yet.

    Spread: the home side covers when the actual home margin is above the frozen spread S, the
    away side when it is below, and equal is a push. The pick's line is -S for home and +S for
    away, so S is recovered from it. Moneyline: a tie is a push. Total: equal is a push.
    """
    if pick["status"] == "no_line":
        return "no_line"
    if pick["status"] == "no_pick":
        return "no_pick"
    if actual_home is None or actual_away is None:
        return None
    hs, as_ = float(actual_home), float(actual_away)
    margin = hs - as_
    side = pick["side"]
    if pick["market"] == "ml":
        if abs(margin) < TOL:
            return "push"
        return "win" if (side == "home") == (margin > 0) else "loss"
    if pick["market"] == "spread":
        line = float(pick["line"])
        spread = -line if side == "home" else line
        diff = margin - spread
        if abs(diff) < TOL:
            return "push"
        covered = diff > 0 if side == "home" else diff < 0
        return "win" if covered else "loss"
    if pick["market"] == "total":
        line = float(pick["line"])
        total = hs + as_
        if abs(total - line) < TOL:
            return "push"
        return "win" if (side == "over") == (total > line) else "loss"
    raise ValueError("unknown Model Pick market %r" % (pick["market"],))


def ats_record(actual_margins, spread_lines):
    """Counts and cover rate, pushes excluded from the rate and reported separately."""
    if len(actual_margins) != len(spread_lines):
        raise ValueError("length mismatch")
    counts = {"cover": 0, "miss": 0, "push": 0}
    for m, s in zip(actual_margins, spread_lines):
        counts[ats_result(m, s)] += 1
    decided = counts["cover"] + counts["miss"]
    counts["cover_rate"] = counts["cover"] / decided if decided else None
    return counts


def bootstrap_mean_diff_ci(loss_a, loss_b, reps=10000, seed=20261009, alpha=0.05):
    """Paired bootstrap 95% interval for mean(loss_a - loss_b), resampling games.

    Returns (point_estimate, lo, hi). An interval that excludes zero is the evidence; the
    point estimate alone is not.
    """
    n = len(loss_a)
    if n == 0 or n != len(loss_b):
        raise ValueError("loss lists must be the same non-zero length")
    diffs = [a - b for a, b in zip(loss_a, loss_b)]
    point = sum(diffs) / n
    rng = random.Random(seed)
    means = []
    for _ in range(reps):
        s = 0.0
        for _ in range(n):
            s += diffs[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * reps)]
    hi = means[min(reps - 1, int((1 - alpha / 2) * reps))]
    return point, lo, hi
