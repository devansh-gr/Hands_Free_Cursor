"""Dwell-to-click state machine.

Park the cursor within a radius for DWELL_TIME_S => exactly one click at the
qdso staring at one spot can never machine-gun clicks.
"""

import math


class DwellClicker:
    def __init__(self, radius_px: float, dwell_s: float, rearm_radius_px: float) -> None:
        assert rearm_radius_px > radius_px, "hysteresis requires rearm > dwell radius"
        self.radius = radius_px
        self.dwell_s = dwell_s
        self.rearm_radius = rearm_radius_px
        self.enabled = True
        self.clicks = 0
        self._anchor: tuple[float, float] | None = None
        self._anchor_t = 0.0
        self._fired = False

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        self.reset()
        return self.enabled

    def reset(self) -> None:
        """Drop any pending dwell (e.g., after a pause or recenter)."""
        self._anchor = None
        self._fired = False

    def update(self, x: float, y: float, t: float) -> tuple[float, float] | None:
        """Feed cursor position each frame. Returns the click point when a
        dwell completes, else None."""
        if not self.enabled:
            return None
        if self._anchor is None:
            self._anchor, self._anchor_t = (x, y), t
            return None

        dist = math.hypot(x - self._anchor[0], y - self._anchor[1])

        if self._fired:
            # Stay quiet until the cursor genuinely leaves the clicked spot.
            if dist > self.rearm_radius:
                self._fired = False
                self._anchor, self._anchor_t = (x, y), t
            return None

        if dist > self.radius:
            self._anchor, self._anchor_t = (x, y), t
            return None

        if t - self._anchor_t >= self.dwell_s:
            self._fired = True
            self.clicks += 1
            return self._anchor
        return None

    def progress(self, t: float) -> float:
        """0..1 settle progress for the HUD; 0 when idle/fired/disabled."""
        if not self.enabled or self._anchor is None or self._fired:
            return 0.0
        return min(1.0, (t - self._anchor_t) / self.dwell_s)
