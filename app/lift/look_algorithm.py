from typing import Set, Tuple, Optional, Collection


def compute_look_next_target(
    current_floor: float,
    current_direction: int,
    queued_floors: Collection[int]
) -> Tuple[Optional[int], int]:
    """
    Computes the next target floor and direction using the classic elevator LOOK algorithm.

    In LOOK scheduling:
    - If traveling UP (+1):
        - Visit the lowest floor strictly above current_floor.
        - If no requests exist above, reverse direction to DOWN (-1) and visit the highest request below.
    - If traveling DOWN (-1):
        - Visit the highest floor strictly below current_floor.
        - If no requests exist below, reverse direction to UP (+1) and visit the lowest request above.
    - If IDLE (0):
        - Head towards the nearest requested floor (ties prefer UP).
    - If the current floor is in queued_floors and lift is stationary or arriving, service it.
    - If queued_floors is empty:
        - Return (None, 0) -> IDLE.

    Returns:
        (target_floor, next_direction)
    """
    if not queued_floors:
        return (None, 0)

    floors = set(int(f) for f in queued_floors)
    
    # Check if we are right now on one of the queued floors (servicing immediately)
    curr_int = int(round(current_floor))
    if abs(current_floor - curr_int) < 1e-4 and curr_int in floors:
        # If already at this floor, service it!
        return (curr_int, current_direction)

    # 1. Moving UP
    if current_direction == 1:
        above = [f for f in floors if f > current_floor]
        if above:
            return (min(above), 1)
        # No more floors above; reverse to DOWN and take the highest floor below
        below = [f for f in floors if f < current_floor]
        if below:
            return (max(below), -1)
        # Should not reach here if floors is not empty, but fallback
        return (min(floors), 1)

    # 2. Moving DOWN
    elif current_direction == -1:
        below = [f for f in floors if f < current_floor]
        if below:
            return (max(below), -1)
        # No more floors below; reverse to UP and take the lowest floor above
        above = [f for f in floors if f > current_floor]
        if above:
            return (min(above), 1)
        return (max(floors), -1)

    # 3. IDLE (direction == 0)
    else:
        # Find closest floor
        # In case of tie, prefer the higher floor
        sorted_by_dist = sorted(floors, key=lambda f: (abs(f - current_floor), -f))
        closest = sorted_by_dist[0]
        if closest > current_floor:
            return (closest, 1)
        elif closest < current_floor:
            return (closest, -1)
        else:
            return (closest, 0)

