"""dossier: write a piece's brand.md from an existing brandkit dossier.

Reads through `brandkit get` (the way any downstream module does), takes the confirmed values (the to_confirm ones only when asked,
marked `(to confirm: source)`), and lists what is missing or left out as comment lines instead of inventing it.
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


def marker(r):
    origin = (r.get("source") or {}).get("origin", "")
    return f" (to confirm: {origin})" if origin else " (to confirm)"


def scalar(dossier, path, inc, left):
    """(value, marker): confirmed values as they are, to_confirm ones only with `inc`, marked; else (None, "")."""
    r = get(dossier, path)
    if r.get("status") not in OK or r.get("value") in (None, "", []):
        return None, ""
    if r["status"] == "to_confirm":
        left.append(path)
        return (r["value"], marker(r)) if inc else (None, "")
    return r["value"], ""


def items(dossier, path, inc, left, need=(), look=None):
    """Rows of a list; a to_confirm field is kept only with `inc` (its marker in row["_tc"]). A row whose `need` field is left out is dropped."""
    out = []
    for it in get(dossier, path).get("items", []):
        if look and it.get("look") not in (None, "", look):
            continue
        row, tc, skipped, noted = {}, {}, False, False
        for k, v in it.items():
            if isinstance(v, dict) and "status" in v:
                if v["status"] == "to_confirm" and path != "looks":  # a look's statuses are structural: which look is master
                    if not noted:
                        left.append(f"{path}[{it.get('look') or ''} {v.get('value')}]")
                        noted = True
                    if not inc:
                        skipped = skipped or k in need
                        continue
                    tc[k] = marker(v)
                if v["status"] in OK and v.get("value") is not None:
                    row[k] = v["value"]
            else:
                row[k] = v
        if not skipped:
            out.append({**row, "_tc": tc})
    return out


def pick_look(dossier, look):
    """The look whose colours, fonts and logo are kept (None: the dossier has no looks)."""
    ls = items(dossier, "looks", True, [])
    ids = [x["id"] for x in ls if x.get("id")]
    if look:
        if ids and look not in ids:
            raise StudioError(f"unknown look {look!r}: the dossier has {', '.join(ids)}")
        return look
    masters = [x["id"] for x in ls if x.get("master") is True and x.get("id")]
    if len(masters) == 1:
        return masters[0]
    if len(ids) == 1:
        return ids[0]
    if ids:
        raise StudioError(f"the dossier names several looks and none is the master: {', '.join(ids)}. Rerun with --look <id>")
    return None


def first(row):
    return next(iter(row["_tc"].values()), "")


def brand_md(dossier, piece_dir, look=None, include_unconfirmed=False) -> tuple:
    """(text of brand.md, names of what is missing, what was left out as unconfirmed, or imported marked with `include_unconfirmed`).
    The dossier's references and web image evidence are never written."""
    inc, soft, kv, mk = include_unconfirmed, [], {}, {}
    look = pick_look(dossier, look)

    def put(k, v, m="", force=False):
        if v and (force or k not in kv):
            kv[k], mk[k] = v, m

    put("name", *scalar(dossier, "identity.name", inc, soft))
    put("slogan", *scalar(dossier, "promise.tagline", inc, soft))
    if "slogan" not in kv:
        put("slogan", *scalar(dossier, "promise.signature_line", inc, soft))
    cols = items(dossier, "colours", inc, soft, ("hex", "role"), look)
    for c in cols:
        if c.get("hex") and c.get("role") in ("background", "text", "accent"):
            put(c["role"], c["hex"], first(c))
    for c in cols:
        used = [x.lower() for x in [kv.get(k, "") for k in ("background", "text", "accent")] + kv.get("extra colours", "").split(", ")]
        if c.get("hex") and c["hex"].lower() not in used:
            put("extra colours", ", ".join(filter(None, [kv.get("extra colours"), c["hex"]])), mk.get("extra colours") or first(c), True)
    for t in items(dossier, "typography", inc, soft, ("family", "role"), look):
        if t.get("family"):
            put("headline font" if t.get("role") in ("headings", "headline", "display") else "body font", t["family"], first(t))
    for lg in items(dossier, "logo", inc, soft, ("file",), look):
        f = Path(dossier) / lg.get("file", "") if lg.get("file") else None
        if f and f.exists():
            put("logo", os.path.relpath(f, piece_dir), lg["_tc"].get("file", ""))
    (traits, m1), (reg, m2) = scalar(dossier, "voice.traits", inc, soft), scalar(dossier, "voice.register", inc, soft)
    put("voice", "; ".join(filter(None, [", ".join(traits) if traits else "", reg or ""])), m1 or m2)
    (never, m1), (dont, m2) = scalar(dossier, "voice.banned_words", inc, soft), scalar(dossier, "imagery.dont", inc, soft)
    put("never", "; ".join(never or []), m1)
    put("never show", "; ".join(dont or []), m2)
    style, m = scalar(dossier, "imagery.style", inc, soft)
    put("notes", f"imagery: {style}" if style else "", m)
    wanted = ["name", "background", "text", "accent", "headline font", "body font", "logo", "voice", "never"]
    miss = [k for k in wanted if k not in kv]
    lines = [f"# Brand, from the dossier {Path(dossier).name}", ""]
    lines += [f"- {k}: {v}{mk[k]}" for k, v in kv.items()]
    if miss:
        lines += ["", f"# missing: {', '.join(miss)}"]
    if soft:
        lines += ["# imported unconfirmed, marked (to confirm): " if inc else "# left out, to confirm in the dossier (rerun with --include-unconfirmed to take them): "]
        lines[-1] += ", ".join(soft)
    return "\n".join(lines) + "\n", miss, soft
