"""brand.md and MOTION.md, generated from brand.json (R13), with the sections of brand-intake so that the skills
already installed can read them. A missing value is written "ASK ME"; an inferred value not yet confirmed carries
"(inferred, to confirm: explore only)" (R6). These files are never edited by hand.
"""

from model import DEFAULT_LOOK

BANNER = "<!-- Generated from brand.json by ix-studio brandkit. Do not edit: change brand.json (or its sources) and export again. -->"
ASK = "ASK ME"


def fmt(v, joiner=", "):
    """One value, ready to print, with its status made visible."""
    if not isinstance(v, dict):
        return ASK
    st = v.get("status")
    if st in ("ask", "to_create", "rejected", "reserved") or v.get("value") in (None, "", []):
        return ASK + (" (to create)" if st == "to_create" else "")
    val = v["value"]
    if isinstance(val, list):
        val = joiner.join(str(x) for x in val)
    if st == "to_confirm":
        return f"{val} (inferred, to confirm: explore only)"
    return str(val)


def raw(v):
    """A value's text without its status tag; ASK ME when missing."""
    if not isinstance(v, dict) or v.get("status") not in ("confirmed", "to_confirm") or v.get("value") in (None, "", []):
        return ASK
    val = v["value"]
    return ", ".join(str(x) for x in val) if isinstance(val, list) else str(val)


def tag(*vs):
    """One tag per line: the line's values are inferred and wait for confirmation."""
    return " (inferred, to confirm: explore only)" if any(isinstance(v, dict) and v.get("status") == "to_confirm" for v in vs) else ""


def master_look(doc):
    items = doc.get("looks", {}).get("items", [])
    for it in items:
        m = it.get("master", {})
        if m.get("value") is True:
            return it["id"], m.get("status")
    if not items:
        return DEFAULT_LOOK, "confirmed"
    return None, "ask"


def look_items(doc, rubric, look):
    return [it for it in doc.get(rubric, {}).get("items", []) if it.get("look", DEFAULT_LOOK) == look]


def several_looks_line(doc):
    looks = doc.get("looks", {}).get("items", [])
    names = "; ".join(f"{it['id']} ({raw(it.get('name'))})" for it in looks)
    return f"{ASK}: several looks were found ({names}). Which one is the master look?"


def colour_lines(doc, look, with_role=True):
    items = look_items(doc, "colours", look)
    if not items:
        return [f"- {ASK}" + (" (to create)" if doc["colours"].get("status") == "to_create" else "")]
    out = []
    for it in items:
        share = f", share {round(float(it['share']['value']) * 100)} %" if it.get("share", {}).get("value") not in (None, "") else ""
        name = f" {it['name']['value']}" if it.get("name", {}).get("value") else ""
        t = tag(it.get("hex"), it.get("role"))
        out.append(f"- {raw(it.get('hex'))}{name}: {raw(it.get('role'))}{share}{t}" if with_role else f"- {raw(it.get('hex'))}{t}")
    return out


def type_lines(doc, look):
    items = look_items(doc, "typography", look)
    if not items:
        return [f"- {ASK}" + (" (to create)" if doc["typography"].get("status") == "to_create" else "")]
    out = []
    for it in items:
        sizes = raw(it.get("sizes")) if it.get("sizes") else ASK
        t = tag(it.get("family"), it.get("role"), it.get("sizes"), it.get("files"))
        out.append(f"- {raw(it.get('family'))}, for {raw(it.get('role'))}. Sizes: {sizes}. Files: {raw(it.get('files'))}. Licence: {raw(it.get('licence'))}{t}")
    return out


def logo_lines(doc, look):
    items = look_items(doc, "logo", look)
    out = [f"- {raw(it.get('file'))} ({raw(it.get('format'))}{', ' + raw(it.get('variant')) if it.get('variant') else ''}){tag(it.get('file'))}" for it in items]
    for g in doc.get("logo", {}).get("gaps", []):
        if g.get("look") == look:
            out.append(f"- Vector logo: {ASK}")
    return out or [f"- {ASK}"]


def never_list(doc):
    out = []
    for path in ("motion.never", "imagery.dont"):
        v = doc["motion"]["never"] if path == "motion.never" else doc["imagery"]["dont"]
        if v.get("status") in ("confirmed", "to_confirm") and v.get("value"):
            tag = " (inferred, to confirm)" if v["status"] == "to_confirm" else ""
            out += [f"{x}{tag}" for x in v["value"]]
    for it in doc.get("bans", {}).get("items", []):
        out.append(f"{fmt(it.get('rule'))} ({fmt(it.get('origin'))})")
    return out


def brand_md(doc):
    look, _ = master_look(doc)
    i, a, p, vo = doc["identity"], doc["audience"], doc["promise"], doc["voice"]
    lines = [BANNER, "", "# Brand", "",
             "## Name and what we do", f"- Name: {fmt(i['name'])}", f"- What we do: {fmt(i['one_liner'])}", "",
             "## Audience", f"- Who: {fmt(a['who'])}", f"- Situation: {fmt(a['situation'])}", "",
             "## What we promote (with the real link)", f"- Offer: {fmt(i['offer'])}", f"- Links: {fmt(i['links'])}", "",
             "## The feeling", f"- Feeling: {fmt(vo['traits'])}", f"- Register: {fmt(vo['register'])}",
             f"- Address: {fmt(vo['address'])}", f"- Tagline (exact words): {fmt(p['tagline'])}",
             f"- Signature line (exact words): {fmt(p['signature_line'])}", f"- Key messages (exact words): {fmt(p['key_messages'], ' / ')}", "",
             "## Assets"]
    if look is None:
        lines.append(several_looks_line(doc))
        for it in doc["looks"]["items"]:
            lines += [f"Look {it['id']} (not chosen):"] + colour_lines(doc, it["id"])
    else:
        lines.append("Colours (hex; typed by me, read from a design-system skill, or inferred from a named source):")
        lines += colour_lines(doc, look)
        lines.append("Fonts:")
        lines += [f"- {raw(it.get('family'))} ({raw(it.get('role'))}){tag(it.get('family'))}" for it in look_items(doc, "typography", look)] or [f"- {ASK}"]
        lines.append("Logo files:")
        lines += logo_lines(doc, look)
    nev = never_list(doc)
    lines += ["", "## Never"] + ([f"- {x}" for x in nev] if nev else [f"- {ASK}"])
    lines += ["", f"_Dossier version {doc['meta']['version']}{' (draft)' if doc['meta'].get('draft') else ''}. Provenance of every value: brand.json._", ""]
    return "\n".join(lines)


def motion_md(doc):
    look, _ = master_look(doc)
    m, im = doc["motion"], doc["imagery"]
    lines = [BANNER, "", "# MOTION", ""]
    lines += ["## 1. Colours and what each one is for"]
    lines += [several_looks_line(doc)] if look is None else colour_lines(doc, look)
    lines += ["", "## 2. Fonts and type sizes"]
    lines += [several_looks_line(doc)] if look is None else type_lines(doc, look)
    lines += ["", "## 3. Timing",
              f"- Coming in: {fmt(m['entrances'])}", f"- Holding: {fmt(m['holds'])}", f"- Leaving: {fmt(m['exits'])}",
              f"- Tempo: {fmt(m['tempo'])}",
              "", "## 4. How things move",
              f"- Frame rate: {fmt(m['frame_rate'])}", f"- Easing: {fmt(m['easing'])}",
              "", "## 5. Texture and finish",
              f"- {fmt(m['texture'])}", f"- Imagery: {fmt(im['style'])}"]
    nev = never_list(doc)
    lines += ["", "## 6. Never"]
    lines += [f"- {x}" for x in nev[:8]] if nev else [f"- {ASK}"]
    if 0 < len(nev) < 5:
        lines.append(f"- {ASK} ({5 - len(nev)} more, if there are)")
    lines += ["", "## 7. One example, shot by shot", f"{fmt(m['example'])}", ""]
    return "\n".join(lines)
