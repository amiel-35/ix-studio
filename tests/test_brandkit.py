"""Acceptance tests for the brand dossier (annex C), on the fictional example and on small made-up sources.

    python3 -m unittest discover -s tests
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BK = ROOT / "scripts" / "brandkit"
EXAMPLE = ROOT / "examples" / "marrowbay"
sys.path.insert(0, str(BK))

from checks import check  # noqa: E402
from fuse import iter_values  # noqa: E402


def run(*args, ok=True):
    r = subprocess.run([sys.executable, str(BK), *map(str, args)], capture_output=True, text=True)
    if ok and r.returncode:
        raise AssertionError(r.stderr + r.stdout)
    return r


def write(path, data):
    Path(path).write_text(json.dumps(data), encoding="utf-8")
    return path


class Example(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="ixs-test-"))
        shutil.copytree(EXAMPLE / "inputs", cls.tmp / "inputs")
        shutil.copy(EXAMPLE / "build.sh", cls.tmp / "build.sh")
        # build.sh finds brandkit two folders up: rebuild the same layout
        (cls.tmp / "x" / "y").mkdir(parents=True)
        shutil.move(str(cls.tmp / "inputs"), cls.tmp / "x" / "y" / "inputs")
        shutil.move(str(cls.tmp / "build.sh"), cls.tmp / "x" / "y" / "build.sh")
        (cls.tmp / "scripts").symlink_to(ROOT / "scripts")
        cls.claude_md = cls.tmp / "x" / "y" / "CLAUDE.md"
        cls.claude_md.write_text("project rules\n")
        r = subprocess.run(["sh", str(cls.tmp / "x" / "y" / "build.sh")], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr + r.stdout
        cls.b = cls.tmp / "x" / "y" / "brand"
        cls.doc = json.loads((cls.b / "brand.json").read_text())
        cls.ev = json.loads((cls.b / "evidence.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_c1_c2_every_value_has_status_and_source(self):
        self.assertEqual(check(self.doc, self.ev), [])
        for path, v in iter_values(self.doc):
            self.assertIn("status", v, path)
            src = v["source"]
            self.assertTrue(src["type"] and src["origin"] and src["at"], path)
            if v.get("value") is not None:
                self.assertNotEqual(src["type"], "none", path)

    def test_c3_skill_wins_and_inferred_is_discarded(self):
        disc = self.doc["colours"]["discarded"]
        accent = [d for d in disc if d["value"]["hex"] == "#E07A2F"]
        self.assertEqual(len(accent), 1)
        self.assertTrue(accent[0]["conflict"])
        kept = [it["hex"]["value"] for it in self.doc["colours"]["items"] if it["look"] == "brand"]
        self.assertIn("#C8553D", kept)
        self.assertNotIn("#E07A2F", kept)
        fams = [it["family"]["value"] for it in self.doc["typography"]["items"]]
        self.assertNotIn("Helvetica Neue", fams)

    def test_c4_inferred_never_confirmed_without_the_user(self):
        for path, v in iter_values(self.doc):
            if v.get("source", {}).get("type") == "inferred" and v["status"] == "confirmed":
                self.assertIn("confirmed", v, path)
        self.assertEqual(self.doc["voice"]["address"]["status"], "to_confirm")
        self.assertEqual(self.doc["imagery"]["style"]["status"], "confirmed")

    def test_c5_empty_fields_are_ask_without_value(self):
        for path in ("audience.situation", "motion.example", "promise.signature_line"):
            sec, f = path.split(".")
            v = self.doc[sec][f]
            self.assertIn(v["status"], ("ask", "to_create"))
            self.assertIsNone(v["value"])

    def test_c8_web_images_are_never_kept(self):
        web = [e for e in self.ev if e["kind"] == "web_image"]
        self.assertEqual(len(web), 4)
        for e in web:
            self.assertFalse(e["kept"])
            self.assertNotIn("file", e)
            self.assertTrue(e["where"] and e["at"] and e["ownership"])

    def test_c9_exports_have_brand_intake_sections_and_ask_me(self):
        bmd = (self.b / "brand.md").read_text()
        for h in ("## Name and what we do", "## Audience", "## What we promote (with the real link)", "## The feeling", "## Assets", "## Never"):
            self.assertIn(h, bmd)
        mmd = (self.b / "MOTION.md").read_text()
        for h in ("## 1. Colours", "## 2. Fonts and type sizes", "## 3. Timing", "## 4. How things move", "## 5. Texture and finish", "## 6. Never", "## 7. One example"):
            self.assertIn(h, mmd)
        self.assertIn("Situation: ASK ME", bmd)
        self.assertIn("ASK ME", mmd)

    def test_c11_downstream_gets_a_status_not_a_value(self):
        r = run("get", self.b, "audience.situation", ok=False)
        self.assertEqual(r.returncode, 3)
        out = json.loads(r.stdout)
        self.assertNotIn("value", out)
        self.assertTrue(out["missing"])
        r = run("get", self.b, "voice.address")
        self.assertIn("explore only", json.loads(r.stdout)["use"])

    def test_c12_claude_md_untouched(self):
        self.assertEqual(self.claude_md.read_text(), "project rules\n")

    def test_r8_correction_drops_what_rests_on_it(self):
        self.assertEqual(self.doc["imagery"]["do"]["status"], "ask")

    def test_r10_looks_are_named_and_the_master_is_chosen(self):
        looks = {it["id"]: it for it in self.doc["looks"]["items"]}
        self.assertEqual(set(looks), {"brand", "summer-2026", "old-identity"})
        self.assertTrue(looks["brand"]["master"]["value"])
        olds = [it["hex"]["value"] for it in self.doc["colours"]["items"] if it["look"] == "old-identity"]
        self.assertEqual(sorted(olds), ["#2F5D3A", "#C9A227"])

    def test_visual_review_shows_looks_and_links_web_images(self):
        page = (self.b / "review.html").read_text()
        for look in ("brand", "summer-2026", "old-identity"):
            self.assertIn(f"id='{look}'", page)
        self.assertIn("https://foodpress.example/2026/05/marrowbay-summer", page)
        self.assertNotIn("data:image", page)  # relative links by default; web images never embedded
        r = run("review-html", self.b, "--embed", "--out", self.tmp / "standalone.html")
        self.assertIn("images embedded", r.stdout)

    def test_versions_are_kept(self):
        self.assertEqual(self.doc["meta"]["version"], 1)
        self.assertTrue((self.b / "history" / "v1" / "brand.json").exists())


class Rules(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-rules-"))
        self.b = self.tmp / "brand"
        run("init", self.b, "--name", "Nobody")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def doc(self):
        return json.loads((self.b / "brand.json").read_text())

    def test_nothing_known_means_ask_or_to_create(self):
        d = self.doc()
        self.assertEqual(d["colours"]["status"], "to_create")
        self.assertEqual(d["voice"]["register"]["status"], "ask")
        self.assertIn("colours", d["meta"]["to_create"])
        r = run("missing", self.b, "--json")
        self.assertGreaterEqual(len(json.loads(r.stdout)), 8)

    def test_r12_skill_version_change_gives_back_to_confirm(self):
        write(self.tmp / "s.json", {"adapter": "skill", "skill": {"name": "ds", "version": "1"},
                                   "values": [{"path": "colours", "item": {"hex": "#000000", "role": "text"}}]})
        run("add", self.b, self.tmp / "s.json")
        self.assertEqual(self.doc()["colours"]["items"][0]["hex"]["status"], "confirmed")
        run("skill-check", self.b, "ds", "2")
        self.assertEqual(self.doc()["colours"]["items"][0]["hex"]["status"], "to_confirm")
        self.assertIn("ds", (self.b / "review.md").read_text())

    def test_declared_but_unused_does_not_outrank_rendered(self):
        write(self.tmp / "i.json", {"adapter": "inferred", "origin": "site", "evidence": [{"id": "p", "kind": "page", "where": "https://x.example", "ownership": "official"}],
                                   "values": [{"path": "voice.register", "value": "A", "confidence": "low", "rank": "web_image", "evidence": ["p"]},
                                              {"path": "voice.register", "value": "B", "confidence": "low", "rank": "rendered", "evidence": ["p"]}]})
        run("add", self.b, self.tmp / "i.json")
        v = self.doc()["voice"]["register"]
        self.assertEqual(v["value"], "B")
        self.assertEqual(v["discarded"][0]["value"], "A")

    def test_typed_vs_skill_skill_wins(self):
        write(self.tmp / "t.json", {"adapter": "typed", "origin": "me", "values": [{"path": "colours", "item": {"hex": "#111111", "role": "text"}}]})
        write(self.tmp / "s.json", {"adapter": "skill", "skill": {"name": "ds", "version": "1"}, "values": [{"path": "colours", "item": {"hex": "#222222", "role": "text"}}]})
        run("add", self.b, self.tmp / "t.json")
        run("add", self.b, self.tmp / "s.json")
        d = self.doc()
        self.assertEqual(d["colours"]["items"][0]["hex"]["value"], "#222222")
        self.assertTrue(d["colours"]["discarded"][0]["conflict"])

    def test_web_image_with_a_file_is_refused(self):
        write(self.tmp / "w.json", {"adapter": "inferred", "origin": "search", "evidence": [{"kind": "web_image", "where": "https://x.example/a.jpg", "ownership": "probable", "file": "a.jpg"}], "values": []})
        r = run("add", self.b, self.tmp / "w.json", ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_inferred_needs_evidence_and_confidence(self):
        write(self.tmp / "x.json", {"adapter": "inferred", "origin": "guess", "values": [{"path": "voice.register", "value": "cool"}]})
        r = run("add", self.b, self.tmp / "x.json", ok=False)
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
