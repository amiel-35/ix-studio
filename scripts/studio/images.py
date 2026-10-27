"""images: the image prompt, and the engines that can draw it.

An engine is one function `(prompt, (w, h), out_path) -> (ok, message)`. None of them ever raises: a failure is a
message, and the piece is composed on a flat brand ground meanwhile. The image never carries text; the headline is
laid in HTML by compose.
"""

import base64
import json
import math
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from compose import areas
from ui import cli

BASE = "No text, no letters, no words, no logos, no watermark."
CALM = "Leave the {where} ~40% of the frame calm and uncluttered, the headline sits there."
FULL = ("The text sits over the image, centred: keep the upper half of the frame and its bottom fifth soft and uncluttered "
        "(a blurred background, plain surfaces, no busy detail), the subject in the middle of the frame.")
BESIDE = "The text sits beside the image, not on it: let the subject fill the frame, centred, the whole subject inside the frame with a margin, nothing important at the edges."
OR_MODEL = "google/gemini-2.5-flash-image"
RATIOS = ((1, 1), (2, 3), (3, 2), (3, 4), (4, 3), (4, 5), (5, 4), (9, 16), (16, 9), (21, 9))
SIGNS = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")


def none_msg(d) -> str:
    return (f"No image generator available: set OPENAI_API_KEY or OPENROUTER_API_KEY (your key) or install and log in to the Codex CLI "
            f"(your ChatGPT plan), then run `{cli(d, 'image')}`, and rerun compose and check after. "
            f"The piece is composed on a flat brand ground meanwhile.")


def build_prompt(brand, brief, variant) -> str:
    w, h = brief["size"]
    iw, ih = zone(brief, variant)
    parts = [variant["image_prompt"].rstrip(". ") + ".",
             f"Format {iw}x{ih}, ratio {api_ratio((iw, ih))}, for the image zone of a {w}x{h} {brief['format']} poster"
             " (this frame wins over any ratio named above: a series may reuse a prompt written for another format).",
             f"Mood from the brand palette: background {brand['background']}, text {brand['text']}"
             + (f", accent {brand['accent']}" if brand["accent"] else "") + ".",
             f"Voice of the brand: {brand['voice']}." if brand["voice"] else "",
             f"Do not show: {'; '.join(brand.get('never_show', []))}." if brand.get("never_show") else "",
             BASE, calm(variant.get("layout"))]
    return " ".join(p for p in parts if p)


def zone(brief, variant):
    """(w, h) of the image zone of the variant's layout."""
    return areas(variant.get("layout"), *brief["size"])[1][2:]


def calm(layout) -> str:
    if layout == "full":
        return FULL
    where = {"overlay-top": "top", "top": "top", "overlay-bottom": "bottom", "bottom": "bottom"}.get(layout)
    return CALM.format(where=where) if where else BESIDE


def api_size(brief) -> str:
    w, h = brief["size"]
    return "1536x1024" if w > h else "1024x1024" if w == h else "1024x1536"


def api_ratio(size) -> str:
    w, h = size
    a, b = min(RATIOS, key=lambda r: abs(math.log(r[0] / r[1] / (w / h))))
    return f"{a}:{b}"


def model_for(engine) -> str:
    env = os.environ.get("STUDIO_IMAGE_MODEL")
    return {"openai": env or "gpt-image-1", "openrouter": env or OR_MODEL, "codex": "codex (its own image tool)"}.get(engine, "")


def api_error(err) -> str:
    try:
        return json.loads(err.read())["error"]["message"]
    except Exception:
        return str(err.reason)


def openai(prompt, wh, out):
    size = api_size({"size": wh})
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return False, "OPENAI_API_KEY is not set."
    model = model_for("openai")
    req = urllib.request.Request("https://api.openai.com/v1/images/generations", method="POST",
                                 data=json.dumps({"model": model, "prompt": prompt, "size": size, "n": 1}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            item = json.load(r)["data"][0]
        if item.get("b64_json"):
            Path(out).write_bytes(base64.b64decode(item["b64_json"]))
        else:
            with urllib.request.urlopen(item["url"], timeout=120) as r:
                Path(out).write_bytes(r.read())
    except urllib.error.HTTPError as err:
        return False, f"OpenAI refused the request (HTTP {err.code}): {api_error(err)}"
    except Exception as err:
        return False, f"OpenAI request failed: {err}"
    return True, f"drawn by OpenAI ({model})"


def openrouter(prompt, wh, out):
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return False, "OPENROUTER_API_KEY is not set."
    model = model_for("openrouter")
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "modalities": ["image", "text"],
            "image_config": {"aspect_ratio": api_ratio(wh)}}
    req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", method="POST", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.load(r)
    except urllib.error.HTTPError as err:
        return False, f"OpenRouter refused the request (HTTP {err.code}): {api_error(err)}"
    except Exception as err:
        return False, f"OpenRouter request failed: {err}"
    try:
        url = data["choices"][0]["message"]["images"][0]["image_url"]["url"]
        raw = base64.b64decode(url.split(",", 1)[1])
    except Exception:
        return False, f"OpenRouter returned no image from {model} (not every model draws images; set STUDIO_IMAGE_MODEL)."
    Path(out).write_bytes(raw)
    return True, f"drawn by OpenRouter ({model})"


def codex(prompt, wh, out):
    size = api_size({"size": wh})
    exe = shutil.which("codex")
    if not exe:
        return False, "The codex CLI is not on PATH."
    out = Path(out).resolve()
    tmp = out.with_name("image.codex.png")
    tmp.unlink(missing_ok=True)
    ask = (f"Generate one image with your image generation tool from this brief, then save it exactly at {tmp} "
           f"(PNG, size close to {size}). Do not write anything else to disk. Brief: {prompt}")
    print("asking Codex for the image, this can take a few minutes…", flush=True)
    try:
        r = subprocess.run([exe, "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", ask],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, cwd=out.parent, timeout=300)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        return False, "codex did not finish within 5 minutes."
    except Exception as err:
        return False, f"codex failed: {err}"
    if tmp.exists() and tmp.stat().st_size > 10240 and tmp.read_bytes()[:8].startswith(SIGNS):
        os.replace(tmp, out)
        return True, "drawn by Codex (your ChatGPT plan)"
    tmp.unlink(missing_ok=True)
    # what Codex said last is on its output (its error, if any, on stderr; the last line of stderr is often only the tokens used)
    said = next((x for x in reversed((r.stdout or "").strip().splitlines()) if x.strip()), "")
    err = next((x for x in (r.stderr or "").splitlines() if x.startswith("ERROR")), "")
    why = (err or said).strip()[:240]
    return False, f"codex ran (exit {r.returncode}) but saved no usable PNG or JPEG image" + (f": {why}" if why else ".") + \
        " (Codex draws only with a model that has an image tool on your plan; otherwise use OPENAI_API_KEY or OpenRouter.)"


def none(prompt, wh, out):
    return False, none_msg(Path(out).parent)


ENGINES = {"openai": openai, "openrouter": openrouter, "codex": codex, "none": none}


def auto_engine() -> str:
    env = os.environ.get
    return "openai" if env("OPENAI_API_KEY") else "openrouter" if env("OPENROUTER_API_KEY") else "codex" if shutil.which("codex") else "none"


def generate(engine, prompt, wh, out):
    """Returns (engine used, ok, message). A failing engine falls back to none, keeping its message."""
    name = auto_engine() if engine == "auto" else engine
    ok, msg = ENGINES[name](prompt, tuple(wh), out)
    if ok:
        return name, True, msg
    return "none", False, msg if name == "none" else f"{name}: {msg} {none_msg(Path(out).parent)}"
