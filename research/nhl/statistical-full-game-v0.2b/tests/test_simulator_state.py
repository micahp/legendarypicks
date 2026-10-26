"""Focused tests for live-state checks and goalie response."""

import sys
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nhl_game_state_sim as sim


def player_totals():
    result={}
    for side,prefix,goalie in (("home","H","HG"),("away","A","AG")):
        for number in range(1,7):
            pid=f"{prefix}{number}"
            result[pid]={"team_side":side,"position":"F"}
        result[goalie]={"team_side":side,"position":"G"}
    return result


def event(event_type, elapsed, *, home, away, strength, details, side=None, participants=None):
    return {"event_type":event_type,"period_number":1,"period_type":"REG",
            "clock_elapsed_seconds":elapsed,"team_side":side,"strength":strength,"sequence":1,
            "details":details,"participants":participants or {},
            "on_ice":{"home":home,"away":away}}


class GoalieResponseTests(unittest.TestCase):
    def test_better_save_rate_lowers_even_strength_goal_probability(self):
        raw_logit=sim._logit(.10)
        weak=sim._sigmoid(raw_logit+sim._goalie_logit_delta(.900,.095))
        strong=sim._sigmoid(raw_logit+sim._goalie_logit_delta(.940,.095))
        self.assertLess(strong,weak)

    def test_better_save_rate_lowers_shootout_goal_probability(self):
        class Model:
            shootout_goal_rate=.32
            global_goal_rate=.095
        weak=sim._shootout_goal_probability(.10,.900,Model())
        strong=sim._shootout_goal_probability(.10,.940,Model())
        self.assertLess(strong,weak)


class EventTransitionTests(unittest.TestCase):
    def test_live_strength_changes_event_family_distribution(self):
        model=sim.EventTransitionModel(
            exact={"start|KNOWN|PP|TIED":Counter({"shot":25}),
                   "start|KNOWN|PK|TIED":Counter({"stoppage":25})},
            previous_possession={},previous={},global_families=Counter({"shot":25,"stoppage":25}),
            owner_exact={"start|KNOWN|PP|TIED|shot":Counter({"same":25})},
            owner_family={},penalty_types=Counter(),eligible_games=2,training_events=50,
            source_manifest_sha256="fixture",model_sha256="fixture")
        offense=("start","KNOWN","PP","TIED")
        defense=("start","KNOWN","PK","TIED")
        self.assertEqual(model.sample_family(offense,sim.random.Random(7))[0],"shot")
        self.assertEqual(model.sample_family(defense,sim.random.Random(7))[0],"stoppage")
        self.assertEqual(model.sample_owner("shot",offense,"home","away",
                                            sim.random.Random(7))[0],"home")


class LivePenaltyValidationTests(unittest.TestCase):
    def setUp(self):
        self.players=player_totals()
        self.home_before=[f"H{i}" for i in range(1,6)]+["HG"]
        self.away=[f"A{i}" for i in range(1,6)]+["AG"]

    def test_penalized_player_is_removed_until_exact_expiry(self):
        home_short=["H2","H3","H4","H5","HG"]
        home_full=["H1","H2","H3","H4","H5","HG"]
        events=[
            event("penalty",100,home=self.home_before,away=self.away,strength="5v5",
                  details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                           "coincidental":False,"goalie_pulled":{"home":False,"away":False}},
                  side="home",participants={"penalized_player_id":"H1","serving_player_id":"H1"}),
            event("faceoff",100,home=home_short,away=self.away,strength="4v5",
                  details={"goalie_pulled":{"home":False,"away":False}},side="away"),
            event("penalty-expiration",220,home=home_full,away=self.away,strength="5v5",
                  details={"goalie_pulled":{"home":False,"away":False}},side="home",
                  participants={"player_id":"H1"}),
        ]
        sim._validate_live_game_state(events,self.players)

    def test_validator_rejects_penalized_player_left_on_ice(self):
        events=[
            event("penalty",100,home=self.home_before,away=self.away,strength="5v5",
                  details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                           "coincidental":False,"goalie_pulled":{"home":False,"away":False}},
                  side="home",participants={"penalized_player_id":"H1","serving_player_id":"H1"}),
            event("faceoff",101,home=self.home_before,away=self.away,strength="5v5",
                  details={"goalie_pulled":{"home":False,"away":False}},side="home"),
        ]
        with self.assertRaisesRegex(ValueError,"remains on ice"):
            sim._validate_live_game_state(events,self.players)


class ShootoutValidationTests(unittest.TestCase):
    def test_shootout_stops_at_first_decisive_attempt(self):
        events=[]
        for side,result in (("home","goal"),("away","saved"),
                            ("home","goal"),("away","missed")):
            events.append({"event_type":"shootout-attempt","team_side":side,
                           "details":{"attempt_result":result}})
        events.append({"event_type":"shootout-decision","team_side":"home"})
        sim._validate_shootout_sequence(events,{"shootout_winner":"home"})

    def test_shootout_rejects_attempt_after_clinch(self):
        events=[]
        for side,result in (("home","goal"),("away","saved"),
                            ("home","goal"),("away","missed"),
                            ("home","goal"),("away","goal")):
            events.append({"event_type":"shootout-attempt","team_side":side,
                           "details":{"attempt_result":result}})
        events.append({"event_type":"shootout-decision","team_side":"home"})
        with self.assertRaisesRegex(ValueError,"continued after"):
            sim._validate_shootout_sequence(events,{"shootout_winner":"home"})


class RestartGenerationTests(unittest.TestCase):
    def test_required_restart_is_accounted_and_updates_live_possession(self):
        home_center=SimpleNamespace(nhl_id="HC",position="C",faceoff_pct=.65,usage_minutes=18)
        away_center=SimpleNamespace(nhl_id="AC",position="C",faceoff_pct=.45,usage_minutes=18)
        inputs=SimpleNamespace(
            home_roster=SimpleNamespace(players={"HC":home_center}),
            away_roster=SimpleNamespace(players={"AC":away_center}))
        players={pid:{"faceoffs_taken":0,"faceoffs_won":0,"faceoffs_lost":0}
                 for pid in ("HC","AC")}
        teams={side:{"faceoffs_won":0} for side in ("home","away")}
        events=[]; score={"home":1,"away":0}; sog={"home":4,"away":2}
        state={"possession":None,"last_transition_family":"goal",
               "transition_family_counts":Counter(),"rule_forced_faceoffs":0}
        active={"home":["HC"],"away":["AC"]}

        sim._emit_rule_restart_faceoff(events,score,sog,teams,players,inputs,
            sim.random.Random(19),state,period_number=1,period_type="REG",elapsed=300,
            duration=1200,active=active,strength="1v1",
            goalie_pulled={"home":False,"away":False},causes=["goal"])

        self.assertEqual(len(events),1)
        faceoff=events[0]
        self.assertEqual(faceoff["event_type"],"faceoff")
        self.assertEqual(faceoff["details"]["faceoff_location"],"center-ice")
        self.assertEqual(faceoff["participants"]["faceoff_winner_id"],"HC")
        self.assertEqual(state["possession"],"home")
        self.assertEqual(players["HC"]["faceoffs_won"],1)
        self.assertEqual(players["AC"]["faceoffs_lost"],1)
        self.assertEqual(teams["home"]["faceoffs_won"],1)
        self.assertEqual(state["rule_forced_faceoffs"],1)


class ExactClockEventOrderTests(unittest.TestCase):
    def test_penalty_expiration_precedes_same_second_goalie_change(self):
        players={}
        shift=[]
        for side,prefix,goalie_ids in (
            ("home","H",("HG1","HG2")),("away","A",("AG",))):
            for number in range(1,6):
                pid=f"{prefix}{number}"
                players[pid]={"team_side":side,"position":"F"}
                shift.append({"period_number":1,"team_side":side,"player_id":pid,
                              "position":"F","start_seconds":0,"end_seconds":1200,
                              "duration_seconds":1200})
            for index,pid in enumerate(goalie_ids):
                players[pid]={"team_side":side,"position":"G"}
                if side=="home":
                    start,end=(0,100) if index==0 else (100,1200)
                else:
                    start,end=0,1200
                shift.append({"period_number":1,"team_side":side,"player_id":pid,
                              "position":"G","start_seconds":start,"end_seconds":end,
                              "duration_seconds":end-start})
        expiry={"period_number":1,"period_type":"REG","clock_elapsed_seconds":100,
                "event_type":"penalty-expiration","team_side":"home","details":{},
                "participants":{"player_id":"H1"},"on_ice":{"home":[],"away":[]},
                "strength":"5v5"}

        events=sim._insert_goalie_substitutions([expiry],shift,players)

        expiration_index=next(i for i,e in enumerate(events) if e["event_type"]=="penalty-expiration")
        change_index=next(i for i,e in enumerate(events) if e["event_type"]=="goalie-substitution")
        self.assertLess(expiration_index,change_index)
        substitution=events[change_index]
        self.assertEqual(substitution["details"]["goalie_pulled"],
                         {"home":False,"away":False})


if __name__=="__main__":
    unittest.main()
