"""Absolute head-pose -> screen-coordinate mapping with recentering."""

import math

from pose import wrap_angle


class AbsoluteMapper:
    """Maps angular offset from a calibrated origin to screen pixels, clamped.

    Linear small-angle mapping: at desk distances and ±15° sweeps, the
    tan-projection error vs. linear is <1.2% — not worth the complexity.
    """

    def __init__(self, screen_w: float, screen_h: float,
                 x_range_deg: float, y_range_deg: float,
                 x_sign: float, y_sign: float) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.x_half_range = math.radians(x_range_deg)
        self.y_half_range = math.radians(y_range_deg)
        self.x_sign = x_sign
        self.y_sign = y_sign
        self.x0: float | None = None
        self.y0: float | None = None
        self.last_clamped = False  # True when the last map() hit a screen edge

    @property
    def calibrated(self) -> bool:
        return self.x0 is not None

    def recenter(self, x_angle: float, y_angle: float) -> None:
        """Current head pose becomes screen center. Kills accumulated drift."""
        self.x0 = x_angle
        self.y0 = y_angle

    def map(self, x_angle: float, y_angle: float) -> tuple[float, float]:
        assert self.x0 is not None and self.y0 is not None, "recenter() first"
        dx = wrap_angle(x_angle - self.x0) * self.x_sign
        dy = wrap_angle(y_angle - self.y0) * self.y_sign
        x = (dx / self.x_half_range * 0.5 + 0.5) * self.screen_w
        y = (dy / self.y_half_range * 0.5 + 0.5) * self.screen_h
        xc = min(max(x, 0.0), self.screen_w - 1.0)
        yc = min(max(y, 0.0), self.screen_h - 1.0)
        # An edge-pinned cursor is stationary by definition — callers must not
        # treat it as an intentional dwell, or edges become click machines.
        self.last_clamped = (xc != x) or (yc != y)
        return xc, yc
