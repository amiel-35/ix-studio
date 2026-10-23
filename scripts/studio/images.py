"""images: the image prompt, and the engines that can draw it.

An engine is one function `(prompt, size, out_path) -> (ok, message)`. None of them ever raises: a failure is a
message, and the piece is composed on a flat brand ground meanwhile. The image never carries text; the headline is
laid in HTML by compose.
"""

import base64
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

SUFFIX = ("No text, no letters, no words, no logos, no watermark. Leave calm, uncluttered space where the headline sits "
          "({layout} of the frame).")
NONE_MSG = ("No image generator available: set OPENAI_API_KEY (your key) or install and log in to the Codex CLI "
            "(your ChatGPT plan), then rerun `studio image`. The piece is composed on a flat brand ground meanwhile.")


def build_prompt(brand, brief, variant) -> str:
    w, h = brief["size"]
    parts = [variant["image_prompt"].rstrip(". ") + ".",
             f"Format {w}x{h} ({brief['format']}).",
             f"Mood from the brand palette: background {brand['background']}, text {brand['text']}"
             + (f", accent {brand['accent']}" if brand["accent"] else "") + ".",
             f"Voice of the brand: {brand['voice']}." if brand["voice"] else "",
             f"Do not show: {'; '.join(brand['never'])}." if brand["never"] else "",
             SUFFIX.format(layout=variant["layout"])]
    return " ".join(p for p in parts if p)


def api_size(brief) -> str:
    w, h = brief["size"]
    return "1024x1024" if w == h else "1024x1536"


def openai(prompt, size, out):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return False, "OPENAI_API_KEY is not set."
    model = os.environ.get("STUDIO_IMAGE_MODEL", "gpt-image-1")
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
        try:
            detail = json.loads(err.read())["error"]["message"]
        except Exception:
            detail = err.reason
        return False, f"OpenAI refused the request (HTTP {err.code}): {detail}"
    except Exception as err:
        return False, f"OpenAI request failed: {err}"
    return True, f"drawn by OpenAI ({model})"


def codex(prompt, size, out):
    exe = shutil.which("codex")
    if not exe:
        return False, "The codex CLI is not on PATH."
    out = Path(out).resolve()
    ask = (f"Generate one image with your image generation tool from this brief, then save it exactly at {out} "
           f"(PNG, size close to {size}). Do not write anything else to disk. Brief: {prompt}")
    try:
        r = subprocess.run([exe, "exec", "--skip-git-repo-check", ask], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, cwd=out.parent, timeout=600)
    except Exception as err:
        return False, f"codex failed: {err}"
    if out.exists():
        return True, "drawn by Codex (your ChatGPT plan)"
    return False, f"codex ran (exit {r.returncode}) but saved no image at {out.name}: {(r.stderr or r.stdout).strip()[-200:]}"


def none(prompt, size, out):
    return False, NONE_MSG


ENGINES = {"openai": openai, "codex": codex, "none": none}


def auto_engine() -> str:
    return "openai" if os.environ.get("OPENAI_API_KEY") else "codex" if shutil.which("codex") else "none"


def generate(engine, prompt, size, out):
    """Returns (engine used, ok, message). A failing engine falls back to none, keeping its message."""
    name = auto_engine() if engine == "auto" else engine
    ok, msg = ENGINES[name](prompt, size, out)
    if ok:
        return name, True, msg
    return "none", False, msg if name == "none" else f"{name}: {msg} {NONE_MSG}"
