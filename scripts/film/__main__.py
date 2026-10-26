"""film: the first film of a project, motion made by code. No video engine: each shot of the storyboard is an HTML page animated by a few lines
of script, in the colours and fonts of the brand and with its logo; headless Chrome captures it image by image, ffmpeg assembles the MP4.

    python3 scripts/film <piece dir> <storyboard.json> --out film.mp4 [--fps 10]

The piece folder is the one of scripts/studio (its brand.md gives the colours, the fonts and the logo). The storyboard is what `scripts/agents
storyboard` gives, after the person corrected it: {"shots": [{seconds, visual, text, colour, read}]}. One format: 9:16 vertical, 1080 x 1920.
It gives {"video", "seconds", "frames"} as JSON on the output. A failure is its reason on stderr, exit 1.
"""

import argparse
import html
import json
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "studio"))

import compose  # noqa: E402
from colour import contrast  # noqa: E402
from files import StudioError, font_css, load_brand  # noqa: E402

SIZE = (1080, 1920)
FADE_IN, FADE_OUT = 0.7, 0.35  # seconds
PAGE = """<!doctype html><html><head><meta charset="utf-8">{fonts}<style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:{colour}}}
#s{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 90px;box-sizing:border-box}}
#t{{margin:0;font-family:{hf};font-size:{size}px;line-height:1.12;font-weight:600;color:{ink};text-wrap:balance}}
#l{{max-width:640px;max-height:420px;object-fit:contain}}
#n{{margin:0;font-family:{hf};font-size:120px;font-weight:700;color:{ink}}}
#b{{position:absolute;left:90px;right:90px;bottom:110px;height:8px;background:{ink};opacity:.9;transform-origin:left}}
</style></head><body><div id="s">{body}</div><div id="b"></div><script>
var D={dur},IN={fin},OUT={fout},t=parseFloat((location.hash.match(/t=([\\d.]+)/)||[0,0])[1]);
var e=function(x){{return 1-Math.pow(1-Math.min(1,Math.max(0,x)),3)}};
var a=Math.min(e(t/IN),Math.min(1,Math.max(0,(D-t)/OUT)));
var s=document.getElementById("s");s.style.opacity=a;
s.style.transform="translateY("+((1-e(t/IN))*70)+"px) scale("+(1+0.03*t/D)+")";
document.getElementById("b").style.transform="scaleX("+Math.min(1,t/D)+")";
</script></body></html>
"""


def ink_on(colour, palette):
    """The colour of the text on a ground: the most contrasted of the brand's colours and of black and white."""
    return max([*palette, "#ffffff", "#111111"], key=lambda c: contrast(c, colour))


def shot_page(shot, brand, piece, palette) -> str:
    colour = shot["colour"]
    ink = ink_on(colour, palette)
    logo = piece / brand["logo"] if brand["logo"] and not brand.get("logo_missing") else None
    if shot["visual"] == "logo":
        body = f'<img id="l" src="{logo.resolve().as_uri()}" alt="">' if logo else f'<p id="n">{html.escape(brand["name"])}</p>'
        size = 120
    else:
        body = f'<p id="t">{html.escape(shot["text"])}</p>'
        size = 150 if len(shot["text"]) <= 24 else 112 if len(shot["text"]) <= 50 else 84
    return PAGE.format(fonts=compose.fonts_link(brand), w=SIZE[0], h=SIZE[1], colour=colour, hf=font_css(brand["hfont"], "Georgia,serif"), size=size, ink=ink,
                       body=body, dur=shot["seconds"], fin=FADE_IN, fout=FADE_OUT)


def capture(chrome, page: Path, t: float, png: Path):
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--virtual-time-budget=3000", f"--screenshot={png}",
           f"--window-size={SIZE[0]},{SIZE[1]}", f"{page.resolve().as_uri()}#t={t:.3f}"]
    subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
    if not png.exists() or not png.stat().st_size:
        raise StudioError(f"Chrome did not capture {page.name} at {t:.2f} s")


def check_shots(sb):
    shots = sb.get("shots") if isinstance(sb, dict) else None
    if not isinstance(shots, list) or not shots:
        raise StudioError("storyboard: a list of shots is needed")
    for n, s in enumerate(shots, 1):
        ok = isinstance(s, dict) and isinstance(s.get("seconds"), (int, float)) and 0 < s["seconds"] <= 30 and s.get("visual") in ("texte", "logo") \
            and isinstance(s.get("colour"), str) and s["colour"].startswith("#") and len(s["colour"]) == 7 and (s["visual"] == "logo" or str(s.get("text") or "").strip())
        if not ok:
            raise StudioError(f"storyboard: shot {n} needs seconds, a visual (texte or logo), a colour (#rrggbb) and, for a text, its text")


def render(piece, storyboard, out, fps=10) -> dict:
    piece, out = Path(piece).resolve(), Path(out).resolve()
    try:
        sb = json.loads(Path(storyboard).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise StudioError(f"storyboard: {storyboard} is not readable JSON ({err})") from None
    check_shots(sb)
    chrome = compose.find_chrome()
    if not chrome:
        raise StudioError("no headless Chrome found (set CHROME=/path/to/chrome)")
    if not shutil.which("ffmpeg"):
        raise StudioError("ffmpeg not found: the film is assembled with it")
    brand = load_brand(piece)
    palette = [c for c in [brand["background"], brand["text"], brand["accent"], *brand["extras"]] if c]
    with tempfile.TemporaryDirectory(prefix="ixs-film-") as tmp:
        tmp = Path(tmp)
        jobs, n = [], 0
        for k, shot in enumerate(sb["shots"]):
            page = tmp / f"shot-{k}.html"
            page.write_text(shot_page(shot, brand, piece, palette), encoding="utf-8")
            for f in range(round(shot["seconds"] * fps)):
                n += 1
                jobs.append((page, f / fps, tmp / f"f{n:05d}.png"))
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda j: capture(chrome, *j), jobs))
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(tmp / "f%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(out)], stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if r.returncode or not out.is_file():
            raise StudioError("ffmpeg failed: " + ((r.stderr or "").strip().splitlines() or [f"exit {r.returncode}"])[-1])
    return {"video": str(out), "seconds": round(n / fps, 1), "frames": n}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="film", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("piece", help="a piece folder of scripts/studio (its brand.md)")
    ap.add_argument("storyboard", help="the storyboard, a JSON file")
    ap.add_argument("--out", required=True, help="the MP4 to write")
    ap.add_argument("--fps", type=int, default=10)
    a = ap.parse_args(argv)
    try:
        print(json.dumps(render(a.piece, a.storyboard, a.out, a.fps), ensure_ascii=False))
    except StudioError as err:
        print(f"film: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
