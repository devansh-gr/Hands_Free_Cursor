# Spatial Telekinesis Engine

Hands-free OS control from nothing but AirPods 4 — no camera, no computer
vision. Head pitch/yaw drives the cursor (±4° sweep ≈ a natural glance);
parking the cursor clicks (dwell); a head-tilt-right ("huh?") summons a
screen-aware Claude agent; tilt-left toggles clicking on/off.

## Architecture

```
AirPods 4 ──CoreMotion──► bridge (Swift) ──UDP 8077──► engine (Python)
                                                          │  quat→Euler
                                                          │  One Euro filter
                                                          │  absolute map
                                                          │  dwell + tilt FSMs
                                                          ▼
                                              Quartz CGEvent (cursor/clicks)
```

- `bridge/` — Swift CLI. Streams raw attitude quaternions as JSON over UDP.
  Deliberately math-free; all geometry lives in the engine.
- `engine/` — Python. Receives IMU, does the transforms, posts HID events,
  renders a live HUD with latency (avg/p95 ms) and IMU rate.

## Milestones

- **M1 ✓** — head → cursor, absolute mapping + `c` recenter, latency HUD
- **M2 ✓** — dwell-to-click (camera-free pivot), tilt-left click toggle,
  tilt-right summon stub, click counter in HUD
- **M3** — right head-tilt ("huh?") → screenshot → Claude acts on screen

## Run (two terminals)

```sh
# terminal 1 — the IMU bridge (AirPods must be in-ear)
# NOTE: must run as the packaged .app — macOS 26 TCC SIGABRTs a bare CLI
# binary that touches CoreMotion, even with an embedded Info.plist.
cd bridge && ./package_app.sh
./.build/TelekinesisBridge.app/Contents/MacOS/bridge

# terminal 2 — the engine
cd engine && .venv/bin/python main.py
```

First run only:
1. macOS will prompt for **Motion** permission (the bridge) — allow it.
2. Grant your terminal **Accessibility** permission
   (System Settings → Privacy & Security → Accessibility), or cursor events
   are silently dropped. The engine warns if this is missing.
3. Run the guided axis calibration once (~20s): `./run_engine.sh --calibrate`.
   It measures which angle channel responds to look-right / look-up /
   tilt-right on *your* head and writes `engine/axes.json`. The engine
   refuses to start without it. Re-run any time it feels wrong.

Keys while running: `c` = recenter+engage (look at screen center first),
`space` = panic freeze, `d` = clicking on/off, `q` = quit. The engine starts
inert: no cursor motion until `c`, no clicking until `d`.

## Web control panel

When the engine starts it also serves a local control panel and opens it in
your browser at **http://127.0.0.1:8765/**. From the page you can see AirPods
connection status + live telemetry (IMU Hz, latency, clicks), run the guided
axis calibration, press Start/Stop, and tune sensitivity / hold-time / scroll
speed / feature toggles — all live. Note: the browser can't read AirPods motion
or move the cursor itself (sandbox), so the page is a front-end to the local
engine, which must be running. Terminal keys keep working alongside it.

## Tuning

Everything adjustable is in `engine/config.py`: sweep ranges (sensitivity),
One Euro filter (jitter vs. lag), render rate, easing time constant.
