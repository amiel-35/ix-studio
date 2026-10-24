"""workflow: who holds the hand on each step of a project, and what waits for the person. The one place it is written.

Both backends (the simulated one and the one that drives scripts/studio and scripts/brandkit) describe a project as
plain data and get its view from here. Nothing in this file touches a disk, a clock other than `now`, or a command.

The state a backend gives (a dict):

    id, name, brand        the project and its brand's name
    can_learn              the studio can search the brand (it has a site to read)
    learned, kept          the brand is learned; the person sorted its visuals
    evidence               how many visuals wait to be sorted
    brief_confirmed        the person read the brief
    mandates_confirmed     the person read the instructions to the agents
    variants               how many variants are written
    pieces                 the pieces (dicts with at least id, label, image, composed, decision), returned as they are
    running                the running jobs: {id, kind, piece, progress, message, start}
    failed                 the last job of a kind that failed and was not run again: {kind, piece, error, at}
    since                  {step: epoch seconds} when the hand last changed on that step
"""

import copy


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


STEPS = [("brand", "Apprendre la marque"), ("brief", "Le brief"), ("mandates", "Les consignes aux agents"),
         ("diverge", "La divergence"), ("image", "Les images"), ("piece", "Les pièces"), ("check", "La vérification"),
         ("decide", "La décision")]
FORMATS = {"post-4x5": (1080, 1350), "post-1x1": (1080, 1080), "story": (1080, 1920), "poster-a3": (1240, 1754),
           "poster-3x2": (1800, 1200), "linkedin": (1200, 627)}
KIND_STEP = {"learn": "brand", "mandates": "mandates", "diverge": "diverge", "image": "image"}


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
    running = s.get("running", [])

    def job_of(kind, piece=None):
        return next((j for j in running if j["kind"] == kind and (piece is None or j.get("piece") == piece)), None)

    def step(key, status, hand, job=None, at=None):
        st[key] = {"key": key, "label": dict(STEPS)[key], "status": status, "hand": hand, "job": job["id"] if job else None,
                   "since": at or since.get(key)}

    def retry(key, piece, title, f):
        asks.append({"step": key, "piece": piece, "kind": "job-failed", "title": title,
                     "question": "Le dernier essai a échoué : " + (f.get("error") or "raison inconnue") + "."})

    j = job_of("learn")
    if j:
        step("brand", "running", "studio", j)
    elif not s["learned"]:
        step("brand", "todo", "person")
        f = failed_of(s, "learn")
        if f:
            retry("brand", None, "Relancer la lecture de la marque", f)
        else:
            asks.append({"step": "brand", "piece": None, "kind": "brand-how", "title": "Choisir comment apprendre la marque",
                         "question": "Comment apprendre la marque : le studio cherche, tu réponds, ou on part de rien ?"})
    elif not s["kept"]:
        step("brand", "waiting", "person")
        n = s["evidence"]
        asks.append({"step": "brand", "piece": None, "kind": "brand-sort", "title": f"Trier {n} visuels de la marque" if n else "Valider une marque sans visuel",
                     "question": f"Garder ou écarter {n} visuels, et choisir le logo."})
    else:
        step("brand", "done", "person")
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
        for pc in pcs:
            if not pc["image"] and not job_of("image", pc["id"]):
                f = failed_of(s, "image", pc["id"])
                if f:
                    retry("image", pc["id"], f"Relancer l'image de {pc['label']}", f)
                else:
                    asks.append({"step": "image", "piece": pc["id"], "kind": "prompt", "title": f"Relire le prompt de {pc['label']}",
                                 "question": f"Relire le prompt de l'image de {pc['label']}, puis la lancer."})
            elif pc["image"] and not pc["composed"]:
                asks.append({"step": "piece", "piece": pc["id"], "kind": "compose", "title": f"Composer et vérifier {pc['label']}",
                             "question": f"Composer et vérifier {pc['label']}."})
            elif pc["composed"] and not pc["decision"]:
                asks.append({"step": "decide", "piece": pc["id"], "kind": "decide", "title": f"Décider de {pc['label']}",
                             "question": f"Garder {pc['label']}, ou recommencer en disant pourquoi."})
        step("piece", "done" if all(pc["composed"] for pc in pcs) else "waiting" if any(pc["image"] for pc in pcs) else "todo", "person")
        step("check", st["piece"]["status"], "studio", at=since.get("piece"))
        step("decide", "done" if all(pc["decision"] for pc in pcs) else "waiting" if any(pc["composed"] for pc in pcs) else "todo", "person")
    jobs = [{"id": j["id"], "kind": j["kind"], "piece": j.get("piece"), "progress": j["progress"], "message": j["message"], "since": j["start"]} for j in running]
    return {"id": s["id"], "name": s["name"], "brand": s["brand"], "can_learn": s.get("can_learn", True),
            "steps": [st[k] for k, _ in STEPS], "pieces": copy.deepcopy(pcs), "waiting": asks, "jobs": jobs, "now": now}


def tasks_payload(entries: list, jobs: list, now: float) -> dict:
    """What waits for the person in every project, the oldest first (stable: the order inside a project is kept), the running jobs
    and the projects. `entries` is a list of (state, view)."""
    tasks, projects = [], []
    for s, v in entries:
        projects.append({"id": s["id"], "name": s["name"], "brand": s["brand"], "can_learn": s.get("can_learn", True), "pieces": len(s["pieces"]), "waiting": len(v["waiting"])})
        for a in v["waiting"]:
            pc = next((x for x in s["pieces"] if x["id"] == a["piece"]), None) if a["piece"] else None
            tasks.append({"id": f"{s['id']}:{a['step']}:{a['piece'] or ''}", "project": s["id"], "project_name": s["name"], "brand": s["brand"],
                          "step": a["step"], "piece": a["piece"], "piece_label": pc["label"] if pc else None, "kind": a["kind"], "title": a["title"],
                          "question": a["question"], "since": s.get("since", {}).get(a["step"])})
    tasks.sort(key=lambda t: (t["since"] is None, t["since"] or 0))
    return {"tasks": tasks, "jobs": jobs, "projects": projects, "now": now}
