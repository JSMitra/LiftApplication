import os
from typing import Optional


class Settings:
    """
    Central application settings loaded from environment variables (e.g. Kubernetes ConfigMap / Downward API).
    """
    # Building configuration (from ConfigMap floor_count)
    FLOOR_COUNT: int = int(os.getenv("FLOOR_COUNT", os.getenv("floor_count", "20")))
    MIN_FLOOR: int = int(os.getenv("MIN_FLOOR", os.getenv("min_floor", "0")))
    LIFT_COUNT: int = int(os.getenv("LIFT_COUNT", os.getenv("lift_count", "16")))

    # Lift identity (from Kubernetes Downward API metadata.name)
    POD_NAME: str = os.getenv("POD_NAME", os.getenv("HOSTNAME", "lift-service-0"))
    LIFT_ID: str = os.getenv("LIFT_ID", POD_NAME)

    # Redis configuration
    REDIS_HOST: str = os.getenv("REDIS_HOST", "redis")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6379"))
    REDIS_PASSWORD: Optional[str] = os.getenv("REDIS_PASSWORD", None)
    REDIS_DB: int = int(os.getenv("REDIS_DB", "0"))

    # Movement timing parameters
    # Requirement: deliberately slow with time gaps of ~1 second per floor
    # We use 5 sub-steps of 0.2s each (0.2s * 5 = 1.0s transit per floor)
    # allowing fractional floor telemetry (e.g. 7.2, 7.4, 7.6, 7.8, 8.0)
    STEP_DELAY_SEC: float = float(os.getenv("STEP_DELAY_SEC", "0.2"))
    FLOOR_SUB_STEPS: int = int(os.getenv("FLOOR_SUB_STEPS", "5"))
    DOOR_DWELL_SEC: float = float(os.getenv("DOOR_DWELL_SEC", "1.0"))

    # Service ports & URLs
    LIFT_PORT: int = int(os.getenv("LIFT_PORT", "8000"))
    ORCHESTRATOR_PORT: int = int(os.getenv("ORCHESTRATOR_PORT", "8000"))
    
    # URL pattern for orchestrator to reach lift-services.
    # In K8s headless service: http://{lift_id}.lift-service.{namespace}.svc.cluster.local:8000
    # or http://{lift_id}.lift-service:8000
    K8S_NAMESPACE: str = os.getenv("K8S_NAMESPACE", "lift-system")
    LIFT_URL_TEMPLATE: str = os.getenv(
        "LIFT_URL_TEMPLATE",
        "http://{lift_id}.lift-service." + os.getenv("K8S_NAMESPACE", "lift-system") + ".svc.cluster.local:8000"
    )

    # Fallback template for Docker Compose or local execution:
    # If K8s DNS is not available, try http://{lift_id}:8000 or http://localhost:{port}
    COMPOSE_URL_TEMPLATE: str = os.getenv("COMPOSE_URL_TEMPLATE", "http://{lift_id}:8000")

    # Redis Keys
    HALL_REQUEST_KEY: str = "hall-request"
    EVENT_STREAM_KEY: str = "lift-events"


settings = Settings()

