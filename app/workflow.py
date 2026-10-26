"""workflow: who holds the hand on each step of a project, and what waits for the person. The one place it is written.

Both backends (the simulated one and the one that drives scripts/studio and scripts/brandkit) describe a project as
plain data and get its view from here. Nothing in this file touches a disk, a clock other than `now`, or a command.

The state a backend gives (a dict):

    id, name, type         the project and its type (`campagne`, the only one for now)
    brand, brand_name      the brand it belongs to: its id and its name
    brand_stage            the brand's stage (see `brand_stage`); the project's step 1 is done when it is `ready`, or once the project's brief is validated
    brand_job              the brand's running discovery job, if any: {id, kind, piece, progress, message, start}
    brand_waiting          the brand's tasks (see `brand_asks`), to say what the project waits for
    can_learn              the studio can search the brand (it has a site to read)
    brief_confirmed        the person read the brief
    mandates_confirmed     the person read the instructions to the agents
    variants               how many variants are written
    pieces                 the pieces (dicts with at least id, label, image, composed, decision), returned as they are
    running                the running jobs: {id, kind, piece, progress, message, start}
    failed                 the last job of a kind that failed and was not run again: {kind, piece, error, at}
    since                  {step: epoch seconds} when the hand last changed on that step
"""

import copy
import html
import io
import ipaddress
import json
import re
import sys
import unicodedata
import urllib.parse
import zipfile
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "agents"))
from answers import (COMPETITOR_HEAD, INTERVIEW_KEYS, INTERVIEW_QUESTIONS, parse_interview, COMPETITORS_MAX, JUDGE_BRIEF, JUDGE_ITEMS, JUDGE_LISTS, JUDGE_NEEDED, JUDGE_REACHED, NAMES_MAX, PERSONA_FROM,  # noqa: E402,F401
                     PERSONA_HEAD, PERSONAS_MAX, READING_AIMED, READING_KEYS, _name_item, judge_missing, one_line, parse_competitors, parse_names,  # noqa: F401
                     parse_personas, parse_reading, parse_verdict)  # the checks of what the agents answer live with the commands (scripts/agents)


class NotFound(Exception):
    pass


class Download(NamedTuple):
    """What a download route answers instead of JSON: the file itself (its type, its name, its bytes). The server sends it as an attachment."""
    name: str
    ctype: str
    data: bytes


class Conflict(Exception):
    pass


STEPS = [("brand", "La marque de ce projet"), ("brief", "Le brief"), ("mandates", "Les consignes aux agents"),
         ("diverge", "La divergence"), ("image", "Les images"), ("piece", "Les pièces"), ("check", "La vérification"),
         ("decide", "La décision")]
FORMATS = {"post-4x5": (1080, 1350), "post-1x1": (1080, 1080), "story": (1080, 1920), "poster-a3": (1240, 1754),
           "poster-3x2": (1800, 1200), "linkedin": (1200, 627)}
SEVEN = [("brand", "La marque"), ("brief", "Le brief"), ("mandates", "Les consignes"), ("diverge", "La divergence"), ("image", "Les images"),
         ("piece", "La composition"), ("decide", "La décision")]  # the seven steps the interface counts (check belongs to piece)
KIND_STEP = {"learn": "brand", "mandates": "mandates", "diverge": "diverge", "image": "image", "judge": "check", "reader": "check", "personas": "brand", "names": "brand", "competitors": "brand", "interview": "brief"}


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:32]


def fmt_key(token: str) -> str:
    return token.strip().lower().replace(" ", "-")


def formats_of(raw: str) -> list:
    """The formats of a brief's `format` line that the studio can make (post-4x5 when none is)."""
    return [f for f in (fmt_key(x) for x in (raw or "").split(",")) if f in FORMATS] or ["post-4x5"]


def left_out_of(raw: str) -> list:
    """The formats of the line that it puts aside (a film, for instance): said to the person, never lost."""
    return [x.strip() for x in (raw or "").split(",") if x.strip() and fmt_key(x) not in FORMATS]


def failed_of(s, kind, piece=None):
    return next((f for f in s.get("failed", []) if f["kind"] == kind and (piece is None or f.get("piece") == piece)), None)


def project_view(s: dict, now: float) -> dict:
    """The project as the interface reads it: its steps, its pieces, what waits for the person, the running jobs."""
    st, asks = {}, []
    since = s.get("since", {})
    running = [j for j in s.get("running", []) if j["kind"] != "learn"]

    def job_of(kind, piece=None):
        return next((j for j in running if j["kind"] == kind and (piece is None or j.get("piece") == piece)), None)

    def step(key, status, hand, job=None, at=None):
        st[key] = {"key": key, "label": dict(STEPS)[key], "status": status, "hand": hand, "job": job["id"] if job else None,
                   "since": at or since.get(key)}

    def retry(key, piece, title, f):
        asks.append({"step": key, "piece": piece, "kind": "job-failed", "title": title,
                     "question": "Le dernier essai a échoué : " + (f.get("error") or "raison inconnue") + "."})

    # Step 1, one rule: the brand of the project is ready (a logo, nothing left to confirm). Otherwise the hand is on the
    # brand's side: its own tasks (sort, brief, confirm) are in the list, not in the project's, and step 2 waits.
    # Once the project's brief is validated, the brand it uses is fixed in its piece: a brand that changes afterwards
    # (a new site read, a value to confirm) does not send an advanced project back to step 1.
    bj = s.get("brand_job")
    if s.get("brand_ready") or s.get("brief_confirmed"):
        step("brand", "done", "person")
    elif bj:
        step("brand", "running", "studio", bj)
    else:
        step("brand", "waiting", "person")
    prev = st["brand"]["status"] == "done"
    if not prev:
        step("brief", "todo", "person")
    elif not s["brief_confirmed"]:
        step("brief", "waiting", "person")
        asks.append({"step": "brief", "piece": None, "kind": "brief", "title": "Relire le brief", "question": "Relire le brief pré-rempli et corriger ce qui change."})
    else:
        step("brief", "done", "person")
    j = job_of("mandates")
    if st["brief"]["status"] != "done":
        step("mandates", "todo", "person")
    elif j:
        step("mandates", "running", "studio", j)
    elif not s["mandates_confirmed"]:
        step("mandates", "waiting", "person")
        asks.append({"step": "mandates", "piece": None, "kind": "mandates", "title": "Relire les consignes aux agents",
                     "question": "Relire les consignes que les agents vont recevoir, et les corriger."})
    else:
        step("mandates", "done", "person")
    pcs = s["pieces"]
    j = job_of("diverge")
    if j:
        step("diverge", "running", "studio", j)
    elif st["mandates"]["status"] != "done" or not s["variants"]:
        step("diverge", "todo", "person")
        if st["mandates"]["status"] == "done":
            f = failed_of(s, "diverge")
            if f:
                retry("diverge", None, "Relancer la divergence", f)
            else:
                asks.append({"step": "diverge", "piece": None, "kind": "diverge-launch", "title": "Lancer la divergence",
                             "question": "Lancer la divergence : quatre agents écrivent chacun leur variante."})
    elif not pcs:
        step("diverge", "waiting", "person")
        asks.append({"step": "diverge", "piece": None, "kind": "diverge-pick", "title": "Choisir les variantes",
                     "question": "Choisir une ou plusieurs variantes : chacune devient une pièce par format."})
    else:
        step("diverge", "done", "person")
    for key in ("image", "piece", "check", "decide"):
        if not pcs:
            step(key, "todo", "person")
    if pcs:
        imgs = [job_of("image", pc["id"]) for pc in pcs]
        if any(imgs):
            step("image", "running", "studio", next(x for x in imgs if x))
        elif all(pc["image"] for pc in pcs):
            step("image", "done", "studio")
        else:
            step("image", "waiting", "person")
        prompts = {}  # one prompt task per variant: its formats share the prompt, and the image of each is drawn from it
        for pc in pcs:
            if not pc["image"] and not job_of("image", pc["id"]):
                f = failed_of(s, "image", pc["id"])
                if f:
                    retry("image", pc["id"], f"Relancer l'image de {pc['label']}", f)
                else:
                    vid = pc.get("variant") or pc["id"]
                    if vid not in prompts:
                        prompts[vid] = {"step": "image", "piece": pc["id"], "variant": vid, "pieces": [], "kind": "prompt"}
                        asks.append(prompts[vid])  # where its first piece stands in the list
                    prompts[vid]["pieces"].append(pc["id"])
            elif pc["image"] and not pc["composed"]:
                asks.append({"step": "piece", "piece": pc["id"], "kind": "compose", "title": f"Composer et vérifier {pc['label']}",
                             "question": f"Composer et vérifier {pc['label']}."})
            elif pc["composed"] and not pc["decision"]:
                asks.append({"step": "decide", "piece": pc["id"], "kind": "decide", "title": f"Décider de {pc['label']}",
                             "question": f"Garder {pc['label']}, ou recommencer en disant pourquoi."})
            if pc["composed"] and not job_of("judge", pc["id"]) and (pc.get("judge") or {}).get("status") != "done":
                f = failed_of(s, "judge", pc["id"])  # the judge blocks nothing: its failure is one more task, beside the decision
                if f:
                    retry("check", pc["id"], f"Relancer le juge de {pc['label']}", f)
        for vid, a in prompts.items():
            n = len(a["pieces"])
            a["title"] = f"Relire le prompt de {vid}" + (f" ({n} formats)" if n > 1 else "")
            a["question"] = f"Relire le prompt de l'image de {vid}" + (f", le même pour ses {n} formats" if n > 1 else "") + ", puis la lancer."
        step("piece", "done" if all(pc["composed"] for pc in pcs) else "waiting" if any(pc["image"] for pc in pcs) else "todo", "person")
        step("check", st["piece"]["status"], "studio", at=since.get("piece"))
        step("decide", "done" if all(pc["decision"] for pc in pcs) else "waiting" if any(pc["composed"] for pc in pcs) else "todo", "person")
    jobs = [{"id": j["id"], "kind": j["kind"], "piece": j.get("piece"), "progress": j["progress"], "message": j["message"], "since": j["start"]} for j in running]
    return {"id": s["id"], "name": s["name"], "type": s.get("type", "campagne"), "brand": s["brand"], "brand_name": s.get("brand_name", ""),
            "brand_stage": s.get("brand_stage"), "brand_waiting": [{"kind": a["kind"], "title": a["title"]} for a in s.get("brand_waiting", [])],
            "can_learn": s.get("can_learn", True), "steps": [st[k] for k, _ in STEPS], "pieces": copy.deepcopy(pcs), "waiting": asks,
            "jobs": jobs, "now": now}


def rank_of(steps: dict) -> tuple:
    """(rank, label): the step of the seven in progress (the first that is not done), from the `steps` of project_view (a list).
    All done: the last."""
    by = {x["key"]: x for x in steps}
    for n, (key, label) in enumerate(SEVEN, 1):
        if by[key]["status"] != "done":
            return n, label
    return len(SEVEN), SEVEN[-1][1]


def project_summary(view: dict) -> dict:
    """The line of a project inside its brand: `{id, name, type, rank, step_label, done, waiting}` (`rank`: the step in progress, out of seven;
    `done`: all seven are done, which `rank` alone cannot tell from the last one in progress)."""
    rank, label = rank_of(view["steps"])
    by = {x["key"]: x for x in view["steps"]}
    done = all(by[k]["status"] == "done" for k, _ in SEVEN)
    return {"id": view["id"], "name": view["name"], "type": view.get("type", "campagne"), "rank": rank, "step_label": label, "done": done,
            "waiting": len(view["waiting"])}


# ---------------------------------------------------------------- the brand
# One brand, many projects. The brand is learned once (a site read, visuals sorted, a brief of the brand, what is deduced
# confirmed); its projects use it. The state a backend gives (a dict):
#
#     id, name, site         the brand and its site ("" when none)
#     discovered, kept       the site was read; the person sorted the visuals and chose the logo
#     logo                   a logo is chosen
#     brief_done             the person filled in (or read) the brief of the brand
#     migrated               the brand came out of several projects of the old format: it is to confirm until the person does
#     deduced                the keys (FIELDS, `logo`) whose value was deduced and is not confirmed
#     unsorted               how many visuals wait to be sorted
#     colours_ok             the brand has the colours a piece needs: at least two, one for the background and one for the text
#     running                the running discovery job (or None)
#     failed                 the last discovery failed and was not run again: {error, at} (or None)
#     since                  {task kind: epoch seconds} when each task came to the person

BRAND_STAGES = ("new", "discovering", "to_sort", "to_brief", "to_confirm", "ready")
FIELDS = [("what", "ce qu'elle est"), ("who", "pour qui"), ("voice", "sa voix"), ("signature", "sa signature"),
          ("never", "ce qu'elle ne dit jamais"), ("colours", "ses couleurs")]
FIELD_KEYS = [k for k, _ in FIELDS]
CONFIRMABLE = FIELD_KEYS + ["logo"]
LABEL = dict(FIELDS, logo="son logo")
FIELD_STATES = ("absent", "deduced", "confirmed")


def field(value="", state="absent", source=""):
    """A value of the brand's identity: what it says, how sure it is (absent, deduced or confirmed) and where it comes from."""
    if state not in FIELD_STATES:
        raise ValueError(f"state is one of {', '.join(FIELD_STATES)}")
    return {"value": value if state != "absent" else "", "state": state, "source": source if state != "absent" else ""}


def identity_of(values: dict) -> dict:
    """The six fields of the identity, each present: those the backend does not give are absent."""
    return {k: values.get(k) or field() for k in FIELD_KEYS}


def split_words(text) -> list:
    """The words of a `voice` or `never` field: separated by commas, semicolons or lines."""
    return [w.strip() for w in re.split(r"[,;\n]+", str(text or "")) if w.strip()]


def brand_stage(b: dict) -> str:
    """Where the brand stands. The first that holds:

    discovering   a discovery job runs
    to_sort       the site was read and the visuals are not sorted, or no logo is chosen yet
    new           no site, nothing read, no brief: nothing at all yet
    to_brief      the brief of the brand is not done (or there is no logo and nothing to sort it from: a site is needed, or the
                  colours are not enough: a background and a text colour)
    to_confirm    values were deduced and not confirmed (or the brand is migrated and the person has not looked)
    ready         a logo, a background and a text colour, nothing to confirm
    """
    if b.get("running"):
        return "discovering"
    if b.get("discovered") and (not b.get("kept") or not b.get("logo")):
        return "to_sort"
    if not b.get("brief_done"):
        return "new" if not b.get("site") and not b.get("discovered") else "to_brief"
    if b.get("deduced") or b.get("migrated"):
        return "to_confirm"
    if not b.get("logo") or not b.get("colours_ok"):
        return "to_brief"
    return "ready"


def brand_needs(b: dict) -> list:
    """What a brand still lacks to be ready, beside the brief and the confirmations: `logo`, `colours` (a background and a text colour)."""
    return [k for k, ok in (("logo", b.get("logo")), ("colours", b.get("colours_ok"))) if not ok]


def brand_ready(b: dict) -> bool:
    return brand_stage(b) == "ready"


def brand_asks(b: dict) -> list:
    """What waits for the person on the brand: `{kind, title, question}`, `kind` in brand-sort, brand-brief, brand-confirm, job-failed.
    A failed discovery comes first (running it again makes it go); then the task of the stage. The titles say "la marque": the brand's
    name is beside them (`brand_name`)."""
    asks, stage = [], brand_stage(b)
    f = b.get("failed")
    if f and stage != "discovering":
        asks.append({"kind": "job-failed", "title": "Relancer la lecture du site de la marque",
                     "question": "Le dernier essai a échoué : " + (f.get("error") or "raison inconnue") + "."})
    if stage == "to_sort":
        n = b.get("unsorted", 0)
        if n:
            asks.append({"kind": "brand-sort", "title": f"Trier {n} visuels de la marque", "question": f"Garder ou écarter {n} visuels, et choisir le logo."})
        else:
            asks.append({"kind": "brand-sort", "title": "Choisir le logo de la marque",
                         "question": "Aucun logo n'est choisi : en prendre un parmi ceux trouvés, ou relancer la lecture du site."})
    elif stage in ("new", "to_brief"):
        if b.get("brief_done") and not b.get("logo"):  # nothing left but the logo, and nothing to sort it from
            asks.append({"kind": "brand-brief", "title": "Trouver le logo de la marque",
                         "question": "La marque n'a pas de logo : déposer son fichier, ou donner l'adresse de son site pour que le studio le cherche."})
        elif b.get("brief_done"):  # a logo, and not the two colours a piece needs
            asks.append({"kind": "brand-brief", "title": "Choisir les couleurs de la marque",
                         "question": "Il faut au moins deux couleurs : une pour le fond, une pour le texte (un accent en plus, si elle en a un)."})
        else:
            asks.append({"kind": "brand-brief", "title": "Écrire le brief de la marque",
                         "question": "Dire ce qu'elle est, pour qui, sa voix, sa signature et ce qu'elle ne dit jamais. Le studio a pré-rempli ce qu'il a trouvé."})
    elif stage == "to_confirm":
        what = ", ".join(LABEL[k] for k in b.get("deduced", []))
        look = "Elle vient de plusieurs projets : la regarder" + (", et confirmer ce que le studio a déduit (" + what + ")." if what else " et la confirmer.") if b.get("migrated") \
            else f"Confirmer ce que le studio a déduit : {what}."
        asks.append({"kind": "brand-confirm", "title": "Confirmer la marque", "question": look})
    return asks


def brand_tasks(b: dict) -> list:
    """The tasks of the brand as the list `GET /api/tasks` shows them. `id` is `@<brand>:<kind>`: it stays the same as long as the task waits."""
    return [{"id": f"@{b['id']}:{a['kind']}", "scope": "brand", "brand": b["id"], "brand_name": b["name"], "project": None, "kind": a["kind"],
             "title": a["title"], "question": a["question"], "since": b.get("since", {}).get(a["kind"])} for a in brand_asks(b)]


def brand_payload(b: dict, meta: dict, identity: dict, assets: dict, projects: list, jobs: list, now: float) -> dict:
    """The brand as the interface reads it. `meta`: description and the like, given by the backend."""
    return {"id": b["id"], "name": b["name"], "site": b.get("site", ""), "description": meta.get("description", ""), "stage": brand_stage(b),
            "can_discover": bool(b.get("site")), "identity": identity_of(identity), "assets": assets, "projects": projects,
            "waiting": brand_tasks(b), "jobs": jobs, "now": now}


def brand_line(b: dict, projects: list) -> dict:
    """The brand in the list of brands: its stage, its projects in short, the number of its tasks."""
    return {"id": b["id"], "name": b["name"], "site": b.get("site", ""), "stage": brand_stage(b), "projects": projects, "waiting": len(brand_asks(b))}


def tasks_payload(entries: list, jobs: list, now: float, brands: list = ()) -> dict:
    """What waits for the person, the oldest first (stable: the order inside a project is kept), the running jobs, the projects
    and the brands. `entries` is a list of (project state, view); `brands` a list of (brand state, its projects in short)."""
    tasks, projects, brand_lines = [], [], []
    for b, pro in brands:
        tasks += brand_tasks(b)
        brand_lines.append(brand_line(b, pro))
    for s, v in entries:
        projects.append({"id": s["id"], "name": s["name"], "brand": s["brand"], "brand_name": s.get("brand_name", ""), "can_learn": s.get("can_learn", True),
                         "pieces": len(s["pieces"]), "waiting": len(v["waiting"])})
        for a in v["waiting"]:
            pc = next((x for x in s["pieces"] if x["id"] == a["piece"]), None) if a["piece"] else None
            t = {"id": f"{s['id']}:{a['step']}:{a['piece'] or ''}", "scope": "project", "project": s["id"], "project_name": s["name"],
                 "brand": s["brand"], "brand_name": s.get("brand_name", ""), "step": a["step"], "piece": a["piece"],
                 "piece_label": a.get("variant") or (pc["label"] if pc else None), "kind": a["kind"], "title": a["title"],
                 "question": a["question"], "since": s.get("since", {}).get(a["step"])}
            if a.get("variant"):  # a prompt: the task of a variant, for the pieces of it that wait for their image
                t.update(variant=a["variant"], pieces=a["pieces"])
            tasks.append(t)
    tasks.sort(key=lambda t: (t["since"] is None, t["since"] or 0))
    return {"tasks": tasks, "jobs": jobs, "projects": projects, "brands": brand_lines, "now": now}


COLOUR_ROLES = ("background", "text", "accent")
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def luminance(h: str) -> float:
    rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def parse_palette(raw) -> list:
    """The colours a person chose with the pickers, `[{hex, role}]`, checked: a background and a text colour that differ (an accent is optional),
    each role once, each colour as #rrggbb. Returns the list in the order background, text, accent, hex in lower case; a ValueError (a 400) says what is wrong."""
    if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
        raise ValueError("colours: a list of {hex, role}")
    by = {}
    for x in raw:
        role, h = x.get("role"), str(x.get("hex") or "")
        if role not in COLOUR_ROLES:
            raise ValueError(f"colours: a role is one of {', '.join(COLOUR_ROLES)}")
        if not HEX.fullmatch(h):
            raise ValueError("colours: a colour is #rrggbb")
        if role in by:
            raise ValueError(f"colours: {role} is given twice")
        by[role] = h.lower()
    for role in ("background", "text"):
        if role not in by:
            raise ValueError("colours: a background and a text colour are needed (an accent is optional)")
    if by["background"] == by["text"]:
        raise ValueError("colours: the text colour must differ from the background")
    return [{"hex": by[r], "role": r} for r in COLOUR_ROLES if r in by]


def palette_of(colours) -> dict:
    """What the studio proposes for the pickers, from the colours a brand has (`[{hex, role}]`): `{background, text, accent}`, each a hex or None.
    A colour that carries one of the three roles keeps it; of the others, the lightest is the background and the one that reads best on it is the
    text. An accent is never guessed."""
    out, rest = {r: None for r in COLOUR_ROLES}, []
    for c in colours or []:
        h = str(c.get("hex") or "").lower()
        if not HEX.fullmatch(h):
            continue
        if c.get("role") in COLOUR_ROLES and out[c["role"]] is None:
            out[c["role"]] = h
        elif h not in rest:
            rest.append(h)
    rest = [h for h in rest if h not in out.values()]
    if out["background"] is None and rest:
        if out["text"] is None and len(rest) == 1:
            only = rest.pop()
            out["background" if luminance(only) > .5 else "text"] = only
        else:
            out["background"] = max(rest, key=luminance)
            rest.remove(out["background"])
    if out["text"] is None and rest:
        ref = out["background"]
        out["text"] = max(rest, key=lambda h: contrast(h, ref)) if ref else min(rest, key=luminance)
    return out


# the tools the studio asks of the machine, in the order they are told, and what to do when one is missing (said to the person, in the studio's column)
MACHINE = [("chrome", "Chrome", "le studio s'en sert pour lire un site et pour composer une pièce. Installe Google Chrome (ou donne son chemin dans CHROME)."),
           ("claude", "Claude Code", "il écrit les consignes et les variantes. Installe Claude Code (la commande claude), puis connecte-toi."),
           ("image", "Un moteur d'image", "il dessine les images. Installe Codex et connecte-toi, ou donne OPENAI_API_KEY (ou OPENROUTER_API_KEY).")]


def machine_view(found: dict) -> dict:
    """What the machine lacks: `{ok, missing: [{key, label, say}]}`, from `found` (`chrome`, `claude`, `image`: each present or not)."""
    missing = [{"key": k, "label": label, "say": say} for k, label, say in MACHINE if not found.get(k)]
    return {"ok": not missing, "missing": missing}


def zip_of(files) -> bytes:
    """A zip (the standard library's) of `[(name, bytes)]`: the pieces are png files, already compressed, so they are stored as they are."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for name, data in files:
            z.writestr(name, data)
    return buf.getvalue()


LOGO_MAX = 2 * 1024 * 1024  # bytes: a logo is a small file
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg"}


def logo_ext(data: bytes, ctype: str = "") -> str:
    """The extension (`png`, `jpg` or `svg`) of a logo file that was dropped, or a ValueError (a 400) saying what is wrong. The type given by
    the browser must be one of the three and the content must really be it (the first bytes, for a picture; a `<svg` root without script, for
    a drawing), so that nothing else is ever stored under the name of a logo."""
    ext = LOGO_TYPES.get((ctype or "").split(";")[0].strip().lower())
    if not ext:
        raise ValueError("logo: a png, jpg or svg file")
    if not data:
        raise ValueError("logo: the file is empty")
    if len(data) > LOGO_MAX:
        raise ValueError(f"logo: the file is too big ({LOGO_MAX // (1024 * 1024)} MB at most)")
    if ext == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("logo: this is not a png file")
    if ext == "jpg" and not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("logo: this is not a jpg file")
    if ext == "svg":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("logo: this is not an svg file") from None
        low = text.lower()
        if "<svg" not in low:
            raise ValueError("logo: this is not an svg file")
        if "<script" in low or "javascript:" in low or "<!entity" in low or "<foreignobject" in low or re.search(r"\son[a-z]+\s*=", low):
            raise ValueError("logo: an svg with a script or an external entity is refused")
    return ext


def normalise_site(raw: str) -> str:
    """The address of a brand's site, as https://host/path, or "" when none is given. Refuses what is not a public web address."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    u = urllib.parse.urlsplit(raw)
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host:
        raise ValueError("site: give a web address (https://…)")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        local = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    else:
        local = host == "localhost" or host.endswith((".local", ".localhost", ".internal")) or "." not in host
    if local:
        raise ValueError("site: a private or local address cannot be read")
    port = f":{u.port}" if u.port else ""
    return urllib.parse.urlunsplit((u.scheme, host + port, u.path or "/", u.query, ""))  # no credentials, no fragment


# ---------------------------------------------------------------- the judge
# One judge, five headings, in words, without a score. It reads the brief, the piece (its image and its words) and the brand's voice when there
# is one. It blocks nothing, nothing starts after it, and it does not judge the morals of the brand or of its product. Both backends give it the
# same entries and read its answer with `parse_verdict`: the agent of the real one writes it, the simulated one has a fixed one.
#
# A verdict (what the API gives, and what the agent writes, as JSON):
#
#     target      {reached, why}: the person aimed at is reached (`yes`), partly (`partly`) or not (`no`), and why, from their point of view;
#                 `unjudgeable` when the brief does not say who it is for ("non jugeable sur la cible : il manque la cible")
#     works       what works: [{where, say}]
#     snags       what catches: a double meaning, a hierarchy that does not read, a cliché, an image that does not answer the headline
#     unsourced   a fact one could check (a figure, a label, a guarantee, a dated promise, a ranking) that is in none of the entries: not false,
#                 only nothing was given to believe it. The price, the product's name or the town are not aimed at
#     brand       the voice and the tone, only when the brand is known (null otherwise); colours, type, contrast, banned words, hierarchy and
#                 signature stay with the mechanical checks
#     missing     what the brief lacks, in words (["la cible", "le message"]): the rest is judged all the same
#
# Every annotation says what it aims at in words ("le titre en haut", "le bandeau du bas"), never with a drawn zone.

JUDGE_MAX = 10 * 1024 * 1024  # bytes: a piece dropped to be judged (a png or a jpg)
JUDGE_TYPES = {"image/png": "png", "image/jpeg": "jpg"}


def judge_brief(raw) -> dict:
    """The brief a judge reads, from what the person filled in (or a project's brief): the five keys, one line each, and the personas its readers
    take (see the readers, below; the judge does not read them). Unknown keys are left out."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError("brief: an object")
    return {**{k: one_line(raw.get(k))[:600] for k, _ in JUDGE_BRIEF}, "personas": brief_personas_of(raw.get("personas"))}


REACHED_WORDS = {"yes": "atteinte", "partly": "en partie", "no": "pas atteinte", "unjudgeable": "non jugeable"}
JUDGE_HEADINGS = [("works", "Ce qui marche"), ("snags", "Ce qui accroche"), ("unsourced", "Sans provenance"), ("brand", "La marque")]


def judge_md(v: dict) -> str:
    """judge.md, the notes `studio check` reads beside its mechanical checks: one line per annotation, never marked major (the judge blocks nothing)."""
    lines = [f"- cible, {REACHED_WORDS[v['target']['reached']]} : {v['target']['why']}"]
    for k, label in JUDGE_HEADINGS:
        for n in v.get(k) or []:
            lines.append(f"- {label.lower()}, {n['where']} : {n['say']}")
    if v.get("missing"):
        lines.append("- brief incomplet : il manque " + ", ".join(v["missing"]))
    return "# Notes du juge\n\n" + "\n".join(lines) + "\n"


def judge_page(v: dict, image: str, title: str, brand_name: str = "", when: str = "") -> str:
    """The flat page of a judgement: the piece at the top, the list under it. `image` is its address (a data: URI keeps the page whole on its own).
    It takes the design system's tokens when it is opened from the studio, and stays readable without them."""
    e = html.escape
    def items(k):
        ns = v.get(k) or []
        return "".join(f"<li><span class=\"cap\">{e(n['where'])}</span> {e(n['say'])}</li>" for n in ns) or "<li class=\"muted\">Rien à signaler.</li>"
    rows = [f"<section><h2>La cible</h2><p><strong>{e(REACHED_WORDS[v['target']['reached']].capitalize())}.</strong> {e(v['target']['why'])}</p></section>"]
    rows += [f"<section><h2>{label}</h2><ul>{items(k)}</ul></section>" for k, label in JUDGE_HEADINGS if k != "brand" or v.get("brand") is not None]
    if v.get("missing"):
        rows.insert(0, f"<p class=\"muted\">Brief incomplet : il manque {e(', '.join(v['missing']))}. Le reste est jugé.</p>")
    sub = " · ".join(x for x in (brand_name, when) if x)
    return ("<!doctype html>\n<html lang=\"fr\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{e(title)}</title><link rel=\"stylesheet\" href=\"/ds/tokens.css\"><style>"
            "body{margin:0;background:var(--surface-page,#fff);color:var(--text-body,#222);font-family:var(--font-body,system-ui,sans-serif);line-height:1.5}"
            "main{max-width:640px;margin:0 auto;padding:32px 16px}h1{font-family:var(--font-display,inherit);font-size:var(--fs-h3,1.5rem);margin:0 0 4px}"
            "h2{font-size:var(--fs-caption,.8rem);text-transform:uppercase;letter-spacing:.06em;color:var(--text-muted,#666);margin:24px 0 8px}"
            "img{display:block;max-width:100%;border:1px solid var(--border-subtle,#ddd);margin:16px 0}ul{list-style:none;padding:0;margin:0}"
            "li{padding:8px 0;border-top:1px solid var(--border-subtle,#eee)}.cap{display:block;font-size:var(--fs-small,.85rem);color:var(--text-muted,#666)}"
            ".muted{color:var(--text-muted,#666)}p{margin:0}</style></head><body><main>"
            f"<h1>{e(title)}</h1>" + (f"<p class=\"muted\">{e(sub)}</p>" if sub else "") + f"<img src=\"{e(image)}\" alt=\"La pièce jugée\">"
            + "".join(rows) + "</main></body></html>\n")


def judge_image_ext(data: bytes, ctype: str = "") -> str:
    """The extension (`png` or `jpg`) of a piece dropped to be judged, or a ValueError (a 400): the type given by the browser must be one of the two
    and the first bytes must agree, the file not empty and not too big. Like a logo, without the svg."""
    ext = JUDGE_TYPES.get((ctype or "").split(";")[0].strip().lower())
    if not ext:
        raise ValueError("piece: a png or jpg file")
    if not data:
        raise ValueError("piece: the file is empty")
    if len(data) > JUDGE_MAX:
        raise ValueError(f"piece: the file is too big ({JUDGE_MAX // (1024 * 1024)} MB at most)")
    if ext == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("piece: this is not a png file")
    if ext == "jpg" and not data.startswith(b"\xff\xd8\xff"):
        raise ValueError("piece: this is not a jpg file")
    return ext


def judge_meta(raw) -> dict:
    """What comes with a piece dropped to be judged (the `X-Judge` header, JSON): `{name?, brand?, brief}`, checked."""
    if raw in (None, ""):
        raw = {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise ValueError("X-Judge: JSON {name, brand, brief}") from None
    if not isinstance(raw, dict):
        raise ValueError("X-Judge: JSON {name, brand, brief}")
    brand = raw.get("brand") or None
    if brand is not None and not re.fullmatch(r"[\w-]+", str(brand)):
        raise ValueError("brand: an id of a brand")
    return {"name": one_line(raw.get("name"))[:120], "brand": brand, "brief": judge_brief(raw.get("brief"))}


def judge_view(job_status, verdict, error=None) -> dict:
    """Where the judge of a piece stands, for the interface: `{status, verdict, error}`; `status` is `running`, `done` or `failed`."""
    return {"status": job_status, "verdict": verdict, "error": error}


# ---------------------------------------------------------------- the readers
# A brief may name one to four personas, written by the person. Each one is a reader: the piece read by that persona, in "I", in a call of its own
# (it sees neither the brief nor the other readers). It says whether the piece aims at it, what it understands, keeps, does not read, misses and
# what bothers it; never whether it would buy. The readings are shown side by side, without a synthesis. The judge stays as it is beside them.
#
#     aimed       does the piece aim at me: `yes`, `partly` or `no`
#     why         why, in "I"
#     understand  what I understand
#     retain      what I keep
#     bother      what bothers me
#     unread      what I do not read
#     lacks       what I miss

def brief_personas_of(raw) -> list:
    """The personas of a brief: a list of one to four free texts (the empty ones left out), or a ValueError."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError("personas: a list of texts")
    out = [one_line(x)[:1200] for x in raw if one_line(x)]
    if len(out) > PERSONAS_MAX:
        raise ValueError(f"personas: {PERSONAS_MAX} at most")
    return out


# ---------- the personas of a brand: proposed by an agent from what the studio knows, corrected and kept by the person ----------
def personas_of(raw) -> list:
    """The personas the person keeps (`PUT personas`): a list of texts, at most four; the empty ones are dropped."""
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError("personas: a list of texts")
    out = [x.strip()[:3000] for x in raw if x.strip()]
    if len(out) > PERSONAS_MAX:
        raise ValueError(f"personas: {PERSONAS_MAX} at most")
    return out


def reader_view(n: int, persona: str, job, saved) -> dict:
    """Where reader `n` stands: `running`, `done` (its reading), `failed` (the reason) or `todo` (never read, or its persona changed since).
    `job` is its last job (`{id, status, error}`) or None, `saved` what it wrote last (`{persona, reading}`) or None."""
    if job and job["status"] == "running":
        return {"n": n, "persona": persona, "status": "running", "reading": None, "error": None, "job": job["id"]}
    if isinstance(saved, dict) and saved.get("persona") == persona and saved.get("reading"):
        return {"n": n, "persona": persona, "status": "done", "reading": saved["reading"], "error": None, "job": None}
    if job and job["status"] == "failed":
        return {"n": n, "persona": persona, "status": "failed", "reading": None, "error": job.get("error"), "job": None}
    return {"n": n, "persona": persona, "status": "todo", "reading": None, "error": None, "job": None}


# ---------- the names of a brand: proposed by an agent from its brief, kept or dropped by the person, one of the kept chosen as its name ----------


def names_of(raw) -> list:
    """The names the person keeps (`PUT names`): a list of `{name, why}`, at most eight; the empty names and the repeated ones are dropped."""
    if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
        raise ValueError("names: a list of {name, why}")
    out, seen = [], set()
    for it in map(_name_item, raw):
        if it["name"] and it["name"].casefold() not in seen:
            seen.add(it["name"].casefold())
            out.append(it)
    if len(out) > NAMES_MAX:
        raise ValueError(f"names: {NAMES_MAX} at most")
    return out


def chosen_of(chosen, names: list):
    """The name chosen among the kept ones (`PUT names` `chosen`), or None when nothing is chosen; a ValueError when it is not kept."""
    if chosen is None:
        return None
    name = one_line(chosen)
    if not any(x["name"] == name for x in names):
        raise ValueError("chosen: one of the names kept")
    return name


# ---------- competitors: the competitors of a brand, proposed by an agent from what the studio knows, corrected and kept by the person ----------
def competitors_of(raw) -> list:
    """The competitors the person keeps (`PUT competitors`): a list of texts, at most six; the empty ones are dropped."""
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError("competitors: a list of texts")
    out = [x.strip()[:2000] for x in raw if x.strip()]
    if len(out) > COMPETITORS_MAX:
        raise ValueError(f"competitors: {COMPETITORS_MAX} at most")
    return out


# ---------- interview: a few questions, the brief of the project pre-filled from the answers, read and corrected by the person ----------
def interview_answers_of(raw) -> list:
    """The answers the person gives (`POST interview`): a list of texts, one per question, five at most, at least one said."""
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw) or len(raw) > len(INTERVIEW_QUESTIONS):
        raise ValueError(f"answers: a list of {len(INTERVIEW_QUESTIONS)} texts at most")
    out = [x.strip()[:1000] for x in raw]
    if not any(out):
        raise ValueError("answers: answer at least one question")
    return out
