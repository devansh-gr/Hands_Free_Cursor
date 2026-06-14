"""Telekinesis engine — real-time loop (camera-free, pure AirPods).

Pipeline per frame:
  drain UDP -> quat->Euler -> One Euro filter -> absolute map -> ease -> CGEvent
  + dwell-click state machine (park cursor 0.8s => click)
  + roll-tilt gestures: left = toggle clicking, right = summon Claude (M3)

Keys: [c] recenter   [d] toggle dwell clicking   [q] quit
Run with --debug-angles to verify axis assignment before first calibration.
"""

import math
import select
import statistics
import sys
import termios
import time
import tty

import config
import cursor
import snap
from calibrate import load_axes, run_calibration, save_axes
from dwell import DwellClicker
from filters import OneEuro
from gestures import TiltDetector
from imu_rx import IMUReceiver
from mapping import AbsoluteMapper
from pose import head_euler
from targets import TargetTracker


def uptime_now() -> float:
    """Same clock base as CMDeviceMotion.timestamp (mach_absolute_time)."""
    return time.clock_gettime(time.CLOCK_UPTIME_RAW)


class RawTerminal:
    """cbreak mode so single keypresses arrive without Enter; restores on exit."""

    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    @staticmethod
    def pending_key() -> str | None:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


def notify(msg: str) -> None:
    """Print above the HUD line without corrupting it."""
    sys.stdout.write("\r\033[K" + msg + "\n")
    sys.stdout.flush()


def run(debug_angles: bool = False) -> None:
    axes = load_axes()
    if axes is None and not debug_angles:
        print("No axis calibration found. Run once (20s, guided):")
        print("  ~/Documents/Projects/AirPods_Telekinesis/run_engine.sh --calibrate")
        sys.exit(1)

    rx = IMUReceiver(config.UDP_HOST, config.UDP_PORT)
    screen_w, screen_h = cursor.screen_size()
    if axes is not None:
        mapper = AbsoluteMapper(
            screen_w, screen_h, config.X_RANGE_DEG, config.Y_RANGE_DEG,
            axes["x_sign"], axes["y_sign"],
        )
        tilt = TiltDetector(config.TILT_THRESHOLD_DEG, config.TILT_HOLD_S,
                            axes["tilt_sign"])
    fx = OneEuro(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF)
    fy = OneEuro(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF)
    dwell = DwellClicker(config.DWELL_RADIUS_PX, config.DWELL_TIME_S,
                         config.DWELL_REARM_RADIUS_PX)
    dwell.enabled = False  # SAFETY: clicking is opt-in, never on at launch

    snap_on = config.SNAP_ENABLED
    tracker = TargetTracker(config.TARGET_REFRESH_HZ, config.TARGET_MAX_ELEMENTS,
                            config.TARGET_WALK_TIMEOUT_S, screen_w * screen_h)
    tracker.start()

    if not cursor.accessibility_trusted():
        print("WARNING: no Accessibility permission — cursor events will be dropped.")
        print("Fix: System Settings → Privacy & Security → Accessibility → enable your terminal.\n")

    print(f"engine: listening on udp://{config.UDP_HOST}:{config.UDP_PORT}, "
          f"screen {screen_w:.0f}x{screen_h:.0f}")
    print("engine: waiting for first IMU sample (start the bridge, AirPods in-ear)…")
    print()
    print("SAFE START: the cursor will NOT move until you press [c].")
    print("  1. look at the CENTER of your screen")
    print("  2. press [c]  → cursor control engages, calibrated to that pose")
    print("  3. press [d] when ready to enable dwell-clicking (starts OFF)")
    print()
    print("keys: [c] recenter+engage  [SPACE] panic freeze  [d] clicking on/off")
    print("      [s] snap-to-button on/off  [v] invert up/down  [b] invert left/right  [q] quit")
    print("gestures: park cursor = click | tilt LEFT = clicking on/off | tilt RIGHT = Claude\n")

    latencies: list[float] = []
    imu_times: list[float] = []
    target: tuple[float, float] | None = None
    eased: tuple[float, float] | None = None
    roll_delta_deg = 0.0
    frozen = False
    engaged = False  # SAFETY: no cursor output until the user presses [c]
    last_hud = 0.0
    frame_dt = 1.0 / config.RENDER_HZ

    with RawTerminal():
        while True:
            frame_start = time.monotonic()

            key = RawTerminal.pending_key()
            if key == "q":
                break
            if key == " ":
                engaged = not engaged
                dwell.reset()
                eased = target = None
                notify("cursor control " + ("RESUMED" if engaged else "FROZEN (panic)"))
            if key == "d":
                notify(f"clicking {'ENABLED' if dwell.toggle() else 'DISABLED'} (key)")
            if key == "s":
                snap_on = not snap_on
                notify(f"snap-to-button {'ON' if snap_on else 'OFF'}")
            if key == "v":
                mapper.y_sign *= -1.0
                axes["y_sign"] = mapper.y_sign
                save_axes(axes)
                notify(f"up/down inverted (y_sign {mapper.y_sign:+.0f}) — saved")
            if key == "b":
                mapper.x_sign *= -1.0
                axes["x_sign"] = mapper.x_sign
                save_axes(axes)
                notify(f"left/right inverted (x_sign {mapper.x_sign:+.0f}) — saved")

            sample = rx.latest()
            if sample is not None:
                now = uptime_now()
                angles = head_euler(
                    sample["qw"], sample["qx"], sample["qy"], sample["qz"])

                latencies.append((now - sample["t"]) * 1000.0)
                imu_times.append(now)
                if len(latencies) > config.LATENCY_WINDOW:
                    latencies.pop(0)
                imu_times[:] = [t for t in imu_times if now - t < 1.0]

                if debug_angles:
                    sys.stdout.write(
                        f"\rheading {math.degrees(angles['heading']):+7.2f}°  "
                        f"elevation {math.degrees(angles['elevation']):+7.2f}°  "
                        f"tilt {math.degrees(angles['tilt']):+7.2f}°   ")
                    sys.stdout.flush()
                    continue

                x_angle = fx(angles[axes["x_source"]], sample["t"])
                y_angle = fy(angles[axes["y_source"]], sample["t"])
                roll_deg = math.degrees(angles[axes["tilt_source"]])

                if key == "c":
                    mapper.recenter(x_angle, y_angle)
                    tilt.set_baseline(roll_deg)
                    dwell.reset()
                    engaged = True
                    notify("recentered + ENGAGED — current pose is screen center")

                if engaged:
                    roll_delta_deg = tilt.delta_deg(roll_deg)
                    gesture = tilt.update(roll_deg, sample["t"])
                    if gesture == "left":
                        notify(f"clicking {'ENABLED' if dwell.toggle() else 'DISABLED'} (tilt)")
                    elif gesture == "right":
                        notify("SUMMON Claude — M3 not built yet (stub)")
                        cursor.play_click_sound()

                    # While the head is tilted for a gesture, yaw/pitch cross-
                    # couple and would drag the cursor — freeze pointing/dwell.
                    frozen = abs(roll_delta_deg) > config.CURSOR_FREEZE_ROLL_DEG
                    if not frozen:
                        target = mapper.map(x_angle, y_angle)

            snap_label = None
            if engaged and target is not None and not debug_angles:
                if eased is None:
                    eased = target
                # Exponential ease toward the latest target: upsamples 25 Hz
                # IMU to RENDER_HZ so motion is continuous, not stepped.
                k = 1.0 - math.exp(-frame_dt / config.EASE_TIME_CONST_S)
                eased = (eased[0] + (target[0] - eased[0]) * k,
                         eased[1] + (target[1] - eased[1]) * k)

                # Magnetic snap: pull the head-driven cursor onto the nearest
                # real clickable element. The dwell anchors at the SNAPPED
                # point, so clicks land dead-center on the button.
                render_pt = eased
                if snap_on and not frozen:
                    tgt, dist = snap.nearest(tracker.snapshot(), eased[0], eased[1],
                                             config.SNAP_RADIUS_PX)
                    if tgt is not None:
                        render_pt, w = snap.snap_point(
                            eased, (tgt.cx, tgt.cy), dist,
                            config.SNAP_FULL_PX, config.SNAP_RADIUS_PX)
                        if w > 0.0:
                            snap_label = tgt.label
                cursor.move(*render_pt)

                # No dwell while gesturing OR while pinned against a screen
                # edge — an edge-clamped cursor is "parked" by definition and
                # would turn screen corners into click machines.
                if not frozen and not mapper.last_clamped:
                    fire = dwell.update(render_pt[0], render_pt[1], time.monotonic())
                    if fire is not None:
                        cursor.click(*fire)
                        if config.CLICK_SOUND:
                            cursor.play_click_sound()
                        tag = f" → {snap_label}" if snap_label else ""
                        notify(f"CLICK #{dwell.clicks} at ({fire[0]:.0f}, {fire[1]:.0f}){tag}")

            now_mono = time.monotonic()
            if latencies and now_mono - last_hud > 1.0 / config.HUD_UPDATE_HZ:
                last_hud = now_mono
                avg = statistics.fmean(latencies)
                p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]
                if not engaged:
                    state = "OFF — press [c] at screen center"
                elif frozen:
                    state = "FROZEN(tilt)"
                elif not dwell.enabled:
                    state = "click:OFF"
                else:
                    pct = dwell.progress(now_mono)
                    state = f"click:{'▆' * int(pct * 5):<5}" if pct > 0 else "click:armed"
                pos = f"({eased[0]:4.0f},{eased[1]:4.0f})" if eased else "(waiting)"
                if not snap_on:
                    snap_txt = "snap:off"
                elif snap_label:
                    snap_txt = f"🧲 {snap_label[:18]}"
                else:
                    snap_txt = f"snap:{tracker.last_count} tgts"
                sys.stdout.write(
                    f"\rIMU {len(imu_times):3d} Hz | lat {avg:4.1f}/{p95:4.1f} ms "
                    f"| {pos} | {state} | {snap_txt} | clicks {dwell.clicks} "
                    f"| roll {roll_delta_deg:+5.1f}°  ")
                sys.stdout.flush()

            sleep_left = frame_dt - (time.monotonic() - frame_start)
            if sleep_left > 0:
                time.sleep(sleep_left)

    tracker.stop()
    print("\nengine: stopped")


if __name__ == "__main__":
    if "--calibrate" in sys.argv:
        run_calibration()
    else:
        run(debug_angles="--debug-angles" in sys.argv)
