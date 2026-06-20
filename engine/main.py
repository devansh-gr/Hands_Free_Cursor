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
import confirm
import cursor
import scroll
import snap
import summon as summon_mod
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


DEFAULT_AXES = {"x_source": "heading", "x_sign": 1.0,
                "y_source": "elevation", "y_sign": -1.0,
                "tilt_source": "tilt", "tilt_sign": 1.0}


def run(debug_angles: bool = False) -> None:
    axes = load_axes()
    if axes is None:
        if not debug_angles:
            print("No axis calibration found. Run once (~20s, guided):")
            print("  ~/Documents/Projects/AirPods_Telekinesis/run_engine.sh --calibrate")
            sys.exit(1)
        axes = dict(DEFAULT_AXES)  # debug-angles doesn't use the mapping

    rx = IMUReceiver(config.UDP_HOST, config.UDP_PORT)
    screen_w, screen_h = cursor.screen_size()
    mapper = AbsoluteMapper(
        screen_w, screen_h, config.X_RANGE_DEG, config.Y_RANGE_DEG,
        axes["x_sign"], axes["y_sign"],
    )
    mapper.set_scale(axes.get("range_scale", 1.0))  # persisted sensitivity
    tilt = TiltDetector(config.TILT_THRESHOLD_DEG, config.TILT_HOLD_S,
                        axes["tilt_sign"])
    fx = OneEuro(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF)
    fy = OneEuro(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF)
    dwell = DwellClicker(config.DWELL_RADIUS_PX,
                         axes.get("dwell_time", config.DWELL_TIME_S),
                         config.DWELL_REARM_RADIUS_PX)
    # Confirm-click: a separate dwell opens the ✓/✕ panel on a button.
    open_dwell = DwellClicker(config.DWELL_RADIUS_PX, config.CONFIRM_OPEN_S,
                              config.DWELL_REARM_RADIUS_PX)
    click_mode = config.CLICK_MODE  # "confirm" | "direct"; toggle with [m]
    overlay = confirm.ConfirmOverlay()
    if click_mode == "confirm" and not overlay.available:
        click_mode = "direct"  # windowing unavailable — fall back gracefully
    # Confirm mode is safe to leave ON (nothing clicks without confirmation), so
    # default it on — that's what users expect. Direct mode stays opt-in.
    dwell.enabled = (click_mode == "confirm")
    confirm_active = False
    panel = None  # current confirm panel layout (dict)
    confirm_target: tuple[float, float] | None = None
    choose_region: str | None = None
    choose_t = 0.0
    confirm_deadline = 0.0

    # Claude summon (tilt-right): screenshot -> claude CLI -> answer panel.
    summoner = summon_mod.Summoner()
    summon_overlay = summon_mod.TextOverlay()
    summon_visible = False
    summon_last_state: str | None = None
    summon_shown_t = 0.0

    snap_on = config.SNAP_ENABLED
    snap_ctrl = snap.SnapController(config.SNAP_RADIUS_PX, config.SNAP_FULL_PX)
    gestures_on = True  # tilt-right = summon Claude; no cursor-freeze anymore
    scroll_invert = config.SCROLL_INVERT
    scroll_enabled = config.SCROLL_ENABLED
    scroll_speed = config.SCROLL_MAX_SPEED
    scroll_accum = 0.0
    scroll_arm_t: float | None = None
    tracker = TargetTracker(config.TARGET_REFRESH_HZ, config.TARGET_MAX_ELEMENTS,
                            config.TARGET_WALK_TIMEOUT_S, screen_w * screen_h,
                            config.SNAP_MAX_TARGET_H)
    tracker.start()
    pending_recenter = config.AUTO_ENGAGE  # engage on the first IMU sample

    if not cursor.accessibility_trusted():
        print("WARNING: no Accessibility permission — cursor events will be dropped.")
        print("Fix: System Settings → Privacy & Security → Accessibility → enable your terminal.\n")

    print(f"engine: listening on udp://{config.UDP_HOST}:{config.UDP_PORT}, "
          f"screen {screen_w:.0f}x{screen_h:.0f}")
    print("engine: waiting for first IMU sample (start the bridge, AirPods in-ear)…")
    print()
    if config.AUTO_ENGAGE:
        print("AUTO-ENGAGE: control turns on the moment your AirPods stream.")
        print("  • look at screen center as it starts (that pose becomes center)")
        print("  • [c] re-center anytime  • [SPACE] pause/resume  • [q] quit")
    else:
        print("Press [c] (looking at screen center) to engage.")
    print()
    print(f"CLICK MODE: {click_mode.upper()}  "
          f"({'hover a button → ✓Click/✕Cancel panel → glide to choose' if click_mode == 'confirm' else 'dwell on a button → clicks directly'})")
    print()
    print("keys: [c] recenter+engage  [SPACE] panic freeze  [d] clicking on/off")
    print("      [m] click mode (confirm/direct)  [-]/[=] sensitivity  [ [ ]/[ ] ] click speed")
    print("      [s] snap on/off  [i] flip scroll dir  [v] invert up/down  [b] invert left/right")
    print("      [g] tilt gestures on/off  [p] diagnostics  [q] quit")
    print("scroll: rest cursor near the TOP or BOTTOM edge of the screen to scroll")
    print("summon: tilt your head RIGHT ('huh?') → Claude reads your screen + answers\n")

    latencies: list[float] = []
    imu_times: list[float] = []
    target: tuple[float, float] | None = None
    eased: tuple[float, float] | None = None
    prev_eased: tuple[float, float] | None = None
    speed_ema = 0.0  # smoothed cursor speed (px/s), for the snap velocity gate
    roll_delta_deg = 0.0
    engaged = False  # SAFETY: no cursor output until the user presses [c]
    last_hud = 0.0
    frame_dt = 1.0 / config.RENDER_HZ
    # IMU-stall detection: the cursor only moves on fresh head-motion samples,
    # so a "freeze" usually means the AirPods motion stream dropped out.
    last_imu_mono: float | None = None
    imu_stalls = 0
    stall_active = False

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
            if key == "[":
                dwell.dwell_s = max(0.2, round(dwell.dwell_s - 0.1, 2))
                axes["dwell_time"] = dwell.dwell_s
                save_axes(axes)
                notify(f"click faster — hold {dwell.dwell_s:.2f}s (saved)")
            if key == "]":
                dwell.dwell_s = min(2.0, round(dwell.dwell_s + 0.1, 2))
                axes["dwell_time"] = dwell.dwell_s
                save_axes(axes)
                notify(f"click slower — hold {dwell.dwell_s:.2f}s (saved)")
            if key == "s":
                snap_on = not snap_on
                notify(f"snap-to-button {'ON' if snap_on else 'OFF'}")
            if key == "g":
                gestures_on = not gestures_on
                notify(f"tilt gestures {'ON' if gestures_on else 'OFF'}")
            if key == "m":
                if click_mode == "confirm":
                    click_mode = "direct"
                elif overlay.available:
                    click_mode = "confirm"
                else:
                    notify("confirm mode unavailable (no window layer)")
                if confirm_active:
                    overlay.close()
                    confirm_active = False
                open_dwell.reset()
                dwell.reset()
                notify(f"click mode: {click_mode.upper()}")
            if key == "i":
                scroll_invert = not scroll_invert
                notify(f"scroll direction {'inverted' if scroll_invert else 'normal'}")
            if key == "p":
                notify(f"[diag] reading app='{tracker.app_name}'  "
                       f"targets={tracker.last_count}  "
                       f"clicking={'ON' if dwell.enabled else 'OFF'}  "
                       f"snap={'ON' if snap_on else 'OFF'}")
                if eased is not None:
                    near = sorted(tracker.snapshot(),
                                  key=lambda t: (t.cx - eased[0]) ** 2 + (t.cy - eased[1]) ** 2)
                    for t in near[:4]:
                        d = ((t.cx - eased[0]) ** 2 + (t.cy - eased[1]) ** 2) ** 0.5
                        notify(f"   {d:5.0f}px  {t.role:14s} '{t.label[:22]}' @({t.cx:.0f},{t.cy:.0f})")
            if key in ("-", "_"):
                s = mapper.set_scale(mapper.scale * 1.15)
                axes["range_scale"] = s
                save_axes(axes)
                notify(f"less sensitive — sweep ±{mapper.x_range_deg:.0f}° (saved)")
            if key in ("=", "+"):
                s = mapper.set_scale(mapper.scale * 0.87)
                axes["range_scale"] = s
                save_axes(axes)
                notify(f"more sensitive — sweep ±{mapper.x_range_deg:.0f}° (saved)")
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
                # Recovered from a motion-stream dropout — report how long it froze.
                if stall_active and last_imu_mono is not None:
                    froze_ms = (time.monotonic() - last_imu_mono) * 1000.0
                    notify(f"⚠ IMU stream resumed after {froze_ms:.0f} ms freeze "
                           f"(dropout #{imu_stalls}) — likely AirPods BLE/handoff")
                    stall_active = False
                last_imu_mono = time.monotonic()

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

                if key == "c" or pending_recenter:
                    pending_recenter = False
                    mapper.recenter(x_angle, y_angle)
                    tilt.set_baseline(roll_deg)
                    dwell.reset()
                    engaged = True
                    notify("recentered + ENGAGED — current pose is screen center")

                if engaged:
                    if gestures_on:
                        roll_delta_deg = tilt.delta_deg(roll_deg)
                        gesture = tilt.update(roll_deg, sample["t"])
                        if gesture == "left":
                            notify(f"clicking {'ENABLED' if dwell.toggle() else 'DISABLED'} (tilt)")
                        elif gesture == "right":
                            if not summoner.available:
                                notify("Claude summon needs the `claude` CLI (not found)")
                            elif summoner.busy():
                                notify("Claude is already thinking…")
                            else:
                                summoner.start()
                                cursor.play_click_sound()
                                notify("🧠 tilt-right — summoning Claude on your screen")
                    else:
                        roll_delta_deg = 0.0
                    # Tilt-freeze removed: the cursor never freezes from head tilt.
                    target = mapper.map(x_angle, y_angle)

            snap_label = None
            scrolling = False
            if engaged and target is not None and not debug_angles:
                if eased is None:
                    eased = target
                # Exponential ease toward the latest target: upsamples 25 Hz
                # IMU to RENDER_HZ so motion is continuous, not stepped.
                k = 1.0 - math.exp(-frame_dt / config.EASE_TIME_CONST_S)
                eased = (eased[0] + (target[0] - eased[0]) * k,
                         eased[1] + (target[1] - eased[1]) * k)

                # Cursor speed (smoothed) gates the magnet: fast = no snap.
                if prev_eased is not None:
                    inst = math.hypot(eased[0] - prev_eased[0],
                                      eased[1] - prev_eased[1]) / frame_dt
                    speed_ema = 0.35 * inst + 0.65 * speed_ema
                prev_eased = eased

                now = time.monotonic()

                if confirm_active:
                    # ---- CONFIRM PHASE: only the ✓/✕ panel is interactive ----
                    centers = (
                        ("click", panel["click_rect"][0] + panel["click_rect"][2] / 2,
                         panel["click_rect"][1] + panel["click_rect"][3] / 2),
                        ("cancel", panel["cancel_rect"][0] + panel["cancel_rect"][2] / 2,
                         panel["cancel_rect"][1] + panel["cancel_rect"][3] / 2),
                    )
                    best, bd = None, float("inf")
                    for name, cx, cy in centers:
                        d = math.hypot(cx - eased[0], cy - eased[1])
                        if d < bd:
                            best, bd = (cx, cy), d
                    render_pt = eased
                    if bd < config.SNAP_RADIUS_PX:
                        render_pt, _ = snap.snap_point(
                            eased, best, bd, config.SNAP_FULL_PX,
                            config.SNAP_RADIUS_PX, strength=1.0)
                    cursor.move(*render_pt)

                    region = confirm.region_at(panel, render_pt[0], render_pt[1])
                    if region != choose_region:
                        choose_region, choose_t = region, now
                    prog = min(1.0, (now - choose_t) / config.CONFIRM_CHOOSE_S) if region else 0.0
                    overlay.update(region, prog)

                    if region is not None and now - choose_t >= config.CONFIRM_CHOOSE_S:
                        overlay.close()
                        confirm_active = False
                        open_dwell.reset()
                        if region == "click" and confirm_target is not None:
                            cursor.move(*confirm_target)
                            cursor.click(*confirm_target)
                            if config.CLICK_SOUND:
                                cursor.play_click_sound()
                            dwell.clicks += 1
                            notify(f"✓ CLICK #{dwell.clicks} confirmed at "
                                   f"({confirm_target[0]:.0f}, {confirm_target[1]:.0f})")
                        else:
                            notify("✕ click cancelled")
                    elif now > confirm_deadline:
                        overlay.close()
                        confirm_active = False
                        open_dwell.reset()
                        notify("confirm panel timed out — cancelled")
                else:
                    # ---- NORMAL PHASE: snap to page targets, scroll, click ----
                    # Sticky magnet (velocity-gated): locks onto ONE target and
                    # holds it, so a dense field of buttons can't make the
                    # cursor flip between them and spasm.
                    render_pt = eased
                    snapped = False
                    if snap_on:
                        gain = snap.speed_gain(speed_ema, config.SNAP_SPEED_SLOW_PX_S,
                                               config.SNAP_SPEED_FAST_PX_S)
                        sx, sy, lbl = snap_ctrl.update(
                            tracker.snapshot(), eased[0], eased[1], gain)
                        render_pt = (sx, sy)
                        snap_label = lbl
                        snapped = lbl is not None

                    # Edge scroll. Engages when not locked to a target OR when
                    # the head is pushed PAST the edge (clamped) — so you can
                    # always scroll up by pushing up, even past a toolbar, while
                    # merely resting on a top button still clicks it.
                    if scroll_enabled and (not snapped or mapper.last_clamped):
                        sdir, sdepth = scroll.scroll_zone(
                            eased[1], screen_h, config.SCROLL_BAND_PX)
                        if sdir != 0:
                            if scroll_arm_t is None:
                                scroll_arm_t = now
                            elif now - scroll_arm_t >= config.SCROLL_ARM_S:
                                scrolling = True
                                render_pt = eased       # don't stick to a target
                                snap_label = None
                                vel = scroll.scroll_velocity(
                                    sdir, sdepth, scroll_speed)
                                scroll_accum += (-vel if scroll_invert else vel) * frame_dt
                                step = int(scroll_accum)
                                if step != 0:
                                    scroll_accum -= step
                                    cursor.scroll(step)
                        else:
                            scroll_arm_t = None
                            scroll_accum = 0.0
                    else:
                        scroll_arm_t = None
                        scroll_accum = 0.0

                    cursor.move(*render_pt)

                    # Click / open-confirm. Allowed when not scrolling and not
                    # pinned to an empty edge (so corners don't auto-fire). A
                    # snapped target overrides the clamp guard.
                    if (dwell.enabled and not scrolling
                            and (snapped or not mapper.last_clamped)):
                        if click_mode == "direct":
                            fire = dwell.update(render_pt[0], render_pt[1], now)
                            if fire is not None:
                                cursor.click(*fire)
                                if config.CLICK_SOUND:
                                    cursor.play_click_sound()
                                tag = f" → {snap_label}" if snap_label else ""
                                notify(f"CLICK #{dwell.clicks} at "
                                       f"({fire[0]:.0f}, {fire[1]:.0f}){tag}")
                        else:
                            # Confirm mode: opens on ANY dwell, so even buttons
                            # snap doesn't recognize (Dock/app icons) get a panel.
                            fire = open_dwell.update(render_pt[0], render_pt[1], now)
                            if fire is not None:
                                confirm_target = (render_pt[0], render_pt[1])
                                panel = confirm.confirm_layout(
                                    confirm_target[0], confirm_target[1],
                                    screen_w, screen_h)
                                overlay.open(panel)
                                confirm_active = True
                                choose_region, choose_t = None, now
                                confirm_deadline = now + config.CONFIRM_TIMEOUT_S
                                open_dwell.reset()
                                notify("panel: glide to ✓ Click or ✕ Cancel")

            now_mono = time.monotonic()

            # Claude summon panel — show on state change, keep pumped while up,
            # auto-dismiss the answer after a while.
            s_state, s_text = summoner.snapshot()
            if s_state != "idle":
                if not summon_visible or s_state != summon_last_state:
                    title = {"thinking": "🧠 Claude — looking…",
                             "done": "🧠 Claude",
                             "error": "⚠ Claude"}.get(s_state, "🧠 Claude")
                    summon_overlay.show(s_text, title, screen_w, screen_h)
                    summon_visible = True
                    if s_state != "thinking":
                        summon_shown_t = now_mono
                summon_last_state = s_state
                summon_overlay.pump()
                if (s_state in ("done", "error")
                        and now_mono - summon_shown_t > config.SUMMON_DISMISS_S):
                    summon_overlay.hide()
                    summoner.dismiss()
                    summon_visible = False
                    summon_last_state = None
            elif summon_visible:
                summon_overlay.hide()
                summon_visible = False
                summon_last_state = None

            # Detect the onset of a motion-stream dropout (cursor freeze).
            imu_age_ms = ((now_mono - last_imu_mono) * 1000.0
                          if last_imu_mono is not None else 0.0)
            if (last_imu_mono is not None and not stall_active
                    and imu_age_ms > config.IMU_STALL_S * 1000.0):
                stall_active = True
                imu_stalls += 1

            if latencies and now_mono - last_hud > 1.0 / config.HUD_UPDATE_HZ:
                last_hud = now_mono
                avg = statistics.fmean(latencies)
                p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1]
                if stall_active:
                    state = f"⚠ NO IMU {imu_age_ms:.0f}ms (AirPods?)"
                elif not engaged:
                    state = "OFF — press [c] at screen center"
                elif confirm_active:
                    state = "CONFIRM: glide ✓/✕"
                elif not dwell.enabled:
                    state = "click:OFF"
                elif click_mode == "confirm":
                    pct = open_dwell.progress(now_mono)
                    state = f"hover→panel:{'▆' * int(pct * 5):<5}" if pct > 0 else "confirm:armed"
                else:
                    pct = dwell.progress(now_mono)
                    state = f"click:{'▆' * int(pct * 5):<5}" if pct > 0 else "click:armed"
                pos = f"({eased[0]:4.0f},{eased[1]:4.0f})" if eased else "(waiting)"
                if scrolling:
                    snap_txt = "⇅ scrolling"
                elif not snap_on:
                    snap_txt = "snap:off"
                elif snap_label:
                    snap_txt = f"🧲 {snap_label[:18]}"
                else:
                    snap_txt = f"snap:{tracker.last_count}·{tracker.app_name[:8]}"
                sys.stdout.write(
                    f"\rIMU {len(imu_times):3d} Hz | lat {avg:4.1f}/{p95:4.1f} ms "
                    f"| {pos} | {state} | {snap_txt} | clicks {dwell.clicks} "
                    f"| freezes {imu_stalls}  ")
                sys.stdout.flush()

            sleep_left = frame_dt - (time.monotonic() - frame_start)
            if sleep_left > 0:
                time.sleep(sleep_left)

    tracker.stop()
    overlay.close()
    summon_overlay.hide()
    print("\nengine: stopped")


if __name__ == "__main__":
    if "--calibrate" in sys.argv:
        run_calibration()
    else:
        run(debug_angles="--debug-angles" in sys.argv)
