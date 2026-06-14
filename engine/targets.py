"""Clickable-target discovery via the macOS Accessibility tree.

This is the OS's own structured map of the UI — buttons, links, window
controls — read straight from the frontmost app. NOT computer vision: no
pixels, no camera, no ML. Same Accessibility permission the cursor already
needs. A background thread re-scans periodically so the hot render loop only
ever reads a cached snapshot.
"""

import threading
import time

from AppKit import NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCopyAttributeValue,
    AXValueGetValue,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXChildrenAttribute,
    kAXRoleAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    kAXTitleAttribute,
)

# Roles worth snapping to: things you actually click. Deliberately excludes
# containers, static text, and images to avoid magnet noise.
CLICKABLE_ROLES = {
    "AXButton", "AXLink", "AXMenuButton", "AXPopUpButton", "AXCheckBox",
    "AXRadioButton", "AXDisclosureTriangle", "AXCloseButton",
    "AXMinimizeButton", "AXZoomButton", "AXToolbarButton", "AXSegment",
    "AXStepper", "AXIncrementor", "AXSwitch",
}

_MAX_DEPTH = 70


class Target:
    __slots__ = ("cx", "cy", "role", "label")

    def __init__(self, cx: float, cy: float, role: str, label: str) -> None:
        self.cx, self.cy, self.role, self.label = cx, cy, role, label


def _attr(elem, name):
    err, val = AXUIElementCopyAttributeValue(elem, name, None)
    return val if err == 0 else None


def _rect(elem):
    pos = _attr(elem, kAXPositionAttribute)
    size = _attr(elem, kAXSizeAttribute)
    if pos is None or size is None:
        return None
    okp, point = AXValueGetValue(pos, kAXValueCGPointType, None)
    oks, dim = AXValueGetValue(size, kAXValueCGSizeType, None)
    if not (okp and oks):
        return None
    return float(point.x), float(point.y), float(dim.width), float(dim.height)


def _walk(elem, out, deadline, max_elems, max_area, depth=0):
    if depth > _MAX_DEPTH or len(out) >= max_elems or time.monotonic() > deadline:
        return
    role = _attr(elem, kAXRoleAttribute)
    if role in CLICKABLE_ROLES:
        r = _rect(elem)
        if r is not None:
            x, y, w, h = r
            # Skip zero/sub-pixel and whole-pane "clickable" containers that
            # would otherwise swallow the whole screen as one magnet.
            if 6.0 < w and 6.0 < h and (w * h) < max_area:
                label = _attr(elem, kAXTitleAttribute) or role
                out.append(Target(x + w / 2.0, y + h / 2.0, role, str(label)))
    for child in _attr(elem, kAXChildrenAttribute) or ():
        if len(out) >= max_elems or time.monotonic() > deadline:
            break
        _walk(child, out, deadline, max_elems, max_area, depth + 1)


def scan_frontmost(max_elems: int, timeout_s: float, max_area: float):
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return []
    axapp = AXUIElementCreateApplication(app.processIdentifier())
    out: list[Target] = []
    _walk(axapp, out, time.monotonic() + timeout_s, max_elems, max_area)
    return out


class TargetTracker(threading.Thread):
    """Background AX scanner. snapshot() is the only thing the render loop calls."""

    def __init__(self, refresh_hz: float, max_elems: int, timeout_s: float,
                 screen_area: float) -> None:
        super().__init__(daemon=True)
        self._period = 1.0 / refresh_hz
        self._max = max_elems
        self._timeout = timeout_s
        self._max_area = screen_area * 0.5  # nothing bigger than half the screen
        self._lock = threading.Lock()
        self._targets: list[Target] = []
        self._stop = threading.Event()
        self.last_count = 0

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                snap = scan_frontmost(self._max, self._timeout, self._max_area)
            except Exception:
                snap = []  # never let an AX hiccup kill the engine
            with self._lock:
                self._targets = snap
                self.last_count = len(snap)
            self._stop.wait(self._period)

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> list[Target]:
        with self._lock:
            return self._targets
