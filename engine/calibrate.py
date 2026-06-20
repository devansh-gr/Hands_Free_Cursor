"""Guided axis calibration — measures, on the user's actual head, which
angle channel responds to look-right / look-up / tilt-right, and with what
sign. Writes axes.json, which the engine loads at startup. Kills the entire
class of 'wrong axis convention' bugs by never assuming a frame layout."""

import json
import math
import os
import time

from imu_rx import IMUReceiver
from pose import head_euler, wrap_angle

AXES_PATH = os.path.join(os.path.dirname(__file__), "axes.json")
CHANNELS = ("heading", "elevation", "tilt")


def _collect_mean(rx: IMUReceiver, seconds: float) -> dict[str, float]:
    """Average each angle channel over a window. Requires live IMU data."""
    sums = dict.fromkeys(CHANNELS, 0.0)
    ref: dict[str, float] | None = None
    n = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        sample = rx.latest()
        if sample is None:
            time.sleep(0.005)
            continue
        angles = head_euler(sample["qw"], sample["qx"], sample["qy"], sample["qz"])
        if ref is None:
            ref = angles  # average wrap-aware deltas around the first sample
        for k in CHANNELS:
            sums[k] += wrap_angle(angles[k] - ref[k])
        n += 1
    if n < 10 or ref is None:
        raise RuntimeError(
            f"only {n} IMU samples received — is the bridge running and AirPods in-ear?")
    return {k: ref[k] + sums[k] / n for k in CHANNELS}


def _step(rx: IMUReceiver, base: dict[str, float], prompt: str) -> tuple[str, float, float]:
    """One guided pose: returns (channel, signed_delta_rad, magnitude_deg)."""
    input(f"  → {prompt}, HOLD it, then press ENTER (keep holding)… ")
    time.sleep(0.3)  # settle after the keypress
    held = _collect_mean(rx, 1.0)
    deltas = {k: wrap_angle(held[k] - base[k]) for k in CHANNELS}
    channel = max(deltas, key=lambda k: abs(deltas[k]))
    return channel, deltas[channel], math.degrees(abs(deltas[channel]))


def run_calibration() -> None:
    rx = IMUReceiver_or_die()
    print("\n=== AXIS CALIBRATION (~20 seconds) ===")
    print("Bridge must be running, AirPods in-ear. Three guided poses.\n")

    input("Sit naturally, look STRAIGHT at your screen center, press ENTER… ")
    time.sleep(0.3)
    base = _collect_mean(rx, 1.0)
    print("  baseline captured ✓\n")

    x_src, x_delta, x_mag = _step(rx, base, "turn your head RIGHT (like checking a side mirror)")
    print(f"  look-right → '{x_src}' channel ({x_mag:.0f}°) ✓\n")
    input("Return to center, press ENTER… ")
    base = _collect_mean(rx, 1.0)

    y_src, y_delta, y_mag = _step(rx, base, "tip your head UP (look at the wall-ceiling corner)")
    print(f"  look-up → '{y_src}' channel ({y_mag:.0f}°) ✓\n")
    input("Return to center, press ENTER… ")
    base = _collect_mean(rx, 1.0)

    t_src, t_delta, t_mag = _step(rx, base, "tilt your RIGHT EAR toward your RIGHT shoulder")
    print(f"  tilt-right → '{t_src}' channel ({t_mag:.0f}°) ✓\n")

    if len({x_src, y_src, t_src}) != 3:
        raise RuntimeError(
            f"channels collided ({x_src}/{y_src}/{t_src}) — movements too small or "
            "mixed. Re-run and exaggerate each pose (~20° or more).")
    if min(x_mag, y_mag, t_mag) < 5.0:
        raise RuntimeError("a pose moved <5° — re-run and exaggerate the movements.")

    axes = {
        # cursor x: positive screen-x is right => sign makes look-right positive
        "x_source": x_src, "x_sign": 1.0 if x_delta > 0 else -1.0,
        # cursor y: screen y grows DOWNWARD => look-up must map negative
        "y_source": y_src, "y_sign": -1.0 if y_delta > 0 else 1.0,
        # tilt: positive = right tilt (summon side)
        "tilt_source": t_src, "tilt_sign": 1.0 if t_delta > 0 else -1.0,
    }
    with open(AXES_PATH, "w") as f:
        json.dump(axes, f, indent=2)
    print(f"=== saved {AXES_PATH} ===")
    print(f"  cursor X ← {axes['x_source']} (sign {axes['x_sign']:+.0f})")
    print(f"  cursor Y ← {axes['y_source']} (sign {axes['y_sign']:+.0f})")
    print(f"  gestures ← {axes['tilt_source']} (sign {axes['tilt_sign']:+.0f})")
    print("\nCalibration done — run the engine normally now.")


def IMUReceiver_or_die() -> IMUReceiver:
    import config
    try:
        return IMUReceiver(config.UDP_HOST, config.UDP_PORT)
    except OSError as e:
        raise RuntimeError(
            f"cannot bind UDP {config.UDP_PORT} — is another engine instance running? ({e})")


def load_axes() -> dict | None:
    """Calibrated axes, or None if the wizard hasn't been run."""
    if not os.path.exists(AXES_PATH):
        return None
    with open(AXES_PATH) as f:
        return json.load(f)


def save_axes(axes: dict) -> None:
    """Persist axes (e.g. after a live sign flip) so the fix survives restarts."""
    with open(AXES_PATH, "w") as f:
        json.dump(axes, f, indent=2)
