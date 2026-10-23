"""compose: the poster as one HTML page at its exact pixel size, and its screenshot when a headless Chrome exists.

The image model never writes text: the headline is HTML, in the brand's fonts and colours. Only brand colours (and
rgba() of them for a scrim) appear in the page, so `check` can verify it.
"""

import glob
import html
import math
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

from colour import contrast, ink_on, rgba
from files import LAYOUTS, font_css, ground_hex, image_file

e = html.escape


def meets(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def inside(a, b):
    return a[0] >= b[0] and a[1] >= b[1] and a[0] + a[2] <= b[0] + b[2] and a[1] + a[3] <= b[1] + b[3]


def areas(layout, w, h, lg=None, gap=24):
    """(effective layout, image rect, text rect, solid rects), rects as (x, y, w, h) in px; lg is the logo rect, if any."""
    lay = "stack" if layout == "side" and w <= h else layout
    if lay == "side":
        iw = round(.55 * w)
        return lay, (0, 0, iw, h), (iw, 0, w - iw, h), [(iw, 0, w - iw, h)]
    if lay == "stack":
        ih = round(.58 * h)
        return lay, (0, 0, w, ih), (0, ih, w, h - ih), [(0, ih, w, h - ih)]
    if lay == "ground":
        m = round(.06 * min(w, h))
        top, bot = m, h - m
        if lg:
            top, bot = (lg[1] + lg[3] + gap, bot) if lg[1] < h / 2 else (top, lg[1] - gap)
        ch = bot - top
        if w > h:
            tw = round(.42 * (w - 2 * m))
            return lay, (2 * m + tw, top, w - 3 * m - tw, ch), (m, top, tw, ch), [(0, 0, w, h)]
        th = round(.36 * ch)
        return lay, (m, top + th + m, w - 2 * m, ch - th - m), (m, top, w - 2 * m, th), [(0, 0, w, h)]
    bh = round(.42 * h)
    return lay, (0, 0, w, h), (0, 0, w, bh) if lay == "overlay-top" else (0, h - bh, w, bh), []


def wrap_lines(text, size, width):
    lines, cur = 1, 0.0
    for wd in text.split():
        n = (len(wd) + 1) * size * .52
        if cur and cur + n > width + size * .52:
            lines, cur = lines + 1, 0.0
        cur += n
    return lines


def headline_size(headline, iw, ih, cap, extra):
    n = len(headline.split())
    size = min(cap, iw * (0.13 if n <= 4 else 0.105 if n <= 8 else 0.082))
    while size > 16 and wrap_lines(headline, size, iw) * size * 1.08 > ih - extra:
        size *= .94
    return round(size)


def glue(t):
    """Non-breaking spaces: the last two words stay together (3+ words), and a 1-2 letter word sticks to the next one."""
    ws = t.split()
    return "".join((("\xa0" if len(ws[i - 1]) <= 2 or (len(ws) > 2 and i == len(ws) - 1) else " ") if i else "") + w for i, w in enumerate(ws))


def fonts_link(brand) -> str:
    fams = [f for f in dict.fromkeys([brand["hfont"], brand["bfont"]]) if f]
    if not fams:
        return ""
    q = "&".join("family=" + quote_plus(f) for f in fams)
    return f'<link rel="stylesheet" href="{e("https://fonts.googleapis.com/css2?" + q + "&display=swap")}">'


def px(r):
    return f"left:{r[0]}px;top:{r[1]}px;width:{r[2]}px;height:{r[3]}px"


def render(d, brand, brief, variant, headline, alt=True):
    """(html, warnings). `alt`: look for another layout to suggest when the hierarchy fails."""
    w, h = brief["size"]
    u = math.sqrt(w * h) / 1080
    img = image_file(d)
    ground = ground_hex(brand, variant["ground"])
    pal = list(dict.fromkeys([brand["text"], brand["background"], *([brand["accent"]] if brand["accent"] else []), *brand["extras"],
                              *([brand["headline_colour"]] if brand["headline_colour"] else [])]))
    ink = ink_on(ground, pal)
    want = brand["headline_colour"] or brand["text"]
    hc = want if contrast(want, ground) >= 3 else ink_on(ground, pal)
    hf, bf = font_css(brand["hfont"], "Georgia,serif"), font_css(brand["bfont"], "system-ui,sans-serif")
    file_logo = bool(brand["logo"]) and not brand.get("logo_missing")
    kind = "file" if file_logo else "placeholder" if brand["logo_placeholder"] else "none"
    pos, lh, lm = brand["logo_position"], round(72 * u), round(40 * u)
    lw = lh * 3 if kind == "file" else lh
    lg = None if kind == "none" else (lm if pos.endswith("left") else w - lm - lw, lm if pos.startswith("top") else h - lm - lh, lw, lh)
    slogan, sl = brand["slogan"], None
    if slogan and lg:  # beside the logo, on its inner side; the reserved corner grows to cover both
        pad, fs = round(10 * u), 26 * u
        while len(slogan) * fs * .56 > .4 * w - 2 * pad:  # one line
            fs *= .94
        sw = round(min(len(slogan) * fs * .56, .4 * w - 2 * pad)) + 2 * pad
        off = lm + lw + 2 * pad + (4 if kind == 'placeholder' else 0)  # flush with the logo's chip (and its dashed border)
        right = not pos.endswith("left")
        x = w - off - sw if right else off
        sl = (right, off, sw, pad, round(fs))
        lg = (min(x, lg[0]), lg[1], max(x + sw, lg[0] + lg[2]) - min(x, lg[0]), lg[3])
    lay, ir, tr, solid = areas(variant["layout"], w, h, lg, round(24 * u))
    over = lay.startswith("overlay")
    p = 0 if lay == "ground" else round(56 * u)
    pt = pb = pl = pr = p
    if lg and meets(tr, lg) and lay != "ground":
        band = round(24 * u)
        vt = max(p, lg[1] + lg[3] - tr[1] + band) if lg[1] < h / 2 else max(p, tr[1] + tr[3] - lg[1] + band)
        hz = max(p, lg[0] + lg[2] - tr[0] + band) if pos.endswith("left") else max(p, tr[0] + tr[2] - lg[0] + band)
        if tr[2] > 2 * tr[3] and hz * tr[3] <= vt * tr[2]:  # a wide band: keep the logo's corner free on its side if that costs less area than a strip
            pl, pr = (hz, p) if pos.endswith("left") else (p, hz)
        elif lg[1] < h / 2:
            pt = vt
        else:
            pb = vt
    sub_t, cta_t = variant["subline"], brief["cta"]
    iw, ih = tr[2] - pl - pr, tr[3] - pt - pb
    ss, warns = round(34 * u), []

    def fit(ss):
        extra = (round(24 * u) + wrap_lines(sub_t, ss, min(iw, 34 * ss)) * ss * 1.3 if sub_t else 0) + (round(110 * u) if cta_t else 0) + ((80 + (40 if slogan else 0)) * u if kind == "none" else 0)
        return headline_size(headline, iw, ih, .11 * math.sqrt(w * h), extra)
    size = fit(ss)
    while sub_t and size < 1.4 * ss and ss > round(24 * u):  # the headline must stay clearly above the subline
        ss = max(round(24 * u), round(ss * .94))
        size = fit(ss)
    if sub_t and size < 1.4 * ss:
        other = next((l for l in LAYOUTS if alt and areas(l, w, h)[0] != lay and not render(d, brand, brief, {**variant, "layout": l}, headline, False)[1]), None)
        warns.append(f"headline {size}px is under 1.4x the subline {ss}px: " + (f"try the layout {other}" if other else "try a shorter headline"))
    sg = round(min(26 * u, iw / (len(slogan) * .56))) if slogan else 0  # a slogan never wraps
    shape_c = brand["accent"] if brand["accent"] and brand["accent"] != ground else brand["text"]
    frame = f"border:{max(2, round(4 * u))}px solid {ink};" if lay == "ground" else ""
    if over:
        edge = "to bottom" if lay == "overlay-top" else "to top"
        block = f"linear-gradient({edge},{rgba(ground, .55)} 0%,{rgba(ground, .55)} 35%,{rgba(ground, 0)} 100%)"
        just = "flex-start" if lay == "overlay-top" else "flex-end"
    else:
        block, just = ground, "center"
    parts = [f'<img class="bg" src="{e(img)}" alt="">' if img else '<div class="shape"></div>']
    cta = f'<p class="cta">{e(cta_t)}</p>' if cta_t else ""
    sub = f'<p class="sub">{e(sub_t)}</p>' if sub_t else ""
    said = f'<p class="slogan">{e(slogan)}</p>' if slogan else ""
    sig = f'<div class="sig">{e(brand["name"])}{said}</div>' if kind == "none" else ""
    parts.append(f'<div class="blk"><h1 class="hl">{e(glue(headline))}</h1>{sub}{cta}{sig}</div>')
    if kind == "file":
        parts.append(f'<img class="logo" src="{e(brand["logo"])}" alt="{e(brand["name"])}">')
    elif kind == "placeholder":
        parts.append('<div class="logo ph">logo</div>')
    if sl:
        parts.append(said)
    chip = f"background:{ground};padding:{round(10 * u)}px;" if lg and not any(inside(lg, s) for s in solid) else ""
    lpos = f"{'left' if pos.endswith('left') else 'right'}:{lm}px;{'top' if pos.startswith('top') else 'bottom'}:{lm}px"
    slogan_css = ""
    if sl:
        right, off, sw, pad, fs = sl
        slogan_css = (f"\n.blk~.slogan{{position:absolute;{'right' if right else 'left'}:{off}px;{'top' if pos.startswith('top') else 'bottom'}:{lm}px;z-index:2;margin:0;"
                      f"box-sizing:border-box;max-width:{sw}px;height:{lh + 2 * pad}px;padding:0 {pad}px;display:flex;align-items:center;"
                      f"text-align:{'right' if right else 'left'};font-size:{fs}px;{'background:' + ground + ';' if chip else ''}}}")
    css = f"""html,body{{margin:0;padding:0}}
body{{width:{w}px;height:{h}px;position:relative;overflow:hidden;background:{ground if lay == 'ground' else brand['background']}}}
.bg{{position:absolute;{px(ir)};object-fit:{variant.get('fit', 'contain')};background:{ground};box-sizing:border-box;{frame}}}
.shape{{position:absolute;{px(ir)};overflow:hidden;background:{rgba(shape_c, 0.14)};box-sizing:border-box;{frame}}}
.shape::after{{content:"";position:absolute;right:-12%;bottom:-18%;width:70%;padding-bottom:70%;border-radius:50%;background:{rgba(shape_c, 0.16)}}}
.blk{{position:absolute;{px(tr)};padding:{pt}px {pr}px {pb}px {pl}px;background:{block};box-sizing:border-box;display:flex;flex-direction:column;justify-content:{just}}}
.hl{{margin:0;font-family:{hf};font-size:{size}px;line-height:1.05;font-weight:600;text-wrap:balance;color:{hc}}}
.sub{{margin:{round(24 * u)}px 0 0;max-width:34em;font-family:{bf};font-size:{ss}px;line-height:1.3;color:{ink}}}
.cta{{align-self:flex-start;margin:{round(32 * u)}px 0 0;padding:{round(10 * u)}px {round(24 * u)}px;border:3px solid {ink};font-family:{bf};font-size:{round(28 * u)}px;font-weight:600;color:{ink}}}
.sig{{margin-top:{round(40 * u)}px;font-family:{hf};font-size:{round(28 * u)}px;color:{ink}}}
.slogan{{margin:{round(8 * u)}px 0 0;font-family:{bf};font-size:{sg}px;line-height:1.25;white-space:nowrap;color:{ink}}}{slogan_css}
.logo{{position:absolute;{lpos};z-index:2;{chip}display:block;height:{lh}px;box-sizing:content-box}}
.ph{{width:{lh}px;border:2px dashed {ink};display:flex;align-items:center;justify-content:center;font-family:{bf};font-size:{round(20 * u)}px;color:{ink}}}"""
    return (f'<!doctype html>\n<html lang="{e(brief["language"] or "en")}"><head><meta charset="utf-8">'
            f'<title>{e(brand["name"])}</title>{fonts_link(brand)}\n<style>\n{css}\n</style></head>\n<body data-layout="{lay}">\n' + "\n".join(parts) + "\n</body></html>\n", warns)


def find_chrome():
    env = os.environ.get("CHROME")
    if env:
        return env
    hits = sorted(glob.glob("/opt/pw-browsers/chromium*/chrome-linux*/chrome"))
    if hits:
        return hits[0]
    for n in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(n):
            return shutil.which(n)
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if Path(mac).exists() else None


def screenshot(html_path, png_path, size):
    """(ok, message). Never raises."""
    chrome = find_chrome()
    if not chrome:
        return False, "no headless Chrome found (set CHROME=/path/to/chrome): piece.html is the deliverable, open it in a browser"
    html_path, png_path = Path(html_path).resolve(), Path(png_path).resolve()
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--virtual-time-budget=8000",
           f"--screenshot={png_path}",
           f"--window-size={size[0]},{size[1]}", f"file://{html_path}"]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    except Exception as err:
        return False, f"screenshot failed: {err}"
    if png_path.exists() and png_path.stat().st_size:
        return True, "piece.png written"
    return False, f"screenshot failed (chrome exit {r.returncode})"
