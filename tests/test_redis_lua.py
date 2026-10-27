import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.models import HallRequest, LiftStatus
from app.redis_client import RedisManager, ASSIGN_REQUEST_LUA


class TestRedisConcurrency(unittest.IsolatedAsyncioTestCase):
    """
    Tests for Redis key conventions and concurrency-safe assignment logic.
    """

    async def test_key_conventions(self):
        manager = RedisManager(host="localhost", port=6379)
        # Requirement 2: Key would be "<lift-statefulset-name>.service_queue"
        self.assertEqual(manager.queue_key("lift-service-0"), "lift-service-0.service_queue")
        self.assertEqual(manager.queue_key("lift-service-15"), "lift-service-15.service_queue")

        # Requirement 9: Generic redis key name "<lift-statefulset-name>.status"
        self.assertEqual(manager.status_key("lift-service-0"), "lift-service-0.status")
        self.assertEqual(manager.status_key("lift-service-7"), "lift-service-7.status")

    async def test_lua_script_structure(self):
        # Validate that Lua script checks HEXISTS, deletes from hall-key, and sets in queue-key
        self.assertIn("HEXISTS", ASSIGN_REQUEST_LUA)
        self.assertIn("HDEL", ASSIGN_REQUEST_LUA)
        self.assertIn("HSET", ASSIGN_REQUEST_LUA)
        self.assertIn("return 1", ASSIGN_REQUEST_LUA)
        self.assertIn("return 0", ASSIGN_REQUEST_LUA)

    async def test_claim_and_assign_atomic_success(self):
        manager = RedisManager(host="localhost", port=6379)
        mock_client = AsyncMock()
        mock_client.script_load = AsyncMock(return_value="sha123")
        mock_client.evalsha = AsyncMock(return_value=1)
        mock_client.lpush = AsyncMock()
        mock_client.ltrim = AsyncMock()

        manager._client = mock_client
        manager._lua_assign_sha = "sha123"

        req = HallRequest(floor=8, direction="UP")
        assigned = await manager.claim_and_assign_request(req, "lift-service-4")

        self.assertTrue(assigned)
        mock_client.evalsha.assert_called_once()
        args = mock_client.evalsha.call_args[0]
        self.assertEqual(args[0], "sha123")
        self.assertEqual(args[1], 2)  # 2 keys
        self.assertEqual(args[2], "hall-request")
        self.assertEqual(args[3], "lift-service-4.service_queue")
        self.assertEqual(args[4], "8:UP")
        self.assertEqual(args[5], "8")

    async def test_claim_and_assign_already_claimed(self):
        manager = RedisManager(host="localhost", port=6379)
        mock_client = AsyncMock()
        # When request was already claimed by another worker, Lua script returns 0
        mock_client.evalsha = AsyncMock(return_value=0)
        manager._client = mock_client
        manager._lua_assign_sha = "sha123"

        req = HallRequest(floor=8, direction="UP")
        assigned = await manager.claim_and_assign_request(req, "lift-service-4")
        self.assertFalse(assigned)


if __name__ == "__main__":
    unittest.main()

