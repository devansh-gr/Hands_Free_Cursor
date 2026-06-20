"""Tuning constants for the telekinesis engine. Everything reviewable lives here."""

# --- transport ---
UDP_HOST = "127.0.0.1"
UDP_PORT = 8077

# --- axis assignment ---
# Never assumed: measured per-user by `run_engine.sh --calibrate`, which
# writes axes.json (which angle channel drives cursor X/Y/gestures + signs).
# The engine refuses to start without it.

# --- engage ---
# Auto-engage cursor control once IMU data flows (no need to press [c]). It
# waits AUTO_ENGAGE_WARMUP_S after the first sample before capturing center —
# the AirPods motion fusion needs a moment to settle, and capturing the origin
# too early makes the cursor drift off toward a corner. [c] re-centers anytime.
AUTO_ENGAGE = True
AUTO_ENGAGE_WARMUP_S = 1.5

# --- absolute mapping ---
# Head sweep (degrees from center) that spans the full screen. Smaller = MORE
# sensitive (less head travel per pixel). Magnetic snap covers fine precision,
# so this can be sensitive. Live-tunable at runtime with [-]/[=]; the chosen
# multiplier persists to axes.json (range_scale).
X_RANGE_DEG = 12.0
Y_RANGE_DEG = 9.0

# --- magnetic targeting (snap-to-button) ---
# Reads real clickable elements from the macOS Accessibility tree (NOT vision)
# and pulls the cursor onto the nearest one — fixes "near but never spot-on".
SNAP_ENABLED = True
SNAP_RADIUS_PX = 55.0        # must be THIS close to acquire a target (smaller =
                             # less grabby; the sticky controller then holds it)
SNAP_FULL_PX = 30.0          # within this, cursor fully sticks to target center
# Don't snap to BIG targets — video thumbnails/cards are tall links and would
# magnet the cursor all over content pages (e.g. YouTube). Real controls
# (buttons, tabs, toolbar items, text links) are short.
SNAP_MAX_TARGET_H = 64.0
# Velocity gate — the magnet only engages as you SLOW to land, so sweeping
# across the screen doesn't get yanked onto every button it passes.
SNAP_SPEED_SLOW_PX_S = 150.0  # at/below this cursor speed: full magnet
SNAP_SPEED_FAST_PX_S = 650.0  # at/above this cursor speed: magnet off
TARGET_REFRESH_HZ = 5.0      # how often the background thread re-scans the UI
TARGET_WALK_TIMEOUT_S = 0.5   # bail out of a slow AX-tree walk (e.g. huge pages)
TARGET_MAX_ELEMENTS = 600    # cap elements per scan (fewer = less magnet noise)

# --- edge-dwell scroll ---
SCROLL_ENABLED = True
SCROLL_BAND_PX = 95.0        # thickness of the top/bottom edge zones
SCROLL_MAX_SPEED = 1700.0    # pixels/sec at the very edge of the screen
SCROLL_ARM_S = 0.18          # must linger in the band this long before scrolling
                             # (so passing through the edge doesn't scroll)
SCROLL_INVERT = False        # flip with [i] live if direction feels backwards

# --- dwell click ---
# Radius is GENEROUS on purpose: head control jitters/drifts, so a tight circle
# means the dwell timer keeps resetting and never fires (the "panel never shows
# up" bug). 80px tolerates natural wobble while you settle.
DWELL_RADIUS_PX = 80.0        # cursor must stay inside this circle...
DWELL_TIME_S = 0.5            # ...for this long => one click (live-tune [ ])
DWELL_REARM_RADIUS_PX = 130.0  # must exit this larger circle to arm the next click
CLICK_SOUND = True            # audible tick on click (demo feedback)

# --- click mode ---
# "confirm": hover a button -> a ✓Click/✕Cancel panel pops up; glide onto a
#            choice to select it (no accidental clicks). "direct": dwell clicks.
# Toggle live with [m].
CLICK_MODE = "confirm"
CONFIRM_OPEN_S = 0.7          # hover a button this long to OPEN the panel
CONFIRM_CHOOSE_S = 0.55       # dwell on ✓/✕ this long to SELECT it
CONFIRM_TIMEOUT_S = 6.0       # auto-cancel if no choice is made

# --- tilt gestures (the cursor never freezes from tilt) ---
TILT_THRESHOLD_DEG = 22.0     # sustained tilt past this = gesture (deliberate)
TILT_HOLD_S = 0.25            # must hold the tilt this long (rejects head bobbles)
SUMMON_DISMISS_S = 18.0       # how long Claude's answer panel stays before auto-hide

# --- One Euro filter (Casiez et al. 2012) ---
# min_cutoff fights jitter at rest; beta fights lag during fast moves.
FILTER_MIN_CUTOFF = 0.5
FILTER_BETA = 0.02
FILTER_D_CUTOFF = 1.0

# --- render loop ---
# IMU arrives at ~25 Hz; we render the cursor at a higher rate and ease toward
# the latest filtered target so motion looks continuous, not stepped.
RENDER_HZ = 120.0
EASE_TIME_CONST_S = 0.08  # exponential approach; smaller = snappier, more steppy

# --- HUD ---
HUD_UPDATE_HZ = 5.0
LATENCY_WINDOW = 100  # samples for avg/p95 stats

# --- freeze detection ---
# The cursor only moves on fresh IMU samples (~25-32 Hz, i.e. one every
# ~35 ms). A gap beyond this means the AirPods motion stream dropped out.
IMU_STALL_S = 0.2
