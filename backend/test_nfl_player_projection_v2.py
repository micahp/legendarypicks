"""Hand-computed fixtures for nfl_player_projection_v2. Parameters are set so no shrinkage applies
(huge half-life, zero pseudo-games), which makes every expected value arithmetic you can do on paper."""
import unittest

import nfl_player_projection_v2 as mod

P = {"H": 1e9, "K_S": 0.0, "K_T": 0.0, "OTHER": 0.0,
     "K_CR": 0.0, "K_YPT": 0.0, "K_TDT": 0.0, "K_YPC": 0.0, "K_TDC": 0.0,
     "NMU_tgt": 0.6, "NMU_car": 0.6, "REDIST": "4.3", "P_LOG": None}
P20 = dict(P, REDIST="v2.0")   # the default rule, 2026-10-12


def gid(week):
    return "2025_%02d_A_B" % week


def row(pid, week, tgt, rec=0, yds=0, team="A", pos="WR"):
    opp = "B" if team == "A" else "A"
    return mod.Row(pid, 2025, week, team, opp, gid(week), pos,
                   {"targets": tgt, "rec": rec, "rec_yds": yds, "rec_td": 0})


def build(rows, status=None):
    return mod.History(rows, status or {})


class Projection(unittest.TestCase):
    def two_receiver_team(self):
        rows = []
        for w, (t1, t2) in enumerate([(5, 5), (10, 10), (15, 15)], start=1):
            rows.append(row(1, w, t1, rec=int(t1 * 0.6), yds=t1 * 6))
            rows.append(row(2, w, t2, rec=int(t2 * 0.6), yds=t2 * 6))
            rows.append(row(9, w, 10, team="B"))   # the opponent's own target volume
        return rows

    def test_volume_share_efficiency_multiply(self):
        hist = build(self.two_receiver_team())
        res = mod.project(hist, 2025, 4, 1, "WR", "A", "B", gid(4), P)
        # team targets 20/game (own 20, opponent allows 20); share 0.5; 6 yards and 0.6 catches per target
        self.assertAlmostEqual(10.0, res["tgt"])
        self.assertAlmostEqual(6.0, res["rec"])
        self.assertAlmostEqual(60.0, res["rec_yds"])

    def test_the_target_week_and_later_never_enter(self):
        rows = self.two_receiver_team()
        base = mod.project(build(rows), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        rows += [row(1, 4, 500, rec=500, yds=5000), row(2, 4, 1, team="A")]
        same = mod.project(build(rows), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        self.assertEqual(base, same)

    def test_no_earlier_game_means_no_projection(self):
        self.assertIsNone(mod.project(build(self.two_receiver_team()), 2025, 1, 1, "WR", "A", "B",
                                      gid(1), P))

    def test_out_teammate_share_goes_to_the_next_man_up_in_his_group(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 3), row(3, w, 2), row(9, w, 10, team="B")]
        status = {(2025, gid(4), "A"): {3: ("Out", None)}}
        hist = build(rows, status)
        res = mod.project(hist, 2025, 4, 1, "WR", "A", "B", gid(4), P)
        # shares .5 .3 .2, the .2 WR out: next man up (player 1) takes .6 of it, player 2 the other .4
        self.assertAlmostEqual(10 * (0.5 + 0.6 * 0.2), res["tgt"])
        self.assertEqual("next_man_up", res["_rules"]["tgt"])
        other = mod.project(hist, 2025, 4, 2, "WR", "A", "B", gid(4), P)
        self.assertAlmostEqual(10 * (0.3 + 0.4 * 0.2), other["tgt"])
        self.assertEqual("group", other["_rules"]["tgt"])

    def test_questionable_teammate_is_not_removed(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 3), row(3, w, 2), row(9, w, 10, team="B")]
        status = {(2025, gid(4), "A"): {3: ("Questionable", None)}}
        res = mod.project(build(rows, status), 2025, 4, 1, "WR", "A", "B", gid(4), P)
        self.assertAlmostEqual(5.0, res["tgt"])
        self.assertEqual("none_out", res["_rules"]["tgt"])

    def test_three_games_together_without_him_use_the_observed_share(self):
        rows, status = [], {}
        for w in (1, 2, 3):          # player 2 out: shares .6 and .4
            rows += [row(1, w, 6), row(3, w, 4), row(9, w, 10, team="B")]
            status[(2025, gid(w), "A")] = {2: ("Out", 0)}
        for w in (4, 5, 6):          # player 2 back: .4 .4 .2
            rows += [row(1, w, 4), row(2, w, 4), row(3, w, 2), row(9, w, 10, team="B")]
        status[(2025, gid(7), "A")] = {2: ("Out", None)}
        res = mod.project(build(rows, status), 2025, 7, 1, "WR", "A", "B", gid(7), P)
        # both remaining players have 3 games without player 2: observed .6 and .4, already summing to 1
        self.assertAlmostEqual(6.0, res["tgt"])
        self.assertEqual("observed", res["_rules"]["tgt"])

    def test_last_season_games_together_count(self):
        rows, status = [], {}
        for w in (1, 2, 3):          # 2024: player 2 out, player 1 took .7
            rows.append(mod.Row(1, 2024, w, "A", "B", "2024_%02d_A_B" % w, "WR",
                                {"targets": 7, "rec": 0, "rec_yds": 0, "rec_td": 0}))
            rows.append(mod.Row(3, 2024, w, "A", "B", "2024_%02d_A_B" % w, "WR",
                                {"targets": 3, "rec": 0, "rec_yds": 0, "rec_td": 0}))
            status[(2024, "2024_%02d_A_B" % w, "A")] = {2: ("Out", 0)}
        for w in (1, 2, 3):
            rows += [row(1, w, 4), row(2, w, 4), row(3, w, 2), row(9, w, 10, team="B")]
        status[(2025, gid(4), "A")] = {2: ("Out", None)}
        shares, rules = build(rows, status).team_shares(2025, 4, "A", "tgt", P, gid(4))
        self.assertEqual({1: "observed", 3: "observed"}, rules)
        self.assertAlmostEqual(0.7, shares[1])

    def test_a_group_with_nobody_left_spreads_in_proportion(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 3), row(3, w, 2, pos="TE"), row(9, w, 10, team="B")]
        status = {(2025, gid(4), "A"): {3: ("Out", None)}}
        shares, rules = build(rows, status).team_shares(2025, 4, "A", "tgt", P, gid(4))
        self.assertAlmostEqual(0.5 / 0.8, shares[1])
        self.assertAlmostEqual(0.3 / 0.8, shares[2])
        self.assertEqual({1: "proportional", 2: "proportional"}, rules)

    def test_shares_sum_to_one_minus_other_for_every_rule_mix(self):
        rows, status = [], {}
        q = dict(P, OTHER=0.1, NMU_tgt=0.75)
        for w in (1, 2, 3):          # players 1 and 4 out: 2, 5 and 6 get 3 games without both
            rows += [row(2, w, 5), row(5, w, 3, pos="TE"), row(6, w, 2, pos="RB"), row(9, w, 10, team="B")]
            status[(2025, gid(w), "A")] = {1: ("Out", 0), 4: ("Out", 0)}
        for w in (4, 5):
            rows += [row(1, w, 6), row(2, w, 3), row(3, w, 2), row(4, w, 4, pos="TE"),
                     row(5, w, 1, pos="TE"), row(6, w, 1, pos="RB"), row(9, w, 10, team="B")]
        status[(2025, gid(6), "A")] = {1: ("Out", None), 4: ("Doubtful", None)}
        shares, rules = build(rows, status).team_shares(2025, 6, "A", "tgt", q, gid(6))
        # player 3 (WR, no games without them) is the only rule-2 player: next man up for the WR share,
        # and he also takes the TE share because TE 5 is on rule 1
        self.assertEqual({2: "observed", 3: "next_man_up", 5: "observed", 6: "observed"}, rules)
        self.assertAlmostEqual(0.9, sum(shares.values()))


class DefaultRedistribution(unittest.TestCase):
    two_receiver_team = Projection.two_receiver_team

    def test_out_teammate_is_removed_and_the_rest_renormalised(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 3), row(3, w, 2), row(9, w, 10, team="B")]
        status = {(2025, gid(4), "A"): {3: ("Out", None)}}
        res = mod.project(build(rows, status), 2025, 4, 1, "WR", "A", "B", gid(4), P20)
        # shares .5 .3 .2 with the .2 player out: .5 / .8 of 10 team targets
        self.assertAlmostEqual(10 * 0.5 / 0.8, res["tgt"])
        self.assertEqual("proportional", res["_rules"]["tgt"])

    def test_three_games_together_without_him_blend_the_observed_share(self):
        rows, status = [], {}
        for w in (1, 2, 3):          # player 2 out: shares .6 and .4
            rows += [row(1, w, 6), row(3, w, 4), row(9, w, 10, team="B")]
            status[(2025, gid(w), "A")] = {2: ("Out", 0)}
        for w in (4, 5, 6):          # player 2 back: .4 .4 .2
            rows += [row(1, w, 4), row(2, w, 4), row(3, w, 2), row(9, w, 10, team="B")]
        status[(2025, gid(7), "A")] = {2: ("Out", None)}
        res = mod.project(build(rows, status), 2025, 7, 1, "WR", "A", "B", gid(7), P20)
        # raw shares: p1 .5, p3 .3 -> proportional .625; observed .6 over n=3 -> weight .5 -> .6125
        self.assertAlmostEqual(10 * 0.6125, res["tgt"])
        self.assertEqual("observed_blend", res["_rules"]["tgt"])

    def test_default_is_v20(self):
        self.assertEqual("v2.0", mod.DEFAULTS["REDIST"])


class PLog(unittest.TestCase):
    def test_a_candidate_who_stopped_logging_counts_at_his_fitted_chance(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(9, w, 10, team="B")]
            if w == 1:
                rows.append(row(2, w, 5))          # player 2 logged week 1 only: k=1, last=0
        hist = build(rows)
        self.assertEqual((1, False), hist.recent_form(2025, "A", 4, 2))
        self.assertEqual((3, True), hist.recent_form(2025, "A", 4, 1))
        q = dict(P, REDIST="v2.0", P_LOG={"10": 0.2, "31": 0.95})
        res = mod.project(hist, 2025, 4, 1, "WR", "A", "B", gid(4), q)
        # raw shares over games played: p1 .5, 1, 1 -> .8333; p2 .5 in his one game
        s1, s2 = (0.5 + 1 + 1) / 3, 0.5
        team = (10 + 5 + 5) / 3                            # own and allowed are both A's 10, 5, 5
        self.assertAlmostEqual(team * s1 / (s1 + 0.2 * s2), res["tgt"])
        plain = mod.project(hist, 2025, 4, 1, "WR", "A", "B", gid(4), dict(q, P_LOG=None))
        self.assertAlmostEqual(team * s1 / (s1 + s2), plain["tgt"])

    def test_the_projected_player_counts_in_full(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 5), row(9, w, 10, team="B")]
        hist = build(rows)
        q = dict(P, REDIST="v2.0", P_LOG={"31": 0.5})
        res = mod.project(hist, 2025, 4, 1, "WR", "A", "B", gid(4), q)
        # p1 counts 1, p2 counts .5: share .5 / (.5 + .25)
        self.assertAlmostEqual(10 * 0.5 / 0.75, res["tgt"])


class GameScript(unittest.TestCase):
    def hist(self):
        rows = []
        for w in (1, 2, 3):
            rows += [row(1, w, 5), row(2, w, 5), row(9, w, 10, team="B")]
        return build(rows)

    def test_margin_scales_team_volume_by_the_fitted_slope(self):
        h = self.hist()
        h.margins[(2025, gid(4), "A")] = 7.0
        q = dict(P, REDIST="v2.0", B_tgt=-0.01)
        res = mod.project(h, 2025, 4, 1, "WR", "A", "B", gid(4), q)
        self.assertAlmostEqual(10 * 0.5 * (1 - 0.07), res["tgt"])   # a favourite throws less

    def test_factor_is_clamped_and_off_without_a_margin_or_slope(self):
        h = self.hist()
        h.margins[(2025, gid(4), "A")] = 40.0
        self.assertEqual(0.75, mod.script_factor(h, 2025, gid(4), "A", "tgt", {"B_tgt": -0.05}))
        self.assertEqual(1.25, mod.script_factor(h, 2025, gid(4), "A", "car", {"B_car": 0.05}))
        self.assertEqual(1.0, mod.script_factor(h, 2025, gid(4), "A", "tgt", {"B_tgt": None}))
        self.assertEqual(1.0, mod.script_factor(h, 2025, gid(5), "A", "tgt", {"B_tgt": -0.05}))


class Quarterback(unittest.TestCase):
    def qb_row(self, pid, week, att, cmp_, yds, td, team="A"):
        opp = "B" if team == "A" else "A"
        return mod.Row(pid, 2025, week, team, opp, gid(week), "QB",
                       {"att": att, "cmp": cmp_, "pass_yds": yds, "pass_td": td})

    def test_attempts_times_rates_and_a_backup_does_not_shrink_the_starter(self):
        rows = []
        for w in (1, 2, 3):
            rows += [self.qb_row(1, w, 30, 20, 210, 3), self.qb_row(9, w, 30, 0, 0, 0, team="B")]
        rows.append(self.qb_row(2, 3, 10, 5, 40, 0))        # backup mop-up in week 3: 40 team attempts
        q = dict(P, K_CMP=0.0, K_YPA=0.0, K_PTD=0.0)
        res = mod.project_qb(build(rows), 2025, 4, 1, "A", "B", gid(4), q)
        team_att = (30 + 30 + 40) / 3                      # own and allowed are both A's 30, 30, 40
        share = (1 + 1 + 0.75) / 3
        self.assertAlmostEqual(team_att * share, res["att"])
        self.assertAlmostEqual(res["att"] * 60 / 90, res["cmp"])
        self.assertAlmostEqual(res["att"] * 630 / 90, res["pass_yds"])
        self.assertAlmostEqual(res["att"] * 9 / 90, res["pass_td"])

    def test_no_earlier_game_no_projection(self):
        rows = [self.qb_row(1, 1, 30, 20, 210, 3), self.qb_row(9, 1, 30, 0, 0, 0, team="B")]
        q = dict(P, K_CMP=0.0, K_YPA=0.0, K_PTD=0.0)
        self.assertIsNone(mod.project_qb(build(rows), 2025, 4, 2, "A", "B", gid(4), q))

    def test_simulated_qb_means_are_near_the_inputs(self):
        draws = mod.simulate_qb(32.0, 0.65, 11.0, 0.045, n=4000, seed=3, dist={"R_ATT": 20.0, "G_PASS": 1.5})
        mean = lambda i: sum(d[i] for d in draws) / len(draws)
        self.assertAlmostEqual(32.0, mean(3), delta=0.6)
        self.assertAlmostEqual(32.0 * 0.65, mean(0), delta=0.5)
        self.assertAlmostEqual(32.0 * 0.65 * 11.0, mean(1), delta=6.0)


class Load(unittest.TestCase):
    """History.load against a real-shaped database: schedule teams are LAR and WSH, the game id says LA."""

    def db(self, schedule_away="LAR"):
        import json
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.executescript("""
            CREATE TABLE players(id INTEGER, league TEXT, position TEXT);
            CREATE TABLE player_game_logs(player_id INTEGER, league TEXT, season INTEGER, team TEXT,
                game_id TEXT, stats TEXT, source TEXT, game_type TEXT);
            CREATE TABLE nfl_schedule(game_id TEXT, season INTEGER, away_team TEXT, home_team TEXT);
            CREATE TABLE player_game_availability(league TEXT, season INTEGER, game_id TEXT, team TEXT,
                player_id INTEGER, report_status TEXT, played INTEGER);
        """)
        con.execute("INSERT INTO players VALUES (1,'nfl','WR'), (2,'nfl','WR')")
        con.execute("INSERT INTO nfl_schedule VALUES ('2025_01_LA_NO',2025,?,'NO')", (schedule_away,))
        for pid, team in ((1, "LAR"), (2, "NO")):
            con.execute("INSERT INTO player_game_logs VALUES (?,'nfl',2025,?,'2025_01_LA_NO',?,"
                        "'nflverse_weekly','REG')", (pid, team, json.dumps({"targets": 5})))
        return con

    def test_the_rams_opponent_is_the_saints_not_themselves(self):
        hist = mod.History.load(self.db(), [2025])
        by = {r.pid: r for r in hist.rows}
        self.assertEqual("NO", by[1].opp)
        self.assertEqual("LAR", by[2].opp)
        # the Saints' defence allowed the Rams' 5 targets, not a 0-target game against "LA"
        self.assertEqual(5, hist.team_game(2025, by[2].opp, 1, "tgt"))

    def test_a_log_team_missing_from_its_game_raises(self):
        with self.assertRaises(RuntimeError):
            mod.History.load(self.db(schedule_away="ARI"), [2025])


class Marcel(unittest.TestCase):
    def test_marcel_is_the_live_route_on_earlier_games(self):
        rows = [row(1, w, 5, rec=w, yds=10 * w) for w in range(1, 6)]
        hist = build(rows)
        # newest first: 40 30 20 10 ... project_stat = .5*l5avg + .3*l10avg + .2*avg over the 4 earlier games
        vals = [40, 30, 20, 10]
        avg = sum(vals) / 4
        self.assertAlmostEqual(round(0.5 * avg + 0.3 * avg + 0.2 * avg, 2),
                               mod.marcel(hist, 2025, 5, 1, "rec_yds"))

    def test_marcel_needs_three_games(self):
        hist = build([row(1, 1, 5), row(1, 2, 5)])
        self.assertIsNone(mod.marcel(hist, 2025, 3, 1, "rec_yds"))


if __name__ == "__main__":
    unittest.main()
