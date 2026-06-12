"""Tuning constants for the telekinesis engine. Everything reviewable lives here."""

# --- transport ---
UDP_HOST = "127.0.0.1"
UDP_PORT = 8077

# --- axis assignment ---
# Never assumed: measured per-user by `run_engine.sh --calibrate`, which
# writes axes.json (which angle channel drives cursor X/Y/gestures + signs).
# The engine refuses to start without it.

# --- absolute mapping ---
# Head sweep (degrees from center) that spans the full screen. Smaller = more
# sensitive but amplifies IMU drift/jitter. Start moderate; tighten toward
# ±4° (the "invisible glance" target) only once control is stable.
X_RANGE_DEG = 16.0
Y_RANGE_DEG = 12.0

# --- dwell click ---
DWELL_RADIUS_PX = 45.0        # cursor must stay inside this circle...
DWELL_TIME_S = 0.8            # ...for this long => one click at the anchor
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
