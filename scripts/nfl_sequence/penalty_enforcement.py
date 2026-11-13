"""Shared NFL penalty-enforcement rules for the V1.7+ model family.

All 16 single-foul labels in penalty_fit.CATEGORIES have a defined legal
transition for their applicable scrimmage situations. This is *not* a
complete NFL penalty catalog, officiating/acceptance model, clock engine,
or full-game integration. Conditional rules require explicit source facts:
DPI foul spot; intentional-grounding passer spot; run-block spot/subtype;
roughing passer completion status. Never manufacture these facts.

Rule basis: NFL Official Playing Rules 2026, Rules 4, 7, 8, 12, 14.
https://operations.nfl.com/rules-officiating/2026-nfl-rulebook
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from penalty_fit import CATEGORIES

EPS = 1e-9


@dataclass(frozen=True)
class DownState:
    down: int
    to_go: float
    yardline_100: float  # distance from opponent goal, supports half-yard enforcement
    possession: str

    def __post_init__(self):
        if not isinstance(self.down, int) or not 1 <= self.down <= 4:
            raise ValueError("invalid down")
        if not math.isfinite(self.to_go) or self.to_go <= 0:
            raise ValueError("invalid distance to gain")
        if not math.isfinite(self.yardline_100) or not 0 <= self.yardline_100 <= 100:
            raise ValueError("invalid field position")
        if not self.possession:
            raise ValueError("missing possession")


@dataclass(frozen=True)
class Enforcement:
    state: DownState
    accepted: bool
    yards: float
    rule_basis: str
    # A completed legal play survives a declined foul or accepted roughing
    # after a catch. Every other accepted supported foul cancels the play.
    play_counts: bool = False
    replay_down: bool = True
    automatic_first_down: bool = False
    loss_of_down: bool = False
    turnover_on_downs: bool = False
    clock_action: str = "review_required"
    enforcement_spot: str = "previous"
    safety: bool = False


@dataclass(frozen=True)
class PenaltyRule:
    phase: str
    yards: int | None
    automatic_first_down: bool
    rule_basis: str
    play_classes: tuple[str, ...]


# Keyed by exactly the model's 16 (committing side, foul) combinations.
# 'live_ball' means after a snap, including snap-timing infractions.
# A generic "illegal_block" is not an official single 10/15-yard rule:
# it requires a resolved subtype before enforcement.
RULES: dict[tuple[str, str], PenaltyRule] = {
    ("offense", "false_start"): PenaltyRule("pre_snap", 5, False, "7-4-2", ()),
    ("offense", "delay_of_game"): PenaltyRule("pre_snap", 5, False, "4-6", ()),
    ("defense", "encroachment"): PenaltyRule("pre_snap", 5, False, "7-4-3", ()),
    ("defense", "neutral_zone_infraction"): PenaltyRule("pre_snap", 5, False, "7-4-4", ()),
    ("offense", "offensive_holding"): PenaltyRule("live_ball", 10, False, "12-1-3", ("run", "dropback")),
    ("offense", "offensive_pass_interference"): PenaltyRule("live_ball", 10, False, "8-5", ("dropback",)),
    ("offense", "illegal_block"): PenaltyRule("live_ball", None, False, "12-1-3", ("run", "dropback")),
    ("offense", "intentional_grounding"): PenaltyRule("live_ball", None, False, "8-2-1; 8-6-1(a)", ("dropback",)),
    ("offense", "illegal_formation"): PenaltyRule("live_ball", 5, False, "7-5-1", ("run", "dropback")),
    ("offense", "illegal_shift"): PenaltyRule("live_ball", 5, False, "7-4-7", ("run", "dropback")),
    ("offense", "illegal_motion"): PenaltyRule("live_ball", 5, False, "7-4-8", ("run", "dropback")),
    ("defense", "defensive_holding"): PenaltyRule("live_ball", 5, True, "12-1-6", ("run", "dropback")),
    ("defense", "defensive_pass_interference"): PenaltyRule("live_ball", None, True, "8-5", ("dropback",)),
    ("defense", "illegal_contact"): PenaltyRule("live_ball", 5, True, "8-4-3", ("dropback",)),
    ("defense", "roughing_passer"): PenaltyRule("live_ball", 15, True, "12-2-11", ("dropback",)),
    ("defense", "offside"): PenaltyRule("live_ball", 5, False, "7-4-5", ("run", "dropback")),
}

MODEL_FOULS = {(side, name) for phase in CATEGORIES for side in CATEGORIES[phase]
               for name in CATEGORIES[phase][side]}
if set(RULES) != MODEL_FOULS:
    raise RuntimeError(f"penalty enforcement/model foul coverage diverged: "
                       f"{sorted(MODEL_FOULS ^ set(RULES))}")

# The model collapses several illegal-block descriptions into one coarse name;
# require a known subtype so 15-yard personal fouls aren't coded as 10.
BLOCK_SUBTYPES = {
    "in_back": (10, "12-1-3(b)"),
    "above_waist": (10, "12-1-3(a)"),
}


def _half_distance(base: float, side: str, yards: float) -> tuple[float, float]:
    if not (0 < base < 100):
        raise ValueError("goal line requires a special scoring transition")
    available = (100 - base) if side == "offense" else base
    actual = min(yards, available / 2) if yards > available / 2 else yards
    target = base + actual if side == "offense" else base - actual
    if not (0 < target < 100):
        raise ValueError("penalty spot is out of playable field bounds")
    return target, actual


def _spot(value: float | None, name: str, *, allow_endzone: bool = False) -> float:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} requires an explicit finite foul spot")
    if allow_endzone:
        if not 0 <= value <= 100:
            raise ValueError(f"{name} spot must be within 0..100")
    elif not 0 < value < 100:
        raise ValueError(f"{name} spot must be in the field of play")
    return float(value)


def _series(before: DownState, new_y: float, side: str, *, auto_first: bool,
            loss_down: bool = False, defense_team: str | None = None) -> tuple[DownState, bool, bool]:
    """State after accepted enforcement; crossing line to gain awards first down."""
    crossed = side == "defense" and new_y <= before.yardline_100 - before.to_go + EPS
    if auto_first or crossed:
        return DownState(1, min(10, new_y), new_y, before.possession), True, False
    if loss_down and before.down == 4:
        if not defense_team or defense_team == before.possession:
            raise ValueError("fourth-down loss requires explicit defending team")
        new_defense_y = 100 - new_y
        return DownState(1, min(10, new_defense_y), new_defense_y, defense_team), False, True
    new_down = before.down + (1 if loss_down else 0)
    # For a live-ball accepted foul, the down is replayed unless the foul carries
    # loss of down. Compute distance from the original line to gain, not from
    # the spot where an illegal block occurred during a run.
    remaining = before.to_go + new_y - before.yardline_100
    if side == "defense":
        remaining = max(EPS, remaining)
    return DownState(new_down, remaining, new_y, before.possession), False, False


def enforce(*, before: DownState, after_play: DownState, phase: str,
            offender: str, foul: str, accepted: bool,
            foul_yardline_100: float | None = None,
            play_class: str | None = None, pass_outcome: str | None = None,
            block_subtype: str | None = None,
            defense_team: str | None = None) -> Enforcement:
    """Apply a single, identified 2026-rule penalty to a supported scrimmage state.

    'live_pass' is retained as a compatibility alias for 'live_ball/dropback'.
    Explicit data is mandatory for spot-of-foul and completion-dependent rules.
    Multi-foul, kickoff/kick, interception/return, and scoring transitions still
    require the separate future full-game rules integration.
    """
    if not isinstance(accepted, bool):
        raise ValueError("accept/decline must be an explicit boolean")
    if not isinstance(before, DownState) or not isinstance(after_play, DownState):
        raise ValueError("before/after must be DownState instances")
    if phase == "live_pass":
        phase, play_class = "live_ball", "dropback"
    if phase not in ("pre_snap", "live_ball"):
        raise ValueError(f"unsupported penalty phase: {phase}")
    key = (offender, foul)
    rule = RULES.get(key)
    if rule is None:
        raise ValueError(f"foul is not one of the 16 modeled types: {key}")
    if phase != rule.phase:
        raise ValueError(f"foul {key} cannot be enforced in phase {phase}")
    if phase == "live_ball" and play_class not in rule.play_classes:
        raise ValueError(f"{key} has no supported {play_class!r} play-class transition")
    if phase == "pre_snap" and after_play != before:
        raise ValueError("pre-snap foul cannot have a completed scrimmage play")
    if not accepted:
        return Enforcement(after_play, False, 0, "declined: completed play stands",
                           play_counts=phase == "live_ball", replay_down=False,
                           clock_action="retain_play_clock" if phase == "live_ball" else "no_snap")
    if before.possession != after_play.possession:
        raise ValueError("accepted foul with possession change requires return/turnover enforcement")
    if not 0 < before.yardline_100 < 100 or not 0 < after_play.yardline_100 < 100:
        raise ValueError("scoring/goal-line play requires scoring integration")

    base = before.yardline_100
    awarded = rule.yards
    spot_type = "previous"
    play_counts = False
    replay_down = True
    loss_down = False
    auto_first = rule.automatic_first_down
    clock_action = "no_snap" if phase == "pre_snap" else "replay_down"

    if foul == "defensive_pass_interference":
        foul_y = _spot(foul_yardline_100, "defensive pass interference", allow_endzone=True)
        if foul_y > base:
            raise ValueError("defensive pass interference spot must be beyond line of scrimmage")
        if foul_y == 0:
            new_y = 1.0 if base >= 2 else base / 2
        else:
            new_y = foul_y
        actual = base - new_y
        spot_type = "foul_or_goal_line"
    elif foul == "intentional_grounding":
        foul_y = _spot(foul_yardline_100, "intentional grounding")
        if foul_y < base:
            raise ValueError("intentional grounding pass spot must be behind line of scrimmage")
        # Rule 8-6-1(a): loss of down, and the lesser benefit to offense of
        # ten yards from previous or passer's release spot; special own-goal
        # line exception caps it at release spot.
        ten_y = base + 10
        release_depth = foul_y - base
        own_goal_distance = 100 - base
        if release_depth < 10 and release_depth > own_goal_distance / 2:
            # 2026 Rule 8-6-1(a): release spot is the enforcement spot
            # when the pass was thrown inside ten yards of the LOS but
            # more than halfway to the offense's goal line.
            new_y = foul_y
        else:
            new_y = max(ten_y, foul_y)
        if not 0 < new_y < 100:
            raise ValueError("intentional grounding safety needs scoring transition")
        actual = new_y - base
        spot_type = "grounding_spot_or_ten_yards"
        loss_down = True
        clock_action = "loss_of_down"
    elif foul == "roughing_passer":
        if pass_outcome not in ("complete", "incomplete"):
            raise ValueError("roughing passer requires complete/incomplete pass outcome")
        if pass_outcome == "complete":
            base = after_play.yardline_100
            spot_type = "end_of_run"
            play_counts = True
            clock_action = "play_stands_then_enforce"
        new_y, actual = _half_distance(base, offender, awarded)
    elif foul == "illegal_block":
        if block_subtype not in BLOCK_SUBTYPES:
            raise ValueError("illegal_block requires verified in_back/above_waist subtype")
        awarded, rule_id = BLOCK_SUBTYPES[block_subtype]
        base = _spot(foul_yardline_100, "illegal block")
        spot_type = "foul"
        new_y, actual = _half_distance(base, offender, awarded)
        rule = PenaltyRule(rule.phase, awarded, auto_first, rule_id, rule.play_classes)
    elif foul == "offensive_holding" and play_class == "run":
        # Run-foul all-but-one mechanics require the spot, not a fake
        # automatic previous-spot penalty.
        base = _spot(foul_yardline_100, "run holding")
        spot_type = "foul"
        new_y, actual = _half_distance(base, offender, awarded)
    else:
        assert awarded is not None
        new_y, actual = _half_distance(base, offender, awarded)

    new_state, new_first, turnover = _series(
        before, new_y, offender, auto_first=auto_first, loss_down=loss_down,
        defense_team=defense_team)
    return Enforcement(
        state=new_state, accepted=True, yards=actual, rule_basis=f"NFL 2026 Rule {rule.rule_basis}",
        play_counts=play_counts, replay_down=replay_down and not loss_down and not new_first,
        automatic_first_down=new_first, loss_of_down=loss_down,
        turnover_on_downs=turnover, clock_action=clock_action,
        enforcement_spot=spot_type)
