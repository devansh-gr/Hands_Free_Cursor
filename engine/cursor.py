"""Stage 3 — OS controller. Posts real HID-level events via Quartz."""

import Quartz


def screen_size() -> tuple[float, float]:
    bounds = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return bounds.size.width, bounds.size.height


def move(x: float, y: float) -> None:
    """Post a real mouseMoved event (not a warp) so apps see normal motion."""
    event = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def click(x: float, y: float) -> None:
    """Post a left mouse down+up pair at (x, y)."""
    for event_type in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(
            None, event_type, (x, y), Quartz.kCGMouseButtonLeft
        )
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def play_click_sound() -> None:
    """Soft audible tick so click feedback is felt without looking at the HUD."""
    try:
        from AppKit import NSSound
        sound = NSSound.soundNamed_("Tink")
        if sound is not None:
            sound.play()
    except ImportError:
        pass


def accessibility_trusted() -> bool:
    """True if this process may post events. False => events are dropped silently."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except ImportError:
        return True  # can't check; let the user verify visually
