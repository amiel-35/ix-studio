"""Invariants a dossier must hold before it can be validated (annex C, C1 to C5 and C8), and the read a
downstream module makes (C11). A failure is a bug in an adapter or the fusion, never something to paper over.
"""

from fuse import iter_values
from model import CONFIDENCE, LISTS, SCALARS, STATUSES, get_path

FILLED = ("confirmed", "to_confirm")


def check(doc, evidence):
    errors = []
    ev = {e["id"]: e for e in evidence}
    for path, v in iter_values(doc):
        st = v.get("status")
        if st == "reserved":
            continue
        if st not in STATUSES and st != "confirmed_with_gaps":
            errors.append(f"C1 {path}: unknown status {st!r}")
            continue
        src = v.get("source") or {}
        if not (src.get("type") and src.get("origin") and src.get("at")):
            errors.append(f"C1/C2 {path}: incomplete source {src}")
        if st in FILLED:
            if v.get("value") in (None, "", []):
                errors.append(f"C1 {path}: status {st} without a value")
            if src.get("type") == "none":
                errors.append(f"C2 {path}: a value without an origin")
            if src.get("type") == "inferred":
                if v.get("confidence") not in CONFIDENCE:
                    errors.append(f"R1 {path}: inferred without a confidence")
                if not v.get("evidence"):
                    errors.append(f"R1 {path}: inferred without evidence")
                for e in v.get("evidence", []):
                    if e not in ev:
                        errors.append(f"R1 {path}: evidence {e} missing from evidence.json")
                if st == "confirmed" and not v.get("confirmed"):
                    errors.append(f"C4 {path}: inferred value marked confirmed without the user's confirmation")
        if st in ("ask", "to_create") and v.get("value") not in (None,) and "items" not in v:
            errors.append(f"C5 {path}: {st} but carries a value")
    for e in evidence:
        if e["kind"] == "web_image" and (e.get("kept") or e.get("file")):
            errors.append(f"C8 {e['id']}: an image found on the web was kept")
        if e["kind"] in ("web_image", "page", "video") and not (e.get("where") and e.get("at") and e.get("ownership")):
            errors.append(f"C8 {e['id']}: address, date or ownership missing")
    return errors


def read(doc, path, look=None):
    """What a downstream module receives (4.3, C11): a value with its status and provenance, or only a status."""
    if path in LISTS:
        r = doc.get(path, {})
        items = [it for it in r.get("items", []) if look is None or it.get("look") == look]
        if not items:
            return {"path": path, "status": r.get("status", "ask"), "missing": True,
                    "say": "no value: ask the user or stop. Never fill it in."}
        out = []
        for it in items:
            row = {}
            for k, v in it.items():
                row[k] = _leaf(v) if isinstance(v, dict) and "status" in v else v
            out.append(row)
        return {"path": path, "status": r.get("status"), "items": out}
    if path not in SCALARS and path != "signature":
        return {"path": path, "error": "unknown field"}
    v = doc["meta"]["language"] if path == "meta.language" else get_path(doc, path)
    return {"path": path, **_leaf(v)}


def _leaf(v):
    st = v.get("status")
    if st not in FILLED:
        return {"status": st, "missing": True, "say": "no value: ask the user or stop. Never fill it in."}
    out = {"status": st, "value": v["value"], "source": v["source"]}
    if st == "to_confirm":
        out["use"] = "explore only (a divergence variant), never a final deliverable without saying so (R6)"
        out["confidence"] = v.get("confidence")
    return out
