"""engines: the engines the studio draws and writes with, and the key of the text engine. They live in the configuration of the person
(`engines.json` in $STUDIO_CONFIG_DIR, else $XDG_CONFIG_HOME/ix-studio, else ~/.config/ix-studio), never in a project and never in the repository.
A key is read here and sent to its engine; it is never given back: `view` only says whether one is saved."""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

IMAGE_ENGINES = ("auto", "openai", "openrouter", "codex", "none")  # those of scripts/studio image
TEXT_ENGINES = ("claude", "openrouter")
OPENROUTER_MODEL = "anthropic/claude-sonnet-4.5"
OPENROUTER_URL = "https://openrouter.ai/api/v1"  # STUDIO_OPENROUTER_URL changes it (the tests give a local one)


def config_file() -> Path:
    base = os.environ.get("STUDIO_CONFIG_DIR") or Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ix-studio"
    return Path(base) / "engines.json"


def load() -> dict:
    try:
        data = json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def image_engine() -> str:
    """STUDIO_IMAGE_ENGINE, else the choice saved, else auto."""
    return os.environ.get("STUDIO_IMAGE_ENGINE") or load().get("image_engine") or "auto"


def text_engine() -> str:
    """STUDIO_TEXT_ENGINE, else the choice saved, else claude."""
    return os.environ.get("STUDIO_TEXT_ENGINE") or load().get("text_engine") or "claude"


def openrouter_key() -> str:
    return load().get("openrouter_key") or os.environ.get("OPENROUTER_API_KEY") or ""


def openrouter_model() -> str:
    return load().get("openrouter_model") or OPENROUTER_MODEL


def view() -> dict:
    """What the interface may show: the engines, the model, and whether a key is saved. Never the key."""
    return {"image_engine": image_engine(), "text_engine": text_engine(), "openrouter_model": openrouter_model(), "key_saved": bool(openrouter_key())}


def save(patch: dict) -> None:
    """Keep the choices named in `patch` (image_engine, text_engine, openrouter_model, openrouter_key; an empty key forgets it). ValueError if one does not hold."""
    cfg = load()
    for k, allowed in (("image_engine", IMAGE_ENGINES), ("text_engine", TEXT_ENGINES)):
        if patch.get(k) is not None:
            if patch[k] not in allowed:
                raise ValueError(f"{k}: one of {', '.join(allowed)}")
            cfg[k] = patch[k]
    for k in ("openrouter_model", "openrouter_key"):
        if patch.get(k) is not None:
            if not isinstance(patch[k], str):
                raise ValueError(f"{k}: a text")
            if patch[k].strip():
                cfg[k] = patch[k].strip()
            else:
                cfg.pop(k, None)
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = f.with_name(f.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # readable by the person alone
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, f)


def openrouter_answer(prompt: str, model=None, timeout=300):
    """One question to OpenRouter (the API compatible with OpenAI's): (code, text, error), code 0 when text is the answer."""
    key = openrouter_key()
    if not key:
        return 1, "", "OpenRouter : aucune clé enregistrée (Réglages)"
    body = {"model": model or openrouter_model(), "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(os.environ.get("STUDIO_OPENROUTER_URL", OPENROUTER_URL).rstrip("/") + "/chat/completions", method="POST",
                                 data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as err:
        return 1, "", f"OpenRouter a refusé la demande (HTTP {err.code})"
    except Exception as err:
        return 1, "", f"OpenRouter ne répond pas : {type(err).__name__}"
    try:
        return 0, data["choices"][0]["message"]["content"] or "", ""
    except (KeyError, IndexError, TypeError):
        return 1, "", "OpenRouter a répondu sans texte"
