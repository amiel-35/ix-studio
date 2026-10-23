"""The review (spec 4.1, step 4): one message, grouped by asset, that lists conflicts, what is inferred and waits
for confirmation, what is missing ("ASK"), what is to create, which visuals need their ownership confirmed, and
which look is the master one when there are several. It never fills a gap: the closest thing found is shown as such.
"""

from fuse import iter_values

GROUPS = [
    ("identity", ("identity.", "audience.", "meta.language")),
    ("promise", ("promise.",)),
    ("voice", ("voice.",)),
    ("colours", ("colours",)),
    ("typography", ("typography",)),
    ("logo", ("logo",)),
    ("imagery", ("imagery.",)),
    ("motion", ("motion.",)),
    ("references", ("references",)),
    ("looks", ("looks",)),
]

T = {
    "en": {
        "title": "Review of the brand dossier", "draft": "draft, not validated", "version": "validated version",
        "how": "Answer in one message: confirm or reject what is inferred, answer the ASK lines, pick the master look, "
               "and say which visuals are or are not the brand's. Nothing below has been filled in for you.",
        "identity": "Who and what", "promise": "Promise (exact words)", "voice": "Voice", "colours": "Colours",
        "typography": "Typography", "logo": "Logo", "imagery": "Imagery", "motion": "Motion", "references": "References",
        "looks": "Looks",
        "conflict": "Conflict", "kept": "kept", "over": "over", "to_confirm": "Inferred, to confirm", "ask": "ASK",
        "to_create": "To create (identity family)", "closest": "closest thing found, not filled in",
        "master": "Several looks were found. Which one is the master look? Nothing is averaged meanwhile.",
        "visuals": "Visuals and pages: are they the brand's?", "visuals_how":
            "Each line is the ownership proposed by the inference. Say \"not the brand's\" for any mistake: what rests only on it leaves the dossier at the next merge.",
        "stale": "Skill changed or unavailable", "stale_line": "{skill}: read at {read}, now {now}. Its values are back to \"to confirm\".",
        "dropped": "Left out (based only on visuals that are not the brand's)", "notes": "What the adapters could not find",
        "ignored": "Ignored on purpose", "none": "Nothing to review here.", "conf": "confidence", "proof": "proof",
        "look": "look", "nothing_left": "Nothing left to review: the dossier can be validated.",
    },
    "fr": {
        "title": "Revue du dossier de marque", "draft": "brouillon, non validé", "version": "version validée",
        "how": "Réponds en un message : confirme ou rejette ce qui est déduit, réponds aux lignes À DEMANDER, choisis le look "
               "maître, et dis quels visuels sont ou ne sont pas de la marque. Rien ci-dessous n'a été rempli à ta place.",
        "identity": "Qui et quoi", "promise": "Promesse (mots exacts)", "voice": "Ton", "colours": "Couleurs",
        "typography": "Typographie", "logo": "Logo", "imagery": "Images", "motion": "Mouvement", "references": "Références",
        "looks": "Looks",
        "conflict": "Conflit", "kept": "retenu", "over": "contre", "to_confirm": "Déduit, à confirmer", "ask": "À DEMANDER",
        "to_create": "À créer (famille identité)", "closest": "le plus proche trouvé, pas rempli",
        "master": "Plusieurs looks trouvés. Lequel est le look maître ? Rien n'est moyenné en attendant.",
        "visuals": "Visuels et pages : sont-ils de la marque ?", "visuals_how":
            "Chaque ligne donne l'appartenance proposée par l'inférence. Dis « pas de la marque » pour toute erreur : ce qui ne repose que sur lui sort du dossier à la fusion suivante.",
        "stale": "Skill changé ou indisponible", "stale_line": "{skill} : lu en {read}, maintenant {now}. Ses valeurs repassent « à confirmer ».",
        "dropped": "Écarté (ne reposait que sur des visuels qui ne sont pas de la marque)", "notes": "Ce que les adaptateurs n'ont pas trouvé",
        "ignored": "Ignoré exprès", "none": "Rien à revoir ici.", "conf": "confiance", "proof": "preuves",
        "look": "look", "nothing_left": "Plus rien à revoir : le dossier peut être validé.",
    },
}


def short(v, n=110):
    if isinstance(v, list):
        v = " · ".join(str(x) for x in v)
    elif isinstance(v, dict):
        v = ", ".join(f"{k}: {x}" for k, x in v.items() if k not in ("master",))
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def render(doc, evidence, review, lang="en"):
    t = T.get(lang, T["en"])
    ev = {e["id"]: e for e in evidence}
    meta = doc["meta"]
    head = f"{t['version']} {meta['version']}" if not meta.get("draft") else t["draft"]
    name = doc["identity"]["name"].get("value") or "?"
    out = [f"# {t['title']} · {name}", "", f"_{head} · {meta.get('generated_at')}_", "", t["how"], ""]
    values = list(iter_values(doc))
    open_items = 0

    if review.get("stale"):
        out += [f"## {t['stale']}", ""]
        out += [f"- {t['stale_line'].format(**s)}" for s in review["stale"]]
        out.append("")
        open_items += len(review["stale"])

    master_q = []
    if review.get("looks"):
        master_q = [f"**{t['master']}**", ""]
        for it in doc["looks"]["items"]:
            master_q.append(f"- `{it['id']}`: {short(it['name'].get('value'))} ({it['kind'].get('value')})"
                            + (f", {t['proof']} {', '.join(it.get('evidence', [])[:4])}" if it.get("evidence") else ""))
        master_q.append("")
        open_items += 1

    for key, prefixes in GROUPS:
        lines = []
        for c in review["conflicts"]:
            if c["path"].startswith(prefixes):
                o = c["other"]
                look = f" ({t['look']} {c['look']})" if c.get("look") else ""
                lines.append(f"- **{t['conflict']}** `{c['path']}`{look}: {t['kept']} {short(c['kept'])} [{c['kept_source']['type']}: {c['kept_source']['origin']}] "
                             f"{t['over']} {short(o['value'])} [{o['source']['type']}: {o['source']['origin']}]")
        grouped = {}
        for path, v in values:
            if not path.startswith(prefixes) or (key == "looks" and path.endswith(".master") and review.get("looks")):
                continue
            st = v.get("status")
            if st == "to_confirm" and "[" in path:
                # one line per list item: its fields read together
                item, _, field = path.rpartition(".")
                if item not in grouped:
                    grouped[item] = {"fields": [], "v": v}
                    lines.append(("item", item))
                grouped[item]["fields"].append(f"{field} {short(v['value'], 70)}")
            elif st == "to_confirm":
                proof = ", ".join(v.get("evidence", [])[:4])
                extra = f" ({t['conf']} {v.get('confidence')}{'; ' + t['proof'] + ' ' + proof if proof else ''})" if v.get("confidence") else ""
                note = f" · {v['note']}" if v.get("note") else ""
                lines.append(f"- {t['to_confirm']} `{path}`: {short(v['value'])}{extra}{note}")
            elif st == "ask":
                hint = ""
                if v.get("closest"):
                    hint = f" ({t['closest']}: {short(v['closest'][0]['value'], 60)})"
                lines.append(f"- **{t['ask']}** `{path}`{hint}")
            elif st == "to_create":
                lines.append(f"- {t['to_create']} `{path}`")
        for i, ln in enumerate(lines):
            if isinstance(ln, tuple):
                g = grouped[ln[1]]
                v = g["v"]
                proof = ", ".join(v.get("evidence", [])[:4])
                extra = f" ({t['conf']} {v.get('confidence')}{'; ' + t['proof'] + ' ' + proof if proof else ''})" if v.get("confidence") else ""
                note = f" · {v['note']}" if v.get("note") else ""
                lines[i] = f"- {t['to_confirm']} `{ln[1]}`: {' · '.join(g['fields'])}{extra}{note}"
        if key == "looks" and master_q:
            out += [f"## {t[key]}", ""] + master_q + lines + ([""] if lines else [])
        elif lines:
            open_items += len(lines)
            out += [f"## {t[key]}", ""] + lines + [""]

    owned = [e for e in evidence if e.get("ownership_status") == "to_confirm"]
    if owned:
        out += [f"## {t['visuals']}", "", t["visuals_how"], ""]
        for e in owned:
            what = e.get("title") or e.get("note") or ""
            page = f" (page {e['page']})" if e.get("page") else ""
            look = f" · {t['look']} {e['look']}" if e.get("look") else ""
            out.append(f"- `{e['id']}` {e['kind']} {e['where']}{page}: **{e['ownership']}**{look}{' · ' + short(what, 80) if what else ''}")
        out.append("")
        open_items += len(owned)

    if review.get("dropped"):
        out += [f"## {t['dropped']}", ""]
        out += [f"- `{d['path']}`: {short(d['value'])} [{d['origin']}]" for d in review["dropped"]]
        out.append("")
    if review.get("notes"):
        out += [f"## {t['notes']}", ""]
        out += [f"- {n['text']} [{n['origin']}]" for n in review["notes"]]
        out.append("")
    if review.get("ignored"):
        out += [f"## {t['ignored']}", ""]
        out += [f"- {short(n.get('what'), 140)}: {n.get('why')} [{n['origin']}]" for n in review["ignored"]]
        out.append("")
    if not open_items:
        out += [t["nothing_left"], ""]
    return "\n".join(out)
