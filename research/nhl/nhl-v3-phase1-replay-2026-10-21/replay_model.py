"""Pure deterministic NHL event replay primitives.

Historical observed events enter through :mod:`replay_data`; this module has no
network, filesystem, model-fitting, or random-number dependency.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


SHOT_EVENTS = frozenset({"goal", "shot-on-goal", "missed-shot", "blocked-shot"})
SOG_EVENTS = frozenset({"goal", "shot-on-goal"})
ORDINARY_PERIOD_TYPES = frozenset({"REG", "OT"})
TARGET_STATISTICS = frozenset({"SOG", "SAVES", "SHOTS_AGAINST", "GOALS_AGAINST"})
ACCEPT = "ACCEPT"


class ReplayIntegrityError(ValueError):
    """Raised when an input violates a pinned chronology or identity contract."""


@dataclass(frozen=True)
class SourceIdentity:
    source_kind: str
    source_url: str
    http_status: int
    content_type: str
    payload_rows: int
    sha256_raw: str
    sha256_gz: str
    bytes_raw: int
    bytes_gz: int
    retrieved_at_utc: str
    evidence_origin: str
    attempts: int | None
    request_duration_seconds: str
    request_elapsed_with_pacing_seconds: str
    sample_event_manifest_sha256: str
    sample_source_commit: str
    source_identity_basis: str
    prior_manifest_sha256: str
    verification_disposition: str
    prior_manifest_disposition: str
    reason_codes: tuple[str, ...]
    canonical_frame_sha256: str
    audit_version: str


@dataclass(frozen=True)
class GameProvenance:
    game_id: str
    season: int
    pbp: SourceIdentity
    shifts: SourceIdentity
    frame_sha256: str
    full_frame_games_sha256: str


@dataclass(frozen=True)
class Quality:
    source_order: str
    event: str
    team_count: str
    player_identity: str
    shooter_identity: str
    goalie_identity: str
    goalie_event: str
    spatial: str
    shot_type: str
    penalty_timing: str
    penalty_duration: str
    penalty_identity: str
    period_number: str
    period_number_reason_code: str
    situation_deployment: str
    situation_shift_status: str
    shooter_shift_status: str
    shooter_on_ice: str
    goalie_shift_status: str
    goalie_shift_comparison: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class NormalizedEvent:
    game_id: str
    season: int
    source_event_id: str
    source_play_index: int
    publisher_sort_order: int
    event_type: str
    period_number: int
    period_type: str
    time_in_period: str
    event_owner_team_id: int | None
    event_owner_side_source: str | None
    credited_shooter_id: int | None
    shooter_id_source: str | None
    goalie_in_net_id: int | None
    situation_code: str | None
    source_strength_state: str | None
    ordinary_shot_eligible: bool | None
    shot_x: Decimal | None
    shot_y: Decimal | None
    shot_type: str | None
    zone_code: str | None
    miss_reason: str | None
    penalty_type_code: str | None
    penalty_reason: str | None
    penalty_duration_minutes: Decimal | None
    penalty_committed_by_player_id: int | None
    penalty_drawn_by_player_id: int | None
    penalty_served_by_player_id: int | None
    source_retrieved_at_utc: str
    provenance: GameProvenance
    quality: Quality


@dataclass(frozen=True)
class NormalizedShiftInterval:
    game_id: str
    season: int
    source_shift_id: str
    player_id: str
    player_type: str
    period_number: int
    start_seconds: int | None
    end_seconds: int | None
    duration_seconds: int | None
    official_toi_seconds: int | None
    player_game_shift_toi_seconds: int | None
    toi_delta_seconds: int | None
    disposition: str
    reason_codes: tuple[str, ...]
    provenance: GameProvenance


@dataclass(frozen=True)
class GameDefinition:
    game_id: str
    season: int
    game_date: str
    home_team: str
    away_team: str
    home_team_id: int
    away_team_id: int
    official_home_score: int
    official_away_score: int
    official_home_sog: int
    official_away_sog: int
    score_disposition: str
    sog_disposition: str


@dataclass(frozen=True)
class Manpower:
    away_goalie_present: bool
    away_skaters: int
    home_skaters: int
    home_goalie_present: bool

    @property
    def empty_net_sides(self) -> tuple[str, ...]:
        missing = []
        if not self.away_goalie_present:
            missing.append("away")
        if not self.home_goalie_present:
            missing.append("home")
        return tuple(missing)

    @property
    def skater_advantage(self) -> str:
        if self.home_skaters > self.away_skaters:
            return "home"
        if self.away_skaters > self.home_skaters:
            return "away"
        return "even"


@dataclass(frozen=True)
class PenaltyCall:
    event_id: str
    publisher_sort_order: int
    period_number: int
    time_in_period: str
    event_owner_team_id: int | None
    committed_by_player_id: int | None
    drawn_by_player_id: int | None
    served_by_player_id: int | None
    duration_minutes: Decimal | None
    penalty_type: str | None
    reason: str | None
    identity_disposition: str
    timing_disposition: str
    duration_disposition: str
    service_observation: str


@dataclass(frozen=True)
class GoalieObservation:
    event_id: str
    sort_order: int
    defending_side: str
    goalie_id: int | None
    status: str


@dataclass(frozen=True)
class DelayedPenaltyObservation:
    event_id: str
    sort_order: int
    period_number: int
    time_in_period: str
    event_type: str
    event_owner_team_id: int | None
    situation_code: str | None


@dataclass(frozen=True)
class TargetValue:
    game_id: str
    player_id: str
    statistic: str
    official_value: int | None
    accepted_value: int | None
    quality_status: str
    reason_code: str
    audit_reason_code: str
    source_issue_id: str
    eligible_training: bool
    eligible_evaluation: bool
    eligible_grading: bool
    audit_eligible_training: bool
    audit_eligible_evaluation: bool
    audit_eligible_grading: bool
    audit_event_count: int | None
    audit_event_count_match: bool
    audit_event_disposition: str
    purpose_values: Mapping[str, int | None]

    @property
    def eligible_splits(self) -> tuple[str, ...]:
        return tuple(name for name, flag in (
            ("training", self.eligible_training),
            ("evaluation", self.eligible_evaluation),
            ("grading", self.eligible_grading),
        ) if flag)


@dataclass
class GameReplay:
    definition: GameDefinition
    provenance: GameProvenance
    event_count: int = 0
    last_sort_order: int | None = None
    seen_event_ids: set[str] = field(default_factory=set)
    current_period_number: int | None = None
    current_period_type: str | None = None
    period_regression_events: int = 0
    score_by_period: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter))
    shot_attempts: Counter[str] = field(default_factory=Counter)
    shots_on_goal: Counter[str] = field(default_factory=Counter)
    shootout_attempts: Counter[str] = field(default_factory=Counter)
    shootout_goals: Counter[str] = field(default_factory=Counter)
    shootout_period_observed: bool = False
    player_sog: Counter[str] = field(default_factory=Counter)
    goalie_stats: dict[str, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))
    shot_event_counts: Counter[str] = field(default_factory=Counter)
    source_component_counts: Counter[str] = field(default_factory=Counter)
    manpower_transitions: list[tuple[int, str, Manpower]] = field(default_factory=list)
    penalty_calls: list[PenaltyCall] = field(default_factory=list)
    delayed_penalty_observations: list[DelayedPenaltyObservation] = field(default_factory=list)
    goalie_observations: list[GoalieObservation] = field(default_factory=list)
    goalie_change_observations: list[tuple[int, str, int, int]] = field(default_factory=list)
    last_manpower: Manpower | None = None
    last_goalie_by_side: dict[str, int] = field(default_factory=dict)
    goalie_state_by_side: dict[str, str] = field(default_factory=dict)
    event_quality_counts: Counter[str] = field(default_factory=Counter)

    @property
    def ordinary_score(self) -> Counter[str]:
        total: Counter[str] = Counter()
        for period_type in ("REG", "OT"):
            total.update(self.score_by_period.get(period_type, Counter()))
        return total

    @property
    def regulation_score(self) -> Counter[str]:
        return self.score_by_period.get("REG", Counter())

    @property
    def overtime_score(self) -> Counter[str]:
        return self.score_by_period.get("OT", Counter())

    @property
    def shootout_adjusted_score(self) -> Counter[str]:
        """Historical final score representation; SO attempts stay separate."""
        adjusted = self.ordinary_score.copy()
        if self.shootout_period_observed:
            if self.definition.official_home_score == self.definition.official_away_score:
                raise ReplayIntegrityError(
                    f"TIED_OFFICIAL_SCORE_WITH_SHOOTOUT {self.definition.game_id}")
            winner = ("home" if self.definition.official_home_score >
                      self.definition.official_away_score else "away")
            adjusted[winner] += 1
        return adjusted


def parse_situation_code(value: str | None) -> Manpower | None:
    """Parse direct four-digit situation code: away G, away skaters, home skaters, home G."""
    if value is None or len(value) != 4 or not value.isdigit():
        return None
    away_goalie, away_skaters, home_skaters, home_goalie = (int(c) for c in value)
    if away_goalie not in (0, 1) or home_goalie not in (0, 1):
        return None
    if not (3 <= away_skaters <= 6 and 3 <= home_skaters <= 6):
        return None
    return Manpower(bool(away_goalie), away_skaters, home_skaters, bool(home_goalie))


def _side_for_team(game: GameDefinition, team_id: int | None) -> str | None:
    if team_id is None:
        return None
    if team_id == game.home_team_id:
        return "home"
    if team_id == game.away_team_id:
        return "away"
    return None


def _is_accept(value: str) -> bool:
    return value == ACCEPT


class GameStateMachine:
    """Deterministic, publisher-order replay with component-level gates."""

    def __init__(self, definition: GameDefinition, provenance: GameProvenance):
        self.state = GameReplay(definition=definition, provenance=provenance)

    def step(self, event: NormalizedEvent) -> GameReplay:
        state = self.state
        if event.game_id != state.definition.game_id:
            raise ReplayIntegrityError(
                f"CROSS_GAME_EVENT expected={state.definition.game_id} got={event.game_id}")
        if event.publisher_sort_order <= 0:
            raise ReplayIntegrityError(f"INVALID_SORT_ORDER {event.game_id}/{event.source_event_id}")
        if state.last_sort_order is not None and event.publisher_sort_order <= state.last_sort_order:
            raise ReplayIntegrityError(
                f"PUBLISHER_ORDER_NOT_STRICT {event.game_id}/{event.publisher_sort_order}")
        if event.source_event_id in state.seen_event_ids:
            raise ReplayIntegrityError(f"DUPLICATE_EVENT_ID {event.game_id}/{event.source_event_id}")
        if not _is_accept(event.quality.source_order):
            raise ReplayIntegrityError(
                f"UNTRUSTED_CHRONOLOGY {event.game_id}/{event.source_event_id}/"
                f"{event.quality.source_order}")
        state.last_sort_order = event.publisher_sort_order
        state.seen_event_ids.add(event.source_event_id)
        state.event_count += 1
        state.event_quality_counts[event.quality.event] += 1
        if event.quality.period_number != ACCEPT:
            state.period_regression_events += 1
        if event.period_type == "SO":
            state.shootout_period_observed = True

        if (state.current_period_number is not None and
                event.period_number < state.current_period_number and
                event.quality.period_number == ACCEPT):
            raise ReplayIntegrityError(
                f"UNMARKED_PERIOD_REGRESSION {event.game_id}/{event.source_event_id}")
        state.current_period_number = event.period_number
        state.current_period_type = event.period_type

        owner_side = _side_for_team(state.definition, event.event_owner_team_id)
        if (event.quality.event == ACCEPT and owner_side is not None and
                event.event_owner_side_source and event.event_owner_side_source != owner_side):
            raise ReplayIntegrityError(
                f"EVENT_OWNER_SIDE_CONFLICT {event.game_id}/{event.source_event_id}")
        if event.quality.team_count == ACCEPT:
            if event.event_owner_team_id is None or owner_side is None:
                raise ReplayIntegrityError(
                    f"ACCEPTED_EVENT_OWNER_UNRESOLVED {event.game_id}/{event.source_event_id}")

        manpower = parse_situation_code(event.situation_code)
        if manpower is not None:
            state.source_component_counts["situation_code_valid"] += 1
            if manpower != state.last_manpower:
                state.manpower_transitions.append(
                    (event.publisher_sort_order, event.source_event_id, manpower))
                state.last_manpower = manpower
        else:
            state.source_component_counts["situation_code_unavailable_or_invalid"] += 1

        if event.event_type == "penalty":
            state.penalty_calls.append(self._penalty_call(event, manpower))
        if event.event_type.lower().startswith("delayed-penalty"):
            state.source_component_counts["explicit_delayed_penalty_event_type"] += 1
            state.delayed_penalty_observations.append(DelayedPenaltyObservation(
                event_id=event.source_event_id,
                sort_order=event.publisher_sort_order,
                period_number=event.period_number,
                time_in_period=event.time_in_period,
                event_type=event.event_type,
                event_owner_team_id=event.event_owner_team_id,
                situation_code=event.situation_code,
            ))

        if event.event_type in SHOT_EVENTS:
            state.shot_event_counts[f"{event.period_type}:{event.event_type}"] += 1
            if event.goalie_in_net_id is not None:
                state.source_component_counts["raw_direct_goalie_id_on_shot_family"] += 1
            if event.quality.goalie_event == ACCEPT:
                state.source_component_counts["goalie_event_attribution_accept"] += 1
            self._shot_event(event, owner_side, manpower)
        return state

    @staticmethod
    def _penalty_call(event: NormalizedEvent, manpower: Manpower | None) -> PenaltyCall:
        service = "PENALTY_CALL_RECORDED_SERVICE_INTERVAL_NOT_INFERRED"
        if manpower is not None:
            service += (f";MANPOWER_AT_CALL={manpower.home_skaters}v{manpower.away_skaters}"
                        f";EMPTY_NET={','.join(manpower.empty_net_sides) or 'none'}")
        return PenaltyCall(
            event_id=event.source_event_id,
            publisher_sort_order=event.publisher_sort_order,
            period_number=event.period_number,
            time_in_period=event.time_in_period,
            event_owner_team_id=event.event_owner_team_id,
            committed_by_player_id=event.penalty_committed_by_player_id,
            drawn_by_player_id=event.penalty_drawn_by_player_id,
            served_by_player_id=event.penalty_served_by_player_id,
            duration_minutes=event.penalty_duration_minutes,
            penalty_type=event.penalty_type_code,
            reason=event.penalty_reason,
            identity_disposition=event.quality.penalty_identity,
            timing_disposition=event.quality.penalty_timing,
            duration_disposition=event.quality.penalty_duration,
            service_observation=service,
        )

    def _shot_event(self, event: NormalizedEvent, owner_side: str | None,
                    manpower: Manpower | None) -> None:
        state = self.state
        if event.period_type == "SO":
            if owner_side is not None and event.quality.event == ACCEPT:
                state.shootout_attempts[owner_side] += 1
                if event.event_type == "goal":
                    state.shootout_goals[owner_side] += 1
            else:
                state.source_component_counts["shootout_attempt_not_accepted"] += 1
            self._record_goalie(event, owner_side, manpower, ordinary=False)
            return
        if event.period_type not in ORDINARY_PERIOD_TYPES:
            state.source_component_counts["shot_unknown_period_excluded"] += 1
            return
        if event.quality.event != ACCEPT or event.quality.team_count != ACCEPT:
            state.source_component_counts["shot_team_count_not_accepted"] += 1
            return
        if owner_side is None:
            raise ReplayIntegrityError(
                f"SHOT_OWNER_UNRESOLVED {event.game_id}/{event.source_event_id}")

        state.shot_attempts[owner_side] += 1
        if event.event_type in SOG_EVENTS:
            state.shots_on_goal[owner_side] += 1
        if event.event_type == "goal":
            state.score_by_period[event.period_type][owner_side] += 1

        if event.event_type in SOG_EVENTS and event.quality.player_identity == ACCEPT:
            if event.credited_shooter_id is not None:
                state.player_sog[str(event.credited_shooter_id)] += 1
            else:
                state.source_component_counts["player_sog_attribution_quarantined"] += 1
        elif event.event_type in SOG_EVENTS:
            state.source_component_counts["player_sog_attribution_quarantined"] += 1

        self._record_goalie(event, owner_side, manpower, ordinary=True)

    def _record_goalie(self, event: NormalizedEvent, shooter_side: str | None,
                       manpower: Manpower | None, *, ordinary: bool) -> None:
        state = self.state
        if event.event_type not in SOG_EVENTS:
            return
        if shooter_side is None:
            return
        defending_side = "away" if shooter_side == "home" else "home"
        explicit_empty = (manpower is not None and defending_side in manpower.empty_net_sides)
        if event.quality.goalie_event == ACCEPT and event.goalie_in_net_id is not None:
            goalie_id = str(event.goalie_in_net_id)
            state.goalie_observations.append(GoalieObservation(
                event.source_event_id, event.publisher_sort_order, defending_side,
                event.goalie_in_net_id, "DIRECT_ID_ACCEPTED"))
            previous = state.last_goalie_by_side.get(defending_side)
            previous_status = state.goalie_state_by_side.get(defending_side)
            if previous is not None and previous != event.goalie_in_net_id:
                state.goalie_change_observations.append((
                    event.publisher_sort_order, defending_side, previous, event.goalie_in_net_id))
            elif previous is None and previous_status == "EMPTY_NET_OBSERVED":
                state.source_component_counts["goalie_return_after_empty_net"] += 1
            state.last_goalie_by_side[defending_side] = event.goalie_in_net_id
            state.goalie_state_by_side[defending_side] = "GOALIE_ID_DIRECTLY_OBSERVED"
            if ordinary:
                if event.event_type == "goal":
                    state.goalie_stats[goalie_id]["GOALS_AGAINST"] += 1
                if event.event_type in SOG_EVENTS:
                    state.goalie_stats[goalie_id]["SHOTS_AGAINST"] += 1
                    if event.event_type == "shot-on-goal":
                        state.goalie_stats[goalie_id]["SAVES"] += 1
        elif explicit_empty:
            state.goalie_observations.append(GoalieObservation(
                event.source_event_id, event.publisher_sort_order, defending_side,
                None, "EMPTY_NET_DIRECTLY_INDICATED_BY_SITUATION_CODE"))
            state.goalie_state_by_side[defending_side] = "EMPTY_NET_OBSERVED"
        else:
            state.goalie_observations.append(GoalieObservation(
                event.source_event_id, event.publisher_sort_order, defending_side,
                None, "GOALIE_ID_UNAVAILABLE_OR_QUARANTINED"))
            state.goalie_state_by_side[defending_side] = "GOALIE_ID_UNVERIFIED"


def replay_game(definition: GameDefinition, provenance: GameProvenance,
                events: Iterable[NormalizedEvent]) -> GameReplay:
    machine = GameStateMachine(definition, provenance)
    for event in events:
        machine.step(event)
    state = machine.state
    if state.event_count != provenance.pbp.payload_rows:
        raise ReplayIntegrityError(
            f"PBP_EVENT_ROW_COUNT_MISMATCH {definition.game_id}: "
            f"{state.event_count}!={provenance.pbp.payload_rows}")
    return state


def compare_team_targets(state: GameReplay) -> dict[str, object]:
    ordinary = state.ordinary_score
    adjusted = state.shootout_adjusted_score
    score_actual = {
        "home": state.definition.official_home_score,
        "away": state.definition.official_away_score,
    }
    sog_actual = {
        "home": state.definition.official_home_sog,
        "away": state.definition.official_away_sog,
    }
    score_match = all(adjusted[side] == score_actual[side] for side in ("home", "away"))
    sog_match = all(state.shots_on_goal[side] == sog_actual[side] for side in ("home", "away"))
    return {
        "ordinary_score": dict(ordinary),
        "shootout_attempts": dict(state.shootout_attempts),
        "shootout_goals": dict(state.shootout_goals),
        "shootout_adjusted_score": dict(adjusted),
        "official_score": score_actual,
        "score_match": score_match,
        "official_sog": sog_actual,
        "replayed_sog": dict(state.shots_on_goal),
        "sog_match": sog_match,
        "score_disposition": state.definition.score_disposition,
        "sog_disposition": state.definition.sog_disposition,
        "score_target_eligible": state.definition.score_disposition == ACCEPT,
        "sog_target_eligible": state.definition.sog_disposition == ACCEPT,
    }


def reconcile_player_targets(state: GameReplay,
                             targets: Iterable[TargetValue], *, purpose: str
                             ) -> list[dict[str, object]]:
    """Compare eligible label values to accepted event attributions; quarantine mismatches."""
    rows: list[dict[str, object]] = []
    for target in targets:
        if target.game_id != state.definition.game_id:
            continue
        candidate = (state.player_sog.get(target.player_id, 0)
                     if target.statistic == "SOG" else
                     state.goalie_stats.get(target.player_id, Counter()).get(target.statistic, 0))
        purpose_value = target.purpose_values[purpose]
        audit_eligible = getattr(target, f"audit_eligible_{purpose}")
        approved = (purpose_value is not None and audit_eligible and
                    target.quality_status in {"VERIFIED", "ADJUDICATED"})
        event_match = purpose_value is not None and candidate == purpose_value
        audit_count_match = target.audit_event_count == candidate
        eligible = (approved and event_match and audit_count_match and
                    target.audit_event_count_match and target.audit_event_disposition == ACCEPT)
        rows.append({
            "game_id": target.game_id,
            "player_id": target.player_id,
            "statistic": target.statistic,
            "quality_status": target.quality_status,
            "reason_code": target.reason_code,
            "audit_reason_code": target.audit_reason_code,
            "source_issue_id": target.source_issue_id,
            "eligible_splits": target.eligible_splits,
            "audit_eligible": audit_eligible,
            "accepted_value": target.accepted_value,
            "purpose_value": purpose_value,
            "replayed_event_count": candidate,
            "audit_event_count": target.audit_event_count,
            "event_count_match": event_match,
            "audit_event_count_match": audit_count_match,
            "eligible_target": eligible,
            "disposition": "ACCEPT" if eligible else "QUARANTINE",
        })
    return rows
