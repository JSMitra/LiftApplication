from typing import List, Dict, Optional, Tuple
from app.models import LiftStatus, HallRequest, DispatchAssignment, Direction
from app.config import settings


def calculate_lift_cost(
    request: HallRequest,
    status: LiftStatus,
    queue: List[int],
    floor_count: int = None
) -> Tuple[float, str]:
    """
    Evaluates dispatch suitability (figure of merit / cost) of a lift for a hall call.
    Lower score means better candidate.

    Heuristic categories:
    1. Nearest Approaching in Same Direction: Minimum cost (direct en-route pickup).
    2. IDLE Lift: Low cost (|dist| + idle bias).
    3. Approaching in Opposite Direction: Moderate penalty.
    4. Moving Away: Highest cost (turnaround penalty).
    """
    fc = floor_count or settings.FLOOR_COUNT
    req_floor = request.floor
    req_dir_int = 1 if request.direction.upper() == "UP" else -1

    curr_floor = status.floor
    curr_dir = status.direction
    q_len = len(queue)

    # 1. Approaching in the SAME direction
    if curr_dir == req_dir_int:
        if curr_dir == 1 and curr_floor <= req_floor:
            # Lift is moving UP and is below or at the request
            dist = req_floor - curr_floor
            cost = dist + (0.1 * q_len)
            reason = f"Approaching UP (dist: {dist:.1f}, queue: {q_len})"
            return (cost, reason)

        elif curr_dir == -1 and curr_floor >= req_floor:
            # Lift is moving DOWN and is above or at the request
            dist = curr_floor - req_floor
            cost = dist + (0.1 * q_len)
            reason = f"Approaching DOWN (dist: {dist:.1f}, queue: {q_len})"
            return (cost, reason)

    # 2. Lift is IDLE (direction == 0)
    if curr_dir == 0:
        dist = abs(curr_floor - req_floor)
        # Small idle bias so a moving lift 0.5 floors away can pick up en route,
        # but otherwise an IDLE lift is ready immediately.
        cost = dist + 1.5 + (0.05 * q_len)
        reason = f"IDLE at floor {curr_floor:.1f} (dist: {dist:.1f})"
        return (cost, reason)

    # 3. Moving towards request floor, but OPPOSITE requested direction
    # (e.g. lift moving UP past floor 7, but passenger at floor 7 wants to go DOWN)
    if (curr_dir == 1 and curr_floor < req_floor) or (curr_dir == -1 and curr_floor > req_floor):
        dist = abs(curr_floor - req_floor)
        cost = dist + (fc * 0.75) + (0.2 * q_len)
        reason = f"Approaching opposite direction (dist: {dist:.1f})"
        return (cost, reason)

    # 4. Moving AWAY from request
    # (e.g. lift moving UP at floor 8, but request is at floor 4)
    dist = abs(curr_floor - req_floor)
    cost = dist + (fc * 2.0) + (0.5 * q_len)
    reason = f"Moving away (dist: {dist:.1f}, queue: {q_len})"
    return (cost, reason)


def select_best_lift(
    request: HallRequest,
    lift_statuses: Dict[str, LiftStatus],
    lift_queues: Dict[str, List[int]],
    floor_count: int = None
) -> Optional[DispatchAssignment]:
    """
    Selects the optimal lift from the 16 stateful lifts to service the hall request.
    """
    if not lift_statuses:
        return None

    best_assignment: Optional[DispatchAssignment] = None
    min_cost = float("inf")

    # Sort lift IDs for deterministic behavior in case of exact ties
    for lift_id in sorted(lift_statuses.keys(), key=lambda x: int(x.split("-")[-1]) if x.split("-")[-1].isdigit() else 0):
        status = lift_statuses[lift_id]
        queue = lift_queues.get(lift_id, [])

        cost, reason = calculate_lift_cost(request, status, queue, floor_count)

        if cost < min_cost:
            min_cost = cost
            best_assignment = DispatchAssignment(
                lift_id=lift_id,
                request=request,
                cost=cost,
                reason=reason
            )

    return best_assignment

