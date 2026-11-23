import math

import pytest

from ball_flight import BallFlight, MovingPlayer, first_reach, reachable_at


def test_flight_endpoints_duration_and_arc():
    flight = BallFlight(1, 2, 2, 13, 7, 10, 4)
    assert flight.duration == pytest.approx(1.3)
    assert flight.position(0) == pytest.approx((1, 2, 2))
    assert flight.position(flight.duration) == pytest.approx((13, 7, 0))
    assert flight.position(flight.duration / 2)[2] > flight.release_height
    assert flight.position(flight.duration / 2) == flight.position(flight.duration / 2)


@pytest.mark.parametrize('change', [
    {'horizontal_speed': 0}, {'horizontal_speed': -1}, {'release_height': -1},
    {'apex_height': 1}, {'landing_x': 1, 'landing_y': 2}, {'release_x': math.nan},
])
def test_rejects_invalid_geometry(change):
    values = dict(release_x=1, release_y=2, release_height=2, landing_x=13,
                  landing_y=7, horizontal_speed=10, apex_height=4)
    values.update(change)
    with pytest.raises(ValueError, match='ball_flight_'):
        BallFlight(**values)


def test_rejects_outside_flight():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    for t in (-0.01, 1.01, math.nan):
        with pytest.raises(ValueError, match='ball_flight_time_out_of_range'):
            flight.position(t)


def test_reach_depends_on_position_and_height():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    x, y, height = flight.position(0.5)
    assert reachable_at(flight, 0.5, x, y, 0, height)
    assert not reachable_at(flight, 0.5, x + 2, y, 1, height)
    assert not reachable_at(flight, 0.5, x, y, 1, height - 0.1)
    with pytest.raises(ValueError, match='ball_flight_invalid_player_reach'):
        reachable_at(flight, 0.5, x, y, -1, height)


def test_first_reach_orders_players_by_motion_and_ball_height():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    defender = MovingPlayer('defender', 5, 2, 0, -4, 0.2, 4)
    receiver = MovingPlayer('receiver', 8, 0, 0, 0, 0.2, 4)
    time, ids = first_reach(flight, [receiver, defender])
    assert ids == ('defender',)
    assert time < 0.8
    assert first_reach(flight, [receiver, defender], until=0.1) is None
    low_defender = MovingPlayer('defender', 5, 2, 0, -4, 0.2, 0)
    assert first_reach(flight, [receiver, low_defender])[1] == ('receiver',)


def test_simultaneous_reach_is_not_resolved_by_input_order():
    flight = BallFlight(0, 0, 2, 10, 0, 10, 3)
    one = MovingPlayer('one', 5, 0, 0, 0, 1, 5)
    two = MovingPlayer('two', 5, 0, 0, 0, 1, 5)
    assert first_reach(flight, [two, one]) == first_reach(flight, [one, two])
    assert first_reach(flight, [two, one])[1] == ('one', 'two')
    with pytest.raises(ValueError, match='ball_flight_duplicate_player'):
        first_reach(flight, [one, one])
