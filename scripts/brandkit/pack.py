"""pack: the brand folder to download, one zip. brand.md (and MOTION.md), the logo, and a brand.json that keeps for every value its source
and its status (confirmed, to_confirm, ask). What is missing is written missing, never filled in. No agent here: it is read from the dossier."""

import io
import json
import zipfile
from pathlib import Path

import exports
from fuse import iter_values

STATUS = ("confirmed", "to_confirm")  # any other status (ask, to_create, rejected, reserved) is a value nobody gave


def facts(doc):
    """The values of the dossier as [{path, value, status, source}]; a value nobody gave has status "ask" and no value."""
    out = []
    for path, v in iter_values(doc):
        if v.get("status") in STATUS and v.get("value") not in (None, "", []):
            out.append({"path": path, "value": v["value"], "status": v["status"], "source": v.get("source")})
        else:
            out.append({"path": path, "value": None, "status": "ask", "source": None})
    return out


def logo_file(doc, root: Path):
    """The path of the first logo file that exists in the dossier folder, or None."""
    for it in doc.get("logo", {}).get("items", []):
        rel = (it.get("file") or {}).get("value")
        f = (root / rel) if rel else None
        if f and f.is_file() and not f.is_symlink() and f.resolve().is_relative_to(root.resolve()):
            return f
    return None


def pack(doc, root: Path) -> bytes:
    """The zip (bytes) of the brand folder of the dossier at `root`, from its merged `doc`."""
    rows = facts(doc)
    body = {"name": (doc.get("identity", {}).get("name") or {}).get("value"), "values": rows,
            "missing": [r["path"] for r in rows if r["status"] == "ask"]}
    logo = logo_file(doc, root)
    body["logo"] = f"logo{logo.suffix}" if logo else None  # None: no logo, written as missing
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("brand.md", exports.brand_md(doc))
        if (root / "MOTION.md").is_file():  # only when the dossier was exported with one
            z.writestr("MOTION.md", (root / "MOTION.md").read_bytes())
        if logo:
            z.writestr(body["logo"], logo.read_bytes())
        z.writestr("brand.json", json.dumps(body, indent=2, ensure_ascii=False) + "\n")
    return buf.getvalue()
