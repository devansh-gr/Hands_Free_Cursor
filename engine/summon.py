"""Claude summon — tilt your head right ("huh?") to call Claude on your screen.

Captures the screen, hands the screenshot to the local `claude` CLI (Claude
Code, already authed — no API key needed) read-only, and shows Claude's answer
in a floating panel. The CLI call runs in a background thread so the 120 Hz
cursor loop never stalls; the main loop polls state and renders the panel.
"""

import os
import shutil
import subprocess
import threading

SHOT_PATH = "/tmp/telekinesis_shot.png"
MODEL = "claude-haiku-4-5"  # fast; opus was ~18s, haiku is much quicker
DEFAULT_PROMPT = ("What's on my screen, and what's the single most useful thing "
                  "I could do next? Answer in under 3 sentences, plainly.")


def _claude_bin() -> str | None:
    return shutil.which("claude") or (
        os.path.expanduser("~/.local/bin/claude")
        if os.path.exists(os.path.expanduser("~/.local/bin/claude")) else None)


class Summoner:
    """Runs screenshot → claude in a background thread; exposes state/text."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "idle"   # idle | thinking | done | error
        self.text = ""
        self._thread: threading.Thread | None = None
        self._bin = _claude_bin()

    @property
    def available(self) -> bool:
        return self._bin is not None

    def busy(self) -> bool:
        with self._lock:
            return self.state == "thinking"

    def start(self, prompt: str = DEFAULT_PROMPT) -> None:
        if self.busy() or not self.available:
            return
        with self._lock:
            self.state = "thinking"
            self.text = "Claude is looking at your screen…"
        self._thread = threading.Thread(target=self._run, args=(prompt,), daemon=True)
        self._thread.start()

    def _run(self, prompt: str) -> None:
        try:
            subprocess.run(["screencapture", "-x", SHOT_PATH], check=True, timeout=12)
            full = (f"Look at the screenshot at {SHOT_PATH} using the Read tool. "
                    f"{prompt}")
            proc = subprocess.run(
                [self._bin, "-p", full, "--allowedTools", "Read", "--model", MODEL],
                capture_output=True, text=True, timeout=90)
            out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
            with self._lock:
                self.state = "done"
                self.text = out or "(Claude returned nothing)"
        except subprocess.TimeoutExpired:
            with self._lock:
                self.state = "error"
                self.text = "Claude took too long — try again."
        except subprocess.CalledProcessError:
            with self._lock:
                self.state = "error"
                self.text = ("Couldn't capture the screen. Grant Screen Recording "
                             "permission (System Settings → Privacy & Security).")
        except Exception as e:  # never crash the engine
            with self._lock:
                self.state = "error"
                self.text = f"summon failed: {e}"

    def snapshot(self) -> tuple[str, str]:
        with self._lock:
            return self.state, self.text

    def dismiss(self) -> None:
        with self._lock:
            self.state = "idle"
            self.text = ""


# --- floating response panel (lazy Cocoa; non-fatal if windowing fails) ------

PANEL_W = 680.0
PANEL_H = 240.0


class TextOverlay:
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
            NSApplication, NSWindow, NSView, NSColor, NSBezierPath, NSFont,
            NSMakeRect, NSInsetRect, NSBackingStoreBuffered,
            NSApplicationActivationPolicyAccessory, NSMutableParagraphStyle,
            NSMutableDictionary, NSFontAttributeName, NSForegroundColorAttributeName,
            NSParagraphStyleAttributeName, NSLineBreakByWordWrapping,
        )
        from Foundation import NSAttributedString

        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory)

        def rgba(r, g, b, a):
            return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)

        class _View(NSView):
            def initWithFrame_(self, frame):
                self = objc.super(_View, self).initWithFrame_(frame)
                if self is None:
                    return None
                self._title = "🧠 Claude"
                self._body = ""
                return self

            def setText_title_(self, body, title):
                self._body, self._title = body, title

            def drawRect_(self, _r):
                b = self.bounds()
                NSColor.clearColor().set()
                NSBezierPath.fillRect_(b)
                card = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                    NSInsetRect(b, 2, 2), 20, 20)
                rgba(0.10, 0.11, 0.13, 0.97).set()
                card.fill()
                rgba(0.21, 0.90, 0.75, 0.55).set()
                card.setLineWidth_(1.5)
                card.stroke()

                tattrs = NSMutableDictionary.dictionary()
                tattrs.setObject_forKey_(NSFont.boldSystemFontOfSize_(17),
                                         NSFontAttributeName)
                tattrs.setObject_forKey_(rgba(0.21, 0.90, 0.75, 1), NSForegroundColorAttributeName)
                NSAttributedString.alloc().initWithString_attributes_(
                    self._title, tattrs).drawAtPoint_(
                    __import__("AppKit").NSMakePoint(26, PANEL_H - 42))

                para = NSMutableParagraphStyle.alloc().init()
                para.setLineBreakMode_(NSLineBreakByWordWrapping)
                battrs = NSMutableDictionary.dictionary()
                battrs.setObject_forKey_(NSFont.systemFontOfSize_(15), NSFontAttributeName)
                battrs.setObject_forKey_(rgba(0.92, 0.95, 0.98, 1), NSForegroundColorAttributeName)
                battrs.setObject_forKey_(para, NSParagraphStyleAttributeName)
                NSAttributedString.alloc().initWithString_attributes_(
                    self._body, battrs).drawInRect_(
                    NSMakeRect(26, 22, PANEL_W - 52, PANEL_H - 78))

        from AppKit import NSWindow as _W
        win = _W.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, PANEL_W, PANEL_H), 0, NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(NSColor.clearColor())
        win.setIgnoresMouseEvents_(True)
        win.setHasShadow_(True)
        try:
            win.setLevel_(1000)
        except Exception:
            pass
        view = _View.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_W, PANEL_H))
        win.setContentView_(view)
        self._win, self._view = win, view

    def show(self, body: str, title: str, screen_w: float, screen_h: float) -> None:
        if not self.available:
            return
        from AppKit import NSMakeRect
        x = (screen_w - PANEL_W) / 2.0
        y = screen_h - PANEL_H - 70.0   # top-centre (Cocoa bottom-left origin)
        self._view.setText_title_(body, title)
        self._win.setFrame_display_(NSMakeRect(x, y, PANEL_W, PANEL_H), True)
        self._win.orderFrontRegardless()
        self._view.setNeedsDisplay_(True)
        self.pump()

    def hide(self) -> None:
        if self.available and self._win is not None:
            self._win.orderOut_(None)
            self.pump()

    def pump(self) -> None:
        if not self.available:
            return
        from Foundation import NSRunLoop, NSDate, NSDefaultRunLoopMode
        NSRunLoop.currentRunLoop().runMode_beforeDate_(
            NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.0))
