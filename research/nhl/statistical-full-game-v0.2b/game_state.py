"""Small, explicit game-state primitives for the v0.2b research simulator."""

from __future__ import annotations

from dataclasses import dataclass


SIDES = ("home", "away")


def opposing(side: str) -> str:
    if side not in SIDES:
        raise ValueError(f"unknown team side: {side!r}")
    return "away" if side == "home" else "home"


def possession_after_event(current: str | None, event_type: str,
                           event_side: str | None) -> str | None:
    """Update the explicitly latent possession proxy from a simulated event."""
    if event_type == "faceoff":
        if event_side not in SIDES:
            raise ValueError("faceoff must have a winner side")
        return event_side
    if event_type == "takeaway":
        if event_side not in SIDES:
            raise ValueError("takeaway must have a team side")
        return event_side
    if event_type == "giveaway":
        if event_side not in SIDES:
            raise ValueError("giveaway must have a team side")
        return opposing(event_side)
    if event_type in {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}:
        return None
    return current


def shot_side_for_possession(possession: str | None, donor_side: str | None) -> str:
    """Use live possession for shot ownership; donor ownership is fallback only."""
    side = possession if possession in SIDES else donor_side
    if side not in SIDES:
        raise ValueError("shot opportunity has neither live possession nor donor fallback team")
    return side


@dataclass
class ActivePenalty:
    team_side: str
    player_id: str
    kind: str
    remaining_seconds: int
    started_at_absolute_second: int
    coincidental: bool = False
    expired_at_absolute_second: int | None = None
    queue_assessed_at_absolute_second: int | None = None
    queue_assessment_event_sequence: int | None = None
    queue_triggered_by_player_id: str | None = None


@dataclass
class QueuedPenalty:
    team_side: str
    player_id: str
    kind: str
    duration_seconds: int
    assessed_at_absolute_second: int
    assessment_event_sequence: int | None = None


class PenaltyLedger:
    """Clocked subset of NHL penalties supported by this prototype.

    Minor, double-minor, major, and ten-minute misconduct clocks are supported.
    Misconduct removes a player but does not change manpower. Other penalty
    classes must be rejected by the caller instead of silently approximated.
    """

    def __init__(self) -> None:
        self.active: list[ActivePenalty] = []
        self.queued: list[QueuedPenalty] = []
        self.expired_waiting_release: list[ActivePenalty] = []
        self._last_absolute_second: int | None = None

    def clone(self) -> "PenaltyLedger":
        duplicate = PenaltyLedger()
        duplicate.active = [ActivePenalty(p.team_side, p.player_id, p.kind, p.remaining_seconds,
                                          p.started_at_absolute_second, p.coincidental,
                                          p.expired_at_absolute_second,
                                          p.queue_assessed_at_absolute_second,
                                          p.queue_assessment_event_sequence,
                                          p.queue_triggered_by_player_id)
                           for p in self.active]
        duplicate.queued = [QueuedPenalty(p.team_side, p.player_id, p.kind, p.duration_seconds,
                                         p.assessed_at_absolute_second, p.assessment_event_sequence)
                            for p in self.queued]
        duplicate.expired_waiting_release = [
            ActivePenalty(p.team_side, p.player_id, p.kind, p.remaining_seconds,
                          p.started_at_absolute_second, p.coincidental,
                          p.expired_at_absolute_second,
                          p.queue_assessed_at_absolute_second,
                          p.queue_assessment_event_sequence,
                          p.queue_triggered_by_player_id)
            for p in self.expired_waiting_release]
        duplicate._last_absolute_second = self._last_absolute_second
        return duplicate

    @staticmethod
    def absolute_second(period: int, elapsed: int) -> int:
        if period in (1, 2, 3):
            if not 0 <= elapsed <= 1200:
                raise ValueError("regulation elapsed second outside period")
            return (period - 1) * 1200 + elapsed
        if period == 4:
            if not 0 <= elapsed <= 300:
                raise ValueError("overtime elapsed second outside period")
            return 3600 + elapsed
        raise ValueError(f"penalty clock unsupported in period {period}")

    def advance_to(self, period: int, elapsed: int) -> list[ActivePenalty]:
        absolute = self.absolute_second(period, elapsed)
        if self._last_absolute_second is not None and absolute < self._last_absolute_second:
            raise ValueError("penalty clock moved backwards")
        delta = 0 if self._last_absolute_second is None else absolute - self._last_absolute_second
        expired = []
        for penalty in self.active:
            penalty.remaining_seconds -= delta
            if penalty.remaining_seconds <= 0:
                penalty.expired_at_absolute_second = absolute + penalty.remaining_seconds
                penalty.remaining_seconds = 0
                expired.append(penalty)
        self.active = [p for p in self.active if p.remaining_seconds > 0]
        self._last_absolute_second = absolute
        return expired

    def start(self, team_side: str, player_id: str, kind: str, *,
              duration_seconds: int | None = None,
              coincidental: bool = False) -> ActivePenalty:
        if team_side not in SIDES or not player_id:
            raise ValueError("penalty requires a valid side and player")
        durations = {"MIN": 120, "MAJ": 300, "MIS": 600}
        if kind not in durations:
            raise ValueError(f"unsupported penalty type {kind!r}")
        duration = durations[kind] if duration_seconds is None else int(duration_seconds)
        allowed = {120, 240} if kind == "MIN" else {300} if kind == "MAJ" else {600}
        if duration not in allowed:
            raise ValueError(f"unsupported {kind} duration {duration} seconds")
        if self._last_absolute_second is None:
            raise ValueError("advance the game clock before starting a penalty")
        if self.is_penalized(player_id):
            raise ValueError("player already has an assessed penalty in this model")
        penalty = ActivePenalty(team_side, str(player_id), kind, duration,
                                self._last_absolute_second, coincidental)
        for prior in self.active:
            if (prior.team_side != team_side
                    and prior.started_at_absolute_second == penalty.started_at_absolute_second
                    and prior.kind == kind
                    and prior.remaining_seconds == duration):
                prior.coincidental = True
                penalty.coincidental = True
        manpower_units=sum(p.team_side==team_side and p.kind in {"MIN","MAJ"}
                           and not p.coincidental for p in self.active)
        if kind in {"MIN","MAJ"} and not penalty.coincidental and manpower_units>=2:
            raise ValueError("a third concurrent manpower penalty requires unsupported penalty queuing")
        self.active.append(penalty)
        return penalty

    def assess(self, team_side: str, player_id: str, kind: str, *,
               duration_seconds: int | None = None) -> tuple[ActivePenalty | QueuedPenalty, str]:
        """Assess a supported penalty, queueing one third manpower penalty.

        Same-clock penalty pairing remains the caller's explicit responsibility;
        matching penalties still pass through ``start`` for coincidence marking.
        """
        if team_side not in SIDES or not player_id:
            raise ValueError("penalty requires a valid side and player")
        allowed = {"MIN": {120, 240}, "MAJ": {300}, "MIS": {600}}
        if kind not in allowed:
            raise ValueError(f"unsupported penalty type {kind!r}")
        default_duration = {"MIN": 120, "MAJ": 300, "MIS": 600}[kind]
        duration = default_duration if duration_seconds is None else int(duration_seconds)
        if duration not in allowed[kind]:
            raise ValueError(f"unsupported {kind} duration {duration} seconds")
        if self._last_absolute_second is None:
            raise ValueError("advance the game clock before assessing a penalty")
        if self.is_penalized(player_id):
            raise ValueError("player already has an assessed penalty in this model")

        coincidental_pair = any(
            prior.team_side != team_side
            and prior.started_at_absolute_second == self._last_absolute_second
            and prior.kind == kind
            and prior.remaining_seconds == duration
            for prior in self.active)
        active_units = sum(p.team_side == team_side and p.kind in {"MIN", "MAJ"}
                           and not p.coincidental for p in self.active)
        if kind in {"MIN", "MAJ"} and not coincidental_pair and active_units >= 2:
            if self.queued or self.expired_waiting_release:
                raise ValueError("additional queued manpower penalty is outside the supported subset")
            queued = QueuedPenalty(team_side, str(player_id), kind, duration,
                                   self._last_absolute_second)
            self.queued.append(queued)
            return queued, "queued"

        return self.start(team_side, player_id, kind,
                          duration_seconds=duration), "active"

    def is_penalized(self, player_id: str) -> bool:
        player_id = str(player_id)
        return (any(p.player_id == player_id for p in self.active)
                or any(p.player_id == player_id for p in self.queued)
                or any(p.player_id == player_id for p in self.expired_waiting_release))

    def set_assessment_event_sequence(self, player_id: str, sequence: int) -> None:
        queued = next((p for p in self.queued if p.player_id == str(player_id)), None)
        if queued is not None:
            if queued.assessment_event_sequence is not None:
                raise ValueError("queued penalty assessment sequence was already recorded")
            queued.assessment_event_sequence = int(sequence)

    def resolve_expirations(self, expired: list[ActivePenalty]) -> list[ActivePenalty]:
        """Start queued service at an exact earlier penalty expiry.

        A Rule 26.2 player whose clock expired while three players were in the
        penalty box remains barred until an eligible return transition.
        """
        started: list[ActivePenalty] = []
        for side in SIDES:
            queued = [p for p in self.queued if p.team_side == side]
            if not queued:
                continue
            manpower_expired = [p for p in expired
                                if p.team_side == side and p.kind in {"MIN", "MAJ"}
                                and not p.coincidental]
            if len(queued) != 1:
                raise ValueError("multiple queued penalties for one side are unsupported")
            if len(manpower_expired) != 1:
                raise ValueError("simultaneous expiry with queued service requires unresolved return order")
            if self._last_absolute_second is None:
                raise ValueError("queued service cannot start without a game-clock second")
            expired_penalty = manpower_expired[0]
            if expired_penalty.expired_at_absolute_second != self._last_absolute_second:
                raise ValueError("queued service trigger does not match exact penalty expiry")
            self.expired_waiting_release.append(expired_penalty)
            queued_penalty = queued[0]
            self.queued.remove(queued_penalty)
            service = ActivePenalty(queued_penalty.team_side, queued_penalty.player_id,
                                    queued_penalty.kind, queued_penalty.duration_seconds,
                                    self._last_absolute_second, False, None,
                                    queued_penalty.assessed_at_absolute_second,
                                    queued_penalty.assessment_event_sequence,
                                    expired_penalty.player_id)
            self.active.append(service)
            started.append(service)
        return started

    def waiting_release_candidates(self, period_type: str, *,
                                   at_stoppage: bool = False) -> list[ActivePenalty]:
        """Return Rule 26.2 eligible returns in penalty-expiration order."""
        eligible: list[ActivePenalty] = []
        for side in SIDES:
            side_waiting = [p for p in self.expired_waiting_release if p.team_side == side]
            if not side_waiting:
                continue
            if not at_stoppage and self.manpower(period_type)[side] <= 4:
                continue
            side_waiting.sort(key=lambda p: (p.expired_at_absolute_second or 0, p.player_id))
            expiry_seconds = [p.expired_at_absolute_second for p in side_waiting]
            if len(expiry_seconds) != len(set(expiry_seconds)):
                raise ValueError("same-time penalty return order requires captain designation")
            eligible.extend(side_waiting)
        return eligible

    def release_waiting_player(self, player_id: str) -> ActivePenalty:
        matches = [p for p in self.expired_waiting_release if p.player_id == str(player_id)]
        if len(matches) != 1:
            raise ValueError("penalty release does not match one expired player awaiting release")
        self.expired_waiting_release.remove(matches[0])
        return matches[0]

    def on_goal_transition(self, scoring_side: str) -> tuple[ActivePenalty | None, list[ActivePenalty]]:
        """Apply a power-play goal and start queued service if a minor ends."""
        if scoring_side not in SIDES:
            raise ValueError("goal must have a scoring side")
        short_side = self.shorthanded_side()
        if short_side is None or short_side == scoring_side:
            return None, []
        releasable = [p for p in self.active if p.team_side == short_side
                      and p.kind == "MIN" and not p.coincidental]
        if not releasable:
            return None, []
        penalty = min(releasable, key=lambda p:(p.remaining_seconds,p.started_at_absolute_second))
        # A double minor is two consecutive minor segments. A power-play goal
        # in segment one cancels that segment and starts a fresh two-minute
        # segment; a goal in segment two releases the player. `remaining` is
        # measured from the current clock, so >120 means segment one is active.
        if penalty.remaining_seconds > 120:
            penalty.remaining_seconds = 120
        else:
            penalty.remaining_seconds = 0
        started: list[ActivePenalty] = []
        if penalty.remaining_seconds <= 0:
            self.active.remove(penalty)
            queued = [p for p in self.queued if p.team_side == short_side]
            if queued:
                if len(queued) != 1 or self._last_absolute_second is None:
                    raise ValueError("power-play goal cannot resolve queued penalty ordering")
                # The goal stoppage is also the eligible return point for the
                # earlier minor; retain it as waiting until its release event.
                self.expired_waiting_release.append(penalty)
                queued_penalty = queued[0]
                self.queued.remove(queued_penalty)
                service = ActivePenalty(queued_penalty.team_side, queued_penalty.player_id,
                                        queued_penalty.kind, queued_penalty.duration_seconds,
                                        self._last_absolute_second, False, None,
                                        queued_penalty.assessed_at_absolute_second,
                                        queued_penalty.assessment_event_sequence,
                                        penalty.player_id)
                self.active.append(service)
                started.append(service)
        return penalty, started

    def on_goal(self, scoring_side: str) -> ActivePenalty | None:
        """Compatibility wrapper returning only the affected penalty."""
        penalty, _ = self.on_goal_transition(scoring_side)
        return penalty

    def shorthanded_side(self) -> str | None:
        counts = {side: sum(p.kind in {"MIN", "MAJ"} and not p.coincidental for p in self.active
                            if p.team_side == side) for side in SIDES}
        if counts["home"] == counts["away"]:
            return None
        return "home" if counts["home"] > counts["away"] else "away"

    def manpower(self, period_type: str, *, goalie_pulled: dict[str, bool] | None = None) -> dict[str, int]:
        base = 3 if period_type == "OT" else 5 if period_type == "REG" else None
        if base is None:
            raise ValueError(f"unsupported manpower period type {period_type!r}")
        penalties = {side: sum(p.kind in {"MIN", "MAJ"} and not p.coincidental
                               for p in self.active if p.team_side == side)
                     for side in SIDES}
        if period_type == "REG":
            # In regulation, simultaneous equal penalties are marked
            # coincidental and excluded above. Distinct active penalties on
            # both teams reduce each team's skaters independently (for example,
            # two overlapping noncoincidental minors produce 4-on-4).
            counts = {side: max(3, base - min(2, penalties[side])) for side in SIDES}
        else:
            # Regular-season overtime uses its own manpower table: an unmatched
            # penalty gives the other team an extra skater. Do not apply the
            # regulation per-side subtraction formula to overtime.
            counts = {side: base for side in SIDES}
            diff = penalties["home"] - penalties["away"]
            if diff:
                short = "home" if diff > 0 else "away"
                units = min(2, abs(diff))
                counts[short] = max(3, base - units)
                other = opposing(short)
                counts[other] = min(5, base + units)
        for side, pulled in (goalie_pulled or {}).items():
            if side not in SIDES:
                raise ValueError(f"unknown goalie-pull side {side!r}")
            if pulled:
                counts[side] = min(6, counts[side] + 1)
        return counts

    def penalized_players(self, side: str) -> set[str]:
        if side not in SIDES:
            raise ValueError(f"unknown team side: {side!r}")
        return ({p.player_id for p in self.active if p.team_side == side}
                | {p.player_id for p in self.queued if p.team_side == side}
                | {p.player_id for p in self.expired_waiting_release if p.team_side == side})


def shootout_decided(goals: dict[str, int], attempts: dict[str, int],
                     initial_rounds: int = 3) -> str | None:
    """Return a clinched winner; tied sudden-death attempts must be paired."""
    if set(goals) != set(SIDES) or set(attempts) != set(SIDES):
        raise ValueError("shootout state must contain home and away")
    if any(value < 0 for value in (*goals.values(), *attempts.values())):
        raise ValueError("shootout counts cannot be negative")
    if attempts["home"] == attempts["away"] and min(attempts.values()) >= initial_rounds:
        if goals["home"] != goals["away"]:
            return "home" if goals["home"] > goals["away"] else "away"
    if max(attempts.values()) <= initial_rounds:
        for side in SIDES:
            other = opposing(side)
            remaining = max(0, initial_rounds - attempts[other])
            if goals[side] > goals[other] + remaining:
                return side
    return None
