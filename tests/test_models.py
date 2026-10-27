import unittest
import json
from app.models import LiftStatus, HallRequest, Direction


class TestModels(unittest.TestCase):
    """
    Tests for models and exact Redis JSON serialization matching user specifications.
    """

    def test_idle_status_format(self):
        # User prompt requirement:
        # If IDLE on floor 9, status would be {"floor":9, "direction":0}
        status = LiftStatus(floor=9.0, direction=0, lift_id="lift-service-0")
        data = status.to_redis_dict()
        self.assertEqual(data["floor"], 9)
        self.assertEqual(data["direction"], 0)

        # Deserialize back
        parsed = LiftStatus.from_redis_data(status.to_compact_json())
        self.assertEqual(parsed.floor, 9.0)
        self.assertEqual(parsed.direction, 0)

    def test_upwards_moving_status_format(self):
        # User prompt requirement:
        # For upwards moving lift the status can be like {"floor":7.2,"direction":1}
        status = LiftStatus(floor=7.2, direction=1, lift_id="lift-service-3")
        data = status.to_redis_dict()
        self.assertEqual(data["floor"], 7.2)
        self.assertEqual(data["direction"], 1)

        parsed = LiftStatus.from_redis_data(status.to_compact_json())
        self.assertEqual(parsed.floor, 7.2)
        self.assertEqual(parsed.direction, 1)

    def test_downward_moving_status_format(self):
        # User prompt requirement:
        # For downward moving lift the status can be like {"floor":5.4,"direction",-1}
        status = LiftStatus(floor=5.4, direction=-1, lift_id="lift-service-7")
        data = status.to_redis_dict()
        self.assertEqual(data["floor"], 5.4)
        self.assertEqual(data["direction"], -1)

        parsed = LiftStatus.from_redis_data(status.to_compact_json())
        self.assertEqual(parsed.floor, 5.4)
        self.assertEqual(parsed.direction, -1)

    def test_hall_request_tuple(self):
        req = HallRequest(floor=6, direction="UP")
        self.assertEqual(req.floor, 6)
        self.assertEqual(req.direction, "UP")
        self.assertEqual(req.key(), "6:UP")

        json_str = req.to_json()
        data = json.loads(json_str)
        self.assertEqual(data["floor"], 6)
        self.assertEqual(data["direction"], "UP")

        reconstructed = HallRequest.from_json(json_str)
        self.assertEqual(reconstructed.floor, 6)
        self.assertEqual(reconstructed.direction, "UP")


if __name__ == "__main__":
    unittest.main()

