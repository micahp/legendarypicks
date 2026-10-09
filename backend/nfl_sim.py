"""nfl_sim.py -- season simulation for playoff odds (SPEC A, 5.1 and 5.4).

Each run plays out every unplayed regular-season game. Played games keep their real results.

Margin model: each unplayed game draws its margin from Normal(expected, sigma), where expected
comes from the frozen ratings fit on every played game and sigma is the frozen 13.295. Win
probability is therefore Phi(expected / sigma), which matches the single-game model in nfl_ratings.

Hot updates (spec 5.1): after each simulated game the two teams' running adjustments move by
k * (actual margin - expected margin): the home team +k*r, the away team -k*r. k = 0 is a cold
simulation (no updates). Adjustments apply to all later games in the same run only.

Seeding uses nfl_seeding (the same engine validated in A4). Coin flips inside a simulated season
are counted and returned: a run with flips is reported with the number, not hidden.

Randomness: one random.Random per run, seeded explicitly, so a run reproduces from its seed.
"""
from __future__ import annotations

import random

import nfl_backtest as nb
import nfl_bracket_check as bc
import nfl_ratings as nr
import nfl_ratings_data as nrd
import nfl_seeding as sd
import nfl_standings as st

FROZEN_SIGMA = 13.295
FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "prior_games": 4.0,
          "shrink": nrd.DEFAULT_SHRINK, "sigma": FROZEN_SIGMA}


def inputs(con, season, overrides=None, as_of_week=None):
    """Everything a run needs. Played = every scored REG game of the season; remaining = every
    unscored REG game. A scored game is never dropped, whatever its week (an earlier version
    dropped scored games after a cut-off week, and that bug is covered by a test).

    The fit uses all played games, anchored at the latest played week."""
    p = dict(FROZEN)
    p.update(overrides or {})
    scored_all = nrd._scored_rows(con, season)
    if not scored_all:
        raise ValueError("no scored REG games for season %d" % season)
    if as_of_week is None:
        scored = scored_all
        through_week = max(r[0] for r in scored)
        unplayed_sql = ("SELECT week, home_team, away_team, location FROM nfl_schedule "
                        "WHERE season = ? AND game_type = 'REG' AND (home_score IS NULL "
                        "OR away_score IS NULL) ORDER BY week, game_id")
        unplayed_args = (season,)
    else:
        # Backtest mode: the world as it was after week as_of_week. Games after that week are
        # remaining whatever their score, and their scores are never used.
        scored = [r for r in scored_all if r[0] <= as_of_week]
        if not scored:
            raise ValueError("no scored REG games through week %d" % as_of_week)
        through_week = as_of_week
        unplayed_sql = ("SELECT week, home_team, away_team, location FROM nfl_schedule "
                        "WHERE season = ? AND game_type = 'REG' AND week > ? "
                        "ORDER BY week, game_id")
        unplayed_args = (season, as_of_week)
    prior = nb.prior_for(con, season, p)
    teams = nrd.teams_in_season(con, season)
    train = nb.training_games([(r[0], r[1], r[2], r[3], r[4], r[5]) for r in scored],
                              through_week + 1, p["cap_points"])
    f = nr.fit(train, teams, prior=prior, half_life=p["half_life"], cap=p["cap"],
               prior_games=p["prior_games"])
    unplayed = con.execute(unplayed_sql, unplayed_args).fetchall()
    remaining = []
    for wk, h, a, loc in unplayed:
        neutral = (loc or "").strip().lower() == "neutral"
        ph, pa = nr.expected_points(f, h, a, neutral)
        remaining.append((wk, h, a, neutral, ph - pa))
    played_games = [(r[0], r[1], r[2], float(r[3]), float(r[4])) for r in scored]
    tmap = bc.team_map(con)
    return {"season": season, "through_week": through_week, "fit": f, "played": played_games,
            "remaining": remaining, "tmap": tmap, "sigma": p["sigma"]}


def hot_update(deltas, home, away, residual, k):
    """Spec 5.1: home +k*r, away -k*r, where r = actual margin - expected margin. Returns a new
    dict; the input is not modified."""
    out = dict(deltas)
    out[home] = out.get(home, 0.0) + k * residual
    out[away] = out.get(away, 0.0) - k * residual
    return out


def one_run(inp, rng, k=0.0):
    """One simulated season. Returns (seeds_by_conf, wins_by_team, coin_flips)."""
    deltas = {}
    sigma = inp["sigma"]
    games = list(inp["played"])
    for wk, h, a, neutral, em in inp["remaining"]:
        e = em + deltas.get(h, 0.0) - deltas.get(a, 0.0)
        m = rng.gauss(e, sigma)
        if k:
            deltas = hot_update(deltas, h, a, m - e, k)
        games.append((wk, h, a, 20.0 + m / 2.0, 20.0 - m / 2.0))
    teams = st.build(inp["tmap"], games)
    sd.COIN_FLAGS.clear()
    seeds = {conf: sd.seeds_for_conference(teams, conf) for conf in ("AFC", "NFC")}
    flips = len(sd.COIN_FLAGS)
    wins = {code: t.wins for code, t in teams.items()}
    return seeds, wins, flips


def run(inp, n, k=0.0, seed=1):
    """n simulated seasons. Returns the aggregate dict described in aggregate()."""
    rng = random.Random(seed)
    counts = {}
    wins_all = {}
    flips = 0
    for _ in range(n):
        seeds, wins, f = one_run(inp, rng, k)
        flips += f
        for conf, lst in seeds.items():
            for s, code in lst:
                c = counts.setdefault(code, {"playoff": 0, "division": 0, "bye": 0,
                                             **{"seed_%d" % i: 0 for i in range(1, 8)}})
                c["playoff"] += 1
                if s <= 4:
                    c["division"] += 1
                if s == 1:
                    c["bye"] += 1
                c["seed_%d" % s] += 1
        for code, w in wins.items():
            wins_all.setdefault(code, []).append(w)
    return aggregate(counts, wins_all, n, flips)


def aggregate(counts, wins_all, n, flips):
    out = {"n": n, "coin_flips": flips, "teams": {}}
    for code, w in wins_all.items():
        c = counts.get(code, {"playoff": 0, "division": 0, "bye": 0,
                              **{"seed_%d" % i: 0 for i in range(1, 8)}})
        ws = sorted(w)
        out["teams"][code] = {
            "p_playoffs": c["playoff"] / n, "p_division": c["division"] / n,
            "p_bye": c["bye"] / n,
            **{"p_seed_%d" % i: c["seed_%d" % i] / n for i in range(1, 8)},
            "wins_mean": sum(w) / n,
            "wins_p10": ws[int(0.10 * (n - 1))], "wins_p90": ws[int(0.90 * (n - 1))],
        }
    return out


def sanity(out, conf_of):
    """Assertions from spec 6.3. Raises AssertionError naming the failing quantity.

    sum of p_playoffs over all teams = 14 (7 per conference); for each conference and each seed
    k, p_seed_k sums to 1 over that conference's teams.
    """
    total = sum(t["p_playoffs"] for t in out["teams"].values())
    assert abs(total - 14.0) <= 0.01, "sum of p_playoffs is %.4f, expected 14" % total
    for conf in ("AFC", "NFC"):
        members = [c for c in out["teams"] if conf_of[c] == conf]
        for k in range(1, 8):
            s = sum(out["teams"][c]["p_seed_%d" % k] for c in members)
            assert abs(s - 1.0) <= 0.01, "%s p_seed_%d sums to %.4f, expected 1" % (conf, k, s)
    return True
