from typing import Optional, List, Dict, Any
from enum import Enum
import time
import json

try:
    from pydantic import BaseModel, Field
except ImportError:
    # Lightweight fallback if pydantic is not installed during local standalone tests
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self):
            return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
        def model_dump_json(self):
            return json.dumps(self.model_dump())
        @classmethod
        def model_validate(cls, data):
            if isinstance(data, str):
                data = json.loads(data)
            return cls(**data)


class Direction(int, Enum):
    DOWN = -1
    IDLE = 0
    UP = 1

    @classmethod
    def from_str(cls, val: str) -> "Direction":
        val_upper = str(val).upper().strip()
        if val_upper in ("UP", "1", "+1"):
            return cls.UP
        elif val_upper in ("DOWN", "-1"):
            return cls.DOWN
        return cls.IDLE

    def to_str(self) -> str:
        if self == Direction.UP:
            return "UP"
        elif self == Direction.DOWN:
            return "DOWN"
        return "IDLE"


class LiftStatus(BaseModel):
    """
    Lift state matching user requirement:
    - IDLE on floor 9: {"floor": 9, "direction": 0}
    - Upwards moving: {"floor": 7.2, "direction": 1}
    - Downward moving: {"floor": 5.4, "direction": -1}
    Additional fields provide rich telemetry for UI and monitoring.
    """
    floor: float
    direction: int  # -1 (DOWN), 0 (IDLE), 1 (UP)
    lift_id: Optional[str] = None
    state: str = "IDLE"  # "IDLE", "MOVING", "DOOR_OPEN"
    target_floor: Optional[int] = None
    queue: List[int] = []
    updated_at: float = 0.0

    def to_redis_dict(self) -> Dict[str, Any]:
        """Compact representation for Redis matching exact user format with optional metadata."""
        return {
            "floor": round(self.floor, 1) if round(self.floor, 1) != int(self.floor) else int(self.floor),
            "direction": self.direction,
            "lift_id": self.lift_id,
            "state": self.state,
            "target_floor": self.target_floor,
            "queue": self.queue,
            "updated_at": self.updated_at or time.time()
        }

    def to_compact_json(self) -> str:
        """Returns JSON string for <lift-name>.status in Redis."""
        return json.dumps(self.to_redis_dict())

    @classmethod
    def from_redis_data(cls, raw: Any, default_lift_id: str = "lift-service-0") -> "LiftStatus":
        if raw is None:
            return cls(floor=0.0, direction=0, lift_id=default_lift_id, state="IDLE", queue=[])
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except Exception:
                return cls(floor=0.0, direction=0, lift_id=default_lift_id, state="IDLE", queue=[])
        elif isinstance(raw, dict):
            data = raw
        else:
            return cls(floor=0.0, direction=0, lift_id=default_lift_id, state="IDLE", queue=[])

        return cls(
            floor=float(data.get("floor", 0.0)),
            direction=int(data.get("direction", 0)),
            lift_id=data.get("lift_id", default_lift_id),
            state=data.get("state", "IDLE"),
            target_floor=data.get("target_floor"),
            queue=list(data.get("queue", [])),
            updated_at=float(data.get("updated_at", 0.0))
        )


class HallRequestIn(BaseModel):
    floor: int
    direction: str


class HallRequest(BaseModel):
    """
    Tuple representing a hall call: (floor number, direction (UP | DOWN)).
    """
    floor: int
    direction: str  # "UP" or "DOWN"
    request_id: Optional[str] = None
    created_at: float = 0.0

    def key(self) -> str:
        """Redis hash field key: e.g. '7:UP' or '3:DOWN'."""
        return f"{self.floor}:{self.direction.upper()}"

    def to_json(self) -> str:
        data = {
            "floor": self.floor,
            "direction": self.direction.upper(),
            "request_id": self.request_id or f"{self.floor}_{self.direction.upper()}_{int(time.time()*1000)}",
            "created_at": self.created_at or time.time()
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: Any) -> "HallRequest":
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        return cls(
            floor=int(data["floor"]),
            direction=data["direction"].upper(),
            request_id=data.get("request_id"),
            created_at=float(data.get("created_at", time.time()))
        )


class DispatchAssignment(BaseModel):
    lift_id: str
    request: HallRequest
    cost: float
    reason: str
    timestamp: float = 0.0
