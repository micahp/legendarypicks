#!/usr/bin/env python3
"""Step 2 of the tennis prediction brief: game, set and match probabilities from serve-point probabilities.

Inputs: serve_a, the probability that A wins a point when A serves; serve_b, the same for B; the scoring rules;
and who serves first. Nothing here reads the point model, so a later point model can replace it without
changing this file.

match_distribution() is exact. Game and tiebreak win probabilities come from a closed form and a small dynamic
programme, and the match is a dynamic programme over games. simulate_match() plays the same rules point by point,
so it is an independent check. verify() compares the two over a grid of formats and serve probabilities.

Scoring rules (a dict; missing keys take DEFAULT_RULES):
  bestOf                  3 or 5
  tiebreakAt              games at which a tiebreak is played in a set that is not the final set; None = no tiebreaks
  tiebreakPoints          points to win one of those tiebreaks
  finalSet                "advantage": no tiebreak, play on until a two-game lead
                          "tiebreak": a tiebreak at finalSetTiebreakAt games
                          "match_tiebreak": a tiebreak to finalSetTiebreakPoints replaces the final set (0 games)
  finalSetTiebreakAt      games at which the final set is decided by a tiebreak (finalSet "tiebreak")
  finalSetTiebreakPoints  points to win the final-set tiebreak, or the match tiebreak

Conventions: the server alternates every game across the whole match. A set tiebreak counts as one game (7-6 is 13
games). A match tiebreak counts as zero games. The first server of a tiebreak is the server of the game it replaces.
The first server of a match tiebreak is the server of the game that would come next.

  python3 backend/tennis_match_sim.py --serve-a 0.65 --serve-b 0.62 --best-of 3
  python3 backend/tennis_match_sim.py --verify 50000
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import random
import sys
from collections import defaultdict
from typing import Any

DEFAULT_RULES: dict[str, Any] = {
    "bestOf": 3,
    "tiebreakAt": 6,
    "tiebreakPoints": 7,
    "finalSet": "tiebreak",
    "finalSetTiebreakAt": 6,
    "finalSetTiebreakPoints": 7,
}
GAMES_PER_SET = 6
MAX_GAMES = 400  # advantage sets can run long; the residual mass beyond this is reported as unresolved
PRUNE = 1e-15  # tiebreak states below this mass are dropped; the total error is far below any reported digit


def normalise_rules(rules: dict[str, Any] | None = None) -> dict[str, Any]:
    r = {**DEFAULT_RULES, **(rules or {})}
    if r["bestOf"] not in (3, 5):
        raise ValueError(f"bestOf must be 3 or 5, got {r['bestOf']}")
    if r["finalSet"] not in ("advantage", "tiebreak", "match_tiebreak"):
        raise ValueError(f"finalSet must be advantage, tiebreak or match_tiebreak, got {r['finalSet']}")
    if r["finalSet"] == "tiebreak" and r["finalSetTiebreakAt"] is None:
        raise ValueError("finalSet 'tiebreak' needs finalSetTiebreakAt")
    for key in ("tiebreakPoints", "finalSetTiebreakPoints"):
        if r[key] is not None and r[key] < 2:
            raise ValueError(f"{key} must be at least 2, got {r[key]}")
    return r


def game_win_prob(p: float) -> float:
    """P(server wins a game) when the server wins each point with probability p. Closed form; deuce is a geometric series."""
    q = 1.0 - p
    deuce = p * p / (p * p + q * q)
    return p**4 * (1 + 4 * q + 10 * q * q) + 20 * (p * q) ** 3 * deuce


def point_server_is_a(n: int, first_is_a: bool) -> bool:
    """Who serves point n (counted from 0) of a tiebreak. The first server serves point 0, the other serves points
    1 and 2, the first server serves 3 and 4, and so on."""
    if n == 0:
        return first_is_a
    return first_is_a if ((n + 1) // 2) % 2 == 0 else not first_is_a


@functools.lru_cache(maxsize=None)
def tiebreak_win_prob_a(serve_a: float, serve_b: float, first_is_a: bool, points: int) -> float:
    """P(A wins a tiebreak to `points`, by two). A wins a point on its own serve with serve_a, and on B's serve with 1 - serve_b."""
    win_a = 0.0
    dist: dict[tuple[int, int], float] = {(0, 0): 1.0}
    n = 0
    while dist and n < 2000:
        p_a_point = serve_a if point_server_is_a(n, first_is_a) else 1.0 - serve_b
        nxt: dict[tuple[int, int], float] = defaultdict(float)
        for (a, b), pr in dist.items():
            for (na, nb), w in (((a + 1, b), p_a_point), ((a, b + 1), 1.0 - p_a_point)):
                mass = pr * w
                if mass < PRUNE:
                    continue
                if max(na, nb) >= points and abs(na - nb) >= 2:
                    if na > nb:
                        win_a += mass
                else:
                    nxt[(na, nb)] += mass
        dist = nxt
        n += 1
    return win_a


def _tiebreak_games(r: dict[str, Any], decider: bool) -> int | None:
    if decider:
        return r["finalSetTiebreakAt"] if r["finalSet"] == "tiebreak" else None
    return r["tiebreakAt"]


def match_distribution(serve_a: float, serve_b: float, rules: dict[str, Any] | None = None,
                       first_server: str = "A", max_games: int = MAX_GAMES) -> dict[str, Any]:
    """Exact distribution of the match under the rules. Returns probabilities, not samples.

    Keys: p_a, p_b (match win), unresolved (mass still in play after max_games), match_scores
    {(winner, winner_sets, loser_sets): p}, sets_played {n: p}, total_games {n: p}, expected_games (over resolved
    matches), p_tiebreak_any (at least one set went to a tiebreak), p_match_tiebreak (the final set was a match
    tiebreak), set_scores {(set_no, winner, winner_games, loser_games): expected count per match}.
    """
    r = normalise_rules(rules)
    stw = (r["bestOf"] + 1) // 2
    frontier: dict[tuple, float] = {(0, 0, 0, 0, first_server == "A", False): 1.0}
    win = {"A": 0.0, "B": 0.0}
    match_scores: dict[tuple, float] = defaultdict(float)
    total_games: dict[int, float] = defaultdict(float)
    set_scores: dict[tuple, float] = defaultdict(float)
    flags = {"tiebreak_any": 0.0, "match_tiebreak": 0.0}

    def end_match(winner: str, winner_sets: int, loser_sets: int, games: int, tb: bool, mass: float) -> None:
        win[winner] += mass
        match_scores[(winner, winner_sets, loser_sets)] += mass
        total_games[games] += mass
        if tb:
            flags["tiebreak_any"] += mass

    for step in range(max_games):
        if not frontier:
            break
        nxt: dict[tuple, float] = defaultdict(float)
        for (sa, sb, ga, gb, srv, tb), pr in frontier.items():
            set_no = sa + sb + 1
            decider = sa == stw - 1 and sb == stw - 1
            if decider and r["finalSet"] == "match_tiebreak" and ga == 0 and gb == 0:
                pa = tiebreak_win_prob_a(serve_a, serve_b, srv, r["finalSetTiebreakPoints"])
                flags["match_tiebreak"] += pr
                end_match("A", stw, stw - 1, step, tb, pr * pa)
                end_match("B", stw, stw - 1, step, tb, pr * (1.0 - pa))
                continue
            tb_games = _tiebreak_games(r, decider)
            if tb_games is not None and ga == tb_games and gb == tb_games:
                points = r["finalSetTiebreakPoints"] if decider else r["tiebreakPoints"]
                pa = tiebreak_win_prob_a(serve_a, serve_b, srv, points)
                for winner, w in (("A", pa), ("B", 1.0 - pa)):
                    mass = pr * w
                    set_scores[(set_no, winner, tb_games + 1, tb_games)] += mass
                    sets_a, sets_b = sa + (winner == "A"), sb + (winner == "B")
                    if sets_a == stw or sets_b == stw:
                        mine, theirs = (sets_a, sets_b) if winner == "A" else (sets_b, sets_a)
                        end_match(winner, mine, theirs, step + 1, True, mass)
                    else:
                        nxt[(sets_a, sets_b, 0, 0, not srv, True)] += mass
                continue
            pg = game_win_prob(serve_a if srv else serve_b)  # P(the server wins the game)
            pa_game = pg if srv else 1.0 - pg
            for winner, w in (("A", pa_game), ("B", 1.0 - pa_game)):
                mass = pr * w
                na, nb = ga + (winner == "A"), gb + (winner == "B")
                if max(na, nb) >= GAMES_PER_SET and abs(na - nb) >= 2:
                    set_scores[(set_no, winner, max(na, nb), min(na, nb))] += mass
                    sets_a, sets_b = sa + (winner == "A"), sb + (winner == "B")
                    if sets_a == stw or sets_b == stw:
                        mine, theirs = (sets_a, sets_b) if winner == "A" else (sets_b, sets_a)
                        end_match(winner, mine, theirs, step + 1, tb, mass)
                    else:
                        nxt[(sets_a, sets_b, 0, 0, not srv, tb)] += mass
                else:
                    nxt[(sa, sb, na, nb, not srv, tb)] += mass
        frontier = nxt

    resolved = win["A"] + win["B"]
    sets_played: dict[int, float] = defaultdict(float)
    for (_, mine, theirs), m in match_scores.items():
        sets_played[mine + theirs] += m
    return {
        "p_a": win["A"],
        "p_b": win["B"],
        "unresolved": sum(frontier.values()),
        "match_scores": dict(match_scores),
        "sets_played": dict(sets_played),
        "total_games": dict(total_games),
        "expected_games": sum(g * m for g, m in total_games.items()) / resolved if resolved else math.nan,
        "p_tiebreak_any": flags["tiebreak_any"],
        "p_match_tiebreak": flags["match_tiebreak"],
        "set_scores": dict(set_scores),
    }


def _play_game(rng: random.Random, server_is_a: bool, serve_a: float, serve_b: float) -> bool:
    """Point by point. True if A wins the game."""
    a = b = 0
    p = serve_a if server_is_a else 1.0 - serve_b
    while True:
        if rng.random() < p:
            a += 1
        else:
            b += 1
        if max(a, b) >= 4 and abs(a - b) >= 2:
            return a > b


def _play_tiebreak(rng: random.Random, first_is_a: bool, serve_a: float, serve_b: float, points: int) -> bool:
    """Point by point. True if A wins the tiebreak."""
    a = b = n = 0
    while True:
        p = serve_a if point_server_is_a(n, first_is_a) else 1.0 - serve_b
        if rng.random() < p:
            a += 1
        else:
            b += 1
        n += 1
        if max(a, b) >= points and abs(a - b) >= 2:
            return a > b


def simulate_match(rng: random.Random, serve_a: float, serve_b: float, rules: dict[str, Any] | None = None,
                   first_server: str = "A") -> dict[str, Any]:
    """One match, played point by point under the same rules. This shares no code with the dynamic programme."""
    r = normalise_rules(rules)
    stw = (r["bestOf"] + 1) // 2
    server_is_a = first_server == "A"
    sets_a = sets_b = games = 0
    tiebreak_any = match_tb = False
    set_log: list[tuple] = []
    while True:
        decider = sets_a == stw - 1 and sets_b == stw - 1
        if decider and r["finalSet"] == "match_tiebreak":
            a_wins = _play_tiebreak(rng, server_is_a, serve_a, serve_b, r["finalSetTiebreakPoints"])
            match_tb = True
            if a_wins:
                sets_a += 1
            else:
                sets_b += 1
            break
        tb_games = _tiebreak_games(r, decider)
        ga = gb = 0
        while True:
            if tb_games is not None and ga == tb_games and gb == tb_games:
                points = r["finalSetTiebreakPoints"] if decider else r["tiebreakPoints"]
                a_set = _play_tiebreak(rng, server_is_a, serve_a, serve_b, points)
                games += 1
                tiebreak_any = True
                winner_games, loser_games = tb_games + 1, tb_games
                server_is_a = not server_is_a
                break
            a_game = _play_game(rng, server_is_a, serve_a, serve_b)
            games += 1
            if a_game:
                ga += 1
            else:
                gb += 1
            server_is_a = not server_is_a
            if max(ga, gb) >= GAMES_PER_SET and abs(ga - gb) >= 2:
                a_set = ga > gb
                winner_games, loser_games = max(ga, gb), min(ga, gb)
                break
        if a_set:
            sets_a += 1
        else:
            sets_b += 1
        set_log.append((len(set_log) + 1, "A" if a_set else "B", winner_games, loser_games))
        if sets_a == stw or sets_b == stw:
            break
    return {
        "winner": "A" if sets_a > sets_b else "B",
        "sets_a": sets_a,
        "sets_b": sets_b,
        "games": games,
        "tiebreak_any": tiebreak_any,
        "match_tiebreak": match_tb,
        "set_log": set_log,
    }


def monte_carlo(serve_a: float, serve_b: float, rules: dict[str, Any] | None = None, first_server: str = "A",
                n: int = 50_000, seed: int = 1) -> dict[str, Any]:
    """Summaries over n simulated matches, with the sums needed for standard errors."""
    rng = random.Random(seed)
    a_wins = tiebreak_any = match_tb = 0
    games_sum = games_sq = 0.0
    sets_count: dict[int, int] = defaultdict(int)
    match_count: dict[tuple, int] = defaultdict(int)
    set_count: dict[tuple, float] = defaultdict(float)
    for _ in range(n):
        m = simulate_match(rng, serve_a, serve_b, rules, first_server)
        a_wins += m["winner"] == "A"
        tiebreak_any += m["tiebreak_any"]
        match_tb += m["match_tiebreak"]
        games_sum += m["games"]
        games_sq += m["games"] ** 2
        sets_count[m["sets_a"] + m["sets_b"]] += 1
        if m["winner"] == "A":
            match_count[("A", m["sets_a"], m["sets_b"])] += 1
        else:
            match_count[("B", m["sets_b"], m["sets_a"])] += 1
        for _, winner, wg, lg in m["set_log"]:
            set_count[(winner, wg, lg)] += 1
    mean_games = games_sum / n
    return {
        "n": n,
        "p_a": a_wins / n,
        "expected_games": mean_games,
        "games_se": math.sqrt(max(games_sq / n - mean_games**2, 0.0) / n),
        "p_tiebreak_any": tiebreak_any / n,
        "p_match_tiebreak": match_tb / n,
        "sets_played": {k: v / n for k, v in sets_count.items()},
        "match_scores": {k: v / n for k, v in match_count.items()},
        "set_scores": {k: v / n for k, v in set_count.items()},
    }


def _z(observed: float, expected: float, se: float) -> float:
    if se <= 0:
        return 0.0 if abs(observed - expected) < 1e-12 else math.inf
    return (observed - expected) / se


def _binomial_p(k: float, n: int, p: float) -> float:
    """Two-sided p-value for k successes in n matches at probability p. Exact below a variance of 1000, normal above."""
    if p <= 0.0:
        return 0.0 if k > 0 else 1.0
    if p >= 1.0:
        return 0.0 if k < n else 1.0
    var = n * p * (1.0 - p)
    if var >= 1000.0:
        return math.erfc(abs(k - n * p) / math.sqrt(2.0 * var))
    k = round(k)
    log_p, log_q = math.log(p), math.log(1.0 - p)

    def pmf(i: int) -> float:
        return math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * log_p + (n - i) * log_q)

    cap = min(n, int(n * p + 40 * math.sqrt(var) + 40))
    lower = sum(pmf(i) for i in range(0, min(k, cap) + 1))
    upper = sum(pmf(i) for i in range(k, cap + 1)) if k <= cap else 0.0
    return min(1.0, 2.0 * min(lower, upper))


def _poisson_p(k: float, lam: float) -> float:
    """Two-sided p-value for k occurrences against a Poisson mean lam. Exact below a mean of 1000, normal above."""
    if lam <= 0.0:
        return 0.0 if k > 0 else 1.0
    if lam >= 1000.0:
        return math.erfc(abs(k - lam) / math.sqrt(2.0 * lam))
    k = round(k)

    def pmf(i: int) -> float:
        return math.exp(-lam + i * math.log(lam) - math.lgamma(i + 1))

    cap = int(lam + 40 * math.sqrt(lam) + 40)
    lower = sum(pmf(i) for i in range(0, min(k, cap) + 1))
    upper = sum(pmf(i) for i in range(k, cap + 1)) if k <= cap else 0.0
    return min(1.0, 2.0 * min(lower, upper))


def compare(exact: dict[str, Any], mc: dict[str, Any]) -> dict[str, float]:
    """Two-sided p-value of each Monte Carlo quantity against the exact value. Match-level probabilities are binomial
    over n matches. Set results are Poisson counts, so rare results are tested exactly rather than with a normal z,
    which is unreliable for expected counts well below one. The mean game count uses its sampling standard error."""
    n = mc["n"]
    pvals = {
        "p_a": _binomial_p(mc["p_a"] * n, n, exact["p_a"]),
        "p_tiebreak_any": _binomial_p(mc["p_tiebreak_any"] * n, n, exact["p_tiebreak_any"]),
        "p_match_tiebreak": _binomial_p(mc["p_match_tiebreak"] * n, n, exact["p_match_tiebreak"]),
        "expected_games": math.erfc(
            abs(_z(mc["expected_games"], exact["expected_games"], mc["games_se"])) / math.sqrt(2.0)
        ),
    }
    for sets, p in exact["sets_played"].items():
        pvals[f"sets_{sets}"] = _binomial_p(mc["sets_played"].get(sets, 0.0) * n, n, p)
    for key, p in exact["match_scores"].items():
        pvals[f"match_score_{key[0]}_{key[1]}-{key[2]}"] = _binomial_p(mc["match_scores"].get(key, 0.0) * n, n, p)
    exact_by_result: dict[tuple, float] = defaultdict(float)
    for (_, winner, wg, lg), c in exact["set_scores"].items():
        exact_by_result[(winner, wg, lg)] += c
    for key in set(exact_by_result) | set(mc["set_scores"]):
        expected = exact_by_result.get(key, 0.0)
        observed = mc["set_scores"].get(key, 0.0)
        pvals[f"set_{key[0]}_{key[1]}-{key[2]}"] = _poisson_p(observed * n, expected * n)
    return pvals


VERIFY_FORMATS: dict[str, dict[str, Any]] = {
    "bo3_final_tiebreak": {"bestOf": 3, "finalSet": "tiebreak"},
    "bo3_match_tiebreak_10": {"bestOf": 3, "finalSet": "match_tiebreak", "finalSetTiebreakPoints": 10},
    "bo5_final_tiebreak": {"bestOf": 5, "finalSet": "tiebreak"},
    "bo5_final_advantage": {"bestOf": 5, "finalSet": "advantage"},
    "bo5_match_tiebreak_10": {"bestOf": 5, "finalSet": "match_tiebreak", "finalSetTiebreakPoints": 10},
    "bo3_no_tiebreaks": {"bestOf": 3, "tiebreakAt": None, "finalSet": "advantage"},
}
VERIFY_SERVES: tuple[tuple[float, float], ...] = ((0.55, 0.60), (0.62, 0.62), (0.66, 0.58), (0.70, 0.50))


def verify(n: int = 50_000, seed: int = 1) -> dict[str, Any]:
    """Exact against Monte Carlo over every format, serve pair and first server. Every quantity gets an exact p-value.
    The pass rule is a Bonferroni threshold over all quantities: no p-value may fall below 0.05 divided by their count."""
    rows = []
    for fmt, rules in VERIFY_FORMATS.items():
        for serve_a, serve_b in VERIFY_SERVES:
            for first in ("A", "B"):
                exact = match_distribution(serve_a, serve_b, rules, first)
                mc = monte_carlo(serve_a, serve_b, rules, first, n, seed)
                pvals = compare(exact, mc)
                worst = min(pvals, key=pvals.get)
                rows.append({
                    "format": fmt,
                    "serve_a": serve_a,
                    "serve_b": serve_b,
                    "first_server": first,
                    "exact_p_a": exact["p_a"],
                    "mc_p_a": mc["p_a"],
                    "unresolved": exact["unresolved"],
                    "min_p": pvals[worst],
                    "worst_quantity": worst,
                    "quantities": len(pvals),
                })
    total = sum(r["quantities"] for r in rows)
    threshold = 0.05 / total
    return {
        "n": n,
        "seed": seed,
        "quantities": total,
        "bonferroni_threshold": threshold,
        "min_p": min(r["min_p"] for r in rows),
        "passed": all(r["min_p"] >= threshold for r in rows),
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--serve-a", type=float)
    parser.add_argument("--serve-b", type=float)
    parser.add_argument("--best-of", type=int, default=3)
    parser.add_argument("--first-server", choices=("A", "B"), default="A")
    parser.add_argument("--final-set", choices=("advantage", "tiebreak", "match_tiebreak"), default="tiebreak")
    parser.add_argument("--verify", type=int, metavar="N", help="compare exact and Monte Carlo over N matches per case")
    args = parser.parse_args(argv)
    if args.verify:
        result = verify(args.verify)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.serve_a is None or args.serve_b is None:
        parser.error("--serve-a and --serve-b are required unless --verify is given")
    rules = {"bestOf": args.best_of, "finalSet": args.final_set}
    out = match_distribution(args.serve_a, args.serve_b, rules, args.first_server)
    out["match_scores"] = {"/".join(map(str, k)): v for k, v in out["match_scores"].items()}
    out["set_scores"] = {"/".join(map(str, k)): v for k, v in out["set_scores"].items()}
    out["total_games"] = {str(k): v for k, v in sorted(out["total_games"].items())}
    out["sets_played"] = {str(k): v for k, v in sorted(out["sets_played"].items())}
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
