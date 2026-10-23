"""The visual review: review.md shown, not described. One HTML page per merge, next to review.md.

Each look with its swatches, its typefaces written in themselves when the font file is reachable, its logo files, the
screenshots of its pages; the images found on the web as links with their proposed ownership (never embedded: they
are not kept); the text values with their status. By default images are linked relatively (review.html opens from
the brand folder); `embed=True` builds a standalone page that can be sent as one file.
"""

import base64
import html
import shutil
import subprocess
import tempfile
from pathlib import Path

from model import DEFAULT_LOOK, SCALARS

e = html.escape

T = {
    "en": {
        "title": "Brand dossier review", "draft": "draft, not validated", "version": "validated version",
        "lead": "What the inference found is marked \"to confirm\". Images found on the web are not kept: click their link to see them.",
        "todo": "What to answer, in one message:", "q_master": "<b>The master look</b>: which of the looks below is the brand by default?",
        "q_visuals": "<b>The images</b>: each label is a proposed ownership. Say which ones are wrong (by their <code>ev-…</code> code or in plain words).",
        "q_values": "<b>The values</b>: what you confirm, what you reject, what you can fill in among the ASK lines.",
        "conflicts": "Conflicts kept", "kept": "kept", "over": "over",
        "colours": "Colours", "type": "Typefaces", "logo": "Logo", "shots": "Screenshots", "web": "Seen on the web (not kept)",
        "no_colours": "No colour measured: ASK", "no_type": "No typeface read: ASK", "no_logo": "No logo file: ASK",
        "vector": "Vector logo: ASK", "master": "master look", "master_ask": "master look? ASK",
        "unattached": "Seen on the web, attached to no look", "text": "Text and everything else", "notes": "Not found",
        "ignored": "Ignored on purpose", "confirmed": "sure", "to_confirm": "to confirm", "ask": "ASK", "to_create": "to create",
        "reserved": "reserved", "confidence": "confidence", "licence": "licence",
        "own": {"official": "official", "official_relayed": "official, relayed", "probable": "probable", "uncertain": "uncertain"},
        "own_status": {"to_confirm": "to confirm", "confirmed": "confirmed", "corrected": "corrected"},
    },
    "fr": {
        "title": "Revue du dossier de marque", "draft": "brouillon, non validé", "version": "version validée",
        "lead": "Ce que l'inférence a trouvé est marqué « à confirmer ». Les images du web ne sont pas gardées : clique sur leur lien pour les voir.",
        "todo": "Ce qu'il faut me dire, en un message :", "q_master": "<b>Le look maître</b> : lequel des looks ci-dessous est la marque par défaut ?",
        "q_visuals": "<b>Les images</b> : chaque étiquette est une appartenance proposée. Dis-moi celles qui sont fausses (par leur code <code>ev-…</code> ou en clair).",
        "q_values": "<b>Les valeurs</b> : ce que tu confirmes, ce que tu rejettes, ce que tu peux remplir parmi les À DEMANDER.",
        "conflicts": "Conflits gardés", "kept": "retenu", "over": "contre",
        "colours": "Couleurs", "type": "Polices", "logo": "Logo", "shots": "Captures", "web": "Vus sur le web (non gardés)",
        "no_colours": "Aucune couleur mesurée : À DEMANDER", "no_type": "Aucune police lue : À DEMANDER", "no_logo": "Aucun fichier de logo : À DEMANDER",
        "vector": "Logo vectoriel : À DEMANDER", "master": "look maître", "master_ask": "look maître ? À DEMANDER",
        "unattached": "Vus sur le web, rattachés à aucun look", "text": "Le texte et le reste", "notes": "Pas trouvé",
        "ignored": "Ignoré exprès", "confirmed": "sûr", "to_confirm": "à confirmer", "ask": "À DEMANDER", "to_create": "à créer",
        "reserved": "réservé", "confidence": "confiance", "licence": "licence",
        "own": {"official": "officielle", "official_relayed": "officielle relayée", "probable": "probable", "uncertain": "incertaine"},
        "own_status": {"to_confirm": "à confirmer", "confirmed": "confirmée", "corrected": "corrigée"},
    },
}

CSS = """
:root{--bg:#f6f6f4;--card:#fff;--ink:#1d1f22;--mute:#6b6f76;--line:#e3e3df;--ok:#e3f6e8;--tc:#e7f0ff;--ask:#ffe6e0;--askink:#7a2a17}
@media (prefers-color-scheme:dark){:root{--bg:#17181a;--card:#202225;--ink:#e8e8e6;--mute:#9a9ea5;--line:#33363a;--ok:#1f3a27;--tc:#1e2c44;--ask:#4a2219;--askink:#ffb4a1}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 80px}
h1{margin:0 0 4px;font-size:24px}.lead,.mute{color:var(--mute)}
.todo{border:1px solid var(--line);border-left:4px solid #d9a400;background:var(--card);border-radius:8px;padding:12px 16px;margin:16px 0}
.todo ol{margin:6px 0 0 18px;padding:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin:20px 0}
.card header{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.card h2{margin:0;font-size:20px}
.pill{font-size:11px;padding:1px 8px;border-radius:99px;background:var(--line);white-space:nowrap}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);margin:18px 0 8px}
.sws{display:flex;flex-wrap:wrap;gap:12px}.sw{width:118px;font-size:12px}.chip{height:56px;border-radius:6px;border:1px solid var(--line)}
.sw code{display:block;margin-top:4px}
.logos{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end}.logos img{max-height:72px;max-width:260px;background:#fff;padding:8px;border:1px solid var(--line);border-radius:6px}
figure{margin:0}figcaption{font-size:12px;color:var(--mute)}
.shots{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px}.shots img{width:100%;border:1px solid var(--line);border-radius:6px}
.confirmed{background:var(--ok)}.to_confirm{background:var(--tc)}.ask,.to_create{background:var(--ask);color:var(--askink)}
.official{background:var(--ok)}.official_relayed{background:var(--tc)}.uncertain{background:var(--ask);color:var(--askink)}
ul{padding-left:20px}li{margin:4px 0}table{border-collapse:collapse;width:100%}td{border-top:1px solid var(--line);padding:8px 6px;vertical-align:top}
code{font-size:12px;color:var(--mute)}a{color:#3d7be0}.type-sample{font-size:22px;margin-right:6px}
"""


class Images:
    """Image sources: a relative path, or the file embedded (scaled down with ffmpeg when it is there)."""

    def __init__(self, root: Path, out: Path, embed: bool):
        self.root, self.out, self.embed = root, out, embed
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-review-")) if embed else None

    def src(self, rel, width=900):
        p = (self.root / rel).resolve()
        if not p.exists():
            return None
        if not self.embed:
            try:
                return str(p.relative_to(self.out.parent.resolve()))
            except ValueError:
                return p.as_uri()
        if p.suffix.lower() == ".svg":
            return "data:image/svg+xml;base64," + base64.b64encode(p.read_bytes()).decode()
        if shutil.which("ffmpeg"):
            out = self.tmp / (p.stem + f"-{abs(hash(str(p)))}.jpg")
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(p), "-vf", f"scale='min({width},iw)':-2", "-q:v", "4", str(out)])
            if r.returncode == 0 and out.exists():
                return "data:image/jpeg;base64," + base64.b64encode(out.read_bytes()).decode()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif"}.get(p.suffix.lower(), "application/octet-stream")
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()

    def close(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


def _v(x):
    if not isinstance(x, dict) or x.get("value") in (None, "", []):
        return None
    val = x["value"]
    return " · ".join(map(str, val)) if isinstance(val, list) else str(val)


def render_html(doc, evidence, review, root, out, lang="en", embed=False):
    t = T.get(lang, T["en"])
    ev = {x["id"]: x for x in evidence}
    pages = {x["where"]: x for x in evidence if x["kind"] == "page"}
    img = Images(Path(root), Path(out), embed)

    def badge(x, label=None):
        st = (x or {}).get("status", "ask")
        conf = f" · {t['confidence']} {x['confidence']}" if x and x.get("confidence") and st == "to_confirm" else ""
        return f'<span class="pill {st}">{label or t.get(st, st)}{conf}</span>'

    def look_of(x):
        if x.get("look"):
            return x["look"]
        if x.get("page") and x["page"] in pages:
            return pages[x["page"]].get("look") or DEFAULT_LOOK
        return None

    def web_line(x):
        st = x.get("ownership_status")
        mark = f' <span class="mute">({t["own_status"].get(st, st)})</span>' if st else ""
        link = x.get("page") or x["where"]
        return (f'<li><a href="{e(link)}" target="_blank" rel="noopener">{e((x.get("note") or x.get("title") or link)[:160])}</a> '
                f'<span class="pill {x.get("ownership", "")}">{t["own"].get(x.get("ownership"), "?")}</span>{mark} <code>{x["id"]}</code></li>')

    looks = doc.get("looks", {}).get("items", []) or [{"id": DEFAULT_LOOK, "name": {"value": doc["identity"]["name"].get("value")}, "kind": {"value": "brand"}}]
    meta = doc["meta"]
    head = f"{t['version']} {meta['version']}" if not meta.get("draft") else t["draft"]
    name = doc["identity"]["name"].get("value") or "?"
    owned = [x for x in evidence if x.get("ownership_status") == "to_confirm"]

    todo = []
    if review.get("looks"):
        todo.append(t["q_master"])
    if owned:
        todo.append(t["q_visuals"])
    todo.append(t["q_values"])
    body = [f"<h1>{e(name)} · {t['title']}</h1><p class='lead'>{head} · {e(str(meta.get('generated_at')))}. {t['lead']}</p>",
            f"<div class='todo'><b>{t['todo']}</b><ol>" + "".join("<li>" + q + "</li>" for q in todo) + "</ol></div>"]

    if review.get("conflicts"):
        rows = []
        for c in review["conflicts"]:
            o = c["other"]

            def show(val):
                if isinstance(val, dict) and val.get("hex"):
                    return f'<span class="chip" style="display:inline-block;width:14px;height:14px;vertical-align:middle;background:{e(val["hex"])}"></span> {e(val["hex"])} {e(str(val.get("role", "")))}'
                if isinstance(val, dict):
                    return e(", ".join(f"{k}: {x}" for k, x in val.items() if k in ("family", "role", "file")))
                if isinstance(val, list):
                    return e(" · ".join(map(str, val)))[:200]
                return e(str(val))[:200]
            look = f" ({c['look']})" if c.get("look") else ""
            rows.append(f"<li><code>{e(c['path'])}</code>{look} : {t['kept']} {show(c['kept'])} <span class='mute'>[{e(c['kept_source']['type'])}]</span> "
                        f"{t['over']} {show(o['value'])} <span class='mute'>[{e(o['source']['type'])}: {e(o['source']['origin'])}]</span></li>")
        body.append(f"<section class='card'><header><h2>{t['conflicts']}</h2></header><ul>{''.join(rows)}</ul></section>")

    font_faces = []
    for lk in looks:
        lid = lk["id"]
        cols = [it for it in doc["colours"].get("items", []) if it.get("look", DEFAULT_LOOK) == lid]
        typ = [it for it in doc["typography"].get("items", []) if it.get("look", DEFAULT_LOOK) == lid]
        logos = [it for it in doc["logo"].get("items", []) if it.get("look", DEFAULT_LOOK) == lid]
        gaps = [g for g in doc["logo"].get("gaps", []) if g.get("look") == lid]
        master = lk.get("master", {})
        mtag = (f"<span class='pill confirmed'>{t['master']}</span>" if master.get("value") is True and master.get("status") == "confirmed"
                else f"<span class='pill to_confirm'>{t['master']}</span>" if master.get("value") is True
                else f"<span class='pill ask'>{t['master_ask']}</span>" if master.get("status") == "ask" else "")
        sw = "".join(f"<div class='sw'><div class='chip' style='background:{e(_v(c.get('hex')) or '#fff')}'></div><code>{e(_v(c.get('hex')) or '?')}</code>"
                     f"{e(_v(c.get('name')) or '')} {e(_v(c.get('role')) or '')}<br>{badge(c.get('hex'))}</div>" for c in cols) or f"<p class='ask'>{t['no_colours']}</p>"
        tl = []
        for it in typ:
            fam = _v(it.get("family")) or "?"
            files = it.get("files", {}).get("value") or []
            web = next((f for f in (files if isinstance(files, list) else [files]) if str(f).startswith("http") and str(f).split("?")[0].endswith((".woff2", ".woff", ".ttf", ".otf"))), None)
            if web:
                font_faces.append(f'@font-face{{font-family:"ixs {e(fam)}";src:url("{e(web)}")}}')
            lic = f" {badge(it.get('licence'), t['licence'] + ' ' + t['ask'])}" if (it.get("licence") or {}).get("status") == "ask" else ""
            tl.append(f"<li><span class='type-sample' style='font-family:\"ixs {e(fam)}\",\"{e(fam)}\"'>{e(fam)}</span> {e(_v(it.get('role')) or '')} {badge(it.get('family'))}{lic}</li>")
        ty = "".join(tl) or f"<li class='ask'>{t['no_type']}</li>"
        figs = []
        for l in logos:
            path = _v(l.get("file"))
            if not path:
                continue
            src = img.src(path, 400)
            shown = f"<img src='{e(src)}' alt=''>" if src else f"<code>{e(path)}</code>"  # a skill's file lives with the skill
            figs.append(f"<figure>{shown}<figcaption>{e(_v(l.get('format')) or '')} · {e(_v(l.get('variant')) or '')} {badge(l.get('file'))}</figcaption></figure>")
        lg = "".join(figs)
        lg += "".join(f"<p class='ask'>{t['vector']}</p>" for _ in gaps)
        lg = lg or f"<p class='ask'>{t['no_logo']}</p>"
        shots = [x for x in evidence if x["kind"] == "file" and look_of(x) == lid and str(x.get("note", "")).lower().startswith(("screenshot", "capture"))]
        shot_html = "".join(f"<img src='{e(s)}' alt=''>" for s in (img.src(x["where"]) for x in shots[:4]) if s)
        webs = [x for x in evidence if x["kind"] in ("web_image", "video") and x.get("look") == lid]
        shots_block = "<h3>" + t["shots"] + "</h3><div class='shots'>" + shot_html + "</div>" if shot_html else ""
        web_block = "<h3>" + t["web"] + "</h3><ul>" + "".join(web_line(x) for x in webs) + "</ul>" if webs else ""
        title = e(_v(lk.get("name")) or lid)
        kind = e(_v(lk.get("kind")) or "")
        summary = e(_v(lk.get("summary")) or "")
        body.append(f"<section class='card' id='{e(lid)}'><header><h2>{title}</h2><span class='pill'>{kind}</span> {mtag} <code>{e(lid)}</code></header>"
                    f"<p class='mute'>{summary}</p><h3>{t['colours']}</h3><div class='sws'>{sw}</div>"
                    f"<h3>{t['type']}</h3><ul>{ty}</ul><h3>{t['logo']}</h3><div class='logos'>{lg}</div>{shots_block}{web_block}</section>")

    loose = [x for x in evidence if x["kind"] in ("web_image", "video") and not x.get("look")]
    if loose:
        body.append(f"<section class='card'><header><h2>{t['unattached']}</h2></header><ul>{''.join(web_line(x) for x in loose)}</ul></section>")

    rows = []
    for path in SCALARS:
        sec, f = path.split(".")
        x = doc["meta"]["language"] if path == "meta.language" else doc.get(sec, {}).get(f)
        if not isinstance(x, dict):
            continue
        rows.append(f"<tr><td><code>{path}</code></td><td>{e(_v(x) or '')}</td><td>{badge(x)}</td><td class='mute'>{e(x.get('note', ''))}</td></tr>")
    body.append(f"<section class='card'><header><h2>{t['text']}</h2></header><table>{''.join(rows)}</table></section>")
    if review.get("notes"):
        items = "".join("<li>" + e(n["text"]) + "</li>" for n in review["notes"])
        body.append(f"<section class='card'><header><h2>{t['notes']}</h2></header><ul>{items}</ul></section>")
    if review.get("ignored"):
        items = "".join("<li>" + e(str(n.get("what"))) + " : " + e(str(n.get("why"))) + "</li>" for n in review["ignored"])
        body.append(f"<section class='card'><header><h2>{t['ignored']}</h2></header><ul>{items}</ul></section>")
    img.close()
    return (f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(name)} review</title><style>{CSS}{''.join(font_faces)}</style></head><body><main>{''.join(body)}</main></body></html>")
