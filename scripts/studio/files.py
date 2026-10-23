"""files: read and check the plain files of a piece folder (brand.md, brief.md, variants/, pick.json, ...).

Nothing here renders anything. Every problem is a StudioError with a sentence a person can act on (exit 2).
"""

import json
import re
from datetime import date
from pathlib import Path

from colour import hex6


class StudioError(Exception):
    pass


FORMATS = {"post-4x5": (1080, 1350), "post-1x1": (1080, 1080), "story": (1080, 1920), "poster-a3": (1240, 1754)}
LAYOUTS = ("top", "bottom", "center")
GROUNDS = ("background", "text", "accent")
GENERIC_FONTS = ("serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                 "georgia", "times new roman", "arial", "helvetica", "inherit")
BRAND_KEYS = ("name", "background", "text", "accent", "extra colours", "headline font", "body font", "logo", "voice", "never", "notes")
BRIEF_KEYS = ("objective", "audience", "message", "format", "fixed", "cta", "language")
VARIANT_KEYS = ("mandate", "default", "headline", "image_prompt", "layout", "ground", "why")
FONT = re.compile(r"[\w .'-]+")
HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})")


def today() -> str:
    return date.today().isoformat()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except ValueError as err:
        raise StudioError(f"{path}: not valid JSON ({err})")


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_kv(text: str) -> dict:
    """`key: value` lines; blank lines, `#` lines and a `- ` bullet prefix are tolerated; keys lowercase."""
    out = {}
    for line in text.splitlines():
        s = re.sub(r"^[-*]\s+", "", line.strip())
        if not s or s.startswith("#") or ":" not in s:
            continue
        k, v = s.split(":", 1)
        out[k.strip().lower()] = v.strip()
    return out


def _kv_file(d, name, hint):
    p = Path(d) / name
    if not p.exists():
        raise StudioError(f"{p} not found: {hint}")
    return parse_kv(p.read_text(encoding="utf-8"))


def _need(kv, name, keys):
    miss = [k for k in keys if not kv.get(k)]
    if miss:
        raise StudioError(f"{name}: missing {', '.join(miss)} (write it as `{miss[0]}: ...`)")


def load_brand(d) -> dict:
    kv = _kv_file(d, "brand.md", "write about ten `key: value` lines, or run `brand --from-dossier <brandkit dir>`")
    _need(kv, "brand.md", ("name", "background", "text"))
    extras = [x.strip() for x in kv.get("extra colours", "").split(",") if x.strip()]
    for k, v in [(k, kv.get(k)) for k in ("background", "text", "accent")] + [("extra colours", x) for x in extras]:
        if v and not HEX.fullmatch(v):
            raise StudioError(f"brand.md: {k} must be a hex colour like #1e2a24, got {v!r}")
    for k in ("headline font", "body font"):
        if kv.get(k) and not FONT.fullmatch(kv[k]):
            raise StudioError(f"brand.md: {k} must be a font name (letters, digits, spaces, . ' -), got {kv[k]!r}")
    b = {"name": kv["name"], "background": hex6(kv["background"]), "text": hex6(kv["text"]),
         "accent": hex6(kv["accent"]) if kv.get("accent") else "", "extras": [hex6(x) for x in extras],
         "hfont": kv.get("headline font", ""), "bfont": kv.get("body font", ""), "logo": kv.get("logo", ""),
         "voice": kv.get("voice", ""), "never": [x.strip() for x in kv.get("never", "").replace(",", ";").split(";") if x.strip()],
         "notes": kv.get("notes", ""), "other": {k: v for k, v in kv.items() if k not in BRAND_KEYS}}
    if b["logo"] and not (Path(d) / b["logo"]).exists():
        b["logo_missing"] = True
    return b


def palette(b) -> list:
    return [c for c in [b["background"], b["text"], b["accent"], *b["extras"]] if c]


def font_css(name: str, generic: str) -> str:
    return f"'{name}',{generic}" if name else generic


def load_brief(d) -> dict:
    kv = _kv_file(d, "brief.md", "write it as `key: value` lines (objective, audience, message, ...)")
    _need(kv, "brief.md", ("objective", "audience", "message"))
    fmt = kv.get("format", "post-4x5")
    if fmt not in FORMATS:
        raise StudioError(f"brief.md: format must be one of {', '.join(FORMATS)}, got {fmt!r}")
    return {**{k: kv.get(k, "") for k in BRIEF_KEYS}, "format": fmt, "size": FORMATS[fmt],
            "other": {k: v for k, v in kv.items() if k not in BRIEF_KEYS}}


def load_variants(d) -> list:
    files = sorted((Path(d) / "variants").glob("*.json"), key=lambda p: (len(p.stem), p.stem))
    out = []
    for p in files:
        v = read_json(p)
        if not isinstance(v, dict):
            raise StudioError(f"{p.name}: must be a JSON object")
        for k in VARIANT_KEYS:
            if k not in v or v[k] in ("", None):
                raise StudioError(f"{p.name}: missing key {k!r}")
        for k in ("headline", "image"):
            if not isinstance(v["default"], dict) or not v["default"].get(k):
                raise StudioError(f"{p.name}: key 'default' needs {k!r}")
        if v["layout"] not in LAYOUTS:
            raise StudioError(f"{p.name}: key 'layout' must be one of {', '.join(LAYOUTS)}")
        if v["ground"] not in GROUNDS:
            raise StudioError(f"{p.name}: key 'ground' must be one of {', '.join(GROUNDS)}")
        out.append({"subline": "", **v, "id": p.stem})
    if len(out) < 2:
        raise StudioError(f"variants/: {len(out)} variant(s), need at least 2 (v1.json, v2.json, ...)")
    return out


def load_pick(d):
    return read_json(Path(d) / "pick.json")


def picked(d, variants):
    """(variant, headline) of the pick, or (None, None)."""
    pk = load_pick(d)
    if not pk:
        return None, None
    v = next((x for x in variants if x["id"] == pk["variant"]), None)
    if not v:
        raise StudioError(f"pick.json names {pk['variant']!r}, which is not in variants/")
    return v, pk.get("headline") or v["headline"]


def image_file(d):
    for n in ("image.png", "image.jpg"):
        if (Path(d) / n).exists():
            return n
    return None


def ground_hex(b, name: str) -> str:
    return b[name] or b["text"]
