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


FORMATS = {"post-4x5": (1080, 1350), "post-1x1": (1080, 1080), "story": (1080, 1920), "poster-a3": (1240, 1754),
           "poster-3x2": (1800, 1200), "linkedin": (1200, 627)}
LAYOUTS = ("side", "stack", "ground", "overlay-top", "overlay-bottom")
LAYOUT_ALIASES = {"top": "overlay-top", "bottom": "overlay-bottom", "center": "ground"}
LOGO_POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")
GROUNDS = ("background", "text", "accent")
GENERIC_FONTS = ("serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif",
                 "georgia", "times new roman", "arial", "helvetica", "inherit")
BRAND_KEYS = ("name", "background", "text", "accent", "extra colours", "headline font", "body font", "logo", "logo position",
              "headline colour", "voice", "never", "never show", "notes", "slogan")
BRIEF_KEYS = ("objective", "audience", "message", "format", "fixed", "cta", "language")
VARIANT_KEYS = ("mandate", "default", "headline", "image_prompt", "layout", "ground", "why")
FONT = re.compile(r"[\w .'-]+")
UNCONFIRMED = re.compile(r"\s*\(\s*(?:to confirm|à confirmer)\s*(?:[:;]\s*(.*?))?\s*\)\s*$", re.I)
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
    unconfirmed = {}
    for k, v in kv.items():
        m = UNCONFIRMED.search(v)
        if m:
            unconfirmed[k], kv[k] = (m.group(1) or "").strip(), v[:m.start()].strip()
    _need(kv, "brand.md", ("name", "background", "text"))
    extras = [x.strip() for x in kv.get("extra colours", "").split(",") if x.strip()]
    for k, v in [(k, kv.get(k)) for k in ("background", "text", "accent", "headline colour")] + [("extra colours", x) for x in extras]:
        if v and not HEX.fullmatch(v):
            raise StudioError(f"brand.md: {k} must be a hex colour like #1e2a24, got {v!r}")
    for k in ("headline font", "body font"):
        if kv.get(k) and not FONT.fullmatch(kv[k]):
            raise StudioError(f"brand.md: {k} must be a font name (letters, digits, spaces, . ' -), got {kv[k]!r}")
    pos = kv.get("logo position", "bottom-right").lower()
    if pos not in LOGO_POSITIONS:
        raise StudioError(f"brand.md: logo position must be one of {', '.join(LOGO_POSITIONS)}, got {pos!r}")
    holder = kv.get("logo", "").lower() == "placeholder"
    b = {"name": kv["name"], "background": hex6(kv["background"]), "text": hex6(kv["text"]),
         "accent": hex6(kv["accent"]) if kv.get("accent") else "", "extras": [hex6(x) for x in extras],
         "hfont": kv.get("headline font", ""), "bfont": kv.get("body font", ""), "logo": "" if holder else kv.get("logo", ""),
         "logo_placeholder": holder, "logo_position": pos, "headline_colour": hex6(kv["headline colour"]) if kv.get("headline colour") else "",
         "never_show": [x.strip() for x in kv.get("never show", "").split(";") if x.strip()], "voice": kv.get("voice", ""), "never": [x.strip() for x in kv.get("never", "").replace(",", ";").split(";") if x.strip()],
         "notes": kv.get("notes", ""), "slogan": " ".join(kv.get("slogan", "").split()), "unconfirmed": unconfirmed, "other": {k: v for k, v in kv.items() if k not in BRAND_KEYS}}
    if b["logo"] and not (Path(d) / b["logo"]).exists():
        b["logo_missing"] = True
    return b


def palette(b) -> list:
    return [c for c in [b["background"], b["text"], b["accent"], b["headline_colour"], *b["extras"]] if c]


def never_checkable(entries) -> list:
    return [w for w in entries if len(w.split()) <= 3]


def never_hits(entries, text: str) -> list:
    """The checkable never entries found in the text (guards only on the sides that are word characters)."""
    def pat(w):
        return (r"(?<!\w)" if w[0].isalnum() or w[0] == "_" else "") + re.escape(w) + (r"(?!\w)" if w[-1].isalnum() or w[-1] == "_" else "")
    return [w for w in never_checkable(entries) if re.search(pat(w), text, re.I)]


def norm_layout(x):
    return LAYOUT_ALIASES.get(x, x)


def parse_format(fmt: str):
    if fmt in FORMATS:
        return FORMATS[fmt]
    m = re.fullmatch(r"(\d{2,4})x(\d{2,4})", fmt)
    if m and all(200 <= int(x) <= 4000 for x in m.groups()):
        return int(m.group(1)), int(m.group(2))
    raise StudioError(f"brief.md: format must be one of {', '.join(FORMATS)}, or WxH like 1600x900 (each side 200 to 4000), got {fmt!r}")


def font_css(name: str, generic: str) -> str:
    return f"'{name}',{generic}" if name else generic


def load_brief(d) -> dict:
    kv = _kv_file(d, "brief.md", "write it as `key: value` lines (objective, audience, message, ...)")
    _need(kv, "brief.md", ("objective", "audience", "message"))
    fmt = kv.get("format", "post-4x5").strip().lower()
    return {**{k: kv.get(k, "") for k in BRIEF_KEYS}, "format": fmt, "size": parse_format(fmt),
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
        v["layout"] = norm_layout(v["layout"])
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
