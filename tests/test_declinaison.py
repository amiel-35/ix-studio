"""A piece declined on its own: a piece dropped with, if one wants, what it says and its brand, and the formats checked; one declination per format,
each kept or sent back, the kept ones downloaded.

The real backend runs the repository's tools for real, offline; the agent (`claude -p`) and the image are the fake runner of test_backend_studio.
Nothing here calls claude, codex or the network.

    python3 -m unittest discover -s tests
"""

import io
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
import workflow  # noqa: E402
from backend_stub import StubBackend  # noqa: E402
from backend_studio import Result  # noqa: E402
from test_backend_studio import Base, Fake, png  # noqa: E402

DECLINED = {"headline": "Acide, puis doux, puis plus rien.", "subline": "Au marché samedi", "image_prompt": "Un verre de kombucha sur une table de marché, aucun texte.",
            "layout": "stack", "ground": "background", "background": "#f4efe6", "text": "#1e2a24", "why": "En hauteur, le titre passe au-dessus de l'image."}


def drop(base, data, ctype="image/png", name="affiche.png", meta=None, code=200):
    """A piece dropped to be declined: the file is the body, what comes with it the X-Judge header (JSON, URL-encoded)."""
    head = {"Content-Type": ctype, "X-Filename": name}
    if meta is not None:
        head["X-Judge"] = urllib.parse.quote(meta if isinstance(meta, str) else json.dumps(meta))
    req = urllib.request.Request(base + "/api/declinaisons", method="POST", data=data, headers=head)
    try:
        with urllib.request.urlopen(req) as r:
            got, out = r.status, json.loads(r.read())
    except urllib.error.HTTPError as err:
        got, out = err.code, json.loads(err.read())
        err.close()
    assert got == code, (got, out)
    return out


class Meta(unittest.TestCase):
    def test_what_comes_with_the_piece_is_checked(self):
        m = workflow.decline_meta(json.dumps({"name": " Affiche ", "words": "Acide.\nAu marché", "formats": ["story", "post-1x1", "story"]}))
        self.assertEqual(m, {"name": "Affiche", "brand": None, "words": "Acide. Au marché", "formats": ["post-1x1", "story"]})  # the order of FORMATS, each once
        for bad in ("{oops", "[]", {"formats": []}, {"formats": ["film"]}, {}, {"formats": "story"}, {"formats": ["story"], "brand": "../x"}):
            with self.assertRaises(ValueError):
                workflow.decline_meta(bad if isinstance(bad, str) else json.dumps(bad))


class StubDecline(unittest.TestCase):
    """The simulated studio: one fixed picture per format, through the same routes."""

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

    def call(self, method, path, body=None, code=200, raw=False):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                got, data = r.status, r.read()
        except urllib.error.HTTPError as err:
            got, data = err.code, err.read()
            err.close()
        out = data if raw else json.loads(data)
        self.assertEqual(got, code, out)
        return out

    def done(self, did):
        for _ in range(200):
            dc = self.call("GET", f"/api/declinaisons/{did}")
            if dc["status"] == "done":
                return dc
            time.sleep(0.02)
        self.fail("never declined")

    def test_one_declination_per_format_kept_or_sent_back(self):
        dc = drop(self.base, png(), meta={"brand": "marrowbay-ferments", "words": "Acide, puis doux. Au marché samedi", "formats": ["story", "post-1x1"]})
        self.assertEqual((dc["status"], dc["brand_name"], dc["name"]), ("running", "Marrowbay Ferments", "affiche"))
        self.assertTrue(dc["source"].startswith("data:image/png;base64,"))
        self.assertTrue(any(j.get("declinaison") == dc["id"] and j["kind"] == "decline" for j in self.call("GET", "/api/tasks")["jobs"]))
        self.call("GET", f"/api/declinaisons/{dc['id']}/download", code=409, raw=True)  # nothing kept yet
        dc = self.done(dc["id"])
        self.assertEqual([(p["format"], p["size"], p["status"]) for p in dc["pieces"]], [("post-1x1", [1080, 1080], "done"), ("story", [1080, 1920], "done")])
        self.assertTrue(all(p["image"] for p in dc["pieces"]))
        self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/story/decide", {"verdict": "again", "words": ""}, code=400)  # say what is wrong
        dc = self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/story/decide", {"verdict": "again", "words": "le titre est coupé"})
        self.assertEqual(dc["pieces"][1]["status"], "running")
        self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/story/decide", {"verdict": "keep"}, code=409)  # not drawn again yet
        dc = self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/post-1x1/decide", {"verdict": "keep"})
        self.assertEqual(dc["pieces"][0]["decision"]["verdict"], "keep")
        with urllib.request.urlopen(self.base + f"/api/declinaisons/{dc['id']}/download") as r:
            self.assertIn("attachment", r.headers["Content-Disposition"])
            self.assertEqual(zipfile.ZipFile(io.BytesIO(r.read())).namelist(), [f"{dc['id']}-post-1x1.png"])
        rows = self.call("GET", "/api/declinaisons")
        self.assertEqual((rows[0]["id"], set(rows[0])), (dc["id"], {"id", "name", "brand", "brand_name", "status", "at"}))
        self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/linkedin/decide", {"verdict": "keep"}, code=404)
        self.call("GET", "/api/declinaisons/nope", code=404)

    def test_a_dropped_piece_is_checked(self):
        ok = {"formats": ["story"]}
        drop(self.base, b"<svg/>", "image/svg+xml", "x.svg", ok, code=400)
        drop(self.base, b"GIF89a", "image/png", "x.png", ok, code=400)
        drop(self.base, png(), meta={"formats": []}, code=400)
        drop(self.base, png(), meta={"formats": ["film"]}, code=400)
        drop(self.base, png(), meta={"brand": "nope", **ok}, code=400)
        self.assertIn("too big", drop(self.base, b"\x89PNG\r\n\x1a\n" + b"0" * workflow.JUDGE_MAX, meta=ok, code=400)["error"])


class DeclineFake(Fake):
    """The runner of test_backend_studio, with the agent that declines a piece: it writes declinaison.json, or nothing."""

    def __init__(self):
        super().__init__()
        self.decline = "ok"  # ok, or none (the agent writes nothing)
        self.prompts = []

    def claude(self, argv, cwd):
        if "./declinaison.json" not in argv[2]:
            return super().claude(argv, cwd)
        self.prompts.append(argv[2])
        if self.decline == "none":
            return Result(1, "", "the agent gave up")
        (Path(cwd) / "declinaison.json").write_text(json.dumps(DECLINED, ensure_ascii=False), encoding="utf-8")
        return Result(0, "declinaison.json\n", "")


class RealDecline(Base):
    """The real studio: one agent per format, then pick, image, compose and check of scripts/studio, in a folder of its own."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.fake = cls.backend.runner = DeclineFake()

    def setUp(self):
        super().setUp()
        self.fake.decline = "ok"

    def until(self, did, status="done"):
        for _ in range(500):
            dc = self.call("GET", f"/api/declinaisons/{did}")
            if dc["status"] != "running":
                return dc
            time.sleep(0.02)
        self.fail("never declined")

    def test_a_piece_declined_on_its_own_is_kept_on_the_disk(self):
        dc = drop(self.base, png(), meta={"words": "Acide, puis doux. Au marché samedi", "formats": ["post-1x1", "linkedin"]})
        dc = self.until(dc["id"])
        self.assertEqual([(p["format"], p["status"], p["error"]) for p in dc["pieces"]], [("post-1x1", "done", None), ("linkedin", "done", None)])
        d = self.home / "declinaisons" / dc["id"]
        self.assertEqual((d / "source.png").read_bytes(), png())
        self.assertIn("Acide, puis doux. Au marché samedi", self.fake.prompts[-1])
        self.assertIn("./source.png", self.fake.prompts[-1])
        for f in ("post-1x1", "linkedin"):
            self.assertTrue((d / f / "piece.png").is_file())
            self.assertIn(f"format: {f}", (d / f / "brief.md").read_text())
            self.assertIn("../source.png", (d / f / "references.md").read_text())  # the piece dropped is the reference
            brand = (d / f / "brand.md").read_text()
            self.assertIn("- background: #f4efe6 (à confirmer: lue sur la pièce de départ)", brand)  # no brand: the colours read on the piece
            self.assertIn("layout: stack", (d / f / "brief.md").read_text())  # the layout the agent chose for the format
            self.assertTrue((d / f / "check.json").is_file())
        self.assertTrue(self.call("GET", dc["pieces"][0]["image"], raw=True).startswith(b"\x89PNG"))
        self.assertTrue(self.call("GET", dc["source"], raw=True).startswith(b"\x89PNG"))
        self.call("GET", f"/files/_declinaisons/{dc['id']}/declinaison.json", code=404, raw=True)
        self.call("GET", f"/files/_declinaisons/{dc['id']}/post-1x1/brief.md", code=404, raw=True)
        self.fetch(f"/api/declinaisons/{dc['id']}/download", code=409)
        self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/linkedin/decide", {"verdict": "keep"})
        head, data = self.fetch(f"/api/declinaisons/{dc['id']}/download")
        self.assertEqual(head["Content-Disposition"], f'attachment; filename="{dc["id"]}.zip"')
        self.assertEqual(zipfile.ZipFile(io.BytesIO(data)).namelist(), [f"{dc['id']}-linkedin.png"])
        n = len(self.fake.prompts)
        again = self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/post-1x1/decide", {"verdict": "again", "words": "le titre est trop petit"})
        self.assertEqual(again["pieces"][0]["status"], "running")
        self.assertEqual(self.until(dc["id"])["pieces"][0]["status"], "done")
        self.assertIn("le titre est trop petit", self.fake.prompts[n])
        self.assertEqual(json.loads((d / "declinaison.json").read_text())["decisions"], {"linkedin": {"verdict": "keep", "words": ""}})  # a restart finds it
        self.assertEqual(self.call("GET", "/api/declinaisons")[0]["id"], dc["id"])

    def test_with_a_brand_its_dossier_gives_the_brand(self):
        bid = self.shared_brand()
        dc = self.until(drop(self.base, png(), meta={"brand": bid, "formats": ["story"]})["id"])
        self.assertEqual((dc["brand"], dc["pieces"][0]["status"]), (bid, "done"))
        brand = (self.home / "declinaisons" / dc["id"] / "story" / "brand.md").read_text()
        self.assertIn("- name: Marrowbay Ferments", brand)
        self.assertNotIn("- background: #f4efe6 (à confirmer", brand)  # the brand's own colour; what its dossier lacks is read on the piece
        self.assertIn("Its words are the ones you read on the image", self.fake.prompts[-1])

    def test_a_failure_is_said_and_run_again(self):
        self.fake.decline = "none"
        dc = self.until(drop(self.base, png(), meta={"formats": ["story"]})["id"])
        self.assertEqual(dc["pieces"][0]["status"], "failed")
        self.assertIn("l'agent n'a pas écrit la déclinaison", dc["pieces"][0]["error"])
        self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/story/decide", {"verdict": "keep"}, code=409)
        self.fake.decline = "ok"
        self.call("POST", f"/api/declinaisons/{dc['id']}/pieces/story/decide", {"verdict": "again"})  # a failed one is run again, no words needed
        self.assertEqual(self.until(dc["id"])["pieces"][0]["status"], "done")

    def test_a_dropped_piece_is_refused_when_it_is_not_one(self):
        n = len(self.call("GET", "/api/declinaisons"))
        drop(self.base, b"GIF89a", "image/png", meta={"formats": ["story"]}, code=400)
        drop(self.base, png(), meta={"formats": ["film"]}, code=400)
        drop(self.base, png(), meta={"brand": "nope", "formats": ["story"]}, code=400)
        self.assertEqual(len(self.call("GET", "/api/declinaisons")), n)  # nothing was kept


if __name__ == "__main__":
    unittest.main()
