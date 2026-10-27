import asyncio
import logging
import time
from typing import Optional, List
from app.config import settings
from app.models import LiftStatus
from app.redis_client import redis_manager
from app.lift.look_algorithm import compute_look_next_target

logger = logging.getLogger(f"lift.{settings.LIFT_ID}")


class LiftService:
    """
    Controller for a single StatefulSet Lift instance.
    Runs the LOOK algorithm over its Redis HashSet queue (<lift_id>.service_queue).
    Publishes real-time fractional floor positions to <lift_id>.status.
    """

    def __init__(self, lift_id: Optional[str] = None):
        self.lift_id = lift_id or settings.LIFT_ID
        self.current_floor: float = float(settings.MIN_FLOOR)
        self.current_direction: int = 0  # 0 = IDLE, 1 = UP, -1 = DOWN
        self.state: str = "IDLE"  # "IDLE", "MOVING", "DOOR_OPEN"
        self.target_floor: Optional[int] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def initialize(self):
        """Called on FastAPI startup to load or set initial state in Redis."""
        try:
            status = await redis_manager.get_lift_status(self.lift_id)
            if status:
                self.current_floor = status.floor
                self.current_direction = status.direction
                self.state = status.state
                self.target_floor = status.target_floor
        except Exception as e:
            logger.warning(f"Could not load previous state for {self.lift_id}: {e}")

        # Update initial status in Redis
        await self._sync_status()
        logger.info(f"[{self.lift_id}] Initialized at floor {self.current_floor}, state: {self.state}")

        # If there are already items in the queue (e.g. after container restart), trigger loop
        queue = await redis_manager.get_lift_queue(self.lift_id)
        if queue:
            logger.info(f"[{self.lift_id}] Found {len(queue)} pending floors in queue on startup: {queue}")
            self.trigger()

    async def _sync_status(self, queue: Optional[List[int]] = None):
        """Publishes the current position and direction to Redis."""
        if queue is None:
            queue = await redis_manager.get_lift_queue(self.lift_id)

        status = LiftStatus(
            floor=self.current_floor,
            direction=self.current_direction,
            lift_id=self.lift_id,
            state=self.state,
            target_floor=self.target_floor,
            queue=queue,
            updated_at=time.time()
        )
        await redis_manager.update_lift_status(self.lift_id, status)

    def trigger(self) -> bool:
        """
        Triggers the LOOK async processing loop if not already running.
        Returns True if a new task was started, False if already running.
        """
        if self._worker_task is None or self._worker_task.done():
            self._stop_event.clear()
            self._worker_task = asyncio.create_task(self._run_loop())
            logger.info(f"[{self.lift_id}] ▶ Triggered async LOOK processing loop")
            return True
        else:
            logger.debug(f"[{self.lift_id}] Async loop is already active")
            return False

    async def stop(self):
        """Graceful shutdown of worker loop."""
        self._stop_event.set()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None

    async def _run_loop(self):
        """
        Async worker loop executing the LOOK algorithm.
        Continues as long as there are items in the Redis queue.
        Transitions to IDLE when queue is empty.
        """
        logger.info(f"[{self.lift_id}] 🚀 Worker loop started")

        try:
            while not self._stop_event.is_set():
                queue = await redis_manager.get_lift_queue(self.lift_id)

                if not queue:
                    # Queue is empty: transition to IDLE
                    self.current_direction = 0
                    self.state = "IDLE"
                    self.target_floor = None
                    self.current_floor = round(self.current_floor)
                    await self._sync_status(queue=[])
                    logger.info(f"[{self.lift_id}] ⏸ Queue empty. Lift is now IDLE at floor {self.current_floor}")
                    break

                # Compute next target and direction via LOOK algorithm
                target, direction = compute_look_next_target(
                    self.current_floor,
                    self.current_direction,
                    queue
                )

                if target is None:
                    # No target found: IDLE
                    self.current_direction = 0
                    self.state = "IDLE"
                    self.target_floor = None
                    await self._sync_status(queue=queue)
                    break

                self.target_floor = target
                self.current_direction = direction

                # Case 1: Already at the target floor
                if abs(self.current_floor - target) < 1e-4:
                    await self._service_floor(target, queue)
                    continue

                # Case 2: Move towards target floor step-by-step
                # Deliberately slow with ~1 second per floor using sub-steps
                self.state = "MOVING"
                sub_step_count = settings.FLOOR_SUB_STEPS
                step_delay = settings.STEP_DELAY_SEC
                sub_step_size = 1.0 / sub_step_count

                # Direction multiplier
                move_dir = 1 if target > self.current_floor else -1
                self.current_direction = move_dir

                # Advance by one fractional step
                next_floor = round(self.current_floor + (move_dir * sub_step_size), 2)

                # Ensure we don't overshoot target
                if (move_dir > 0 and next_floor >= target) or (move_dir < 0 and next_floor <= target):
                    self.current_floor = float(target)
                else:
                    self.current_floor = next_floor

                # Log and update status
                arrow = "⬆ UP" if self.current_direction > 0 else "⬇ DOWN"
                logger.info(f"[{self.lift_id}] {arrow} Floor {self.current_floor:.1f} (heading to {self.target_floor})")
                await self._sync_status(queue=queue)

                # Delay between steps (e.g. 0.2s * 5 = 1.0s per floor)
                await asyncio.sleep(step_delay)

                # If reached target floor exactly, service it
                if abs(self.current_floor - target) < 1e-4:
                    await self._service_floor(target, queue)

        except asyncio.CancelledError:
            logger.info(f"[{self.lift_id}] Worker loop cancelled")
        except Exception as e:
            logger.error(f"[{self.lift_id}] Error in worker loop: {e}", exc_info=True)
        finally:
            self.target_floor = None
            if not self._stop_event.is_set():
                # Re-check queue in case items arrived during shutdown
                final_queue = await redis_manager.get_lift_queue(self.lift_id)
                if final_queue:
                    self.trigger()

    async def _service_floor(self, floor: int, queue: List[int]):
        """
        Simulates elevator arrival at target floor:
        - Changes state to DOOR_OPEN
        - Opens doors and waits dwell time (e.g. 1.0s)
        - Concurrency-safe deletes floor from Redis HashSet
        - Closes doors and prepares for next request
        """
        self.state = "DOOR_OPEN"
        self.current_floor = float(floor)
        logger.info(f"[{self.lift_id}] 🚪 Arrived at Floor {floor}. Doors OPENING...")
        await self._sync_status(queue=queue)

        # Dwell time with doors open
        await asyncio.sleep(settings.DOOR_DWELL_SEC)

        # Atomically remove serviced floor from Redis HashSet
        await redis_manager.remove_from_lift_queue(self.lift_id, floor)
        remaining_queue = await redis_manager.get_lift_queue(self.lift_id)

        logger.info(f"[{self.lift_id}] ✅ Doors CLOSING. Serviced Floor {floor}. Remaining queue: {remaining_queue}")
        self.state = "MOVING" if remaining_queue else "IDLE"
        await self._sync_status(queue=remaining_queue)


# Singleton controller for this pod
lift_service = LiftService()

