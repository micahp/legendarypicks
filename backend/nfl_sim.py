"""nfl_sim.py -- season simulation for playoff odds (SPEC A, 5.1 and 5.4).

Each run plays out every unplayed regular-season game. Played games keep their real results.

Margin model: each unplayed game draws its margin from Normal(expected, sigma), where expected
comes from the frozen ratings fit on every played game and sigma is the frozen 13.295. Win
probability is therefore Phi(expected / sigma), which matches the single-game model in nfl_ratings.

Hot updates (spec 5.1): after each simulated game the two teams' running adjustments move by
k * (actual margin - expected margin): the home team +k*r, the away team -k*r. k = 0 is a cold
simulation (no updates). Adjustments apply to all later games in the same run only. With
"history" scores the actual margin is the integer margin of the drawn score, and the adjusted
expected margin sets both the outcome probability and the neighbour search.

Scores, two options (`scores=`):
- "placeholder": each simulated game splits its Normal margin around a fixed total of 40 (home
  20 + m/2, away 20 - m/2). Non-integer, never a tie; its points are not a model and must not be
  reported as one.
- "history": nfl_sim_scores (pre-registered there, gates G1-G6). The outcome (home win, away win,
  tie) is drawn from the same Phi(expected / sigma) with the historical tie rate taken out
  proportionally, and the score is an actual NFL final with that outcome, from the nearest
  historical games in (expected margin, expected total). Integer scores, real ties.
DEFAULT_SCORES says which one runs when the caller does not choose.

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
import nfl_sim_scores as nss
import nfl_standings as st

FROZEN_SIGMA = 13.295
FROZEN = {"half_life": 6.0, "cap": 14.0, "cap_points": None, "prior_games": 4.0,
          "shrink": nrd.DEFAULT_SHRINK, "sigma": FROZEN_SIGMA}
SCORES = ("placeholder", "history")
DEFAULT_SCORES = "placeholder"
HISTORY_K = 25      # chosen by nfl_sim_scores.select_k on 2011-2019 (pre-registered rule)


def inputs(con, season, overrides=None, as_of_week=None, scores=None, pool=None):
    """Everything a run needs. Played = every scored REG game of the season; remaining = every
    unscored REG game. A scored game is never dropped, whatever its week (an earlier version
    dropped scored games after a cut-off week, and that bug is covered by a test).

    The fit uses all played games, anchored at the latest played week.

    scores: "placeholder" or "history" (None = DEFAULT_SCORES). pool: optional precomputed
    nfl_sim_scores.pool_rows covering the seasons before `season` (saves rebuilding it)."""
    scores = DEFAULT_SCORES if scores is None else scores
    if scores not in SCORES:
        raise ValueError("scores must be one of %s, got %r" % (SCORES, scores))
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
    totals = []
    for wk, h, a, loc in unplayed:
        neutral = (loc or "").strip().lower() == "neutral"
        ph, pa = nr.expected_points(f, h, a, neutral)
        remaining.append((wk, h, a, neutral, ph - pa))
        totals.append(ph + pa)
    played_games = [(r[0], r[1], r[2], float(r[3]), float(r[4])) for r in scored]
    tmap = bc.team_map(con)
    out = {"season": season, "through_week": through_week, "fit": f, "played": played_games,
           "remaining": remaining, "remaining_totals": totals, "tmap": tmap, "sigma": p["sigma"],
           "scores": scores}
    if scores == "history":
        out["sampler"] = nss.build(con, season, HISTORY_K, rows=pool)
    return out


def attach_history(inp, sampler):
    """Switch an inputs dict to history scores with a given sampler (tests, synthetic leagues).
    remaining_totals must be present, one per remaining game."""
    if len(inp.get("remaining_totals") or []) != len(inp["remaining"]):
        raise ValueError("remaining_totals must have one expected total per remaining game")
    out = dict(inp)
    out["scores"] = "history"
    out["sampler"] = sampler
    out.pop("_tables", None)
    return out


def _tables(inp):
    """Cold-run neighbour tables, one per remaining game, computed once per inputs dict."""
    t = inp.get("_tables")
    if t is None:
        s = inp["sampler"]
        t = [s.game_table(g[4], tot) for g, tot in zip(inp["remaining"], inp["remaining_totals"])]
        inp["_tables"] = t
    return t


def simulate_games(inp, rng, k=0.0):
    """Played games plus one simulated result for every remaining game: rows
    (week, home, away, home_score, away_score)."""
    deltas = {}
    sigma = inp["sigma"]
    games = list(inp["played"])
    scores = inp.get("scores", "placeholder")
    if scores == "placeholder":
        for wk, h, a, neutral, em in inp["remaining"]:
            e = em + deltas.get(h, 0.0) - deltas.get(a, 0.0)
            m = rng.gauss(e, sigma)
            if k:
                deltas = hot_update(deltas, h, a, m - e, k)
            games.append((wk, h, a, 20.0 + m / 2.0, 20.0 - m / 2.0))
        return games
    if scores != "history":
        raise ValueError("unknown scores option %r" % scores)
    s = inp["sampler"]
    if s.sigma != sigma:
        raise ValueError("sampler sigma %r differs from the run's %r" % (s.sigma, sigma))
    if not k:
        for (wk, h, a, neutral, em), (p, table) in zip(inp["remaining"], _tables(inp)):
            hs, as_ = s.draw(rng, p, table)
            games.append((wk, h, a, hs, as_))
        return games
    for (wk, h, a, neutral, em), tot in zip(inp["remaining"], inp["remaining_totals"]):
        e = em + deltas.get(h, 0.0) - deltas.get(a, 0.0)
        p = s.p_home(e)
        outcome = s.outcome(p, rng.random())
        pairs = s.pairs(e, tot, outcome)
        hs, as_ = pairs[rng.randrange(len(pairs))]
        deltas = hot_update(deltas, h, a, (hs - as_) - e, k)
        games.append((wk, h, a, hs, as_))
    return games


def hot_update(deltas, home, away, residual, k):
    """Spec 5.1: home +k*r, away -k*r, where r = actual margin - expected margin. Returns a new
    dict; the input is not modified."""
    out = dict(deltas)
    out[home] = out.get(home, 0.0) + k * residual
    out[away] = out.get(away, 0.0) - k * residual
    return out


def one_run(inp, rng, k=0.0, observe=None):
    """One simulated season. Returns (seeds_by_conf, wins_by_team, coin_flips).
    observe(games, teams, seeds), if given, sees every simulated season (backtests, gates)."""
    games = simulate_games(inp, rng, k)
    teams = st.build(inp["tmap"], games)
    sd.COIN_FLAGS.clear()
    n_seeds = sd.n_seeds_for(inp["season"])
    seeds = {conf: sd.seeds_for_conference(teams, conf, n_seeds=n_seeds, rng=rng)
             for conf in ("AFC", "NFC")}
    flips = len(sd.COIN_FLAGS)
    wins = {code: t.wins for code, t in teams.items()}
    if observe is not None:
        observe(games, teams, seeds)
    return seeds, wins, flips


def run(inp, n, k=0.0, seed=1, observe=None):
    """n simulated seasons. Returns the aggregate dict described in aggregate()."""
    rng = random.Random(seed)
    counts = {}
    wins_all = {}
    flips = 0
    for _ in range(n):
        seeds, wins, f = one_run(inp, rng, k, observe)
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


def sanity(out, conf_of, n_seeds=7):
    """Assertions from spec 6.3. Raises AssertionError naming the failing quantity.

    sum of p_playoffs over all teams = 2 * n_seeds (n_seeds per conference); for each conference
    and each seed k, p_seed_k sums to 1 over that conference's teams. n_seeds: 7 since 2020, 6
    before (nfl_seeding.n_seeds_for).
    """
    total = sum(t["p_playoffs"] for t in out["teams"].values())
    assert abs(total - 2.0 * n_seeds) <= 0.01, \
        "sum of p_playoffs is %.4f, expected %d" % (total, 2 * n_seeds)
    for conf in ("AFC", "NFC"):
        members = [c for c in out["teams"] if conf_of[c] == conf]
        for k in range(1, n_seeds + 1):
            s = sum(out["teams"][c]["p_seed_%d" % k] for c in members)
            assert abs(s - 1.0) <= 0.01, "%s p_seed_%d sums to %.4f, expected 1" % (conf, k, s)
    return True
