import json
import time
import logging
from typing import List, Dict, Optional, Any, Set
from app.config import settings
from app.models import LiftStatus, HallRequest

logger = logging.getLogger("lift.redis")

# Atomic Lua script for concurrency-safe hall request assignment
# Transfers a request from 'hall-request' hash into '<lift_id>.service_queue' hash atomically.
ASSIGN_REQUEST_LUA = """
local hall_key = KEYS[1]
local queue_key = KEYS[2]
local req_field = ARGV[1]
local floor_val = ARGV[2]
local timestamp = ARGV[3]

local exists = redis.call('HEXISTS', hall_key, req_field)
if exists == 1 then
    redis.call('HDEL', hall_key, req_field)
    redis.call('HSET', queue_key, floor_val, timestamp)
    return 1
else
    return 0
end
"""


class RedisManager:
    """
    Concurrency-safe Redis interface for Lift services and Orchestrator.
    Manages:
    - '<lift-id>.service_queue' (Redis Hash: field=floor, value=timestamp)
    - '<lift-id>.status' (Redis String: JSON of LiftStatus)
    - 'hall-request' (Redis Hash: field='<floor>:<dir>', value=JSON)
    - 'lift-events' (Redis List: recent event logs)
    """

    def __init__(self, host: str = None, port: int = None, password: Optional[str] = None, db: int = None):
        self.host = host or settings.REDIS_HOST
        self.port = port or settings.REDIS_PORT
        self.password = password or settings.REDIS_PASSWORD
        self.db = db if db is not None else settings.REDIS_DB
        self._client: Optional[Any] = None
        self._lua_assign_sha: Optional[str] = None

    async def get_client(self):
        """Lazy-initializes async Redis connection."""
        if self._client is None:
            try:
                import redis.asyncio as aioredis
                self._client = aioredis.Redis(
                    host=self.host,
                    port=self.port,
                    password=self.password,
                    db=self.db,
                    decode_responses=True,
                    socket_connect_timeout=3.0,
                    socket_timeout=3.0
                )
                # Register Lua script
                try:
                    self._lua_assign_sha = await self._client.script_load(ASSIGN_REQUEST_LUA)
                except Exception as e:
                    logger.warning(f"Could not preload Lua script: {e}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis at {self.host}:{self.port}: {e}")
                raise
        return self._client

    async def close(self):
        if self._client is not None:
            await self._client.close()
            self._client = None

    # -------------------------------------------------------------
    # Lift Service Queue Operations (<lift_id>.service_queue)
    # Stored as a Redis HashSet where field is floor number string
    # -------------------------------------------------------------

    def queue_key(self, lift_id: str) -> str:
        return f"{lift_id}.service_queue"

    async def add_to_lift_queue(self, lift_id: str, floor: int) -> bool:
        """Atomically adds a floor number to the lift's service queue HashSet."""
        client = await self.get_client()
        key = self.queue_key(lift_id)
        # HSET key field value returns 1 if new field, 0 if already existed
        res = await client.hset(key, str(floor), str(time.time()))
        logger.debug(f"Added floor {floor} to {key} (result: {res})")
        return bool(res)

    async def get_lift_queue(self, lift_id: str) -> List[int]:
        """Returns sorted list of unique floor integers in the lift's service queue."""
        client = await self.get_client()
        key = self.queue_key(lift_id)
        fields = await client.hkeys(key)
        floors = []
        for f in fields:
            try:
                floors.append(int(f))
            except ValueError:
                pass
        return sorted(floors)

    async def remove_from_lift_queue(self, lift_id: str, floor: int) -> bool:
        """Atomically removes a floor from the lift's service queue HashSet."""
        client = await self.get_client()
        key = self.queue_key(lift_id)
        res = await client.hdel(key, str(floor))
        logger.debug(f"Removed floor {floor} from {key} (result: {res})")
        return res > 0

    async def clear_lift_queue(self, lift_id: str) -> None:
        """Clears all queued floors for this lift."""
        client = await self.get_client()
        await client.delete(self.queue_key(lift_id))

    # -------------------------------------------------------------
    # Lift Status Operations (<lift_id>.status)
    # Stored as JSON string under <lift_id>.status
    # -------------------------------------------------------------

    def status_key(self, lift_id: str) -> str:
        return f"{lift_id}.status"

    async def update_lift_status(self, lift_id: str, status: LiftStatus) -> None:
        """Updates the lift status in Redis."""
        client = await self.get_client()
        key = self.status_key(lift_id)
        status.lift_id = lift_id
        status.updated_at = time.time()
        await client.set(key, status.to_compact_json())

    async def get_lift_status(self, lift_id: str) -> LiftStatus:
        """Reads lift status from Redis."""
        client = await self.get_client()
        key = self.status_key(lift_id)
        val = await client.get(key)
        return LiftStatus.from_redis_data(val, default_lift_id=lift_id)

    async def get_all_lift_statuses(self, lift_count: int = None) -> Dict[str, LiftStatus]:
        """Fetches status of all lifts (lift-service-0 to lift-service-N)."""
        count = lift_count or settings.LIFT_COUNT
        client = await self.get_client()
        keys = [self.status_key(f"lift-service-{i}") for i in range(count)]
        
        try:
            values = await client.mget(keys)
        except Exception as e:
            logger.error(f"Error fetching lift statuses: {e}")
            values = [None] * count

        result = {}
        for i, val in enumerate(values):
            lid = f"lift-service-{i}"
            result[lid] = LiftStatus.from_redis_data(val, default_lift_id=lid)
        return result

    async def get_all_lift_queues(self, lift_count: int = None) -> Dict[str, List[int]]:
        """Fetches queues for all lifts."""
        count = lift_count or settings.LIFT_COUNT
        client = await self.get_client()
        result = {}
        async with client.pipeline(transaction=False) as pipe:
            for i in range(count):
                pipe.hkeys(self.queue_key(f"lift-service-{i}"))
            responses = await pipe.execute()

        for i, fields in enumerate(responses):
            lid = f"lift-service-{i}"
            floors = []
            for f in fields:
                try:
                    floors.append(int(f))
                except ValueError:
                    pass
            result[lid] = sorted(floors)
        return result

    # -------------------------------------------------------------
    # Hall Requests Operations ('hall-request')
    # Stored as a Redis Hash where field is '<floor>:<dir>'
    # -------------------------------------------------------------

    async def add_hall_request(self, request: HallRequest) -> bool:
        """Adds a hall request to the hall-request HashSet."""
        client = await self.get_client()
        key = settings.HALL_REQUEST_KEY
        field = request.key()
        res = await client.hset(key, field, request.to_json())
        await self.publish_event({
            "type": "HALL_REQUEST_ADDED",
            "floor": request.floor,
            "direction": request.direction,
            "timestamp": time.time()
        })
        return bool(res)

    async def get_all_hall_requests(self) -> List[HallRequest]:
        """Returns all pending hall requests."""
        client = await self.get_client()
        key = settings.HALL_REQUEST_KEY
        data = await client.hgetall(key)
        requests = []
        for _, raw_val in data.items():
            try:
                requests.append(HallRequest.from_json(raw_val))
            except Exception as e:
                logger.error(f"Error decoding hall request: {e}")
        # Sort by creation time
        requests.sort(key=lambda r: r.created_at)
        return requests

    async def delete_hall_request(self, floor: int, direction: str) -> bool:
        """Cancels/deletes a pending hall request."""
        client = await self.get_client()
        field = f"{floor}:{direction.upper()}"
        res = await client.hdel(settings.HALL_REQUEST_KEY, field)
        return res > 0

    async def claim_and_assign_request(self, request: HallRequest, lift_id: str) -> bool:
        """
        Concurrency-safe atomic assignment of a hall request to a lift's queue.
        Uses Lua script to ensure no other process claims the same request concurrently.
        """
        client = await self.get_client()
        hall_key = settings.HALL_REQUEST_KEY
        queue_key = self.queue_key(lift_id)
        req_field = request.key()
        floor_val = str(request.floor)
        now_ts = str(time.time())

        try:
            if self._lua_assign_sha:
                res = await client.evalsha(
                    self._lua_assign_sha,
                    2,
                    hall_key,
                    queue_key,
                    req_field,
                    floor_val,
                    now_ts
                )
            else:
                res = await client.eval(
                    ASSIGN_REQUEST_LUA,
                    2,
                    hall_key,
                    queue_key,
                    req_field,
                    floor_val,
                    now_ts
                )
            success = bool(res == 1)
            if success:
                await self.publish_event({
                    "type": "REQUEST_ASSIGNED",
                    "floor": request.floor,
                    "direction": request.direction,
                    "lift_id": lift_id,
                    "timestamp": time.time()
                })
            return success
        except Exception as e:
            logger.error(f"Atomic assign failed: {e}")
            # Fallback to pipeline
            async with client.pipeline(transaction=True) as pipe:
                pipe.hexists(hall_key, req_field)
                pipe.hdel(hall_key, req_field)
                pipe.hset(queue_key, floor_val, now_ts)
                results = await pipe.execute()
                exists = results[0]
                return bool(exists)

    # -------------------------------------------------------------
    # Event Log Stream (for live UI display)
    # -------------------------------------------------------------

    async def publish_event(self, event_data: Dict[str, Any]) -> None:
        """Stores recent event in Redis list and trims to last 100 items."""
        try:
            client = await self.get_client()
            payload = json.dumps(event_data)
            await client.lpush(settings.EVENT_STREAM_KEY, payload)
            await client.ltrim(settings.EVENT_STREAM_KEY, 0, 99)
        except Exception as e:
            logger.debug(f"Event publish ignored: {e}")

    async def get_recent_events(self, limit: int = 30) -> List[Dict[str, Any]]:
        """Returns recent system events for UI display."""
        try:
            client = await self.get_client()
            raw_items = await client.lrange(settings.EVENT_STREAM_KEY, 0, limit - 1)
            events = []
            for item in raw_items:
                try:
                    events.append(json.loads(item))
                except Exception:
                    pass
            return events
        except Exception:
            return []

    async def reset_all_data(self) -> None:
        """Resets all queues, requests, and lift statuses to Floor 0 IDLE."""
        client = await self.get_client()
        keys_to_delete = [settings.HALL_REQUEST_KEY, settings.EVENT_STREAM_KEY]
        for i in range(settings.LIFT_COUNT):
            lid = f"lift-service-{i}"
            keys_to_delete.append(self.queue_key(lid))
            keys_to_delete.append(self.status_key(lid))
        await client.delete(*keys_to_delete)

        # Set all lifts to IDLE floor 0
        for i in range(settings.LIFT_COUNT):
            lid = f"lift-service-{i}"
            await self.update_lift_status(lid, LiftStatus(floor=0.0, direction=0, lift_id=lid, state="IDLE", queue=[]))


# Global singleton instance
redis_manager = RedisManager()

