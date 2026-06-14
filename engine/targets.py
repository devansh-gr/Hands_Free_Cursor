"""Clickable-target discovery via the macOS Accessibility tree.

This is the OS's own structured map of the UI — buttons, links, window
controls — read straight from the app. NOT computer vision: no pixels, no
camera, no ML. Same Accessibility permission the cursor already needs.

Scans the WINDOW UNDER THE CURSOR (via the system-wide element-at-position
API), not the keyboard-focused app — because the focused app is usually the
terminal running the engine, not the app the head-cursor is pointing at. A
background thread re-scans periodically so the hot render loop only ever reads
a cached snapshot.
"""

import threading
import time

import Quartz
from AppKit import NSRunningApplication, NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    AXUIElementCopyElementAtPosition,
    AXUIElementCopyAttributeValue,
    AXUIElementGetPid,
    AXValueGetValue,
    kAXValueCGPointType,
    kAXValueCGSizeType,
    kAXChildrenAttribute,
    kAXRoleAttribute,
    kAXParentAttribute,
    kAXWindowAttribute,
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
    "AXStepper", "AXIncrementor", "AXSwitch", "AXTabButton",
}

_MAX_DEPTH = 70
_syswide = AXUIElementCreateSystemWide()


class Target:
    __slots__ = ("cx", "cy", "role", "label")

    def __init__(self, cx: float, cy: float, role: str, label: str) -> None:
        self.cx, self.cy, self.role, self.label = cx, cy, role, label


def _attr(elem, name):
    err, val = AXUIElementCopyAttributeValue(elem, name, None)
    return val if err == 0 else None


def _mouse_point() -> tuple[float, float]:
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return loc.x, loc.y


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


def _enclosing_window(elem):
    """The AXWindow containing elem, or None. Tries the direct attribute, then
    climbs parents."""
    win = _attr(elem, kAXWindowAttribute)
    if win is not None:
        return win
    cur = elem
    for _ in range(_MAX_DEPTH):
        if _attr(cur, kAXRoleAttribute) == "AXWindow":
            return cur
        parent = _attr(cur, kAXParentAttribute)
        if parent is None:
            return None
        cur = parent
    return None


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


def _app_name(pid: int) -> str:
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    return app.localizedName() if app else "?"


def scan_under_cursor(max_elems: int, timeout_s: float, max_area: float):
    """(app_name, targets) for the window under the cursor. Falls back to the
    frontmost app if there's no element under the cursor."""
    x, y = _mouse_point()
    err, elem = AXUIElementCopyElementAtPosition(_syswide, x, y, None)
    if err != 0 or elem is None:
        return _scan_frontmost(max_elems, timeout_s, max_area)

    perr, pid = AXUIElementGetPid(elem, None)
    name = _app_name(pid) if perr == 0 else "?"
    root = _enclosing_window(elem)
    if root is None:
        if perr != 0:
            return _scan_frontmost(max_elems, timeout_s, max_area)
        root = AXUIElementCreateApplication(pid)

    out: list[Target] = []
    _walk(root, out, time.monotonic() + timeout_s, max_elems, max_area)
    return name, out


def _scan_frontmost(max_elems: int, timeout_s: float, max_area: float):
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return "?", []
    axapp = AXUIElementCreateApplication(app.processIdentifier())
    out: list[Target] = []
    _walk(axapp, out, time.monotonic() + timeout_s, max_elems, max_area)
    return app.localizedName(), out


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
        self.app_name = "?"

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                name, snap = scan_under_cursor(self._max, self._timeout, self._max_area)
            except Exception:
                name, snap = "?", []  # never let an AX hiccup kill the engine
            with self._lock:
                self._targets = snap
                self.last_count = len(snap)
                self.app_name = name
            self._stop.wait(self._period)

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> list[Target]:
        with self._lock:
            return self._targets
