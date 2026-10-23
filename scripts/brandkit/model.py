"""The brand dossier's shape: which fields exist, what a value looks like, how sources rank.

Everything else in brandkit reads these tables. A field is either a scalar (one value, which may itself be a
list of strings) or a list rubric (items, each item a set of fields, each field a value).
"""

import hashlib
import json
import re
from datetime import date

SCHEMA = "ix-studio/brand@1"

STATUSES = ("confirmed", "to_confirm", "ask", "to_create", "rejected")
SOURCE_TYPES = ("typed", "skill", "inferred", "created")
CONFIDENCE = ("high", "medium", "low")
OWNERSHIP = ("official", "official_relayed", "probable", "uncertain")
EVIDENCE_KINDS = ("page", "file", "web_image", "video", "skill", "text")

# Priority between source types (R3): skill, then typed; a created value once validated counts as typed.
TYPE_RANK = {"skill": 0, "typed": 1, "created": 1, "inferred": 2}
# Inside "inferred" (R3): declared in a source file AND used on visible elements, then read on the rendered page,
# then sampled from an image, then taken from an image found on the web. "text" is a reading of the brand's own words.
INFER_RANK = {"declared_used": 0, "rendered": 1, "text": 1, "measured": 1, "image_sample": 2, "web_image": 3}
CONF_RANK = {"high": 0, "medium": 1, "low": 2, None: 1}
# Ownership classes that may feed the inference (R8). The others are kept as evidence only.
FEEDING = ("official", "official_relayed", "probable")

# Scalar fields. kind: "text" (one string) or "list" (a list of strings).
# verbatim: the brand's exact words, never rephrased. create: an empty field is "to_create" rather than "ask".
SCALARS = {
    "identity.name": {"kind": "text"},
    "identity.one_liner": {"kind": "text"},
    "identity.offer": {"kind": "text"},
    "identity.links": {"kind": "list"},
    "audience.who": {"kind": "text"},
    "audience.situation": {"kind": "text"},
    "promise.tagline": {"kind": "text", "verbatim": True},
    "promise.signature_line": {"kind": "text", "verbatim": True},
    "promise.key_messages": {"kind": "list", "verbatim": True},
    "voice.register": {"kind": "text"},
    "voice.address": {"kind": "text"},
    "voice.traits": {"kind": "list"},
    "voice.banned_words": {"kind": "list"},
    "voice.samples": {"kind": "list", "verbatim": True},
    "imagery.style": {"kind": "text"},
    "imagery.do": {"kind": "list"},
    "imagery.dont": {"kind": "list"},
    "motion.entrances": {"kind": "text"},
    "motion.holds": {"kind": "text"},
    "motion.exits": {"kind": "text"},
    "motion.easing": {"kind": "text"},
    "motion.tempo": {"kind": "text"},
    "motion.never": {"kind": "list"},
    # Not in annex A of the spec: added so that MOTION.md can be filled section for section (brand-intake).
    "motion.frame_rate": {"kind": "text"},
    "motion.texture": {"kind": "text"},
    "motion.example": {"kind": "text"},
    "meta.language": {"kind": "text"},
}

# List rubrics. key: what identifies an item inside a look. required: fields that become "ask" when absent.
# optional: fields left out when absent. merge: "tier" (the best source tier wins the whole look, R3/R4)
# or "union" (items accumulate). create: an empty rubric is "to_create" (the identity family makes it, D14).
LISTS = {
    "colours": {"key": "role", "required": ("hex", "role"), "optional": ("share", "name"), "merge": "tier", "create": True},
    "typography": {"key": "role", "required": ("family", "role", "files", "licence"), "optional": ("sizes", "weights"), "merge": "tier", "create": True},
    "logo": {"key": "variant", "required": ("file", "format"), "optional": ("variant", "background"), "merge": "tier", "create": True},
    "references": {"key": "url", "required": ("url", "grammar"), "optional": (), "merge": "union", "create": False},
    "bans": {"key": "rule", "required": ("rule", "origin"), "optional": (), "merge": "union", "create": False, "reserved": True},
    "looks": {"key": "id", "required": ("name", "kind"), "optional": ("summary",), "merge": "union", "create": False},
}

RESERVED = ("signature",)  # D3: a field kept for later, nothing more.
DEFAULT_LOOK = "brand"
VECTOR_FORMATS = ("svg", "pdf", "eps", "ai")

SECTIONS = ("identity", "audience", "promise", "voice", "imagery", "motion")


def today() -> str:
    return date.today().isoformat()


def fingerprint(value) -> str:
    """A stable id for a value, so a decision (confirm, reject) survives a re-merge."""
    return hashlib.sha1(json.dumps(norm(value), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]


def norm(value):
    if isinstance(value, str):
        v = value.strip()
        return v.lower() if re.fullmatch(r"#[0-9a-fA-F]{3,8}", v) else v
    if isinstance(value, list):
        return [norm(v) for v in value]
    if isinstance(value, dict):
        return {k: norm(v) for k, v in value.items()}
    return value


def evidence_id(kind: str, where: str) -> str:
    return "ev-" + hashlib.sha1(f"{kind}|{where}".encode()).hexdigest()[:8]


def missing(status: str, why: str, at: str | None = None) -> dict:
    """A value nobody provided. It carries a status and says who looked, never a value (R5)."""
    return {"value": None, "status": status, "source": {"type": "none", "origin": why, "at": at or today()}}


def hex_to_rgb(h: str):
    h = h.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(c * 2 for c in h[:3])
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hex_distance(a: str, b: str) -> float:
    try:
        return sum((x - y) ** 2 for x, y in zip(hex_to_rgb(a), hex_to_rgb(b))) ** 0.5
    except ValueError:
        return 999.0


def get_path(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def set_path(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = doc
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value
