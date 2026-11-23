"""Deterministic geometry for a thrown ball. Distances are yards and times are seconds.

This is a geometric primitive, not a complete pass model. Its inputs must come from
the live play and data-backed player models; it does not choose a throw or an outcome.
"""
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class BallFlight:
    release_x: float
    release_y: float
    release_height: float
    landing_x: float
    landing_y: float
    horizontal_speed: float
    apex_height: float

    def __post_init__(self):
        values = (self.release_x, self.release_y, self.release_height, self.landing_x,
                  self.landing_y, self.horizontal_speed, self.apex_height)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('ball_flight_non_finite_input')
        if self.horizontal_speed <= 0:
            raise ValueError('ball_flight_invalid_speed')
        if self.release_height < 0 or self.apex_height < self.release_height:
            raise ValueError('ball_flight_invalid_height')
        if self.distance == 0:
            raise ValueError('ball_flight_zero_distance')

    @property
    def distance(self):
        return math.hypot(self.landing_x - self.release_x, self.landing_y - self.release_y)

    @property
    def duration(self):
        return self.distance / self.horizontal_speed

    def position(self, seconds):
        """Return x, y, height at the requested instant within the flight.

        Height uses a quadratic arc through release and ground, with the supplied
        maximum height. Horizontal speed is constant. No later play state is read.
        """
        if not math.isfinite(seconds) or not 0 <= seconds <= self.duration:
            raise ValueError('ball_flight_time_out_of_range')
        u = seconds / self.duration
        # A quadratic with its maximum at apex_height and zero at u=1.
        root = math.sqrt(self.apex_height)
        release_root = math.sqrt(self.apex_height - self.release_height)
        height = self.apex_height - ((root + release_root) * u - release_root) ** 2
        return (self.release_x + (self.landing_x - self.release_x) * u,
                self.release_y + (self.landing_y - self.release_y) * u,
                max(0.0, height))


def reachable_at(flight, seconds, player_x, player_y, reach_radius, reach_height):
    """Whether a player at an observed live position can reach the ball now.

    The caller owns player movement, reach inputs, contest resolution and sampling
    times. This function does not assume a route or invent a player rating.
    """
    values = (player_x, player_y, reach_radius, reach_height)
    if not all(math.isfinite(v) for v in values) or reach_radius < 0 or reach_height < 0:
        raise ValueError('ball_flight_invalid_player_reach')
    x, y, height = flight.position(seconds)
    return height <= reach_height and math.hypot(x - player_x, y - player_y) <= reach_radius


@dataclass(frozen=True)
class MovingPlayer:
    """A player's current position and constant velocity over one live segment."""
    player_id: str
    x: float
    y: float
    vx: float
    vy: float
    reach_radius: float
    reach_height: float

    def __post_init__(self):
        numbers = (self.x, self.y, self.vx, self.vy, self.reach_radius, self.reach_height)
        if (not self.player_id or not all(math.isfinite(v) for v in numbers)
                or self.reach_radius < 0 or self.reach_height < 0):
            raise ValueError('ball_flight_invalid_player_motion')


def _roots(a, b, c):
    if abs(a) < 1e-14:
        return [] if abs(b) < 1e-14 else [-c / b]
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return []
    root = math.sqrt(discriminant)
    return [(-b - root) / (2 * a), (-b + root) / (2 * a)]


def first_reach(flight, players, *, until=None):
    """Return (time, player IDs) for first reach in this segment, or None.

    The caller supplies motion from the current play state. A tie remains a tie;
    it is not silently decided by player ordering. `until` limits observation
    to a live instant so that a decision need not read future positions.
    """
    end = flight.duration if until is None else until
    if not math.isfinite(end) or not 0 <= end <= flight.duration:
        raise ValueError('ball_flight_time_out_of_range')
    if len({p.player_id for p in players}) != len(players):
        raise ValueError('ball_flight_duplicate_player')
    results = []
    for p in players:
        bx = (flight.landing_x - flight.release_x) / flight.duration
        by = (flight.landing_y - flight.release_y) / flight.duration
        dx, dy = flight.release_x - p.x, flight.release_y - p.y
        dvx, dvy = bx - p.vx, by - p.vy
        horizontal = (dvx * dvx + dvy * dvy, 2 * (dx * dvx + dy * dvy),
                      dx * dx + dy * dy - p.reach_radius ** 2)
        root = math.sqrt(flight.apex_height)
        release_root = math.sqrt(flight.apex_height - flight.release_height)
        slope = (root + release_root) / flight.duration
        vertical = (-slope * slope, 2 * slope * release_root,
                    flight.release_height - p.reach_height)
        points = sorted({0.0, end} | {t for t in _roots(*horizontal) + _roots(*vertical) if 0 <= t <= end})
        for t in points:
            h = (horizontal[0] * t + horizontal[1]) * t + horizontal[2]
            v = (vertical[0] * t + vertical[1]) * t + vertical[2]
            if h <= 1e-9 and v <= 1e-9:
                results.append((t, p.player_id))
                break
    if not results:
        return None
    first = min(t for t, _ in results)
    return first, tuple(sorted(player for t, player in results if abs(t - first) <= 1e-9))
