import asyncio
import logging
import time
from typing import List, Dict, Set, Optional, Any
import httpx
from app.config import settings
from app.models import HallRequest, LiftStatus, DispatchAssignment
from app.redis_client import redis_manager
from app.orchestrator.dispatcher import select_best_lift

logger = logging.getLogger("orchestrator.service")


class OrchestratorService:
    """
    Central dispatch coordinator for 16-pod Lift system.
    Monitors Redis 'hall-request' HashSet, assigns requests to optimal lifts,
    and invokes their /trigger endpoints.
    """

    def __init__(self):
        self._dispatch_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._http_client: Optional[httpx.AsyncClient] = None
        self._websocket_clients: Set[Any] = set()

    async def initialize(self):
        self._http_client = httpx.AsyncClient(timeout=3.0)
        self.start()

    async def close(self):
        self._stop_event.set()
        if self._dispatch_task and not self._dispatch_task.done():
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        if self._http_client:
            await self._http_client.aclose()

    def start(self):
        if self._dispatch_task is None or self._dispatch_task.done():
            self._stop_event.clear()
            self._dispatch_task = asyncio.create_task(self._run_dispatch_loop())
            logger.info("Started Orchestrator dispatch loop")

    def register_websocket(self, ws: Any):
        self._websocket_clients.add(ws)

    def unregister_websocket(self, ws: Any):
        self._websocket_clients.discard(ws)

    async def broadcast_ws(self, message: Dict[str, Any]):
        """Broadcasts live telemetry to all connected UI browser clients."""
        if not self._websocket_clients:
            return
        dead = []
        for ws in self._websocket_clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._websocket_clients.discard(ws)

    async def _resolve_lift_trigger_url(self, lift_id: str) -> List[str]:
        """
        Generates candidate URLs to reach the lift's /trigger endpoint.
        Tries K8s headless DNS first, then Docker compose service name, then localhost.
        """
        urls = [
            # 1. K8s Headless Service FQDN
            f"http://{lift_id}.lift-service.{settings.K8S_NAMESPACE}.svc.cluster.local:{settings.LIFT_PORT}/trigger",
            # 2. Short K8s service name
            f"http://{lift_id}.lift-service:{settings.LIFT_PORT}/trigger",
            # 3. Docker Compose service name by pod ID (e.g. lift-service-0)
            f"http://{lift_id}:{settings.LIFT_PORT}/trigger",
            # 4. Docker Compose single lift-service container name
            f"http://lift-service:{settings.LIFT_PORT}/trigger",
            # 5. Localhost fallback
            f"http://localhost:{settings.LIFT_PORT}/trigger"
        ]
        return urls

    async def trigger_lift_remote(self, lift_id: str) -> bool:
        """
        Sends HTTP POST /trigger to the targeted lift pod.
        """
        if not self._http_client:
            self._http_client = httpx.AsyncClient(timeout=2.0)

        candidate_urls = await self._resolve_lift_trigger_url(lift_id)

        for url in candidate_urls:
            try:
                resp = await self._http_client.post(url)
                if resp.status_code == 200:
                    logger.debug(f"Successfully triggered {lift_id} via {url}")
                    return True
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError):
                continue
            except Exception as e:
                logger.debug(f"Error calling {url}: {e}")
                continue

        logger.warning(f"Could not reach {lift_id} on any endpoint (K8s/Compose DNS might not be ready yet)")
        return False

    async def run_single_dispatch_cycle(self) -> List[DispatchAssignment]:
        """
        Executes one evaluation cycle:
        1. Fetch all pending hall requests.
        2. Fetch all lift statuses and queues.
        3. Match and assign each request to the best lift.
        4. Trigger the assigned lift.
        """
        requests = await redis_manager.get_all_hall_requests()
        if not requests:
            return []

        lift_statuses = await redis_manager.get_all_lift_statuses(settings.LIFT_COUNT)
        lift_queues = await redis_manager.get_all_lift_queues(settings.LIFT_COUNT)

        assignments: List[DispatchAssignment] = []

        for req in requests:
            best = select_best_lift(
                request=req,
                lift_statuses=lift_statuses,
                lift_queues=lift_queues,
                floor_count=settings.FLOOR_COUNT
            )

            if not best:
                continue

            # Atomically claim from hall-request and add to lift's service_queue in Redis
            claimed = await redis_manager.claim_and_assign_request(req, best.lift_id)
            if claimed:
                logger.info(
                    f"🎯 Assigned Hall Call [Floor {req.floor}, {req.direction}] -> {best.lift_id} "
                    f"(Cost: {best.cost:.2f}, Reason: {best.reason})"
                )
                assignments.append(best)

                # Optimistically update local queue cache for next iteration in same cycle
                lift_queues[best.lift_id].append(req.floor)

                # Trigger the lift pod asynchronously
                asyncio.create_task(self.trigger_lift_remote(best.lift_id))

        return assignments

    async def _run_dispatch_loop(self):
        """Main orchestrator loop running continuously."""
        logger.info("Orchestrator dispatch loop active")

        tick = 0
        while not self._stop_event.is_set():
            try:
                # 1. Run dispatch cycle
                await self.run_single_dispatch_cycle()

                # 2. Every 250ms, broadcast real-time state to UI WebSockets
                if self._websocket_clients:
                    statuses = await redis_manager.get_all_lift_statuses(settings.LIFT_COUNT)
                    queues = await redis_manager.get_all_lift_queues(settings.LIFT_COUNT)
                    hall_reqs = await redis_manager.get_all_hall_requests()
                    events = await redis_manager.get_recent_events(limit=15)

                    lift_data = []
                    for i in range(settings.LIFT_COUNT):
                        lid = f"lift-service-{i}"
                        st = statuses.get(lid, LiftStatus(floor=0.0, direction=0, lift_id=lid))
                        q = queues.get(lid, [])
                        lift_data.append({
                            "lift_id": lid,
                            "index": i,
                            "floor": st.floor,
                            "direction": st.direction,
                            "state": st.state,
                            "target_floor": st.target_floor,
                            "queue": q
                        })

                    ws_payload = {
                        "type": "TELEMETRY_UPDATE",
                        "timestamp": time.time(),
                        "lifts": lift_data,
                        "hall_requests": [r.to_json() for r in hall_reqs],
                        "recent_events": events,
                        "floor_count": settings.FLOOR_COUNT
                    }
                    await self.broadcast_ws(ws_payload)

            except Exception as e:
                logger.error(f"Error in orchestrator loop: {e}", exc_info=True)

            tick += 1
            await asyncio.sleep(0.3)


orchestrator_service = OrchestratorService()

