"""checks: mechanical checks of piece.html against the brand, and the judge's free notes.

Form only: palette, fonts, contrast, length, forbidden words, image, logo. Each result is
{id, status: pass|warn|fail, say}. The judge's notes (judge.md, written by an agent) are shown, never blocking.
"""

import html
import re
from pathlib import Path

from colour import contrast, css_to_hex, hex6
from files import GENERIC_FONTS, never_checkable, never_hits, palette

RGB = re.compile(r"rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)")
HEXC = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


def _style(src):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", src, re.S)) + "\n" + " ".join(re.findall(r'style="([^"]*)"', src))


def text(src, cls):
    """The text of the first element carrying the class token `cls`, or None."""
    m = re.search(rf"""<(\w+)[^>]*class=["'][^"']*(?<![\w-]){cls}(?![\w-])[^"']*["'][^>]*>(.*?)</\1>""", src, re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).split()) if m else None  # \xa0 counts as a space


def _prop(css, sel, prop):
    m = re.search(rf"\.{sel}\s*\{{[^}}]*?(?<![-\w]){prop}\s*:\s*([^;}}]+)", css)
    return css_to_hex(m.group(1)) if m else None


def _px(css, sel):
    m = re.search(rf"\.{sel}\s*\{{[^}}]*?(?<![-\w])font-size\s*:\s*([\d.]+)px", css)
    return float(m.group(1)) if m else None


def judge_notes(d):
    p = Path(d) / "judge.md"
    out = []
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        m = re.match(r"^\s*[-*]\s+(?:\[(minor|major)\]\s*)?(.+)$", line)
        if m:
            out.append({"level": m.group(1) or "note", "say": m.group(2).strip()})
    return out


def run(d, brand):
    src = (Path(d) / "piece.html").read_text(encoding="utf-8")
    css = _style(src)
    res = []

    def add(id, ok, say, bad="fail"):
        res.append({"id": id, "status": "pass" if ok else bad, "say": say})

    pal = set(palette(brand))
    used = {hex6(h) for h in HEXC.findall(css)} | {css_to_hex(c) for c in RGB.findall(css)}
    used |= {w for w in re.findall(r"(?::\s*)(white|black)\b", css)}
    off = sorted(u for u in used if u not in pal)
    add("palette", not off, "every colour is a brand colour" if not off else f"colours outside the brand palette: {', '.join(off)}")

    ok_fonts = {f.lower() for f in (brand["hfont"], brand["bfont"]) if f} | set(GENERIC_FONTS)
    fams = [f.strip().strip("'\"").lower() for m in re.findall(r"font-family\s*:\s*([^;}]+)", css) for f in m.split(",")]
    bad = sorted({f for f in fams if f and f not in ok_fonts})
    add("fonts", not bad, "every font is a brand font" if not bad else f"fonts outside the brand: {', '.join(bad)}")

    lay = (re.search(r'<body[^>]*data-layout="([\w-]+)"', src) or [0, ""])[1]
    fg, bgv = _prop(css, "hl", "color"), re.search(r"\.blk\s*\{[^}]*?(?<![-\w])background\s*:\s*([^;}]+)", css)
    bg = css_to_hex(RGB.search(bgv.group(1)).group(0) if bgv and RGB.search(bgv.group(1)) else bgv.group(1)) if bgv else None
    if fg and bg:
        c = contrast(fg, bg)
        if lay.startswith("overlay"):
            add("contrast", False, f"headline over the image with a light gradient of {bg}: contrast with {bg} is {c:.1f}:1; the image under it decides, look at piece.png", "warn")
        else:
            add("contrast", c >= 3, f"headline {fg} on {bg}: contrast {c:.1f}:1 (large text needs 3:1)")
        want = brand["headline_colour"] or brand["text"]
        if fg == want:
            add("headline colour", True, f"headline is {fg}, the brand's " + ("headline colour" if brand["headline_colour"] else "text colour"))
        elif contrast(want, bg) < 3:
            add("headline colour", False, f"{want} is unreadable on {bg} ({contrast(want, bg):.1f}:1): {fg} used instead", "warn")
        else:
            add("headline colour", False, f"headline is {fg}, the brand's colour is {want}")
    else:
        add("contrast", False, "headline colour or its ground not found in piece.html (.hl color, .blk background)", "warn")

    head, sub, cta = text(src, "hl"), text(src, "sub") or "", text(src, "cta") or ""
    if head is None:
        add("length", False, "headline not found in piece.html")
        add("never", False, "headline not found in piece.html")
    else:
        n = len(head.split())
        add("length", n <= 12, f"headline is {n} word(s)" + ("" if n <= 12 else ": shorter is stronger (12 max)"), "warn")
        hits = never_hits(brand["never"], " ".join((head, sub, cta)))
        prose = [w for w in brand["never"] if w not in never_checkable(brand["never"])]
        if hits:
            add("never", False, f"forbidden by the brand: {', '.join(hits)}")
        elif prose:
            add("never", False, f"not verifiable: {'; '.join(prose)}; write the exact words or characters", "warn")
        else:
            add("never", True, "none of the brand's never-words appears")

    hs, ss = _px(css, "hl"), _px(css, "sub")
    if hs and ss:
        add("hierarchy", hs >= 1.4 * ss, f"headline {hs:g}px, subline {ss:g}px" + ("" if hs >= 1.4 * ss else ": the headline should be at least 1.4x the subline"), "fail" if hs < ss else "warn")
    if cta and sub:
        tok = lambda t: [w.strip(".,;:!?\"'()") for w in t.lower().split()]
        gram = lambda ws: {tuple(ws[i:i + 3]) for i in range(len(ws) - 2)}
        cw, sw = tok(cta), tok(sub)
        dup = f" {' '.join(cw)} " in f" {' '.join(sw)} " or any(("." in w or "@" in w) and w in sw for w in cw) or gram(cw) & gram(sw)
        add("cta", not dup, "the call to action does not repeat the subline" if not dup else "the call to action repeats the subline word for word: say it once", "warn")

    has_img = 'class="bg"' in src
    add("image", has_img, "a generated or provided image is used" if has_img else "placeholder: no generated image", "warn")
    if 'class="logo ph"' in src:
        add("logo", False, "logo placeholder: drop the logo file in and set `logo: <path>`", "warn")
    else:
        has_logo = 'class="logo"' in src
        add("logo", has_logo, "logo present" if has_logo else "no logo file: the brand name is set in type instead", "warn")
    if brand["slogan"]:
        got = " ".join((text(src, "slogan") or "").split())
        add("slogan", got == brand["slogan"], "the slogan is the brand's exact words" if got == brand["slogan"] else
            "the slogan in the piece is not the brand's exact words" if got else "the brand's slogan is missing from the piece")
    if brand["unconfirmed"]:
        keys = ", ".join(k + (f" (source {s})" if s else "") for k, s in brand["unconfirmed"].items())
        add("unconfirmed", False, f"the piece relies on values not confirmed: {keys}; confirm them or remove the marker", "warn")
    return res


def summary(results, notes):
    c = {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "warn", "fail")}
    return {**c, "judge": len(notes), "major": sum(1 for n in notes if n["level"] == "major")}


def line(s):
    return f"check: {s['pass']} pass · {s['warn']} warn · {s['fail']} fail · {s['major']} major judge notes ({s['judge']} notes)"
