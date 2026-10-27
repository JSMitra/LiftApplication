import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, List
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.models import HallRequest, HallRequestIn
from app.redis_client import redis_manager
from app.orchestrator.service import orchestrator_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [orchestrator] %(message)s"
)
logger = logging.getLogger("orchestrator.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting Lift Orchestrator (Managing {settings.LIFT_COUNT} lifts across {settings.FLOOR_COUNT} floors)")
    await orchestrator_service.initialize()
    yield
    logger.info("Stopping Lift Orchestrator")
    await orchestrator_service.close()
    await redis_manager.close()


app = FastAPI(
    title="Lift Orchestrator Service",
    description="Central dispatch coordinator for 16-pod elevator system with real-time UI dashboard",
    version="1.0.0",
    lifespan=lifespan
)


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------

@app.post("/api/requests")
async def create_hall_request(req_in: HallRequestIn):
    """
    Submits a hall request: tuple (floor number, direction (UP | DOWN)).
    Saves to Redis 'hall-request' HashSet and triggers immediate dispatch evaluation.
    """
    dir_upper = req_in.direction.upper().strip()
    if dir_upper not in ("UP", "DOWN"):
        raise HTTPException(status_code=400, detail="Direction must be 'UP' or 'DOWN'")

    if req_in.floor < settings.MIN_FLOOR or req_in.floor >= settings.FLOOR_COUNT:
        raise HTTPException(
            status_code=400,
            detail=f"Floor {req_in.floor} is out of building range ({settings.MIN_FLOOR} to {settings.FLOOR_COUNT - 1})"
        )

    # Edge cases: top floor cannot go UP, ground floor cannot go DOWN
    if req_in.floor == settings.FLOOR_COUNT - 1 and dir_upper == "UP":
        raise HTTPException(status_code=400, detail="Top floor cannot request UP")
    if req_in.floor == settings.MIN_FLOOR and dir_upper == "DOWN":
        raise HTTPException(status_code=400, detail="Ground floor cannot request DOWN")

    request = HallRequest(floor=req_in.floor, direction=dir_upper)
    await redis_manager.add_hall_request(request)

    # Trigger immediate dispatch cycle
    assignments = await orchestrator_service.run_single_dispatch_cycle()

    return {
        "status": "received",
        "request": request.model_dump() if hasattr(request, 'model_dump') else request.__dict__,
        "immediate_assignments": [
            {
                "lift_id": a.lift_id,
                "cost": a.cost,
                "reason": a.reason
            } for a in assignments
        ]
    }


@app.get("/api/requests")
async def list_hall_requests():
    """Lists all pending hall requests currently in Redis."""
    requests = await redis_manager.get_all_hall_requests()
    return {
        "count": len(requests),
        "requests": [
            r.model_dump() if hasattr(r, 'model_dump') else r.__dict__
            for r in requests
        ]
    }


@app.delete("/api/requests/{floor}/{direction}")
async def cancel_hall_request(floor: int, direction: str):
    """Cancels a pending hall request."""
    success = await redis_manager.delete_hall_request(floor, direction)
    return {"deleted": success}


@app.get("/api/lifts")
async def get_all_lifts():
    """Returns telemetry of all 16 lifts from Redis (<lift_id>.status)."""
    statuses = await redis_manager.get_all_lift_statuses(settings.LIFT_COUNT)
    queues = await redis_manager.get_all_lift_queues(settings.LIFT_COUNT)

    result = []
    for i in range(settings.LIFT_COUNT):
        lid = f"lift-service-{i}"
        st = statuses.get(lid)
        q = queues.get(lid, [])
        result.append({
            "lift_id": lid,
            "floor": st.floor if st else 0.0,
            "direction": st.direction if st else 0,
            "state": st.state if st else "IDLE",
            "target_floor": st.target_floor if st else None,
            "queue": q
        })
    return {"lifts": result}


@app.get("/api/queues")
async def get_all_queues():
    """Returns the HashSet service queues for all 16 lifts."""
    queues = await redis_manager.get_all_lift_queues(settings.LIFT_COUNT)
    return {"queues": queues}


@app.post("/api/dispatch")
async def trigger_dispatch():
    """Manually forces a dispatch cycle across pending requests."""
    assignments = await orchestrator_service.run_single_dispatch_cycle()
    return {
        "assigned_count": len(assignments),
        "assignments": [
            {
                "lift_id": a.lift_id,
                "floor": a.request.floor,
                "direction": a.request.direction,
                "cost": a.cost,
                "reason": a.reason
            } for a in assignments
        ]
    }


@app.post("/api/reset")
async def reset_system():
    """Resets all queues and statuses for demonstration/testing."""
    await redis_manager.reset_all_data()
    return {"status": "system_reset_complete"}


@app.get("/api/config")
async def get_config():
    """Returns building configuration parameters."""
    return {
        "floor_count": settings.FLOOR_COUNT,
        "min_floor": settings.MIN_FLOOR,
        "lift_count": settings.LIFT_COUNT,
        "step_delay_sec": settings.STEP_DELAY_SEC,
        "door_dwell_sec": settings.DOOR_DWELL_SEC
    }


@app.get("/api/events")
async def get_events(limit: int = 30):
    """Returns recent dispatch and arrival event history."""
    events = await redis_manager.get_recent_events(limit)
    return {"events": events}


@app.get("/healthz")
async def healthz():
    """Kubernetes liveness and readiness probe."""
    try:
        client = await redis_manager.get_client()
        await client.ping()
        return {"status": "healthy", "service": "lift-orchestrator"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unhealthy: {e}")


# -------------------------------------------------------------
# Real-Time WebSocket Streaming for UI
# -------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    orchestrator_service.register_websocket(websocket)
    try:
        while True:
            # Keep-alive receive loop
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        orchestrator_service.unregister_websocket(websocket)
    except Exception:
        orchestrator_service.unregister_websocket(websocket)


# -------------------------------------------------------------
# Static Files & UI Mounting
# -------------------------------------------------------------

static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/style.css")
    async def serve_css():
        return FileResponse(os.path.join(static_dir, "style.css"))

    @app.get("/app.js")
    async def serve_js():
        return FileResponse(os.path.join(static_dir, "app.js"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.orchestrator.main:app", host="0.0.0.0", port=settings.ORCHESTRATOR_PORT, reload=False)
