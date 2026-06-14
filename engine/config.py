"""Tuning constants for the telekinesis engine. Everything reviewable lives here."""

# --- transport ---
UDP_HOST = "127.0.0.1"
UDP_PORT = 8077

# --- axis assignment ---
# Never assumed: measured per-user by `run_engine.sh --calibrate`, which
# writes axes.json (which angle channel drives cursor X/Y/gestures + signs).
# The engine refuses to start without it.

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
SNAP_RADIUS_PX = 70.0        # within this of a target, the cursor gets pulled in
SNAP_FULL_PX = 24.0          # within this, cursor fully sticks to target center
# Velocity gate — the magnet only engages as you SLOW to land, so sweeping
# across the screen doesn't get yanked onto every button it passes.
SNAP_SPEED_SLOW_PX_S = 150.0  # at/below this cursor speed: full magnet
SNAP_SPEED_FAST_PX_S = 650.0  # at/above this cursor speed: magnet off
TARGET_REFRESH_HZ = 5.0      # how often the background thread re-scans the UI
TARGET_WALK_TIMEOUT_S = 0.35  # bail out of a slow AX-tree walk (e.g. huge pages)
TARGET_MAX_ELEMENTS = 500    # safety cap on elements collected per scan

# --- edge-dwell scroll ---
SCROLL_ENABLED = True
SCROLL_BAND_PX = 95.0        # thickness of the top/bottom edge zones
SCROLL_MAX_SPEED = 1700.0    # pixels/sec at the very edge of the screen
SCROLL_ARM_S = 0.18          # must linger in the band this long before scrolling
                             # (so passing through the edge doesn't scroll)
SCROLL_INVERT = False        # flip with [i] live if direction feels backwards

# --- dwell click ---
DWELL_RADIUS_PX = 45.0        # cursor must stay inside this circle...
DWELL_TIME_S = 0.5            # ...for this long => one click (live-tune [ ])
DWELL_REARM_RADIUS_PX = 70.0  # must exit this larger circle to arm the next click
CLICK_SOUND = True            # audible tick on click (demo feedback)

# --- tilt gestures ---
TILT_THRESHOLD_DEG = 14.0     # sustained tilt past this = gesture
TILT_HOLD_S = 0.25            # must hold the tilt this long (rejects head bobbles)
CURSOR_FREEZE_ROLL_DEG = 8.0  # cursor + dwell freeze while tilted past this,
                              # so gestures can't drag the cursor or fire clicks

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
