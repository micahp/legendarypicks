"""nfl_player_projection_v2.py -- Spec B section 4: player stat projections, volume times efficiency.

PRE-REGISTERED 2026-10-12, before any 2025 number was computed. Nothing below is changed after a result.

What it projects: a player's regular-season stat line for one team game, GIVEN that he plays.
    receiving: targets, receptions, rec_yds, rec_td      (RB, WR, TE, FB)
    rushing:   carries, rush_yds, rush_td                (QB, RB, WR, TE, FB)
Quarterback passing is not built in this version.

Method (Spec B 4.1 to 4.5), every input uses only games BEFORE the target week:
  1. Team volume. Team targets and carries per game: the team's own season-to-date per game and its
     opponent's season-to-date allowed per game, each regressed to the league mean with K_T pseudo-games,
     then averaged 50/50. No game-script adjustment (that needs SPEC A's projected margin).
  2. Player share. Recency-weighted (half-life H weeks) season-to-date share of team volume over games
     the player played, regressed with K_S pseudo-games to a prior: his previous-season share if he played
     6 or more games, else the position mean share. Shares of the available candidates are normalised to
     1 - OTHER, where OTHER is fitted in 2024.
  3. Availability. Candidates are players who logged for the team in its last 3 games. Teammates whose
     final injury report status is Out or Doubtful are removed. Their share is redistributed by Spec B 4.3
     (History.team_shares, pre-registered 2026-10-13): observed shares where a player has MIN_TOGETHER
     games without them this season or last, otherwise within the position group with the next man up
     taking a fitted fraction NMU_<col> (fitted on 2024 starter absences, backtest --fit-nmu).
     (Until 2026-10-12 the removed share was spread proportionally over every candidate and the observed
     share was blended at n / (n + MIN_TOGETHER).)
  4. Efficiency. Catch rate, yards per target, TD per target, yards per carry, TD per carry from the
     player's games in the current and previous season, regressed to the position mean with K_CR, K_YPT,
     K_TDT, K_YPC, K_TDC pseudo-opportunities.
  5. Stat line = volume x share x efficiency. Fantasy points are derived, never projected.

Constants. FIXED (chosen here, not fitted): MIN_TOGETHER = 3, LAST_GAMES = 3, PRIOR_MIN_GAMES = 6.
FITTED ON 2024 ONLY (walk-forward inside 2024, weeks 3 to 18), then frozen for 2025:
    volume:     (H, K_S, K_T) over H in {2, 4, 8}, K_S in {1, 2, 3, 5, 8}, K_T in {2, 4, 8},
                minimising the mean absolute error of projected targets on games played;
    efficiency: K_YPT in {10, 20, 40, 80, 160}, K_CR in {10, 20, 40, 80, 160}, K_TDT in {20, 40, 80, 160, 320}
                and the rushing analogues, minimising squared error of the stat given the ACTUAL
                opportunities (so efficiency is fitted apart from volume);
    OTHER:      the 2024 mean of 1 - sum of candidate shares.

GATE (Spec B section 5), 2025 weeks 3 to 18, player-games where the player played and had at least 3
games earlier in 2025: version 2 must have a lower mean absolute error than Marcel-lite
(analytics.projections.project_stat on that player's earlier 2025 games, exactly the live route) on BOTH
receiving yards and receptions. Reported with a paired player-game bootstrap 95% interval of the MAE
difference. A second benchmark, Marcel-lite over the 2024 and 2025 games together, is reported but is not
the gate. ESPN's weekly projections are a separate benchmark (B7); not used here.
"""
import math
import os
import random
import sqlite3
from collections import defaultdict

LEAGUE = "nfl"
SKILL = ("QB", "RB", "FB", "WR", "TE")
MIN_TOGETHER = 3
LAST_GAMES = 3
PRIOR_MIN_GAMES = 6
OUT_STATUSES = ("Out", "Doubtful")

# (opportunity column, [(stat column, name)])
RECEIVING = ("tgt", (("rec", "rec"), ("rec_yds", "rec_yds"), ("rec_td", "rec_td")))
RUSHING = ("car", (("rush_yds", "rush_yds"), ("rush_td", "rush_td")))

P_LOG_2024 = {"10": 0.343, "11": 0.596, "20": 0.505, "21": 0.801, "31": 0.917}
DEFAULTS = {"H": 8.0, "K_S": 1.0, "K_T": 8.0, "OTHER": 0.0424, "NMU_tgt": 0.590, "NMU_car": 0.519, "REDIST": "v2.0", "P_LOG": None, "B_tgt": None, "B_car": None,
            "K_CR": 80.0, "K_YPT": 160.0, "K_TDT": 160.0, "K_YPC": 160.0, "K_TDC": 320.0}
# Frozen 2026-10-12 from backtest_nfl_player_projection_v2.py --fit (2024 only, 3,298 player-games).
# H, K_T, K_YPT, K_YPC and K_TDC sit on the edge of their pre-registered grids: the true optimum may be beyond.
# P_LOG fitted 2026-10-13 on 2024 (6,319 candidate-games; 2025 alone agrees within 0.04). NOT adopted: on 2025 it
# removed the bias but raised MAE on targets, receptions and receiving yards (pre-registered rule). Use P_LOG_2024.
# NMU_tgt and NMU_car frozen 2026-10-13 from backtest --fit-nmu on 2024 (68 and 58 starter absences).
# Plain proportional would give 0.525 and 0.571; the 2025 cases alone give 0.475 and 0.726, so the split is not stable.


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


class Row(object):
    __slots__ = ("pid", "season", "week", "team", "opp", "game_id", "pos",
                 "tgt", "rec", "rec_yds", "rec_td", "car", "rush_yds", "rush_td")

    def __init__(self, pid, season, week, team, opp, game_id, pos, stats):
        self.pid, self.season, self.week, self.team, self.opp = pid, season, week, team, opp
        self.game_id, self.pos = game_id, pos
        self.tgt = _num(stats.get("targets"))
        self.rec = _num(stats.get("rec"))
        self.rec_yds = _num(stats.get("rec_yds"))
        self.rec_td = _num(stats.get("rec_td"))
        self.car = _num(stats.get("carries"))
        self.rush_yds = _num(stats.get("rush_yds"))
        self.rush_td = _num(stats.get("rush_td"))


def parse_game_id(game_id):
    """'2025_07_LA_NO' -> (2025, 7, 'LA', 'NO') (away, home). nflverse ids, as published."""
    season, week, away, home = game_id.split("_")
    return int(season), int(week), away, home


class History(object):
    """In-memory view of regular-season logs and the final injury report for some seasons."""

    def __init__(self, rows, status):
        self.rows = rows
        self.status = status  # (season, game_id, team) -> {pid: (report_status, played)}
        self.by_player = defaultdict(list)       # (season, pid) -> rows by week
        self.by_team = defaultdict(lambda: defaultdict(list))   # (season, team) -> week -> rows
        self.team_weeks = defaultdict(set)       # (season, team) -> weeks played
        for r in sorted(rows, key=lambda r: (r.season, r.week)):
            self.by_player[(r.season, r.pid)].append(r)
            self.by_team[(r.season, r.team)][r.week].append(r)
            self.team_weeks[(r.season, r.team)].add(r.week)
        self._team_game = {}
        self._memo = {}
        self.margins = {}   # (season, game_id, team) -> SPEC A projected margin (nfl_game_script); empty = none

    @classmethod
    def load(cls, con, seasons):
        pos = {pid: p for pid, p in con.execute("SELECT id, position FROM players WHERE league='nfl'")}
        # The opponent comes from the published schedule row, whose team columns use the same codes as the
        # logs (LAR, WSH). The game id string uses nflverse's (LA, WAS); comparing a log team to it made the
        # Rams and Commanders their own opponent until 2026-10-13.
        sched = {gid: (away, home) for gid, away, home in con.execute(
            "SELECT game_id, away_team, home_team FROM nfl_schedule WHERE season IN (%s)"
            % ",".join("?" * len(seasons)), list(seasons))}
        rows, unplaced = [], []
        for season in seasons:
            for pid, team, game_id, stats in con.execute(
                    "SELECT player_id, team, game_id, stats FROM player_game_logs WHERE league='nfl' "
                    "AND season=? AND source='nflverse_weekly' AND (game_type='REG' OR game_type IS NULL) "
                    "AND team IS NOT NULL AND game_id IS NOT NULL", (season,)):
                if pos.get(pid) not in SKILL:
                    continue
                s_, week, _away, _home = parse_game_id(game_id)
                if week > 18:
                    continue
                away, home = sched.get(game_id, (None, None))
                if team not in (away, home):
                    unplaced.append((game_id, team))
                    continue
                import json
                rows.append(Row(pid, s_, week, team, home if team == away else away, game_id,
                                "RB" if pos[pid] == "FB" else pos[pid], json.loads(stats)))
        if unplaced:
            raise RuntimeError("%d log rows whose team is not in their schedule game, e.g. %s"
                               % (len(unplaced), unplaced[:3]))
        status = defaultdict(dict)
        for season, game_id, team, pid, rep, played in con.execute(
                "SELECT season, game_id, team, player_id, report_status, played FROM player_game_availability "
                "WHERE league='nfl' AND season IN (%s)" % ",".join("?" * len(seasons)), list(seasons)):
            status[(season, game_id, team)][pid] = (rep, played)
        return cls(rows, status)

    # -- team volume -------------------------------------------------------------------------

    def team_game(self, season, team, week, col):
        key = (season, team, week, col)
        if key not in self._team_game:
            self._team_game[key] = sum(getattr(r, col) for r in self.by_team[(season, team)].get(week, ()))
        return self._team_game[key]

    def league_mean(self, season, week, col):
        key = ("lm", season, week, col)
        if key in self._memo:
            return self._memo[key]
        self._memo[key] = self._league_mean(season, week, col)
        return self._memo[key]

    def _league_mean(self, season, week, col):
        tot, n = 0.0, 0
        for (s, team), weeks in self.team_weeks.items():
            if s != season:
                continue
            for w in weeks:
                if w < week:
                    tot += self.team_game(season, team, w, col)
                    n += 1
        return tot / n if n else None

    def team_volume(self, season, team, opp, week, col, k_t):
        league = self.league_mean(season, week, col)
        if league is None:
            return None

        def reg(total, n):
            return (total + k_t * league) / (n + k_t)
        own_w = [w for w in self.team_weeks[(season, team)] if w < week]
        own = reg(sum(self.team_game(season, team, w, col) for w in own_w), len(own_w))
        # allowed: what teams scored/targeted against the opponent, from the opponent's games
        allowed_total, allowed_n = 0.0, 0
        for w in self.team_weeks[(season, opp)]:
            if w >= week:
                continue
            rows = self.by_team[(season, opp)][w]
            other = rows[0].opp if rows else None
            if other is None:
                continue
            allowed_total += self.team_game(season, other, w, col)
            allowed_n += 1
        return 0.5 * own + 0.5 * reg(allowed_total, allowed_n)

    # -- player shares ----------------------------------------------------------------------

    def _pos_mean_share(self, season, week, pos, col):
        key = ("pm", season, week, pos, col)
        if key not in self._memo:
            self._memo[key] = self._pos_mean_share_calc(season, week, pos, col)
        return self._memo[key]

    def _pos_mean_share_calc(self, season, week, pos, col):
        tot, n = 0.0, 0
        for (s, pid), rows in self.by_player.items():
            if s != season:
                continue
            for r in rows:
                if r.pos == pos and r.week < week:
                    team_total = self.team_game(season, r.team, r.week, col)
                    if team_total > 0:
                        tot += getattr(r, col) / team_total
                        n += 1
        return tot / n if n else 0.0

    def _prior_share(self, season, pid, pos, week, col, pos_mean):
        prev = self.by_player.get((season - 1, pid), [])
        if len(prev) >= PRIOR_MIN_GAMES:
            tot = sum(getattr(r, col) for r in prev)
            team = sum(self.team_game(season - 1, r.team, r.week, col) for r in prev)
            if team > 0:
                return tot / team
        return pos_mean

    def raw_share(self, season, pid, pos, week, col, p, pos_mean_cache):
        """Season-to-date recency-weighted share regressed to the prior. None if no prior games."""
        rows = [r for r in self.by_player.get((season, pid), []) if r.week < week]
        pm = self._pos_mean_share(season, week, pos, col)
        prior = self._prior_share(season, pid, pos, week, col, pm)
        num, den = 0.0, 0.0
        for r in rows:
            team_total = self.team_game(season, r.team, r.week, col)
            if team_total <= 0:
                continue
            w = 0.5 ** ((week - 1 - r.week) / p["H"])
            num += w * getattr(r, col) / team_total
            den += w
        if den + p["K_S"] <= 0:
            return 0.0, len(rows)
        return (num + p["K_S"] * prior) / (den + p["K_S"]), len(rows)

    def candidates(self, season, team, week):
        """Players who logged for the team in its last LAST_GAMES games before `week`."""
        weeks = sorted(w for w in self.team_weeks[(season, team)] if w < week)[-LAST_GAMES:]
        seen = {}
        for w in weeks:
            for r in self.by_team[(season, team)][w]:
                seen[r.pid] = r.pos
        return seen

    def recent_form(self, season, team, week, pid):
        """(k, last): how many of the team's last LAST_GAMES games before `week` `pid` logged in, and
        whether he logged in the most recent one."""
        weeks = sorted(w for w in self.team_weeks[(season, team)] if w < week)[-LAST_GAMES:]
        logged = [any(r.pid == pid for r in self.by_team[(season, team)][w]) for w in weeks]
        return sum(logged), bool(logged and logged[-1])

    def p_log(self, season, team, week, pid, table):
        """Fitted chance a candidate appears in the box score of the target game, from recent_form.

        P_LOG is PRE-REGISTERED 2026-10-13: for every candidate not removed by the report, in 2024 team-games
        weeks 3 to 18, the share who logged in the target game, by (k, last). Fitted by backtest --fit-plog,
        frozen in DEFAULTS before the 2025 run. Gate: adopted only if on 2025 weeks 3 to 18 the paired MAE of
        targets, receptions and receiving yards are each no higher than the engine without it (1.562, 1.207,
        15.849 on the dev DB copied 2026-10-13) and the Spec B 5 gate still passes."""
        k, last = self.recent_form(season, team, week, pid)
        return table.get("%d%d" % (k, int(last)), 1.0)

    def out_before(self, season, game_id, team):
        return {pid for pid, (rep, _p) in self.status.get((season, game_id, team), {}).items()
                if rep in OUT_STATUSES}

    def observed_without(self, season, week, team, pid, col, out):
        """Shares of team `col` in games this season (before `week`) or last season in which `pid`
        played for `team` and every player in `out` had played = 0."""
        observed = []
        for s in (season - 1, season):
            for r in self.by_player.get((s, pid), []):
                if r.team != team or (s == season and r.week >= week):
                    continue
                st = self.status.get((s, r.game_id, r.team), {})
                if all(st.get(x, (None, None))[1] == 0 for x in out):
                    tt = self.team_game(s, r.team, r.week, col)
                    if tt > 0:
                        observed.append(getattr(r, col) / tt)
        return observed

    def team_shares(self, season, week, team, col, p, game_id, keep=None, keep_pos=None):
        """Projected share of team `col` for every available candidate, and the rule behind each.

        Spec B 4.3, PRE-REGISTERED 2026-10-13 before the 2025 run:
          base     each candidate's raw_share, the Out/Doubtful ones included (the world where all play).
          rule 1   'observed': an available player with MIN_TOGETHER or more games this season or last
                   in which every removed teammate had played = 0 takes his mean share in those games.
          rule 2   the removed players' base shares are freed per position group (RB with FB, WR, TE,
                   QB). Within a group, the remaining player with the highest base share not on rule 1
                   is the next man up and takes NMU_<col> of the group's freed share; the rest goes to the
                   group's other rule-2 players in proportion to base ('next_man_up' / 'group').
                   A group with no rule-2 player left frees its share to every rule-2 player in
                   proportion to base ('proportional'). With nobody removed the rule is 'none_out'.
          last     shares of the available candidates are scaled to sum to 1 - OTHER.
        `keep` is projected as available even if the report lists him (shares are conditional on
        playing). Returns ({pid: share}, {pid: rule}); empty when there is no basis.
        """
        cands = self.candidates(season, team, week)
        if keep is not None:
            cands.setdefault(keep, keep_pos)
        out = self.out_before(season, game_id, team) - {keep}
        base = {j: self.raw_share(season, j, jpos, week, col, p, None)[0] for j, jpos in cands.items()}
        avail = [j for j in cands if j not in out]
        removed = [j for j in cands if j in out]
        if not removed:
            pre = {j: base[j] for j in avail}
            rules = {j: "none_out" for j in avail}
        else:
            pre, rules = {}, {}
            for j in avail:
                obs = self.observed_without(season, week, team, j, col, removed)
                if len(obs) >= MIN_TOGETHER:
                    pre[j], rules[j] = sum(obs) / len(obs), "observed"
            rest = [j for j in avail if j not in pre]
            for j in rest:
                pre[j], rules[j] = base[j], "proportional"
            spill = 0.0
            for g in sorted({cands[x] for x in removed}):
                freed = sum(base[x] for x in removed if cands[x] == g)
                group = sorted((j for j in rest if cands[j] == g), key=lambda j: (-base[j], j))
                if not group:
                    spill += freed
                    continue
                nmu, others = group[0], group[1:]
                o_tot = sum(base[j] for j in others)
                if not others or o_tot <= 0:
                    pre[nmu] += freed
                else:
                    pre[nmu] += p["NMU_" + col] * freed
                    for j in others:
                        pre[j] += (1.0 - p["NMU_" + col]) * freed * base[j] / o_tot
                        rules[j] = "group"
                rules[nmu] = "next_man_up"
            r_tot = sum(base[j] for j in rest)
            if spill > 0 and r_tot > 0:
                for j in rest:
                    pre[j] += spill * base[j] / r_tot
        total = sum(pre.values())
        if total <= 0:
            return {}, {}
        return {j: v * (1.0 - p["OTHER"]) / total for j, v in pre.items()}, rules

    def share_v20(self, season, week, team, pid, pos, col, p, game_id, caches):
        """The 2026-10-12 rule (REDIST 'v2.0'): removed players' share spread over every candidate in
        proportion, observed share blended at n / (n + MIN_TOGETHER). (share, rule) or None."""
        cands = self.candidates(season, team, week)
        cands.setdefault(pid, pos)
        out = self.out_before(season, game_id, team) - {pid}
        raw = {}
        for j, jpos in cands.items():
            if j in out:
                continue
            val = self.raw_share(season, j, jpos, week, col, p, caches)
            raw[j] = val[0]
        if p.get("P_LOG"):
            # Bias fix, PRE-REGISTERED 2026-10-13 (see recent_form / P_LOG): the projection is conditional
            # on `pid` playing, so he counts in full; every other candidate counts at his fitted chance
            # of appearing in the box score, so share is not handed to players who will not play.
            total = sum(v * (1.0 if j == pid else self.p_log(season, team, week, j, p["P_LOG"]))
                        for j, v in raw.items())
        else:
            total = sum(raw.values())
        if total <= 0 or pid not in raw:
            return None
        share = raw[pid] * (1.0 - p["OTHER"]) / total
        rule = "proportional" if out else "none_out"
        if out:
            observed = []
            for r in self.by_player.get((season, pid), []):
                if r.week >= week:
                    continue
                st = self.status.get((season, r.game_id, r.team), {})
                if all(st.get(x, (None, None))[1] == 0 for x in out):
                    tt = self.team_game(season, r.team, r.week, col)
                    if tt > 0:
                        observed.append(getattr(r, col) / tt)
            if len(observed) >= MIN_TOGETHER:
                n = len(observed)
                wgt = n / (n + MIN_TOGETHER)
                share = wgt * (sum(observed) / n) + (1 - wgt) * share
                rule = "observed_blend"
        return share, rule

    def share(self, season, week, team, pid, pos, col, p, game_id, caches):
        """(projected share of the team's `col`, rule used) or None if there is no basis.

        REDIST 'v2.0' (default) is the 2026-10-12 rule; '4.3' is team_shares. On 2025 weeks 3 to 18
        (3,945 player-games, dev DB 2026-10-13) '4.3' had higher MAE than 'v2.0' on targets (1.590 vs
        1.567), receptions (1.225 vs 1.209) and receiving yards (15.910 vs 15.832), so it is not the default.
        """
        if p.get("REDIST", "v2.0") == "v2.0":
            return self.share_v20(season, week, team, pid, pos, col, p, game_id, caches)
        shares, rules = self.team_shares(season, week, team, col, p, game_id, keep=pid, keep_pos=pos)
        if pid not in shares:
            return None
        return shares[pid], rules[pid]

    # -- efficiency -------------------------------------------------------------------------

    def pos_rates(self, season, week, pos, opp_col, stat_col):
        key = ("pr", season, week, pos, opp_col, stat_col)
        if key not in self._memo:
            self._memo[key] = self._pos_rates_calc(season, week, pos, opp_col, stat_col)
        return self._memo[key]

    def _pos_rates_calc(self, season, week, pos, opp_col, stat_col):
        tot_s, tot_o = 0.0, 0.0
        for s in (season - 1, season):
            for (ss, _pid), rows in self.by_player.items():
                if ss != s:
                    continue
                for r in rows:
                    if r.pos == pos and (s < season or r.week < week):
                        tot_s += getattr(r, stat_col)
                        tot_o += getattr(r, opp_col)
        return tot_s / tot_o if tot_o else 0.0

    def eff(self, season, week, pid, pos, opp_col, stat_col, k, rate_cache):
        base = self.pos_rates(season, week, pos, opp_col, stat_col)
        s_tot = o_tot = 0.0
        for s in (season - 1, season):
            for r in self.by_player.get((s, pid), []):
                if s < season or r.week < week:
                    s_tot += getattr(r, stat_col)
                    o_tot += getattr(r, opp_col)
        return (s_tot + k * base) / (o_tot + k)


def opportunities(hist, season, week, pid, pos, team, opp, game_id, opp_col, p, caches=None):
    """Projected targets (opp_col 'tgt') or carries ('car') and the redistribution rule used, or None."""
    vol = hist.team_volume(season, team, opp, week, opp_col, p["K_T"])
    sh = hist.share(season, week, team, pid, pos, opp_col, p, game_id, caches if caches is not None else {})
    if vol is None or sh is None:
        return None
    return vol * script_factor(hist, season, game_id, team, opp_col, p) * sh[0], sh[1]


def script_factor(hist, season, game_id, team, col, p):
    """Spec B 4.1 game script, rule pre-registered in nfl_game_script.py: clamp(1 + B_col * margin)."""
    b = p.get("B_" + col)
    margin = hist.margins.get((season, game_id, team))
    if b is None or margin is None:
        return 1.0
    return min(1.25, max(0.75, 1.0 + b * margin))


_EFF_K = {"rec": "K_CR", "rec_yds": "K_YPT", "rec_td": "K_TDT", "rush_yds": "K_YPC", "rush_td": "K_TDC"}


def project(hist, season, week, pid, pos, team, opp, game_id, p=None):
    """Version 2 stat line for one player-game given he plays, or None without a basis.

    Returns {stat: mean, ..., '_rules': {...}}. Only games before `week` and the pregame injury report
    for the target game are read.
    """
    p = dict(DEFAULTS, **(p or {}))
    out, rules, caches = {}, {}, {}
    for opp_col, stats in (RECEIVING, RUSHING):
        got = opportunities(hist, season, week, pid, pos, team, opp, game_id, opp_col, p, caches)
        if got is None:
            continue
        opps, rules[opp_col] = got
        out[opp_col] = opps
        for stat_col, name in stats:
            out[name] = opps * hist.eff(season, week, pid, pos, opp_col, stat_col, p[_EFF_K[name]], None)
    if "tgt" not in out and "car" not in out:
        return None
    out["_rules"] = rules
    return out


def marcel(hist, season, week, pid, col, both_seasons=False):
    """Marcel-lite exactly as the live route: analytics.projections.project_stat, newest first."""
    from analytics.projections import project_stat
    rows = [r for r in hist.by_player.get((season, pid), []) if r.week < week]
    if both_seasons:
        rows = list(hist.by_player.get((season - 1, pid), [])) + rows
    vals = [getattr(r, col) for r in reversed(rows)]
    res = project_stat(vals)
    return res["projection"] if res else None


# -- distribution (Spec B 4.5) ---------------------------------------------------------------------
# PRE-REGISTERED 2026-10-12 before any 2025 coverage was computed. For a receiver with projected mean
# targets T, catch rate c, yards per reception y and TD per target d:
#   targets ~ NegBin(mean T, dispersion R)         var = T + T^2 / R
#   receptions ~ Binomial(targets, c)
#   yards = sum over receptions of Gamma(mean y, shape G)
#   receiving TDs ~ Binomial(targets, d)
# R and G are fitted on 2024 by method of moments (backtest_nfl_player_projection_v2.py --fit-dist) and
# frozen in DIST. Graded on 2025 by the share of actual values inside the simulated p10 to p90 band
# (target 80%) and the share below p10 and above p90 (target 10% each).
DIST = {"R": 3.41, "G": 1.23}   # frozen from --fit-dist on 2024


def simulate(mean_tgt, catch, yards_per_rec, td_per_tgt, n=2000, seed=0, dist=None):
    """n simulated (receptions, yards, tds, targets) draws for one player-game."""
    dist = dict(DIST, **(dist or {}))
    rng = random.Random(seed)
    out = []
    r = dist["R"]
    for _ in range(n):
        # NB as a gamma-Poisson mixture
        lam = rng.gammavariate(r, mean_tgt / r) if mean_tgt > 0 else 0.0
        t = _poisson(rng, lam)
        rec = sum(1 for _ in range(t) if rng.random() < catch)
        yds = sum(rng.gammavariate(dist["G"], yards_per_rec / dist["G"]) for _ in range(rec)) if yards_per_rec > 0 else 0.0
        td = sum(1 for _ in range(t) if rng.random() < td_per_tgt)
        out.append((rec, yds, td, t))
    return out


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, prod = math.exp(-lam), 0, 1.0
    while True:
        prod *= rng.random()
        if prod <= limit:
            return k
        k += 1


def quantile(sorted_vals, q):
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def summarize(draws, index, line=None):
    vals = sorted(d[index] for d in draws)
    res = {"mean": sum(vals) / len(vals), "median": quantile(vals, 0.5),
           "p10": quantile(vals, 0.1), "p90": quantile(vals, 0.9)}
    if line is not None:
        res["p_over"] = sum(1 for v in vals if v > line) / len(vals)
    return res
