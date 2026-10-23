"""The mechanical half of the inference adapter: facts collected on a site (collect.mjs) become an inferred source.

Only what a script can read without judgement goes here: colours really painted, with their role and share; the
typefaces really rendered per role; logo files; the page language. Tone, imagery, motion and bans need the model's
eyes and are written by the agent as a second inferred source, with their own evidence and a low or medium confidence.
"""

import os
import re

from model import hex_distance, today

NEAR = 10  # two colours closer than this (RGB distance) are the same colour read twice

# Names a UI kit or a site template gives its own palette and fonts. A colour declared only under such a name, or a
# template's default font, may be painted on the page without being the brand's: it comes out with a low confidence.
KIT_VAR = re.compile(r"^--(color-)?(slate|gray|grey|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|"
                     r"cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}$|^--(background|foreground|primary|"
                     r"primary-foreground|secondary|secondary-foreground|muted|muted-foreground|accent|accent-foreground|"
                     r"destructive|border|input|ring|card|card-foreground|popover|popover-foreground|chart-\d|sidebar[\w-]*|"
                     r"tw-[\w-]+|swiper-[\w-]+|wp--preset--color--[\w-]+|bs-[\w-]+)$", re.I)
KIT_FONTS = {"geist", "geist variable", "geist sans", "geist mono"}


def _near_any(h, hexes):
    return any(hex_distance(h, x) < NEAR for x in hexes)


def _grey(h):
    from model import hex_to_rgb
    r, g, b = hex_to_rgb(h)
    return max(r, g, b) - min(r, g, b) < 12


def from_site(facts, collect_dir, brand_dir, look=None, look_name=None, look_kind=None, ownership="official",
              given_by_user=True):
    url = facts.get("final_url") or facts["url"]
    at = (facts.get("at") or today())[:10]
    rel = os.path.relpath(collect_dir, brand_dir)
    ev = [{"id": "page", "kind": "page", "where": url, "at": at, "ownership": ownership,
           "ownership_given_by_user": given_by_user, "title": facts.get("title", ""), **({"look": look} if look else {})}]
    for f in facts.get("files", []):
        if f["kind"] == "screen":
            ev.append({"id": f["file"], "kind": "file", "where": f"{rel}/{f['file']}", "at": at, "kept": True,
                       "page": url, "note": f"screenshot {f.get('note', '')}"})
    values, ignored, not_found = [], [], list(facts.get("missing", []))
    used = [v for v in facts.get("vars", []) if v.get("used") and v.get("hex")]
    used_vars = {v["hex"] for v in used if not KIT_VAR.match(v["name"])}
    kit_vars = {v["hex"]: v["name"] for v in used if KIT_VAR.match(v["name"]) and v["hex"] not in used_vars}
    lk = {"look": look} if look else {}

    def colour(role, c, conf, why):
        rank = "declared_used" if _near_any(c["hex"], used_vars) else "rendered"
        kit = next((n for h, n in kit_vars.items() if hex_distance(h, c["hex"]) < NEAR), None)
        if kit and rank == "rendered" and c["hex"] not in ("#ffffff", "#000000"):
            conf, why = "low", f"{why}; declared only as {kit}, a UI kit's palette: may not be the brand's"
        values.append({"path": "colours", **lk, "item": {"hex": c["hex"], "role": role, "share": c.get("share")},
                       "confidence": conf, "evidence": ["page", "screen-01.png"] if any(e["id"] == "screen-01.png" for e in ev) else ["page"],
                       "rank": rank, "note": why})

    cols = facts.get("colours", {})
    taken = []
    grounds = [c for c in cols.get("ground", []) if c["share"] >= 0.08][:3]
    for i, c in enumerate(grounds):
        if _near_any(c["hex"], taken):
            continue
        colour("background" if i == 0 else f"background {i + 1}", c, "high" if c["share"] >= 0.25 else "medium",
               f"{round(c['share'] * 100)} % of the painted surface")
        taken.append(c["hex"])
    heads = [c for c in cols.get("heading", []) if c["share"] >= 0.3]
    for c in heads[:1]:
        colour("headings", c, "high" if c["share"] >= 0.6 else "medium", f"{round(c['share'] * 100)} % of heading characters")
        taken.append(c["hex"])
    texts = [c for c in cols.get("type", []) if c["share"] >= 0.15 and not _near_any(c["hex"], taken)]
    for c in texts[:1]:
        colour("text", c, "high" if c["share"] >= 0.4 else "medium", f"{round(c['share'] * 100)} % of body characters")
        taken.append(c["hex"])
    accents = [c for c in cols.get("accent", []) + cols.get("ground", [])[3:] + cols.get("type", [])
               if not _near_any(c["hex"], taken) and not _grey(c["hex"])]
    # a colour the stylesheet names and really paints outranks one only seen painted (a carousel, a partner's banner)
    tallied = set(facts.get("painted_hex", []))
    for v in facts.get("vars", []):
        if v.get("used") and v.get("hex") and not _grey(v["hex"]) and v["hex"] not in tallied and not _near_any(v["hex"], taken):
            accents.append({"hex": v["hex"], "share": None, "var": v["name"]})
    accents.sort(key=lambda c: not _near_any(c["hex"], used_vars))
    seen = []
    for c in accents:
        if _near_any(c["hex"], seen) or len(seen) >= 5:
            continue
        seen.append(c["hex"])
        why = f"declared as {c['var']} and painted (borders, icons, shapes)" if c.get("var") else "painted on buttons, links or small areas"
        colour("accent" if len(seen) == 1 else f"accent {len(seen)}", c, "medium" if len(seen) == 1 else "low", why)
    unused = [v for v in facts.get("vars", []) if not v.get("used")]
    if unused:
        ignored.append({"what": f"{len(unused)} CSS colour variables declared but painted on nothing visible "
                                f"(e.g. {', '.join(v['name'] for v in unused[:5])})",
                        "why": "a value declared but not used does not count (R3): often a template or a UI kit"})

    rendered = facts.get("rendered_fonts", {})
    faces = facts.get("font_faces", [])
    seen_fam = {}
    for role, label in (("heading", "headings"), ("body", "body"), ("ui", "interface")):
        fl = facts.get("fonts", {}).get(role, [])
        if not fl:
            continue
        top = fl[0]
        fam = top["family"]
        real = rendered.get(role, {})
        # a variable font reports its instance ("Archivo SemiBold"): the family is drawn if a face name starts with it
        if real and not any(r.lower().startswith(fam.lower()) or fam.lower().startswith(r.lower()) for r in real):
            # the stack's first family is not what the browser drew: trust the renderer, say so
            alt = max(real, key=real.get)
            ignored.append({"what": f"{role}: declared {fam!r}", "why": f"the browser rendered {alt!r} instead"})
            fam = alt
        if fam in seen_fam and role == "ui":
            continue
        seen_fam[fam] = True
        kit_font = fam.lower() in KIT_FONTS
        files = sorted({f["src"] for f in faces if f.get("src") and f["family"].lower() == fam.lower()})
        item = {"family": fam, "role": label, "sizes": ", ".join(top.get("sizes", [])),
                "weights": ", ".join(sorted({x["weight"] for x in fl if x["family"] == top["family"]}))}
        if files:
            item["files"] = files
        values.append({"path": "typography", **lk, "item": item, "rank": "rendered",
                       "confidence": "low" if kit_font else "high" if top.get("share", 0) >= 0.5 else "medium", "evidence": ["page"],
                       "note": f"{round(top.get('share', 0) * 100)} % of {role} characters"
                               + ("; the default font of a common site template: may not be the brand's" if kit_font else "")})
    drawn = {v["item"]["family"].lower() for v in values if v["path"] == "typography"}
    drawn |= {r.lower() for role in rendered.values() for r in role}
    declared_only = sorted({f["family"] for f in faces if f.get("family") and not any(
        d.startswith(f["family"].lower()) or f["family"].lower().startswith(d) for d in drawn)})
    if declared_only:
        ignored.append({"what": f"fonts declared in @font-face but not seen on text: {', '.join(declared_only[:6])}",
                        "why": "declared, not used (R3)"})

    logos = facts.get("logos", [])
    header = [l for l in logos if l.get("where", "").startswith("header")]
    for l in header[:2] + [l for l in logos if l.get("where") == "img"][:1]:
        fid = l["file"]
        ev.append({"id": fid, "kind": "file", "where": f"{rel}/{fid}", "at": at, "kept": True, "page": url,
                   "note": f"logo candidate, {l.get('where')} ({l['src'][:80]})"})
        values.append({"path": "logo", **lk, "item": {"file": f"{rel}/{fid}", "format": l["format"],
                                                      "variant": "header" if l.get("where", "").startswith("header") else "page"},
                       "rank": "rendered", "confidence": "high" if l["format"] == "svg" and l.get("where", "").startswith("header") else "medium",
                       "evidence": ["page", fid]})
    def icon_size(l):
        m = re.search(r"(\d+)x\d+", (l.get("note") or "") + " " + l.get("src", ""))
        return int(m.group(1)) if m else 0
    icons = sorted([l for l in logos if l.get("where") == "link"], key=lambda l: (l["format"] != "svg", -icon_size(l)))
    for l in icons[:1]:
        fid = l["file"]
        ev.append({"id": fid, "kind": "file", "where": f"{rel}/{fid}", "at": at, "kept": True, "page": url, "note": f"icon ({l.get('note')})"})
        values.append({"path": "logo", **lk, "item": {"file": f"{rel}/{fid}", "format": "favicon", "variant": f"site icon ({l['format']})"},
                       "rank": "rendered", "confidence": "low", "evidence": ["page", fid], "note": "site icon: a logo's nature, not a logo file to use as is"})
    if not header and not icons:
        not_found.append(f"no logo file found on {url}")

    if facts.get("lang"):
        values.append({"path": "meta.language", "value": facts["lang"].split("-")[0], "rank": "rendered", "confidence": "high", "evidence": ["page"]})
    if look and (look != "brand" or look_name):  # the main identity is implied; a named look is declared
        brand_look = look == "brand"
        values.append({"path": "looks", "item": {"id": look, "name": look_name or ("Brand identity" if brand_look else look),
                                                 "kind": look_kind or ("brand" if brand_look else "unknown"),
                                                 "summary": facts.get("title", "")}, "rank": "rendered", "confidence": "high", "evidence": ["page"]})
    return {"adapter": "inferred", "origin": f"{url} ({at})", "label": f"site {url}", "at": at, "evidence": ev,
            "values": values, "ignored": ignored, "not_found": not_found}
