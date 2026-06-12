"""Roll-axis tilt gestures: sustained head tilt left/right, one event per
excursion. The roll baseline is captured at recenter time, since nobody's
head sits at exactly 0° roll naturally."""


class TiltDetector:
    IDLE, PENDING, FIRED = 0, 1, 2

    def __init__(self, threshold_deg: float, hold_s: float, right_sign: float) -> None:
        self.threshold_deg = threshold_deg
        self.hold_s = hold_s
        self.right_sign = right_sign
        self.baseline_deg = 0.0
        self._state = self.IDLE
        self._side: str | None = None
        self._t_enter = 0.0

    def set_baseline(self, roll_deg: float) -> None:
        self.baseline_deg = roll_deg

    def delta_deg(self, roll_deg: float) -> float:
        """Signed tilt relative to baseline; positive = tilt right."""
        return (roll_deg - self.baseline_deg) * self.right_sign

    def update(self, roll_deg: float, t: float) -> str | None:
        """Feed roll each IMU sample. Returns 'left'/'right' once per
        sustained excursion past threshold, else None."""
        d = self.delta_deg(roll_deg)
        side = "right" if d > self.threshold_deg else ("left" if d < -self.threshold_deg else None)

        if side is None:
            self._state = self.IDLE
            self._side = None
            return None

        if self._state == self.IDLE or side != self._side:
            self._state, self._side, self._t_enter = self.PENDING, side, t
            return None

        if self._state == self.PENDING and t - self._t_enter >= self.hold_s:
            self._state = self.FIRED
            return side
        return None
