import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from app.config import settings
from app.lift.service import lift_service
from app.redis_client import redis_manager

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s [%(levelname)s] [{settings.LIFT_ID}] %(message)s"
)
logger = logging.getLogger("lift.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize lift service and connect to Redis
    logger.info(f"Starting {settings.LIFT_ID} (Floors: {settings.MIN_FLOOR} to {settings.FLOOR_COUNT - 1})")
    await lift_service.initialize()
    yield
    # Shutdown
    logger.info(f"Stopping {settings.LIFT_ID}")
    await lift_service.stop()
    await redis_manager.close()


app = FastAPI(
    title=f"Lift Service - {settings.LIFT_ID}",
    description="Elevator Controller executing LOOK Algorithm on Redis HashSet queue",
    version="1.0.0",
    lifespan=lifespan
)


@app.post("/trigger")
async def trigger_lift():
    """
    Trigger endpoint called by the lift-orchestrator whenever a new floor is assigned.
    Starts the async LOOK loop if it is not currently running.
    """
    started = lift_service.trigger()
    return {
        "status": "started" if started else "already_running",
        "lift_id": lift_service.lift_id,
        "current_floor": lift_service.current_floor,
        "direction": lift_service.current_direction,
        "state": lift_service.state
    }


@app.get("/status")
async def get_status():
    """Returns the current lift telemetry and state."""
    queue = await redis_manager.get_lift_queue(lift_service.lift_id)
    return {
        "lift_id": lift_service.lift_id,
        "floor": lift_service.current_floor,
        "direction": lift_service.current_direction,
        "state": lift_service.state,
        "target_floor": lift_service.target_floor,
        "queue": queue
    }


@app.get("/queue")
async def get_queue():
    """Returns the current HashSet of floors to be serviced."""
    queue = await redis_manager.get_lift_queue(lift_service.lift_id)
    return {
        "lift_id": lift_service.lift_id,
        "queue": queue,
        "count": len(queue)
    }


@app.get("/healthz")
async def healthz():
    """Kubernetes liveness and readiness probe."""
    try:
        # Quick ping to redis
        client = await redis_manager.get_client()
        await client.ping()
        return {"status": "healthy", "lift_id": settings.LIFT_ID}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Unhealthy: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.lift.main:app", host="0.0.0.0", port=settings.LIFT_PORT, reload=False)

