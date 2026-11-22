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
