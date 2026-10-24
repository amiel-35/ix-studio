"""The visual review: review.md shown, not described. One HTML page per merge, next to review.md.

Each look with its swatches, its typefaces written in themselves when the font file is reachable, its logo files, the
screenshots of its pages; the images found on the web as links with their proposed ownership (never embedded: they
are not kept); the text values with their status. By default images are linked relatively (review.html opens from
the brand folder); `embed=True` builds a standalone page that can be sent as one file.

The page is also where the user arbitrates the visuals: one card per visual with Keep / Discard, the logo candidates
apart, and the `brandkit keep` command that records the choices, built live at the bottom. A web image or a page gets a
preview hotlinked from its og:image when `previews=True` (read at render time, never downloaded into the dossier).
"""

import base64
import html
import json
import re
import shlex
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import media
from model import DEFAULT_LOOK, FEEDING, SCALARS, VISUAL_KINDS

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
        "q_pick": "<b>The visuals</b>: keep or discard each card, choose the logo, then copy the command at the bottom of the page and run it.",
        "pick": "Keep or discard", "pick_lead": "Every visual the dossier rests on. Keep what is the brand's today; discard the old identity, other campaigns, other people's posters. What you discard stops feeding colours, type and looks. A card with no choice counts as discarded.",
        "keep": "Keep", "discard": "Discard", "n_keep": "kept", "n_disc": "discarded", "n_open": "no choice yet (counted as discarded)",
        "no_preview": "no preview", "open": "open", "video_only": "video: link only", "logo_pick": "Logo",
        "logo_lead": "The logo is always taken as a file, apart from the screenshots. Choose the one to use.", "logo_none": "No change",
        "cmd": "Your choices, as one command", "cmd_help": "Copy it and run it in a terminal, or hand it back to Claude.", "copy": "Copy", "copied": "Copied",
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
        "q_pick": "<b>Les visuels</b> : garde ou écarte chaque carte, choisis le logo, puis copie la commande en bas de page et lance-la.",
        "pick": "Je garde / J'écarte", "pick_lead": "Tous les visuels sur lesquels repose le dossier. Garde ce qui est la marque aujourd'hui ; écarte l'ancienne identité, les autres campagnes, les affiches des autres. Ce que tu écartes ne nourrit plus les couleurs, les polices ni les looks. Une carte sans choix compte comme écartée.",
        "keep": "Je garde", "discard": "J'écarte", "n_keep": "gardés", "n_disc": "écartés", "n_open": "sans choix (comptés comme écartés)",
        "no_preview": "pas d'aperçu", "open": "ouvrir", "video_only": "vidéo : lien seulement", "logo_pick": "Logo",
        "logo_lead": "Le logo se prend toujours comme un fichier, à part des captures. Choisis celui à utiliser.", "logo_none": "Pas de changement",
        "cmd": "Tes choix, en une commande", "cmd_help": "Copie-la et lance-la dans un terminal, ou rends-la à Claude.", "copy": "Copier", "copied": "Copié",
        "own": {"official": "officielle", "official_relayed": "officielle relayée", "probable": "probable", "uncertain": "incertaine"},
        "own_status": {"to_confirm": "à confirmer", "confirmed": "confirmée", "corrected": "corrigée"},
    },
}

CSS = """
:root{--bg:#f6f6f4;--card:#fff;--ink:#1d1f22;--mute:#6b6f76;--line:#e3e3df;--ok:#e3f6e8;--tc:#e7f0ff;--ask:#ffe6e0;--askink:#7a2a17}
@media (prefers-color-scheme:dark){:root{--bg:#17181a;--card:#202225;--ink:#e8e8e6;--mute:#9a9ea5;--line:#33363a;--ok:#1f3a27;--tc:#1e2c44;--ask:#4a2219;--askink:#ffb4a1}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 220px}
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
.picks{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:12px}
.vcard{background:var(--card);border:2px solid var(--line);border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:6px;font-size:13px}
.vcard[data-choice=keep]{border-color:#2f9e55}.vcard[data-choice=discard]{border-color:#d9534f}.vcard[data-choice=discard] .view{opacity:.35}
.vcard .view{height:150px;border-radius:6px;background:var(--bg);display:flex;align-items:center;justify-content:center;overflow:hidden;text-align:center;color:var(--mute)}
.vcard .view img{max-width:100%;max-height:100%;object-fit:contain}
.vcard .meta{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.vcard .note{overflow-wrap:anywhere}
.btns{display:flex;gap:8px;margin-top:auto}.btns button{flex:1;padding:8px 6px;border-radius:8px;border:1px solid var(--line);background:var(--bg);color:var(--ink);font:inherit;cursor:pointer}
.btns button[aria-pressed=true].k{background:#2f9e55;color:#fff;border-color:#2f9e55}.btns button[aria-pressed=true].d{background:#d9534f;color:#fff;border-color:#d9534f}
.logo-pick{display:flex;flex-wrap:wrap;gap:12px}.logo-opt{display:block;border:2px solid var(--line);border-radius:10px;padding:8px;background:var(--card);font-size:13px;cursor:pointer;max-width:100%}
.logo-opt:has(input:checked){border-color:#2f9e55}.chips{display:flex}.chips span{display:flex;align-items:center;justify-content:center;width:130px;height:84px}
.chips img{max-width:112px;max-height:68px}.on-light{background:#fff}.on-dark{background:#1d1f22}
.bar{position:fixed;left:0;right:0;bottom:0;z-index:5;background:var(--card);border-top:1px solid var(--line);padding:10px 16px}
.bar>div{max-width:1100px;margin:0 auto}.bar .count{font-size:12px;color:var(--mute);margin-bottom:4px}
.bar pre{margin:0 0 8px;max-height:5.5em;overflow:auto;white-space:pre-wrap;word-break:break-all;font-size:12px;background:var(--bg);border-radius:6px;padding:6px 8px}
.bar button{padding:8px 18px;border-radius:8px;border:0;background:#3d7be0;color:#fff;font:inherit;cursor:pointer}
@media (max-width:600px){.bar .hint{display:none}.bar pre{max-height:4em}}
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


LOGO_WORDS = re.compile(r"logo|favicon|\bicons?\b", re.I)


def logo_candidates(doc, evidence):
    """The files that may be the brand's logo: the logo rubric's files, and any file whose name or note says logo or icon."""
    rubric = doc.get("logo", {})
    files = {(it.get("file") or {}).get("value") for it in rubric.get("items", [])}
    files |= {(d.get("value") or {}).get("file") for d in rubric.get("discarded", [])}
    files.discard(None)
    return [x for x in evidence if x["kind"] == "file" and (x["where"] in files or LOGO_WORDS.search(f"{Path(x['where']).name} {x.get('note', '')}"))]


def cards(doc, evidence):
    """What the user arbitrates card by card: every visual evidence except the logo candidates (they have their own section)."""
    logos = {x["id"] for x in logo_candidates(doc, evidence)}
    return [x for x in evidence if x["kind"] in VISUAL_KINDS and x["id"] not in logos]


def preset(x):
    """Keep, discard or no choice, from the decision already recorded (a proposal alone decides nothing)."""
    if x.get("ownership_status") in ("confirmed", "corrected") and x.get("ownership"):
        return "keep" if x["ownership"] in FEEDING else "discard"
    return ""


def fetch_previews(items):
    """{evidence id: image address} for pages and web images, read now from the page's og:image. Never stored."""
    todo = [x for x in items if x["kind"] in ("page", "web_image")]
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip((x["id"] for x in todo), pool.map(media.preview_url, todo)))


def pick_command(root):
    return f"python3 {shlex.quote(str(Path(__file__).resolve().parent))} keep {shlex.quote(str(Path(root).resolve()))}"


def _v(x):
    if not isinstance(x, dict) or x.get("value") in (None, "", []):
        return None
    val = x["value"]
    return " · ".join(map(str, val)) if isinstance(val, list) else str(val)


def render_html(doc, evidence, review, root, out, lang="en", embed=False, previews=False, decisions=None):
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


    def pick_section():
        cs = cards(doc, evidence)
        logos = logo_candidates(doc, evidence)
        if not cs and not logos:
            return "", ""
        seen = fetch_previews(cs) if previews else {}
        out_cards = []
        for n, x in enumerate(cs, 1):
            link = x.get("page") or x["where"]
            url = seen.get(x["id"])
            if x["kind"] == "file":
                src = img.src(x["where"])
                link = src or x["where"]
                view = f"<img src='{e(src)}' alt=''>" if src else t["no_preview"]
            elif x["kind"] == "video":
                view = t["video_only"]
            elif url:
                view = f"<img src='{e(url)}' alt='' loading='lazy' referrerpolicy='no-referrer' onerror='this.style.display=&quot;none&quot;'>"
            else:
                view = t["no_preview"]
            look = look_of(x)
            what = x.get("note") or x.get("title") or Path(x["where"]).name or x["where"]
            own = f"<span class='pill {x['ownership']}'>{t['own'].get(x['ownership'], '?')}</span>" if x.get("ownership") else ""
            look_pill = "<span class='pill'>" + e(look) + "</span>" if look else ""
            out_cards.append(
                f"<div class='vcard' data-id='{x['id']}' data-choice='{preset(x)}'><div class='meta'><b>{n}</b><span class='pill'>{x['kind']}</span>"
                f"{look_pill}{own}<code>{x['id']}</code></div>"
                f"<div class='view'>{view}</div><div class='note'>{e(what[:160])}</div>"
                f"<a href='{e(link)}' target='_blank' rel='noopener'>{t['open']}</a>"
                f"<div class='btns'><button type='button' class='k' data-set='keep'>{t['keep']}</button>"
                f"<button type='button' class='d' data-set='discard'>{t['discard']}</button></div></div>")
        chosen = [d for d in (decisions or []) if d.get("action") == "logo"]
        current = chosen[-1]["evidence"] if chosen else ""
        opts = [f"<label class='logo-opt'><input type='radio' name='logo' value=''{' checked' if not current else ''}> {t['logo_none']}</label>"]
        for x in logos:
            src = img.src(x["where"], 400)
            shown = (f"<div class='chips'><span class='on-light'><img src='{e(src)}' alt=''></span><span class='on-dark'><img src='{e(src)}' alt=''></span></div>"
                     if src else f"<code>{e(x['where'])}</code>")
            opts.append(f"<label class='logo-opt'><input type='radio' name='logo' value='{x['id']}'{' checked' if x['id'] == current else ''}> {shown}"
                        f"<br><code>{x['id']}</code> {e((x.get('note') or Path(x['where']).name)[:80])}</label>")
        logo_html = (f"<h3>{t['logo_pick']}</h3><p class='mute'>{t['logo_lead']}</p><div class='logo-pick'>{''.join(opts)}</div>") if logos else ""
        html_ = (f"<section class='card' id='pick'><header><h2>{t['pick']}</h2></header><p class='mute'>{t['pick_lead']}</p>"
                 f"<div class='picks'>{''.join(out_cards)}</div>{logo_html}</section>"
                 f"<div class='bar'><div><div class='count' id='count'></div><pre id='cmd' aria-label='{e(t['cmd'])}'></pre>"
                 f"<button type='button' id='copy'>{t['copy']}</button> <span class='mute hint'>{t['cmd_help']}</span></div></div>")
        js = ("(function(){var P=%s,L=%s,cs=[].slice.call(document.querySelectorAll('.vcard')),cmd=document.getElementById('cmd'),cnt=document.getElementById('count');"
              "function upd(){var k=[],d=0,o=0;cs.forEach(function(c){var v=c.getAttribute('data-choice');"
              "[].forEach.call(c.querySelectorAll('button'),function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-set')===v))});"
              "if(v==='keep')k.push(c.getAttribute('data-id'));else if(v==='discard')d++;else o++;});"
              "var r=document.querySelector('input[name=logo]:checked'),lg=r&&r.value?' --logo '+r.value:'';"
              "cmd.textContent=P+(k.length?' '+k.join(' '):' --none')+lg;"
              "cnt.textContent=k.length+' '+L.k+' · '+(d+o)+' '+L.d+(o?' ('+o+' '+L.o+')':'');}"
              "cs.forEach(function(c){[].forEach.call(c.querySelectorAll('button'),function(b){b.onclick=function(){"
              "var v=b.getAttribute('data-set');c.setAttribute('data-choice',c.getAttribute('data-choice')===v?'':v);upd();};});});"
              "[].forEach.call(document.querySelectorAll('input[name=logo]'),function(r){r.onchange=upd;});"
              "document.getElementById('copy').onclick=function(){var b=this,txt=cmd.textContent;"
              "function done(){b.textContent=L.c;setTimeout(function(){b.textContent=L.b},1500)}"
              "function fb(){var a=document.createElement('textarea');a.value=txt;document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(x){}document.body.removeChild(a);done()}"
              "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(txt).then(done,fb)}else{fb()}};upd();})();"
              % (json.dumps(pick_command(root)).replace("</", "<\\/"),
                 json.dumps({"k": t["n_keep"], "d": t["n_disc"], "o": t["n_open"], "c": t["copied"], "b": t["copy"]}, ensure_ascii=False).replace("</", "<\\/")))
        return html_, f"<script>{js}</script>"

    looks = doc.get("looks", {}).get("items", []) or [{"id": DEFAULT_LOOK, "name": {"value": doc["identity"]["name"].get("value")}, "kind": {"value": "brand"}}]
    meta = doc["meta"]
    head = f"{t['version']} {meta['version']}" if not meta.get("draft") else t["draft"]
    name = doc["identity"]["name"].get("value") or "?"
    owned = [x for x in evidence if x.get("ownership_status") == "to_confirm"]

    pick_html, pick_js = pick_section()
    todo = []
    if review.get("looks"):
        todo.append(t["q_master"])
    if pick_html:
        todo.append(t["q_pick"])
    elif owned:
        todo.append(t["q_visuals"])
    todo.append(t["q_values"])
    body = [f"<h1>{e(name)} · {t['title']}</h1><p class='lead'>{head} · {e(str(meta.get('generated_at')))}. {t['lead']}</p>",
            f"<div class='todo'><b>{t['todo']}</b><ol>" + "".join("<li>" + q + "</li>" for q in todo) + "</ol></div>"]

    body.append(pick_html)

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
            f"<title>{e(name)} review</title><style>{CSS}{''.join(font_faces)}</style></head><body><main>{''.join(body)}</main>{pick_js}</body></html>")
