"""NSAttributedString helpers for styled menu bar text.

Uses AppKit via PyObjC (bundled with rumps).
"""

from AppKit import (
    NSAttributedString,
    NSColor,
    NSFont,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
    NSMutableAttributedString,
)


def hex_to_nscolor(hex_str):
    """Convert a hex color string like '#FF4444' to an NSColor."""
    h = hex_str.lstrip("#")
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)


def styled_string(text, color=None, font_name="Menlo", font_size=13.0):
    """Return an NSAttributedString with the given font and optional color.

    Args:
        text: The string to style.
        color: A hex color string (e.g. '#FF4444') or None for default.
        font_name: Font family name.
        font_size: Font size in points.

    Returns:
        An NSAttributedString.
    """
    attrs = {}
    font = NSFont.fontWithName_size_(font_name, font_size)
    if font:
        attrs[NSFontAttributeName] = font
    if color:
        attrs[NSForegroundColorAttributeName] = hex_to_nscolor(color)
    return NSAttributedString.alloc().initWithString_attributes_(text, attrs)


def styled_segments(segments, font_name="Menlo", font_size=13.0):
    """Build an NSMutableAttributedString from colored segments.

    Args:
        segments: List of (text, color_hex_or_None) tuples.
        font_name: Font family name.
        font_size: Font size in points.

    Returns:
        An NSMutableAttributedString with per-segment coloring.
    """
    result = NSMutableAttributedString.alloc().init()
    for text, color in segments:
        part = styled_string(text, color=color, font_name=font_name, font_size=font_size)
        result.appendAttributedString_(part)
    return result
