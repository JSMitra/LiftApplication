import unittest
from app.models import HallRequestIn


class TestApiValidation(unittest.TestCase):
    """
    Tests input validation on API models.
    """

    def test_valid_hall_request_in(self):
        req = HallRequestIn(floor=5, direction="UP")
        self.assertEqual(req.floor, 5)
        self.assertEqual(req.direction, "UP")

    def test_hall_request_in_attributes(self):
        req = HallRequestIn(floor=12, direction="DOWN")
        self.assertEqual(req.floor, 12)
        self.assertEqual(req.direction, "DOWN")


if __name__ == "__main__":
    unittest.main()
