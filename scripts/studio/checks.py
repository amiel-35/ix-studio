"""checks: mechanical checks of piece.html against the brand, and the judge's free notes.

Form only: palette, fonts, contrast, length, forbidden words, image, logo. Each result is
{id, status: pass|warn|fail, say}. The judge's notes (judge.md, written by an agent) are shown, never blocking.
"""

import html
import re
from pathlib import Path

from colour import contrast, css_to_hex, hex6
from files import GENERIC_FONTS, palette

RGB = re.compile(r"rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[\d.]+\s*)?\)")
HEXC = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b")


def _style(src):
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", src, re.S)) + "\n" + " ".join(re.findall(r'style="([^"]*)"', src))


def text(src, cls):
    """The text of the first element carrying the class token `cls`, or None."""
    m = re.search(rf"""<(\w+)[^>]*class=["'][^"']*(?<![\w-]){cls}(?![\w-])[^"']*["'][^>]*>(.*?)</\1>""", src, re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip() if m else None


def _prop(css, sel, prop):
    m = re.search(rf"\.{sel}\s*\{{[^}}]*?(?<![-\w]){prop}\s*:\s*([^;}}]+)", css)
    return css_to_hex(m.group(1)) if m else None


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

    fg, bg = _prop(css, "hl", "color"), _prop(css, "blk", "background")
    if fg and bg:
        c = contrast(fg, bg)
        add("contrast", c >= 3, f"headline {fg} on {bg}: contrast {c:.1f}:1 (large text needs 3:1)")
    else:
        add("contrast", False, "headline colour or its ground not found in piece.html (.hl color, .blk background)", "warn")

    head, sub, cta = text(src, "hl"), text(src, "sub") or "", text(src, "cta") or ""
    if head is None:
        add("length", False, "headline not found in piece.html")
        add("never", False, "headline not found in piece.html")
    else:
        n = len(head.split())
        add("length", n <= 12, f"headline is {n} word(s)" + ("" if n <= 12 else ": shorter is stronger (12 max)"), "warn")
        hits = [w for w in brand["never"] if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", " ".join((head, sub, cta)), re.I)]
        add("never", not hits, "none of the brand's never-words appears" if not hits else f"forbidden by the brand: {', '.join(hits)}")

    has_img = 'class="bg"' in src
    add("image", has_img, "a generated or provided image is used" if has_img else "placeholder: no generated image", "warn")
    has_logo = 'class="logo"' in src
    add("logo", has_logo, "logo present" if has_logo else "no logo file: the brand name is set in type instead", "warn")
    return res


def summary(results, notes):
    c = {k: sum(1 for r in results if r["status"] == k) for k in ("pass", "warn", "fail")}
    return {**c, "judge": len(notes)}


def line(s):
    return f"check: {s['pass']} pass · {s['warn']} warn · {s['fail']} fail · {s['judge']} judge notes"
