"""Quaternion -> head-angle conversion. Pure math, unit-testable.

AirPods report attitude in a head-centric frame: x through the right ear,
y up through the skull, z out the back of the head. Head motions are then
rotations about distinct axes:
    shake ("no")  = about y   -> heading
    nod ("yes")   = about x   -> elevation
    tilt ("huh?") = about z   -> tilt
A Z-Y-X (aerospace) Euler decomposition assumes z is the vertical axis and
mixes these channels badly — the correct decomposition for this frame is
intrinsic Y-X-Z. Final axis-to-cursor assignment and signs are still measured
per-user by the calibration wizard, never assumed.
"""

import math


def quat_to_matrix(qw: float, qx: float, qy: float, qz: float) -> list[list[float]]:
    """Unit quaternion -> 3x3 rotation matrix (row-major)."""
    return [
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ]


def head_euler(qw: float, qx: float, qy: float, qz: float) -> dict[str, float]:
    """Decompose attitude as intrinsic Y-X-Z: R = Ry(heading)·Rx(elevation)·Rz(tilt).

    Returns {"heading", "elevation", "tilt"} in radians. Heading/tilt in
    [-pi, pi]; elevation in [-pi/2, pi/2] (clamped against float noise at
    gimbal lock, i.e. looking straight up/down).
    """
    r = quat_to_matrix(qw, qx, qy, qz)
    heading = math.atan2(r[0][2], r[2][2])
    elevation = math.asin(max(-1.0, min(1.0, -r[1][2])))
    tilt = math.atan2(r[1][0], r[1][1])
    return {"heading": heading, "elevation": elevation, "tilt": tilt}


def wrap_angle(a: float) -> float:
    """Wrap an angle to [-pi, pi]. Needed when differencing across ±pi."""
    return math.atan2(math.sin(a), math.cos(a))
