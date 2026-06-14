"""Magnetic snap math — pure and unit-testable.

Given the head-driven cursor position and the distance to the nearest
clickable target, decide where the cursor should actually render: the closer
it is to a target, the harder it is pulled in, until it fully sticks. This is
what turns "near the button" into "on the button" without precise head control.
"""


def _smoothstep(e0: float, e1: float, x: float) -> float:
    if x <= e0:
        return 0.0
    if x >= e1:
        return 1.0
    t = (x - e0) / (e1 - e0)
    return t * t * (3.0 - 2.0 * t)


def pull_weight(dist: float, full_px: float, radius_px: float) -> float:
    """Attraction strength in [0, 1].

    1.0 when within full_px (fully snapped), 0.0 at/beyond radius_px,
    smoothly increasing as the cursor approaches.
    """
    if dist <= full_px:
        return 1.0
    if dist >= radius_px:
        return 0.0
    return 1.0 - _smoothstep(full_px, radius_px, dist)


def speed_gain(speed: float, slow_px_s: float, fast_px_s: float) -> float:
    """Magnet strength vs. cursor speed: 1.0 when settling (<= slow), 0.0 while
    traversing (>= fast), smooth between. This is what stops the cursor getting
    yanked onto every button it passes — the magnet only acts when you slow to
    land on a target."""
    if speed <= slow_px_s:
        return 1.0
    if speed >= fast_px_s:
        return 0.0
    return 1.0 - _smoothstep(slow_px_s, fast_px_s, speed)


def snap_point(cursor_xy: tuple[float, float], target_xy: tuple[float, float],
               dist: float, full_px: float, radius_px: float,
               strength: float = 1.0) -> tuple[tuple[float, float], float]:
    """Blend cursor toward target by (pull weight x strength). Returns (xy, weight)."""
    w = pull_weight(dist, full_px, radius_px) * max(0.0, min(1.0, strength))
    cx, cy = cursor_xy
    tx, ty = target_xy
    return (cx + (tx - cx) * w, cy + (ty - cy) * w), w


def nearest(targets, x: float, y: float, radius: float):
    """Closest target within radius, as (target, distance), else (None, inf)."""
    best, best_d = None, float("inf")
    for t in targets:
        d = ((t.cx - x) ** 2 + (t.cy - y) ** 2) ** 0.5
        if d < best_d:
            best, best_d = t, d
    if best is None or best_d > radius:
        return None, float("inf")
    return best, best_d
