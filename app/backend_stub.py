"""backend_stub: a simulated studio behind the API, for building the interface without the production backend.

Nothing is generated and no model is called: the brands, the variants and the pieces are fixed fictional data, and the long
steps (reading a brand's site, the divergence, the image) are jobs whose progress follows the clock. The real backend has
the same methods, driving scripts/studio and scripts/brandkit instead.

The studio holds brands, a brand holds projects. Three brands are there from the start, each in a different stage:

- Marrowbay Ferments (the public example): `ready`, with two projects at two different steps;
- Atelier Ondine: `to_sort` (its site is read, the visuals wait to be sorted), and its project waits for it;
- Kestrel Bakehouse: `to_confirm` (it has a logo, but a voice, colours and the logo are still deduced).

The other stages are reached by creating a brand: no site, `new`; a site, `discovering` then `to_sort`; a brief done, `to_confirm`
then `ready`. A site whose host contains "fail" makes the reading fail (a `job-failed` task), to see what that looks like.
"""

import base64
import copy
import itertools
import os
import threading
import time
import urllib.parse

import workflow
from pathlib import Path

from workflow import FORMATS, STEPS, Conflict, Download, NotFound, field, one_line  # noqa: F401  (the server imports the exceptions from here too)

DURATION = {"learn": 4.0, "diverge": 6.0, "image": 8.0, "judge": 5.0, "reader": 4.0, "personas": 4.0, "names": 4.0, "competitors": 4.0, "texts": 4.0, "storyboard": 4.0, "film": 5.0}  # seconds: long enough to see a progress, short enough to demo
JOB_KEYS = ("id", "kind", "status", "progress", "message", "result", "piece")


def placeholder(label, w=320, h=400, dark=False):
    """A neutral placeholder picture with its label, as a data URI: stands for a visual the real studio finds."""
    bg, ink = ("#1E2A3A", "#F5F7FA") if dark else ("#E8EEF7", "#1E2A3A")
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
           f"<rect width='100%' height='100%' fill='{bg}'/><rect x='12' y='12' width='{w - 24}' height='{h - 24}' fill='none' stroke='{ink}' stroke-opacity='.25'/>"
           f"<text x='24' y='{h - 28}' font-family='sans-serif' font-size='15' fill='{ink}'>{label}</text></svg>")
    return "data:image/svg+xml;utf8," + urllib.parse.quote(svg)


def seed_evidence(brand="Marrowbay"):
    rows = [("site", "Page d'accueil du site", "page", True), ("affiche-marche", "Affiche du marché du samedi", "image", True),
            ("bouteille", "Photo produit, bouteille sur bois brut", "image", True), ("post-ete", "Post de l'été, terrasse", "image", None),
            ("ancien-logo", "Ancien logo, avant 2024", "image", False), ("concurrent", "Visuel d'un concurrent remonté par la recherche", "image", False),
            ("etiquette", "Étiquette de la cuvée gingembre", "image", True), ("salon", "Stand au salon bio, photo d'un visiteur", "image", None)]
    out = [{"id": f"ev-{i + 1:02d}", "slug": s, "note": n, "kind": k, "proposed": p, "kept": None,
            "preview": placeholder(n)} for i, (s, n, k, p) in enumerate(rows)]
    logos = [{"id": "logo-1", "note": "Logo du site, vectoriel", "preview": placeholder(brand, 320, 120)},
             {"id": "logo-2", "note": "Favicon", "preview": placeholder(brand[:1], 120, 120)}]
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

MEASURED = ("#2f5d50", "#e8dcc4", "#b5562f", "#1e2a24")
ROLES = ("background", "text", "accent", "headline colour")
DEDUCED_FROM_SITE = {"what": "Une brasserie de kombucha de petite cuvée, au port", "voice": "direct, chaleureux, pince-sans-rire",
                     "signature": "Servez-vous."}


# the simulated judge's one verdict, plausible and fixed (the brand heading only when a brand is given; what the brief lacks is said by workflow)
VERDICT = {"target": {"reached": "partly", "why": "Un citadin pressé comprend vite qu'il s'agit d'une boisson, mais rien ne lui dit pourquoi il la prendrait plutôt qu'un soda."},
           "works": [{"where": "l'image", "say": "La lumière du matin et le bois brut installent le marché sans avoir à l'écrire."}],
           "snags": [{"where": "le titre en haut", "say": "« plus rien » peut se lire comme un goût qui s'en va trop vite : le double sens joue contre la boisson."},
                     {"where": "le bandeau du bas", "say": "L'appel à l'action est plus petit que la sous-ligne : l'œil s'arrête avant de le lire."}],
           "unsourced": [{"where": "la sous-ligne", "say": "« petite cuvée » : rien dans le brief ni dans la marque ne dit la taille des cuvées."}],
           "brand": [{"where": "le titre en haut", "say": "Direct et pince-sans-rire, c'est bien sa voix ; la chaleur qu'elle revendique manque un peu."}]}


# the simulated reader's one reading, plausible and fixed, whatever its persona (a persona whose text contains "fail" makes its reader fail)
READING = {"aimed": "partly", "why": "Je vois une boisson et un marché, ça me parle un peu, mais rien ne me dit que c'est pour quelqu'un comme moi.",
           "understand": "Je comprends que c'est une boisson au thé, fermentée, qu'on trouve au marché.",
           "retain": "La bouteille ambrée dans la lumière du matin.",
           "bother": "« plus rien » : je ne sais pas si c'est le goût qui s'en va ou autre chose.",
           "unread": "Le bandeau du bas : je ne l'ai pas lu, il est trop petit.",
           "lacks": "Ce que ça a comme goût, en vrai, et où est ce marché."}
# the simulated names agent's one answer, plausible and fixed
NAMES = {"names": [
    {"name": "Quai Ambré", "why": "Le port où l'on brasse et la couleur de la boisson dans la bouteille : un lieu et une lumière."},
    {"name": "Bulle Lente", "why": "Une fermentation qui prend son temps : évoque la patience et une boisson qui pétille sans brusquer."},
    {"name": "Petite Cuvée", "why": "Dit le petit lot et le soin, comme pour un vin : évoque l'artisan plus que la mode."},
    {"name": "Marée Douce", "why": "Le bord de mer et une acidité tenue : évoque le large sans promettre de santé."},
    {"name": "Thé Vivant", "why": "Dit ce que c'est, un thé qui fermente : évoque le vivant, simple à retenir au marché."}]}
# the simulated personas agent's one answer, plausible and fixed (written as texts by workflow, as the real agent's)
PERSONAS = {"personas": [
    {"need": "savoir si ça a bon goût avant d'en acheter une bouteille", "lines": [
        {"from": "supposé", "say": "Tu as la cinquantaine, tu fais le marché le samedi matin, panier au bras."},
        {"from": "supposé", "say": "Tu croises l'affiche du stand en passant, en trois secondes, entre deux étals."},
        {"from": "dossier", "say": "Tu entends parler d'un kombucha de petite cuvée, brassé au port."},
        {"from": "supposé", "say": "Tu penses que c'est une boisson de mode, un peu acide, pas pour toi."},
        {"from": "supposé", "say": "Tes mots : « c'est quoi ce truc ? », « ça se boit comment ? »."}]},
    {"need": "trouver une boisson sans alcool qui ne soit pas un soda", "lines": [
        {"from": "supposé", "say": "Tu as trente ans, tu sors le soir mais tu ne bois pas toujours d'alcool."},
        {"from": "supposé", "say": "Tu vois le post dans ton fil, au pouce, sans le son."},
        {"from": "dossier", "say": "La marque parle à des citadins qui pensent que le kombucha est une mode bien-être."},
        {"from": "supposé", "say": "Tu en as déjà bu un, trop sucré ; tu te méfies des promesses de santé."},
        {"from": "supposé", "say": "Tes mots : « un truc sans alcool qui a du goût », « pas un jus »."}]},
    {"need": "proposer quelque chose de local à ses clients", "lines": [
        {"from": "supposé", "say": "Tu tiens un café du quartier et tu cherches ce que tu mettras au frigo."},
        {"from": "supposé", "say": "Tu tombes sur l'affiche au marché, ou sur le post qu'un client te montre."},
        {"from": "dossier", "say": "La marque dit d'elle : direct, chaleureux, pince-sans-rire ; sa signature : « Servez-vous. »."},
        {"from": "supposé", "say": "Tu ne connais pas la marque ; tu aimes ce qui se fabrique à côté."},
        {"from": "supposé", "say": "Tes mots : « ça se vend bien ? », « vous livrez ? »."}]}]}

# storyboard: the simulated storyboard agent's one answer, plausible and fixed (checked by workflow.parse_storyboard, as the real agent's)
STORYBOARD = {"script": "Le film commence par une question, répond par le geste de brasser, puis dit le goût et finit sur la marque.",
              "shots": [{"seconds": 3, "visual": "texte", "text": "Un kombucha, c'est quoi ?", "colour": "#1e2a24", "read": "Un kombucha, c'est quoi ?"},
                        {"seconds": 4, "visual": "texte", "text": "Du thé qui fermente, doucement.", "colour": "#c8553d", "read": "C'est du thé qui fermente, doucement."},
                        {"seconds": 4, "visual": "texte", "text": "Brassé en petits lots au port.", "colour": "#f4efe6", "read": "On le brasse en petits lots, au port."},
                        {"seconds": 4, "visual": "texte", "text": "Un goût franc, pas un jus.", "colour": "#1e2a24", "read": "Un goût franc, pas un jus."},
                        {"seconds": 3, "visual": "texte", "text": "Servez-vous.", "colour": "#c8553d", "read": "Servez-vous."},
                        {"seconds": 3, "visual": "logo", "text": "", "colour": "#1e2a24", "read": "Marrowbay Ferments."}]}

# competitors: the simulated competitors agent's one answer, plausible, fixed and fictional
COMPETITORS = {"competitors": [
    {"name": "Brasserie du Quai", "from": "supposé", "sells": "des bières artisanales brassées au port, aux bars et aux cavistes du quartier.",
     "differs": "Elle parle d'apéro et de fête, avec de l'alcool ; la marque parle d'une boisson sans alcool qui a du goût."},
    {"name": "Fizz Santé", "from": "supposé", "sells": "un kombucha en canette vendu en grande surface aux citadins soucieux de leur santé.",
     "differs": "Un ton bien-être et des promesses de santé ; la marque est directe, pince-sans-rire, et parle du goût."},
    {"name": "Les Sirops de Léonie", "from": "supposé", "sells": "des sirops et limonades de fruits locaux aux familles, au marché et en épicerie fine.",
     "differs": "Doux et sucré, pour les enfants aussi ; la marque est acidulée et vise les adultes."},
    {"name": "Thé Vagabond", "from": "dossier", "sells": "des thés en vrac et des infusions froides aux cafés de la ville.",
     "differs": "Il vend la feuille, à infuser soi-même ; la marque vend une boisson prête, fermentée, à boire tout de suite."}]}

# texts: the simulated texts agent's one answer, plausible and fixed
TEXTS = {"texts": [
    {"kind": "accroche", "text": "Du thé qui a un peu fait la fête."},
    {"kind": "accroche", "text": "Le kombucha, version sans prise de tête."},
    {"kind": "post", "text": "Tu croyais que le kombucha était une mode bien-être ?\nC'est du thé qui a un peu fait la fête, et c'est bon.\nRetrouvez-nous au marché."},
    {"kind": "post", "text": "Pas de promesse, pas de sermon.\nUn thé fermenté, acidulé, à boire frais.\nGoûtez-le, vous nous direz."}]}


def default_brief():
    return {"objective": "faire connaître le kombucha à des citadins qui n'en ont jamais bu",
            "audience": "des citadins qui pensent que le kombucha est une mode bien-être",
            "message": "le kombucha, c'est du thé qui a un peu fait la fête, et c'est bon",
            "format": "post-4x5, story", "layout": "", "fixed": "les couleurs et les polices de la marque",
            "cta": "Retrouvez-nous au marché", "language": "fr"}


def job_view(j):
    return {k: j[k] for k in JOB_KEYS}


class StubBackend:
    name = "stub"

    def __init__(self, static_url="stub", speed=1.0, missing=None):
        self.lock = threading.RLock()
        # tools the simulated machine lacks (`chrome`, `claude`, `image`), to see what the studio says: STUDIO_STUB_MISSING=chrome,image
        self.missing = set(missing if missing is not None else (os.environ.get("STUDIO_STUB_MISSING") or "").replace(" ", "").split(",")) - {""}
        self.speed = speed  # 0.01 in tests: the jobs end at once
        self.static = static_url
        self.brands, self.projects, self.jobs, self.judgements = {}, {}, {}, {}
        self.engines = {"image_engine": "auto", "text_engine": "claude", "openrouter_model": "anthropic/claude-sonnet-4.5", "key_saved": False}  # engines: the simulated settings; a key is never kept
        self.ids = itertools.count(1)
        self._seed()

    # ---------- the data it starts with ----------
    def _seed(self):
        ev, logos = seed_evidence()
        for e in ev:
            e["kept"] = bool(e["proposed"])
        marrow = self._brand("Marrowbay Ferments", "https://marrowbay.example/", "Kombucha de petite cuvée, brassé dans une ville de port.")
        marrow.update(discovered=True, kept=True, logo="logo-1", logo_state="confirmed", brief_done=True, evidence=ev, logos=logos,
                      colours=[{"hex": h, "role": r, "state": "confirmed", "source": "tapé"} for h, r in zip(MEASURED, ROLES)])
        marrow["fields"] = {"what": field("un kombucha de petite cuvée, brassé au port", "confirmed", "tapé"),
                            "who": field("des citadins qui pensent que le kombucha est une mode bien-être", "confirmed", "tapé"),
                            "voice": field("direct, chaleureux, pince-sans-rire", "confirmed", "tapé"),
                            "signature": field("Servez-vous.", "confirmed", "tapé"),
                            "never": field("détox, superaliment, booster", "confirmed", "tapé"),
                            "colours": field("vert sauge, crème, un orange brûlé", "confirmed", "tapé")}
        self._touch(marrow)
        autumn = self._project(marrow, "Campagne de rentrée")  # the divergence is written: the person has to choose
        autumn["brief"]["confirmed"] = True
        autumn["mandates"]["confirmed"] = True
        autumn["variants"] = copy.deepcopy(VARIANTS)
        self._mark(autumn, "brief", "mandates", "diverge")
        self._project(marrow, "Lancement gingembre")  # nothing yet: the brief waits

        ev2, logos2 = seed_evidence("Atelier Ondine")
        ondine = self._brand("Atelier Ondine", "https://ondine.example/", "Un atelier de céramique et de bains de mer.")
        ondine.update(discovered=True, evidence=ev2, logos=logos2)
        ondine["fields"] = {k: field(v, "deduced", "déduit du site") for k, v in DEDUCED_FROM_SITE.items()}
        self._touch(ondine)
        self._project(ondine, "Ouverture de la saison")  # its brand is not sorted: step 1 waits for it

        ev3, logos3 = seed_evidence("Kestrel")
        for e in ev3:
            e["kept"] = bool(e["proposed"])
        kestrel = self._brand("Kestrel Bakehouse", "https://kestrel.example/", "Boulangerie au levain, en ville.")
        kestrel.update(discovered=True, kept=True, logo="logo-1", logo_state="deduced", brief_done=True, evidence=ev3, logos=logos3,
                       colours=[{"hex": h, "role": r, "state": "deduced", "source": "mesurée sur les visuels gardés"} for h, r in zip(MEASURED[:3], ROLES)])
        kestrel["fields"] = {"what": field("une boulangerie au levain", "confirmed", "tapé"), "who": field("le quartier, le matin", "confirmed", "tapé"),
                             "voice": field("simple, chaude, matinale", "deduced", "déduit du site")}
        self._touch(kestrel)

    # ---------- helpers ----------
    def _new_id(self, prefix):
        return f"{prefix}-{next(self.ids)}"

    def _b(self, bid):
        b = self.brands.get(bid)
        if not b:
            raise NotFound(f"no brand {bid}")
        return b

    def _p(self, pid):
        p = self.projects.get(pid)
        if not p:
            raise NotFound(f"no project {pid}")
        return p

    def _brand(self, name, site="", description=""):
        base = workflow.slug(name) or "marque"
        bid, n = base, 1
        while bid in self.brands:
            n += 1
            bid = f"{base}-{n}"
        b = {"id": bid, "name": name, "site": site, "description": description, "created": time.time(), "discovered": False, "kept": False,
             "logo": None, "logo_state": "absent", "brief_done": False, "migrated": False, "fields": {}, "evidence": [], "logos": [], "colours": [],
             "answers": "", "since": {}, "tasked": []}
        self.brands[bid] = b
        return b

    def _project(self, b, name, src=None):
        base = workflow.slug(name) or "projet"
        pid, n = base, 1
        while pid in self.projects:
            n += 1
            pid = f"{base}-{n}"
        p = {"id": pid, "name": name or "Nouveau projet", "brand": b["id"], "type": "campagne", "since": {},
             "brief": {"confirmed": False, "fields": copy.deepcopy(src["brief"]["fields"]) if src else default_brief()},
             "texts": {"kept": [], "proposed": []},
             "mandates": {"confirmed": False, "common": "Écrire en français, au vouvoiement ; aucun chiffre ni promesse inventés ; relire chaque ligne pour y traquer un double sens ; l'image ne contient aucun texte.",
                          "items": [{"id": v["id"], "mandate": v["mandate"]} for v in VARIANTS]},
             "variants": [], "pieces": []}
        self.projects[pid] = p
        self._mark(p, "brand", *(["brief"] if workflow.brand_ready(self._bstate(b)) else []))
        return p

    def _mark(self, p, *keys):
        """Note that the hand changed on these steps now: the interface says who holds it and since when."""
        for k in keys:
            p["since"][k] = time.time()

    def _job(self, kind, brand=None, project=None, piece=None, judgement=None, reader=None):
        j = {"id": self._new_id("job"), "kind": kind, "brand": brand, "project": project, "piece": piece, "judgement": judgement, "reader": reader, "start": time.time(),
             "duration": DURATION[kind] * self.speed, "status": "running", "progress": 0.0, "message": "", "result": None, "error": None}
        self.jobs[j["id"]] = j
        if project:
            self._mark(self._p(project), workflow.KIND_STEP[kind])
        return j

    def _tick(self):
        """Finish the jobs whose time is up and apply what they produce."""
        now = time.time()
        for j in self.jobs.values():
            if j["status"] != "running":
                continue
            j["progress"] = min(1.0, (now - j["start"]) / j["duration"])
            j["message"] = {"learn": "lecture du site et des images", "diverge": "quatre agents écrivent, chacun à l'aveugle",
                            "image": "le modèle d'image dessine", "judge": "le juge relit la pièce",
                            "reader": "un lecteur lit la pièce", "personas": "un agent imagine les personas",
                            "names": "un agent cherche des noms", "competitors": "un agent cherche les concurrents",
                            "texts": "un agent écrit les textes", "storyboard": "un agent écrit le script et les plans",
                            "film": "chaque plan est animé puis assemblé"}[j["kind"]]
            if j["progress"] < 1:
                continue
            j["status"], j["message"] = "done", "terminé"
            if j["kind"] == "learn":
                b = self.brands.get(j["brand"])
                if not b:
                    continue
                if "fail" in urllib.parse.urlsplit(b["site"]).netloc:
                    j["status"], j["error"] = "failed", "le site n'a pas répondu (simulé)"
                    j["message"] = j["error"]
                else:
                    self._discovered(b)
                self._touch(b)
                continue
            if j["kind"] == "reader":
                self._read(j)
                continue
            if j["kind"] == "personas":
                b = self.brands.get(j["brand"])
                if b:
                    b["proposed"] = workflow.parse_personas(copy.deepcopy(PERSONAS))
                continue
            if j["kind"] == "names":
                b = self.brands.get(j["brand"])
                if b:
                    b["names_proposed"] = workflow.parse_names(copy.deepcopy(NAMES))
            if j["kind"] == "competitors":
                b = self.brands.get(j["brand"])
                if b:
                    b["competitors_proposed"] = workflow.parse_competitors(copy.deepcopy(COMPETITORS))
                continue
            if j["kind"] in ("storyboard", "film"):  # storyboard
                p = self.projects.get(j["project"])
                if p and j["kind"] == "storyboard":
                    p["storyboard"] = {**workflow.parse_storyboard(copy.deepcopy(STORYBOARD)), "saved": False, "film": False}
                elif p:
                    p["storyboard"]["film"] = True
            if j["kind"] == "texts":
                p = self.projects.get(j["project"])
                if p:
                    p["texts"]["proposed"] = workflow.parse_texts(copy.deepcopy(TEXTS))
                continue
            if j["judgement"]:
                jg = self.judgements.get(j["judgement"])
                if jg and "fail" in jg["name"].lower():  # a piece whose name says "fail" makes the judge fail, to see what that looks like
                    j["status"], j["error"] = "failed", "le juge n'a pas répondu (simulé)"
                    j["message"], jg["error"] = j["error"], j["error"]
                elif jg:
                    jg["verdict"], jg["error"] = self._verdict(jg["brand"], jg["brief"]), None
                continue
            p = self.projects.get(j["project"])
            if not p:
                continue
            self._mark(p, workflow.KIND_STEP[j["kind"]], *(["piece"] if j["kind"] == "image" else []))
            if j["kind"] == "judge":
                pc = next((x for x in p["pieces"] if x["id"] == j["piece"]), None)
                if pc and pc["composed"] and (pc.get("judge") or {}).get("job") == j["id"]:
                    pc["judge"] = {**workflow.judge_view("done", self._verdict(p["brand"], p["brief"]["fields"])), "job": j["id"]}
            elif j["kind"] == "diverge":
                p["variants"] = copy.deepcopy(VARIANTS)
            elif j["kind"] == "image":
                pc = self._piece(p, j["piece"])
                pc["image"] = f"{self.static}/image.png"
                pc["status"] = "image"

    def _discovered(self, b):
        """What reading the site produced: visuals to sort, and a few values deduced for the brief (never over what the person said)."""
        ev, logos = seed_evidence(b["name"].split()[0])
        known = {e["id"]: e for e in b["evidence"]}
        for e in ev:  # the choices already made stay
            if e["id"] in known:
                e["kept"] = known[e["id"]]["kept"]
        b["evidence"], b["logos"], b["discovered"] = ev, logos, True
        for k, v in DEDUCED_FROM_SITE.items():
            if b["fields"].get(k, field())["state"] == "absent":
                b["fields"][k] = field(v, "deduced", "déduit du site")
        if any(e["kept"] is None for e in ev):
            b["kept"] = False  # something new to sort

    def _piece(self, p, i):
        for pc in p["pieces"]:
            if pc["id"] == i:
                return pc
        raise NotFound(f"no piece {i}")

    def _running(self, kind, project=None, brand=None, piece=None):
        return next((j for j in self.jobs.values() if j["kind"] == kind and j["status"] == "running" and (project is None or j["project"] == project)
                     and (brand is None or j["brand"] == brand) and (piece is None or j["piece"] == piece)), None)

    # ---------- the brand as plain data ----------
    def _identity(self, b):
        """The six fields. `colours`: what the person said of them, or else what was measured. Its state is the state of the colours
        themselves: said in words, they still have to be confirmed as long as the measured swatches are not."""
        out = dict(b["fields"])
        cols, words = b["colours"], out.get("colours")
        if cols:
            deduced = any(c["state"] == "deduced" for c in cols)
            said = words["value"] if words and words["state"] != "absent" else ""
            out["colours"] = field(said or ", ".join(c["hex"] for c in cols), "deduced" if deduced else "confirmed",
                                   "tapé" if said and not deduced else cols[0]["source"])
        return workflow.identity_of(out)

    def _bstate(self, b):
        ident = self._identity(b)
        deduced = [k for k in workflow.FIELD_KEYS if ident[k]["state"] == "deduced"] + (["logo"] if b["logo"] and b["logo_state"] == "deduced" else [])
        last = next((j for j in reversed(list(self.jobs.values())) if j["kind"] == "learn" and j["brand"] == b["id"]), None)
        return {"id": b["id"], "name": b["name"], "site": b["site"], "discovered": b["discovered"], "kept": b["kept"], "logo": bool(b["logo"]),
                "colours_ok": len(b["colours"]) >= 2, "brief_done": b["brief_done"], "migrated": b["migrated"], "deduced": deduced, "unsorted": sum(1 for e in b["evidence"] if e["kept"] is None),
                "running": self._running("learn", brand=b["id"]),
                "failed": {"error": last["error"], "at": last["start"]} if last and last["status"] == "failed" else None, "since": b["since"]}

    def _touch(self, b):
        """Note when each task of the brand came to the person: the oldest first in the list, and `since` for the interface."""
        kinds = [a["kind"] for a in workflow.brand_asks(self._bstate(b))]
        for k in kinds:
            if k not in b["tasked"]:
                b["since"][k] = time.time()
        b["tasked"] = kinds

    def _assets(self, b):
        logo = next((x for x in b["logos"] if x["id"] == b["logo"]), None)
        return {"logo": {"id": logo["id"], "preview": logo["preview"], "state": b["logo_state"],
                         "source": "choisi par toi" if b["logo_state"] == "confirmed" else "lu sur le site"} if logo else None,
                "colours": copy.deepcopy(b["colours"]),
                "visuals": [{"id": e["id"], "note": e["note"], "preview": e["preview"]} for e in b["evidence"] if e["kept"]],
                "evidence": [{"id": e["id"], "kind": e["kind"], "note": e["note"], "preview": e["preview"], "proposed": e["proposed"], "kept": e["kept"]} for e in b["evidence"]],
                "logos": [{"id": x["id"], "note": x["note"], "preview": x["preview"]} for x in b["logos"]]}

    def _brand_projects(self, b):
        return [workflow.project_summary(self.view(p)) for p in self.projects.values() if p["brand"] == b["id"]]

    def _brand_view(self, b):
        jobs = [{"id": j["id"], "kind": j["kind"], "piece": None, "progress": j["progress"], "message": j["message"], "since": j["start"]}
                for j in self.jobs.values() if j["kind"] == "learn" and j["brand"] == b["id"] and j["status"] == "running"]
        return workflow.brand_payload(self._bstate(b), {"description": b["description"]}, self._identity(b), self._assets(b), self._brand_projects(b), jobs, time.time())

    def _brief_view(self, b):
        bs = self._bstate(b)
        return {"fields": self._identity(b), "done": b["brief_done"], "stage": workflow.brand_stage(bs), "keys": workflow.FIELD_KEYS,
                "needs": workflow.brand_needs(bs), "palette": workflow.palette_of(b["colours"])}

    # ---------- the project and what waits for the person ----------
    def state(self, p):
        """The project as plain data for workflow.project_view (the logic of the steps lives there, once)."""
        b = self.brands[p["brand"]]
        bs = self._bstate(b)
        since = dict(p["since"])
        if b["since"]:
            since["brand"] = max(b["since"].values())
        return {"id": p["id"], "name": p["name"], "type": p["type"], "brand": b["id"], "brand_name": b["name"], "brand_stage": workflow.brand_stage(bs),
                "brand_ready": workflow.brand_ready(bs), "brand_job": bs["running"], "brand_waiting": workflow.brand_asks(bs), "can_learn": bool(b["site"]),
                "brief_confirmed": p["brief"]["confirmed"], "mandates_confirmed": p["mandates"]["confirmed"],
                "variants": len(p["variants"]), "pieces": p["pieces"], "failed": [], "since": since,
                "running": [j for j in self.jobs.values() if j["project"] == p["id"] and j["status"] == "running"]}

    def view(self, p):
        return workflow.project_view(self.state(p), time.time())

    # ---------- routes: health, tasks, jobs ----------
    def health(self):
        return {"ok": True, "backend": self.name}

    # ---------- routes: engines ----------
    def get_engines(self):
        with self.lock:
            return workflow.engines_view(self.engines)

    def put_engines(self, kind, body):
        """The engine of the images, or of the texts with its key (only whether one is saved is kept, never the key) and its model."""
        patch = workflow.engines_patch(kind, body)
        with self.lock:
            for k, v in patch.items():
                if k == "openrouter_key":
                    self.engines["key_saved"] = bool(v.strip())
                elif k != "openrouter_model" or v.strip():
                    self.engines[k] = v.strip() if k == "openrouter_model" else v
            return workflow.engines_view(self.engines)

    def machine(self):
        """What the machine lacks to run the studio for real: nothing, unless STUDIO_STUB_MISSING says so."""
        return workflow.machine_view({k: k not in self.missing for k, _, _ in workflow.MACHINE})

    def tasks(self):
        """What waits for the person, in every brand and project, the oldest first; the running jobs; the projects and the brands, for the breadcrumb."""
        with self.lock:
            self._tick()
            entries = [(self.state(p), self.view(p)) for p in self.projects.values()]
            brands = [(self._bstate(b), self._brand_projects(b)) for b in self.brands.values()]
            jobs = [{"id": j["id"], "project": j["project"], "brand": j["brand"] or (self.projects[j["project"]]["brand"] if j["project"] else None), "kind": j["kind"], "piece": j["piece"],
                     "progress": j["progress"], "message": j["message"], "since": j["start"], "eta": round(j["duration"] * (1 - j["progress"]), 1),
                     "judgement": j["judgement"]}
                    for j in self.jobs.values() if j["status"] == "running"]
            return workflow.tasks_payload(entries, jobs, time.time(), brands)

    def job(self, jid):
        with self.lock:
            self._tick()
            j = self.jobs.get(jid)
            if not j:
                raise NotFound(f"no job {jid}")
            return {**job_view(j), "error": j["error"]}

    # ---------- routes: brands ----------
    def list_brands(self):
        with self.lock:
            self._tick()
            return [workflow.brand_line(self._bstate(b), self._brand_projects(b)) for b in self.brands.values()]

    def create_brand(self, name, site=None):
        name = one_line(name)
        if not name:
            raise ValueError("name: give the brand's name")
        url = workflow.normalise_site(site)
        with self.lock:
            self._tick()
            b = self._brand(name, url)
            if url:
                self._job("learn", brand=b["id"])
            self._touch(b)
            return self._brand_view(b)

    def brand_view(self, bid):
        with self.lock:
            self._tick()
            return self._brand_view(self._b(bid))

    def update_brand(self, bid, name=None, site=None, description=None):
        with self.lock:
            b = self._b(bid)
            if name is not None:
                if not one_line(name):
                    raise ValueError("name: give the brand's name")
                b["name"] = one_line(name)
            if site is not None:
                b["site"] = workflow.normalise_site(site)  # a new site reads nothing by itself
            if description is not None:
                b["description"] = str(description)
            self._touch(b)
            return self._brand_view(b)

    def discover(self, bid):
        with self.lock:
            self._tick()
            b = self._b(bid)
            if not b["site"]:
                raise Conflict("this brand has no site: the studio cannot read it. Give its site first")
            if self._running("learn", brand=bid):
                raise Conflict("the studio is already reading the brand")
            j = self._job("learn", brand=bid)
            self._touch(b)
            return job_view(j)

    def keep_brand(self, bid, kept, logo):
        with self.lock:
            self._tick()
            b = self._b(bid)
            if not b["discovered"]:
                raise Conflict("the brand is not read yet")
            ids = {e["id"] for e in b["evidence"]}
            kept = list(dict.fromkeys(kept or []))
            if set(kept) - ids:
                raise ValueError(f"unknown evidence: {', '.join(sorted(set(kept) - ids))}")
            if logo and logo not in {x["id"] for x in b["logos"]}:
                raise ValueError(f"unknown logo: {logo}")
            for e in b["evidence"]:
                e["kept"] = e["id"] in kept
            b["logo"], b["logo_state"], b["kept"] = logo or None, "confirmed" if logo else "absent", True
            if not b["colours"] or all(c["state"] == "deduced" for c in b["colours"]):
                b["colours"] = [{"hex": h, "role": r, "state": "deduced", "source": "mesurée sur les visuels gardés"}
                                for h, r in zip(MEASURED, ROLES)][:max(1, min(4, len(kept)))]
            self._touch(b)
            return {**self._brand_view(b), "kept": len(kept), "discarded": len(ids) - len(kept)}

    def add_logo(self, bid, data, ctype="", name=""):
        """A logo dropped by the person: a new candidate, chosen at once (and confirmed: the person gave it)."""
        ext = workflow.logo_ext(data, ctype)
        mime = {"png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}[ext]
        with self.lock:
            self._tick()
            b = self._b(bid)
            lid = self._new_id("logo-up")
            b["logos"].append({"id": lid, "note": "Logo déposé, " + ext, "preview": f"data:{mime};base64," + base64.b64encode(data).decode()})
            b["logo"], b["logo_state"] = lid, "confirmed"
            self._touch(b)
            return self._brand_view(b)

    def get_brand_brief(self, bid):
        with self.lock:
            self._tick()
            return self._brief_view(self._b(bid))

    def put_brand_brief(self, bid, fields):
        with self.lock:
            self._tick()
            b = self._b(bid)
            if not isinstance(fields, dict):
                raise ValueError("fields: an object")
            unknown = set(fields) - set(workflow.FIELD_KEYS)
            if unknown:
                raise ValueError(f"brief: unknown field {', '.join(sorted(unknown))}")
            palette = workflow.parse_palette(fields["colours"]) if isinstance(fields.get("colours"), list) else None  # the pickers; a string is the person's words
            now = self._identity(b)
            todo = {}
            for k in workflow.FIELD_KEYS:
                if k == "colours" and palette:
                    continue
                text = ", ".join(workflow.split_words(fields.get(k))) if k in ("voice", "never") else one_line(fields.get(k))
                if text:
                    todo[k] = text
            if not (todo.get("what") or now["what"]["value"]):
                raise ValueError("brief: what is required (what the brand is)")
            for k, text in todo.items():
                cur = now[k]
                if cur["state"] == "deduced" and text == cur["value"]:
                    self._confirm_key(b, k)  # read and kept as it is: confirmed, not typed
                elif not (cur["state"] == "confirmed" and text == cur["value"]):
                    b["fields"][k] = field(text, "confirmed", "tapé")
            if palette:  # the colours chosen are the brand's colours, confirmed; what was said of them in words is no longer
                b["colours"] = [{**c, "state": "confirmed", "source": "choisie par toi"} for c in palette]
                b["fields"].pop("colours", None)
            b["brief_done"] = True
            self._touch(b)
            return self._brief_view(b)

    def _confirm_key(self, b, k):
        if k == "logo":
            b["logo_state"] = "confirmed"
            return
        if k == "colours":
            for c in b["colours"]:
                c["state"] = "confirmed"
        cur = b["fields"].get(k)
        if cur and cur["state"] == "deduced":
            b["fields"][k] = field(cur["value"], "confirmed", cur["source"])

    def confirm(self, bid, keys=None):
        with self.lock:
            self._tick()
            b = self._b(bid)
            if keys is None:
                keys = list(self._bstate(b)["deduced"])
            if not isinstance(keys, list) or set(keys) - set(workflow.CONFIRMABLE):
                raise ValueError(f"keys: any of {', '.join(workflow.CONFIRMABLE)}")
            ident = self._identity(b)
            for k in keys:
                if (k == "logo" and not b["logo"]) or (k != "logo" and ident[k]["state"] == "absent"):
                    raise ValueError(f"{k}: there is nothing to confirm, give it instead")
            for k in keys:
                self._confirm_key(b, k)
            if not self._bstate(b)["deduced"]:
                b["migrated"] = False
            self._touch(b)
            return self._brand_view(b)

    # ---------- routes: the personas of the brand ----------
    def _personas_view(self, b):
        run = self._running("personas", brand=b["id"])
        last = next((j for j in reversed(list(self.jobs.values())) if j["kind"] == "personas" and j["brand"] == b["id"]), None)
        return {"personas": list(b.get("personas", [])), "proposed": list(b.get("proposed", [])), "can_propose": b["brief_done"],
                "job": job_view(run) if run else None, "error": last["error"] if last and last["status"] == "failed" else None}

    def get_personas(self, bid):
        with self.lock:
            self._tick()
            return self._personas_view(self._b(bid))

    def propose_personas(self, bid):
        """The personas agent: up to four, from what the studio knows of the brand (a job). The simulated one answers PERSONAS."""
        with self.lock:
            self._tick()
            b = self._b(bid)
            if not b["brief_done"]:
                raise Conflict("the brief of the brand is not done: the personas come from it")
            if self._running("personas", brand=bid):
                raise Conflict("the personas are already being proposed")
            return job_view(self._job("personas", brand=bid))

    def put_personas(self, bid, personas):
        """The personas the person keeps (corrected, or written by hand): only these are the brand's. The proposal is settled."""
        texts = workflow.personas_of(personas)
        with self.lock:
            self._tick()
            b = self._b(bid)
            b["personas"], b["proposed"] = texts, []
            return self._personas_view(b)

    # ---------- routes: the names of the brand ----------
    def _names_view(self, b):
        run = self._running("names", brand=b["id"])
        last = next((j for j in reversed(list(self.jobs.values())) if j["kind"] == "names" and j["brand"] == b["id"]), None)
        return {"name": b["name"], "names": list(b.get("names", [])), "proposed": list(b.get("names_proposed", [])), "can_propose": b["brief_done"],
                "job": job_view(run) if run else None, "error": last["error"] if last and last["status"] == "failed" else None}

    def get_names(self, bid):
        with self.lock:
            self._tick()
            return self._names_view(self._b(bid))

    def propose_names(self, bid):
        """The names agent: up to eight, from the brief of the brand (a job). The simulated one answers NAMES."""
        with self.lock:
            self._tick()
            b = self._b(bid)
            if not b["brief_done"]:
                raise Conflict("the brief of the brand is not done: the names come from it")
            if self._running("names", brand=bid):
                raise Conflict("the names are already being proposed")
            return job_view(self._job("names", brand=bid))

    def put_names(self, bid, names, chosen=None):
        """The names the person keeps (or wrote); `chosen`, one of them, becomes the brand's name. The proposal is settled."""
        kept = workflow.names_of(names)
        name = workflow.chosen_of(chosen, kept)
        with self.lock:
            self._tick()
            b = self._b(bid)
            b["names"], b["names_proposed"] = kept, []
            if name:
                b["name"] = name
                self._touch(b)
            return self._names_view(b)

    # ---------- routes: competitors of the brand ----------
    def _competitors_view(self, b):
        run = self._running("competitors", brand=b["id"])
        last = next((j for j in reversed(list(self.jobs.values())) if j["kind"] == "competitors" and j["brand"] == b["id"]), None)
        return {"competitors": list(b.get("competitors", [])), "proposed": list(b.get("competitors_proposed", [])), "can_propose": b["brief_done"],
                "job": job_view(run) if run else None, "error": last["error"] if last and last["status"] == "failed" else None}

    def get_competitors(self, bid):
        with self.lock:
            self._tick()
            return self._competitors_view(self._b(bid))

    def propose_competitors(self, bid):
        """The competitors agent: up to six, from what the studio knows of the brand (a job). The simulated one answers COMPETITORS."""
        with self.lock:
            self._tick()
            b = self._b(bid)
            if not b["brief_done"]:
                raise Conflict("the brief of the brand is not done: the competitors come from it")
            if self._running("competitors", brand=bid):
                raise Conflict("the competitors are already being proposed")
            return job_view(self._job("competitors", brand=bid))

    def put_competitors(self, bid, competitors):
        """The competitors the person keeps (corrected, or written by hand): only these are the brand's. The proposal is settled."""
        texts = workflow.competitors_of(competitors)
        with self.lock:
            self._tick()
            b = self._b(bid)
            b["competitors"], b["competitors_proposed"] = texts, []
            return self._competitors_view(b)

    # ---------- routes: texts of a project ----------
    def _texts_view(self, p):
        run = self._running("texts", project=p["id"])
        last = next((j for j in reversed(list(self.jobs.values())) if j["kind"] == "texts" and j["project"] == p["id"]), None)
        return {"texts": list(p["texts"]["kept"]), "proposed": list(p["texts"]["proposed"]), "can_propose": p["brief"]["confirmed"],
                "job": job_view(run) if run else None, "error": last["error"] if last and last["status"] == "failed" else None}

    def get_texts(self, pid):
        with self.lock:
            self._tick()
            return self._texts_view(self._p(pid))

    def propose_texts(self, pid):
        """The texts agent: up to six hooks and posts, from the brief of the project (a job). The simulated one answers TEXTS."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            if not p["brief"]["confirmed"]:
                raise Conflict("the brief is not confirmed yet: the texts come from it")
            if self._running("texts", project=pid):
                raise Conflict("the texts are already being proposed")
            return job_view(self._job("texts", project=pid))

    def put_texts(self, pid, texts):
        """The texts the person keeps (corrected, or written by hand): only these are the project's. The proposal is settled."""
        kept = workflow.texts_of(texts)
        with self.lock:
            self._tick()
            p = self._p(pid)
            p["texts"].update(kept=kept, proposed=[])
            return self._texts_view(p)

    # ---------- routes: projects ----------
    def list_projects(self):
        with self.lock:
            self._tick()
            return [{"id": p["id"], "name": p["name"], "brand": p["brand"], "brand_name": self.brands[p["brand"]]["name"],
                     "waiting": len(self.view(p)["waiting"])} for p in self.projects.values()]

    def create_project(self, name, src=None, brand=None, site=None):
        """For the callers that make a project in one go: `from` makes a declination in the same brand; otherwise the brand is found by its
        name (or made, and its site read)."""
        with self.lock:
            self._tick()
            if src:
                base = self._p(src)
                return self.view(self._project(self.brands[base["brand"]], one_line(name) or "Nouveau projet", base))
            if not one_line(brand):
                raise ValueError("brand: give the brand's name")
            b = next((x for x in self.brands.values() if x["name"].casefold() == one_line(brand).casefold()), None)
            if b is None:
                self.create_brand(brand, site)
                b = next(x for x in self.brands.values() if x["name"].casefold() == one_line(brand).casefold())
            return self.view(self._project(b, one_line(name) or "Nouveau projet"))

    def create_project_in(self, bid, name, src=None):
        with self.lock:
            self._tick()
            b = self._b(bid)
            base = None
            if src:
                base = self.projects.get(src)
                if not base or base["brand"] != bid:
                    raise ValueError("from: give a project of the same brand")
            return self.view(self._project(b, one_line(name) or "Nouveau projet", base))

    def update_project(self, pid, name=None):
        with self.lock:
            p = self._p(pid)
            if name is not None:
                if not one_line(name):
                    raise ValueError("name: give the project's name")
                p["name"] = one_line(name)
            return self.view(p)

    def project(self, pid):
        with self.lock:
            self._tick()
            return self.view(self._p(pid))

    # ---------- routes: the brand seen from a project (kept for the callers that still use them) ----------
    def learn(self, pid, mode="learn", answers=None):
        with self.lock:
            self._tick()
            b = self.brands[self._p(pid)["brand"]]
            if mode not in ("learn", "answer", "create"):
                raise ValueError("mode is learn, answer or create")
            if mode == "answer" and not (answers or "").strip():
                raise ValueError("answer: say what you know of the brand")
            if answers:
                b["answers"] = str(answers)
            if mode == "learn":
                return self.discover(b["id"])
            b["discovered"] = True
            if mode == "answer":
                b["fields"]["what"] = field(one_line(answers)[:600], "confirmed", "tapé")
            self._touch(b)
            return {"id": None, "status": "done", "progress": 1.0, "message": "sans recherche", "result": None}

    @staticmethod
    def _legacy_colours(b):
        return [{"hex": c["hex"], "status": "to confirm" if c["state"] == "deduced" else "confirmed", "source": c["source"]} for c in b["colours"]]

    def brand(self, pid):
        with self.lock:
            self._tick()
            b = self.brands[self._p(pid)["brand"]]
            return {"name": b["name"], "evidence": b["evidence"], "logos": b["logos"], "logo": b["logo"], "colours": self._legacy_colours(b),
                    "kept": b["kept"], "answers": b["answers"]}

    def keep(self, pid, kept, logo):
        with self.lock:
            b = self.brands[self._p(pid)["brand"]]
            r = self.keep_brand(b["id"], kept, logo)
            return {"kept": r["kept"], "discarded": r["discarded"], "logo": logo, "colours": self._legacy_colours(b)}

    # ---------- routes: the brief of the project ----------
    def get_brief(self, pid):
        with self.lock:
            p = self._p(pid)
            return {"fields": p["brief"]["fields"], "confirmed": p["brief"]["confirmed"], "formats": list(FORMATS),
                    "chosen": self._formats(p), "left_out": self._left_out(p)}

    def put_brief(self, pid, fields):
        with self.lock:
            self._tick()
            p = self._p(pid)
            if not workflow.brand_ready(self._bstate(self.brands[p["brand"]])):
                raise Conflict("the brand is not ready yet")
            for k in ("objective", "audience", "message"):
                if not (fields.get(k) or "").strip():
                    raise ValueError(f"brief: {k} is required")
            p["brief"]["fields"].update({k: workflow.brief_personas_of(v) if k == "personas" else str(v) for k, v in fields.items()})
            p["brief"]["confirmed"] = True
            self._mark(p, "brief", "mandates")
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
            self._mark(p, "mandates", "diverge")
            return p["mandates"]

    def diverge(self, pid):
        with self.lock:
            p = self._p(pid)
            if not p["mandates"]["confirmed"]:
                raise Conflict("the instructions to the agents are not read yet")
            p["variants"], p["pieces"] = [], []
            return job_view(self._job("diverge", project=pid))

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
                                        "composed": None, "check": None, "decision": None, "judge": None, "readers": [], "status": "picked"})
            self._mark(p, "diverge", "image")
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

    def put_variant_prompt(self, pid, vid, prompt):
        """The prompt of a variant, shared by its formats: written in each of its pieces that still wait for their image."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            if not (prompt or "").strip():
                raise ValueError("the prompt is empty")
            mine = [pc for pc in p["pieces"] if pc["variant"] == vid]
            if not mine:
                raise NotFound(f"no variant {vid} in the series")
            todo = [pc for pc in mine if not pc["image"] and not self._running("image", project=pid, piece=pc["id"])]
            if not todo:
                raise Conflict("every piece of this variant has its image: redo one of them to change its prompt")
            for pc in todo:
                pc["prompt"] = prompt
            return copy.deepcopy(todo)

    def put_variant_text(self, pid, vid, headline, subline=None):
        """The words of a variant corrected, for its formats: the headline (required), the subline (`""` removes it; None leaves it)."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            headline = one_line(headline)[:200]
            if not headline:
                raise ValueError("headline: give the headline")
            mine = [pc for pc in p["pieces"] if pc["variant"] == vid]
            if not mine:
                raise NotFound(f"no variant {vid} in the series")
            todo = [pc for pc in mine if not pc["composed"]]
            if not todo:
                raise Conflict("every piece of this variant is composed: send one back (redo its image) to change its words")
            for pc in todo:
                pc["headline"] = headline
                if subline is not None:
                    pc["subline"] = one_line(subline)[:300]
            return copy.deepcopy(todo)

    def draw_images(self, pid, variant=None):
        """Draw every image that is missing (those of one variant when `variant` is given): one job per piece."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            if variant and not any(pc["variant"] == variant for pc in p["pieces"]):
                raise ValueError(f"variant: no {variant} in the series")
            todo = [pc["id"] for pc in p["pieces"] if (not variant or pc["variant"] == variant) and not pc["image"] and not self._running("image", project=pid, piece=pc["id"])]
            if not todo:
                raise Conflict("every piece has its image, or is being drawn")
            return {"jobs": [self.image(pid, i) for i in todo]}

    def compose_all(self, pid):
        """Compose and check every piece that has its image and is not composed yet."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            todo = [pc["id"] for pc in p["pieces"] if pc["image"] and not pc["composed"]]
            if not todo:
                raise Conflict("no piece waits to be composed")
            return {"composed": [self.compose(pid, i)["id"] for i in todo], "failed": []}

    def image(self, pid, i):
        with self.lock:
            p = self._p(pid)
            pc = self._piece(p, i)
            pc["image"], pc["composed"], pc["check"], pc["decision"], pc["judge"], pc["readers"] = None, None, None, None, None, []
            return job_view(self._job("image", project=pid, piece=i))

    def compose(self, pid, i):
        with self.lock:
            self._tick()
            p = self._p(pid)
            pc = self._piece(p, i)
            if not pc["image"]:
                raise Conflict("no image yet")
            pc["composed"] = f"{self.static}/piece.png"
            pc["check"] = {"pass": 10, "warn": 2, "fail": 0, "major": 0,
                           "notes": [{"status": "warn", "say": "deux valeurs de la marque sont encore à confirmer (la police, le logo)"},
                                     {"status": "warn", "say": "le contraste du titre dépend de l'image : regarder la pièce"}]}
            pc["status"] = "composed"
            self._mark(p, "image", "piece", "decide")
            self._judge(pid, pc)  # the judge reads the piece once it is composed and checked: it blocks nothing
            pc["readers"] = [self._reader(n, x, project=pid, piece=i)[1] for n, x in enumerate(workflow.brief_personas_of(p["brief"]["fields"].get("personas")))]
            return copy.deepcopy(pc)

    def _png(self, pc):
        """The composed piece: the simulated studio has one picture for all of them (static/stub/piece.png)."""
        return (Path(__file__).resolve().parent / "static" / self.static / "piece.png").read_bytes()

    # ---------- routes: storyboard (the script and the shots of the project's film, then the film) ----------
    def _storyboard_view(self, p):
        sb = p.get("storyboard") or {}
        run, frun = self._running("storyboard", project=p["id"]), self._running("film", project=p["id"])
        return workflow.storyboard_view(sb, p["brief"]["confirmed"], run["id"] if run else None, None,
                                        {"url": f"{self.static}/film.mp4", "seconds": 2.0} if sb.get("film") else None, frun["id"] if frun else None, None)

    def get_storyboard(self, pid):
        with self.lock:
            self._tick()
            return self._storyboard_view(self._p(pid))

    def propose_storyboard(self, pid):
        """The storyboard agent: the script and the shots (a job). The simulated one answers STORYBOARD."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            if not p["brief"]["confirmed"]:
                raise Conflict("the brief is not confirmed: the film comes from it")
            if self._running("storyboard", project=pid):
                raise Conflict("the storyboard is already being proposed")
            if self._running("film", project=pid):
                raise Conflict("le film du projet est en cours de rendu : attends qu'il soit fini pour toucher au découpage")
            return job_view(self._job("storyboard", project=pid))

    def put_storyboard(self, pid, script, shots):
        """The storyboard the person corrected and keeps; the film of an older one is dropped."""
        with self.lock:
            self._tick()
            p = self._p(pid)
            if not p["brief"]["confirmed"]:
                raise Conflict("the brief is not confirmed: the film comes from it")
            if self._running("film", project=pid):
                raise Conflict("le film du projet est en cours de rendu : attends qu'il soit fini pour toucher au découpage")
            try:
                p["storyboard"] = {**workflow.parse_storyboard({"script": script, "shots": shots}), "saved": True, "film": False}
            except ValueError as err:
                raise ValueError(f"storyboard: {err}") from None
            return self._storyboard_view(p)

    def render_film(self, pid):
        with self.lock:
            self._tick()
            p = self._p(pid)
            if not (p.get("storyboard") or {}).get("saved"):
                raise Conflict("the storyboard is not saved: read it, correct it and save it first")
            if self._running("film", project=pid):
                raise Conflict("the film is already being made")
            return job_view(self._job("film", project=pid))

    def download_film(self, pid):
        with self.lock:
            self._tick()
            if not (self._p(pid).get("storyboard") or {}).get("film"):
                raise Conflict("the film is not made yet")
            return Download(f"{pid}.mp4", "video/mp4", (Path(__file__).resolve().parent / "static" / self.static / "film.mp4").read_bytes())

    def download_piece(self, pid, i):
        """The composed piece as a png file (at its size in the real studio; the simulated one has one picture)."""
        with self.lock:
            self._tick()
            pc = self._piece(self._p(pid), i)
            if not pc["composed"]:
                raise Conflict("this piece is not composed yet")
            return Download(f"{pid}-{i}.png", "image/png", self._png(pc))

    def download_project(self, pid):
        """Every piece kept, in a zip."""
        with self.lock:
            self._tick()
            kept = [pc for pc in self._p(pid)["pieces"] if pc["composed"] and (pc["decision"] or {}).get("verdict") == "keep"]
            if not kept:
                raise Conflict("no piece is kept yet")
            return Download(f"{pid}.zip", "application/zip", workflow.zip_of([(f"{pid}-{pc['id']}.png", self._png(pc)) for pc in kept]))

    def decide(self, pid, i, verdict, words):
        with self.lock:
            p = self._p(pid)
            pc = self._piece(p, i)
            if verdict not in ("keep", "again"):
                raise ValueError("verdict is keep or again")
            if not pc["composed"]:
                raise Conflict("nothing to decide yet")
            if verdict == "again" and not (words or "").strip():
                raise ValueError("say what is wrong: it is remembered for the next round")
            pc["decision"] = {"verdict": verdict, "words": words, "at": time.time()}
            self._mark(p, "decide")
            if verdict == "again":
                pc["image"], pc["composed"], pc["check"], pc["judge"], pc["readers"], pc["status"] = None, None, None, None, [], "again"
                pc["decision"] = None
                pc["bans"] = pc.get("bans", []) + [words]
            return copy.deepcopy(pc)

    # ---------- the judge ----------
    def _verdict(self, bid, brief):
        """The fixed verdict, as the real judge's goes through workflow: the brand heading only with a brand, what the brief lacks said."""
        return workflow.parse_verdict(copy.deepcopy(VERDICT), bool(bid), workflow.judge_brief(brief))

    def _judge(self, pid, pc):
        j = self._job("judge", project=pid, piece=pc["id"])
        pc["judge"] = {**workflow.judge_view("running", None), "job": j["id"]}
        return j

    def judge_piece(self, pid, i):
        """Run the judge of a composed piece again."""
        with self.lock:
            self._tick()
            pc = self._piece(self._p(pid), i)
            if not pc["composed"]:
                raise Conflict("this piece is not composed yet")
            if self._running("judge", project=pid, piece=i):
                raise Conflict("the judge is already reading this piece")
            return job_view(self._judge(pid, pc))

    def _jg(self, jid):
        jg = self.judgements.get(jid)
        if not jg:
            raise NotFound(f"no judgement {jid}")
        return jg

    def _jg_status(self, jg):
        if any(j["judgement"] == jg["id"] and j["kind"] == "judge" and j["status"] == "running" for j in self.jobs.values()):
            return "running"
        return "done" if jg["verdict"] else "failed" if jg["error"] else "running"

    def _jg_view(self, jg):
        st = self._jg_status(jg)
        job = next((j["id"] for j in self.jobs.values() if j["judgement"] == jg["id"] and j["kind"] == "judge" and j["status"] == "running"), None)
        return {"id": jg["id"], "name": jg["name"], "brand": jg["brand"], "brand_name": jg["brand_name"], "brief": dict(jg["brief"]), "image": jg["image"],
                "at": jg["at"], "status": st, "verdict": copy.deepcopy(jg["verdict"]) if st == "done" else None, "error": jg["error"] if st == "failed" else None,
                "missing": workflow.judge_missing(jg["brief"]), "job": job, "readers": copy.deepcopy(jg["readers"])}

    def list_judgements(self):
        """The judgements made on their own, the newest first."""
        with self.lock:
            self._tick()
            return [{k: v[k] for k in ("id", "name", "brand", "brand_name", "status", "at")} for v in
                    (self._jg_view(jg) for jg in sorted(self.judgements.values(), key=lambda x: -x["at"]))]

    def create_judgement(self, data, ctype="", name="", meta=None):
        """A piece dropped to be judged on its own, with the brief it answers and, if any, its brand: the judge starts at once."""
        ext = workflow.judge_image_ext(data, ctype)
        m = workflow.judge_meta(meta)
        with self.lock:
            self._tick()
            b = None
            if m["brand"]:
                b = self.brands.get(m["brand"])
                if not b:
                    raise ValueError(f"brand: no brand {m['brand']}")
            jid = self._new_id("jugement")
            mime = {"png": "image/png", "jpg": "image/jpeg"}[ext]
            label = m["name"] or one_line(Path(name or "").stem) or "Pièce à juger"
            jg = {"id": jid, "name": label[:120], "brand": b["id"] if b else None, "brand_name": b["name"] if b else "", "brief": m["brief"],
                  "image": f"data:{mime};base64," + base64.b64encode(data).decode(), "at": time.time(), "verdict": None, "error": None}
            self.judgements[jid] = jg
            self._job("judge", judgement=jid)
            jg["readers"] = [self._reader(n, x, judgement=jid)[1] for n, x in enumerate(m["brief"]["personas"])]
            return self._jg_view(jg)

    def judgement(self, jid):
        with self.lock:
            self._tick()
            return self._jg_view(self._jg(jid))

    def run_judgement(self, jid):
        """Run the judge of a judgement again (after a failure, or to read it once more)."""
        with self.lock:
            self._tick()
            jg = self._jg(jid)
            if self._jg_status(jg) == "running":
                raise Conflict("the judge is already reading this piece")
            jg["verdict"], jg["error"] = None, None
            return job_view(self._job("judge", judgement=jid))

    # ---------- the readers: one per persona of the brief, beside the judge ----------
    def _reader(self, n, persona, project=None, piece=None, judgement=None):
        """Start reader `n`: its job and its view (running)."""
        j = self._job("reader", project=project, piece=piece, judgement=judgement, reader=n)
        return j, workflow.reader_view(n, persona, j, None)

    def _readers_of(self, j):
        if j["judgement"]:
            return (self.judgements.get(j["judgement"]) or {}).get("readers") or []
        p = self.projects.get(j["project"])
        pc = next((x for x in p["pieces"] if x["id"] == j["piece"]), None) if p else None
        return (pc or {}).get("readers") or []

    def _read(self, j):
        """A reader's job ends: its fixed reading, or its failure when its persona says "fail". A reader started again since keeps the new one."""
        rs = self._readers_of(j)
        r = next((x for x in rs if x["job"] == j["id"]), None)
        if not r:
            return
        if "fail" in r["persona"].lower():
            j["status"], j["error"] = "failed", "le lecteur n'a pas répondu (simulé)"
            j["message"] = j["error"]
            rs[r["n"]] = workflow.reader_view(r["n"], r["persona"], j, None)
        else:
            rs[r["n"]] = workflow.reader_view(r["n"], r["persona"], None, {"persona": r["persona"], "reading": workflow.parse_reading(copy.deepcopy(READING))})

    def _rerun(self, rs, n, **owner):
        if not 0 <= n < len(rs):
            raise NotFound(f"no reader {n}")
        if rs[n]["status"] == "running":
            raise Conflict("this reader is already reading the piece")
        j, rs[n] = self._reader(n, rs[n]["persona"], **owner)
        return job_view(j)

    def run_reader(self, pid, i, n):
        """Run reader `n` of a composed piece again, alone."""
        with self.lock:
            self._tick()
            pc = self._piece(self._p(pid), i)
            if not pc["composed"]:
                raise Conflict("this piece is not composed yet")
            return self._rerun(pc.setdefault("readers", []), n, project=pid, piece=i)

    def run_judgement_reader(self, jid, n):
        """Run reader `n` of a judgement again, alone."""
        with self.lock:
            self._tick()
            return self._rerun(self._jg(jid)["readers"], n, judgement=jid)

    def judgement_page(self, jid):
        """The flat page of a judgement (the piece at the top, the list under it), as a file."""
        with self.lock:
            self._tick()
            v = self._jg_view(self._jg(jid))
            if v["status"] != "done":
                raise Conflict("the judge has not given its verdict yet")
            page = workflow.judge_page(v["verdict"], v["image"], v["name"], v["brand_name"], time.strftime("%Y-%m-%d", time.localtime(v["at"])))
            return Download(f"{jid}.html", "text/html; charset=utf-8", page.encode("utf-8"))
