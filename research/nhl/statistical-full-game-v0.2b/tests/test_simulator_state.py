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


def shift_transition_fixture():
    totals={}
    rosters={}
    for side,prefix,goalie_ids,team in (
        ("home","H",("HG1","HG2"),"HOME"),
        ("away","A",("AG",),"AWAY")):
        players={}
        for number in range(1,7):
            pid=f"{prefix}{number}"
            player=sim.Player(pid,None,pid,team,"F")
            players[pid]=player
            totals[pid]={"team_side":side,"position":"F"}
        for goalie_id in goalie_ids:
            players[goalie_id]=sim.Player(goalie_id,None,goalie_id,team,"G")
            totals[goalie_id]={"team_side":side,"position":"G"}
        game_roster_ids = [pid for pid in players if players[pid].position != "G"] + list(goalie_ids)
        rosters[side]=sim.TeamRoster(team,players,30.0,30.0,list(goalie_ids),
            [1.0]*len(goalie_ids),"fixture",{},game_roster_ids)
    return totals,SimpleNamespace(home_roster=rosters["home"],away_roster=rosters["away"])


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
    def test_goalie_transition_reconciles_short_donor_shift_to_legal_manpower(self):
        players,inputs=shift_transition_fixture()
        shift=[]
        for pid in ("H1","H2","H3","H4"):
            shift.append({"period_number":1,"team_side":"home","player_id":pid,
                "position":"F","start_seconds":0,"end_seconds":1200,
                "duration_seconds":1200})
        for pid,start,end in (("HG1",0,100),("HG2",100,1200)):
            shift.append({"period_number":1,"team_side":"home","player_id":pid,
                "position":"G","start_seconds":start,"end_seconds":end,
                "duration_seconds":end-start})
        for pid in ("A1","A2","A3","A4","A5","AG"):
            position="G" if pid=="AG" else "F"
            shift.append({"period_number":1,"team_side":"away","player_id":pid,
                "position":position,"start_seconds":0,"end_seconds":1200,
                "duration_seconds":1200})

        events=sim._insert_goalie_substitutions([],shift,players,inputs)
        substitution=next(e for e in events if e["event_type"]=="goalie-substitution")
        home_skaters=[pid for pid in substitution["on_ice"]["home"]
                      if players[pid]["position"]!="G"]
        self.assertEqual(len(home_skaters),5)
        self.assertEqual(substitution["strength"],"5v5")
        self.assertEqual(substitution["details"]["goalie_pulled"],
                         {"home":False,"away":False})

    def test_penalty_expiration_precedes_same_second_goalie_change(self):
        players,inputs=shift_transition_fixture()
        shift=[]
        for side,prefix,goalie_id in (("home","H",None),("away","A","AG")):
            for number in range(1,6):
                pid=f"{prefix}{number}"
                shift.append({"period_number":1,"team_side":side,"player_id":pid,
                    "position":"F","start_seconds":0,"end_seconds":1200,
                    "duration_seconds":1200})
            if side=="away":
                shift.append({"period_number":1,"team_side":side,"player_id":goalie_id,
                    "position":"G","start_seconds":0,"end_seconds":1200,
                    "duration_seconds":1200})
        shift.extend([
            {"period_number":1,"team_side":"home","player_id":"HG1","position":"G",
             "start_seconds":0,"end_seconds":140,"duration_seconds":140},
            {"period_number":1,"team_side":"home","player_id":"HG2","position":"G",
             "start_seconds":140,"end_seconds":1200,"duration_seconds":1060},
        ])
        full_home=["H1","H2","H3","H4","H5","HG1"]
        away=["A1","A2","A3","A4","A5","AG"]
        penalty=event("penalty",20,home=full_home,away=away,strength="5v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"goalie_pulled":{"home":False,"away":False}},
            side="home",participants={"penalized_player_id":"H1","serving_player_id":"H1"})
        expiry=event("penalty-expiration",140,home=["H1","H2","H3","H4","H5","HG2"],
            away=away,strength="5v5",details={"goalie_pulled":{"home":False,"away":False}},
            side="home",participants={"player_id":"H1"})

        events=sim._insert_goalie_substitutions([penalty,expiry],shift,players,inputs)

        expiration_index=next(i for i,e in enumerate(events) if e["event_type"]=="penalty-expiration")
        change_index=next(i for i,e in enumerate(events) if e["event_type"]=="goalie-substitution")
        self.assertLess(expiration_index,change_index)
        substitution=events[change_index]
        self.assertEqual(substitution["details"]["goalie_pulled"],
                         {"home":False,"away":False})
        self.assertIn("H1",substitution["on_ice"]["home"])

    def test_goalie_reconciliation_replays_queued_penalty_clock_and_remaps_reference(self):
        players,inputs=shift_transition_fixture()
        full_away=["A1","A2","A3","A4","A5","AG"]
        one_short=["A2","A3","A4","A5","AG"]
        two_short=["A3","A4","A5","AG"]
        queued_substitute=["A4","A5","A6","AG"]
        home=["H1","H2","H3","H4","H5","HG1"]
        events=[]

        def append(row):
            row["sequence"]=len(events)+1
            events.append(row)
            return row

        append(event("penalty",10,home=home,away=full_away,strength="5v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"active"},
            side="away",participants={"penalized_player_id":"A1","serving_player_id":"A1"}))
        append(event("faceoff",10,home=home,away=one_short,strength="5v4",details={},side="home"))
        append(event("penalty",20,home=home,away=one_short,strength="5v4",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"active"},
            side="away",participants={"penalized_player_id":"A2","serving_player_id":"A2"}))
        append(event("faceoff",20,home=home,away=two_short,strength="5v3",details={},side="home"))
        queued_assessment=append(event("penalty",30,home=home,away=two_short,strength="5v3",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"queued"},
            side="away",participants={"penalized_player_id":"A3","serving_player_id":"A3"}))
        queued_assessment["details"]["penalty_assessment_event_sequence"]=queued_assessment["sequence"]
        original_assessment_sequence=queued_assessment["sequence"]
        append(event("faceoff",30,home=home,away=queued_substitute,strength="5v3",details={},side="home"))
        append(event("penalty-expiration",130,home=home,away=queued_substitute,strength="5v3",
            details={"return_deferred_under_rule_26_2":True},side="away",
            participants={"player_id":"A1"}))
        append(event("penalty-service-start",130,home=home,away=queued_substitute,strength="5v3",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                "penalty_assessment_event_sequence":queued_assessment["sequence"],
                "assessed_at_absolute_second":30,"service_started_at_absolute_second":130,
                "triggered_by_expired_player_id":"A1"},side="away",
            participants={"player_id":"A3"}))
        append(event("stoppage",131,home=home,away=queued_substitute,strength="5v3",details={}))
        append(event("penalty-release",131,home=home,away=queued_substitute,strength="5v3",
            details={"release_reason":"penalty_expiration_stoppage"},side="away",
            participants={"player_id":"A1"}))
        append(event("penalty-expiration",140,home=home,
            away=["A1","A4","A5","A6","AG"],strength="5v4",
            details={"return_deferred_under_rule_26_2":False},side="away",
            participants={"player_id":"A2"}))
        append(event("penalty-expiration",250,home=home,away=full_away,strength="5v5",
            details={"return_deferred_under_rule_26_2":False},side="away",
            participants={"player_id":"A3"}))

        shifts=[]
        for pid in ("H1","H2","H3","H4","H5"):
            shifts.append({"period_number":1,"team_side":"home","player_id":pid,
                "position":"F","start_seconds":0,"end_seconds":300,"duration_seconds":300})
        for pid,start,end in (("HG1",0,25),("HG2",25,300)):
            shifts.append({"period_number":1,"team_side":"home","player_id":pid,
                "position":"G","start_seconds":start,"end_seconds":end,
                "duration_seconds":end-start})
        for pid in ("A1","A2","A3","A4","A5","A6","AG"):
            shifts.append({"period_number":1,"team_side":"away","player_id":pid,
                "position":"G" if pid=="AG" else "F","start_seconds":0,
                "end_seconds":300,"duration_seconds":300})

        reconciled=sim._insert_goalie_substitutions(events,shifts,players,inputs)
        service=next(e for e in reconciled if e["event_type"]=="penalty-service-start")
        assessment=next(e for e in reconciled if e["event_type"]=="penalty"
                        and e["participants"].get("penalized_player_id")=="A3")
        self.assertNotEqual(assessment["sequence"],original_assessment_sequence)
        self.assertEqual(service["details"]["penalty_assessment_event_sequence"],
                         assessment["sequence"])
        sim._validate_live_game_state(reconciled,players)

    def test_shift_reconstruction_replays_queued_service_and_delayed_return(self):
        players,inputs=shift_transition_fixture()
        home=["H1","H2","H3","H4","H5","HG1"]
        away=["A1","A2","A3","A4","A5","AG"]
        one_short=["A2","A3","A4","A5","AG"]
        two_short=["A3","A4","A5","AG"]
        queued_substitute=["A4","A5","A6","AG"]
        events=[]

        def append(row):
            row["sequence"]=len(events)+1
            events.append(row)
            return row

        append(event("penalty",10,home=home,away=away,strength="5v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"active"},
            side="away",participants={"penalized_player_id":"A1","serving_player_id":"A1"}))
        append(event("faceoff",10,home=home,away=one_short,strength="5v4",details={},side="home"))
        append(event("penalty",20,home=home,away=one_short,strength="5v4",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"active"},
            side="away",participants={"penalized_player_id":"A2","serving_player_id":"A2"}))
        append(event("faceoff",20,home=home,away=two_short,strength="5v3",details={},side="home"))
        queued=append(event("penalty",30,home=home,away=two_short,strength="5v3",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"queued"},
            side="away",participants={"penalized_player_id":"A3","serving_player_id":"A3"}))
        queued["details"]["penalty_assessment_event_sequence"]=queued["sequence"]
        append(event("faceoff",30,home=home,away=queued_substitute,strength="5v3",details={},side="home"))
        append(event("penalty-expiration",130,home=home,away=queued_substitute,strength="5v3",
            details={"return_deferred_under_rule_26_2":True},side="away",
            participants={"player_id":"A1"}))
        append(event("penalty-service-start",130,home=home,away=queued_substitute,strength="5v3",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                "penalty_assessment_event_sequence":queued["sequence"],
                "assessed_at_absolute_second":30,"service_started_at_absolute_second":130,
                "triggered_by_expired_player_id":"A1"},side="away",
            participants={"player_id":"A3"}))
        append(event("stoppage",131,home=home,away=queued_substitute,strength="5v3",details={}))
        append(event("penalty-release",131,home=home,away=queued_substitute,strength="5v3",
            details={"release_reason":"penalty_expiration_stoppage"},side="away",
            participants={"player_id":"A1"}))
        append(event("penalty-expiration",140,home=home,
            away=["A1","A4","A5","A6","AG"],strength="5v4",
            details={"return_deferred_under_rule_26_2":False},side="away",
            participants={"player_id":"A2"}))
        append(event("penalty-expiration",250,home=home,away=away,strength="5v5",
            details={"return_deferred_under_rule_26_2":False},side="away",
            participants={"player_id":"A3"}))

        shifts=[]
        for side,prefix,goalie_id in (("home","H","HG1"),("away","A","AG")):
            for number in range(1,6):
                shifts.append({"period_number":1,"team_side":side,
                    "player_id":f"{prefix}{number}","position":"F",
                    "start_seconds":0,"end_seconds":1200,"duration_seconds":1200})
            shifts.append({"period_number":1,"team_side":side,"player_id":goalie_id,
                "position":"G","start_seconds":0,"end_seconds":1200,"duration_seconds":1200})
        donor=SimpleNamespace(period_number=1,period_type="REG",shift_ledger=shifts,
            terminal_elapsed=None,active=lambda elapsed:{"home":list(home),"away":list(away)})

        rows=sim._state_reconciled_shift_ledger(donor,events,inputs,sim.PenaltyLedger())
        a1_intervals=[row for row in rows if row["player_id"]=="A1"]
        self.assertTrue(any(row["start_seconds"]>=131 for row in a1_intervals),a1_intervals)
        self.assertTrue(all(row["end_seconds"]<=130 or row["start_seconds"]>=131
                            for row in a1_intervals),a1_intervals)

    def test_goal_triggered_queue_start_remains_after_goal_during_reconciliation(self):
        players,inputs=shift_transition_fixture()
        home=["H1","H2","H3","H4","H5","HG1"]
        home_one_short=["H2","H3","H4","H5","HG1"]
        home_two_short=["H3","H4","H5","HG1"]
        home_substitute=["H4","H5","H6","HG1"]
        away=["A1","A2","A3","A4","A5","AG"]
        events=[]

        def append(row):
            row["sequence"]=len(events)+1
            events.append(row)
            return row

        append(event("penalty",10,home=home,away=away,strength="5v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"active"},
            side="home",participants={"penalized_player_id":"H1","serving_player_id":"H1"}))
        append(event("faceoff",10,home=home_one_short,away=away,strength="4v5",details={},side="away"))
        append(event("penalty",20,home=home_one_short,away=away,strength="4v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"active"},
            side="home",participants={"penalized_player_id":"H2","serving_player_id":"H2"}))
        append(event("faceoff",20,home=home_two_short,away=away,strength="3v5",details={},side="away"))
        queued=append(event("penalty",30,home=home_two_short,away=away,strength="3v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                     "coincidental":False,"penalty_service_state":"queued"},
            side="home",participants={"penalized_player_id":"H3","serving_player_id":"H3"}))
        queued["details"]["penalty_assessment_event_sequence"]=queued["sequence"]
        append(event("faceoff",30,home=home_substitute,away=away,strength="3v5",details={},side="away"))
        append(event("goal",100,home=home_substitute,away=away,strength="3v5",
            details={},side="away",participants={"shooter_id":"A1","goalie_id":"HG1"}))
        append(event("penalty-service-start",100,home=home_substitute,away=away,strength="3v5",
            details={"penalty_kind":"MIN","penalty_duration_seconds":120,
                "penalty_assessment_event_sequence":queued["sequence"],
                "assessed_at_absolute_second":30,"service_started_at_absolute_second":100,
                "triggered_by_expired_player_id":"H1"},side="home",
            participants={"player_id":"H3"}))
        append(event("penalty-release",100,home=home_substitute,away=away,strength="3v5",
            details={"penalty_kind":"MIN","release_reason":"power_play_goal"},side="home",
            participants={"player_id":"H1"}))
        append(event("faceoff",100,home=home_substitute,away=away,strength="3v5",details={},side="away"))
        append(event("penalty-expiration",140,
            home=["H1","H4","H5","H6","HG1"],away=away,strength="4v5",
            details={"return_deferred_under_rule_26_2":False},side="home",
            participants={"player_id":"H2"}))
        append(event("penalty-expiration",220,home=home,away=away,strength="5v5",
            details={"return_deferred_under_rule_26_2":False},side="home",
            participants={"player_id":"H3"}))

        shifts=[]
        for pid in ("H1","H2","H3","H4","H5","H6"):
            shifts.append({"period_number":1,"team_side":"home","player_id":pid,
                "position":"F","start_seconds":0,"end_seconds":1200,"duration_seconds":1200})
        shifts.append({"period_number":1,"team_side":"home","player_id":"HG1",
            "position":"G","start_seconds":0,"end_seconds":1200,"duration_seconds":1200})
        for pid in ("A1","A2","A3","A4","A5","AG"):
            shifts.append({"period_number":1,"team_side":"away","player_id":pid,
                "position":"G" if pid=="AG" else "F","start_seconds":0,
                "end_seconds":1200,"duration_seconds":1200})

        reconciled=sim._insert_goalie_substitutions(events,shifts,players,inputs)
        at_goal=[e["event_type"] for e in reconciled
                 if e["period_number"]==1 and e["clock_elapsed_seconds"]==100
                 and e["event_type"] in {"goal","penalty-service-start","penalty-release"}]
        self.assertEqual(at_goal,["goal","penalty-service-start","penalty-release"])
        sim._validate_live_game_state(reconciled,players)


if __name__=="__main__":
    unittest.main()
