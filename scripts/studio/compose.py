"""compose: the poster as one HTML page at its exact pixel size, and its screenshot when a headless Chrome exists.

The image model never writes text: the headline is HTML, in the brand's fonts and colours. Only brand colours (and
rgba() of them for a scrim) appear in the page, so `check` can verify it.
"""

import glob
import html
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

from colour import ink_on, rgba
from files import font_css, ground_hex, image_file

e = html.escape
PX = {"top": "top:6%", "bottom": "bottom:6%", "center": "top:50%;transform:translateY(-50%)"}


def fonts_link(brand) -> str:
    fams = [f for f in dict.fromkeys([brand["hfont"], brand["bfont"]]) if f]
    if not fams:
        return ""
    q = "&".join("family=" + quote_plus(f) for f in fams)
    return f'<link rel="stylesheet" href="{e("https://fonts.googleapis.com/css2?" + q + "&display=swap")}">'


def render(d, brand, brief, variant, headline) -> str:
    w, h = brief["size"]
    s = w / 1080
    img = image_file(d)
    ground = ground_hex(brand, variant["ground"])
    pal = [brand["text"], brand["background"], *([brand["accent"]] if brand["accent"] else []), *brand["extras"]]
    ink = ink_on(ground, pal)
    n = len(headline.split())
    size = round(w * (0.1 if n <= 4 else 0.08 if n <= 8 else 0.062))
    hf, bf = font_css(brand["hfont"], "Georgia,serif"), font_css(brand["bfont"], "system-ui,sans-serif")
    block = rgba(ground, 0.9) if img else ground
    shape_c = brand["accent"] or brand["text"]
    opposite = "bottom:-12%" if variant["layout"] == "top" else "top:-12%"
    parts = []
    if img:
        parts.append(f'<img class="bg" src="{e(img)}" alt="">')
    else:
        parts.append('<div class="shape"></div>')
    sig = (f'<img class="logo" src="{e(brand["logo"])}" alt="{e(brand["name"])}">'
           if brand["logo"] and not brand.get("logo_missing") else f'<div class="sig">{e(brand["name"])}</div>')
    cta = f'<p class="cta">{e(brief["cta"])}</p>' if brief["cta"] else ""
    sub = f'<p class="sub">{e(variant["subline"])}</p>' if variant["subline"] else ""
    parts.append(f'<div class="blk"><h1 class="hl">{e(headline)}</h1>{sub}{cta}{sig}</div>')
    css = f"""html,body{{margin:0;padding:0}}
body{{width:{w}px;height:{h}px;position:relative;overflow:hidden;background:{brand['background']}}}
.bg{{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:cover}}
.shape{{position:absolute;{opposite};right:-14%;width:{round(w * 0.7)}px;height:{round(w * 0.7)}px;border-radius:50%;background:{rgba(shape_c, 0.16)}}}
.blk{{position:absolute;left:6%;right:6%;{PX[variant['layout']]};padding:{round(56 * s)}px;background:{block};box-sizing:border-box}}
.hl{{margin:0;font-family:{hf};font-size:{size}px;line-height:1.05;font-weight:600;color:{ink}}}
.sub{{margin:{round(24 * s)}px 0 0;font-family:{bf};font-size:{round(34 * s)}px;line-height:1.3;color:{ink}}}
.cta{{display:inline-block;margin:{round(32 * s)}px 0 0;padding:{round(10 * s)}px {round(24 * s)}px;border:3px solid {ink};font-family:{bf};font-size:{round(28 * s)}px;font-weight:600;color:{ink}}}
.sig{{margin-top:{round(40 * s)}px;font-family:{hf};font-size:{round(28 * s)}px;color:{ink}}}
.logo{{display:block;margin-top:{round(40 * s)}px;height:{round(64 * s)}px;max-width:60%}}"""
    return (f'<!doctype html>\n<html lang="{e(brief["language"] or "en")}"><head><meta charset="utf-8">'
            f'<title>{e(brand["name"])}</title>{fonts_link(brand)}\n<style>\n{css}\n</style></head>\n<body>\n' + "\n".join(parts) + "\n</body></html>\n")


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
