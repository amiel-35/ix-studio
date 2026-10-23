"""dossier: write a piece's brand.md from an existing brandkit dossier.

Reads through `brandkit get` (the way any downstream module does), takes only confirmed or to_confirm values, and
lists what is missing as a comment line instead of inventing it.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from files import StudioError

BRANDKIT = Path(__file__).resolve().parent.parent / "brandkit"
OK = ("confirmed", "to_confirm")


def get(dossier, path):
    r = subprocess.run([sys.executable, str(BRANDKIT), "get", str(dossier), path], capture_output=True, text=True)
    if r.returncode not in (0, 3):  # 3 = the value is missing: not a failure
        raise StudioError(f"brandkit get {path}: {(r.stderr or r.stdout).strip()}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"missing": True}


def scalar(dossier, path, soft):
    r = get(dossier, path)
    if r.get("status") not in OK or r.get("value") in (None, "", []):
        return None
    if r["status"] == "to_confirm":
        soft.append(path)
    return r["value"]


def items(dossier, path, soft):
    out = []
    for it in get(dossier, path).get("items", []):
        row = {}
        for k, v in it.items():
            if isinstance(v, dict) and "status" in v:
                if v["status"] in OK and v.get("value") is not None:
                    row[k] = v["value"]
                    if v["status"] == "to_confirm" and path not in soft:
                        soft.append(path)
            else:
                row[k] = v
        out.append(row)
    return out


def brand_md(dossier, piece_dir) -> tuple:
    """(text of brand.md, names of what is missing)."""
    soft, kv = [], {}
    kv["name"] = scalar(dossier, "identity.name", soft)
    for c in items(dossier, "colours", soft):
        if c.get("hex") and c.get("role") in ("background", "text", "accent"):
            kv.setdefault(c["role"], c["hex"])
        elif c.get("hex"):
            kv["extra colours"] = ", ".join(filter(None, [kv.get("extra colours"), c["hex"]]))
    for t in items(dossier, "typography", soft):
        if t.get("family"):
            kv.setdefault("headline font" if t.get("role") in ("headings", "headline", "display") else "body font", t["family"])
    for lg in items(dossier, "logo", soft):
        f = Path(dossier) / lg.get("file", "") if lg.get("file") else None
        if f and f.exists():
            kv.setdefault("logo", os.path.relpath(f, piece_dir))
    traits = scalar(dossier, "voice.traits", soft)
    reg = scalar(dossier, "voice.register", soft)
    voice = "; ".join(filter(None, [", ".join(traits) if traits else "", reg or ""]))
    if voice:
        kv["voice"] = voice
    never = (scalar(dossier, "voice.banned_words", soft) or []) + (scalar(dossier, "imagery.dont", soft) or [])
    if never:
        kv["never"] = "; ".join(never)
    style = scalar(dossier, "imagery.style", soft)
    if style:
        kv["notes"] = f"imagery: {style}"
    wanted = ["name", "background", "text", "accent", "headline font", "body font", "logo", "voice", "never"]
    miss = [k for k in wanted if k not in kv]
    lines = [f"# Brand, from the dossier {Path(dossier).name}", ""]
    lines += [f"- {k}: {v}" for k, v in kv.items()]
    if miss:
        lines += ["", f"# missing: {', '.join(miss)}"]
    if soft:
        lines += [f"# to confirm in the dossier: {', '.join(soft)}"]
    return "\n".join(lines) + "\n", miss
