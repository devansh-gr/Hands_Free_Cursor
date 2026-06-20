"""Neon 'telekinetic' cursor — a glowing ARROW (normal pointer shape) that
replaces the system cursor: cyan normally, green when locked onto a button.

A small borderless, click-through, top-level transparent window drawn at the
cursor each frame, with the arrow TIP at the cursor hotspot. The real macOS
cursor is hidden separately (cursor.hide_system_cursor) so only this shows.

Perf: moving the window is cheap (~0.06ms) and happens every frame; the glow
redraw is costly (transparent compositing), so it only redraws when the lock
color changes — net well under the frame budget.
"""

W = 64.0          # window size
TIP = W / 2.0     # arrow tip sits at the window center -> at the cursor hotspot
SCALE = 1.7

# Classic pointer outline, offsets from the tip in screen (y-down) pixels.
_ARROW = [(0, 0), (0, 16.5), (4.2, 12.8), (7.0, 19.2), (9.4, 18.1),
          (6.6, 12.2), (12.0, 12.0)]

CYAN = (0.28, 0.85, 1.0)
GREEN = (0.30, 0.95, 0.46)


class CursorGlow:
    def __init__(self) -> None:
        self.available = False
        self._win = None
        self._view = None
        try:
            self._build()
            self.available = True
        except Exception as e:
            self._err = e

    def _build(self) -> None:
        import objc
        from AppKit import (
            NSApplication, NSWindow, NSView, NSColor, NSBezierPath, NSMakeRect,
            NSMakePoint, NSBackingStoreBuffered, NSRoundLineJoinStyle,
            NSApplicationActivationPolicyAccessory,
        )

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory)

        def rgba(r, g, b, a):
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)

        class _Arrow(NSView):
            def initWithFrame_(self, frame):
                self = objc.super(_Arrow, self).initWithFrame_(frame)
                if self is None:
                    return None
                self._rgb = CYAN
                return self

            def setRgb_(self, rgb):
                self._rgb = rgb

            def _path(self):
                p = NSBezierPath.bezierPath()
                for j, (dx, dy) in enumerate(_ARROW):
                    pt = NSMakePoint(TIP + dx * SCALE, TIP - dy * SCALE)  # y-up view
                    if j == 0:
                        p.moveToPoint_(pt)
                    else:
                        p.lineToPoint_(pt)
                p.closePath()
                p.setLineJoinStyle_(NSRoundLineJoinStyle)
                return p

            def drawRect_(self, _r):
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(self.bounds())
                r, g, b = self._rgb
                path = self._path()
                # outer glow halo
                for lw, a in ((12.0, 0.07), (8.0, 0.12), (4.5, 0.28)):
                    rgba(r, g, b, a).set()
                    path.setLineWidth_(lw)
                    path.stroke()
                # solid neon fill
                rgba(r, g, b, 1.0).set()
                path.fill()
                # crisp light edge for definition
                rgba(1, 1, 1, 0.85).set()
                path.setLineWidth_(1.0)
                path.stroke()

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, W), 0, NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setIgnoresMouseEvents_(True)
        win.setHasShadow_(False)
        try:
            win.setLevel_(1001)
        except Exception:
            pass
        view = _Arrow.alloc().initWithFrame_(NSMakeRect(0, 0, W, W))
        win.setContentView_(view)
        self._win, self._view = win, view
        self._shown = False
        self._cur_locked: bool | None = None

    def update(self, x: float, y: float, screen_h: float,
               locked: bool, t: float) -> None:
        """Place the arrow tip at (x, y) (top-left screen coords). Moves every
        call; only redraws when the lock color changes."""
        if not self.available:
            return
        from AppKit import NSMakePoint
        self._win.setFrameOrigin_(NSMakePoint(x - TIP, screen_h - (y + (W - TIP))))
        if not self._shown:
            self._win.orderFrontRegardless()
            self._shown = True
        if locked != self._cur_locked:
            self._view.setRgb_(GREEN if locked else CYAN)
            self._view.setNeedsDisplay_(True)
            self._cur_locked = locked
        self._pump()

    def hide(self) -> None:
        if self.available and self._win is not None and self._shown:
            self._win.orderOut_(None)
            self._shown = False
            self._pump()

    def _pump(self) -> None:
        from Foundation import NSRunLoop, NSDate, NSDefaultRunLoopMode
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.0))
