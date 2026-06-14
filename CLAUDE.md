# CLAUDE.md — Spatial Telekinesis Engine

Hands-free macOS control using **only AirPods 4** — no camera, no computer
vision, ever. Head pose drives the cursor; dwell clicks; head-tilt gestures
trigger actions. Owner: Devansh (reviewer). Claude writes the code.

## Prime directive

Every session must move toward a low-latency hands-free daemon with a
**zero false-positive click rate**. If a session drifts, surface the two
numbers that matter: end-to-end latency (ms) and false-positive click count.
Both are instrumented in the engine HUD — keep them visible and honest.

## Hard constraints (owner decisions — do not relitigate)

- **Pure AirPods.** No webcam, no MediaPipe/OpenCV, no face tracking. The
  pitch is "control from hardware everyone already owns."
- **Movement must look natural.** No exaggerated head gestures. The one
  sanctioned theatrical gesture: tilt-right "huh?" summons the Claude agent.
- **Demo target:** ~60-second kinetic demo. Drift mitigations only need to
  survive that window (recenter key exists for resets).
- **Commits:** do NOT add Claude attribution (no Co-Authored-By lines).

## Architecture

```
AirPods 4 ──CoreMotion──► bridge (Swift) ──UDP 8077 JSON──► engine (Python)
                                                              quat → Y-X-Z Euler
                                                              One Euro filter
                                                              absolute map + ease
                                                              dwell/tilt FSMs
                                                              Quartz CGEvent out
```

- `bridge/` — Swift CLI, deliberately math-free (ships raw quaternions +
  timestamps). All geometry lives in the engine where it's unit-testable.
- `engine/` — flat Python modules: `pose.py` (math), `filters.py` (One Euro),
  `mapping.py` (absolute map), `dwell.py` + `gestures.py` (click FSMs),
  `cursor.py` (Quartz), `calibrate.py` (axis wizard), `main.py` (loop + HUD),
  `config.py` (every tunable, commented).
- Launchers at repo root: `run_bridge.sh`, `run_engine.sh [--calibrate|--debug-angles]`.

## Hard-won platform lessons (violate these and it breaks)

1. **TCC/motion:** macOS 26 SIGABRTs any process touching CMHeadphoneMotionManager
   unless it is a real `.app` bundle **launched via `open`/launchd**. Embedded
   Info.plist in a bare CLI binary is ignored; direct-exec of the bundled
   binary gets blamed on the hosting terminal (VS Code) and killed. Hence
   `bridge/package_app.sh` + `open` in `run_bridge.sh`. Don't "simplify" this.
2. **Axis layout is never assumed.** AirPods' channel-to-motion mapping did
   not match either frame convention we derived on paper. The calibration
   wizard (`--calibrate` → `engine/axes.json`, gitignored, per-user) measures
   it empirically. The engine refuses to start without axes.json. Keep it
   that way.
3. **Safety invariants** (born from a runaway-cursor incident — the user
   could not control their own mouse):
   - engine starts inert; no cursor output until the user presses `c`
   - clicking starts OFF every launch; `d` or tilt-left enables
   - spacebar = instant panic freeze; keyboard must always win
   - no dwell-click while edge-clamped (corners are "parked" by definition)
     or while tilted (gesture cross-coupling)
   - emergency kill: `pkill -f main.py; pkill -f TelekinesisBridge`
4. **Latency clock:** bridge timestamps use the mach uptime base; engine
   compares against `CLOCK_UPTIME_RAW`. Don't switch either side to wall time.
5. **UDP receiver drains to newest packet** — processing backlog replays
   stale head positions. Keep the drain.

## Working style (owner preferences)

- Bullet points, no info dumps; warn before unavoidable long output.
- Owner reviews; Claude writes code and runs the math/unit checks before
  handing anything over (`engine/.venv/bin/python` for tests; pure-math
  modules have no pyobjc dependency).
- Tuning requests come as feel descriptions ("too fast", "can't hold it").
  Map them to `config.py` knobs and explain the change in one line.

## Magnetic snap (the precision fix — NOT computer vision)

`targets.py` reads clickable elements (buttons/links/window controls) straight
from the **macOS Accessibility tree** of the **window under the cursor**, in a
daemon thread, refreshed ~5 Hz. (It must NOT scan the keyboard-focused app:
that's the terminal running the engine, not the app the head-cursor points at
— this was the original "snap isn't working" bug. Uses system-wide
element-at-position → enclosing window.) `p` key dumps the live app/targets it
sees; HUD shows `snap:N·AppName`. `snap.py` (pure, unit-tested) pulls the head-driven
cursor onto the nearest element within `SNAP_RADIUS_PX`, fully sticking within
`SNAP_FULL_PX`. The dwell anchors at the *snapped* point, so clicks land
dead-center. **Velocity gate** (`speed_gain`): the magnet strength scales with
cursor speed — full when settling (≤`SNAP_SPEED_SLOW_PX_S`), off while
traversing (≥`SNAP_SPEED_FAST_PX_S`). This is what stops "snaps onto every
button I pass." Keep the radius modest (~70px); big radius + always-on = the
over-reactive failure mode. This is the cure for "near the button but never spot-on" and
stays inside the no-CV constraint — it's the OS's own UI map, no pixels.
Toggle live with `s`. Same Accessibility permission the cursor already needs;
an AX hiccup degrades to "no targets", never crashes.

## Runtime axis fixes

Up/down (and left/right) sign has been flaky across sessions (the calibration
sign inference isn't fully trustworthy). Fix: live keys `v` (invert up/down)
and `b` (invert left/right) flip the sign AND persist to `axes.json`
immediately, so the owner is self-sufficient and we stop flip-flopping it by
hand. If axes feel deeply wrong, re-run `--calibrate`.

## Edge-dwell scroll

`scroll.py` (pure, unit-tested): rest the cursor in the top/bottom
`SCROLL_BAND_PX` zone → content scrolls that way, speed = depth^gamma ramp
(gentle near inner edge). No mode, no gesture — chosen over a gesture-toggle
scroll mode because it's the most natural/hands-free. Priority rule in the
loop: a clickable snap target under the cursor wins (so edge toolbars stay
clickable); only empty edges scroll. `SCROLL_ARM_S` delay stops pass-through
scrolling; suppresses dwell-click while scrolling. `cursor.scroll()` posts
pixel-unit wheel events; `i` flips direction live (for natural-scroll setting).

## State (update when milestones move)

- **M1 ✓** head→cursor. **M2 ✓** dwell-click + tilt gestures. **Magnetic
  snap ✓** + **edge-scroll ✓** built + unit-tested, awaiting owner live-test
  (2026-06-14).
- Current keys: `c` engage/recenter · `SPACE` panic · `d` clicking · `s` snap
  · `i` flip scroll dir · `v` invert ↕ · `b` invert ↔ · `q` quit.
- **M3 (next):** tilt-right → screenshot → Claude agent reads the screen and
  acts. Currently a stub notify in `main.py`.
- Known open items: live-validate snap feel + false-positive rate with snap on;
  M3 agent design (screenshot capture, Claude API call, action execution,
  permission story).
