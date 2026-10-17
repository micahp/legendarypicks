#!/usr/bin/env python3
"""nfl_qb_opportunities_propensity.py -- do opportunities x pass propensity beat the incumbent on attempts?

The incumbent (nfl_player_projection_v2.project_qb) projects a quarterback's attempts as

    att = team_volume('att', K_T) * qb_share

where team_volume blends the team's own season-to-date attempts with what its opponent allowed,
each regressed to the league mean with K_T = 8 pseudo-games. Section 6 of
RESULTS-nfl-marcel-and-calibration-2026-10-16.md showed that this compresses dispersion: the
projection has sd 1.7 against an actual sd of 9.7, because with one to four games behind a team
67 to 89 percent of it is the league mean.

This tests the decomposition

    att = opportunities(team) * propensity(team) * qb_share

with opportunities = offensive plays per game and propensity = pass attempts per play, each
regressed to its own league mean with its own pseudo-count (K_OPP pseudo-games, K_PROP
pseudo-plays). The claim under test is that a team's play count and its pass rate vary
independently enough that separating them carries more signal than the blended attempt rate.

Evaluation is on team attempts first (the pure model), then the same two projections are scaled by
the quarterback share for the player-game level. Constants are fitted on the fit seasons in the
early-week regime (weeks 2 to --fit-max-week), the only regime props exist in, then evaluated on
seasons neither fit saw.

Read-only. Usage: LP_DB_PATH=... python3 nfl_qb_opportunities_propensity.py \
    --fit-seasons 2013 ... 2021 --season 2026
"""
import argparse
import math
import os
import sqlite3
from collections import defaultdict

OFFENSIVE_PLAYS = ("pass", "run", "qb_kneel", "qb_spike")
PLAY_TYPES_SQL = ",".join("'%s'" % p for p in OFFENSIVE_PLAYS)


def reg(total, n, league, k):
    return (total + k * league) / (n + k) if (n + k) else None


def sd(v):
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def auc(pairs):
    """Rank AUC with tie handling. pairs = [(score, outcome)]."""
    s = sorted(pairs, key=lambda p: p[0])
    n = len(s)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and s[j + 1][0] == s[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2.0 + 1.0
        i = j + 1
    n1 = sum(1 for _, y in s if y)
    n0 = n - n1
    if n1 == 0 or n0 == 0:
        return None
    return (sum(r for r, (_, y) in zip(ranks, s) if y) - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def load(con):
    """(season, team, week) -> {game_id, opp, att, plays, drop, snaps} for every team-game."""
    sched = {}
    for game_id, season, away, home in con.execute(
            "SELECT game_id, season, away_team, home_team FROM nfl_schedule"):
        sched[(season, game_id, away)] = home
        sched[(season, game_id, home)] = away
    logs = {}
    for season, game_id, team, att, drop, snaps in con.execute(
            "SELECT season, game_id, team, "
            "SUM(CAST(json_extract(stats,'$.att') AS REAL)), "
            "SUM(CAST(json_extract(stats,'$.dropbacks') AS REAL)), "
            "SUM(CAST(json_extract(stats,'$.off_snaps') AS REAL)) "
            "FROM player_game_logs WHERE league='nfl' GROUP BY season, game_id, team"):
        logs[(season, game_id, team)] = {"att": att or 0.0, "drop": drop or 0.0, "snaps": snaps or 0.0}
    pbp = {}
    for season, game_id, posteam, plays, drop, patt in con.execute(
            "SELECT season, game_id, posteam, COUNT(*), SUM(qb_dropback), SUM(pass_attempt) "
            "FROM nfl_pbp WHERE posteam IS NOT NULL AND play_type IN (%s) "
            "GROUP BY season, game_id, posteam" % PLAY_TYPES_SQL):
        pbp[(season, game_id, posteam)] = {"plays": plays, "drop": drop or 0.0, "patt": patt or 0.0}
    rec = {}
    for (season, game_id, team), v in logs.items():
        p = pbp.get((season, game_id, team))
        if p is None:
            continue
        week = int(game_id.split("_")[1])
        if week > 18:
            continue
        rec[(season, team, week)] = {"game_id": game_id, "opp": sched.get((season, game_id, team)),
                                     "att": v["att"], "plays": p["plays"], "snaps": v["snaps"]}
    return rec


class Model(object):
    """Team attempt projection. kind is 'inc' (blend attempts) or 'sep' (plays x propensity)."""

    def __init__(self, rec, kind, opp_col="plays"):
        self.rec = rec
        self.kind = kind
        self.opp_col = opp_col
        self.by_team = defaultdict(dict)   # (season, team) -> week -> record
        for (season, team, week), r in rec.items():
            self.by_team[(season, team)][week] = r

    def league_pg(self, season, week, key):
        vals = [r[key] for (s, t, w), r in self.rec.items() if s == season and w < week]
        return sum(vals) / len(vals) if vals else None

    def league_rate(self, season, week, num, den):
        n = sum(r[num] for (s, t, w), r in self.rec.items() if s == season and w < week)
        d = sum(r[den] for (s, t, w), r in self.rec.items() if s == season and w < week)
        return n / d if d else None

    def prior(self, season, team, week):
        return sorted(w for w in self.by_team[(season, team)] if w < week)

    def allowed(self, season, opp, week, key):
        """What the opponent's opponents did, in the opponent's games before `week`."""
        tot, n = 0.0, 0
        for w in self.prior(season, opp, week):
            r = self.rec[(season, opp, w)]
            other = r["opp"]
            if other is None or (season, other, w) not in self.rec:
                continue
            tot += self.rec[(season, other, w)][key]
            n += 1
        return tot, n

    def project(self, season, team, opp, week, k_t, k_opp, k_prop, blend=True):
        if opp is None:
            return None
        if self.kind == "inc":
            league = self.league_pg(season, week, "att")
            if league is None:
                return None
            own_w = self.prior(season, team, week)
            own = reg(sum(self.rec[(season, team, w)]["att"] for w in own_w), len(own_w), league, k_t)
            at, an = self.allowed(season, opp, week, "att")
            al = reg(at, an, league, k_t)
            if own is None or al is None:
                return None
            return 0.5 * own + 0.5 * al if blend else own
        league_p = self.league_pg(season, week, self.opp_col)
        league_r = self.league_rate(season, week, "att", self.opp_col)
        if league_p is None or league_r is None:
            return None
        own_w = self.prior(season, team, week)
        own_plays = reg(sum(self.rec[(season, team, w)][self.opp_col] for w in own_w), len(own_w), league_p, k_opp)
        own_rate = reg(sum(self.rec[(season, team, w)]["att"] for w in own_w),
                       sum(self.rec[(season, team, w)][self.opp_col] for w in own_w), league_r, k_prop)
        if not blend:
            if own_plays is None or own_rate is None:
                return None
            return own_plays * own_rate
        at, an = self.allowed(season, opp, week, "att")
        pt, pn = self.allowed(season, opp, week, self.opp_col)
        al_plays = reg(pt, pn, league_p, k_opp)
        al_rate = reg(at, pt, league_r, k_prop)
        if None in (own_plays, own_rate, al_plays, al_rate):
            return None
        return (0.5 * own_plays + 0.5 * al_plays) * (0.5 * own_rate + 0.5 * al_rate)


def team_games(rec, seasons, max_week=18):
    return [(season, team, week) for (season, team, week) in sorted(rec) if season in seasons and 2 <= week <= max_week]


def mae(pairs):
    return sum(abs(p - a) for p, a in pairs) / len(pairs)


def fit(rec, model, seasons, max_week, grids):
    games = team_games(rec, seasons, max_week)
    best = None
    for combo in grids:
        vals = []
        for season, team, week in games:
            r = rec[(season, team, week)]
            p = model.project(season, team, r["opp"], week, *combo)
            if p is not None:
                vals.append((p, r["att"]))
        if not vals:
            continue
        m = mae(vals)
        if best is None or m < best[0]:
            best = (m, combo, len(vals))
    return best


def evaluate(rec, model, seasons, params, threshold):
    out = {}
    for label, ss in seasons.items():
        games = team_games(rec, ss)
        vals = []
        for season, team, week in games:
            r = rec[(season, team, week)]
            p = model.project(season, team, r["opp"], week, *params)
            if p is not None and r["att"] > 0:
                vals.append((p, r["att"], r["game_id"]))
        if not vals:
            continue
        proj = [v[0] for v in vals]
        act = [v[1] for v in vals]
        out[label] = {"n": len(vals), "mae": mae([(p, a) for p, a, _ in vals]),
                      "sd_proj": sd(proj), "sd_act": sd(act),
                      "bias": (sum(proj) - sum(act)) / len(vals),
                      "auc": auc([(p, 1 if a > threshold else 0) for p, a, _ in vals]) or 0.0}
    return out


def paired(rec, mA, pA, mB, pB, seasons, max_week):
    """Paired per-team-game differences of B minus A, clustered by game."""
    games = team_games(rec, seasons, max_week)
    d, cl = [], defaultdict(list)
    for season, team, week in games:
        r = rec[(season, team, week)]
        pa = mA.project(season, team, r["opp"], week, *pA)
        pb = mB.project(season, team, r["opp"], week, *pB)
        if pa is None or pb is None:
            continue
        x = abs(pb - r["att"]) - abs(pa - r["att"])
        d.append(x)
        cl[r["game_id"]].append(x)
    n = len(d)
    mean = sum(d) / n
    G = len(cl)
    var = G / (G - 1.0) * sum((sum(v) - len(v) * mean) ** 2 for v in cl.values()) / n ** 2 if G > 1 else 0.0
    return mean, 1.96 * math.sqrt(var), n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fit-seasons", type=int, nargs="+", required=True)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--fit-max-week", type=int, default=5)
    ap.add_argument("--kt", type=float, nargs="+", default=[2.0, 4.0, 8.0, 16.0])
    ap.add_argument("--kopp", type=float, nargs="+", default=[2.0, 4.0, 8.0, 16.0])
    ap.add_argument("--kprop", type=float, nargs="+", default=[100.0, 200.0, 400.0, 800.0])
    ap.add_argument("--opp-col", choices=("plays", "snaps"), default="plays")
    a = ap.parse_args(argv)
    path = os.environ.get("LP_DB_PATH")
    if not path:
        raise SystemExit("LP_DB_PATH is required")
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    rec = load(con)
    print("loaded %d team-games, seasons %s" % (len(rec), sorted({s for s, t, w in rec})))

    # -- fit both models on the fit seasons, early-week regime -------------------------------
    fit_set = set(a.fit_seasons)
    grids_inc = [(kt, 0.0, 0.0) for kt in a.kt]
    grids_sep = [(8.0, ko, kp) for ko in a.kopp for kp in a.kprop]
    m_inc = Model(rec, "inc", a.opp_col)
    m_sep = Model(rec, "sep", a.opp_col)
    b_inc = fit(rec, m_inc, fit_set, a.fit_max_week, grids_inc)
    b_sep = fit(rec, m_sep, fit_set, a.fit_max_week, grids_sep)
    print("\nfit seasons %s, weeks 2 to %d: %d team-games" % (a.fit_seasons, a.fit_max_week,
          len(team_games(rec, fit_set, a.fit_max_week))))
    print("  incumbent: K_T %.2f, MAE %.4f (n %d)" % (b_inc[1][0], b_inc[0], b_inc[2]))
    print("  separated: K_OPP %.1f K_PROP %.0f, MAE %.4f (n %d)" % (b_sep[1][1], b_sep[1][2], b_sep[0], b_sep[2]))

    # -- predetermined threshold for AUC, from the fit seasons in the same regime -------------
    thr = sorted(r["att"] for (s, t, w), r in rec.items() if s in fit_set and 2 <= w <= a.fit_max_week)
    threshold = thr[len(thr) // 2]
    print("  predetermined AUC threshold (median team attempts, fit weeks 2 to %d): %.1f" % (a.fit_max_week, threshold))

    # -- holdout ---------------------------------------------------------------------------
    hold = {a.season: {a.season}}
    print("\n== holdout season %d ==" % a.season)
    for nm, mdl, prm in (("incumbent", m_inc, b_inc[1]), ("separated", m_sep, b_sep[1])):
        ev = evaluate(rec, mdl, hold, prm, threshold)[a.season]
        print("  %-10s n %4d  MAE %.4f  sd proj %.3f (act %.3f)  bias %+.3f  AUC %.4f" % (
            nm, ev["n"], ev["mae"], ev["sd_proj"], ev["sd_act"], ev["bias"], ev["auc"]))
    dm, hw, n = paired(rec, m_inc, b_inc[1], m_sep, b_sep[1], hold, 18)
    print("  paired |sep| - |inc| on %d team-games: %+.4f  clustered 95%% +/- %.4f" % (n, dm, hw))

    # -- the discrimination objective: fit both models by AUC and compare --------------------
    print("\n== fit by AUC (discrimination) ==")
    fit_games = team_games(rec, fit_set, a.fit_max_week)
    thr_fit = sorted(rec[(s, t, w)]["att"] for s, t, w in fit_games)
    thr_fit = thr_fit[len(thr_fit) // 2]

    def fit_auc(model, grids):
        best = None
        for combo in grids:
            vals = []
            for s, t, w in fit_games:
                p = model.project(s, t, rec[(s, t, w)]["opp"], w, *combo)
                if p is not None:
                    vals.append((p, rec[(s, t, w)]["att"]))
            if not vals:
                continue
            sc = auc([(p, 1 if x > thr_fit else 0) for p, x in vals]) or 0.0
            if best is None or sc > best[0]:
                best = (sc, combo, len(vals))
        return best

    ba_inc = fit_auc(m_inc, grids_inc)
    ba_sep = fit_auc(m_sep, grids_sep)
    print("  fit weeks 2 to %d, threshold %.1f: incumbent K_T %.2f AUC %.4f; separated K_OPP %.1f K_PROP %.0f AUC %.4f" % (
        a.fit_max_week, thr_fit, ba_inc[1][0], ba_inc[0], ba_sep[1][1], ba_sep[1][2], ba_sep[0]))
    for nm, mdl, prm in (("incumbent", m_inc, ba_inc[1]), ("separated", m_sep, ba_sep[1])):
        ev = evaluate(rec, mdl, hold, prm, threshold)[a.season]
        print("  holdout %-10s MAE %.4f  sd proj %.3f  AUC %.4f" % (nm, ev["mae"], ev["sd_proj"], ev["auc"]))
    dm, hw, n = paired(rec, m_inc, ba_inc[1], m_sep, ba_sep[1], hold, 18)
    print("  paired |sep| - |inc| on %d team-games: %+.4f  clustered 95%% +/- %.4f" % (n, dm, hw))

    # -- across seasons and regimes --------------------------------------------------------
    print("\n== separated vs incumbent, by season and regime (MAE, and paired diff) ==")
    print("  %-8s %-10s %8s %8s %10s" % ("season", "regime", "inc MAE", "sep MAE", "paired sep-inc"))
    for season in sorted({s for s, t, w in rec} - fit_set):
        for lo, hi, label in ((2, a.fit_max_week, "wk2-%d" % a.fit_max_week), (2, 18, "all wk")):
            games = [(s, t, w) for (s, t, w) in team_games(rec, {season}, hi) if lo <= w <= hi]
            if len(games) < 20:
                continue
            vi = [(m_inc.project(s, t, rec[(s, t, w)]["opp"], w, *b_inc[1]), rec[(s, t, w)]["att"]) for s, t, w in games]
            vs = [(m_sep.project(s, t, rec[(s, t, w)]["opp"], w, *b_sep[1]), rec[(s, t, w)]["att"]) for s, t, w in games]
            vi = [(p, x) for p, x in vi if p is not None]
            vs = [(p, x) for p, x in vs if p is not None]
            if not vi or not vs:
                continue
            dm, hw, n = paired(rec, m_inc, b_inc[1], m_sep, b_sep[1], {season}, hi)
            print("  %-8s %-10s %8.4f %8.4f %+10.4f +/- %.4f (n %d)" % (
                season, label, mae(vi), mae(vs), dm, hw, n))


if __name__ == "__main__":
    main()
