"""Edge-dwell scroll math — pure and unit-testable.

Rest the cursor near the top or bottom of the screen and the content scrolls
that way; the deeper into the edge band, the faster. Gentle near the inner
edge (so brushing past the band barely scrolls) and ramps up toward the screen
edge. No mode, no gesture — the cursor's own position is the control.
"""


def scroll_zone(y: float, screen_h: float, band_px: float) -> tuple[int, float]:
    """Classify a cursor y-position.

    Returns (direction, depth):
      direction = +1 in the top band (scroll up), -1 in the bottom band
                  (scroll down), 0 in the neutral middle.
      depth     = 0..1, how far into the band (0 at inner edge, 1 at screen edge).
    """
    if band_px <= 0:
        return 0, 0.0
    if y < band_px:
        return 1, min(1.0, (band_px - y) / band_px)
    if y > screen_h - band_px:
        return -1, min(1.0, (y - (screen_h - band_px)) / band_px)
    return 0, 0.0


def scroll_velocity(direction: int, depth: float, max_speed: float,
                    gamma: float = 1.7) -> float:
    """Pixels/second. The gamma curve keeps slow, controllable scrolling near
    the band's inner edge and fast scrolling only when pushed to the screen edge."""
    return direction * max_speed * (depth ** gamma)
