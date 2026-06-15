"""Clickable-target discovery via the macOS Accessibility tree.

This is the OS's own structured map of the UI — buttons, links, window
controls — read straight from the app. NOT computer vision: no pixels, no
camera, no ML. Same Accessibility permission the cursor already needs.

Design notes that matter:
- Scans the WINDOW UNDER THE CURSOR (system-wide element-at-position ->
  enclosing window), not the keyboard-focused app — the focused app is the
  terminal running the engine, not what the head-cursor points at.
- Clickability is decided by whether the element exposes an AXPress ACTION,
  not just by a role-name whitelist — this catches buttons that report
  non-obvious roles (e.g. Chrome's toolbar buttons).
- Traversal is BREADTH-FIRST so shallow window chrome (toolbar, tab strip,
  the new-tab button) is found before a deep web page exhausts the scan
  budget. Depth-first would dive into web content and never reach them.
- The element directly under the cursor is always included (climbing to its
  pressable ancestor), so whatever you're pointing at is lockable even if the
  bounded walk didn't reach it.
"""

import collections
import threading
import time

import Quartz
from AppKit import NSRunningApplication, NSWorkspace
from ApplicationServices import (
    AXUIElementCreateApplication,
    AXUIElementCreateSystemWide,
    AXUIElementCopyElementAtPosition,
    AXUIElementCopyAttributeValue,
    AXUIElementCopyActionNames,
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

# Fast-path roles: definitely clickable, skip the action lookup.
CLICKABLE_ROLES = {
    "AXButton", "AXLink", "AXMenuButton", "AXPopUpButton", "AXCheckBox",
    "AXRadioButton", "AXDisclosureTriangle", "AXCloseButton",
    "AXMinimizeButton", "AXZoomButton", "AXToolbarButton", "AXSegment",
    "AXStepper", "AXIncrementor", "AXSwitch", "AXTabButton", "AXMenuItem",
}

# Pure structure/content roles: never pressable, skip the action lookup to
# keep scans fast (these dominate a UI tree by count).
_NEVER = {
    "AXStaticText", "AXTextArea", "AXTextField", "AXImage", "AXHeading",
    "AXGroup", "AXScrollArea", "AXScrollBar", "AXList", "AXTable", "AXRow",
    "AXColumn", "AXCell", "AXOutline", "AXSplitGroup", "AXLayoutArea",
    "AXLayoutItem", "AXWebArea", "AXMenuBar", "AXToolbar", "AXTabGroup",
    "AXUnknown", "AXValueIndicator", "AXGenericElement",
}

_MAX_DEPTH = 60
_MAX_NODES = 8000           # hard cap on elements visited per scan
MAX_TARGET_H = 1e9          # set from config by TargetTracker; caps snap-target
                            # height so big thumbnails/cards aren't magnets
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


def _is_clickable(elem, role) -> bool:
    if role in CLICKABLE_ROLES:
        return True
    if role in _NEVER or role is None:
        return False
    err, actions = AXUIElementCopyActionNames(elem, None)
    return err == 0 and actions is not None and "AXPress" in actions


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


def _make_target(elem, role, max_area):
    r = _rect(elem)
    if r is None:
        return None
    x, y, w, h = r
    # Skip zero/sub-pixel, too-tall (thumbnails/cards), and whole-pane
    # "clickable" containers that would otherwise magnet a big region.
    if not (6.0 < w and 6.0 < h <= MAX_TARGET_H and (w * h) < max_area):
        return None
    label = _attr(elem, kAXTitleAttribute) or role
    return Target(x + w / 2.0, y + h / 2.0, role, str(label))


def _enclosing_window(elem):
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


def _pressable_self_or_ancestor(elem, max_area):
    """The element under the cursor (or its nearest pressable ancestor) as a
    Target — guarantees the thing you're pointing at is always snappable."""
    cur = elem
    for _ in range(8):
        role = _attr(cur, kAXRoleAttribute)
        if _is_clickable(cur, role):
            return _make_target(cur, role, max_area)
        parent = _attr(cur, kAXParentAttribute)
        if parent is None:
            return None
        cur = parent
    return None


def _walk_bfs(root, deadline, max_elems, max_area):
    """Breadth-first collection of clickable targets, bounded by time, count,
    and total nodes visited."""
    out: list[Target] = []
    seen = set()
    nodes = 0
    queue = collections.deque(((root, 0),))
    while queue and len(out) < max_elems and nodes < _MAX_NODES:
        if time.monotonic() > deadline:
            break
        elem, depth = queue.popleft()
        nodes += 1
        role = _attr(elem, kAXRoleAttribute)
        if _is_clickable(elem, role):
            t = _make_target(elem, role, max_area)
            if t is not None:
                key = (round(t.cx), round(t.cy))
                if key not in seen:
                    seen.add(key)
                    out.append(t)
        if depth < _MAX_DEPTH:
            for child in _attr(elem, kAXChildrenAttribute) or ():
                queue.append((child, depth + 1))
    return out, seen


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

    out, seen = _walk_bfs(root, time.monotonic() + timeout_s, max_elems, max_area)

    # Guarantee the element under the cursor is snappable even if the bounded
    # walk missed it (e.g. deep inside a huge page).
    here = _pressable_self_or_ancestor(elem, max_area)
    if here is not None and (round(here.cx), round(here.cy)) not in seen:
        out.append(here)
    return name, out


def _scan_frontmost(max_elems: int, timeout_s: float, max_area: float):
    app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if app is None:
        return "?", []
    axapp = AXUIElementCreateApplication(app.processIdentifier())
    out, _ = _walk_bfs(axapp, time.monotonic() + timeout_s, max_elems, max_area)
    return app.localizedName(), out


class TargetTracker(threading.Thread):
    """Background AX scanner. snapshot() is the only thing the render loop calls."""

    def __init__(self, refresh_hz: float, max_elems: int, timeout_s: float,
                 screen_area: float, max_target_h: float = 1e9) -> None:
        super().__init__(daemon=True)
        global MAX_TARGET_H
        MAX_TARGET_H = max_target_h
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
