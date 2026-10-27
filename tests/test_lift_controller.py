import unittest
from unittest.mock import AsyncMock, patch
from app.lift.service import LiftService
from app.models import LiftStatus


class TestLiftController(unittest.IsolatedAsyncioTestCase):
    """
    Tests for LiftService state transitions and async loop control.
    """

    async def test_lift_initialization(self):
        controller = LiftService(lift_id="lift-service-5")
        self.assertEqual(controller.lift_id, "lift-service-5")
        self.assertEqual(controller.current_direction, 0)
        self.assertEqual(controller.state, "IDLE")

    @patch("app.lift.service.redis_manager")
    async def test_trigger_starts_task(self, mock_redis):
        mock_redis.get_lift_queue = AsyncMock(return_value=[8])
        mock_redis.update_lift_status = AsyncMock()

        controller = LiftService(lift_id="lift-service-2")
        started = controller.trigger()
        self.assertTrue(started)

        # Triggering a second time while running should return False
        started_again = controller.trigger()
        self.assertFalse(started_again)

        # Stop controller
        await controller.stop()
        self.assertIsNone(controller._worker_task)


if __name__ == "__main__":
    unittest.main()

