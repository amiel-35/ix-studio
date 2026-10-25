"""The judge: one judge, five headings, in words, without a score. Its two doors (in the chain, after a piece is composed and checked; on its own,
a piece dropped with its brief), the checking of what it writes, an incomplete brief, a failure run again, a dropped piece refused.

The real backend runs the repository's tools for real, offline; the judge (`claude -p`) is the fake runner of test_backend_studio. Nothing here
calls claude, codex or the network.

    python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util  # noqa: E402
import server  # noqa: E402
import workflow  # noqa: E402
from backend_stub import StubBackend  # noqa: E402
from test_backend_studio import JUDGED, Base, png  # noqa: E402

_spec = importlib.util.spec_from_file_location("ixs_studio_checks", ROOT / "scripts" / "studio" / "checks.py")  # how `studio check` reads judge.md
checks = importlib.util.module_from_spec(_spec)  # by its path: scripts/brandkit has a checks.py too
sys.path.insert(0, str(ROOT / "scripts" / "studio"))  # it imports colour and files from beside it
try:
    _spec.loader.exec_module(checks)
finally:
    sys.path.remove(str(ROOT / "scripts" / "studio"))

BRIEF = {"objective": "faire goûter le kombucha", "audience": "des citadins qui n'en ont jamais bu", "message": "c'est du thé qui a fait la fête",
         "cta": "Au marché samedi", "fixed": "les couleurs de la marque"}
HEADINGS = {"target", "works", "snags", "unsourced", "brand", "missing"}


def drop(base, data, ctype="image/png", name="affiche.png", meta=None, code=200):
    """A piece dropped to be judged: the file is the body, what comes with it the X-Judge header (JSON, URL-encoded)."""
    head = {"Content-Type": ctype, "X-Filename": name}
    if meta is not None:
        head["X-Judge"] = urllib.parse.quote(meta if isinstance(meta, str) else json.dumps(meta))
    req = urllib.request.Request(base + "/api/judgements", method="POST", data=data, headers=head)
    try:
        with urllib.request.urlopen(req) as r:
            got, out = r.status, json.loads(r.read())
    except urllib.error.HTTPError as err:
        got, out = err.code, json.loads(err.read())
        err.close()
    assert got == code, (got, out)
    return out


class Verdict(unittest.TestCase):
    """What the judge writes is checked before anything is shown: one shape, whichever backend."""

    def test_a_verdict_is_put_in_its_one_shape(self):
        v = workflow.parse_verdict("Voilà :\n```json\n" + json.dumps(JUDGED) + "\n```", True, workflow.judge_brief(BRIEF))
        self.assertEqual(set(v), HEADINGS)
        self.assertNotIn("score", v)  # no score, even when the agent gives one
        self.assertEqual((v["target"]["reached"], v["missing"]), ("partly", []))
        self.assertEqual(v["unsourced"], [{"where": "le bandeau du bas", "say": "« n°1 en ville » : rien ne permet de le croire."}])
        self.assertEqual(len(v["brand"]), 1)

    def test_no_brand_no_brand_heading(self):
        v = workflow.parse_verdict(JUDGED, False, workflow.judge_brief(BRIEF))
        self.assertIsNone(v["brand"])
        self.assertIsNone(workflow.parse_verdict({**JUDGED, "brand": None}, False, workflow.judge_brief(BRIEF))["brand"])

    def test_what_does_not_hold_is_refused(self):
        brief = workflow.judge_brief(BRIEF)
        bad = [("pas de JSON", "no JSON"), ("{oops}", "not readable"), ([], "object"),
               ({**JUDGED, "target": {"reached": "maybe", "why": "x"}}, "target"),
               ({**JUDGED, "target": {"reached": "yes", "why": " "}}, "target"),
               ({k: v for k, v in JUDGED.items() if k != "snags"}, "snags"),
               ({**JUDGED, "works": "tout"}, "works"),
               ({**JUDGED, "works": [{"where": "", "say": "bien"}]}, "where"),
               ({**JUDGED, "unsourced": [{"x": 10, "y": 20, "say": "un chiffre"}]}, "where"),  # a drawn zone is not a place said in words
               ({**JUDGED, "brand": None}, "brand")]
        for raw, word in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError) as cm:
                    workflow.parse_verdict(raw, True, brief)
                self.assertIn(word, str(cm.exception))

    def test_an_incomplete_brief_is_said_and_the_rest_judged(self):
        brief = workflow.judge_brief({"objective": "faire goûter", "message": "c'est bon"})
        self.assertEqual(workflow.judge_missing(brief), ["la cible", "l'appel à l'action"])
        v = workflow.parse_verdict(JUDGED, False, brief)  # the agent judged the target all the same: what the backend knows wins
        self.assertEqual(v["target"], {"reached": "unjudgeable", "why": "non jugeable sur la cible : il manque la cible"})
        self.assertEqual(v["missing"], ["la cible", "l'appel à l'action"])
        self.assertEqual(len(v["snags"]), 1)  # the rest is judged
        v = workflow.parse_verdict(JUDGED, False, workflow.judge_brief({**BRIEF, "cta": ""}))
        self.assertEqual((v["target"]["reached"], v["missing"]), ("partly", ["l'appel à l'action"]))  # the target can be judged without the call to action
        self.assertEqual(workflow.judge_missing(workflow.judge_brief({**BRIEF, "fixed": ""})), [])  # the frame of the assets is optional

    def test_judge_md_is_read_by_studio_check_and_blocks_nothing(self):
        v = workflow.parse_verdict(JUDGED, True, workflow.judge_brief({**BRIEF, "audience": ""}))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "judge.md").write_text(workflow.judge_md(v), encoding="utf-8")
            notes = checks.judge_notes(tmp)
        self.assertEqual(len(notes), 1 + 1 + 1 + 1 + 1 + 1)  # the target, one per annotation, what the brief lacks
        self.assertTrue(all(n["level"] == "note" for n in notes))  # never major: the judge blocks nothing
        self.assertEqual(notes[0]["say"], "cible, non jugeable : non jugeable sur la cible : il manque la cible")
        self.assertIn("sans provenance, le bandeau du bas : « n°1 en ville »", " ".join(n["say"] for n in notes))

    def test_the_flat_page_has_the_piece_on_top_and_the_list_under_it(self):
        v = workflow.parse_verdict(JUDGED, False, workflow.judge_brief(BRIEF))
        page = workflow.judge_page(v, "data:image/png;base64,AAAA", "Affiche <été>", "", "2026-10-25")
        self.assertLess(page.index("<img"), page.index("La cible"))
        self.assertIn("Affiche &lt;été&gt;", page)
        self.assertNotIn("La marque", page)  # no brand, no heading
        self.assertIn("Sans provenance", page)

    def test_a_dropped_piece_is_a_png_or_a_jpg_of_a_bounded_size(self):
        self.assertEqual(workflow.judge_image_ext(png(), "image/png"), "png")
        self.assertEqual(workflow.judge_image_ext(b"\xff\xd8\xff\xe0rest", "image/jpeg"), "jpg")
        for data, ctype, word in [(png(), "image/svg+xml", "png or jpg"), (png(), "image/gif", "png or jpg"), (b"", "image/png", "empty"),
                                  (b"GIF89a", "image/png", "not a png"), (png(), "image/jpeg", "not a jpg"),
                                  (b"\x89PNG\r\n\x1a\n" + b"0" * workflow.JUDGE_MAX, "image/png", "too big")]:
            with self.subTest(ctype=ctype, word=word):
                with self.assertRaises(ValueError) as cm:
                    workflow.judge_image_ext(data, ctype)
                self.assertIn(word, str(cm.exception))


class StubJudge(unittest.TestCase):
    """The simulated studio: a plausible and fixed verdict, through the same routes."""

    @classmethod
    def setUpClass(cls):
        cls.backend = StubBackend(speed=0.01)
        cls.httpd = server.serve("127.0.0.1", 0, cls.backend)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None, code=200):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                got, data = r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            got, data = err.code, json.loads(err.read())
            err.close()
        self.assertEqual(got, code, data)
        return data

    def until(self, fn, what):
        for _ in range(200):
            v = fn()
            if v:
                return v
            time.sleep(0.02)
        self.fail(what)

    def composed(self):
        pid = self.call("POST", "/api/brands/marrowbay-ferments/projects", {"name": "Juge"})["id"]
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "format": "story"}})
        self.call("PUT", f"/api/projects/{pid}/mandates", {})
        j = self.call("POST", f"/api/projects/{pid}/diverge")
        self.until(lambda: self.call("GET", f"/api/jobs/{j['id']}")["status"] == "done", "diverge")
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": ["v1"]})
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose", code=409)
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/judge", code=409)  # nothing to judge before it is composed
        j = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image")
        self.until(lambda: self.call("GET", f"/api/jobs/{j['id']}")["status"] == "done", "image")
        return pid

    def test_in_the_chain_the_judge_reads_the_piece_once_composed(self):
        pid = self.composed()
        pc = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        self.assertEqual(pc["judge"]["status"], "running")
        self.assertIn("decide", [a["kind"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]])  # it blocks nothing
        self.assertTrue(any(j["kind"] == "judge" and j["piece"] == "v1-story" for j in self.call("GET", "/api/tasks")["jobs"]))
        pc = self.until(lambda: (lambda x: x if x["judge"]["status"] == "done" else None)(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")), "judge")
        v = pc["judge"]["verdict"]
        self.assertEqual(set(v), HEADINGS)
        self.assertIsInstance(v["brand"], list)  # a piece of a project has its brand
        self.assertTrue(all(n["where"] and n["say"] for k in ("works", "snags", "unsourced") for n in v[k]))
        self.assertEqual([a["kind"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]], ["decide"])
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/judge")  # run again: the same verdict comes back
        d = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/decide", {"verdict": "again", "words": "trop sombre"})
        self.assertIsNone(d["judge"])  # sent back: a new piece will be judged anew

    def test_a_piece_judged_on_its_own(self):
        before = len(self.call("GET", "/api/judgements"))
        jg = drop(self.base, png(), meta={"brand": "marrowbay-ferments", "brief": BRIEF})
        self.assertEqual((jg["status"], jg["brand_name"], jg["name"], jg["missing"]), ("running", "Marrowbay Ferments", "affiche", []))
        self.assertTrue(jg["image"].startswith("data:image/png;base64,"))
        self.call("GET", f"/api/judgements/{jg['id']}/page", code=409)  # no page before the verdict
        jg = self.until(lambda: (lambda x: x if x["status"] == "done" else None)(self.call("GET", f"/api/judgements/{jg['id']}")), "judgement")
        self.assertEqual(set(jg["verdict"]), HEADINGS)
        self.assertIsInstance(jg["verdict"]["brand"], list)
        rows = self.call("GET", "/api/judgements")
        self.assertEqual((len(rows), rows[0]["id"], set(rows[0])), (before + 1, jg["id"], {"id", "name", "brand", "brand_name", "status", "at"}))
        with urllib.request.urlopen(self.base + f"/api/judgements/{jg['id']}/page") as r:
            self.assertEqual(r.headers["Content-Type"], "text/html; charset=utf-8")
            self.assertIn("attachment", r.headers["Content-Disposition"])
            self.assertIn("Ce qui accroche", r.read().decode())

    def test_without_brand_and_without_target(self):
        jg = drop(self.base, b"\xff\xd8\xff\xe0jpeg", "image/jpeg", "post.jpg", meta={"brief": {**BRIEF, "audience": ""}})
        jg = self.until(lambda: (lambda x: x if x["status"] == "done" else None)(self.call("GET", f"/api/judgements/{jg['id']}")), "judgement")
        v = jg["verdict"]
        self.assertEqual((v["brand"], v["target"]["why"], v["missing"]), (None, "non jugeable sur la cible : il manque la cible", ["la cible"]))
        self.assertTrue(v["snags"])

    def test_a_failure_is_said_and_run_again(self):
        jg = drop(self.base, png(), name="fail.png", meta={"brief": BRIEF})
        jg = self.until(lambda: (lambda x: x if x["status"] == "failed" else None)(self.call("GET", f"/api/judgements/{jg['id']}")), "failure")
        self.assertIn("simulé", jg["error"])
        job = self.call("POST", f"/api/judgements/{jg['id']}/run")
        self.assertEqual(job["kind"], "judge")
        self.call("POST", f"/api/judgements/{jg['id']}/run", code=409)  # already running
        self.call("GET", "/api/judgements/nope", code=404)

    def test_a_dropped_piece_is_checked(self):
        drop(self.base, b"<svg/>", "image/svg+xml", "x.svg", {"brief": BRIEF}, code=400)
        drop(self.base, b"GIF89a", "image/png", "x.png", {"brief": BRIEF}, code=400)
        drop(self.base, b"", "image/png", "x.png", {"brief": BRIEF}, code=400)
        drop(self.base, png(), meta={"brand": "nope", "brief": BRIEF}, code=400)
        drop(self.base, png(), meta="{pas du json", code=400)
        err = drop(self.base, b"\x89PNG\r\n\x1a\n" + b"0" * workflow.JUDGE_MAX, meta={"brief": BRIEF}, code=400)
        self.assertIn("too big", err["error"])


class RealJudge(Base):
    """The real studio: an agent without a screen, through the injected runner, in a folder of its own."""

    def judge_calls(self):
        return [c for c in self.fake.calls if Path(c["argv"][0]).name == "claude" and "./verdict.json" in c["argv"][2]]

    def until(self, fn, what):
        for _ in range(500):
            v = fn()
            if v:
                return v
            time.sleep(0.02)
        self.fail(what)

    def piece_when(self, pid, status):
        return self.until(lambda: (lambda x: x if (x["judge"] or {}).get("status") == status else None)(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")),
                          f"judge {status}")

    def composed(self):
        pid, _ = self.picked(("v1",), formats="story")
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        return pid

    def test_in_the_chain_the_judge_reads_the_piece_once_composed_and_checked(self):
        pid = self.composed()
        self.fake.judge_hold = threading.Event()
        pc = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        self.assertEqual(pc["judge"], {"status": "running", "verdict": None, "error": None})
        self.assertEqual(self.asks(pid), ["decide"])  # it blocks nothing: the decision is there while it reads
        job = next(j for j in self.call("GET", "/api/tasks")["jobs"] if j["project"] == pid)
        self.assertEqual((job["kind"], job["piece"]), ("judge", "v1-story"))
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/judge", code=409)  # already reading
        self.fake.judge_hold.set()
        pc = self.piece_when(pid, "done")
        v = pc["judge"]["verdict"]
        self.assertEqual(set(v), HEADINGS)
        self.assertNotIn("score", v)
        self.assertEqual(v["brand"], [{"where": "le titre en haut", "say": "C'est sa voix, franche."}])
        call = self.judge_calls()[-1]
        self.assertEqual(call["ls"], ["inputs.md", "piece.png"])  # a folder of its own: the picture and the entries, nothing else
        self.assertIn("--tools=Read,Write", call["argv"])
        self.assertIn("titre : Titre de v1", self.fake.inputs)  # the words of the piece
        self.assertIn("cible : des citadins", self.fake.inputs)
        self.assertIn("sa voix : franc, chaleureux, drôle", self.fake.inputs)  # the brand's voice
        d = self.pdir(pid) / "piece" / "pieces" / "v1"
        self.assertEqual(json.loads((d / "judge.json").read_text()), v)
        self.assertIn("sans provenance, le bandeau du bas", (d / "judge.md").read_text())
        chk = json.loads((d / "check.json").read_text())
        self.assertTrue(chk["judge"])  # `studio check` ran again and read judge.md
        self.assertEqual(chk["summary"]["major"], 0)
        self.assertFalse(any("cible" in n["say"] for n in pc["check"]["notes"]))  # given apart, not twice
        self.assertFalse((self.pdir(pid) / "work").exists() and any((self.pdir(pid) / "work").iterdir()))  # the folder of the judge is gone
        self.assertEqual(self.asks(pid), ["decide"])
        d2 = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/decide", {"verdict": "keep", "words": "bon"})
        self.assertEqual(d2["judge"]["status"], "done")  # nothing starts after it, nothing hangs on it

    def test_a_failed_judge_is_a_task_to_run_again(self):
        pid = self.composed()
        self.fake.judge = "none"
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        pc = self.piece_when(pid, "failed")
        self.assertIn("le juge n'a pas écrit de verdict", pc["judge"]["error"])
        ask = self.call("GET", f"/api/projects/{pid}")["waiting"]
        self.assertEqual([(a["kind"], a["step"], a["piece"]) for a in ask], [("decide", "decide", "v1-story"), ("job-failed", "check", "v1-story")])
        self.assertEqual(ask[1]["title"], "Relancer le juge de v1 en story")
        t = next(t for t in self.call("GET", "/api/tasks")["tasks"] if t["project"] == pid and t["kind"] == "job-failed")
        self.assertEqual(t["id"], f"{pid}:check:v1-story")
        self.fake.judge = "ok"
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/judge"))  # the same route runs it again
        self.assertEqual(self.piece_when(pid, "done")["judge"]["error"], None)
        self.assertEqual(self.asks(pid), ["decide"])

    def test_a_verdict_that_does_not_hold_is_a_failure(self):
        pid = self.composed()
        self.fake.judge = "bad"
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        self.assertIn("verdict du juge illisible", self.piece_when(pid, "failed")["judge"]["error"])
        self.assertFalse((self.pdir(pid) / "piece" / "pieces" / "v1" / "judge.json").exists())

    def test_a_new_image_drops_the_old_verdict(self):
        pid = self.composed()
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        self.piece_when(pid, "done")
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        self.assertIsNone(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")["judge"])
        self.assertFalse((self.pdir(pid) / "piece" / "pieces" / "v1" / "judge.json").exists())

    def dropped(self, meta, data=None, ctype="image/png", name="affiche.png", code=200):
        return drop(self.base, data if data is not None else png(), ctype, name, meta, code)

    def judged(self, jid, status="done"):
        return self.until(lambda: (lambda x: x if x["status"] == status else None)(self.call("GET", f"/api/judgements/{jid}")), f"judgement {status}")

    def test_a_piece_judged_on_its_own_is_kept_on_the_disk(self):
        bid = self.shared_brand()
        jg = self.dropped({"brand": bid, "brief": BRIEF})
        self.assertEqual((jg["brand"], jg["name"], jg["missing"]), (bid, "affiche", []))
        jg = self.judged(jg["id"])
        self.assertEqual(set(jg["verdict"]), HEADINGS)
        self.assertIsInstance(jg["verdict"]["brand"], list)
        d = self.home / "jugements" / jg["id"]
        self.assertEqual(sorted(x.name for x in d.iterdir() if x.is_file()), ["judge.md", "jugement.json", "page.html", "piece.png"])
        self.assertEqual((d / "piece.png").read_bytes(), png())
        self.assertIn("sa voix : franc, chaleureux, drôle", self.fake.inputs)
        self.assertIn("ses textes : ceux qu'on lit sur l'image", self.fake.inputs)
        self.assertTrue(self.call("GET", jg["image"], raw=True).startswith(b"\x89PNG"))
        self.call("GET", f"/files/_jugements/{jg['id']}/jugement.json", code=404, raw=True)
        self.call("GET", f"/files/_jugements/{jg['id']}/../marques", code=404, raw=True)
        head, page = self.fetch(f"/api/judgements/{jg['id']}/page")
        self.assertEqual(head["Content-Disposition"], f'attachment; filename="{jg["id"]}.html"')
        self.assertEqual(page, (d / "page.html").read_bytes())
        self.assertIn(b"data:image/png;base64,", page)  # whole on its own
        self.assertEqual(self.call("GET", "/api/judgements")[0]["id"], jg["id"])
        self.assertEqual(json.loads((d / "jugement.json").read_text())["verdict"], jg["verdict"])  # on the disk: a restart finds it

    def test_an_incomplete_brief_without_brand(self):
        jg = self.judged(self.dropped({"brief": {"objective": "faire goûter", "message": "c'est bon", "cta": "Au marché"}})["id"])
        v = jg["verdict"]
        self.assertEqual((v["target"]["reached"], v["target"]["why"]), ("unjudgeable", "non jugeable sur la cible : il manque la cible"))
        self.assertEqual((v["brand"], v["missing"]), (None, ["la cible"]))
        self.assertTrue(v["works"])  # the rest is judged
        prompt = self.judge_calls()[-1]["argv"][2]
        self.assertIn("The brief lacks la cible", prompt)
        self.assertIn('"brand": null', prompt)
        self.assertIn("aucune", self.fake.inputs)

    def test_a_failed_judgement_is_run_again(self):
        self.fake.judge = "none"
        jg = self.judged(self.dropped({"brief": BRIEF})["id"], "failed")
        self.assertIn("le juge n'a pas écrit de verdict", jg["error"])
        self.fetch(f"/api/judgements/{jg['id']}/page", code=409)
        self.fake.judge = "ok"
        self.wait(self.call("POST", f"/api/judgements/{jg['id']}/run"))
        self.assertTrue(self.judged(jg["id"])["verdict"]["snags"])

    def test_a_dropped_piece_is_refused_when_it_is_not_one(self):
        n = len(self.call("GET", "/api/judgements"))
        self.dropped({"brief": BRIEF}, b"<svg/>", "image/svg+xml", code=400)
        self.dropped({"brief": BRIEF}, b"GIF89a", "image/png", code=400)
        self.dropped({"brief": BRIEF}, b"", code=400)
        self.assertIn("too big", self.dropped({"brief": BRIEF}, b"\x89PNG\r\n\x1a\n" + b"0" * workflow.JUDGE_MAX, code=400)["error"])
        self.dropped({"brand": "nope", "brief": BRIEF}, code=400)
        self.dropped({"brand": "../x", "brief": BRIEF}, code=400)
        self.assertEqual(len(self.call("GET", "/api/judgements")), n)  # nothing was kept


if __name__ == "__main__":
    unittest.main()
