import unittest
from app.models import HallRequest, LiftStatus
from app.orchestrator.dispatcher import calculate_lift_cost, select_best_lift


class TestDispatcher(unittest.TestCase):
    """
    Tests for elevator dispatch heuristics.
    """

    def test_approaching_same_direction_is_preferred(self):
        # Request at Floor 8 going UP
        req = HallRequest(floor=8, direction="UP")

        # Lift 0: At floor 5, moving UP (+1). Distance = 3. Approaching!
        status_approaching = LiftStatus(floor=5.0, direction=1, lift_id="lift-service-0")
        cost_approaching, reason1 = calculate_lift_cost(req, status_approaching, queue=[])

        # Lift 1: At floor 5, IDLE (0). Distance = 3.
        status_idle = LiftStatus(floor=5.0, direction=0, lift_id="lift-service-1")
        cost_idle, reason2 = calculate_lift_cost(req, status_idle, queue=[])

        # Lift 2: At floor 10, moving UP (+1). Distance = 2, but moving AWAY (already passed 8)!
        status_away = LiftStatus(floor=10.0, direction=1, lift_id="lift-service-2")
        cost_away, reason3 = calculate_lift_cost(req, status_away, queue=[])

        # Cost ranking: Approaching < IDLE < Moving away
        self.assertLess(cost_approaching, cost_idle, "Approaching lift should beat IDLE at same distance")
        self.assertLess(cost_idle, cost_away, "IDLE lift should beat lift moving away")

    def test_approaching_down_same_direction(self):
        # Request at Floor 3 going DOWN
        req = HallRequest(floor=3, direction="DOWN")

        # Lift at Floor 6 moving DOWN: distance 3, approaching
        status_app = LiftStatus(floor=6.0, direction=-1, lift_id="lift-service-0")
        cost_app, _ = calculate_lift_cost(req, status_app, queue=[])

        # Lift at Floor 1 moving DOWN: already passed floor 3, moving away
        status_away = LiftStatus(floor=1.0, direction=-1, lift_id="lift-service-1")
        cost_away, _ = calculate_lift_cost(req, status_away, queue=[])

        self.assertLess(cost_app, cost_away)

    def test_select_best_lift_among_fleet(self):
        # 16 Lifts
        # Request at Floor 13 going UP
        # lift-service-12 is at Floor 12 moving UP (+1): distance = 1.0, cost = 1.0
        # lift-service-14 is at Floor 14 IDLE (0): distance = 1.0, cost = 1.0 + 1.5 = 2.5
        req = HallRequest(floor=13, direction="UP")
        statuses = {}
        queues = {}

        for i in range(16):
            lid = f"lift-service-{i}"
            statuses[lid] = LiftStatus(floor=float(i), direction=0, lift_id=lid)
            queues[lid] = []

        # Make lift-service-12 moving UP at floor 12 (approaching in same direction)
        statuses["lift-service-12"] = LiftStatus(floor=12.0, direction=1, lift_id="lift-service-12")

        best = select_best_lift(req, statuses, queues, floor_count=20)
        self.assertIsNotNone(best)
        self.assertEqual(best.lift_id, "lift-service-12")
        self.assertIn("Approaching UP", best.reason)


if __name__ == "__main__":
    unittest.main()
