"""colour: hex parsing and WCAG contrast, the little maths the composer and the checker share."""

import re


def hex6(h: str) -> str:
    h = h.strip().lstrip("#").lower()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h[:6]


def rgb(h: str):
    h = hex6(h)[1:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(h: str, a: float) -> str:
    r, g, b = rgb(h)
    return f"rgba({r},{g},{b},{a})"


def css_to_hex(s: str):
    """'#abc', 'rgb(1,2,3)' or 'rgba(1,2,3,.5)' -> '#rrggbb' (alpha ignored), else None."""
    s = s.strip().lower()
    if re.fullmatch(r"#(?:[0-9a-f]{3}|[0-9a-f]{6})", s):
        return hex6(s)
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*[\d.]+\s*)?\)", s)
    return "#%02x%02x%02x" % tuple(int(x) for x in m.groups()) if m else None


def lum(h: str) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def ink_on(ground: str, candidates) -> str:
    """The first candidate (brand text colour first) readable on the ground (4.5), else the best of them."""
    for c in candidates:
        if contrast(ground, c) >= 4.5:
            return c
    return max(candidates, key=lambda c: contrast(ground, c))
