"""pages: the body of each of the five step pages. The shell and the CSS are in ui.py."""

import re
from pathlib import Path

from colour import ink_on, rgba
from compose import fonts_link
from files import (font_css, ground_hex, image_file, load_brand, load_brief, load_pick, load_variants, picked, read_json,
                   StudioError)
from ui import cli, e, shell, write_page

EN = {
    "name": "Name", "voice": "Voice", "never": "Never", "notes": "Notes", "logo": "Logo", "no_logo": "no logo file: the name is set in type",
    "fonts": "Fonts", "colours": "Colours", "headline": "headline", "body": "body", "none": "none given", "other": "Also kept",
    "t1": ["Are the colours and fonts right, in the sample sentences?", "Is the voice a sentence you would sign, and the never-list complete?",
           "Answer: fix <code>brand.md</code> and rerun, or go to the brief."],
    "objective": "Objective", "audience": "Audience", "message": "The piece must make people think or do", "format": "Format",
    "fixed": "Fixed beyond the brand", "cta": "Call to action", "language": "Language",
    "t2": ["Is the message one sentence, and the audience a person you could picture?", "Answer: fix <code>brief.md</code>, or ask for the variants."],
    "attractor": "The attractor: what bland looks like on this brief", "attractor_say": "Each variant's discarded default. A variant that sounds like one of these did not leave.",
    "close": "fell back to the default?", "mandate": "Mandate", "why": "Why", "pick": "To pick it", "never_hit": "contains a never-word",
    "picked": "picked", "default_img": "default image", "prompt": "Image prompt", "headline_l": "Headline", "layout": "Layout", "ground": "Ground",
    "t3": ["Do the variants really differ in what they say, not only in wording?", "Does each image answer its headline?",
            "Answer: which one to pick (the command under it), and any headline you want changed."],
    "piece": "The piece", "engine": "Image engine", "placeholder": "Placeholder", "no_image": "no generated image: flat brand ground",
    "t4": ["Read the headline first, then see if the image answers it.", "Answer: go to the check, or change the pick and recompose."],
    "mech": "Mechanical checks", "judge": "The judge's notes (never blocking)", "no_judge": "no judge.md yet", "call": "Your call",
    "keep": "Keep it", "again": "Again, and say what is wrong", "decision": "Decision", "verdict": "Verdict",
    "t5": ["Read the failures first, then the judge's notes: they are advice, not a gate.", "Answer: keep, or again with what is wrong (it is remembered)."],
    "not_picked": "no pick yet",
}
FR = {
    "name": "Nom", "voice": "Voix", "never": "Jamais", "notes": "Notes", "logo": "Logo", "no_logo": "pas de logo : le nom est composé en lettres",
    "fonts": "Polices", "colours": "Couleurs", "headline": "titres", "body": "texte", "none": "rien", "other": "Aussi gardé",
    "t1": ["Les couleurs et les polices sont-elles justes, dans les phrases d'exemple ?", "La voix est-elle une phrase que tu signerais, la liste des interdits complète ?",
           "Réponse : corrige <code>brand.md</code> et relance, ou passe au brief."],
    "objective": "Objectif", "audience": "Public", "message": "La pièce doit faire penser ou faire", "format": "Format",
    "fixed": "Fixe, au-delà de la marque", "cta": "Appel à l'action", "language": "Langue",
    "t2": ["Le message tient-il en une phrase, le public est-il quelqu'un qu'on voit ?", "Réponse : corrige <code>brief.md</code>, ou demande les variantes."],
    "attractor": "L'attracteur : à quoi ressemble le banal sur ce brief", "attractor_say": "Le défaut écarté de chaque variante. Une variante qui ressemble à l'un d'eux n'est pas partie.",
    "close": "retombée sur le défaut ?", "mandate": "Mandat", "why": "Pourquoi", "pick": "Pour la choisir", "never_hit": "contient un mot interdit",
    "picked": "choisie", "default_img": "image par défaut", "prompt": "Prompt d'image", "headline_l": "Accroche", "layout": "Mise en page", "ground": "Fond",
    "t3": ["Les variantes diffèrent-elles vraiment par ce qu'elles disent, pas seulement par les mots ?", "Chaque image répond-elle à son accroche ?",
            "Réponse : laquelle choisir (la commande dessous), et l'accroche à changer."],
    "piece": "La pièce", "engine": "Moteur d'image", "placeholder": "Provisoire", "no_image": "pas d'image générée : aplat de la marque",
    "t4": ["Lis l'accroche d'abord, puis vois si l'image y répond.", "Réponse : passe à la vérification, ou change le choix et recompose."],
    "mech": "Vérifications mécaniques", "judge": "Notes du juge (jamais bloquantes)", "no_judge": "pas encore de judge.md", "call": "À toi de trancher",
    "keep": "Garder", "again": "Recommencer, en disant ce qui ne va pas", "decision": "Décision", "verdict": "Verdict",
    "t5": ["Lis d'abord les échecs, puis les notes du juge : ce sont des conseils, pas une barrière.", "Réponse : garder, ou recommencer avec ce qui ne va pas (c'est retenu)."],
    "not_picked": "pas encore de choix",
}


def tt(lang):
    return {**EN, **(FR if lang == "fr" else {})}


def swatch(h, label):
    return f'<div class="sw"><div class="chip" style="background:{h}"></div><b>{e(label)}</b><br><code>{h}</code></div>'


def sws(b):
    items = [("background", b["background"]), ("text", b["text"])] + ([("accent", b["accent"])] if b["accent"] else [])
    return '<div class="sws">' + "".join(swatch(h, n) for n, h in items + [("extra", x) for x in b["extras"]]) + "</div>"


def brand_page(d, lang):
    t, b = tt(lang), load_brand(d)
    hf, bf = font_css(b["hfont"], "Georgia,serif"), font_css(b["bfont"], "system-ui,sans-serif")
    logo = (f'<img src="{e(b["logo"])}" alt="" style="max-height:72px;max-width:260px">' if b["logo"] and not b.get("logo_missing")
            else f'<span class="mute">{t["no_logo"]}</span>')
    never = "".join(f'<span class="pill fail">{e(w)}</span> ' for w in b["never"]) or f'<span class="mute">{t["none"]}</span>'
    other = "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in b["other"].items())
    body = f"""<h1>{e(b['name'])}</h1>
<div class="card"><h3>{t['colours']}</h3>{sws(b)}</div>
<div class="card"><h3>{t['fonts']}</h3>
<p style="font-family:{hf};font-size:32px;margin:0;line-height:1.1">{e(b['name'])}: a headline in {e(b['hfont'] or 'the default serif')}</p>
<p style="font-family:{bf};margin:8px 0 0">{t['body']}: the quick brown fox, set in {e(b['bfont'] or 'the default sans')}.</p></div>
<div class="cols"><div class="card"><h3>{t['logo']}</h3>{logo}</div>
<div class="card"><h3>{t['voice']}</h3>{e(b['voice']) or '<span class="mute">' + t['none'] + '</span>'}</div>
<div class="card"><h3>{t['never']}</h3>{never}</div></div>
{('<div class="card"><h3>' + t['notes'] + '</h3>' + e(b['notes']) + '</div>') if b['notes'] else ''}
{('<div class="card"><h3>' + t['other'] + '</h3><table>' + other + '</table></div>') if other else ''}"""
    return write_page(d, 1, shell(1, b["name"], body, lang, t["t1"], cli(d, "brief"), fonts_link(b)))


def brief_page(d, lang):
    t, b, br = tt(lang), load_brand(d), load_brief(d)
    w, h = br["size"]
    rows = [("objective", br["objective"]), ("audience", br["audience"]), ("message", br["message"]),
            ("format", f"{br['format']} · {w}×{h}"), ("fixed", br["fixed"]), ("cta", br["cta"]), ("language", br["language"])]
    rows = "".join(f"<tr><td class='mute'>{t[k]}</td><td>{e(v)}</td></tr>" for k, v in rows if v)
    other = "".join(f"<tr><td class='mute'>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in br["other"].items())
    body = f"""<h1>{e(b['name'])}</h1><div class="card"><table>{rows}{other}</table></div>
<div class="card"><h3>{t['colours']}</h3>{sws(b)}</div>"""
    return write_page(d, 2, shell(2, br["objective"], body, lang, t["t2"], "agent writes variants/v1.json … v4.json, then: " + cli(d, "diverge"), fonts_link(b)))


def words(s):
    return set(re.findall(r"\w+", s.lower()))


def overlap(a, b):
    x, y = words(a), words(b)
    return len(x & y) / len(x | y) if x | y else 0


def mock(b, br, v, headline=None):
    w, h = br["size"]
    g = ground_hex(b, v["ground"])
    ink = ink_on(g, [b["text"], b["background"], *([b["accent"]] if b["accent"] else [])])
    pos = {"top": "top:5%", "bottom": "bottom:5%", "center": "top:50%;transform:translateY(-50%)"}[v["layout"]]
    cap = "bottom:3%" if v["layout"] == "top" else "top:3%"
    sub = f"<small style=\"font-family:{font_css(b['bfont'], 'sans-serif')}\">{e(v['subline'])}</small>" if v["subline"] else ""
    return (f'<div class="mock" style="aspect-ratio:{w}/{h};background:{b["background"]}">'
            f'<div class="hatch" style="background:repeating-linear-gradient(45deg,{rgba(b["text"], .13)} 0 6px,transparent 6px 12px)"></div>'
            f'<div class="cap" style="{cap};color:{b["text"]}">{e(v["image_prompt"])}</div>'
            f'<div class="mblk" style="{pos};background:{g};color:{ink}"><b style="font-family:{font_css(b["hfont"], "Georgia,serif")}">{e(headline or v["headline"])}</b>{sub}</div></div>')


def diverge_page(d, lang):
    t, b, br, vs = tt(lang), load_brand(d), load_brief(d), load_variants(d)
    pk = load_pick(d) or {}
    defaults = [x["default"]["headline"] for x in vs]
    att = "".join(f'<div class="card"><b>{e(x["default"]["headline"])}</b><br><span class="mute">{t["default_img"]}: {e(x["default"]["image"])}</span>'
                  f'<br><code>{x["id"]}</code></div>' for x in vs)
    cards = []
    for x in vs:
        flags = []
        close = max(overlap(x["headline"], dh) for dh in defaults)
        if close >= 0.6:
            flags.append(f'<span class="pill warn">{t["close"]}</span>')
        hit = [w for w in b["never"] if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", x["headline"], re.I)]
        if hit:
            flags.append(f'<span class="pill fail">{t["never_hit"]}: {e(", ".join(hit))}</span>')
        on = pk.get("variant") == x["id"]
        head = pk.get("headline") if on and pk.get("headline") else None
        cards.append(f"""<div class="card{' picked' if on else ''}"><h3>{x['id']} {'<span class="pill pass">' + t['picked'] + '</span>' if on else ''}</h3>
{mock(b, br, x, head)}<p><b>{e(head or x['headline'])}</b> {''.join(flags)}</p>
<p class="mute">{t['layout']}: {x['layout']} · {t['ground']}: {x['ground']}</p>
<p><b>{t['mandate']}.</b> {e(x['mandate'])}</p><p><b>{t['why']}.</b> {e(x['why'])}</p>
<p class="mute">{t['prompt']}: {e(x['image_prompt'])}</p>
<h3>{t['pick']}</h3><pre>{e(cli(d, 'pick', x['id']))}</pre></div>""")
    body = f"""<h1>{e(b['name'])}</h1><h2>{t['attractor']}</h2><p class="mute">{t['attractor_say']}</p><div class="grid">{att}</div>
<h2>{len(vs)} variants</h2><div class="grid">{''.join(cards)}</div>"""
    nxt = cli(d, "image") + "   (then: " + cli(d, "compose") + ")" if pk else cli(d, "pick", vs[0]["id"])
    return write_page(d, 3, shell(3, br["format"], body, lang, t["t3"], nxt, fonts_link(b)))


def view(d, w, h, small=False):
    if (Path(d) / "piece.png").exists():
        return f'<div class="view"><img src="piece.png" alt=""></div>'
    if (Path(d) / "piece.html").exists():
        return f'<div class="view" data-w="{w}" data-h="{h}"><iframe src="piece.html" width="{w}" height="{h}" scrolling="no" title="piece"></iframe></div>'
    return ""


def piece_page(d, lang):
    t, b, br, vs = tt(lang), load_brand(d), load_brief(d), load_variants(d)
    v, headline = picked(d, vs)
    if not v:
        raise StudioError("no pick.json: pick a variant first")
    if not (Path(d) / "piece.html").exists():
        raise StudioError("no piece.html: run compose first")
    w, h = br["size"]
    im = read_json(Path(d) / "image.json", {})
    ph = [t["no_image"]] if not image_file(d) else []
    if not b["logo"] or b.get("logo_missing"):
        ph.append(t["no_logo"])
    ph_html = "".join(f"<li>{e(x)}</li>" for x in ph) or f'<li class="mute">{t["none"]}</li>'
    body = f"""<div class="cols"><div class="small">{view(d, w, h)}<p><a href="piece.html">piece.html</a> · {w}×{h}</p></div><div>
<h1>{e(headline)}</h1><p class="mute">{v['id']} · {e(v['mandate'])}</p>
<h3>{t['prompt']}</h3><pre>{e(im.get('prompt') or v['image_prompt'])}</pre>
<h3>{t['engine']}</h3><p>{e(im.get('engine', '?'))}: {e(im.get('message', ''))}</p>
<h3>{t['placeholder']}</h3><ul>{ph_html}</ul></div></div>"""
    return write_page(d, 4, shell(4, v["id"], body, lang, t["t4"], cli(d, "check"), fonts_link(b)))


def note_li(n):
    pill = {"major": "fail", "minor": "warn"}.get(n["level"])
    tag = '<span class="pill ' + pill + '">' + n["level"] + "</span> " if pill else ""
    return "<li>" + tag + e(n["say"]) + "</li>"


def check_page(d, lang):
    t, b, br = tt(lang), load_brand(d), load_brief(d)
    ck = read_json(Path(d) / "check.json")
    if not ck:
        raise StudioError("no check.json: run check first")
    w, h = br["size"]
    rows = "".join(f'<tr><td><span class="pill {r["status"]}">{r["status"]}</span></td><td><b>{r["id"]}</b></td><td>{e(r["say"])}</td></tr>' for r in ck["results"])
    notes = "".join(note_li(n) for n in ck["judge"]) or f'<li class="mute">{t["no_judge"]}</li>'
    dec = (Path(d) / "decision.md")
    if dec.exists():
        call = f'<div class="card"><h3>{t["decision"]}</h3><pre>{e(dec.read_text(encoding="utf-8"))}</pre></div>'
        nxt = "done: " + ("rerun the variants with bans.md in hand" if "verdict: again" in dec.read_text(encoding="utf-8") else "the piece is yours")
    else:
        call = (f'<h2>{t["call"]}</h2><div class="card"><h3>{t["keep"]}</h3><pre>{e(cli(d, "decide", "keep", chr(34) + "why" + chr(34)))}</pre>'
                f'<h3>{t["again"]}</h3><pre>{e(cli(d, "decide", "again", chr(34) + "what is wrong" + chr(34)))}</pre></div>')
        nxt = cli(d, "decide", "keep|again", '"..."')
    s = ck["summary"]
    body = f"""<div class="cols"><div class="small">{view(d, w, h)}</div><div>
<h1>{s['pass']} pass · {s['warn']} warn · {s['fail']} fail</h1>
<h3>{t['mech']}</h3><table>{rows}</table><h3>{t['judge']}</h3><ul>{notes}</ul></div></div>{call}"""
    return write_page(d, 5, shell(5, ck.get("headline", ""), body, lang, t["t5"], nxt, fonts_link(b)))


RENDER = {1: brand_page, 2: brief_page, 3: diverge_page, 4: piece_page, 5: check_page}
