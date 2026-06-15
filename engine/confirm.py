"""Click-confirmation overlay.

When the cursor dwells on a button, instead of clicking immediately we pop a
small floating panel with two choices — ✓ Click and ✕ Cancel — anchored near
the target. The user glides onto a choice and dwells briefly to select it.
Eliminates accidental clicks: nothing actually clicks without a second,
deliberate confirmation.

Geometry (placement + hit-testing) is pure and unit-tested. The Cocoa window
is created lazily and wrapped so that, if the windowing layer ever fails, the
engine can fall back to direct clicking instead of crashing.
"""

PANEL_W = 300.0
PANEL_H = 96.0
_BTN_W = 128.0
_BTN_H = 64.0
_MARGIN = 14.0           # gap from panel edge to button
_TOP_BOTTOM = (PANEL_H - _BTN_H) / 2.0  # 16


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def confirm_layout(target_x: float, target_y: float,
                   screen_w: float, screen_h: float) -> dict:
    """Place the panel near the target, on-screen. Returns both the Cocoa
    window frame (bottom-left origin) and the two button rects in TOP-LEFT
    screen coords (matching cursor/CGEvent coords) for hit-testing."""
    wx = _clamp(target_x - PANEL_W / 2.0, 8.0, max(8.0, screen_w - PANEL_W - 8.0))
    below = target_y + 24.0
    if below + PANEL_H <= screen_h - 8.0:
        wy = below
    else:
        wy = target_y - 24.0 - PANEL_H
    wy = _clamp(wy, 8.0, max(8.0, screen_h - PANEL_H - 8.0))

    click_rect = (wx + _MARGIN, wy + _TOP_BOTTOM, _BTN_W, _BTN_H)
    cancel_rect = (wx + PANEL_W - _MARGIN - _BTN_W, wy + _TOP_BOTTOM, _BTN_W, _BTN_H)

    # Local (bottom-left, window-relative) draw rects for the view.
    click_local = (_MARGIN, _TOP_BOTTOM, _BTN_W, _BTN_H)
    cancel_local = (PANEL_W - _MARGIN - _BTN_W, _TOP_BOTTOM, _BTN_W, _BTN_H)

    return {
        "cocoa_frame": (wx, screen_h - (wy + PANEL_H), PANEL_W, PANEL_H),
        "click_rect": click_rect,
        "cancel_rect": cancel_rect,
        "click_local": click_local,
        "cancel_local": cancel_local,
    }


def rect_contains(rect, x: float, y: float) -> bool:
    rx, ry, rw, rh = rect
    return rx <= x <= rx + rw and ry <= y <= ry + rh


def region_at(layout: dict, x: float, y: float):
    """Which choice is the point over: 'click', 'cancel', or None."""
    if rect_contains(layout["click_rect"], x, y):
        return "click"
    if rect_contains(layout["cancel_rect"], x, y):
        return "cancel"
    return None


# --- Cocoa overlay (created lazily; non-fatal if it fails) -------------------

class ConfirmOverlay:
    def __init__(self) -> None:
        self.available = False
        self._win = None
        self._view = None
        try:
            self._build()
            self.available = True
        except Exception as e:  # windowing unavailable — caller falls back
            self._err = e

    def _build(self) -> None:
        import objc
        from AppKit import (
            NSApplication, NSWindow, NSView, NSColor, NSBezierPath, NSFont,
            NSMakeRect, NSMakePoint, NSInsetRect, NSBackingStoreBuffered,
            NSGraphicsContext, NSApplicationActivationPolicyAccessory,
            NSMutableParagraphStyle, NSTextAlignmentCenter,
            NSMutableDictionary, NSFontAttributeName, NSForegroundColorAttributeName,
            NSParagraphStyleAttributeName,
        )
        from Foundation import NSAttributedString

        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        def _rgba(r, g, b, a):
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)

        class _ConfirmView(NSView):
            def initWithFrame_(self, frame):
                self = objc.super(_ConfirmView, self).initWithFrame_(frame)
                if self is None:
                    return None
                self._buttons = []   # (key, local_rect, label, (r,g,b))
                self._hovered = None  # 'click' | 'cancel' | None
                self._progress = 0.0
                return self

            def setButtons_(self, buttons):
                self._buttons = buttons

            def setHover_progress_(self, hovered, progress):
                self._hovered = hovered
                self._progress = progress

            def _label_attrs(self):
                para = NSMutableParagraphStyle.alloc().init()
                para.setAlignment_(NSTextAlignmentCenter)
                attrs = NSMutableDictionary.dictionary()
                attrs.setObject_forKey_(
                    NSFont.systemFontOfSize_weight_(19.0, 0.3), NSFontAttributeName)
                attrs.setObject_forKey_(NSColor.whiteColor(),
                                        NSForegroundColorAttributeName)
                attrs.setObject_forKey_(para, NSParagraphStyleAttributeName)
                return attrs

            def drawRect_(self, _rect):
                b = self.bounds()
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(b)

                # Dark frosted container card with a hairline border.
                card = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSInsetRect(b, 2, 2), 18, 18)
                _rgba(0.11, 0.12, 0.14, 0.96).set()
                card.fill()
                _rgba(1, 1, 1, 0.09).set()
                card.setLineWidth_(1.0)
                card.stroke()

                attrs = self._label_attrs()
                for key, lrect, label, rgb in self._buttons:
                    r = NSMakeRect(*lrect)
                    pill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 13, 13)
                    hovered = (key == self._hovered)
                    _rgba(rgb[0], rgb[1], rgb[2], 1.0 if hovered else 0.88).set()
                    pill.fill()

                    if hovered and self._progress > 0.0:
                        # progress sweeps the pill left→right as a light wash
                        NSGraphicsContext.saveGraphicsState()
                        pill.addClip()
                        fw = lrect[2] * max(0.0, min(1.0, self._progress))
                        _rgba(1, 1, 1, 0.26).set()
                        NSBezierPath.fillRect_(NSMakeRect(lrect[0], lrect[1], fw, lrect[3]))
                        NSGraphicsContext.restoreGraphicsState()

                    _rgba(1, 1, 1, 0.18 if hovered else 0.07).set()
                    pill.setLineWidth_(1.0)
                    pill.stroke()

                    s = NSAttributedString.alloc().initWithString_attributes_(label, attrs)
                    sz = s.size()
                    s.drawInRect_(NSMakeRect(
                        lrect[0], lrect[1] + (lrect[3] - sz.height) / 2.0,
                        lrect[2], sz.height))

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PANEL_W, PANEL_H), 0, NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setIgnoresMouseEvents_(True)
        win.setHasShadow_(True)
        try:
            win.setLevel_(1000)  # float above normal windows
        except Exception:
            pass
        view = _ConfirmView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_W, PANEL_H))
        win.setContentView_(view)
        self._win, self._view = win, view

    def open(self, layout: dict) -> None:
        if not self.available:
            return
        from AppKit import NSMakeRect
        cx, cy, w, h = layout["cocoa_frame"]
        self._view.setButtons_([
            ("click", layout["click_local"], "✓  Click", (0.20, 0.63, 0.36)),
            ("cancel", layout["cancel_local"], "✕  Cancel", (0.27, 0.29, 0.34)),
        ])
        self._view.setHover_progress_(None, 0.0)
        self._win.setFrame_display_(NSMakeRect(cx, cy, w, h), True)
        self._win.orderFrontRegardless()
        self._view.setNeedsDisplay_(True)
        self.pump()

    def update(self, hovered, progress: float) -> None:
        if not self.available:
            return
        self._view.setHover_progress_(hovered, progress)
        self._view.setNeedsDisplay_(True)
        self.pump()

    def close(self) -> None:
        if not self.available or self._win is None:
            return
        self._win.orderOut_(None)
        self.pump()

    def pump(self) -> None:
        if not self.available:
            return
        from Foundation import NSRunLoop, NSDate, NSDefaultRunLoopMode
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.0))
