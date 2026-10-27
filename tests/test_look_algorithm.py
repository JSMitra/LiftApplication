import unittest
from app.lift.look_algorithm import compute_look_next_target


class TestLookAlgorithm(unittest.TestCase):
    """
    Exhaustive tests for the LOOK elevator scheduling algorithm.
    """

    def test_empty_queue_is_idle(self):
        target, direction = compute_look_next_target(
            current_floor=5.0,
            current_direction=1,
            queued_floors=[]
        )
        self.assertIsNone(target)
        self.assertEqual(direction, 0)

    def test_current_floor_in_queue_serviced_immediately(self):
        target, direction = compute_look_next_target(
            current_floor=7.0,
            current_direction=1,
            queued_floors=[3, 7, 12]
        )
        self.assertEqual(target, 7)
        self.assertEqual(direction, 1)

    def test_moving_up_picks_lowest_floor_above(self):
        # Current at 4.2 moving UP. Requests at 2, 6, 10.
        # Should pick 6 and continue UP (direction 1).
        target, direction = compute_look_next_target(
            current_floor=4.2,
            current_direction=1,
            queued_floors=[2, 6, 10]
        )
        self.assertEqual(target, 6)
        self.assertEqual(direction, 1)

    def test_moving_up_reverses_when_no_requests_above(self):
        # Current at 12.0 moving UP. Requests only at 8 and 3 (all below).
        # In LOOK, elevator reverses to DOWN (-1) and visits the highest request below (8).
        target, direction = compute_look_next_target(
            current_floor=12.0,
            current_direction=1,
            queued_floors=[3, 8]
        )
        self.assertEqual(target, 8)
        self.assertEqual(direction, -1)

    def test_moving_down_picks_highest_floor_below(self):
        # Current at 8.6 moving DOWN. Requests at 3, 5, 14.
        # Should pick 5 and continue DOWN (direction -1).
        target, direction = compute_look_next_target(
            current_floor=8.6,
            current_direction=-1,
            queued_floors=[3, 5, 14]
        )
        self.assertEqual(target, 5)
        self.assertEqual(direction, -1)

    def test_moving_down_reverses_when_no_requests_below(self):
        # Current at 2.0 moving DOWN. Requests only at 6 and 11 (all above).
        # In LOOK, elevator reverses to UP (1) and visits the lowest request above (6).
        target, direction = compute_look_next_target(
            current_floor=2.0,
            current_direction=-1,
            queued_floors=[6, 11]
        )
        self.assertEqual(target, 6)
        self.assertEqual(direction, 1)

    def test_idle_picks_nearest_higher_floor(self):
        # Lift is IDLE at floor 4. Requests at 1 and 9.
        # Distance to 1 is 3. Distance to 9 is 5.
        # Nearest is 1 -> heads DOWN (-1).
        target, direction = compute_look_next_target(
            current_floor=4.0,
            current_direction=0,
            queued_floors=[1, 9]
        )
        self.assertEqual(target, 1)
        self.assertEqual(direction, -1)

    def test_idle_picks_nearest_upper_floor(self):
        # Lift is IDLE at floor 4. Requests at 2 and 5.
        # Distance to 2 is 2. Distance to 5 is 1.
        # Nearest is 5 -> heads UP (1).
        target, direction = compute_look_next_target(
            current_floor=4.0,
            current_direction=0,
            queued_floors=[2, 5]
        )
        self.assertEqual(target, 5)
        self.assertEqual(direction, 1)


if __name__ == "__main__":
    unittest.main()

