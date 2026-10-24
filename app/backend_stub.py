"""backend_stub: a simulated studio behind the API, for building the interface without the production backend.

Nothing is generated and no model is called: the brand, the variants and the pieces are fixed fictional data
(Marrowbay Ferments, the public example), and the long steps (learning the brand, the divergence, the image) are
jobs whose progress follows the clock. The real backend will have the same methods, driving scripts/studio and
scripts/brandkit instead.
"""

import copy
import itertools
import threading
import time
import urllib.parse

import workflow
from workflow import FORMATS, STEPS, Conflict, NotFound  # noqa: F401  (the server imports the exceptions from here too)

DURATION = {"learn": 4.0, "diverge": 6.0, "image": 8.0}  # seconds: long enough to see a progress, short enough to demo


def placeholder(label, w=320, h=400, dark=False):
    """A neutral placeholder picture with its label, as a data URI: stands for a visual the real studio finds."""
    bg, ink = ("#1E2A3A", "#F5F7FA") if dark else ("#E8EEF7", "#1E2A3A")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
           f"<rect width='100%' height='100%' fill='{bg}'/><rect x='12' y='12' width='{w - 24}' height='{h - 24}' fill='none' stroke='{ink}' stroke-opacity='.25'/>"
           f"<text x='24' y='{h - 28}' font-family='sans-serif' font-size='15' fill='{ink}'>{label}</text></svg>")
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


def seed_evidence():
    rows = [("site", "Page d'accueil du site", "page", True), ("affiche-marche", "Affiche du marché du samedi", "image", True),
            ("bouteille", "Photo produit, bouteille sur bois brut", "image", True), ("post-ete", "Post de l'été, terrasse", "image", None),
            ("ancien-logo", "Ancien logo, avant 2024", "image", False), ("concurrent", "Visuel d'un concurrent remonté par la recherche", "image", False),
            ("etiquette", "Étiquette de la cuvée gingembre", "image", True), ("salon", "Stand au salon bio, photo d'un visiteur", "image", None)]
    out = [{"id": f"ev-{i + 1:02d}", "slug": s, "note": n, "kind": k, "proposed": p, "kept": None,
            "preview": placeholder(n)} for i, (s, n, k, p) in enumerate(rows)]
    logos = [{"id": "logo-1", "note": "Logo du site, vectoriel", "preview": placeholder("Marrowbay", 320, 120)},
             {"id": "logo-2", "note": "Favicon", "preview": placeholder("M", 120, 120)}]
    return out, logos


VARIANTS = [
    {"id": "v1", "mandate": "Le goût d'abord", "headline": "Acide, puis doux, puis plus rien.", "subline": "Kombucha de petite cuvée. Servez-vous.",
     "image_prompt": "Un verre de kombucha sur une table de marché, lumière du matin, bois brut, aucun texte."},
    {"id": "v2", "mandate": "Démonter l'idée reçue", "headline": "C'est du thé qui a un peu fait la fête.", "subline": "Brassé au port. Servi partout.",
     "image_prompt": "Une théière renversée sur un comptoir, des bulles dans la lumière, aucun texte."},
    {"id": "v3", "mandate": "Le temps long", "headline": "Quatorze jours dans une ville de port.", "subline": "",
     "image_prompt": "Des bocaux de fermentation alignés devant une fenêtre sur le port, aucun texte."},
    {"id": "v4", "mandate": "Rupture : l'entre-deux", "headline": "Pour quand l'eau est trop polie et le soda trop bavard.", "subline": "",
     "image_prompt": "Deux verres, l'un d'eau, l'autre de soda, et entre eux une bouteille ambrée, aucun texte."},
]


class StubBackend:
    name = "stub"

    def __init__(self, static_url="stub", speed=1.0):
        self.lock = threading.Lock()
        self.speed = speed  # 0.01 in tests: the jobs end at once
        self.static = static_url
        self.projects, self.jobs = {}, {}
        self.ids = itertools.count(1)
        self._create("Marrowbay, premier kombucha en ville")

    # ---------- helpers ----------
    def _new_id(self, prefix):
        return f"{prefix}-{next(self.ids)}"

    def _p(self, pid):
        p = self.projects.get(pid)
        if not p:
            raise NotFound(f"no project {pid}")
        return p

    def _job(self, kind, pid, piece=None):
        j = {"id": self._new_id("job"), "kind": kind, "project": pid, "piece": piece, "start": time.time(),
             "duration": DURATION[kind] * self.speed, "status": "running", "progress": 0.0, "message": "", "result": None}
        self.jobs[j["id"]] = j
        self._mark(pid, {"learn": "brand", "diverge": "diverge", "image": "image"}[kind])
        return j

    def _mark(self, pid, *keys):
        """Note that the hand changed on these steps now: the interface says who holds it and since when."""
        p = self.projects.get(pid)
        if p:
            for k in keys:
                p["since"][k] = time.time()

    def _tick(self):
        """Finish the jobs whose time is up and apply what they produce."""
        now = time.time()
        for j in self.jobs.values():
            if j["status"] != "running":
                continue
            j["progress"] = min(1.0, (now - j["start"]) / j["duration"])
            j["message"] = {"learn": "lecture du site et des images", "diverge": "quatre agents écrivent, chacun à l'aveugle",
                            "image": "le modèle d'image dessine"}[j["kind"]]
            if j["progress"] < 1:
                continue
            j["status"], j["message"] = "done", "terminé"
            p = self.projects.get(j["project"])
            if not p:
                continue
            self._mark(j["project"], {"learn": "brand", "diverge": "diverge", "image": "image"}[j["kind"]], *(["piece"] if j["kind"] == "image" else []))
            if j["kind"] == "learn":
                p["evidence"], p["logos"] = seed_evidence()
                p["brand"]["learned"] = True
            elif j["kind"] == "diverge":
                p["variants"] = copy.deepcopy(VARIANTS)
            elif j["kind"] == "image":
                pc = self._piece(p, j["piece"])
                pc["image"] = f"{self.static}/image.png"
                pc["status"] = "image"

    def _piece(self, p, i):
        for pc in p["pieces"]:
            if pc["id"] == i:
                return pc
        raise NotFound(f"no piece {i}")

    def _running(self, p, kind, piece=None):
        return next((j for j in self.jobs.values() if j["project"] == p["id"] and j["kind"] == kind and j["status"] == "running"
                     and (piece is None or j["piece"] == piece)), None)

    # ---------- the project and what waits for the person ----------
    def state(self, p):
        """The project as plain data for workflow.project_view (the logic of the steps lives there, once)."""
        return {"id": p["id"], "name": p["name"], "brand": p["brand"]["name"], "can_learn": True,
                "learned": p["brand"]["learned"], "kept": p["brand"]["kept"], "evidence": len(p["evidence"]),
                "brief_confirmed": p["brief"]["confirmed"], "mandates_confirmed": p["mandates"]["confirmed"],
                "variants": len(p["variants"]), "pieces": p["pieces"], "failed": [], "since": p["since"],
                "running": [j for j in self.jobs.values() if j["project"] == p["id"] and j["status"] == "running"]}

    def view(self, p):
        return workflow.project_view(self.state(p), time.time())

    # ---------- routes ----------
    def health(self):
        return {"ok": True, "backend": self.name}

    def list_projects(self):
        with self.lock:
            self._tick()
            return [{"id": p["id"], "name": p["name"], "waiting": len(self.view(p)["waiting"])} for p in self.projects.values()]

    def tasks(self):
        """What waits for the person, in every project, the oldest first; the running jobs; the projects, for the breadcrumb."""
        with self.lock:
            self._tick()
            entries = [(self.state(p), self.view(p)) for p in self.projects.values()]
            jobs = [{"id": j["id"], "project": j["project"], "kind": j["kind"], "piece": j["piece"], "progress": j["progress"],
                     "message": j["message"], "since": j["start"], "eta": round(j["duration"] * (1 - j["progress"]), 1)}
                    for j in self.jobs.values() if j["status"] == "running"]
            return workflow.tasks_payload(entries, jobs, time.time())

    def create_project(self, name, src=None, brand=None, site=None):
        """brand and site are for the real studio (it searches the brand on its site); the simulated one has one fictional brand."""
        with self.lock:
            return self._create(name, src)

    def _create(self, name, src=None):
        pid = self._new_id("p")
        base = self.projects.get(src) if src else None
        p = {"id": pid, "name": name or "Nouveau projet", "since": {},
             "brand": copy.deepcopy(base["brand"]) if base else {"name": "Marrowbay Ferments", "learned": False, "kept": False, "colours": []},
             "evidence": copy.deepcopy(base["evidence"]) if base else [], "logos": copy.deepcopy(base["logos"]) if base else [], "logo": base["logo"] if base else None,
             "brief": {"confirmed": False, "fields": copy.deepcopy(base["brief"]["fields"]) if base else {
                 "objective": "faire connaître le kombucha à des citadins qui n'en ont jamais bu",
                 "audience": "des citadins qui pensent que le kombucha est une mode bien-être",
                 "message": "le kombucha, c'est du thé qui a un peu fait la fête, et c'est bon",
                 "format": "post-4x5, story", "layout": "", "fixed": "les couleurs et les polices de la marque",
                 "cta": "Retrouvez-nous au marché", "language": "fr"}},
             "mandates": {"confirmed": False, "common": "Écrire en français, au vouvoiement ; aucun chiffre ni promesse inventés ; relire chaque ligne pour y traquer un double sens ; l'image ne contient aucun texte.",
                          "items": [{"id": v["id"], "mandate": v["mandate"]} for v in VARIANTS]},
             "variants": [], "pieces": []}
        self.projects[pid] = p
        self._mark(pid, "brand", *(["brief"] if base and base["brand"]["kept"] else []))
        return self.view(p)

    def project(self, pid):
        with self.lock:
            self._tick()
            return self.view(self._p(pid))

    def learn(self, pid, mode="learn", answers=None):
        with self.lock:
            p = self._p(pid)
            if mode not in ("learn", "answer", "create"):
                raise ValueError("mode is learn, answer or create")
            if mode == "answer" and not (answers or "").strip():
                raise ValueError("answer: say what you know of the brand")
            if answers:
                p["brand"]["answers"] = str(answers)
            if mode == "learn":
                return self._job("learn", pid)
            p["evidence"], p["logos"] = ([], []) if mode == "create" else seed_evidence()
            p["brand"]["learned"] = True
            self._mark(pid, "brand")
            return {"id": None, "status": "done", "progress": 1.0, "message": "sans recherche", "result": None}

    def brand(self, pid):
        with self.lock:
            self._tick()
            p = self._p(pid)
            return {"name": p["brand"]["name"], "evidence": p["evidence"], "logos": p["logos"], "logo": p["logo"],
                    "colours": p["brand"]["colours"], "kept": p["brand"]["kept"], "answers": p["brand"].get("answers", "")}

    def keep(self, pid, kept, logo):
        with self.lock:
            p = self._p(pid)
            if not p["brand"]["learned"]:
                raise Conflict("the brand is not learned yet")
            ids = {e["id"] for e in p["evidence"]}
            if set(kept) - ids:
                raise ValueError(f"unknown evidence: {', '.join(sorted(set(kept) - ids))}")
            for e in p["evidence"]:
                e["kept"] = e["id"] in kept
            p["logo"] = logo
            p["brand"]["kept"] = True
            p["brand"]["colours"] = [{"hex": h, "status": "to confirm", "source": "mesurée sur les visuels gardés"}
                                     for h in ("#2F5D50", "#E8DCC4", "#B5562F", "#1E2A24")][:max(1, min(4, len(kept)))]
            self._mark(pid, "brand", "brief")
            return {"kept": len(kept), "discarded": len(ids) - len(kept), "logo": logo, "colours": p["brand"]["colours"]}

    def get_brief(self, pid):
        with self.lock:
            p = self._p(pid)
            return {"fields": p["brief"]["fields"], "confirmed": p["brief"]["confirmed"], "formats": list(FORMATS),
                    "chosen": self._formats(p), "left_out": self._left_out(p)}

    def put_brief(self, pid, fields):
        with self.lock:
            p = self._p(pid)
            for k in ("objective", "audience", "message"):
                if not (fields.get(k) or "").strip():
                    raise ValueError(f"brief: {k} is required")
            p["brief"]["fields"].update({k: str(v) for k, v in fields.items()})
            p["brief"]["confirmed"] = True
            self._mark(pid, "brief", "mandates")
            return {"fields": p["brief"]["fields"], "formats": self._formats(p), "left_out": self._left_out(p)}

    def _formats(self, p):
        return workflow.formats_of(p["brief"]["fields"].get("format", ""))

    def _left_out(self, p):
        return workflow.left_out_of(p["brief"]["fields"].get("format", ""))

    def get_mandates(self, pid):
        with self.lock:
            p = self._p(pid)
            return p["mandates"]

    def put_mandates(self, pid, items, common):
        with self.lock:
            p = self._p(pid)
            if p["brief"]["confirmed"] is False:
                raise Conflict("the brief is not confirmed yet")
            p["mandates"].update({"items": items or p["mandates"]["items"], "common": common if common is not None else p["mandates"]["common"], "confirmed": True})
            self._mark(pid, "mandates", "diverge")
            return p["mandates"]

    def diverge(self, pid):
        with self.lock:
            p = self._p(pid)
            if not p["mandates"]["confirmed"]:
                raise Conflict("the instructions to the agents are not read yet")
            p["variants"], p["pieces"] = [], []
            return self._job("diverge", pid)

    def variants(self, pid):
        with self.lock:
            self._tick()
            return self._p(pid)["variants"]

    def pick(self, pid, ids):
        with self.lock:
            p = self._p(pid)
            have = {v["id"]: v for v in p["variants"]}
            if not ids or set(ids) - set(have):
                raise ValueError("pick at least one known variant")
            p["pieces"] = []
            for vid in ids:
                for fmt in self._formats(p):
                    v = have[vid]
                    p["pieces"].append({"id": f"{vid}-{fmt}", "label": f"{vid} en {fmt}", "variant": vid, "format": fmt, "size": FORMATS[fmt],
                                        "headline": v["headline"], "subline": v["subline"], "prompt": v["image_prompt"], "image": None,
                                        "composed": None, "check": None, "decision": None, "status": "picked"})
            self._mark(pid, "diverge", "image")
            return copy.deepcopy(p["pieces"])

    def piece(self, pid, i):
        with self.lock:
            self._tick()
            return copy.deepcopy(self._piece(self._p(pid), i))

    def put_prompt(self, pid, i, prompt):
        with self.lock:
            pc = self._piece(self._p(pid), i)
            if not (prompt or "").strip():
                raise ValueError("the prompt is empty")
            pc["prompt"] = prompt
            return copy.deepcopy(pc)

    def image(self, pid, i):
        with self.lock:
            p = self._p(pid)
            pc = self._piece(p, i)
            pc["image"], pc["composed"], pc["check"], pc["decision"] = None, None, None, None
            return self._job("image", pid, i)

    def compose(self, pid, i):
        with self.lock:
            self._tick()
            pc = self._piece(self._p(pid), i)
            if not pc["image"]:
                raise Conflict("no image yet")
            pc["composed"] = f"{self.static}/piece.png"
            pc["check"] = {"pass": 10, "warn": 2, "fail": 0, "major": 0,
                           "notes": [{"status": "warn", "say": "deux valeurs de la marque sont encore à confirmer (la police, le logo)"},
                                     {"status": "warn", "say": "le contraste du titre dépend de l'image : regarder la pièce"}]}
            pc["status"] = "composed"
            self._mark(pid, "image", "piece", "decide")
            return copy.deepcopy(pc)

    def decide(self, pid, i, verdict, words):
        with self.lock:
            pc = self._piece(self._p(pid), i)
            if verdict not in ("keep", "again"):
                raise ValueError("verdict is keep or again")
            if not pc["composed"]:
                raise Conflict("nothing to decide yet")
            if verdict == "again" and not (words or "").strip():
                raise ValueError("say what is wrong: it is remembered for the next round")
            pc["decision"] = {"verdict": verdict, "words": words, "at": time.time()}
            self._mark(pid, "decide")
            if verdict == "again":
                pc["image"], pc["composed"], pc["check"], pc["status"] = None, None, None, "again"
                pc["decision"] = None
                pc["bans"] = pc.get("bans", []) + [words]
            return copy.deepcopy(pc)

    def job(self, jid):
        with self.lock:
            self._tick()
            j = self.jobs.get(jid)
            if not j:
                raise NotFound(f"no job {jid}")
            return {k: j[k] for k in ("id", "kind", "status", "progress", "message", "result", "piece")}
