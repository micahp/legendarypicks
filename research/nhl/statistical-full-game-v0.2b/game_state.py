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


class PenaltyLedger:
    """Clocked subset of NHL penalties supported by this prototype.

    Minor, double-minor, major, and ten-minute misconduct clocks are supported.
    Misconduct removes a player but does not change manpower. Other penalty
    classes must be rejected by the caller instead of silently approximated.
    """

    def __init__(self) -> None:
        self.active: list[ActivePenalty] = []
        self._last_absolute_second: int | None = None

    def clone(self) -> "PenaltyLedger":
        duplicate = PenaltyLedger()
        duplicate.active = [ActivePenalty(p.team_side, p.player_id, p.kind, p.remaining_seconds,
                                          p.started_at_absolute_second, p.coincidental,
                                          p.expired_at_absolute_second)
                           for p in self.active]
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
        penalty = ActivePenalty(team_side, str(player_id), kind, duration,
                                self._last_absolute_second, coincidental)
        if any(p.player_id == penalty.player_id for p in self.active):
            raise ValueError("player already has an active penalty in this model")
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

    def on_goal(self, scoring_side: str) -> ActivePenalty | None:
        """Release the earliest releasable minor on the shorthanded team."""
        if scoring_side not in SIDES:
            raise ValueError("goal must have a scoring side")
        short_side = self.shorthanded_side()
        if short_side is None or short_side == scoring_side:
            return None
        releasable = [p for p in self.active if p.team_side == short_side
                      and p.kind == "MIN" and not p.coincidental]
        if not releasable:
            return None
        penalty = min(releasable, key=lambda p:(p.remaining_seconds,p.started_at_absolute_second))
        # A double minor is two consecutive minor segments. A power-play goal
        # in segment one cancels that segment and starts a fresh two-minute
        # segment; a goal in segment two releases the player. `remaining` is
        # measured from the current clock, so >120 means segment one is active.
        if penalty.remaining_seconds > 120:
            penalty.remaining_seconds = 120
        else:
            penalty.remaining_seconds = 0
        if penalty.remaining_seconds <= 0:
            self.active.remove(penalty)
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
        counts = {side: base for side in SIDES}
        penalties = {side: sum(p.kind in {"MIN", "MAJ"} and not p.coincidental
                               for p in self.active if p.team_side == side)
                     for side in SIDES}
        diff = penalties["home"] - penalties["away"]
        if diff:
            short = "home" if diff > 0 else "away"
            units = min(2, abs(diff))
            counts[short] = max(3 if period_type == "REG" else 3, base - units)
            other = opposing(short)
            if period_type == "OT":
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
        return {p.player_id for p in self.active if p.team_side == side}


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
