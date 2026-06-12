"""One Euro filter (Casiez, Roussel, Vogel — CHI 2012).

Adaptive low-pass: heavy smoothing when the signal is slow (kills jitter at
rest), light smoothing when it is fast (kills lag during deliberate motion).
The right tool for cursor signals, where jitter and lag are both fatal.
"""

import math


class _LowPass:
    def __init__(self) -> None:
        self.y: float | None = None

    def __call__(self, x: float, alpha: float) -> float:
        if self.y is None:
            self.y = x
        else:
            self.y = alpha * x + (1.0 - alpha) * self.y
        return self.y


def _alpha(cutoff: float, dt: float) -> float:
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuro:
    def __init__(self, min_cutoff: float, beta: float, d_cutoff: float) -> None:
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x = _LowPass()
        self._dx = _LowPass()
        self._t_prev: float | None = None

    def __call__(self, x: float, t: float) -> float:
        if self._t_prev is None:
            self._t_prev = t
            return self._x(x, 1.0)
        dt = t - self._t_prev
        self._t_prev = t
        if dt <= 0.0:
            # Duplicate/reordered timestamp; return current state unchanged.
            return self._x.y if self._x.y is not None else x

        dx = (x - (self._x.y if self._x.y is not None else x)) / dt
        dx_hat = self._dx(dx, _alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        return self._x(x, _alpha(cutoff, dt))
