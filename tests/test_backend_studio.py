"""The real backend of the interface (app/backend_studio.py), end to end through the HTTP API.

The tools of this repository (scripts/studio, scripts/brandkit) run for real, offline. What costs something, or needs
the network, is faked by the runner the backend is given: `node collect.mjs` (it would open Chrome on a site), `claude -p`
(the writing agents) and `studio image` (Codex or an API). Nothing here calls claude, codex or the network.

    python3 -m unittest discover -s tests
"""

import json
import os
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))

import backend_studio  # noqa: E402
import server  # noqa: E402
import workflow  # noqa: E402
from backend_studio import Result, StudioBackend, normalise_site, run_command  # noqa: E402


def png(w=64, h=80, rgb=(200, 80, 40)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


VARIANT = {"default": {"headline": "Le titre qu'on aurait fait", "image": "Le produit sur une table"}, "subline": "", "ground": "background",
           "why": "Il regarde ailleurs."}
LAYOUTS = ["side", "stack", "ground", "overlay-top"]
JUDGED = {"target": {"reached": "partly", "why": "Un citadin comprend la boisson, pas pourquoi la choisir."}, "score": 7,
          "works": [{"where": "l'image", "say": "La lumière installe le matin."}],
          "snags": [{"where": "le titre en haut", "say": "Un double sens possible sur « plus rien »."}],
          "unsourced": [{"where": "le bandeau du bas", "say": "« n°1 en ville » : rien ne permet de le croire."}],
          "brand": [{"where": "le titre en haut", "say": "C'est sa voix, franche."}]}


class Fake:
    """The runner: the repository's own tools for real, offline; node, claude and the image engines faked and recorded."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()
        self.agents_fail = set()  # variant ids whose agent writes nothing
        self.claude_down = False  # every claude call fails
        self.image_fails = False
        self.fake_png = True  # the screenshot (Chrome) is faked unless a test says otherwise
        self.collect_fails = False
        self.extra_screen = False  # the next reading of a site finds one more visual
        self.hold = None  # an Event: claude calls wait for it
        self.env_seen = []
        self.judge = "ok"  # what the judge writes: ok (a verdict), none (nothing), bad (a verdict that does not hold)
        self.judge_hold = None  # an Event: the judge waits for it
        self.inputs = ""  # the inputs.md the last judge read
        self.readers = []  # the inputs.md each reader read

    def tool_env(self):
        env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(STUDIO_OFFLINE="1", CHROME="/nonexistent/chrome")
        env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if p and not (Path(p) / "codex").exists() and not (Path(p) / "claude").exists())
        return env

    def __call__(self, argv, cwd=None, env=None, timeout=None):
        argv = [str(a) for a in argv]
        with self.lock:
            self.calls.append({"argv": argv, "cwd": cwd, "env": dict(env or {}), "ls": sorted(os.listdir(cwd)) if cwd and os.path.isdir(cwd) else None})
        exe = Path(argv[0]).name
        if exe == "node":
            return self.node(argv)
        if exe == "claude":
            return self.claude(argv, cwd)
        if exe.startswith("python") and Path(argv[1]).name in ("studio", "brandkit"):
            if Path(argv[1]).name == "studio" and argv[2] == "image":
                return self.image(argv)
            r = run_command(argv, cwd=cwd, env=self.tool_env(), timeout=timeout)
            if Path(argv[1]).name == "studio" and argv[2] == "compose" and self.fake_png:
                d = Path(argv[3])
                if not (d / "piece.png").exists():
                    (d / "piece.png").write_bytes(png(108, 135))
            return r
        raise AssertionError(f"the tests do not expect this command: {argv[:3]}")

    # node collect.mjs <site> <out>
    def node(self, argv):
        if self.collect_fails:
            return Result(1, "", "collect: no Chrome found (set CHROME=/path/to/chrome)")
        site, out = argv[2], Path(argv[3])
        out.mkdir(parents=True, exist_ok=True)
        (out / "screen-01.png").write_bytes(png(rgb=(200, 80, 40)))
        (out / "screen-02.png").write_bytes(png(rgb=(30, 60, 50)))
        if self.extra_screen:
            (out / "screen-03.png").write_bytes(png(rgb=(10, 90, 140)))
        (out / "logo-svg-1.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40"><rect width="120" height="40" fill="#222"/></svg>')
        logo = {"kind": "logo", "file": "logo-svg-1.svg", "src": "inline SVG on the page", "format": "svg", "where": "header svg"}
        facts = {"url": site, "final_url": "file:///fake-site/", "at": "2026-10-24T10:00:00Z", "title": "Site de test", "lang": "fr-FR",
                 "files": [{"kind": "screen", "file": "screen-01.png", "note": "y=0px"}, {"kind": "screen", "file": "screen-02.png", "note": "y=900px"}]
                 + ([{"kind": "screen", "file": "screen-03.png", "note": "y=1800px"}] if self.extra_screen else []) + [logo],
                 "logos": [logo],
                 "colours": {"ground": [{"hex": "#f4efe6", "share": 0.6}, {"hex": "#1e2a24", "share": 0.2}], "type": [{"hex": "#1e2a24", "share": 0.7}],
                             "heading": [{"hex": "#1e2a24", "share": 0.8}], "accent": [{"hex": "#c8553d", "share": 0.5}]},
                 "painted_hex": [], "vars": [], "fonts": {"heading": [{"family": "Archivo", "share": 0.9, "sizes": ["40px"], "weight": "700"}],
                                                          "body": [{"family": "Inter", "share": 0.9, "sizes": ["16px"], "weight": "400"}], "ui": []},
                 "rendered_fonts": {}, "font_faces": [], "missing": []}
        (out / "facts.json").write_text(json.dumps(facts))
        return Result(0, f"collect {site}\n", "")

    def claude(self, argv, cwd):
        if self.hold is not None:
            self.hold.wait(10)
        if self.claude_down:
            return Result(1, "", "Claude Code is not signed in")
        prompt = argv[2]
        if "./verdict.json" in prompt:
            return self.judge_agent(prompt, cwd)
        if "./reading.json" in prompt:
            return self.reader_agent(cwd)
        if "--tools" in argv and argv[argv.index("--tools") + 1] == "":  # the instructions
            body = json.dumps({"common": "Écrire en français. Rien d'inventé.", "mandates": ["Le goût d'abord", "Démonter l'idée reçue", "Le temps long", "Rupture : l'entre-deux"]})
            return Result(0, "Voilà ma proposition :\n```json\n" + body + "\n```\n", "")
        vid = re.search(r"\./(v\d+)\.json", prompt).group(1)
        if vid in self.agents_fail:
            return Result(0, "", "")
        mandate = re.search(r"Your mandate: (.*)", prompt).group(1)
        n = int(vid[1:])
        v = {"mandate": mandate, "headline": f"Titre de {vid}", "image_prompt": f"Une image pour {vid}, aucun texte.", "layout": LAYOUTS[n % 4], **VARIANT}
        (Path(cwd) / f"{vid}.json").write_text(json.dumps(v), encoding="utf-8")
        return Result(0, f"{vid}.json\n", "")

    def judge_agent(self, prompt, cwd):
        if self.judge_hold is not None:
            self.judge_hold.wait(10)
        self.inputs = (Path(cwd) / "inputs.md").read_text(encoding="utf-8")
        if self.judge == "none":
            return Result(1, "", "the judge gave up")
        v = {"target": {"reached": "maybe"}} if self.judge == "bad" else JUDGED
        (Path(cwd) / "verdict.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        return Result(0, "verdict.json\n", "")

    def reader_agent(self, cwd):
        """A reader: what it read is kept (`readers`); a persona that says "fail" writes nothing."""
        text = (Path(cwd) / "inputs.md").read_text(encoding="utf-8")
        with self.lock:
            self.readers.append(text)
        if "fail" in text:
            return Result(1, "", "the reader gave up")
        r = {"aimed": "partly", "why": "Je me reconnais un peu.", "understand": "Une boisson.", "retain": "La bouteille.", "bother": "", "unread": "Le bas.",
             "lacks": "Le goût.", "buy": "oui"}
        (Path(cwd) / "reading.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
        return Result(0, "reading.json\n", "")

    def image(self, argv):
        d = Path(argv[3])
        if self.image_fails:
            return Result(0, "image: none: No image generator available: set OPENAI_API_KEY or install the Codex CLI\n", "")
        (d / "image.png").write_bytes(png(108, 135, (90, 120, 60)))
        (d / "image.json").write_text(json.dumps({"engine": "fake", "variant": "x", "prompt": "", "model": "", "message": "fake"}))
        return Result(0, "image: fake: drawn\n", "")

    def where(self, word):
        return [c for c in self.calls if word in c["argv"]]



class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = Path(tempfile.mkdtemp(prefix="ixs-home-"))
        cls.fake = Fake()
        cls.backend = StudioBackend(cls.home, runner=cls.fake)
        cls.httpd = server.serve("127.0.0.1", 0, cls.backend)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.shared = None

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        f = self.fake
        f.agents_fail, f.claude_down, f.image_fails, f.collect_fails, f.hold, f.fake_png, f.extra_screen = set(), False, False, False, None, True, False
        f.judge, f.judge_hold, f.readers = "ok", None, []

    def call(self, method, path, body=None, code=200, headers=None, raw=False):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                got, data = r.status, r.read()
        except urllib.error.HTTPError as err:
            got, data = err.code, err.read()
            err.close()
        out = data if raw else json.loads(data)
        self.assertEqual(got, code, out)
        return out

    def fetch(self, path, code=200):
        """A route that answers a file: (headers, bytes)."""
        try:
            with urllib.request.urlopen(self.base + path) as r:
                got, head, data = r.status, r.headers, r.read()
        except urllib.error.HTTPError as err:
            got, head, data = err.code, err.headers, err.read()
            err.close()
        self.assertEqual(got, code, data[:200])
        return head, data

    def wait(self, job, status="done"):
        for _ in range(500):
            j = self.call("GET", f"/api/jobs/{job['id']}")
            if j["status"] != "running":
                self.assertEqual(j["status"], status, j)
                return j
            time.sleep(0.02)
        self.fail("job never ended")

    def asks(self, pid):
        return [a["kind"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]]

    def step(self, pid, key):
        return next(s for s in self.call("GET", f"/api/projects/{pid}")["steps"] if s["key"] == key)

    def pdir(self, pid):
        return self.backend._pdir(pid)

    def bdir(self, bid):
        return self.home / "marques" / bid / "brand"

    def doc(self, bid):
        return json.loads((self.bdir(bid) / "brand.json").read_text())

    def brand_calls(self, bid, word):
        """The brandkit commands of a kind that were run on the dossier of a brand."""
        return [c["argv"] for c in self.fake.calls if len(c["argv"]) > 3 and Path(c["argv"][1]).name == "brandkit" and c["argv"][2] == word
                and c["argv"][3] == str(self.bdir(bid))]

    # ---- the path of a brand, in stages
    def mkbrand(self, name="Marrowbay Ferments", site="marrowbay.example"):
        """A brand; with a site, the reading is waited for. Returns its id."""
        body = {"name": name}
        if site is not None:
            body["site"] = site
        b = self.call("POST", "/api/brands", body)
        for j in b["jobs"]:
            self.wait(j)
        return b["id"]

    read = mkbrand  # the same: a brand whose site is read, its visuals waiting to be sorted

    def sort(self, bid):
        a = self.call("GET", f"/api/brands/{bid}")["assets"]
        return self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in a["evidence"] if e["proposed"]], "logo": a["logos"][0]["id"]})

    def ready_brand(self, **kw):
        bid = self.mkbrand(**kw)
        self.sort(bid)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un kombucha de port", "who": "des citadins", "voice": "franc, chaleureux, drôle",
                                                              "signature": "Servez-vous.", "never": "détox"}})
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "ready")
        return bid

    def deduce(self, bid, path, value):
        """A value the studio deduced (it is to confirm): a source of the dossier read from the site, as the reading of a site would add it."""
        d = self.bdir(bid)
        page = next(e for e in json.loads((d / "evidence.json").read_text()) if e["kind"] == "page")
        src = {"adapter": "inferred", "origin": "test", "label": "test", "evidence": [{"id": page["id"], "kind": "page", "where": page["where"], "at": "2026-10-24",
                                                                                  "ownership": "official", "ownership_given_by_user": True, "title": "t"}],
               "values": [{"path": path, "value": value, "confidence": "high", "rank": "text", "evidence": [page["id"]]}]}
        f = d / "deduced.tmp.json"
        f.write_text(json.dumps(src))
        res = run_command([sys.executable, str(backend_studio.BRANDKIT), "add", str(d), str(f)], env=self.fake.tool_env(), timeout=60)
        self.assertEqual(res.code, 0, res.err)
        f.unlink()

    # ---- the path of a project, in stages: each starts a new project in a brand that has been made ready once, for the whole class
    def shared_brand(self):
        if type(self).shared is None or not (self.home / "marques" / type(self).shared).exists():
            type(self).shared = self.ready_brand()
        return type(self).shared

    def started(self, name="Test", brand=None):
        return self.call("POST", f"/api/brands/{brand or self.shared_brand()}/projects", {"name": name})["id"]

    def briefed(self, formats="post-4x5, story", **kw):
        pid = self.started(**kw)
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "faire connaître", "audience": "des citadins", "message": "c'est bon", "format": formats}})
        self.settle_mandates(pid)
        return pid

    def settle_mandates(self, pid):
        for _ in range(500):
            if not [j for j in self.call("GET", "/api/tasks")["jobs"] if j["project"] == pid and j["kind"] == "mandates"]:
                return
            time.sleep(0.02)
        self.fail("mandates never ended")

    def confirmed(self, **kw):
        pid = self.briefed(**kw)
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": m["items"], "common": m["common"]})
        return pid

    def diverged(self, **kw):
        pid = self.confirmed(**kw)
        self.wait(self.call("POST", f"/api/projects/{pid}/diverge"))
        return pid

    def picked(self, ids=("v1", "v3"), **kw):
        pid = self.diverged(**kw)
        return pid, self.call("POST", f"/api/projects/{pid}/pick", {"variants": list(ids)})


class Layout(Base):
    def test_brands_and_projects_are_folders(self):
        bid = self.mkbrand(name="La Marque", site="https://Marrowbay.example/shop?x=1#top")
        self.assertEqual(bid, "la-marque")
        m = json.loads((self.home / "marques" / bid / "marque.json").read_text())
        self.assertEqual((m["id"], m["name"], m["site"], m["description"]), ("la-marque", "La Marque", "https://marrowbay.example/shop?x=1", ""))
        self.assertTrue((self.home / "marques" / bid / "brand" / "brand.json").is_file() and (self.home / "marques" / bid / "logs").is_dir())
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "La campagne de rentrée"})["id"]
        self.assertEqual(pid, "la-campagne-de-rentree")
        d = self.home / "marques" / bid / "projets" / pid
        p = json.loads((d / "project.json").read_text())
        self.assertEqual((p["name"], p["brand"], p["type"]), ("La campagne de rentrée", bid, "campagne"))
        self.assertTrue((d / "piece").is_dir() and (d / "logs").is_dir())
        v = self.call("GET", f"/api/projects/{pid}")
        self.assertEqual((v["brand"], v["brand_name"], v["can_learn"], v["type"]), (bid, "La Marque", True, "campagne"))
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["projects"][0]["id"], pid)
        other = self.mkbrand(name="L'autre", site=None)  # a project id is unique in the whole studio: the routes name it by its id alone
        self.assertEqual(self.call("POST", f"/api/brands/{other}/projects", {"name": "La campagne de rentrée"})["id"], "la-campagne-de-rentree-2")
        self.assertEqual(self.call("GET", "/api/projects/la-campagne-de-rentree-2")["brand"], other)
        self.assertEqual(self.mkbrand(name="La Marque", site=None), "la-marque-2")

    def test_a_brand_needs_a_name_and_the_site_is_optional(self):
        self.call("POST", "/api/brands", {"site": "x.example"}, code=400)
        self.call("POST", "/api/projects", {"name": "x"}, code=400)  # the one-go route wants a brand's name
        bid = self.mkbrand(name="Sans Site", site=None)
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual((b["stage"], b["can_discover"], b["site"], b["jobs"], [t["kind"] for t in b["waiting"]]), ("new", False, "", [], ["brand-brief"]))
        self.call("POST", f"/api/brands/{bid}/discover", code=409)  # no site: the studio cannot search, and says so
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "x"})["id"]
        self.assertFalse(self.call("GET", f"/api/projects/{pid}")["can_learn"])
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"}, code=400)
        self.assertFalse([c for c in self.fake.where("node") if bid in " ".join(c["argv"])])  # nothing was started

    def test_a_site_must_be_a_public_web_address(self):
        for bad in ("ftp://marrowbay.example", "http://localhost:8000", "http://127.0.0.1/", "http://192.168.1.4/", "intranet", "file:///etc/passwd"):
            self.call("POST", "/api/brands", {"name": "x", "site": bad}, code=400)
            self.call("POST", "/api/projects", {"name": "x", "brand": "B", "site": bad}, code=400)
        bid = self.mkbrand(name="Pour le site", site=None)
        self.call("PUT", f"/api/brands/{bid}", {"site": "http://localhost:8000"}, code=400)
        self.assertEqual(normalise_site(""), "")
        self.assertEqual(normalise_site("marrowbay.example"), "https://marrowbay.example/")
        self.assertEqual(self.call("GET", "/api/brands/" + bid)["site"], "")

    def test_the_one_go_route_finds_the_brand_by_its_name(self):
        bid = self.shared_brand()
        n = len(self.call("GET", "/api/brands"))
        pid = self.call("POST", "/api/projects", {"name": "En un coup", "brand": "marrowbay FERMENTS"})["id"]
        self.assertEqual(self.call("GET", f"/api/projects/{pid}")["brand"], bid)
        self.assertEqual(len(self.call("GET", "/api/brands")), n)
        new = self.call("POST", "/api/projects", {"name": "Neuve", "brand": "Marque Neuve", "site": "neuve.example"})
        self.assertEqual((new["brand_name"], new["brand_stage"]), ("Marque Neuve", "discovering"))  # a new brand with a site starts reading it
        self.wait(self.call("GET", f"/api/brands/{new['brand']}")["jobs"][0])

    def test_a_declination_copies_the_fields_of_the_brief_and_nothing_else(self):
        src = self.briefed()
        self.assertTrue((self.pdir(src) / "piece" / "brief.md").exists())
        new = self.call("POST", f"/api/brands/{self.shared_brand()}/projects", {"name": "Déclinaison", "from": src})
        self.assertEqual((new["brand"], new["type"], [a["kind"] for a in new["waiting"]]), (self.shared_brand(), "campagne", ["brief"]))
        self.assertEqual(self.call("GET", f"/api/projects/{new['id']}/brief")["fields"]["message"], "c'est bon")
        got = self.call("GET", f"/api/projects/{new['id']}/brief")
        self.assertFalse(got["confirmed"])  # to read again
        self.assertEqual(sorted(x.name for x in (self.pdir(new["id"]) / "piece").iterdir()), [])  # no file of the other project
        self.assertEqual(json.loads((self.pdir(new["id"]) / "project.json").read_text())["origin"], {"from": src})
        other = self.mkbrand(name="Une Autre Marque", site=None)
        self.call("POST", f"/api/brands/{other}/projects", {"name": "x", "from": src}, code=400)  # the project of another brand
        self.call("POST", f"/api/brands/{other}/projects", {"name": "x", "from": "nope"}, code=404)
        self.call("POST", "/api/projects", {"name": "x", "from": "nope"}, code=404)
        copy = self.call("POST", "/api/projects", {"name": "Copie", "from": src})  # the one-go route does the same
        self.assertEqual(copy["brand"], self.shared_brand())

    def test_a_brand_and_a_project_are_edited(self):
        bid = self.ready_brand(name="Nom Avant")
        b = self.call("PUT", f"/api/brands/{bid}", {"name": "Nom Après", "description": "Une brasserie.", "site": "https://apres.example/page"})
        self.assertEqual((b["id"], b["name"], b["description"], b["site"], b["stage"], b["jobs"]), (bid, "Nom Après", "Une brasserie.", "https://apres.example/page", "ready", []))
        self.assertEqual(json.loads((self.home / "marques" / bid / "marque.json").read_text())["name"], "Nom Après")
        self.assertTrue(self.brand_calls(bid, "answer")[-1][-2:] == ["identity.name", "Nom Après"])  # the dossier carries the name too
        self.call("PUT", f"/api/brands/{bid}", {"name": " "}, code=400)
        self.call("PUT", f"/api/brands/{bid}", {"site": "ftp://x.example"}, code=400)
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["name"], "Nom Après")
        self.call("PUT", "/api/brands/nope", {"name": "x"}, code=404)
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Avant"})["id"]
        p = self.call("PUT", f"/api/projects/{pid}", {"name": "Après"})
        self.assertEqual((p["id"], p["name"], p["brand_name"]), (pid, "Après", "Nom Après"))
        self.call("PUT", f"/api/projects/{pid}", {"name": ""}, code=400)
        self.call("PUT", "/api/projects/nope", {"name": "x"}, code=404)
        self.assertEqual([x["name"] for x in self.call("GET", f"/api/brands/{bid}")["projects"]], ["Après"])
        self.assertEqual(json.loads((self.pdir(pid) / "project.json").read_text())["name"], "Après")


class Brand(Base):
    def test_reading_the_site_lists_what_to_sort(self):
        b = self.call("POST", "/api/brands", {"name": "Lecture", "site": "marrowbay.example"})
        bid = b["id"]
        self.assertEqual((b["stage"], [j["kind"] for j in b["jobs"]], b["waiting"]), ("discovering", ["learn"], []))
        done = self.wait(b["jobs"][0])
        self.assertEqual(done["progress"], 1.0)
        calls = [c["argv"] for c in self.fake.calls if str(self.home / "marques" / bid) in " ".join(c["argv"])]
        collect = next(c for c in calls if Path(c[0]).name == "node")
        self.assertEqual(collect[1:3], [str(backend_studio.COLLECT), "https://marrowbay.example/"])
        self.assertEqual(Path(collect[3]), self.home / "marques" / bid / "brand" / "collect" / "web-marrowbay.example")
        kinds = [c[2] for c in calls if Path(c[1]).name == "brandkit"]
        self.assertEqual(kinds[:3], ["init", "infer-site", "review-html"])
        self.assertIn("--no-previews", next(c for c in calls if len(c) > 2 and c[2] == "review-html"))
        b = self.call("GET", f"/api/brands/{bid}")
        a = b["assets"]
        self.assertEqual(b["stage"], "to_sort")
        self.assertEqual([e["note"] for e in a["evidence"]], ["Capture du site, haut de la page", "Capture du site, plus bas (900 px)"])
        self.assertTrue(all(e["proposed"] is True and e["kept"] is None and e["kind"] == "image" for e in a["evidence"]))
        self.assertEqual((len(a["logos"]), a["logo"], a["visuals"]), (1, None, []))
        self.assertEqual([(t["kind"], t["title"], t["scope"]) for t in b["waiting"]], [("brand-sort", "Trier 2 visuels de la marque", "brand")])
        self.assertEqual({k: v["state"] for k, v in b["identity"].items()}, {"what": "absent", "who": "absent", "voice": "absent", "signature": "absent", "never": "absent", "colours": "deduced"})
        self.assertTrue(all(c["state"] == "deduced" and c["source"] and c["role"] for c in a["colours"]))  # read on the site: to confirm
        img = self.call("GET", a["evidence"][0]["preview"], raw=True)  # the picture is served, from the brand's folder
        self.assertTrue(img.startswith(b"\x89PNG"))
        self.assertTrue(a["evidence"][0]["preview"].startswith(f"/files/_marques/{bid}/brand/collect/web-marrowbay.example/"))

    def drop(self, bid, data, ctype="image/png", name="logo.png", code=200):
        req = urllib.request.Request(self.base + f"/api/brands/{bid}/logo", method="POST", data=data, headers={"Content-Type": ctype, "X-Filename": name})
        try:
            with urllib.request.urlopen(req) as r:
                got, out = r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            got, out = err.code, json.loads(err.read())
            err.close()
        self.assertEqual(got, code, out)
        return out

    def test_a_logo_dropped_goes_through_the_dossier_and_makes_a_brand_without_site_ready(self):
        bid = self.mkbrand(name="Sans Site", site=None)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "une cave", "who": "les voisins"}})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "to_brief")  # no logo, no site to find one
        self.drop(bid, b"nope", "image/png", code=400)
        data = png(40, 20, (30, 60, 50))
        b = self.drop(bid, data, name="mon logo.png")
        logo = b["assets"]["logo"]
        self.assertEqual((logo["state"], logo["source"], b["stage"], [t["title"] for t in b["waiting"]]), ("confirmed", "choisi par toi", "to_brief", ["Choisir les couleurs de la marque"]))
        self.assertEqual(self.call("GET", f"/api/brands/{bid}/brief")["needs"], ["colours"])
        self.assertEqual([x["note"] for x in b["assets"]["logos"]], ["Logo déposé, png"])
        self.assertEqual(self.call("GET", logo["preview"], raw=True), data)  # the picture is served from the dossier of the brand
        f = next((self.bdir(bid) / "assets").glob("logo-*.png"))
        self.assertEqual(f.read_bytes(), data)
        self.assertEqual(len(self.brand_calls(bid, "add")), 1)  # the dossier took it as a source, through brandkit
        self.assertEqual(self.doc(bid)["logo"]["items"][0]["file"]["value"], f"assets/{f.name}")
        m = json.loads((self.home / "marques" / bid / "marque.json").read_text())
        self.assertEqual(m["logo"], logo["id"])
        self.assertFalse(list((self.home / "marques" / bid / "logs").glob("logo-*.json")))  # no scrap left behind
        again = self.drop(bid, data)  # the same file twice: one candidate
        self.assertEqual(len(again["assets"]["logos"]), 1)
        self.drop("nope", data, code=404)

    def test_colours_chosen_with_the_pickers_become_the_colours_of_the_brand(self):
        bid = self.mkbrand(name="Sélecteur", site=None)
        self.drop(bid, png(40, 20))
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "une cave"}})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "to_brief")
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"colours": [{"hex": "#112233", "role": "background"}]}}, code=400)  # no text colour
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"colours": [{"hex": "#F4EFE6", "role": "background"}, {"hex": "#1E2A24", "role": "text"}]}})
        self.assertEqual((r["stage"], r["needs"], r["palette"]), ("ready", [], {"background": "#f4efe6", "text": "#1e2a24", "accent": None}))
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual([(c["hex"], c["role"], c["state"], c["source"]) for c in b["assets"]["colours"]],
                         [("#f4efe6", "background", "confirmed", "choisie par toi"), ("#1e2a24", "text", "confirmed", "choisie par toi")])
        self.assertEqual(b["identity"]["colours"], {"value": "#f4efe6, #1e2a24", "state": "confirmed", "source": "choisie par toi"})
        self.assertFalse(list((self.home / "marques" / bid / "logs").glob("colours-*.json")))  # no scrap left behind
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"colours": [{"hex": "#ffffff", "role": "background"}, {"hex": "#000000", "role": "text"}, {"hex": "#c8553d", "role": "accent"}]}})
        self.assertEqual(r["palette"], {"background": "#ffffff", "text": "#000000", "accent": "#c8553d"})  # a second choice replaces the first
        self.assertEqual(len(self.call("GET", f"/api/brands/{bid}")["assets"]["colours"]), 3)
        self.assertEqual(len([f for f in (self.bdir(bid) / "sources").glob("*.json") if "colours" in f.name]), 1)
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Premier"})["id"]  # the piece is written from these colours
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o", "audience": "a", "message": "m"}})
        brand_md = (self.pdir(pid) / "piece" / "brand.md").read_text()
        self.assertIn("- background: #ffffff", brand_md)
        self.assertIn("- text: #000000", brand_md)

    def test_a_logo_dropped_next_to_the_logos_of_the_site(self):
        bid = self.mkbrand(name="Deux Logos")
        site_logo = self.call("GET", f"/api/brands/{bid}")["assets"]["logos"][0]
        b = self.drop(bid, png(), name="a.png")
        self.assertEqual((b["stage"], len(b["assets"]["logos"]), b["assets"]["logo"]["id"] != site_logo["id"]), ("to_sort", 2, True))
        self.assertIn(site_logo["id"], [x["id"] for x in b["assets"]["logos"]])
        a = b["assets"]
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in a["evidence"]][:1], "logo": site_logo["id"]})  # the person can still prefer the site's
        self.assertEqual((r["assets"]["logo"]["id"], r["stage"]), (site_logo["id"], "to_brief"))
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in a["evidence"]][:1], "logo": b["assets"]["logo"]["id"]})
        self.assertEqual((r["assets"]["logo"]["id"], r["assets"]["logo"]["state"]), (b["assets"]["logo"]["id"], "confirmed"))

    def test_sorting_keeps_the_choices(self):
        bid = self.mkbrand(name="Tri")
        a = self.call("GET", f"/api/brands/{bid}")["assets"]
        keep = [a["evidence"][0]["id"]]
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": keep, "logo": a["logos"][0]["id"]})
        self.assertEqual((r["kept"], r["discarded"], r["stage"]), (1, 1, "to_brief"))
        self.assertEqual((r["assets"]["logo"]["id"], r["assets"]["logo"]["state"]), (a["logos"][0]["id"], "confirmed"))  # a logo the person chose is confirmed
        self.assertEqual([v["id"] for v in r["assets"]["visuals"]], keep)
        self.assertEqual([e["kept"] for e in r["assets"]["evidence"]], [True, False])
        self.assertTrue(r["assets"]["logo"]["preview"].startswith(f"/files/_marques/{bid}/brand/"))
        self.assertTrue(self.call("GET", r["assets"]["logo"]["preview"], raw=True).startswith(b"<svg"))
        self.assertTrue(r["assets"]["colours"] and all(re.fullmatch(r"#[0-9a-f]{6}", c["hex"]) and c["state"] in ("deduced", "confirmed") for c in r["assets"]["colours"]))
        keepcall = self.brand_calls(bid, "keep")[-1]
        self.assertIn(keep[0], keepcall)
        self.assertEqual(keepcall[keepcall.index("--logo") + 1], a["logos"][0]["id"])
        self.assertFalse(list(self.home.glob(f"marques/{bid}/projets/*/piece/brand.md")))  # the brand of a piece is written with the project's brief
        m = json.loads((self.home / "marques" / bid / "marque.json").read_text())
        self.assertEqual((m["kept"], m["kept_ids"], m["logo"]), (True, keep, a["logos"][0]["id"]))
        self.assertEqual([t["kind"] for t in r["waiting"]], ["brand-brief"])

    def test_sorting_refuses_what_it_does_not_know(self):
        bid = self.mkbrand(name="Refus", site=None)
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [], "logo": None}, code=409)  # nothing read yet
        bid = self.mkbrand(name="Refus lu")
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": ["ev-nope"], "logo": None}, code=400)
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [], "logo": "ev-nope"}, code=400)
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "to_sort")

    def test_no_logo_chosen_keeps_the_brand_in_the_sort(self):
        bid = self.mkbrand(name="Sans Logo")
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": [], "logo": None})
        self.assertEqual((r["stage"], r["assets"]["logo"], r["waiting"][0]["title"]), ("to_sort", None, "Choisir le logo de la marque"))
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "x"}})
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "to_sort")  # a logo is part of a ready brand
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [], "logo": self.call("GET", f"/api/brands/{bid}")["assets"]["logos"][0]["id"]})
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "ready")

    def test_the_one_rule_of_step_one(self):
        bid = self.mkbrand(name="Règle")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Premier tour"})["id"]
        stages = []
        def look():
            p = self.call("GET", f"/api/projects/{pid}")
            stages.append((p["brand_stage"], p["steps"][0]["status"], p["steps"][1]["status"]))
            if p["brand_stage"] != "ready":
                self.assertEqual(p["waiting"], [])  # the brand's tasks are the brand's: the list shows them, not the project
        look()
        self.sort(bid)
        look()
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un kombucha"}})
        look()
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o", "audience": "a", "message": "m"}}, code=409)
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        look()
        self.assertEqual(stages, [("to_sort", "waiting", "todo"), ("to_brief", "waiting", "todo"), ("to_confirm", "waiting", "todo"), ("ready", "done", "waiting")])
        self.assertEqual(self.asks(pid), ["brief"])

    def test_a_project_follows_the_reading_of_its_brand(self):
        b = self.call("POST", "/api/brands", {"name": "Suivi", "site": "marrowbay.example"})
        self.fake.hold = None
        pid = self.call("POST", f"/api/brands/{b['id']}/projects", {"name": "Dès maintenant"})["id"]
        p = self.call("GET", f"/api/projects/{pid}")
        if p["steps"][0]["status"] == "running":  # the reading may already be over
            self.assertEqual((p["steps"][0]["hand"], p["steps"][0]["job"]), ("studio", b["jobs"][0]["id"]))
            self.assertEqual(p["jobs"], [])  # the brand's job is the brand's
        self.wait(b["jobs"][0])

    def test_reading_again_keeps_what_was_said_and_asks_for_the_new_visuals(self):
        bid = self.ready_brand(name="Relecture")
        before = self.doc(bid)["identity"]["one_liner"]
        self.assertEqual(before["value"], "un kombucha de port")
        self.fake.extra_screen = True
        self.wait(self.call("POST", f"/api/brands/{bid}/discover"))
        self.assertEqual(self.doc(bid)["identity"]["one_liner"]["value"], "un kombucha de port")  # the dossier is not wiped
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual(b["identity"]["what"]["state"], "confirmed")
        self.assertEqual((b["stage"], b["waiting"][0]["title"]), ("to_sort", "Trier 1 visuels de la marque"))  # the one that was not there before
        self.assertEqual([e["kept"] for e in b["assets"]["evidence"]], [True, True, None])  # the choices already made stay
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in b["assets"]["evidence"]], "logo": b["assets"]["logo"]["id"]})
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "ready")

    def test_a_failed_reading_becomes_a_task_to_run_again(self):
        self.fake.collect_fails = True
        b = self.call("POST", "/api/brands", {"name": "Échec", "site": "marrowbay.example"})
        bid = b["id"]
        j = self.wait(b["jobs"][0], "failed")
        self.assertIn("no Chrome found", j["message"])
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual([t["kind"] for t in b["waiting"]], ["job-failed", "brand-brief"])
        self.assertIn("no Chrome found", b["waiting"][0]["question"])
        task = next(t for t in self.call("GET", "/api/tasks")["tasks"] if t["brand"] == bid and t["kind"] == "job-failed")
        self.assertEqual((task["id"], task["scope"], task["since"] > 0), (f"@{bid}:job-failed", "brand", True))
        self.assertTrue((self.home / "marques" / bid / "logs" / f"{j['id']}.log").read_text().count("no Chrome found"))  # the log keeps the output
        self.fake.collect_fails = False
        self.wait(self.call("POST", f"/api/brands/{bid}/discover"))
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual([t["kind"] for t in b["waiting"]], ["brand-sort"])  # running it again made the task go

    def test_answer_and_create_from_the_project_route_need_no_search(self):
        bid = self.mkbrand(name="Réponse", site=None)
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "x"})["id"]
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer"}, code=400)
        r = self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer", "answers": "Un kombucha de port."})
        self.assertEqual(r["status"], "done")
        b = self.call("GET", f"/api/projects/{pid}/brand")
        self.assertEqual((b["evidence"], b["answers"]), ([], "Un kombucha de port."))
        self.assertTrue(self.brand_calls(bid, "answer")[-1][-2:] == ["identity.one_liner", "Un kombucha de port."])  # given to the dossier too
        r = self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": [], "logo": None})
        self.assertEqual((r["kept"], r["colours"]), (0, []))
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "create"})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["identity"]["what"]["state"], "confirmed")


class BrandBrief(Base):
    def test_what_is_typed_is_confirmed_and_goes_to_the_dossier(self):
        bid = self.mkbrand(name="Brief")
        self.sort(bid)
        g = self.call("GET", f"/api/brands/{bid}/brief")
        self.assertEqual((g["done"], g["stage"], g["keys"]), (False, "to_brief", ["what", "who", "voice", "signature", "never", "colours"]))
        self.assertEqual(g["fields"]["what"], {"value": "", "state": "absent", "source": ""})
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"who": "les voisins"}}, code=400)  # what the brand is, at least
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"nope": "x"}}, code=400)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": ["what"]}, code=400)
        self.assertFalse(self.call("GET", f"/api/brands/{bid}/brief")["done"])
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un kombucha\nde port", "who": "les voisins", "voice": "franc; chaleureux\ndrôle",
                                                                  "signature": "À la vôtre.", "never": "premium, artisanal", "colours": "du vert et du cuivre"}})
        f = r["fields"]
        self.assertEqual((r["done"], r["stage"]), (True, "to_confirm"))  # the measured colours still wait for a look
        self.assertEqual(f["what"], {"value": "un kombucha de port", "state": "confirmed", "source": "tapé"})
        self.assertEqual((f["voice"]["value"], f["never"]["value"], f["signature"]["value"]), ("franc, chaleureux, drôle", "premium, artisanal", "À la vôtre."))
        self.assertEqual(f["colours"]["state"], "deduced")
        d = self.doc(bid)
        self.assertEqual((d["identity"]["one_liner"]["value"], d["audience"]["who"]["value"], d["promise"]["signature_line"]["value"]),
                         ("un kombucha de port", "les voisins", "À la vôtre."))
        self.assertEqual((d["voice"]["traits"]["value"], d["voice"]["banned_words"]["value"]), (["franc", "chaleureux", "drôle"], ["premium", "artisanal"]))
        self.assertEqual({d["identity"]["one_liner"]["status"], d["voice"]["traits"]["status"]}, {"confirmed"})
        ans = [c for c in self.brand_calls(bid, "answer") if c[4] == "voice.traits"][-1]
        self.assertEqual(ans[5:], ['["franc", "chaleureux", "drôle"]', "--json"])  # a list goes to the dossier as a list
        m = json.loads((self.home / "marques" / bid / "marque.json").read_text())
        self.assertEqual((m["brief_done"], m["colours_words"]), (True, "du vert et du cuivre"))  # no field of the dossier: kept with the brand
        self.assertEqual(f["colours"]["value"], "du vert et du cuivre")

    def test_a_deduced_value_read_and_kept_is_confirmed_not_retyped(self):
        bid = self.mkbrand(name="Déduit")
        self.sort(bid)
        self.deduce(bid, "voice.traits", ["franc", "chaud", "drôle"])
        f = self.call("GET", f"/api/brands/{bid}/brief")["fields"]
        self.assertEqual(f["voice"], {"value": "franc, chaud, drôle", "state": "deduced", "source": "déduit du site"})
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un truc", "voice": "franc, chaud, drôle", "colours": f["colours"]["value"]}})
        self.assertEqual(r["fields"]["voice"], {"value": "franc, chaud, drôle", "state": "confirmed", "source": "déduit du site"})  # confirmed, its source stays
        self.assertEqual(r["fields"]["colours"]["state"], "confirmed")
        self.assertEqual([c[4] for c in self.brand_calls(bid, "confirm")][-2:], ["voice.traits", "colours"])
        self.assertFalse([c for c in self.brand_calls(bid, "answer") if c[4] == "voice.traits"])
        self.assertEqual(r["stage"], "ready")
        self.assertEqual(self.doc(bid)["voice"]["traits"]["source"]["type"], "inferred")

    def test_what_is_typed_over_what_is_deduced(self):
        bid = self.mkbrand(name="Prime")
        self.sort(bid)
        self.deduce(bid, "voice.traits", ["franc", "chaud", "drôle"])
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un truc", "voice": "sec, net, bref"}})
        self.assertEqual(r["fields"]["voice"], {"value": "sec, net, bref", "state": "confirmed", "source": "tapé"})

    def test_confirming_gives_one_state_per_value(self):
        bid = self.mkbrand(name="Confirmation")
        self.sort(bid)
        self.deduce(bid, "voice.traits", ["franc", "chaud", "drôle"])
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un truc", "colours": "du vert"}})
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual((b["stage"], b["waiting"][0]["kind"]), ("to_confirm", "brand-confirm"))
        self.assertIn("sa voix", b["waiting"][0]["question"])
        self.assertIn("ses couleurs", b["waiting"][0]["question"])  # said in words, the measured colours still wait: the state is the state of the swatches
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": ["voice"]})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["identity"]["voice"]["state"], "confirmed")
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": ["signature"]}, code=400)  # nothing there to confirm
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": ["nope"]}, code=400)
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": "voice"}, code=400)
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "to_confirm")
        r = self.call("POST", f"/api/brands/{bid}/confirm", {})  # all that is left
        self.assertEqual((r["stage"], r["waiting"], {c["state"] for c in r["assets"]["colours"]}), ("ready", [], {"confirmed"}))
        self.assertEqual(self.call("POST", f"/api/brands/{bid}/confirm", {})["stage"], "ready")  # and again: nothing changes

    def test_the_task_to_confirm_and_the_gesture_are_the_same_call(self):
        bid = self.mkbrand(name="Un seul appel")
        self.sort(bid)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un truc"}})
        t = next(x for x in self.call("GET", "/api/tasks")["tasks"] if x["brand"] == bid)
        self.assertEqual((t["kind"], t["scope"]), ("brand-confirm", "brand"))
        self.call("POST", f"/api/brands/{t['brand']}/confirm", {})  # the route the task points to
        self.assertEqual([x for x in self.call("GET", "/api/tasks")["tasks"] if x["brand"] == bid], [])

    def test_a_missing_colour_is_said_not_made_up(self):
        bid = self.mkbrand(name="Sans Couleur", site=None)
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "x"})["id"]
        (self.pdir(pid) / "piece" / "brand.md").write_text("- name: Sans Couleur\n", encoding="utf-8")
        brand = json.loads((self.home / "marques" / bid / "marque.json").read_text())
        self.backend._ensure_dossier(brand, None)
        with self.assertRaises(backend_studio.ToolError) as cm:
            self.backend._complete_brand_md(pid, brand, None)
        self.assertIn("aucune couleur", str(cm.exception))
        self.assertNotIn("#ffffff", (self.pdir(pid) / "piece" / "brand.md").read_text())


def legacy_project(home, pid, brand, site="https://old.example/", kept=True, when=None, **extra):
    """A project in the old format: `<home>/<pid>/` with its own brand dossier (really made by brandkit: the site read, the visuals kept, a logo
    chosen) and what the person chose of it in `project.json`."""
    d = Path(home) / pid
    (d / "piece").mkdir(parents=True)
    (d / "logs").mkdir()
    kit = [sys.executable, str(backend_studio.BRANDKIT)]
    env = Fake().tool_env()
    Fake().node(["node", "collect", "https://old.example/", str(d / "brand" / "collect" / "web-old.example")])
    for args in (["init", str(d / "brand"), "--name", brand, "--lang", "fr"], ["infer-site", str(d / "brand"), str(d / "brand" / "collect" / "web-old.example")]):
        res = run_command(kit + args, env=env, timeout=60)
        assert res.code == 0, res.err
    ev = json.loads((d / "brand" / "evidence.json").read_text())
    shots = [e["id"] for e in ev if e["kind"] == "file" and "screen" in e["where"]]
    logo = next(e["id"] for e in ev if e["kind"] == "file" and "logo" in e["where"])
    pages = [e["id"] for e in ev if e["kind"] == "page"]
    res = run_command(kit + ["keep", str(d / "brand"), *shots, *pages, "--logo", logo], env=env, timeout=60)
    assert res.code == 0, res.err
    (d / "piece" / "brief.md").write_text("objective: o\n")
    p = {"id": pid, "name": pid.title(), "brand_name": brand, "site": site, "origin": None, "created": when or time.time(), "since": {"brand": 1.0},
         "learn": {"learned": True, "mode": "answer", "answers": "Un truc ancien."},
         "brand": {"kept": kept, "kept_ids": shots, "discarded_ids": [], "logo": logo, "colours": []},
         "brief": {"confirmed": True, "fields": {"objective": "o", "audience": "a", "message": "m", "format": "post-4x5"}},
         "mandates": {"confirmed": False, "proposed": False, "common": "c", "items": []}, "pieces": [], "jobs": [], **extra}
    (d / "project.json").write_text(json.dumps(p))
    return d


class Migration(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="ixs-old-"))
        self.fake = Fake()

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def open(self):
        return StudioBackend(self.home, runner=self.fake)

    def test_a_lone_project_goes_to_its_brand(self):
        d = legacy_project(self.home, "campagne-ete", "Marrowbay Ferments")
        (d / "piece" / "brand.md").write_text("- name: Marrowbay Ferments\n")
        b = self.open()
        m = self.home / "marques" / "marrowbay-ferments"
        self.assertFalse(d.exists())  # moved, not copied
        self.assertTrue((m / "projets" / "campagne-ete" / "piece" / "brief.md").is_file() and (m / "projets" / "campagne-ete" / "piece" / "brand.md").is_file())
        self.assertTrue((m / "brand" / "brand.json").is_file())  # its dossier became the brand's
        self.assertFalse((m / "projets" / "campagne-ete" / "brand").exists())
        mq = json.loads((m / "marque.json").read_text())
        self.assertEqual((mq["id"], mq["name"], mq["site"], mq["discovered"], mq["kept"], mq["migrated"]), ("marrowbay-ferments", "Marrowbay Ferments", "https://old.example/", True, True, False))
        self.assertEqual(mq["answers"], "Un truc ancien.")
        p = json.loads((m / "projets" / "campagne-ete" / "project.json").read_text())
        self.assertEqual((p["brand"], p["type"], p["legacy"]["brand_name"], p["legacy"]["brand"]["kept"]), ("marrowbay-ferments", "campagne", "Marrowbay Ferments", True))
        self.assertNotIn("learn", p)
        v = b.project("campagne-ete")  # the project's own state is intact
        self.assertEqual((v["brand"], v["brand_name"], v["type"], v["steps"][1]["key"]), ("marrowbay-ferments", "Marrowbay Ferments", "campagne", "brief"))
        self.assertTrue(b.get_brief("campagne-ete")["confirmed"])
        self.assertEqual([x["id"] for x in b.list_brands()], ["marrowbay-ferments"])
        self.assertEqual(b.brand_view("marrowbay-ferments")["projects"][0]["id"], "campagne-ete")

    def test_projects_of_the_same_brand_share_the_most_recent_dossier_and_nothing_is_deleted(self):
        now = time.time()
        old = legacy_project(self.home, "premier", "Marrowbay Ferments", when=now - 300)
        new = legacy_project(self.home, "second", "marrowbay  ferments", site="", when=now - 200)
        other = legacy_project(self.home, "troisieme", "Autre Marque", when=now - 100)
        (old / "brand" / "mark-old.txt").write_text("old dossier")
        (new / "brand" / "mark-new.txt").write_text("new dossier")
        os.utime(old / "project.json", (now - 300, now - 300))
        os.utime(new / "brand" / "brand.json", (now, now))  # the dossier of "second" was modified last
        b = self.open()
        m = self.home / "marques" / "marrowbay-ferments"
        self.assertEqual((m / "brand" / "mark-new.txt").read_text(), "new dossier")  # the most recent one is the brand's
        self.assertFalse((m / "brand" / "mark-old.txt").exists())
        self.assertEqual((m / "projets" / "premier" / "brand" / "mark-old.txt").read_text(), "old dossier")  # the other stays in its project, untouched
        self.assertTrue((m / "projets" / "second").is_dir() and not (m / "projets" / "second" / "brand").exists())
        mq = json.loads((m / "marque.json").read_text())
        self.assertEqual((mq["migrated"], mq["site"], sorted(mq["from"])), (True, "https://old.example/", ["premier", "second"]))  # the first non-empty site
        v = b.brand_view("marrowbay-ferments")
        self.assertEqual(v["stage"], "to_confirm")  # nobody has looked at what several projects made of it
        self.assertEqual([(t["kind"], t["title"]) for t in v["waiting"]], [("brand-confirm", "Confirmer la marque")])
        self.assertIn("plusieurs projets", v["waiting"][0]["question"])
        self.assertEqual(sorted(x["id"] for x in v["projects"]), ["premier", "second"])
        # the other brand has one project and is not marked
        self.assertFalse(json.loads((self.home / "marques" / "autre-marque" / "marque.json").read_text())["migrated"])
        self.assertEqual(b.project("troisieme")["brand"], "autre-marque")
        self.assertTrue(other.name not in [x.name for x in self.home.iterdir() if x.is_dir() and x.name != "marques"])

    def test_the_person_confirms_the_migrated_brand_and_the_flag_goes(self):
        now = time.time()
        legacy_project(self.home, "a", "Duo", when=now - 10)
        legacy_project(self.home, "b", "Duo", when=now)
        b = self.open()
        # a logo the person chose and a text typed: the dossier of the old format already knew them
        run_command([sys.executable, str(backend_studio.BRANDKIT), "answer", str(self.home / "marques" / "duo" / "brand"), "identity.one_liner", "un duo"], timeout=60)
        self.assertEqual(b.brand_view("duo")["stage"], "to_confirm")
        r = b.confirm("duo", None)  # nothing deduced is left, only the look: the call clears the flag
        self.assertFalse(json.loads((self.home / "marques" / "duo" / "marque.json").read_text())["migrated"])
        self.assertNotEqual(r["stage"], "to_confirm")

    def test_a_restart_after_the_migration_changes_nothing(self):
        legacy_project(self.home, "a", "Stable")
        self.open()
        before = sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*") if p.is_file() and p.suffix != ".log")
        again = self.open()
        self.assertEqual(before, sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*") if p.is_file() and p.suffix != ".log"))
        self.assertEqual([x["id"] for x in again.list_brands()], ["stable"])

    def test_learn_jobs_of_the_old_project_go_to_the_brand(self):
        job = {"id": "job-old", "kind": "learn", "piece": None, "status": "done", "start": 1.0, "end": 2.0, "message": "terminé", "error": None, "result": None}
        legacy_project(self.home, "a", "Avec Job", jobs=[job, {**job, "id": "job-img", "kind": "image", "piece": "v1"}])
        b = self.open()
        self.assertEqual(b.job("job-old")["status"], "done")
        self.assertEqual([j["id"] for j in json.loads((self.home / "marques" / "avec-job" / "marque.json").read_text())["jobs"]], ["job-old"])
        self.assertEqual([j["id"] for j in json.loads((self.home / "marques" / "avec-job" / "projets" / "a" / "project.json").read_text())["jobs"]], ["job-img"])

    def test_a_project_called_marques_does_not_stand_in_the_way(self):
        legacy_project(self.home, "marques", "Cas Limite")
        b = self.open()
        self.assertEqual(b.project("marques-projet")["brand"], "cas-limite")
        self.assertTrue((self.home / "marques" / "cas-limite" / "projets" / "marques-projet" / "piece" / "brief.md").is_file())

    def test_a_home_already_in_the_new_format_is_left_alone(self):
        b = self.open()
        bid = b.create_brand("Neuf", None)["id"]
        pid = b.create_project_in(bid, "p")["id"]
        again = self.open()
        self.assertEqual((again.project(pid)["brand"], [x["id"] for x in again.list_brands()]), (bid, [bid]))
        self.assertEqual(sorted(x.name for x in self.home.iterdir()), ["marques"])


class Tasks(Base):
    def test_tasks_across_brands_and_projects_oldest_first_with_running_jobs(self):
        bid = self.mkbrand(name="Tâches", site=None)
        a, b = self.started(name="tâches A", brand=bid), self.started(name="tâches B", brand=bid)
        t = self.call("GET", "/api/tasks")
        mine = [x for x in t["tasks"] if x["brand"] == bid]
        self.assertEqual([(x["scope"], x["kind"], x["id"]) for x in mine], [("brand", "brand-brief", f"@{bid}:brand-brief")])  # the brand's task, once, not one per project
        self.assertEqual((mine[0]["brand_name"], mine[0]["project"]), ("Tâches", None))
        self.assertTrue(all(x["title"] and x["since"] for x in mine))
        self.assertIn({"id": a, "name": "tâches A", "brand": bid, "brand_name": "Tâches", "can_learn": False, "pieces": 0, "waiting": 0}, t["projects"])
        self.assertEqual([x for x in t["brands"] if x["id"] == bid], [{"id": bid, "name": "Tâches", "site": "", "stage": "new", "waiting": 1,
                                                                        "projects": [{"id": a, "name": "tâches A", "type": "campagne", "rank": 1, "step_label": "La marque", "done": False, "waiting": 0},
                                                                                     {"id": b, "name": "tâches B", "type": "campagne", "rank": 1, "step_label": "La marque", "done": False, "waiting": 0}]}])
        self.assertEqual(t["tasks"], sorted(t["tasks"], key=lambda x: (x["since"] is None, x["since"] or 0)))
        proj = self.started(name="de la marque prête")
        mine = [x for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == proj]
        self.assertEqual([(x["scope"], x["kind"], x["brand"]) for x in mine], [("project", "brief", self.shared_brand())])  # a project's own task
        self.fake.hold = threading.Event()
        self.fake.hold.set()
        b3 = self.call("POST", "/api/brands", {"name": "Job", "site": "marrowbay.example"})
        running = [j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == b3["jobs"][0]["id"]]
        for j in running:
            self.assertEqual((j["project"], j["brand"], j["kind"]), (None, b3["id"], "learn"))
            self.assertTrue(0 <= j["progress"] <= 0.95 and j["eta"] >= 0)
        self.wait(b3["jobs"][0])
        self.assertEqual([j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == b3["jobs"][0]["id"]], [])

    def test_progress_is_an_estimate_capped_below_the_end(self):
        j = {"id": "job-x", "kind": "diverge", "status": "running", "start": time.time() - 10_000, "message": "m", "piece": None}
        pub = StudioBackend._job_public(self.backend, j)
        self.assertEqual(pub["progress"], 0.95)
        self.assertGreaterEqual(pub["eta"], 3)
        j["start"] = time.time() - 15
        self.assertAlmostEqual(StudioBackend._job_public(self.backend, j)["progress"], 0.1, delta=0.02)
        self.assertEqual(StudioBackend._job_public(self.backend, {**j, "status": "done"})["progress"], 1.0)


class Restart(Base):
    def test_a_new_server_finds_everything_on_the_disk(self):
        pid, _ = self.picked(("v1",), formats="story")
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        before = self.call("GET", f"/api/projects/{pid}")
        again = StudioBackend(self.home, runner=self.fake)
        after = again.project(pid)
        for k in ("id", "name", "brand", "brand_name", "steps", "pieces", "waiting", "jobs"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual([t["id"] for t in again.tasks()["tasks"] if t["project"] == pid], [f"{pid}:piece:v1-story"])
        self.assertEqual(again.get_mandates(pid)["items"][0]["id"], "v1")
        self.assertEqual(again.variants(pid)[0]["headline"], "Titre de v1")
        bid = before["brand"]
        self.assertEqual(again.brand_view(bid)["stage"], "ready")
        self.assertEqual(again.brand(pid)["kept"], True)
        job_id = json.loads((self.pdir(pid) / "project.json").read_text())["jobs"][0]["id"]
        self.assertEqual(again.job(job_id)["status"], "done")
        self.assertEqual(again.job(json.loads((self.home / "marques" / bid / "marque.json").read_text())["jobs"][0]["id"])["status"], "done")

    def test_a_job_that_was_running_when_the_server_stopped_is_failed(self):
        bid = self.mkbrand(name="Interrompue", site=None)
        pid = self.started(brand=bid)
        d = self.pdir(pid) / "project.json"
        p = json.loads(d.read_text())
        p["jobs"].append({"id": "job-dead", "kind": "mandates", "piece": None, "status": "running", "start": time.time() - 30, "message": "", "error": None, "result": None})
        d.write_text(json.dumps(p))
        m = self.home / "marques" / bid / "marque.json"
        b = json.loads(m.read_text())
        b["jobs"].append({"id": "job-dead-brand", "kind": "learn", "piece": None, "status": "running", "start": time.time() - 30, "message": "", "error": None, "result": None})
        b["site"] = "https://marrowbay.example/"
        m.write_text(json.dumps(b))
        again = StudioBackend(self.home, runner=self.fake)
        for jid in ("job-dead", "job-dead-brand"):
            j = again.job(jid)
            self.assertEqual(j["status"], "failed")
            self.assertIn("redémarré", j["message"])
        self.assertEqual([t["kind"] for t in again.brand_view(bid)["waiting"]], ["job-failed", "brand-brief"])  # a task to run the brand's reading again


class Files(Base):
    def test_the_files_route_never_leaves_the_folder_of_the_brand_or_the_project(self):
        bid = self.mkbrand(name="Fichiers")
        other = self.mkbrand(name="Autre fichiers")
        pid = self.started(brand=bid)
        ok = f"/files/_marques/{bid}/brand/collect/web-marrowbay.example/screen-01.png"
        self.assertTrue(self.call("GET", ok, raw=True).startswith(b"\x89PNG"))
        self.assertTrue(self.call("GET", f"/files/{pid}/brand/collect/web-marrowbay.example/screen-01.png", raw=True).startswith(b"\x89PNG"))  # the brand's, seen from its project
        (self.pdir(pid) / "piece" / "x.txt").write_text("piece")
        self.assertEqual(self.call("GET", f"/files/{pid}/piece/x.txt", raw=True), b"piece")
        (self.home / "secret.txt").write_text("secret")
        (self.pdir(pid) / "piece" / "link.txt").symlink_to(self.home / "secret.txt")
        (self.home / "marques" / bid / "brand" / "link.txt").symlink_to(self.home / "secret.txt")
        for bad in (f"/files/{pid}/project.json", f"/files/{pid}/logs/commands.log", f"/files/{pid}/brand/../project.json",
                    f"/files/{pid}/brand/%2e%2e/marque.json", f"/files/{pid}/brand/..%2f..%2fsecret.txt", f"/files/{pid}/piece/link.txt",
                    f"/files/{pid}/%2e%2e/secret.txt", f"/files/{pid}/piece/..%2f..%2f..%2fmarque.json", f"/files/{pid}/brand", f"/files/{pid}/piece",
                    f"/files/nope/brand/x.png", f"/files/../secret.txt", f"/files//etc/passwd", f"/files/{pid}//etc/passwd", f"/files/{pid}/brand/%00.png",
                    f"/files/_marques/{bid}/marque.json", f"/files/_marques/{bid}/logs/commands.log", f"/files/_marques/{bid}/projets/{pid}/project.json",
                    f"/files/_marques/{bid}/brand/link.txt", f"/files/_marques/{bid}/brand/../marque.json", f"/files/_marques/{bid}/brand/..%2fmarque.json",
                    f"/files/_marques/{bid}/brand/%2e%2e/%2e%2e/secret.txt", f"/files/_marques/{bid}/brand", f"/files/_marques/{bid}/brand/%00.png",
                    f"/files/_marques/nope/brand/x.png", f"/files/_marques/../secret.txt", f"/files/_marques/", f"/files/_marques/{bid}",
                    f"/files/_marques/{bid}/piece/x.txt", f"/files/_marques//etc/passwd",
                    f"/files/_marques/{bid}/brand/collect/web-marrowbay.example/..%2f..%2f..%2f..%2f..%2fsecret.txt"):
            self.call("GET", bad, code=404, raw=True)
        # a brand's folder is not another brand's
        self.call("GET", f"/files/_marques/{other}/brand/collect/web-marrowbay.example/screen-01.png", raw=True)
        self.call("GET", f"/files/_marques/{other}/../{bid}/brand/collect/web-marrowbay.example/screen-01.png", code=404, raw=True)

    def test_the_files_route_has_the_authentication_of_the_api(self):
        bid = self.mkbrand(name="Authentifiée")
        path = f"/files/_marques/{bid}/brand/collect/web-marrowbay.example/screen-01.png"
        os.environ.update(STUDIO_AUTH="token", STUDIO_TOKEN="s3cret")
        try:
            self.call("GET", path, code=401, raw=True)
            self.call("GET", path, code=401, raw=True, headers={"Authorization": "Bearer wrong"})
            self.assertTrue(self.call("GET", path, raw=True, headers={"Authorization": "Bearer s3cret"}).startswith(b"\x89PNG"))
        finally:
            os.environ.pop("STUDIO_AUTH")
            os.environ.pop("STUDIO_TOKEN")

    def test_a_picture_cannot_run_a_script_when_opened_on_its_own(self):
        bid = self.mkbrand(name="Sandbox")
        req = urllib.request.Request(self.base + f"/files/_marques/{bid}/brand/collect/web-marrowbay.example/logo-svg-1.svg")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["Content-Security-Policy"], "sandbox")
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")


class Brief(Base):
    def test_the_brief_is_written_for_the_studio_and_validated_by_it(self):
        pid = self.started()
        got = self.call("GET", f"/api/projects/{pid}/brief")
        self.assertEqual((got["chosen"], got["left_out"], got["confirmed"]), (["post-4x5"], [], False))
        self.assertIn("post-1x1", got["formats"])
        f = got["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": ""}}, code=400)
        err = self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o", "audience": "a", "message": "m", "layout": "diagonal"}}, code=400)
        self.assertIn("layout must be one of", err["error"])  # the studio's own message
        self.assertFalse(self.call("GET", f"/api/projects/{pid}/brief")["confirmed"])
        self.assertFalse((self.pdir(pid) / "piece" / "brief.md").exists())
        r = self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o\nsur deux lignes", "audience": "a", "message": "m", "format": "post-4x5, story, pub télé 30s"}})
        self.assertEqual((r["formats"], r["left_out"]), (["post-4x5", "story"], ["pub télé 30s"]))
        txt = (self.pdir(pid) / "piece" / "brief.md").read_text()
        self.assertIn("objective: o sur deux lignes", txt)
        self.assertIn("format: post-4x5, story\n", txt)  # the studio only gets what it can make
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/brief")["fields"]["format"], "post-4x5, story, pub télé 30s")  # the person's line is kept whole
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o"}}, code=400)
        self.settle_mandates(pid)

    def test_no_brief_while_the_brand_is_not_ready(self):
        bid = self.read()
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Trop tôt"})["id"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o", "audience": "a", "message": "m"}}, code=409)
        self.assertFalse((self.pdir(pid) / "piece" / "brief.md").exists())
        self.assertFalse((self.pdir(pid) / "piece" / "brand.md").exists())  # nothing is written from a brand nobody has looked at

    def test_the_brand_of_the_piece_is_written_from_the_dossier_when_the_brief_is_saved(self):
        pid = self.started()
        self.assertFalse((self.pdir(pid) / "piece" / "brand.md").exists())
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o", "audience": "a", "message": "m"}})
        bid = self.call("GET", f"/api/projects/{pid}")["brand"]
        cmd = next(c["argv"] for c in reversed(self.fake.calls) if len(c["argv"]) > 3 and c["argv"][2] == "brand" and "--from-dossier" in c["argv"] and c["argv"][3] == str(self.pdir(pid) / "piece"))
        self.assertEqual(cmd[2:3] + cmd[4:], ["brand", "--from-dossier", str(self.home / "marques" / bid / "brand"), "--include-unconfirmed", "--force"])
        md = (self.pdir(pid) / "piece" / "brand.md").read_text()
        self.assertIn("name: Marrowbay Ferments", md)
        self.assertRegex(md, r"(?m)^- background: #[0-9a-f]{6}")
        self.assertRegex(md, r"(?m)^- text: #[0-9a-f]{6}.*(to confirm|à confirmer)")  # nobody gave the text colour: completed from the measured ones, marked
        self.assertTrue((self.pdir(pid) / "piece" / "references.md").exists())
        self.settle_mandates(pid)


class Mandates(Base):
    def test_an_agent_proposes_the_instructions_and_the_person_corrects_them(self):
        pid = self.started()
        self.fake.hold = threading.Event()
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o", "audience": "a", "message": "m"}})
        self.assertEqual(self.step(pid, "mandates")["status"], "running")  # the agent is at work
        self.assertEqual(self.asks(pid), [])
        self.call("GET", f"/api/projects/{pid}/mandates", code=409)
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": None, "common": "x"}, code=409)
        self.assertEqual([j["kind"] for j in self.call("GET", "/api/tasks")["jobs"] if j["project"] == pid], ["mandates"])
        self.fake.hold.set()
        self.settle_mandates(pid)
        self.assertEqual(self.asks(pid), ["mandates"])
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.assertEqual([x["mandate"] for x in m["items"]], ["Le goût d'abord", "Démonter l'idée reçue", "Le temps long", "Rupture : l'entre-deux"])
        self.assertEqual([x["id"] for x in m["items"]], ["v1", "v2", "v3", "v4"])
        call = self.fake.where("--restricted")[-1]
        self.assertEqual(call["argv"][:2], [call["argv"][0], "-p"])
        self.assertEqual(call["argv"][3:6], ["--model", "sonnet", "--no-session-persistence"])
        self.assertIn("--tools", call["argv"])
        self.assertIn("=== brand.md ===", call["argv"][2])
        self.assertIn("name: Marrowbay Ferments", call["argv"][2])
        self.assertIn("objective: o", call["argv"][2])
        self.assertIn("references.md", call["argv"][2])
        self.assertNotIn("ANTHROPIC_API_KEY", call["env"])  # the plan pays, not a key left in the environment
        items = [{"id": x["id"], "mandate": x["mandate"] + "!"} for x in m["items"]]
        r = self.call("PUT", f"/api/projects/{pid}/mandates", {"items": items, "common": "Tutoyer."})
        self.assertEqual((r["confirmed"], r["common"], r["items"][0]["mandate"]), (True, "Tutoyer.", "Le goût d'abord!"))
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": [{"id": "v1", "mandate": ""}], "common": ""}, code=400)
        self.assertEqual(self.asks(pid), ["diverge-launch"])

    def test_when_the_call_fails_a_default_proposal_stands(self):
        self.fake.claude_down = True
        pid = self.briefed()
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.assertEqual(len(m["items"]), 4)
        self.assertTrue(m["items"][3]["mandate"].startswith("Rupture"))
        self.assertEqual(self.asks(pid), ["mandates"])  # not a failure: the person reads and corrects as always
        job = next(j for j in json.loads((self.pdir(pid) / "project.json").read_text())["jobs"] if j["kind"] == "mandates")
        self.assertEqual(job["status"], "done")
        self.assertIn("not signed in", job["message"])


class Diverge(Base):
    def test_four_blind_agents_write_the_variants(self):
        pid = self.confirmed()
        self.call("POST", f"/api/projects/{pid}/diverge")
        for _ in range(500):
            if not [j for j in self.call("GET", "/api/tasks")["jobs"] if j["project"] == pid]:
                break
            time.sleep(0.02)
        vs = self.call("GET", f"/api/projects/{pid}/variants")
        self.assertEqual([v["id"] for v in vs], ["v1", "v2", "v3", "v4"])
        self.assertEqual(vs[3]["mandate"], "Rupture : l'entre-deux")
        self.assertEqual(vs[0]["headline"], "Titre de v1")
        self.assertEqual(self.asks(pid), ["diverge-pick"])
        agents = [c for c in self.fake.calls if c["cwd"] and "/work/v" in c["cwd"] and str(self.pdir(pid)) in c["cwd"]]
        self.assertEqual(sorted(Path(c["cwd"]).name for c in agents), ["v1", "v2", "v3", "v4"])
        for c in agents:
            vid = Path(c["cwd"]).name
            self.assertIn("--restricted", c["argv"])  # file tools confined to its folder
            self.assertIn("--tools=Read,Write", c["argv"])
            self.assertIn("--permission-mode=acceptEdits", c["argv"])
            self.assertEqual(c["argv"][c["argv"].index("--model") + 1], "sonnet")
            self.assertEqual(c["ls"], ["brand.md", "brief.md", "references.md", "refs"])  # its own folder: no variants/, no other agent's file
            self.assertIn(f"./{vid}.json", c["argv"][2])
            for other in ("Démonter l'idée reçue", "Le temps long", "Le goût d'abord"):
                mine = re.search(r"Your mandate: (.*)", c["argv"][2]).group(1)
                if other != mine:
                    self.assertNotIn(other, c["argv"][2])  # blind: it only knows its own mandate
            for rule in ("what you would have made by default", "second reading", "Nothing is invented"):
                self.assertTrue(rule in c["argv"][2] or rule.lower() in c["argv"][2].lower(), rule)
        refs = (self.pdir(pid) / "piece" / "references.md").read_text()
        self.assertIn("../brand/collect", refs)
        self.assertFalse((self.pdir(pid) / "piece" / "work").exists())  # the work folders are cleaned
        self.assertTrue(self.fake.where("diverge"))

    def test_one_agent_failing_is_tolerated_two_are_not(self):
        self.fake.agents_fail = {"v2"}
        pid = self.confirmed()
        self.wait(self.call("POST", f"/api/projects/{pid}/diverge"))
        self.assertEqual([v["id"] for v in self.call("GET", f"/api/projects/{pid}/variants")], ["v1", "v3", "v4"])
        self.fake.agents_fail = {"v1", "v2", "v3"}
        job = self.call("POST", f"/api/projects/{pid}/diverge")
        j = self.wait(job, "failed")
        self.assertIn("seulement 1 variante(s) valide(s) sur 4", j["message"])
        self.assertIn("v1: no variant file written", j["message"])
        ask = self.call("GET", f"/api/projects/{pid}")["waiting"]
        self.assertEqual([(a["step"], a["kind"], a["title"]) for a in ask], [("diverge", "job-failed", "Relancer la divergence")])
        self.assertEqual(self.step(pid, "diverge")["status"], "todo")
        self.fake.agents_fail = set()
        self.wait(self.call("POST", f"/api/projects/{pid}/diverge"))
        self.assertEqual(self.asks(pid), ["diverge-pick"])

    def test_diverge_waits_for_the_instructions(self):
        pid = self.briefed()
        self.call("POST", f"/api/projects/{pid}/diverge", code=409)
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": ["v1"]}, code=400)


class Pieces(Base):
    def test_picking_makes_one_piece_per_variant_and_format(self):
        pid, pieces = self.picked(("v1", "v3"))
        self.assertEqual([p["id"] for p in pieces], ["v1-post-4x5", "v1-story", "v3-post-4x5", "v3-story"])
        p = pieces[1]
        self.assertEqual((p["size"], p["format"], p["headline"], p["prompt"], p["image"], p["composed"], p["status"]),
                         ([1080, 1920], "story", "Titre de v1", "Une image pour v1, aucun texte.", None, None, "picked"))
        self.assertEqual(sorted(x.name for x in (self.pdir(pid) / "piece" / "pieces").iterdir()), ["v1-post-4x5", "v1-story", "v3-post-4x5", "v3-story"])
        self.assertIn("format: story", (self.pdir(pid) / "piece" / "pieces" / "v1-story" / "brief.md").read_text())
        self.assertEqual(self.asks(pid).count("prompt"), 2)  # one prompt task per variant: its two formats share it
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": ["v9"]}, code=400)
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": []}, code=400)
        self.call("GET", f"/api/projects/{pid}/pieces/nope", code=404)

    def test_one_variant_in_one_format_is_a_piece_too(self):
        pid, pieces = self.picked(("v2",), formats="post-1x1")
        self.assertEqual([p["id"] for p in pieces], ["v2-post-1x1"])
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v2-post-1x1")["headline"], "Titre de v2")
        self.assertTrue((self.pdir(pid) / "piece" / "pieces" / "v2" / "pick.json").exists())

    def test_the_prompt_is_corrected_in_the_variant_of_its_piece_only(self):
        pid, pieces = self.picked(("v1", "v3"))
        r = self.call("PUT", f"/api/projects/{pid}/pieces/v1-story/prompt", {"prompt": "Un verre, lumière du jour, aucun texte."})
        self.assertEqual(r["prompt"], "Un verre, lumière du jour, aucun texte.")
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v1-post-4x5")["prompt"], "Une image pour v1, aucun texte.")
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/variants")[0]["image_prompt"], "Une image pour v1, aucun texte.")
        self.call("PUT", f"/api/projects/{pid}/pieces/v1-story/prompt", {"prompt": "  "}, code=400)

    def test_a_prompt_is_one_task_per_variant_and_its_formats_share_it(self):
        pid, _ = self.picked(("v1", "v3"))
        t = [x for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == pid]
        self.assertEqual([(x["kind"], x["variant"], x["pieces"], x["piece"], x["piece_label"], x["title"]) for x in t],
                         [("prompt", "v1", ["v1-post-4x5", "v1-story"], "v1-post-4x5", "v1", "Relire le prompt de v1 (2 formats)"),
                          ("prompt", "v3", ["v3-post-4x5", "v3-story"], "v3-post-4x5", "v3", "Relire le prompt de v3 (2 formats)")])
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": "Un verre, lumière du jour, aucun texte."})
        self.assertEqual([x["id"] for x in r], ["v1-post-4x5", "v1-story"])
        for i in ("v1-post-4x5", "v1-story"):  # written in the variant file of each piece, which is what its image is drawn from
            self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/{i}")["prompt"], "Un verre, lumière du jour, aucun texte.")
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v3-story")["prompt"], "Une image pour v3, aucun texte.")
        self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": " "}, code=400)
        self.call("PUT", f"/api/projects/{pid}/variants/v9/prompt", {"prompt": "x"}, code=404)
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": "Un autre."})  # only the piece that still waits for its image
        self.assertEqual([x["id"] for x in r], ["v1-post-4x5"])
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")["prompt"], "Un verre, lumière du jour, aucun texte.")
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-post-4x5/image"))
        self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": "Trop tard."}, code=409)  # both have their image: redo one to change its prompt

    def test_the_words_of_a_variant_can_be_corrected_until_it_is_composed(self):
        pid, _ = self.picked(("v1", "v3"))
        self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "  "}, code=400)
        self.call("PUT", f"/api/projects/{pid}/variants/v9/text", {"headline": "x"}, code=404)
        self.fake.calls.clear()
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Acide,\npuis doux.", "subline": "Servez-vous."})
        self.assertEqual([(x["id"], x["headline"], x["subline"]) for x in r], [("v1-post-4x5", "Acide, puis doux.", "Servez-vous."), ("v1-story", "Acide, puis doux.", "Servez-vous.")])
        pick = self.fake.where("pick")[0]["argv"]
        self.assertEqual(pick[2:3] + pick[4:], ["pick", "v1", "--headline", "Acide, puis doux.", "--subline", "Servez-vous."])  # the studio's own command, which keeps them in pick.json
        pj = json.loads((self.pdir(pid) / "piece" / "pieces" / "v1-story" / "pick.json").read_text())
        self.assertEqual((pj["variant"], pj["headline"], pj["subline"]), ("v1", "Acide, puis doux.", "Servez-vous."))
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v3-story")["headline"], "Titre de v3")  # the other variant stays
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/variants")[0]["headline"], "Titre de v1")  # the variant as the agent wrote it stays too
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Acide, puis doux, puis rien."})  # the subline left out stays
        self.assertEqual((r[0]["headline"], r[0]["subline"]), ("Acide, puis doux, puis rien.", "Servez-vous."))
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Acide.", "subline": ""})  # an empty one takes it off
        self.assertEqual((r[0]["headline"], r[0]["subline"]), ("Acide.", ""))
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        self.assertIn("Acide.", (self.pdir(pid) / "piece" / "pieces" / "v1-story" / "piece.html").read_text())  # the piece is composed with the corrected words
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Doux."})  # only the piece that is not composed yet
        self.assertEqual([x["id"] for x in r], ["v1-post-4x5"])
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")["headline"], "Acide.")
        d = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/decide", {"verdict": "again", "words": "trop sombre"})
        self.assertEqual(d["headline"], "Acide.")  # sent back, it keeps the words the person corrected
        for pc in ("v3-post-4x5", "v3-story"):
            self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
            self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        self.call("PUT", f"/api/projects/{pid}/variants/v3/text", {"headline": "Trop tard."}, code=409)  # every piece of the variant is composed

    def test_all_the_images_are_drawn_at_once_and_all_the_pieces_composed(self):
        pid, _ = self.picked(("v1", "v3"))
        self.call("POST", f"/api/projects/{pid}/images", {"variant": "v9"}, code=400)
        self.call("POST", f"/api/projects/{pid}/compose", code=409)  # no image yet
        jobs = self.call("POST", f"/api/projects/{pid}/images", {"variant": "v1"})["jobs"]
        self.assertEqual(sorted(j["piece"] for j in jobs), ["v1-post-4x5", "v1-story"])
        for j in jobs:
            self.wait(j)
        self.call("POST", f"/api/projects/{pid}/images", {"variant": "v1"}, code=409)  # drawn already
        jobs = self.call("POST", f"/api/projects/{pid}/images")["jobs"]  # all the others
        self.assertEqual(sorted(j["piece"] for j in jobs), ["v3-post-4x5", "v3-story"])
        for j in jobs:
            self.wait(j)
        self.assertEqual(self.asks(pid), ["compose"] * 4)
        self.fake.calls.clear()
        r = self.call("POST", f"/api/projects/{pid}/compose")
        self.assertEqual((sorted(r["composed"]), r["failed"]), (["v1-post-4x5", "v1-story", "v3-post-4x5", "v3-story"], []))
        self.assertEqual(len(self.fake.where("compose")), 4)
        self.assertEqual(self.asks(pid), ["decide"] * 4)
        self.call("POST", f"/api/projects/{pid}/compose", code=409)  # nothing is left to compose
        self.call("POST", f"/api/projects/{pid}/images", code=409)

    def test_a_piece_that_cannot_be_composed_does_not_stop_the_others(self):
        pid, _ = self.picked(("v1",), formats="post-4x5, story")
        for j in self.call("POST", f"/api/projects/{pid}/images")["jobs"]:
            self.wait(j)
        self.fake.fake_png = False  # no Chrome: no screenshot, for every piece
        err = self.call("POST", f"/api/projects/{pid}/compose", code=400)
        self.assertIn("Chrome", err["error"])  # none could: the reason of the first
        self.assertEqual(self.asks(pid), ["compose"] * 2)

    def test_image_compose_check_decide(self):
        pid, _ = self.picked(("v1",), formats="story")
        pc = "v1-story"
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose", code=409)
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "keep"}, code=409)
        self.call("PUT", f"/api/projects/{pid}/pieces/{pc}/prompt", {"prompt": "Un verre, aucun texte."})
        job = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image")
        self.assertEqual((job["kind"], job["piece"]), ("image", pc))
        self.wait(job)
        img = self.fake.where("image")[-1]["argv"]
        self.assertEqual(img[2:3] + img[3:], ["image", str(self.pdir(pid) / "piece" / "pieces" / "v1"), "--engine", "auto", "--force"])
        got = self.call("GET", f"/api/projects/{pid}/pieces/{pc}")
        self.assertTrue(got["image"].startswith(f"/files/{pid}/piece/pieces/v1/image.png?v="))
        self.assertTrue(self.call("GET", got["image"], raw=True).startswith(b"\x89PNG"))
        self.assertEqual(self.asks(pid), ["compose"])
        c = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        self.assertEqual(set(c["check"]), {"pass", "warn", "fail", "major", "notes"})
        self.assertGreater(c["check"]["pass"], 3)
        self.assertEqual(c["check"]["fail"] + c["check"]["major"], 0)
        self.assertTrue(all(set(n) == {"status", "say"} and n["status"] != "pass" for n in c["check"]["notes"]))
        self.assertTrue(c["composed"].startswith(f"/files/{pid}/piece/pieces/v1/piece.png"))
        self.assertEqual(self.asks(pid), ["decide"])
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "again"}, code=400)
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "maybe"}, code=400)
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "keep", "words": "bon"})
        self.assertEqual((d["decision"]["verdict"], d["decision"]["words"]), ("keep", "bon"))
        self.assertIn("verdict: keep", (self.pdir(pid) / "piece" / "pieces" / "v1" / "decision.md").read_text())
        steps = {s["key"]: s["status"] for s in self.call("GET", f"/api/projects/{pid}")["steps"]}
        self.assertEqual([steps[k] for k in ("brand", "diverge", "image", "piece", "decide")], ["done"] * 5)
        self.assertEqual(self.asks(pid), [])

    def test_again_sends_the_piece_back_to_its_prompt_and_remembers_why(self):
        pid, _ = self.picked(("v1",), formats="story")
        pc = "v1-story"
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "again", "words": "trop sombre"})
        self.assertEqual((d["bans"], d["image"], d["composed"], d["decision"], d["status"]), (["trop sombre"], None, None, None, "again"))
        self.assertEqual(d["prompt"], "Une image pour v1, aucun texte.")  # the variant is back: the prompt can be read and redrawn
        self.assertEqual(self.asks(pid), ["prompt"])
        self.assertIn("trop sombre", (self.pdir(pid) / "piece" / "bans.md").read_text())  # the next round of variants reads it
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "again", "words": "encore trop sombre"})
        self.assertEqual(d["bans"], ["trop sombre", "encore trop sombre"])
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "keep", "words": "voilà"})
        self.assertEqual(d["decision"]["verdict"], "keep")

    def test_the_pieces_are_taken_out_one_by_one_and_in_a_zip(self):
        import io
        import zipfile
        pid, _ = self.picked(("v1", "v3"))
        self.fetch(f"/api/projects/{pid}/pieces/v1-story/download", code=409)  # not composed yet
        self.fetch(f"/api/projects/{pid}/download", code=409)  # nothing kept yet
        for pc in ("v1-story", "v3-story", "v3-post-4x5"):
            self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
            self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        head, data = self.fetch(f"/api/projects/{pid}/pieces/v1-story/download")
        self.assertEqual((head["Content-Type"], head["Content-Disposition"]), ("image/png", f'attachment; filename="{pid}-v1-story.png"'))
        self.assertEqual(data, (self.pdir(pid) / "piece" / "pieces" / "v1-story" / "piece.png").read_bytes())  # the file compose made, as it is
        self.fetch(f"/api/projects/{pid}/pieces/v1-post-4x5/download", code=409)  # its image is not drawn
        self.fetch(f"/api/projects/{pid}/pieces/nope/download", code=404)
        self.fetch(f"/api/projects/{pid}/download", code=409)  # composed is not kept
        self.call("POST", f"/api/projects/{pid}/pieces/v3-story/decide", {"verdict": "keep"})
        self.call("POST", f"/api/projects/{pid}/pieces/v3-post-4x5/decide", {"verdict": "keep"})
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/decide", {"verdict": "again", "words": "trop sombre"})
        head, data = self.fetch(f"/api/projects/{pid}/download")
        self.assertEqual((head["Content-Type"], head["Content-Disposition"]), ("application/zip", f'attachment; filename="{pid}.zip"'))
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(sorted(z.namelist()), [f"{pid}-v3-post-4x5.png", f"{pid}-v3-story.png"])  # only what is kept
        self.assertTrue(all(z.read(n).startswith(b"\x89PNG") for n in z.namelist()))
        self.fetch("/api/projects/nope/download", code=404)

    def test_a_missing_screenshot_is_said_not_hidden(self):
        pid, _ = self.picked(("v1",), formats="story")
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        self.fake.fake_png = False
        err = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose", code=400)
        self.assertIn("Chrome", err["error"])
        self.assertIsNone(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")["composed"])

    def test_a_failed_image_becomes_a_task_to_run_again_with_the_reason(self):
        pid, _ = self.picked(("v1",), formats="story")
        self.fake.image_fails = True
        job = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image")
        j = self.wait(job, "failed")
        self.assertIn("No image generator available", j["message"])
        ask = self.call("GET", f"/api/projects/{pid}")["waiting"]
        self.assertEqual([(a["step"], a["piece"], a["kind"], a["title"]) for a in ask], [("image", "v1-story", "job-failed", "Relancer l'image de v1 en story")])
        self.assertIn("No image generator available", ask[0]["question"])
        t = next(t for t in self.call("GET", "/api/tasks")["tasks"] if t["project"] == pid)
        self.assertEqual((t["id"], t["piece_label"]), (f"{pid}:image:v1-story", "v1 en story"))
        self.fake.image_fails = False
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        self.assertEqual(self.asks(pid), ["compose"])


class Runner(unittest.TestCase):
    def test_the_real_runner_closes_stdin_and_never_raises(self):
        r = run_command([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout=20)
        self.assertEqual((r.code, r.out.strip()), (0, "''"))  # an end of file at once: codex and claude would otherwise wait
        self.assertEqual(run_command(["definitely-not-a-command-xyz"]).code, 127)
        slow = run_command([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3)
        self.assertEqual(slow.code, 124)
        self.assertEqual(backend_studio.tail(Result(1, "out\n", "boom\nstudio: the real reason\n\n")), "the real reason")

    def test_the_backend_runs_the_commands_given_to_it_and_logs_them(self):
        home = Path(tempfile.mkdtemp(prefix="ixs-home-"))
        try:
            seen = []
            b = StudioBackend(home, runner=lambda argv, cwd=None, env=None, timeout=None: seen.append(argv) or Result(0, "ok\n", "warn\n"))
            log = home / "l.log"
            b._sh(log, ["echo", "a b", "c"])
            self.assertEqual(seen, [["echo", "a b", "c"]])
            self.assertIn("$ echo 'a b' c", log.read_text())
            self.assertIn("[stderr]\nwarn", log.read_text())
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_both_backends_answer_the_same_methods(self):
        """The server calls one set of methods on whichever backend runs: the simulated studio must have every one the real one has."""
        from backend_stub import StubBackend
        public = lambda c: {n for n in dir(c) if not n.startswith("_") and callable(getattr(c, n))}
        self.assertEqual(public(StudioBackend) - public(StubBackend), {"file"})  # pictures: only the real studio has files of its own
        self.assertEqual(public(StubBackend) - public(StudioBackend), {"state", "view"})

    def test_the_stage_of_a_brand_and_its_tasks(self):
        """The one place the stages are written (workflow.brand_stage), whatever the backend."""
        st = workflow.brand_stage
        base = {"id": "b", "name": "B", "site": "", "discovered": False, "kept": False, "logo": False, "colours_ok": True, "brief_done": False, "deduced": [], "unsorted": 0}
        self.assertEqual(st(base), "new")
        self.assertEqual(st({**base, "site": "https://x.example/"}), "to_brief")
        self.assertEqual(st({**base, "site": "https://x.example/", "running": {"id": "j"}}), "discovering")
        self.assertEqual(st({**base, "discovered": True, "unsorted": 3}), "to_sort")
        self.assertEqual(st({**base, "discovered": True, "kept": True, "brief_done": True}), "to_sort")  # kept without a logo
        kept = {**base, "discovered": True, "kept": True, "logo": True}
        self.assertEqual(st(kept), "to_brief")
        self.assertEqual(st({**kept, "brief_done": True, "deduced": ["voice"]}), "to_confirm")
        self.assertEqual(st({**kept, "brief_done": True, "migrated": True}), "to_confirm")
        self.assertEqual(st({**kept, "brief_done": True}), "ready")
        self.assertEqual(st({**kept, "brief_done": True, "colours_ok": False}), "to_brief")  # a logo and not the two colours a piece needs
        self.assertEqual([a["title"] for a in workflow.brand_asks({**kept, "brief_done": True, "colours_ok": False})], ["Choisir les couleurs de la marque"])
        self.assertEqual(workflow.brand_needs({**kept, "brief_done": True, "colours_ok": False}), ["colours"])
        self.assertEqual(workflow.brand_needs({**base, "brief_done": True}), ["logo"])
        self.assertEqual(st({**base, "brief_done": True}), "to_brief")  # nothing to find a logo in
        self.assertEqual([a["kind"] for a in workflow.brand_asks({**kept, "brief_done": True, "deduced": ["voice", "logo"]})], ["brand-confirm"])
        self.assertEqual([a["kind"] for a in workflow.brand_asks({**kept, "brief_done": True})], [])
        failed = workflow.brand_asks({**base, "site": "https://x.example/", "failed": {"error": "no Chrome"}})
        self.assertEqual([a["kind"] for a in failed], ["job-failed", "brand-brief"])
        self.assertIn("no Chrome", failed[0]["question"])
        self.assertEqual(workflow.brand_asks({**base, "site": "x", "failed": {"error": "e"}, "running": {"id": "j"}}), [])  # running again: nothing to do
        with self.assertRaises(ValueError):
            workflow.field("x", "maybe")
        self.assertEqual(workflow.field("x", "absent"), {"value": "", "state": "absent", "source": ""})

    def test_the_machine_is_looked_at_never_run(self):
        probe = backend_studio.probe_machine
        none = dict(env={}, which=lambda n: None, isfile=lambda p: False, glob_=lambda p: [])
        self.assertEqual(probe(**none), {"chrome": False, "claude": False, "image": False})
        have = lambda *names: lambda n: "/usr/bin/" + n if n in names else None
        self.assertEqual(probe(**{**none, "which": have("claude", "codex", "chromium")}), {"chrome": True, "claude": True, "image": True})
        self.assertEqual(probe(**{**none, "isfile": lambda p: p.endswith("Google Chrome")})["chrome"], True)  # the Chrome of a Mac
        self.assertEqual(probe(**{**none, "env": {"CHROME": "/x/chrome"}, "isfile": lambda p: p == "/x/chrome"})["chrome"], True)
        self.assertEqual(probe(**{**none, "env": {"CHROME": "/x/chrome"}, "which": have("chromium")})["chrome"], False)  # CHROME says where, and it is not there
        self.assertEqual(probe(**{**none, "env": {"OPENAI_API_KEY": "k"}})["image"], True)
        self.assertEqual(probe(**{**none, "env": {"OPENAI_API_KEY": "k"}}, image_engine="codex")["image"], False)  # the engine asked for is the one that counts
        self.assertEqual(probe(**{**none, "which": have("codex")}, image_engine="none")["image"], False)
        self.assertEqual(probe(**{**none, "env": {"STUDIO_CLAUDE_BIN": "/opt/claude"}, "which": lambda n: n if n == "/opt/claude" else None})["claude"], True)
        home = Path(tempfile.mkdtemp(prefix="ixs-home-"))
        try:
            b = StudioBackend(home, runner=lambda *a, **k: Result(1, "", "never called"), probe=lambda: {"chrome": True, "claude": False, "image": True})
            httpd = server.serve("127.0.0.1", 0, b)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/api/machine") as r:
                    got = json.loads(r.read())
            finally:
                httpd.shutdown()
                httpd.server_close()
            self.assertEqual((got["ok"], [m["key"] for m in got["missing"]]), (False, ["claude"]))
        finally:
            shutil.rmtree(home, ignore_errors=True)
        self.assertEqual(workflow.machine_view({"chrome": True, "claude": True, "image": True}), {"ok": True, "missing": []})

    def test_the_workflow_helpers(self):
        self.assertEqual(workflow.formats_of("Post 4x5, story, film 30s"), ["post-4x5", "story"])
        self.assertEqual(workflow.formats_of(""), ["post-4x5"])
        self.assertEqual(workflow.left_out_of("Post 4x5, story, film 30s"), ["film 30s"])
        self.assertEqual(workflow.split_words("franc; chaleureux\n drôle,, "), ["franc", "chaleureux", "drôle"])
        self.assertEqual(workflow.slug("Atelier Ondine !"), "atelier-ondine")

    def test_the_pickers_and_the_proposal(self):
        ok = [{"hex": "#FFFFFF", "role": "background"}, {"hex": "#112233", "role": "text"}]
        self.assertEqual(workflow.parse_palette(ok), [{"hex": "#ffffff", "role": "background"}, {"hex": "#112233", "role": "text"}])
        self.assertEqual([c["role"] for c in workflow.parse_palette(ok[::-1] + [{"hex": "#c8553d", "role": "accent"}])], ["background", "text", "accent"])
        for bad in (None, "x", [1], [], ok[:1], [{"hex": "#fff", "role": "background"}, ok[1]], [ok[0], {"hex": "#112233", "role": "dominant"}], ok + [ok[1]]):
            with self.assertRaises(ValueError):
                workflow.parse_palette(bad)
        measured = [{"hex": "#2f5d50", "role": "dominant"}, {"hex": "#e8dcc4", "role": "dominant 2"}, {"hex": "#1e2a24", "role": "dominant 3"}]
        self.assertEqual(workflow.palette_of(measured), {"background": "#e8dcc4", "text": "#1e2a24", "accent": None})  # the lightest, then what reads best on it
        self.assertEqual(workflow.palette_of(ok + measured), {"background": "#ffffff", "text": "#112233", "accent": None})  # a named role wins
        self.assertEqual(workflow.palette_of([{"hex": "#202020", "role": "dominant"}]), {"background": None, "text": "#202020", "accent": None})
        self.assertEqual(workflow.palette_of([]), {"background": None, "text": None, "accent": None})


if __name__ == "__main__":
    unittest.main()

