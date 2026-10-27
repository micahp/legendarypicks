from __future__ import annotations

import copy
import csv
import gzip
import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import validator


BASE_HOME = ["H1", "H2", "H3", "H4", "H5", "HG"]
BASE_AWAY = ["A1", "A2", "A3", "A4", "A5", "AG"]
SHORT_AWAY = ["A2", "A3", "A4", "A5", "AG"]


class GameBuilder:
    def __init__(self) -> None:
        self.players = {}
        self.projected_players = {"home": [], "away": []}
        for side, prefix in (("home", "H"), ("away", "A")):
            for n in range(1, 7):
                self.players[f"{prefix}{n}"] = {
                    "team_side": side, "position": "F", "goals": 0,
                    "assists": 0, "shot_attempts": 0, "shots_on_goal": 0,
                    "shootout_attempts": 0, "shootout_goals": 0,
                    "time_on_ice_seconds": 0,
                }
                self.projected_players[side].append({"player_id": f"{prefix}{n}", "position": "F"})
            self.players[f"{prefix}G"] = {
                "team_side": side, "position": "G", "goals": 0,
                "assists": 0, "shot_attempts": 0, "shots_on_goal": 0,
                "shootout_attempts": 0, "shootout_goals": 0,
                "time_on_ice_seconds": 0,
            }
            self.projected_players[side].append({"player_id": f"{prefix}G", "position": "G"})
            for n in range(7, 13):
                player_id = f"{prefix}{n}"
                self.players[player_id] = {
                    "team_side": side, "position": "F", "goals": 0,
                    "assists": 0, "shot_attempts": 0, "shots_on_goal": 0,
                    "shootout_attempts": 0, "shootout_goals": 0,
                    "time_on_ice_seconds": 0,
                }
                self.projected_players[side].append({"player_id": player_id, "position": "F"})
            for n in range(1, 7):
                player_id = f"{prefix}D{n}"
                self.players[player_id] = {
                    "team_side": side, "position": "D", "goals": 0,
                    "assists": 0, "shot_attempts": 0, "shots_on_goal": 0,
                    "shootout_attempts": 0, "shootout_goals": 0,
                    "time_on_ice_seconds": 0,
                }
                self.projected_players[side].append({"player_id": player_id, "position": "D"})
            goalie_id = f"{prefix}G2"
            self.players[goalie_id] = {
                "team_side": side, "position": "G", "goals": 0,
                "assists": 0, "shot_attempts": 0, "shots_on_goal": 0,
                "shootout_attempts": 0, "shootout_goals": 0,
                "time_on_ice_seconds": 0,
            }
            self.projected_players[side].append({"player_id": goalie_id, "position": "G"})
        self.events = []
        self.score = {"home": 0, "away": 0}
        self.sog = {"home": 0, "away": 0}
        self.attempts = {"home": 0, "away": 0}

    def emit(self, event_type, period, elapsed, *, side=None, home=None, away=None,
             details=None, participants=None, strength=None):
        period_type = "REG" if period <= 3 else "OT" if period == 4 else "SO"
        period_length = 1200 if period_type == "REG" else 300 if period_type == "OT" else 0
        home = list(home if home is not None else BASE_HOME)
        away = list(away if away is not None else BASE_AWAY)
        on_ice = {"home": home, "away": away}
        if strength is None and period_type in {"REG", "OT"}:
            goalies_home = sum(self.players.get(pid, {}).get("position") == "G" for pid in home)
            goalies_away = sum(self.players.get(pid, {}).get("position") == "G" for pid in away)
            strength = f"{len(home)-goalies_home}v{len(away)-goalies_away}"
        default_pulled = {
            "home": not any(self.players.get(pid, {}).get("position") == "G" for pid in home),
            "away": not any(self.players.get(pid, {}).get("position") == "G" for pid in away),
        }
        details = dict(details or {})
        if period_type in {"REG", "OT"} and event_type not in {"period-start", "period-end", "game-end"}:
            details.setdefault("goalie_pulled", default_pulled)
        before = {"score": dict(self.score), "sog_event_count": dict(self.sog)}
        if event_type == "goal" and period_type != "SO":
            self.score[side] += 1
            self.sog[side] += 1
            self.attempts[side] += 1
            shooter = str((participants or {}).get("shooter_id"))
            if shooter in self.players:
                self.players[shooter]["goals"] += 1
                self.players[shooter]["shot_attempts"] += 1
                self.players[shooter]["shots_on_goal"] += 1
        elif event_type == "shot-on-goal" and period_type != "SO":
            self.sog[side] += 1
            self.attempts[side] += 1
            shooter = str((participants or {}).get("shooter_id"))
            if shooter in self.players:
                self.players[shooter]["shot_attempts"] += 1
                self.players[shooter]["shots_on_goal"] += 1
        elif event_type in {"missed-shot", "blocked-shot", "failed-shot-attempt"}:
            if period_type != "SO":
                self.attempts[side] += 1
                shooter = str((participants or {}).get("shooter_id"))
                if shooter in self.players:
                    self.players[shooter]["shot_attempts"] += 1
        elif event_type == "shootout-attempt":
            shooter = str((participants or {}).get("shooter_id"))
            if shooter in self.players:
                self.players[shooter]["shootout_attempts"] += 1
                if details.get("attempt_result") == "goal":
                    self.players[shooter]["shootout_goals"] += 1
        elif event_type == "shootout-decision":
            self.score[side] += 1
        if strength is None and period_type == "SO":
            strength = None
        event = {
            "sequence": len(self.events) + 1,
            "period_number": period,
            "period_type": period_type,
            "time_in_period": f"{elapsed // 60:02d}:{elapsed % 60:02d}",
            "time_remaining": f"{max(0, period_length-elapsed) // 60:02d}:{max(0, period_length-elapsed) % 60:02d}",
            "clock_elapsed_seconds": elapsed,
            "clock_remaining_seconds": max(0, period_length - elapsed),
            "event_type": event_type,
            "team_side": side,
            "details": details,
            "participants": dict(participants or {}),
            "on_ice": on_ice,
            "strength": strength,
            "state_before": before,
            "state_after": {"score": dict(self.score), "sog_event_count": dict(self.sog)},
        }
        self.events.append(event)
        return event

    def faceoff(self, period, elapsed, *, home=None, away=None, winner="home"):
        details = {"faceoff_location": "center", "xCoord": 0, "yCoord": 0,
                   "zoneCode": "N"}
        if winner == "home":
            participants = {"faceoff_winner_id": "H2", "faceoff_loser_id": "A2"}
        else:
            participants = {"faceoff_winner_id": "A2", "faceoff_loser_id": "H2"}
        return self.emit("faceoff", period, elapsed, side=winner, home=home, away=away,
                         details=details, participants=participants)

    def base_regulation(self, *, p1_goal=True):
        self.emit("period-start", 1, 0, home=[], away=[])
        self.faceoff(1, 0)
        if p1_goal:
            self.emit("goal", 1, 60, side="home", details={"shot_quality_bin": {"shot_type": "wrist"}},
                participants={"shooter_id": "H1", "goalie_id": "AG", "empty_net": False})
            self.faceoff(1, 60)
        self.emit("period-end", 1, 1200, home=[], away=[])
        for period in (2, 3):
            self.emit("period-start", period, 0, home=[], away=[])
            self.faceoff(period, 0)
            self.emit("period-end", period, 1200, home=[], away=[])
        return self

    def default_shifts(self):
        rows = []
        periods = sorted({int(e["period_number"]) for e in self.events
                          if e["period_type"] in {"REG", "OT"}})
        for period in periods:
            limit = 1200 if period <= 3 else 300
            for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
                for pid in ids:
                    rows.append({"period_number": period, "team_side": side,
                        "player_id": pid, "position": self.players[pid]["position"],
                        "start_seconds": 0, "end_seconds": limit,
                        "duration_seconds": limit})
        return rows

    def finish(self, *, shifts=None, shootout_winner=None):
        if shifts is None:
            shifts = self.default_shifts()
        for row in shifts:
            self.players[row["player_id"]]["time_on_ice_seconds"] += row["duration_seconds"]
        if not any(e["event_type"] == "game-end" for e in self.events):
            period = max(e["period_number"] for e in self.events)
            ptype = next(e["period_type"] for e in reversed(self.events))
            elapsed = 300 if ptype == "OT" else 0 if ptype == "SO" else 1200
            self.emit("game-end", period, elapsed, home=[], away=[])
        reg_ot = {side: sum(e["event_type"] == "goal" and e["period_type"] in {"REG", "OT"}
                            and e["team_side"] == side for e in self.events) for side in ("home", "away")}
        team_totals = {}
        for side in ("home", "away"):
            team_totals[side] = {
                "goals": reg_ot[side], "shot_attempts": self.attempts[side],
                "shots_on_goal": self.sog[side], "penalties": sum(
                    e["event_type"] == "penalty" and e["team_side"] == side for e in self.events),
            }
        goalie_totals = {
            "HG": {"team_side": "home", "saves": 0, "goals_against": 0, "shots_against": 0},
            "AG": {"team_side": "away", "saves": 0, "goals_against": reg_ot["home"], "shots_against": self.sog["home"]},
        }
        return {
            "schema_version": "nhl-statistical-pbp-v0.2b",
            "simulation_id": "test-game", "seed": 7,
            "teams": {"home": "HOM", "away": "AWY"},
            "pregame_snapshot": {"game_date": "2021-11-01",
                "actual_target_game_stats_or_lineups_used": False,
                "projected_game_roster": {
                    "status": "pregame_projection_only",
                    "selection_policy": "synthetic test roster",
                    "actual_target_game_lineup_used": False,
                    "source_by_side": {"home": "synthetic", "away": "synthetic"},
                    "players_by_side": self.projected_players,
                },
                "home_roster_coverage": {"active_players": 20},
                "away_roster_coverage": {"active_players": 20}},
            "rules_profile": {"competition": "regular_season", "regulation_periods": 3,
                "regulation_period_seconds": 1200, "overtime_period_seconds": 300,
                "three_on_three_overtime": True, "shootout_after_tied_overtime": True},
            "events": self.events,
            "shift_ledger": shifts,
            "summary": {
                "official_final_score": dict(self.score),
                "regulation_overtime_score": reg_ot,
                "sog_event_counts": dict(self.sog),
                "team_totals": team_totals,
                "player_totals": self.players,
                "goalie_totals": goalie_totals,
                "shootout_winner": shootout_winner,
            },
        }


def regular_game():
    builder = GameBuilder().base_regulation()
    builder.emit("game-end", 3, 1200, home=[], away=[])
    return builder.finish()


def penalty_game(kind="MIN", duration=120, *, goal_time=None, expiry_time=None,
                 forced_resolution=None):
    builder = GameBuilder().base_regulation()
    # Remove the pre-built period 3 end and append its live events before it.
    builder.events.pop()
    builder.emit("penalty", 3, 100, side="away", home=BASE_HOME, away=BASE_AWAY,
        details={"penalty_kind": kind, "penalty_duration_seconds": duration,
                 "coincidental": False},
        participants={"penalized_player_id": "A1", "serving_player_id": "A1"})
    builder.faceoff(3, 100, away=SHORT_AWAY)
    resolution_time = expiry_time
    if goal_time is not None:
        builder.emit("goal", 3, goal_time, side="home", home=BASE_HOME, away=SHORT_AWAY,
            participants={"shooter_id": "H1", "goalie_id": "AG", "empty_net": False})
        resolution_type = forced_resolution
        if resolution_type is None:
            resolution_type = "penalty-segment-end" if kind == "MIN" and duration == 240 else "penalty-release" if kind == "MIN" else None
        if resolution_type:
            builder.emit(resolution_type, 3, goal_time, side="away", home=BASE_HOME,
                away=SHORT_AWAY, details={"penalty_kind": kind, "release_reason": "power_play_goal",
                    "penalty_fully_released": resolution_type == "penalty-release"},
                participants={"player_id": "A1"})
        released = resolution_type == "penalty-release"
        builder.faceoff(3, goal_time, away=BASE_AWAY if released else SHORT_AWAY)
        if resolution_type == "penalty-segment-end":
            resolution_time = goal_time + 120
        elif resolution_type == "penalty-release":
            resolution_time = None
        elif kind == "MAJ":
            resolution_time = 100 + duration
        else:
            resolution_time = 100 + duration
    else:
        resolution_time = expiry_time if expiry_time is not None else 100 + duration
    shifts = []
    for period in (1, 2):
        for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
            for pid in ids:
                shifts.append({"period_number": period, "team_side": side, "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 1200, "duration_seconds": 1200})
    p3_end_a1 = resolution_time if resolution_time is not None else 1200
    if goal_time is not None and forced_resolution == "penalty-release":
        p3_start_a1 = goal_time
    elif goal_time is not None and kind == "MIN" and duration == 120:
        p3_start_a1 = goal_time
    elif goal_time is not None and kind == "MIN" and duration == 240:
        p3_start_a1 = goal_time + 120
    else:
        p3_start_a1 = 100 + duration
    p3_start_a1 = max(100, p3_start_a1)
    for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
        for pid in ids:
            if side == "away" and pid == "A1":
                if 100 > 0:
                    shifts.append({"period_number": 3, "team_side": side, "player_id": pid,
                        "position": "F", "start_seconds": 0, "end_seconds": 100,
                        "duration_seconds": 100})
                if p3_start_a1 < 1200:
                    shifts.append({"period_number": 3, "team_side": side, "player_id": pid,
                        "position": "F", "start_seconds": p3_start_a1, "end_seconds": 1200,
                        "duration_seconds": 1200-p3_start_a1})
            else:
                shifts.append({"period_number": 3, "team_side": side, "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 1200, "duration_seconds": 1200})
    if resolution_time is not None:
        event_away = BASE_AWAY
        builder.emit("penalty-expiration", 3, resolution_time, side="away", home=BASE_HOME,
            away=event_away, details={"penalty_kind": kind}, participants={"player_id": "A1"})
    builder.emit("period-end", 3, 1200, home=[], away=[])
    builder.emit("game-end", 3, 1200, home=[], away=[])
    return builder.finish(shifts=shifts)


def misconduct_game(expiry_time=700):
    builder = GameBuilder().base_regulation(p1_goal=False)
    builder.events.pop()  # Replace period 3 end with the misconduct interval.
    full_away = ["A1", "A2", "A3", "A4", "A5", "AG"]
    replacement_away = ["A2", "A3", "A4", "A5", "A6", "AG"]
    builder.emit("penalty", 3, 100, side="away", home=BASE_HOME, away=full_away,
        details={"penalty_kind": "MIS", "penalty_duration_seconds": 600,
                 "coincidental": False},
        participants={"penalized_player_id": "A1", "serving_player_id": "A1"})
    builder.faceoff(3, 100, away=replacement_away)
    builder.emit("penalty-expiration", 3, expiry_time, side="away", home=BASE_HOME,
        away=full_away, details={"penalty_kind": "MIS"},
        participants={"player_id": "A1"})
    builder.emit("period-end", 3, 1200, home=[], away=[])
    builder.emit("game-end", 3, 1200, home=[], away=[])
    shifts = []
    for period in (1, 2):
        for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
            for pid in ids:
                shifts.append({"period_number": period, "team_side": side, "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 1200, "duration_seconds": 1200})
    for pid in BASE_HOME:
        shifts.append({"period_number": 3, "team_side": "home", "player_id": pid,
            "position": builder.players[pid]["position"], "start_seconds": 0,
            "end_seconds": 1200, "duration_seconds": 1200})
    for pid in ("A2", "A3", "A4", "A5", "AG"):
        shifts.append({"period_number": 3, "team_side": "away", "player_id": pid,
            "position": builder.players[pid]["position"], "start_seconds": 0,
            "end_seconds": 1200, "duration_seconds": 1200})
    for pid, start, end in (("A1", 0, 100), ("A1", 700, 1200), ("A6", 100, 700)):
        shifts.append({"period_number": 3, "team_side": "away", "player_id": pid,
            "position": "F", "start_seconds": start, "end_seconds": end,
            "duration_seconds": end-start})
    return builder.finish(shifts=shifts)


def shootout_game(*, add_attempt_after_clinch=False):
    builder = GameBuilder().base_regulation(p1_goal=False)
    builder.emit("period-start", 4, 0, home=[], away=[])
    ot_home = ["H1", "H2", "H3", "HG"]
    ot_away = ["A1", "A2", "A3", "AG"]
    builder.faceoff(4, 0, home=ot_home, away=ot_away)
    builder.emit("period-end", 4, 300, home=[], away=[])
    builder.emit("period-start", 5, 0, home=[], away=[],
        details={"first_shooting_side": "home"})
    attempts = [("home", "goal", "H1"), ("away", "goal", "A1"),
                ("home", "goal", "H2"), ("away", "goal", "A2"),
                ("home", "goal", "H3"), ("away", "missed", "A3")]
    if add_attempt_after_clinch:
        attempts.append(("home", "missed", "H4"))
    for side, result, shooter in attempts:
        builder.emit("shootout-attempt", 5, 0, side=side, home=[], away=[],
            details={"round": (sum(e["event_type"] == "shootout-attempt" for e in builder.events) // 2) + 1,
                     "attempt_result": result},
            participants={"shooter_id": shooter, "goalie_id": "AG" if side == "home" else "HG"})
    builder.emit("shootout-decision", 5, 0, side="home", home=[], away=[],
        details={"official_bonus_goal": 1}, participants={})
    builder.emit("period-end", 5, 0, home=[], away=[])
    builder.emit("game-end", 5, 0, home=[], away=[])
    shifts = []
    for period in (1, 2, 3):
        for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
            for pid in ids:
                shifts.append({"period_number": period, "team_side": side, "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 1200, "duration_seconds": 1200})
    for side, ids in (("home", ot_home), ("away", ot_away)):
        for pid in ids:
            shifts.append({"period_number": 4, "team_side": side, "player_id": pid,
                "position": builder.players[pid]["position"], "start_seconds": 0,
                "end_seconds": 300, "duration_seconds": 300})
    return builder.finish(shifts=shifts, shootout_winner="home")


def goalie_pull_game():
    builder = GameBuilder().base_regulation()
    builder.events.pop()  # Replace period 3 terminal events with pull/return sequence.
    pulled_home = ["H1", "H2", "H3", "H4", "H5", "H6"]
    builder.emit("goalie-substitution", 3, 300, side="home", home=pulled_home, away=BASE_AWAY,
        details={"reason": "research fixture", "goalie_pulled": {"home": True, "away": False}},
        participants={"goalie_leaving_id": "HG", "goalie_entering_id": None})
    builder.emit("goal", 3, 300, side="away", home=pulled_home, away=BASE_AWAY,
        participants={"shooter_id": "A1", "goalie_id": None, "empty_net": True})
    builder.faceoff(3, 300, home=pulled_home)
    builder.emit("stoppage", 3, 301, side=None, home=pulled_home, away=BASE_AWAY)
    returned_home = ["H1", "H2", "H3", "H4", "H5", "HG"]
    builder.emit("goalie-substitution", 3, 301, side="home", home=returned_home, away=BASE_AWAY,
        participants={"goalie_leaving_id": None, "goalie_entering_id": "HG"})
    builder.faceoff(3, 301, home=returned_home)
    builder.emit("goal", 3, 400, side="home", home=returned_home, away=BASE_AWAY,
        participants={"shooter_id": "H2", "goalie_id": "AG", "empty_net": False})
    builder.faceoff(3, 400, home=returned_home)
    builder.emit("period-end", 3, 1200, home=[], away=[])
    builder.emit("game-end", 3, 1200, home=[], away=[])
    shifts = []
    for period in (1, 2):
        for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
            for pid in ids:
                shifts.append({"period_number": period, "team_side": side, "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 1200, "duration_seconds": 1200})
    for pid in ["H1", "H2", "H3", "H4", "H5"]:
        shifts.append({"period_number": 3, "team_side": "home", "player_id": pid,
            "position": "F", "start_seconds": 0, "end_seconds": 1200, "duration_seconds": 1200})
    shifts.extend([
        {"period_number": 3, "team_side": "home", "player_id": "HG", "position": "G",
         "start_seconds": 0, "end_seconds": 300, "duration_seconds": 300},
        {"period_number": 3, "team_side": "home", "player_id": "HG", "position": "G",
         "start_seconds": 301, "end_seconds": 1200, "duration_seconds": 899},
        {"period_number": 3, "team_side": "home", "player_id": "H6", "position": "F",
         "start_seconds": 300, "end_seconds": 301, "duration_seconds": 1},
    ])
    for pid in BASE_AWAY:
        shifts.append({"period_number": 3, "team_side": "away", "player_id": pid,
            "position": builder.players[pid]["position"], "start_seconds": 0,
            "end_seconds": 1200, "duration_seconds": 1200})
    return builder.finish(shifts=shifts)


class IndependentGate1ValidatorTests(unittest.TestCase):
    def get_check(self, game, code):
        result = validator.audit_game(game, ruleset="2021-22")
        return next(row for row in result["checks"] if row["code"] == code)

    def test_structural_game_passes_while_full_rule_assessment_stays_unavailable(self):
        game = regular_game()
        result = validator.audit_game(game, ruleset="2021-22")
        self.assertTrue(result["structural_valid"])
        self.assertFalse(result["full_rule_assessed"])
        self.assertEqual(self.get_check(game, "restart_sequence")["status"], "PASS")
        self.assertEqual(self.get_check(game, "restart_location")["status"], "PASS")
        self.assertEqual(self.get_check(game, "simulation_roster_consistency")["status"], "PASS")
        self.assertEqual(self.get_check(game, "geometry_and_officiating")["status"], "NOT_ASSESSED")
        self.assertEqual(self.get_check(game, "game_lineup_eligibility")["status"], "NOT_ASSESSED")

    def test_simulation_roster_rejects_target_lineup_leakage_and_extra_player_totals(self):
        game = regular_game()
        game["pregame_snapshot"]["projected_game_roster"]["actual_target_game_lineup_used"] = True
        self.assertEqual(self.get_check(game, "simulation_roster_consistency")["status"], "FAIL")
        game = regular_game()
        game["summary"]["player_totals"]["H99"] = {"team_side": "home", "position": "F"}
        self.assertEqual(self.get_check(game, "simulation_roster_consistency")["status"], "FAIL")

    def test_goal_requires_center_faceoff_before_play_resumes(self):
        game = regular_game()
        goal_index = next(i for i, e in enumerate(game["events"]) if e["event_type"] == "goal")
        self.assertEqual(game["events"][goal_index + 1]["event_type"], "faceoff")
        self.assertEqual(self.get_check(game, "restart_sequence")["status"], "PASS")
        self.assertEqual(self.get_check(game, "restart_location")["status"], "PASS")
        del game["events"][goal_index + 1]
        for i, event in enumerate(game["events"], 1):
            event["sequence"] = i
        result = self.get_check(game, "restart_sequence")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("goal is not followed", " ".join(x["message"] for x in result["findings"]))

    def test_missing_restart_location_is_unassessed_and_wrong_location_fails(self):
        game = regular_game()
        goal_index = next(i for i, e in enumerate(game["events"]) if e["event_type"] == "goal")
        faceoff = game["events"][goal_index + 1]
        for key in ("faceoff_location", "location", "xCoord", "yCoord", "zoneCode"):
            faceoff["details"].pop(key, None)
        self.assertEqual(self.get_check(game, "restart_sequence")["status"], "PASS")
        self.assertEqual(self.get_check(game, "restart_location")["status"], "NOT_ASSESSED")
        result = validator.audit_game(game, ruleset="2021-22")
        self.assertTrue(result["structural_valid"])
        self.assertFalse(result["full_rule_assessed"])
        faceoff["details"].update({"faceoff_location": "offensive-zone", "xCoord": 70,
                                   "yCoord": 10, "zoneCode": "O"})
        self.assertEqual(self.get_check(game, "restart_location")["status"], "FAIL")

    def test_penalty_service_and_exact_minor_expiry(self):
        game = penalty_game("MIN", 120)
        result = self.get_check(game, "penalty_and_manpower")
        self.assertEqual(result["status"], "PASS", result["findings"])
        expiration = next(e for e in game["events"] if e["event_type"] == "penalty-expiration")
        self.assertEqual(expiration["clock_elapsed_seconds"], 220)
        invalid = penalty_game("MIN", 120, expiry_time=219)
        result = self.get_check(invalid, "penalty_and_manpower")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("early", " ".join(x["message"] for x in result["findings"]))

    def test_misconduct_runs_ten_minutes_without_reducing_manpower(self):
        game = misconduct_game()
        result = self.get_check(game, "penalty_and_manpower")
        self.assertEqual(result["status"], "PASS", result["findings"])
        after_assessment = next(e for e in game["events"]
                                if e["event_type"] == "faceoff" and e["period_number"] == 3
                                and e["clock_elapsed_seconds"] == 100)
        self.assertEqual(after_assessment["strength"], "5v5")
        self.assertNotIn("A1", after_assessment["on_ice"]["away"])
        expiration = next(e for e in game["events"] if e["event_type"] == "penalty-expiration")
        self.assertEqual(expiration["clock_elapsed_seconds"], 700)
        self.assertIn("A1", expiration["on_ice"]["away"])

    def test_misconduct_early_expiry_fails(self):
        game = misconduct_game(expiry_time=650)
        result = self.get_check(game, "penalty_and_manpower")
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("early" in row["message"] or "active penalty" in row["message"]
                            for row in result["findings"]))

    def test_missing_coincidental_state_is_unassessed_not_noncoincidental(self):
        game = penalty_game("MIN", 120)
        penalty = next(e for e in game["events"] if e["event_type"] == "penalty")
        del penalty["details"]["coincidental"]
        result = self.get_check(game, "penalty_and_manpower")
        self.assertEqual(result["status"], "NOT_ASSESSED", result["findings"])
        self.assertTrue(any("explicit coincidental classification" in row["message"]
                            and row["status"] == "NOT_ASSESSED"
                            for row in result["findings"]))
        self.assertFalse(any(row["status"] == "FAIL" for row in result["findings"]))

    def test_coincidental_minor_does_not_change_manpower(self):
        active = [
            {"side": "home", "player_id": "H1", "kind": "MIN", "duration": 120,
             "start": 100, "end": 220, "coincidental": True},
            {"side": "away", "player_id": "A1", "kind": "MIN", "duration": 120,
             "start": 100, "end": 220, "coincidental": True},
        ]
        counts, reason = validator._expected_manpower(active, "REG", {"home": False, "away": False})
        self.assertIsNone(reason)
        self.assertEqual(counts, {"home": 5, "away": 5})
        for penalty in active:
            penalty["coincidental"] = False
        counts, reason = validator._expected_manpower(active, "REG", {"home": False, "away": False})
        self.assertIsNone(reason)
        self.assertEqual(counts, {"home": 4, "away": 4})
        active[0]["coincidental"] = None
        counts, reason = validator._expected_manpower(active, "REG", {"home": False, "away": False})
        self.assertIsNone(counts)
        self.assertIn("explicit coincidental classification", reason)

    def test_double_minor_goal_ends_only_first_segment(self):
        game = penalty_game("MIN", 240, goal_time=150)
        result = self.get_check(game, "penalty_and_manpower")
        self.assertEqual(result["status"], "PASS", result["findings"])
        transitions = [e for e in game["events"] if e["event_type"] in {"penalty-segment-end", "penalty-expiration"}]
        self.assertEqual([e["event_type"] for e in transitions], ["penalty-segment-end", "penalty-expiration"])
        self.assertEqual(transitions[-1]["clock_elapsed_seconds"], 270)

    def test_major_remains_active_after_power_play_goal(self):
        game = penalty_game("MAJ", 300, goal_time=150)
        result = self.get_check(game, "penalty_and_manpower")
        self.assertEqual(result["status"], "PASS", result["findings"])
        self.assertEqual(sum(e["event_type"] == "penalty-release" for e in game["events"]), 0)
        self.assertEqual(next(e for e in game["events"] if e["event_type"] == "penalty-expiration")["clock_elapsed_seconds"], 400)

    def test_line_change_ids_and_shift_boundaries_reconcile(self):
        builder = GameBuilder()
        builder.emit("period-start", 1, 0, home=[], away=[])
        builder.faceoff(1, 0)
        builder.emit("stoppage", 1, 30)
        post_change = ["H2", "H3", "H4", "H5", "H6", "HG"]
        builder.emit("line-change", 1, 30, side="home", home=post_change,
            details={"change_window": "stoppage", "stoppage_event_sequence": 3},
            participants={"players_off": ["H1"], "players_on": ["H6"]})
        builder.faceoff(1, 30, home=post_change)
        builder.emit("goal", 1, 60, side="home", home=post_change,
            participants={"shooter_id": "H2", "goalie_id": "AG", "empty_net": False})
        builder.faceoff(1, 60, home=post_change)
        builder.emit("period-end", 1, 1200, home=[], away=[])
        for period in (2, 3):
            builder.emit("period-start", period, 0, home=[], away=[])
            builder.faceoff(period, 0, home=post_change)
            builder.emit("period-end", period, 1200, home=[], away=[])
        builder.emit("game-end", 3, 1200, home=[], away=[])
        shifts = []
        for period in (1, 2, 3):
            home_ids = BASE_HOME if period > 1 else None
            rows = [(pid, 0, 1200) for pid in BASE_HOME if pid != "H1"]
            if period == 1:
                rows.extend([("H1", 0, 30), ("H6", 30, 1200)])
            else:
                rows.append(("H6", 0, 1200))
            for pid, start, end in rows:
                shifts.append({"period_number": period, "team_side": "home", "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": start,
                    "end_seconds": end, "duration_seconds": end-start})
            for pid in BASE_AWAY:
                shifts.append({"period_number": period, "team_side": "away", "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 1200, "duration_seconds": 1200})
        game = builder.finish(shifts=shifts)
        self.assertEqual(self.get_check(game, "line_change_legality")["status"], "PASS")
        game["events"][3]["participants"]["players_on"] = ["H3"]
        self.assertEqual(self.get_check(game, "line_change_legality")["status"], "FAIL")

    def test_goalie_pull_empty_net_scoring_and_return_personnel(self):
        game = goalie_pull_game()
        self.assertEqual(self.get_check(game, "on_ice_personnel")["status"], "PASS")
        self.assertEqual(self.get_check(game, "penalty_and_manpower")["status"], "PASS")
        transitions = self.get_check(game, "goalie_transition_state")
        self.assertEqual(transitions["status"], "NOT_ASSESSED")
        self.assertTrue(any("stoppage/bench window" in x["message"] for x in transitions["findings"]))
        empty_net_goal = next(e for e in game["events"] if e["event_type"] == "goal" and e["team_side"] == "away")
        self.assertIsNone(empty_net_goal["participants"]["goalie_id"])
        self.assertEqual(empty_net_goal["state_after"]["score"], {"home": 1, "away": 1})
        bad = copy.deepcopy(game)
        pull = next(e for e in bad["events"] if e["event_type"] == "goalie-substitution")
        pull["participants"]["goalie_entering_id"] = "A1"
        self.assertEqual(self.get_check(bad, "goalie_transition_state")["status"], "FAIL")

    def test_regulation_overtime_shootout_and_early_decision(self):
        game = shootout_game()
        result = self.get_check(game, "overtime_and_shootout")
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(validator.audit_game(game, ruleset="2021-22")["full_rule_assessed"])
        bad = shootout_game(add_attempt_after_clinch=True)
        result = self.get_check(bad, "overtime_and_shootout")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("continued after", " ".join(x["message"] for x in result["findings"]))

    def test_shootout_rejects_player_before_projected_roster_has_all_shot(self):
        game = shootout_game()
        home_attempts = [event for event in game["events"] if event["event_type"] == "shootout-attempt"
                         and event["team_side"] == "home"]
        home_attempts[1]["participants"]["shooter_id"] = home_attempts[0]["participants"]["shooter_id"]
        result = self.get_check(game, "overtime_and_shootout")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("before every eligible", " ".join(row["message"] for row in result["findings"]))

    def test_shootout_excludes_active_misconduct_player(self):
        game = shootout_game()
        start_index = next(i for i, event in enumerate(game["events"])
                           if event["event_type"] == "period-start" and event["period_type"] == "SO")
        game["events"].insert(start_index, {
            "sequence": 0, "period_number": 3, "period_type": "REG",
            "event_type": "penalty", "team_side": "home",
            "details": {"penalty_kind": "MIS", "penalty_duration_seconds": 600},
            "participants": {"penalized_player_id": "H3", "serving_player_id": "H3"},
            "on_ice": {"home": [], "away": []},
        })
        for sequence, event in enumerate(game["events"], 1):
            event["sequence"] = sequence
        result = self.get_check(game, "overtime_and_shootout")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("not eligible", " ".join(row["message"] for row in result["findings"]))

    def test_shootout_without_projected_roster_remains_unassessed(self):
        game = shootout_game()
        del game["pregame_snapshot"]["projected_game_roster"]
        self.assertEqual(self.get_check(game, "overtime_and_shootout")["status"], "NOT_ASSESSED")

    def test_overtime_goal_ends_immediately(self):
        builder = GameBuilder().base_regulation(p1_goal=False)
        builder.emit("period-start", 4, 0, home=[], away=[])
        ot_home = ["H1", "H2", "H3", "HG"]
        ot_away = ["A1", "A2", "A3", "AG"]
        builder.faceoff(4, 0, home=ot_home, away=ot_away)
        builder.emit("goal", 4, 47, side="away", home=ot_home, away=ot_away,
            participants={"shooter_id": "A1", "goalie_id": "HG", "empty_net": False})
        builder.emit("game-end", 4, 47, home=[], away=[])
        shifts = []
        for period in (1, 2, 3):
            for side, ids in (("home", BASE_HOME), ("away", BASE_AWAY)):
                for pid in ids:
                    shifts.append({"period_number": period, "team_side": side, "player_id": pid,
                        "position": builder.players[pid]["position"], "start_seconds": 0,
                        "end_seconds": 1200, "duration_seconds": 1200})
        for side, ids in (("home", ot_home), ("away", ot_away)):
            for pid in ids:
                shifts.append({"period_number": 4, "team_side": side, "player_id": pid,
                    "position": builder.players[pid]["position"], "start_seconds": 0,
                    "end_seconds": 47, "duration_seconds": 47})
        game = builder.finish(shifts=shifts)
        self.assertEqual(self.get_check(game, "overtime_and_shootout")["status"], "PASS")
        goal_index = next(i for i, e in enumerate(game["events"])
                          if e["period_type"] == "OT" and e["event_type"] == "goal")
        illegal = copy.deepcopy(game)
        illegal["events"].insert(goal_index + 1, copy.deepcopy(illegal["events"][goal_index]))
        illegal["events"][goal_index + 1]["event_type"] = "faceoff"
        for i, event in enumerate(illegal["events"], 1):
            event["sequence"] = i
        self.assertEqual(self.get_check(illegal, "overtime_and_shootout")["status"], "FAIL")

    def test_unsupported_and_contradictory_events_are_rejected_without_repair(self):
        game = regular_game()
        invalid = copy.deepcopy(game)
        invalid["events"][2]["event_type"] = "unknown-rule-transition"
        before = json.dumps(invalid, sort_keys=True)
        check = self.get_check(invalid, "event_schema")
        self.assertEqual(check["status"], "QUARANTINED")
        self.assertIn("unknown-rule-transition", json.dumps(check["findings"]))
        self.assertEqual(json.dumps(invalid, sort_keys=True), before)
        contradictory = regular_game()
        contradictory["events"][2]["state_after"]["score"]["home"] = 9
        self.assertEqual(self.get_check(contradictory, "score_and_terminal_state")["status"], "FAIL")

    def test_validator_does_not_import_simulator_state_machine(self):
        source = (HERE / "validator.py").read_text()
        self.assertNotIn("nhl_game_state_sim", source)
        self.assertNotIn("game_state", source)
        self.assertEqual(validator.audit_game(regular_game(), ruleset="2021-22")["validator"],
                         "nhl-independent-gate1-v0.3")

    def test_official_source_fixture_records_a_real_goal_center_faceoff(self):
        fixture_path = HERE / "fixtures/official-pbp-goal-center-faceoff.json"
        fixture = json.loads(fixture_path.read_text())
        source = fixture["source"]
        self.assertEqual(source["provider"], "NHL GameCenter play-by-play")
        self.assertEqual(source["manifest_sha256"],
                         "d87e40a3387f014429377cc8dfb010cec8ca2d0e4d03d0b5bdbfacd8de9ca990")
        self.assertEqual(source["compressed_body_sha256"],
                         "a06cd9d2dedcbdae814381a3a50aac9d2e9d2e411a234ee1564a4b7ce1a4e06b")
        manifest_path = Path(source["manifest_path_outside_repository"])
        manifest_bytes = manifest_path.read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), source["manifest_sha256"])
        manifest_rows = list(csv.DictReader(manifest_bytes.decode("utf-8").splitlines()))
        manifest_row = next(row for row in manifest_rows if row["game_id"] == source["game_id"])
        body = Path(source["compressed_body_path_outside_repository"]).read_bytes()
        self.assertEqual(len(body), source["compressed_bytes"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), manifest_row["sha256_gz"])
        observed_pbp = json.loads(gzip.decompress(body))
        goal = fixture["observed_transition"]["goal"]
        restart = fixture["observed_transition"]["next_play"]
        self.assertEqual((goal["plays_index_zero_based"], restart["plays_index_zero_based"]), (119, 120))
        self.assertEqual(goal["time_in_period"], restart["time_in_period"])
        self.assertEqual((restart["xCoord"], restart["yCoord"], restart["zoneCode"]), (0, 0, "N"))
        goal_event = observed_pbp["plays"][goal["plays_index_zero_based"]]
        restart_event = observed_pbp["plays"][restart["plays_index_zero_based"]]
        self.assertEqual(goal_event["typeDescKey"], "goal")
        self.assertEqual(restart_event["typeDescKey"], "faceoff")
        self.assertEqual(goal_event["timeInPeriod"], restart_event["timeInPeriod"])
        self.assertEqual((restart_event["details"]["xCoord"], restart_event["details"]["yCoord"],
                          restart_event["details"]["zoneCode"]), (0, 0, "N"))

    def test_official_source_fixture_records_penalty_then_faceoff(self):
        fixture = json.loads((HERE / "fixtures/official-pbp-penalty-restart.json").read_text())
        source = fixture["source"]
        manifest_bytes = Path(source["manifest_path_outside_repository"]).read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), source["manifest_sha256"])
        manifest_rows = list(csv.DictReader(manifest_bytes.decode("utf-8").splitlines()))
        manifest_row = next(row for row in manifest_rows if row["game_id"] == source["game_id"])
        body = Path(source["compressed_body_path_outside_repository"]).read_bytes()
        self.assertEqual(len(body), source["compressed_bytes"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), manifest_row["sha256_gz"])
        plays = json.loads(gzip.decompress(body))["plays"]
        penalty = fixture["observed_transition"]["penalty"]
        restart = fixture["observed_transition"]["next_play"]
        self.assertEqual((penalty["plays_index_zero_based"], restart["plays_index_zero_based"]), (180, 181))
        self.assertEqual(plays[penalty["plays_index_zero_based"]]["typeDescKey"], "penalty")
        self.assertEqual(plays[penalty["plays_index_zero_based"]]["details"]["typeCode"], "MIN")
        self.assertEqual(plays[penalty["plays_index_zero_based"]]["details"]["duration"], 2)
        self.assertEqual(plays[restart["plays_index_zero_based"]]["typeDescKey"], "faceoff")
        self.assertEqual(plays[penalty["plays_index_zero_based"]]["timeInPeriod"],
                         plays[restart["plays_index_zero_based"]]["timeInPeriod"])

    def test_official_source_fixture_records_shift_boundary_at_faceoff_clock(self):
        fixture = json.loads((HERE / "fixtures/official-shift-boundary-at-faceoff.json").read_text())
        shift_source = fixture["shift_source"]
        shift_manifest_bytes = Path(shift_source["manifest_path_outside_repository"]).read_bytes()
        self.assertEqual(hashlib.sha256(shift_manifest_bytes).hexdigest(), shift_source["manifest_sha256"])
        shift_manifest = list(csv.DictReader(shift_manifest_bytes.decode("utf-8").splitlines()))
        shift_row = next(row for row in shift_manifest if row["game_id"] == shift_source["game_id"])
        shift_body = Path(shift_source["compressed_body_path_outside_repository"]).read_bytes()
        self.assertEqual(len(shift_body), shift_source["compressed_bytes"])
        self.assertEqual(hashlib.sha256(shift_body).hexdigest(), shift_row["sha256_gz"])
        shift_data = json.loads(gzip.decompress(shift_body))["data"]
        for expected in fixture["observed_shift_boundaries"]:
            found = [row for row in shift_data if str(row["playerId"]) == str(expected["player_id"])
                     and row["teamAbbrev"] == expected["team"]
                     and row["startTime"] == expected["start_time"]
                     and row["endTime"] == expected["end_time"]]
            self.assertEqual(len(found), 1)
        pbp_manifest_bytes = Path(
            "/root/lp-data/nhl-fullframe-event-audit-2026-10-21/manifests/hardened-v1/pbp_verified_manifest.csv"
        ).read_bytes()
        self.assertEqual(hashlib.sha256(pbp_manifest_bytes).hexdigest(),
                         fixture["pbp_reference"]["manifest_sha256"])
        pbp_manifest = list(csv.DictReader(pbp_manifest_bytes.decode("utf-8").splitlines()))
        pbp_row = next(row for row in pbp_manifest if row["game_id"] == shift_source["game_id"])
        pbp_body = Path("/root/lp-data/nhl-fullframe-event-audit-2026-10-21/raw/pbp/2021020001.json.gz").read_bytes()
        self.assertEqual(hashlib.sha256(pbp_body).hexdigest(), pbp_row["sha256_gz"])
        plays = json.loads(gzip.decompress(pbp_body))["plays"]
        faceoff = plays[fixture["pbp_reference"]["faceoff_index_zero_based"]]
        self.assertEqual(faceoff["eventId"], fixture["pbp_reference"]["faceoff_event_id"])
        self.assertEqual(faceoff["typeDescKey"], "faceoff")
        self.assertEqual(faceoff["timeInPeriod"], fixture["pbp_reference"]["time_in_period"])

    def test_official_source_fixture_records_shootout_ending_after_two_pairs(self):
        fixture = json.loads((HERE / "fixtures/official-pbp-shootout-early-decision.json").read_text())
        source = fixture["source"]
        manifest_bytes = Path(source["manifest_path_outside_repository"]).read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), source["manifest_sha256"])
        manifest = list(csv.DictReader(manifest_bytes.decode("utf-8").splitlines()))
        row = next(row for row in manifest if row["game_id"] == source["game_id"])
        body = Path(source["compressed_body_path_outside_repository"]).read_bytes()
        self.assertEqual(len(body), source["compressed_bytes"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), row["sha256_gz"])
        pbp = json.loads(gzip.decompress(body))
        observed = fixture["observed_shootout"]
        self.assertEqual(pbp["gameOutcome"]["lastPeriodType"], "SO")
        self.assertEqual(pbp["homeTeam"]["score"], observed["official_final_score"]["home"])
        self.assertEqual(pbp["awayTeam"]["score"], observed["official_final_score"]["away"])
        attempts = [pbp["plays"][item["plays_index_zero_based"]] for item in observed["attempts"]]
        self.assertEqual([event["typeDescKey"] for event in attempts],
                         [item["event_type"] for item in observed["attempts"]])
        self.assertEqual([event["details"]["eventOwnerTeamId"] for event in attempts],
                         [4, 23, 4, 23])
        self.assertEqual(sum(event["typeDescKey"] == "goal" for event in attempts), 2)
        self.assertEqual(pbp["plays"][observed["completion_index"]]["typeDescKey"],
                         "shootout-complete")


if __name__ == "__main__":
    unittest.main()
