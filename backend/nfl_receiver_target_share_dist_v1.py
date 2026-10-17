#!/usr/bin/env python3
"""nfl_receiver_target_share_dist_v1.py -- three candidate target-share allocation
models, tested on holdout 2026.

All three use the existing Spec B team volume (nfl_player_projection_v2.team_volume)
as the team total, then differ in how shares are allocated among players.

  1. Baseline         Spec B share_v20 (no probabilistic adjustment)
  2. Avail-adjusted   report_status -> p_play; redistribute shares among likely players
  3. Dirichlet shares Dirichlet-multinomial: phi-controlled share variability

Read-only on the DB. Usage: LP_DB_PATH=... python3 nfl_receiver_target_share_dist_v1.py --season 2026
"""
import argparse
import math
import os
import random
import sqlite3
from collections import defaultdict

import nfl_player_projection_v2 as eng

REC_POS = ("RB", "WR", "TE")
HIST_WEEKS = range(3, 19)
N_SIMS = 1000
N_FIT_SIMS = 200


def eligible(hist, season, positions=REC_POS):
    """(row) for every graded player-game: RB/WR/TE with 3+ prior games this season."""
    for (s, pid), rows in hist.by_player.items():
        if s != season:
            continue
        for i, r in enumerate(rows):
            if r.week in HIST_WEEKS and i >= 3 and r.pos in positions:
                yield r
SEED_BASE = 1024
# Report status -> pre-kickoff play probability. Out and Doubtful never play
# in the data (2,010 combined in 2024, 0 played). Questionable plays 63.4%.
# Null/empty plays 89.9%. Fixed from 2024 rates; not fitted here.
P_PLAY = {"Out": 0.0, "Doubtful": 0.0, "Questionable": 0.634, "Note": 1.0, "": 0.899}
GAMMA_SHAPE = 1.23  # from eng.DIST["G"], fitted on 2024


def connect():
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def load_availability(con, seasons):
    """( season, game_id, team, player_id ) -> (report_status, played).

    report_status is the pre-kickoff injury report. played is the realized
    outcome, used only as the label.
    """
    out = {}
    for season, game_id, team, pid, rep, played in con.execute(
        "SELECT season, game_id, team, player_id, report_status, played "
        "FROM player_game_availability WHERE league='nfl' AND season IN (%s)"
        % ",".join("?" * len(seasons)), list(seasons)):
        out[(season, game_id, team, pid)] = (rep or "", int(played) if played is not None else 0)
    return out


def p_play_for(rep):
    """Map a report_status string to pre-kickoff play probability."""
    if rep in P_PLAY:
        return P_PLAY[rep]
    return 0.899


# ---------------------------------------------------------------------------
# Candidate 1: Baseline (Spec B via eng.project)
# ---------------------------------------------------------------------------

def project_baseline(hist, season, row, params, avail):
    """Point-estimate targets from Spec B. Returns list of N_SIMS target draws."""
    v = eng.project(hist, season, row.week, row.pid, row.pos, row.team, row.opp,
                    row.game_id, params)
    if v is None or v.get("tgt", 0) <= 0:
        return None
    seed = SEED_BASE + hash((row.game_id, row.pid)) & 0xffff
    sims = eng.simulate(v["tgt"], v["rec"] / v["tgt"], v["rec_yds"] / v["rec"] if v["rec"] > 0 else 0.0,
                        v["rec_td"] / v["tgt"], n=N_SIMS, seed=seed)
    return [s[3] for s in sims]  # targets


# ---------------------------------------------------------------------------
# Candidate 2: Availability-adjusted
# ---------------------------------------------------------------------------

def project_avail_adj(hist, season, row, params, avail):
    """Shares redistributed among players expected to be available.

    Removes Out/Doubtful players, then probability-weights each remaining
    player's share by their pre-kickoff play probability (p_play), so that
    players with uncertain availability receive proportionally less allocation.
    Shares are then normalized to sum to (1 - OTHER).
    """
    vol = hist.team_volume(season, row.team, row.opp, row.week, "tgt", params["K_T"])
    if vol is None or vol <= 0:
        return None
    cands = hist.candidates(season, row.team, row.week)
    cands.setdefault(row.pid, row.pos)
    rep_self = avail.get((season, row.game_id, row.team, row.pid), ("", 0))[0]
    pp_self = p_play_for(rep_self)
    if pp_self <= 0:
        return None
    # Probability-weighted base shares for all available candidates
    base = {}
    for pid, pos in cands.items():
        rep = avail.get((season, row.game_id, row.team, pid), ("", 0))[0]
        pp = p_play_for(rep)
        if pp <= 0:
            continue
        got = hist.raw_share(season, pid, pos, row.week, "tgt", params, None)
        if got is None or got[0] <= 0:
            continue
        base[pid] = got[0] * pp
    if not base or row.pid not in base:
        return None
    raw_total = sum(base.values())
    if raw_total <= 0:
        return None
    eff_share = base[row.pid] / raw_total * (1.0 - params["OTHER"])
    targets = vol * eff_share
    return targets, pp_self


def _eff_rates(hist, season, row, params):
    """Compute catch rate, yards per reception, TD rate for a player."""
    catch = hist.eff(season, row.week, row.pid, row.pos, "tgt", "rec", params["K_CR"], None)
    ypt = hist.eff(season, row.week, row.pid, row.pos, "tgt", "rec_yds", params["K_YPT"], None)
    tdr = hist.eff(season, row.week, row.pid, row.pos, "tgt", "rec_td", params["K_TDT"], None)
    return (catch, ypt, tdr)


def _simulate_from_tgt(tgt_mean, p_play, rates, game_id, pid):
    """Simulate N_SIMS draws of (rec, yds, td, tgt) from an expected target count."""
    catch, ypt, tdr = rates
    seed = SEED_BASE + hash((game_id, pid)) & 0xffff
    sims = eng.simulate(tgt_mean, catch, ypt / catch if catch > 0 else 0.0, tdr,
                        n=N_SIMS, seed=seed)
    return sims


# ---------------------------------------------------------------------------
# Candidate 3: Dirichlet-multinomial probabilistic shares
# ---------------------------------------------------------------------------

def fit_dirichlet_phi(hist, season, params, avail):
    """Grid-search phi on the fit season (2024) by minimizing mean CRPS on targets.

    Pre-computes each team-game's base shares and volume once, then for each candidate
    phi draws Dirichlet samples and computes CRPS per player. Uses N_FIT_SIMS for speed.
    """
    N_FIT_SIMS = 200
    grid = [1.0, 5.0, 20.0, 100.0]
    best_phi, best_crps = 5.0, float("inf")
    games = list(eligible(hist, season, positions=REC_POS))
    if not games:
        return 5.0

    # Pre-compute team-level base data for the fit season
    team_lookup = {}
    for (s, team), weeks in hist.team_weeks.items():
        if s != season:
            continue
        for week in sorted(weeks):
            if week < 3 or week > 18:
                continue
            rows = hist.by_team[(season, team)].get(week, [])
            if not rows:
                continue
            opp = rows[0].opp
            game_id = rows[0].game_id
            vol = hist.team_volume(season, team, opp, week, "tgt", params["K_T"])
            if vol is None or vol <= 0:
                continue
            cands = hist.candidates(season, team, week)
            if not cands:
                continue
            bases = []
            for pid, pos in cands.items():
                rep = avail.get((season, game_id, team, pid), ("", 0))[0]
                pp = p_play_for(rep)
                if pp <= 0:
                    continue
                got = hist.raw_share(season, pid, pos, week, "tgt", params, None)
                if got is None or got[0] <= 0:
                    continue
                bases.append((pid, got[0], pp))
            total_base = sum(b[1] for b in bases)
            if total_base <= 0:
                continue
            norm = (1.0 - params["OTHER"]) / total_base
            team_lookup[(season, team, week, game_id, opp)] = {
                "vol": vol, "bases": [(b[0], b[1] * norm, b[2]) for b in bases],
                "game_id": game_id, "opp": opp}

    for phi in grid:
        rng = random.Random((SEED_BASE + int(phi)) & 0xffff)
        crps_vals = []
        for r in games:
            key = (season, r.team, r.week, r.game_id, r.opp)
            td = team_lookup.get(key)
            if td is None:
                continue
            vol = td["vol"]
            bases = td["bases"]
            pids = [b[0] for b in bases]
            if r.pid not in pids:
                continue
            alphas = [b[1] * b[2] * phi for b in bases]
            pid_idx = pids.index(r.pid)
            # Draw N_FIT_SIMS samples from the Dirichlet, extract this player's targets
            draws = []
            for _ in range(N_FIT_SIMS):
                gammas = [rng.gammavariate(a, 1.0) for a in alphas]
                total = sum(gammas)
                if total <= 0:
                    shares = [1.0 / len(pids)] * len(pids)
                else:
                    shares = [g / total for g in gammas]
                draws.append(vol * shares[pid_idx])
            crps_vals.append(crps(draws, r.tgt))
        if crps_vals:
            mean_crps = sum(crps_vals) / len(crps_vals)
            if mean_crps < best_crps:
                best_crps = mean_crps
                best_phi = phi
    return best_phi


def project_dirichlet_team(hist, season, team, week, game_id, opp, params, avail,
                           phi, rng):
    """Joint Dirichlet-multinomial: draw shares for all team players at once.

    Returns {pid: (draws_targets, p_play)} where draws_targets is a list
    of N_SIMS simulated target counts.
    """
    vol = hist.team_volume(season, team, opp, week, "tgt", params["K_T"])
    if vol is None or vol <= 0:
        return None
    cands = hist.candidates(season, team, week)
    if not cands:
        return None
    # Build base shares for available candidates
    bases = {}
    for pid, pos in cands.items():
        rep = avail.get((season, game_id, team, pid), ("", 0))[0]
        pp = p_play_for(rep)
        if pp <= 0:
            continue
        got = hist.raw_share(season, pid, pos, week, "tgt", params, None)
        if got is None or got[0] <= 0:
            continue
        bases[pid] = (got[0], pp)
    if not bases:
        return None
    total_base = sum(v[0] for v in bases.values())
    if total_base <= 0:
        return None
    norm = (1.0 - params["OTHER"]) / total_base
    alphas = {pid: base * norm * pp * phi for pid, (base, pp) in bases.items()}
    pids = sorted(bases)
    out = {}
    alpha_list = [alphas[pid] for pid in pids]
    for _ in range(N_SIMS):
        gammas = [rng.gammavariate(a, 1.0) for a in alpha_list]
        total = sum(gammas)
        if total <= 0:
            shares = [1.0 / len(pids)] * len(pids)
        else:
            shares = [g / total for g in gammas]
        for i, pid in enumerate(pids):
            t = vol * shares[i]
            if pid not in out:
                out[pid] = ([], bases[pid][1])
            out[pid][0].append(t)
    return out


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def crps(samples, obs):
    """CRPS for an empirical CDF (efficient form)."""
    n = len(samples)
    if n == 0:
        return float("inf")
    s = sorted(samples)
    # E|X - obs|: sum |x_i - obs| / n
    e_abs = sum(abs(x - obs) for x in s) / n
    # E|X - X'|: (2/n^2) * sum_{i<j} |s_i - s_j|
    e_pair = 0.0
    for i, x in enumerate(s):
        e_pair += x * (2 * i - n + 1)
    e_pair = e_pair / (n * n)  # (1/n^2) * sum_{i<j} |s_i - s_j|
    return e_abs - e_pair


def coverage(draws, obs, level):
    """1 if obs falls within the [lo_q, hi_q] interval of draws."""
    s = sorted(draws)
    n = len(s)
    lo = s[min(int(((1.0 - level) / 2.0) * n), n - 1)]
    hi = s[min(int((1.0 - (1.0 - level) / 2.0) * n), n - 1)]
    return 1.0 if lo <= obs <= hi else 0.0


def mae(pairs):
    return sum(abs(p - a) for p, a in pairs) / len(pairs) if pairs else float("inf")


def mean_ci(vals):
    """Mean and 1.96*SE for a list of values (unpaired)."""
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    m = sum(vals) / n
    if n < 2:
        return m, 0.0
    var = sum((v - m) ** 2 for v in vals) / n
    return m, 1.96 * math.sqrt(var / n)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(hist, season, params, avail, con):
    """Run all three candidates on the holdout season."""
    # Fit Dirichlet phi on the fit season (2024)
    phi = fit_dirichlet_phi(hist, 2024, params, avail)
    print("Dirichlet phi (fit on 2024): %.2f" % phi)

    games = sorted(eligible(hist, season, positions=REC_POS),
                   key=lambda r: (r.week, r.pid))
    print("eligible %d player-games: %d" % (season, len(games)))

    # Pre-compute Dirichlet team-level draws
    team_dir = {}
    for (s, team), weeks in hist.team_weeks.items():
        if s != season:
            continue
        for week in sorted(weeks):
            if week < 2 or week > 18:
                continue
            rows = hist.by_team[(season, team)].get(week, [])
            if not rows:
                continue
            opp = rows[0].opp
            game_id = rows[0].game_id
            rng = random.Random(SEED_BASE + hash((season, team, week)) & 0xffff)
            team_dir[(season, team, week, game_id, opp)] = \
                project_dirichlet_team(hist, season, team, week, game_id, opp,
                                       params, avail, phi, rng)

    # Per-model accumulators, keyed by player-game for paired comparison
    # key = (game_id, pid), value = dict of metric lists
    results = defaultdict(lambda: {
        "baseline": {"crps": [], "cov50": 0, "cov80": 0, "cov90": 0,
                      "mae_tgt": [], "mae_rec": [], "mae_yds": [], "n": 0},
        "avail_adj": {"crps": [], "cov50": 0, "cov80": 0, "cov90": 0,
                       "mae_tgt": [], "mae_rec": [], "mae_yds": [], "n": 0},
        "dirichlet": {"crps": [], "cov50": 0, "cov80": 0, "cov90": 0,
                       "mae_tgt": [], "mae_rec": [], "mae_yds": [], "n": 0},
    })

    for r in games:
        key = (r.game_id, r.pid)
        m = results[key]
        seed = SEED_BASE + hash((r.game_id, r.pid)) & 0xffff
        rng = random.Random(seed)
        td_key = (season, r.team, r.week, r.game_id, r.opp)

        # -- Baseline --
        v = eng.project(hist, season, r.week, r.pid, r.pos, r.team, r.opp,
                        r.game_id, params)
        if v is not None and v.get("tgt", 0) > 0:
            sims = eng.simulate(v["tgt"], v["rec"] / v["tgt"],
                                v["rec_yds"] / v["rec"] if v["rec"] > 0 else 0.0,
                                v["rec_td"] / v["tgt"], n=N_SIMS, seed=seed)
            tgt_draws = [s[3] for s in sims]
            m["baseline"]["crps"].append(crps(tgt_draws, r.tgt))
            m["baseline"]["cov50"] += coverage(tgt_draws, r.tgt, 0.5)
            m["baseline"]["cov80"] += coverage(tgt_draws, r.tgt, 0.8)
            m["baseline"]["cov90"] += coverage(tgt_draws, r.tgt, 0.9)
            m["baseline"]["n"] += 1
            m["baseline"]["mae_tgt"].append((sum(tgt_draws) / len(tgt_draws), r.tgt))
            m["baseline"]["mae_rec"].append((
                sum(s[0] for s in sims) / len(sims), r.rec))
            m["baseline"]["mae_yds"].append((
                sum(s[1] for s in sims) / len(sims), r.rec_yds))

        # -- Availability-adjusted --
        result_aa = project_avail_adj(hist, season, r, params, avail)
        if result_aa is not None:
            t_mean, pp_self = result_aa
            catch = hist.eff(season, r.week, r.pid, r.pos, "tgt", "rec",
                             params["K_CR"], None)
            ypt = hist.eff(season, r.week, r.pid, r.pos, "tgt", "rec_yds",
                           params["K_YPT"], None)
            tdr = hist.eff(season, r.week, r.pid, r.pos, "tgt", "rec_td",
                           params["K_TDT"], None)
            sims = eng.simulate(t_mean, catch, ypt / catch if catch > 0 else 0.0,
                                tdr, n=N_SIMS, seed=seed)
            tgt_draws = [s[3] for s in sims]
            m["avail_adj"]["crps"].append(crps(tgt_draws, r.tgt))
            m["avail_adj"]["cov50"] += coverage(tgt_draws, r.tgt, 0.5)
            m["avail_adj"]["cov80"] += coverage(tgt_draws, r.tgt, 0.8)
            m["avail_adj"]["cov90"] += coverage(tgt_draws, r.tgt, 0.9)
            m["avail_adj"]["n"] += 1
            m["avail_adj"]["mae_tgt"].append((sum(tgt_draws) / len(tgt_draws), r.tgt))
            m["avail_adj"]["mae_rec"].append((
                sum(s[0] for s in sims) / len(sims), r.rec))
            m["avail_adj"]["mae_yds"].append((
                sum(s[1] for s in sims) / len(sims), r.rec_yds))

        # -- Dirichlet --
        td = team_dir.get(td_key)
        if td and r.pid in td:
            draws_tgt_list, p_play = td[r.pid]
            m["dirichlet"]["crps"].append(crps(draws_tgt_list, r.tgt))
            m["dirichlet"]["cov50"] += coverage(draws_tgt_list, r.tgt, 0.5)
            m["dirichlet"]["cov80"] += coverage(draws_tgt_list, r.tgt, 0.8)
            m["dirichlet"]["cov90"] += coverage(draws_tgt_list, r.tgt, 0.9)
            m["dirichlet"]["n"] += 1
            pt = sum(draws_tgt_list) / len(draws_tgt_list)
            m["dirichlet"]["mae_tgt"].append((pt, r.tgt))
            # Downstream simulation from each Dirichlet target draw
            catch = hist.eff(season, r.week, r.pid, r.pos, "tgt", "rec",
                             params["K_CR"], None)
            ypt = hist.eff(season, r.week, r.pid, r.pos, "tgt", "rec_yds",
                           params["K_YPT"], None)
            tdr = hist.eff(season, r.week, r.pid, r.pos, "tgt", "rec_td",
                           params["K_TDT"], None)
            rec_draws, yds_draws = [], []
            for sim_t in draws_tgt_list:
                ds = eng.simulate(sim_t, catch, ypt / catch if catch > 0 else 0.0,
                                  tdr, n=1, seed=(seed + int(sim_t * 1000)) & 0xffff)
                rec_draws.append(ds[0][0])
                yds_draws.append(ds[0][1])
            m["dirichlet"]["mae_rec"].append(
                (sum(rec_draws) / len(rec_draws), r.rec))
            m["dirichlet"]["mae_yds"].append(
                (sum(yds_draws) / len(yds_draws), r.rec_yds))

    # -- Report --
    print("\n== Results: %d holdout ==\n" % season)
    for model_name in ("baseline", "avail_adj", "dirichlet"):
        all_crps = []
        all_mnemonics = []
        n_games = 0
        for key, vals in results.items():
            mm = vals[model_name]
            all_crps.extend(mm["crps"])
            n_games += mm["n"]
        if all_crps:
            c_mean, c_ci = mean_ci(all_crps)
            print("Model: %s" % model_name)
            print("  CRPS (targets): %.4f +/- %.4f (mean over %d player-games)" %
                  (c_mean, c_ci, n_games))
            print("  Coverage 50%%: %.3f" %
                  (sum(results[k][model_name]["cov50"] for k in results) / n_games))
            print("  Coverage 80%%: %.3f" %
                  (sum(results[k][model_name]["cov80"] for k in results) / n_games))
            print("  Coverage 90%%: %.3f" %
                  (sum(results[k][model_name]["cov90"] for k in results) / n_games))
            all_mae_tgt = [x for k in results for x in results[k][model_name]["mae_tgt"]]
            if all_mae_tgt:
                print("  MAE targets: %.4f (n=%d)" % (mae(all_mae_tgt), len(all_mae_tgt)))
            print()

    # -- Paired CRPS comparison (by player-game, same games) --
    print("== Paired CRPS by player-game ==")
    def paired_crps(a_name, b_name):
        diffs = []
        for key in results:
            a = results[key][a_name]["crps"]
            b = results[key][b_name]["crps"]
            if a and b:
                diffs.append(sum(b) / len(b) - sum(a) / len(a))
        if diffs:
            mean = sum(diffs) / len(diffs)
            var = sum((d - mean) ** 2 for d in diffs) / len(diffs)
            se = math.sqrt(var / len(diffs))
            print("  %s - %s: %+.4f +/- %.4f (n=%d player-games)" %
                  (b_name, a_name, mean, 1.96 * se, len(diffs)))

    paired_crps("baseline", "avail_adj")
    paired_crps("baseline", "dirichlet")
    paired_crps("avail_adj", "dirichlet")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--season", type=int, default=2026)
    a = ap.parse_args(argv)
    params = dict(eng.DEFAULTS, K_T=8.0)
    con = connect()
    avail = load_availability(con, [2024, a.season])
    hist = eng.History.load(con, [2024, a.season])
    evaluate(hist, a.season, params, avail, con)


if __name__ == "__main__":
    main()
