from __future__ import annotations

import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from prospective import (  # noqa: E402
    LookaheadFeatureError, PregameFeature, PregameSnapshot, SimulationRequest,
)
from replay_data import (  # noqa: E402
    InputIntegrityError, load_bundle, verify_source_body,
)
from replay_model import (  # noqa: E402
    GameDefinition, GameProvenance, GameStateMachine, NormalizedEvent, Quality,
    SourceIdentity, TargetValue, compare_team_targets, parse_situation_code,
    reconcile_player_targets, replay_game,
)
from run_replay import replay_population  # noqa: E402


def _source(kind: str = "pbp", payload_rows: int = 5) -> SourceIdentity:
    return SourceIdentity(
        source_kind=kind, source_url="https://example.invalid/source", http_status=200,
        content_type="application/json", payload_rows=payload_rows,
        sha256_raw="a" * 64, sha256_gz="b" * 64, bytes_raw=10, bytes_gz=8,
        retrieved_at_utc="2026-10-21T00:00:00+00:00", evidence_origin="test",
        attempts=None, request_duration_seconds="", request_elapsed_with_pacing_seconds="",
        sample_event_manifest_sha256="", sample_source_commit="", source_identity_basis="test",
        prior_manifest_sha256="c" * 64, verification_disposition="ACCEPT",
        prior_manifest_disposition="ACCEPT", reason_codes=(),
        canonical_frame_sha256="d" * 64, audit_version="test-v1",
    )


def _definition(home_score=0, away_score=0, home_sog=0, away_sog=0,
                *, score_disposition="ACCEPT", sog_disposition="ACCEPT") -> GameDefinition:
    return GameDefinition(
        game_id="9999999999", season=2025, game_date="2025-01-01",
        home_team="HOM", away_team="AWY", home_team_id=10, away_team_id=8,
        official_home_score=home_score, official_away_score=away_score,
        official_home_sog=home_sog, official_away_sog=away_sog,
        score_disposition=score_disposition, sog_disposition=sog_disposition,
    )


def _provenance(payload_rows=5) -> GameProvenance:
    return GameProvenance(
        game_id="9999999999", season=2025,
        pbp=_source("pbp", payload_rows), shifts=_source("shifts", 10),
        frame_sha256="d" * 64, full_frame_games_sha256="e" * 64,
    )


def _quality(**changes) -> Quality:
    values = {
        "source_order": "ACCEPT", "event": "ACCEPT", "team_count": "ACCEPT",
        "player_identity": "ACCEPT", "shooter_identity": "ACCEPT",
        "goalie_identity": "ACCEPT", "goalie_event": "ACCEPT", "spatial": "ACCEPT",
        "shot_type": "ACCEPT", "penalty_timing": "ACCEPT", "penalty_duration": "ACCEPT",
        "penalty_identity": "ACCEPT", "period_number": "ACCEPT",
        "period_number_reason_code": "", "situation_deployment": "ACCEPT",
        "situation_shift_status": "MATCH", "shooter_shift_status": "ON_ACCEPTED_SHIFT",
        "shooter_on_ice": "ACCEPT", "goalie_shift_status": "DIRECT_ID_MATCHES_ACCEPTED_SHIFT",
        "goalie_shift_comparison": "ACCEPT", "reason_codes": (),
    }
    values.update(changes)
    return Quality(**values)


def _event(sort_order: int, event_id: str, event_type: str, *, period=1, period_type="REG",
           owner=10, side="home", situation="1551", shooter=None, goalie=None,
           quality=None, penalty_duration=None) -> NormalizedEvent:
    return NormalizedEvent(
        game_id="9999999999", season=2025, source_event_id=event_id,
        source_play_index=sort_order - 1, publisher_sort_order=sort_order,
        event_type=event_type, period_number=period, period_type=period_type,
        time_in_period="05:00", event_owner_team_id=owner,
        event_owner_side_source=side if owner is not None else None,
        credited_shooter_id=shooter, shooter_id_source="shootingPlayerId" if shooter else None,
        goalie_in_net_id=goalie, situation_code=situation, source_strength_state=None,
        ordinary_shot_eligible=period_type != "SO", shot_x=None, shot_y=None,
        shot_type="wrist" if event_type in {"goal", "shot-on-goal"} else None,
        zone_code=None, miss_reason=None, penalty_type_code="minor" if event_type == "penalty" else None,
        penalty_reason=None,
        penalty_duration_minutes=Decimal(penalty_duration) if penalty_duration is not None else None,
        penalty_committed_by_player_id=900 if event_type == "penalty" else None,
        penalty_drawn_by_player_id=901 if event_type == "penalty" else None,
        penalty_served_by_player_id=None, source_retrieved_at_utc="2026-10-21T00:00:00+00:00",
        provenance=_provenance(5), quality=quality or _quality(),
    )


class ReplayStateMachineTests(unittest.TestCase):
    def test_regulation_overtime_manpower_penalty_and_goalie_targets(self):
        events = [
            _event(1, "1", "goal", owner=10, side="home", shooter=101, goalie=201),
            _event(2, "2", "shot-on-goal", owner=8, side="away", shooter=102, goalie=202),
            _event(3, "3", "blocked-shot", owner=10, side="home", situation="1541"),
            _event(4, "4", "penalty", owner=8, side="away", situation="1541", penalty_duration="2"),
            _event(5, "5", "goal", period=4, period_type="OT", owner=8, side="away",
                   shooter=103, goalie=201),
        ]
        state = replay_game(
            _definition(home_score=1, away_score=1, home_sog=2, away_sog=2),
            _provenance(len(events)), events)
        self.assertEqual(state.regulation_score, {"home": 1})
        self.assertEqual(state.overtime_score, {"away": 1})
        self.assertEqual(state.shot_attempts, {"home": 2, "away": 2})
        self.assertEqual(state.shots_on_goal, {"home": 1, "away": 2})
        self.assertEqual(state.player_sog, {"101": 1, "102": 1, "103": 1})
        self.assertEqual(state.goalie_stats["201"], {"GOALS_AGAINST": 2, "SHOTS_AGAINST": 2})
        self.assertEqual(state.goalie_stats["202"], {"SHOTS_AGAINST": 1, "SAVES": 1})
        self.assertEqual(state.penalty_calls[0].duration_minutes, 2)
        self.assertIn("SERVICE_INTERVAL_NOT_INFERRED", state.penalty_calls[0].service_observation)
        self.assertTrue(any(item[2].skater_advantage == "away" for item in state.manpower_transitions))
        self.assertTrue(compare_team_targets(state)["score_match"])

    def test_goalie_substitution_and_empty_net_are_direct_observations(self):
        events = [
            _event(1, "1", "shot-on-goal", owner=10, side="home", shooter=101, goalie=201),
            _event(2, "2", "shot-on-goal", owner=10, side="home", shooter=102, goalie=202),
            _event(3, "3", "goal", owner=10, side="home", shooter=103, goalie=None,
                   situation="0541", quality=_quality(goalie_event="QUARANTINE",
                                                       goalie_identity="QUARANTINE")),
        ]
        state = replay_game(_definition(home_score=1, home_sog=3), _provenance(3), events)
        self.assertEqual(len(state.goalie_change_observations), 1)
        self.assertEqual(state.goalie_change_observations[0][2:], (201, 202))
        self.assertEqual(state.goalie_observations[-1].status,
                         "EMPTY_NET_DIRECTLY_INDICATED_BY_SITUATION_CODE")
        self.assertNotIn("GOALS_AGAINST", state.goalie_stats.get("201", {}))

    def test_explicit_delayed_penalty_type_does_not_create_a_service_clock(self):
        event = _event(1, "1", "delayed-penalty", owner=8, side="away",
                       quality=_quality(team_count="NOT_APPLICABLE"))
        state = GameStateMachine(_definition(), _provenance(1)).step(event)
        self.assertEqual(state.source_component_counts["explicit_delayed_penalty_event_type"], 1)
        self.assertEqual(state.penalty_calls, [])
        self.assertEqual(len(state.delayed_penalty_observations), 1)
        self.assertEqual(state.delayed_penalty_observations[0].event_id, "1")

    def test_shootout_is_separate_and_winner_adjustment_is_only_final_representation(self):
        events = [
            _event(1, "1", "goal", owner=10, side="home", shooter=101, goalie=201),
            _event(2, "2", "goal", period=5, period_type="SO", owner=10, side="home",
                   shooter=101, goalie=201, situation="0000",
                   quality=_quality(team_count="NOT_APPLICABLE", player_identity="NOT_APPLICABLE",
                                    shooter_identity="NOT_APPLICABLE", goalie_event="NOT_APPLICABLE")),
            _event(3, "3", "missed-shot", period=5, period_type="SO", owner=8, side="away",
                   situation="0000", quality=_quality(team_count="NOT_APPLICABLE",
                       player_identity="NOT_APPLICABLE", shooter_identity="NOT_APPLICABLE",
                       goalie_event="NOT_APPLICABLE")),
        ]
        state = replay_game(
            _definition(home_score=2, away_score=0, home_sog=1, away_sog=0),
            _provenance(len(events)), events)
        self.assertEqual(state.shots_on_goal, {"home": 1})
        self.assertEqual(state.ordinary_score, {"home": 1})
        self.assertEqual(state.shootout_attempts, {"home": 1, "away": 1})
        self.assertEqual(state.shootout_goals, {"home": 1})
        self.assertEqual(state.shootout_adjusted_score, {"home": 2})
        self.assertTrue(compare_team_targets(state)["score_match"])

    def test_period_regression_is_flagged_without_reordering_publisher_events(self):
        events = [
            _event(10, "10", "goal", period=3, owner=10, side="home"),
            _event(11, "11", "goal", period=2, owner=8, side="away",
                   quality=_quality(period_number="QUARANTINE",
                                    period_number_reason_code="PBP_PERIOD_NUMBER_SEQUENCE_REGRESSION")),
        ]
        state = replay_game(
            _definition(home_score=1, away_score=1, home_sog=1, away_sog=1),
            _provenance(2), events)
        self.assertEqual(state.last_sort_order, 11)
        self.assertEqual(state.period_regression_events, 1)
        self.assertEqual(state.ordinary_score, {"home": 1, "away": 1})

    def test_invalid_publisher_order_fails_instead_of_falling_back(self):
        machine = GameStateMachine(_definition(), _provenance())
        machine.step(_event(20, "20", "stoppage", owner=None, side=None,
                            quality=_quality(team_count="NOT_APPLICABLE")))
        with self.assertRaisesRegex(ValueError, "PUBLISHER_ORDER_NOT_STRICT"):
            machine.step(_event(19, "19", "stoppage", owner=None, side=None,
                                quality=_quality(team_count="NOT_APPLICABLE")))

    def test_quarantined_label_cannot_become_target(self):
        event = _event(1, "1", "shot-on-goal", shooter=101, goalie=201)
        state = GameStateMachine(_definition(home_sog=1), _provenance(1)).step(event)
        target = TargetValue(
            game_id="9999999999", player_id="101", statistic="SOG", official_value=1,
            accepted_value=None, quality_status="QUARANTINED", reason_code="LABEL_QUARANTINED",
            audit_reason_code="LABEL_QUARANTINED", source_issue_id="q1",
            eligible_training=False, eligible_evaluation=False, eligible_grading=False,
            audit_eligible_training=False, audit_eligible_evaluation=False,
            audit_eligible_grading=False,
            audit_event_count=None, audit_event_count_match=False,
            audit_event_disposition="QUARANTINE",
            purpose_values={"training": None, "evaluation": None, "grading": None},
        )
        result = reconcile_player_targets(state, [target], purpose="training")[0]
        self.assertFalse(result["eligible_target"])
        self.assertEqual(result["disposition"], "QUARANTINE")

    def test_situation_code_is_raw_manpower_not_tracking(self):
        parsed = parse_situation_code("0540")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.away_skaters, 5)
        self.assertEqual(parsed.home_skaters, 4)
        self.assertEqual(parsed.empty_net_sides, ("away", "home"))
        self.assertIsNone(parse_situation_code("abcd"))


class ProspectiveBoundaryTests(unittest.TestCase):
    def test_pregame_boundary_rejects_lookahead_and_has_no_replay_argument(self):
        start = datetime(2025, 1, 1, 20, tzinfo=timezone.utc)
        good = PregameFeature(
            key="prior_goalie_toi", value=3600,
            available_at_utc=datetime(2024, 12, 31, 23, tzinfo=timezone.utc),
            source_kind="published_prior_game", source_key="prior-1",
            source_sha256="a" * 64, quality_disposition="ACCEPT")
        snapshot = PregameSnapshot("x", start, 10, 8, (good,))
        request = SimulationRequest(snapshot, random_seed=7)
        self.assertEqual([item.name for item in fields(SimulationRequest)], ["pregame", "random_seed"])
        self.assertEqual(request.pregame, snapshot)
        late = PregameFeature(
            key="postgame_sog", value=3, available_at_utc=datetime(2025, 1, 1, 21, tzinfo=timezone.utc),
            source_kind="postgame_boxscore", source_key="actual", source_sha256="b" * 64,
            quality_disposition="ACCEPT")
        with self.assertRaises(LookaheadFeatureError):
            PregameSnapshot("x", start, 10, 8, (late,))


class SourceBodyFailureInjectionTests(unittest.TestCase):
    def test_compressed_body_hash_failure_is_rejected(self):
        payload = {
            "id": "9999999999",
            "plays": [{"eventId": 1, "sortOrder": 1, "periodDescriptor": {}}],
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        with tempfile.TemporaryDirectory() as tmp:
            raw_dir = Path(tmp)
            body_dir = raw_dir / "pbp"
            body_dir.mkdir()
            body_path = body_dir / "9999999999.json.gz"
            with body_path.open("wb") as raw_file:
                with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=0) as compressed:
                    compressed.write(raw)
            gz_bytes = body_path.read_bytes()
            sidecar = {
                "game_id": "9999999999", "kind": "pbp", "bytes_raw": len(raw),
                "bytes_gz": len(gz_bytes), "rows": 1,
                "sha256_raw": hashlib.sha256(raw).hexdigest(),
                "sha256_gz": hashlib.sha256(gz_bytes).hexdigest(),
                "http_status": 200, "content_type": "application/json",
            }
            (body_dir / "9999999999.meta.json").write_text(json.dumps(sidecar))
            source = _source("pbp", 1)
            source = SourceIdentity(
                **{**source.__dict__, "sha256_raw": sidecar["sha256_raw"],
                   "sha256_gz": sidecar["sha256_gz"], "bytes_raw": len(raw),
                   "bytes_gz": len(gz_bytes)})
            verify_source_body(raw_dir, "9999999999", source)
            raw_hash_mismatch = SourceIdentity(
                **{**source.__dict__, "sha256_raw": "f" * 64})
            with self.assertRaisesRegex(InputIntegrityError, "RAW_DECOMPRESSED_BODY_MISMATCH"):
                verify_source_body(raw_dir, "9999999999", raw_hash_mismatch)
            body_path.write_bytes(gz_bytes + b"tamper")
            with self.assertRaisesRegex(InputIntegrityError, "RAW_COMPRESSED_BODY_MISMATCH"):
                verify_source_body(raw_dir, "9999999999", source)


class PinnedFullFrameRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = load_bundle()
        cohort = {"2018020003", "2018020001", "2018020019", "2018020002",
                  "2019020372", "2020020056", "2018020164", "2018020751"}
        cls.result = replay_population(cls.bundle, game_ids=cohort)

    def test_real_regression_cohort_covers_required_cases(self):
        cohort = {"2018020003", "2018020001", "2018020019", "2018020002",
                  "2019020372", "2020020056", "2018020164", "2018020751"}
        result = self.result
        self.assertEqual(result["games_replayed"], len(cohort))
        self.assertEqual(result["team_score"]["matched"], len(cohort))
        self.assertEqual(result["team_sog"]["quarantined"], 3)
        self.assertTrue(result["cohort_games"]["2020020056"]["score_match"])
        self.assertEqual(result["cohort_games"]["2020020056"]["metric_duplicate_shift_charts"], 1)
        self.assertGreater(result["cohort_games"]["2018020164"]["period_regression_events"], 0)
        self.assertGreater(result["cohort_games"]["2018020019"]["shootout_attempts"].get("home", 0) +
                           result["cohort_games"]["2018020019"]["shootout_attempts"].get("away", 0), 0)

    def test_real_event_reader_retains_provenance_and_component_quality(self):
        first = self.result["cohort_games"]["2018020001"]["first_event_provenance"]
        self.assertEqual(first["pbp_sha256_raw"],
                         "b487b257c92b8bdb29806419283cda1728249a23a298188a3f936cadf9dbfed4")
        self.assertEqual(first["shift_source_kind"], "shifts")
        self.assertEqual(first["period_type"], "REG")
        self.assertEqual(first["time_in_period"], "00:00")
        self.assertEqual(first["event_disposition"], "ACCEPT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
