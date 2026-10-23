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

from ui import cli

SUFFIX = ("No text, no letters, no words, no logos, no watermark. Leave calm, uncluttered space where the headline sits "
          "({layout} of the frame).")
SIGNS = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")


def none_msg(d) -> str:
    return (f"No image generator available: set OPENAI_API_KEY (your key) or install and log in to the Codex CLI "
            f"(your ChatGPT plan), then run `{cli(d, 'image')}`, and rerun compose and check after. "
            f"The piece is composed on a flat brand ground meanwhile.")


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
    last = next((x for x in reversed((r.stderr or "").strip().splitlines()) if x.strip()), "")
    return False, f"codex ran (exit {r.returncode}) but saved no usable PNG or JPEG image" + (f": {last.strip()[:200]}" if last else ".")


def none(prompt, size, out):
    return False, none_msg(Path(out).parent)


ENGINES = {"openai": openai, "codex": codex, "none": none}


def auto_engine() -> str:
    return "openai" if os.environ.get("OPENAI_API_KEY") else "codex" if shutil.which("codex") else "none"


def generate(engine, prompt, size, out):
    """Returns (engine used, ok, message). A failing engine falls back to none, keeping its message."""
    name = auto_engine() if engine == "auto" else engine
    ok, msg = ENGINES[name](prompt, size, out)
    if ok:
        return name, True, msg
    return "none", False, msg if name == "none" else f"{name}: {msg} {none_msg(Path(out).parent)}"
