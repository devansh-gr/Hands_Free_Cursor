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
sees; HUD shows `snap:N·AppName`.

Recognition robustness (Chrome new-tab was being missed): clickability is
decided by the **AXPress action**, not just a role whitelist; traversal is
**breadth-first** so shallow window chrome is found before a deep web page
exhausts the budget (DFS dove into web content and never reached the toolbar);
and the **element under the cursor is always added** (climb to pressable
ancestor) so the pointed-at thing is lockable even if the bounded walk missed
it. Budget: 1500 elems / 8000 nodes / 0.5 s.

**`SnapController` (sticky, 2026-06-15)** is the live path: once locked onto a
target it HOLDS it until the head leaves the release radius (acquire×1.4) or a
different target becomes decisively closer (<55% of the locked distance). This
fixed the "spasming / snaps onto everything" regression — without stickiness,
the per-frame nearest flips between adjacent targets in a dense field. The
AXPress + breadth-first + big-budget change had flooded the target set; budget
pulled back (600 elems / 4000 nodes) and acquire radius tightened to 55px.
`snap.py` also has standalone `nearest`/`snap_point` (still used for the
2-button confirm panel) and `speed_gain` (velocity gate feeds the controller).
The older non-sticky pull: The dwell anchors at the *snapped* point, so clicks land
dead-center. Snap ignores targets taller than `SNAP_MAX_TARGET_H` (~64px) so
big thumbnails/cards (YouTube) don't magnet the cursor; real controls are
short. Top-edge buttons (Chrome new-tab/close): the edge-clamp dwell guard
blocks clicks at a clamped screen edge (anti corner-click-machine), BUT a
snapped target is a real button, so clicks are allowed when locked onto one
even at the clamp (`tgt is not None or not mapper.last_clamped`). **Velocity gate** (`speed_gain`): the magnet strength scales with
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
loop: scroll engages when there's no snap target OR when the head is pushed
PAST the edge (`mapper.last_clamped`). So resting on a top toolbar button
clicks it, but pushing further up scrolls up past the toolbar — this fixed
"scrolling up is a pain." `SCROLL_ARM_S` delay stops pass-through scrolling;
dwell-click suppressed while scrolling. `cursor.scroll()` posts
pixel-unit wheel events; `i` flips direction live (for natural-scroll setting).

## "Random freeze" — diagnosed 2026-06-14

It was the **tilt-freeze**, not AirPods. The cursor froze while head-roll
exceeded the threshold (so it couldn't drag during a gesture); for this user
"look up" cross-couples into the tilt channel, so it froze exactly when trying
to go up. **Tilt-freeze REMOVED entirely** (owner request) — the cursor never
freezes from tilt now. Tilt gestures default OFF (`gestures_on=False`), enable
with `g` only when M3's Claude-summon needs them (and even then, no freeze).
Separately, IMU-stall instrumentation exists (`freezes N` counter + `⚠ NO IMU`
HUD state + a "resumed after X ms" notify) for real AirPods motion dropouts —
distinct from the (now-removed) tilt-freeze.

## Confirm-click (default click mode)

`confirm.py` — hold the cursor still for `CONFIRM_OPEN_S` (~1.2s) → a floating
Cocoa panel pops up with **✓ Click** / **✕ Cancel**; glide onto a choice and
dwell `CONFIRM_CHOOSE_S` (~0.6s) to select. Opens on ANY dwell (not just
recognized snap targets) so unrecognized buttons / Dock+app icons still work —
the click target is the snapped center if snapped, else the cursor position.
Panel is a dark rounded card with two pill buttons + a sweep progress fill. ✓ performs the real click at the
saved target; ✕ / timeout cancels. Eliminates accidental clicks. The panel is
a borderless floating NSWindow (level 1000, ignores mouse) created lazily and
pumped via the run loop each frame; geometry (`confirm_layout`, `region_at`)
is pure/unit-tested. During the confirm phase the cursor snaps to the two
panel buttons only. Falls back to "direct" mode if the window layer is
unavailable. `m` toggles confirm/direct; `d` still gates all clicking.
A separate `open_dwell` times the panel-open so it's independent of direct
mode's `dwell`.

## KNOWN ISSUE — dense top-left button cluster (owner is designing a fix)

In the top-left of the screen (macOS menu/app controls, window traffic lights,
toolbars) there are SO many clickable AX targets packed together that snapping
is annoying — the magnet jumps between adjacent buttons. Do NOT fix this yet;
the owner wants to design the solution himself. Ideas parked for later:
per-region snap cooldown, a "snap to the target you're moving toward" velocity
heuristic, temporarily widening SNAP_FULL only for isolated targets, or a
density check that weakens the magnet where targets are clustered.

## Web control panel (`server.py` + `web/index.html`)

HARD BROWSER LIMITS (do not try to "move this fully into the browser"): a web
page CANNOT read AirPods motion (no CoreMotion/Web-Bluetooth path) and CANNOT
move the macOS cursor (sandbox). So the website is a **front-end to the local
engine**, not a standalone app. `server.py` is a stdlib-only (no pip deps)
`ThreadingHTTPServer` that serves the page, streams telemetry over **SSE**
(`GET /events`), and takes commands over **POST `/cmd`**. The engine main loop
`control.drain()`s commands each frame and `control.set_telemetry()`s at HUD
rate. Engine auto-opens `http://127.0.0.1:8765/` and keeps terminal keys
working too (dual control). Connection resets from the browser are silenced in
`_QuietServer.handle_error`.

Web also does first-run **axis calibration** (capture center/right/up/tilt →
`compute_axes` in calibrate.py → axes.json), so the engine no longer hard-exits
when axes.json is missing — it starts uncalibrated with `DEFAULT_AXES`, and
engage is gated on `calibrated`. Runtime-settable from the panel: engage/stop,
clicking, snap, scroll on/off + direction, gestures, confirm/direct mode,
invert X/Y, sensitivity (mapper scale), hold time, scroll speed.

## M3 — Claude summon (tilt-right "huh?")  ✓ built 2026-06-15

`summon.py`: tilt head right past the gesture threshold → `screencapture -x`
→ the local **`claude` CLI** (`claude -p ... --allowedTools Read --model
claude-opus-4-8`) reads the shot and answers → answer shows in a floating
Cocoa panel (`TextOverlay`). Uses the user's existing Claude Code auth — **no
API key needed** (none was set; `anthropic` SDK isn't installed). Runs in a
daemon thread (`Summoner`) so the 120 Hz loop never blocks; main loop polls
`snapshot()` and renders. ~18s latency (image analysis); "looking…" panel
covers the wait. NEEDS macOS **Screen Recording** permission for the engine's
host (VS Code/terminal) — first summon prompts; errors degrade to a panel
message, never a crash. Gestures are ON by default now (no freeze exists, so
tilt is safe). `g` still toggles them. To speed up / change behavior: `MODEL`
and `DEFAULT_PROMPT` in summon.py.

NOTE: this is "Claude reads the screen and answers", not yet "Claude acts on
the screen" (autonomous clicking/typing). Acting would be a computer-use loop —
deferred. The CLI already has tools, so a future version could allow-list more
than Read to let it act.

## Clicking reliability (the "panel never shows up" fix, 2026-06-15)

Dwell was failing because the radius (45px) + open time (1.2s) were too tight
for head jitter — the timer kept resetting, so the confirm panel almost never
opened. Now: `DWELL_RADIUS_PX=80`, `DWELL_REARM_RADIUS_PX=130`,
`CONFIRM_OPEN_S=0.7`. Also clicking now defaults **ON in confirm mode**
(`dwell.enabled = (click_mode == "confirm")`) — safe because nothing fires
without the ✓ confirm. Confirm opens on ANY dwell (see confirm section), so it
works on app/Dock buttons snap doesn't recognize.

## State (update when milestones move)

- **M1 ✓** head→cursor. **M2 ✓** dwell-click + tilt gestures. **Magnetic
  snap ✓** + **edge-scroll ✓** built + unit-tested, awaiting owner live-test
  (2026-06-14).
- Current keys: `c` engage/recenter · `SPACE` panic · `d` clicking · `s` snap
  · `i` flip scroll dir · `v` invert ↕ · `b` invert ↔ · `q` quit.
- **M3 ✓** tilt-right → screenshot → `claude` CLI reads screen → answer panel
  (summon.py). Built + verified end-to-end (~18s). "Reads + answers", not yet
  "acts".
- Known open items: live-validate snap feel + false-positive rate; summon
  latency (~18s — could try haiku or a real API key for speed); optional
  "Claude acts" computer-use upgrade; the parked top-left-cluster snap issue.
