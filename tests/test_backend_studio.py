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
        self.hold = None  # an Event: claude calls wait for it
        self.env_seen = []

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
        (out / "logo-svg-1.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40"><rect width="120" height="40" fill="#222"/></svg>')
        logo = {"kind": "logo", "file": "logo-svg-1.svg", "src": "inline SVG on the page", "format": "svg", "where": "header svg"}
        facts = {"url": site, "final_url": "file:///fake-site/", "at": "2026-10-24T10:00:00Z", "title": "Site de test", "lang": "fr-FR",
                 "files": [{"kind": "screen", "file": "screen-01.png", "note": "y=0px"}, {"kind": "screen", "file": "screen-02.png", "note": "y=900px"}, logo],
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

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        f = self.fake
        f.agents_fail, f.claude_down, f.image_fails, f.collect_fails, f.hold, f.fake_png = set(), False, False, False, None, True

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

    # ---- the path, in stages
    def new(self, name="Test", brand="Marrowbay Ferments", site="marrowbay.example"):
        body = {"name": name, "brand": brand}
        if site is not None:
            body["site"] = site
        return self.call("POST", "/api/projects", body)["id"]

    def learned(self, **kw):
        pid = self.new(**kw)
        self.wait(self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"}))
        return pid

    sorted_src = sorted_home = None  # one brand read and sorted for real, which the other tests start from (a declination): the reading is tested once

    def sorted(self, **kw):
        if not kw and Base.sorted_src and (self.home / Base.sorted_src).exists() and self.home == Base.sorted_home:
            return self.call("POST", "/api/projects", {"name": "Test", "from": Base.sorted_src})["id"]
        pid = self.learned(**kw)
        b = self.call("GET", f"/api/projects/{pid}/brand")
        self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": [e["id"] for e in b["evidence"] if e["proposed"]], "logo": b["logos"][0]["id"]})
        if not kw:
            Base.sorted_src, Base.sorted_home = pid, self.home
        return pid

    def briefed(self, formats="post-4x5, story", **kw):
        pid = self.sorted(**kw)
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


class Create(Base):
    def test_a_project_is_a_folder_with_its_brand_and_site(self):
        pid = self.new(name="La campagne de rentrée", site="https://Marrowbay.example/shop?x=1#top")
        d = self.home / pid
        self.assertEqual(pid, "la-campagne-de-rentree")
        p = json.loads((d / "project.json").read_text())
        self.assertEqual((p["name"], p["brand_name"], p["site"]), ("La campagne de rentrée", "Marrowbay Ferments", "https://marrowbay.example/shop?x=1"))
        self.assertTrue((d / "piece").is_dir() and (d / "logs").is_dir())
        v = self.call("GET", f"/api/projects/{pid}")
        self.assertEqual((v["brand"], v["can_learn"], self.asks(pid)), ("Marrowbay Ferments", True, ["brand-how"]))
        self.assertEqual(self.new(name="La campagne de rentrée"), "la-campagne-de-rentree-2")

    def test_brand_is_required_and_the_site_is_optional(self):
        self.call("POST", "/api/projects", {"name": "x"}, code=400)
        pid = self.new(site=None)
        self.assertFalse(self.call("GET", f"/api/projects/{pid}")["can_learn"])
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"}, code=400)  # no site: the studio cannot search, and says so
        self.assertFalse([c for c in self.fake.where("node") if pid in " ".join(c["argv"])])  # nothing was started

    def test_a_site_must_be_a_public_web_address(self):
        for bad in ("ftp://marrowbay.example", "http://localhost:8000", "http://127.0.0.1/", "http://192.168.1.4/", "intranet", "file:///etc/passwd"):
            self.call("POST", "/api/projects", {"name": "x", "brand": "B", "site": bad}, code=400)
        self.assertEqual(normalise_site(""), "")
        self.assertEqual(normalise_site("marrowbay.example"), "https://marrowbay.example/")

    def test_a_declination_keeps_the_brand_and_the_brief(self):
        src = self.briefed()
        new = self.call("POST", "/api/projects", {"name": "Déclinaison", "from": src})
        self.assertEqual(new["brand"], "Marrowbay Ferments")
        self.assertEqual([a["kind"] for a in new["waiting"]], ["brief"])
        self.assertTrue((self.home / new["id"] / "piece" / "brand.md").exists())
        self.assertEqual(self.call("GET", f"/api/projects/{new['id']}/brief")["fields"]["message"], "c'est bon")
        self.call("POST", "/api/projects", {"name": "x", "from": "nope"}, code=404)


class Brand(Base):
    def test_learning_reads_the_site_and_lists_what_to_sort(self):
        pid = self.new()
        job = self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"})
        self.assertEqual(job["kind"], "learn")
        done = self.wait(job)
        self.assertEqual(done["progress"], 1.0)
        calls = [c["argv"] for c in self.fake.calls if str(self.home / pid) in " ".join(c["argv"])]
        collect = next(c for c in calls if Path(c[0]).name == "node")
        self.assertEqual(collect[1:3], [str(backend_studio.COLLECT), "https://marrowbay.example/"])
        self.assertEqual(Path(collect[3]), self.home / pid / "brand" / "collect" / "web-marrowbay.example")
        kinds = [c[2] for c in calls if Path(c[1]).name == "brandkit"]
        self.assertEqual(kinds[:3], ["init", "infer-site", "review-html"])
        self.assertIn("--no-previews", next(c for c in calls if len(c) > 2 and c[2] == "review-html"))
        b = self.call("GET", f"/api/projects/{pid}/brand")
        self.assertEqual([e["note"] for e in b["evidence"]], ["Capture du site, haut de la page", "Capture du site, plus bas (900 px)"])
        self.assertTrue(all(e["proposed"] is True and e["kept"] is None for e in b["evidence"]))
        self.assertEqual(len(b["logos"]), 1)
        self.assertEqual(self.asks(pid), ["brand-sort"])
        self.assertEqual([a["title"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]], ["Trier 2 visuels de la marque"])
        img = self.call("GET", b["evidence"][0]["preview"], raw=True)  # the picture is served
        self.assertTrue(img.startswith(b"\x89PNG"))

    def test_sorting_keeps_the_choices_and_writes_brand_md(self):
        pid = self.learned()
        b = self.call("GET", f"/api/projects/{pid}/brand")
        keep = [b["evidence"][0]["id"]]
        r = self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": keep, "logo": b["logos"][0]["id"]})
        self.assertEqual((r["kept"], r["discarded"], r["logo"]), (1, 1, b["logos"][0]["id"]))
        self.assertTrue(r["colours"] and all(re.fullmatch(r"#[0-9a-f]{6}", c["hex"]) and c["status"] for c in r["colours"]))
        md = (self.home / pid / "piece" / "brand.md").read_text()
        self.assertIn("name: Marrowbay Ferments", md)
        self.assertRegex(md, r"(?m)^- background: #[0-9a-f]{6}")
        self.assertRegex(md, r"(?m)^- text: #[0-9a-f]{6}.*(to confirm|à confirmer)")  # nobody gave the text colour: completed, marked
        self.assertTrue((self.home / pid / "piece" / "references.md").exists())
        cmd = next(c["argv"] for c in self.fake.calls if len(c["argv"]) > 3 and c["argv"][2] == "brand" and "--from-dossier" in c["argv"] and str(self.home / pid) in c["argv"][3])
        self.assertEqual(cmd[2:3] + cmd[4:], ["brand", "--from-dossier", str(self.home / pid / "brand"), "--include-unconfirmed", "--force"])
        b2 = self.call("GET", f"/api/projects/{pid}/brand")
        self.assertEqual([e["kept"] for e in b2["evidence"]], [True, False])
        self.assertEqual((b2["kept"], b2["logo"]), (True, b["logos"][0]["id"]))
        self.assertEqual(self.asks(pid), ["brief"])
        keepcall = next(c["argv"] for c in self.fake.calls if len(c["argv"]) > 2 and c["argv"][2] == "keep" and str(self.home / pid) in c["argv"][3])
        self.assertIn(keep[0], keepcall)
        self.assertIn("--logo", keepcall)

    def test_sorting_refuses_what_it_does_not_know(self):
        pid = self.new()
        self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": [], "logo": None}, code=409)
        self.wait(self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"}))
        self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": ["ev-nope"], "logo": None}, code=400)
        self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": [], "logo": "ev-nope"}, code=400)
        self.assertEqual(self.asks(pid), ["brand-sort"])

    def test_answer_and_create_need_no_search_and_still_give_a_brand(self):
        pid = self.new(site=None)
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer"}, code=400)
        r = self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer", "answers": "Un kombucha de port."})
        self.assertEqual(r["status"], "done")
        b = self.call("GET", f"/api/projects/{pid}/brand")
        self.assertEqual((b["evidence"], b["answers"]), ([], "Un kombucha de port."))
        self.assertEqual([a["title"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]], ["Valider une marque sans visuel"])
        self.assertTrue([c for c in self.fake.calls if c["argv"][-2:] == ["identity.one_liner", "Un kombucha de port."]])  # given to the dossier too
        r = self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": [], "logo": None})
        self.assertEqual((r["kept"], r["colours"]), (0, []))
        md = (self.home / pid / "piece" / "brand.md").read_text()
        self.assertRegex(md, r"background: #ffffff \(à confirmer")  # nothing known: neutral colours, marked
        self.assertEqual(self.asks(pid), ["brief"])
        pid2 = self.new(site=None)
        self.call("POST", f"/api/projects/{pid2}/brand/learn", {"mode": "create"})
        self.assertEqual(self.call("GET", f"/api/projects/{pid2}/brand")["evidence"], [])

    def test_a_failed_reading_becomes_a_task_to_run_again(self):
        self.fake.collect_fails = True
        pid = self.new()
        job = self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"})
        j = self.wait(job, "failed")
        self.assertIn("no Chrome found", j["message"])
        self.assertEqual(self.step(pid, "brand")["status"], "todo")
        ask = self.call("GET", f"/api/projects/{pid}")["waiting"]
        self.assertEqual([a["kind"] for a in ask], ["job-failed"])
        self.assertIn("no Chrome found", ask[0]["question"])
        task = next(t for t in self.call("GET", "/api/tasks")["tasks"] if t["project"] == pid)
        self.assertEqual((task["kind"], task["step"], task["id"]), ("job-failed", "brand", f"{pid}:brand:"))
        self.assertTrue((self.home / pid / "logs" / f"{job['id']}.log").read_text().count("no Chrome found"))  # the log keeps the output
        self.fake.collect_fails = False
        self.wait(self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"}))
        self.assertEqual(self.asks(pid), ["brand-sort"])


class Brief(Base):
    def test_the_brief_is_written_for_the_studio_and_validated_by_it(self):
        pid = self.sorted()
        got = self.call("GET", f"/api/projects/{pid}/brief")
        self.assertEqual((got["chosen"], got["left_out"], got["confirmed"]), (["post-4x5"], [], False))
        self.assertIn("post-1x1", got["formats"])
        f = got["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": ""}}, code=400)
        err = self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o", "audience": "a", "message": "m", "layout": "diagonal"}}, code=400)
        self.assertIn("layout must be one of", err["error"])  # the studio's own message
        self.assertFalse(self.call("GET", f"/api/projects/{pid}/brief")["confirmed"])
        self.assertFalse((self.home / pid / "piece" / "brief.md").exists())
        r = self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "objective": "o\nsur deux lignes", "audience": "a", "message": "m", "format": "post-4x5, story, pub télé 30s"}})
        self.assertEqual((r["formats"], r["left_out"]), (["post-4x5", "story"], ["pub télé 30s"]))
        txt = (self.home / pid / "piece" / "brief.md").read_text()
        self.assertIn("objective: o sur deux lignes", txt)
        self.assertIn("format: post-4x5, story\n", txt)  # the studio only gets what it can make
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/brief")["fields"]["format"], "post-4x5, story, pub télé 30s")  # the person's line is kept whole
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o"}}, code=400)
        self.settle_mandates(pid)

    def test_no_brief_before_the_brand_is_sorted(self):
        pid = self.learned()
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o", "audience": "a", "message": "m"}}, code=409)


class Mandates(Base):
    def test_an_agent_proposes_the_instructions_and_the_person_corrects_them(self):
        pid = self.sorted()
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
        job = next(j for j in json.loads((self.home / pid / "project.json").read_text())["jobs"] if j["kind"] == "mandates")
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
        agents = [c for c in self.fake.calls if c["cwd"] and "/work/v" in c["cwd"] and str(self.home / pid) in c["cwd"]]
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
        refs = (self.home / pid / "piece" / "references.md").read_text()
        self.assertIn("../brand/collect", refs)
        self.assertFalse((self.home / pid / "piece" / "work").exists())  # the work folders are cleaned
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
        self.assertEqual(sorted(x.name for x in (self.home / pid / "piece" / "pieces").iterdir()), ["v1-post-4x5", "v1-story", "v3-post-4x5", "v3-story"])
        self.assertIn("format: story", (self.home / pid / "piece" / "pieces" / "v1-story" / "brief.md").read_text())
        self.assertEqual(self.asks(pid).count("prompt"), 4)
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": ["v9"]}, code=400)
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": []}, code=400)
        self.call("GET", f"/api/projects/{pid}/pieces/nope", code=404)

    def test_one_variant_in_one_format_is_a_piece_too(self):
        pid, pieces = self.picked(("v2",), formats="post-1x1")
        self.assertEqual([p["id"] for p in pieces], ["v2-post-1x1"])
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v2-post-1x1")["headline"], "Titre de v2")
        self.assertTrue((self.home / pid / "piece" / "pieces" / "v2" / "pick.json").exists())

    def test_the_prompt_is_corrected_in_the_variant_of_its_piece_only(self):
        pid, pieces = self.picked(("v1", "v3"))
        r = self.call("PUT", f"/api/projects/{pid}/pieces/v1-story/prompt", {"prompt": "Un verre, lumière du jour, aucun texte."})
        self.assertEqual(r["prompt"], "Un verre, lumière du jour, aucun texte.")
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v1-post-4x5")["prompt"], "Une image pour v1, aucun texte.")
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/variants")[0]["image_prompt"], "Une image pour v1, aucun texte.")
        self.call("PUT", f"/api/projects/{pid}/pieces/v1-story/prompt", {"prompt": "  "}, code=400)

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
        self.assertEqual(img[2:3] + img[3:], ["image", str(self.home / pid / "piece" / "pieces" / "v1"), "--engine", "auto", "--force"])
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
        self.assertIn("verdict: keep", (self.home / pid / "piece" / "pieces" / "v1" / "decision.md").read_text())
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
        self.assertIn("trop sombre", (self.home / pid / "piece" / "bans.md").read_text())  # the next round of variants reads it
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "again", "words": "encore trop sombre"})
        self.assertEqual(d["bans"], ["trop sombre", "encore trop sombre"])
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "keep", "words": "voilà"})
        self.assertEqual(d["decision"]["verdict"], "keep")

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


class Tasks(Base):
    def test_tasks_across_projects_oldest_first_with_running_jobs(self):
        a, b = self.new(name="tâches A"), self.new(name="tâches B")
        mine = [t for t in self.call("GET", "/api/tasks")["tasks"] if t["project"] in (a, b)]
        self.assertEqual([(t["project"], t["kind"]) for t in mine], [(a, "brand-how"), (b, "brand-how")])
        self.assertTrue(all(t["title"] and t["since"] and t["project_name"] for t in mine))
        self.fake.hold = threading.Event()
        self.fake.hold.set()
        job = self.call("POST", f"/api/projects/{a}/brand/learn", {"mode": "learn"})
        running = [j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == job["id"]]
        for j in running:
            self.assertEqual((j["project"], j["kind"]), (a, "learn"))
            self.assertTrue(0 <= j["progress"] <= 0.95 and j["eta"] >= 0)
        self.wait(job)
        self.assertEqual([j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == job["id"]], [])
        self.assertIn({"id": a, "name": "tâches A", "brand": "Marrowbay Ferments", "can_learn": True, "pieces": 0, "waiting": 1}, self.call("GET", "/api/tasks")["projects"])

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
        for k in ("id", "name", "brand", "steps", "pieces", "waiting", "jobs"):
            self.assertEqual(after[k], before[k], k)
        self.assertEqual([t["id"] for t in again.tasks()["tasks"] if t["project"] == pid], [f"{pid}:piece:v1-story"])
        self.assertEqual(again.get_mandates(pid)["items"][0]["id"], "v1")
        self.assertEqual(again.variants(pid)[0]["headline"], "Titre de v1")
        self.assertEqual(again.brand(pid)["kept"], True)
        job_id = json.loads((self.home / pid / "project.json").read_text())["jobs"][0]["id"]
        self.assertEqual(again.job(job_id)["status"], "done")

    def test_a_job_that_was_running_when_the_server_stopped_is_failed(self):
        pid = self.new()
        d = self.home / pid / "project.json"
        p = json.loads(d.read_text())
        p["jobs"].append({"id": "job-dead", "kind": "learn", "piece": None, "status": "running", "start": time.time() - 30, "message": "", "error": None, "result": None})
        d.write_text(json.dumps(p))
        again = StudioBackend(self.home, runner=self.fake)
        j = again.job("job-dead")
        self.assertEqual(j["status"], "failed")
        self.assertIn("redémarré", j["message"])
        self.assertEqual([a["kind"] for a in again.project(pid)["waiting"]], ["job-failed"])  # and a task to run it again


class Files(Base):
    def test_the_files_route_never_leaves_the_project(self):
        pid = self.learned()
        other = self.new(name="autre")
        ok = f"/files/{pid}/brand/collect/web-marrowbay.example/screen-01.png"
        self.assertTrue(self.call("GET", ok, raw=True).startswith(b"\x89PNG"))
        (self.home / "secret.txt").write_text("secret")
        (self.home / pid / "piece" / "link.txt").symlink_to(self.home / "secret.txt")
        for bad in (f"/files/{pid}/project.json", f"/files/{pid}/logs/commands.log", f"/files/{pid}/brand/../project.json",
                    f"/files/{pid}/brand/%2e%2e/project.json", f"/files/{pid}/brand/..%2f..%2fsecret.txt", f"/files/{pid}/piece/link.txt",
                    f"/files/{pid}/%2e%2e/secret.txt", f"/files/{pid}/brand/collect/web-marrowbay.example/..%2f..%2f..%2f..%2fsecret.txt",
                    f"/files/{pid}/brand", f"/files/nope/brand/x.png", f"/files/{other}/brand/collect/web-marrowbay.example/screen-01.png",
                    f"/files/../secret.txt", f"/files//etc/passwd", f"/files/{pid}//etc/passwd", f"/files/{pid}/brand/%00.png"):
            self.call("GET", bad, code=404, raw=True)
        self.assertEqual(self.call("GET", f"/files/{pid}/brand/collect/web-marrowbay.example/screen-01.png", raw=True)[:4], b"\x89PNG")

    def test_the_files_route_has_the_authentication_of_the_api(self):
        pid = self.learned()
        path = f"/files/{pid}/brand/collect/web-marrowbay.example/screen-01.png"
        os.environ.update(STUDIO_AUTH="token", STUDIO_TOKEN="s3cret")
        try:
            self.call("GET", path, code=401, raw=True)
            self.call("GET", path, code=401, raw=True, headers={"Authorization": "Bearer wrong"})
            self.assertTrue(self.call("GET", path, raw=True, headers={"Authorization": "Bearer s3cret"}).startswith(b"\x89PNG"))
        finally:
            os.environ.pop("STUDIO_AUTH")
            os.environ.pop("STUDIO_TOKEN")

    def test_a_picture_cannot_run_a_script_when_opened_on_its_own(self):
        pid = self.learned()
        req = urllib.request.Request(self.base + f"/files/{pid}/brand/collect/web-marrowbay.example/logo-svg-1.svg")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(r.headers["Content-Security-Policy"], "sandbox")
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")


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

    def test_the_workflow_helpers(self):
        self.assertEqual(workflow.formats_of("Post 4x5, story, film 30s"), ["post-4x5", "story"])
        self.assertEqual(workflow.formats_of(""), ["post-4x5"])
        self.assertEqual(workflow.left_out_of("Post 4x5, story, film 30s"), ["film 30s"])


if __name__ == "__main__":
    unittest.main()
