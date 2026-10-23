"""Acceptance tests for the brand dossier (annex C), on the fictional example and on small made-up sources.

    python3 -m unittest discover -s tests
"""

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
BK = ROOT / "scripts" / "brandkit"
EXAMPLE = ROOT / "examples" / "marrowbay"
sys.path.insert(0, str(BK))

import media  # noqa: E402
import visual  # noqa: E402
from checks import check  # noqa: E402
from fuse import iter_values  # noqa: E402
from model import evidence_id  # noqa: E402


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
        r = run("review-html", self.b, "--embed", "--no-previews", "--out", self.tmp / "standalone.html")
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


def cli(*args):
    """The command line in this process (so that media can be mocked); returns what it printed."""
    spec = importlib.util.spec_from_file_location("brandkit_cli", BK / "__main__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        mod.main([str(a) for a in args])
    return out.getvalue()


class Keep(unittest.TestCase):
    """The review's outcome: keep / discard, the logo, the measured colours. A made-up brand, local files, no network."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-keep-"))
        self.b = self.tmp / "brand"
        run("init", self.b, "--name", "Nobody")
        (self.b / "collect").mkdir(exist_ok=True)
        for n in ("screen-old.png", "screen-new.png", "logo.png"):
            (self.b / "collect" / n).write_bytes(b"not really an image")
        self.id = {"old": evidence_id("page", "https://old.example/"), "new": evidence_id("page", "https://new.example/"),
                   "s_old": evidence_id("file", "collect/screen-old.png"), "s_new": evidence_id("file", "collect/screen-new.png"),
                   "logo": evidence_id("file", "collect/logo.png"), "web": evidence_id("web_image", "https://press.example/poster.jpg")}
        shot = lambda i, w, page: {"id": i, "kind": "file", "where": w, "page": page, "note": "screenshot home"}
        write(self.tmp / "s.json", {"adapter": "inferred", "origin": "two sites", "evidence": [
            {"id": "old", "kind": "page", "where": "https://old.example/", "ownership": "official", "ownership_given_by_user": True},
            {"id": "new", "kind": "page", "where": "https://new.example/", "ownership": "official", "ownership_given_by_user": True},
            shot("s_old", "collect/screen-old.png", "https://old.example/"), shot("s_new", "collect/screen-new.png", "https://new.example/"),
            {"id": "logo", "kind": "file", "where": "collect/logo.png", "page": "https://new.example/", "note": "logo candidate, header"},
            {"id": "web", "kind": "web_image", "where": "https://press.example/poster.jpg", "ownership": "probable", "note": "poster"}],
            "values": [{"path": "colours", "item": {"hex": "#AA0000", "role": "background"}, "confidence": "high", "rank": "declared_used", "evidence": ["old", "s_old"]},
                       {"path": "logo", "item": {"file": "collect/logo.png", "format": "png", "variant": "header"}, "confidence": "medium", "rank": "rendered", "evidence": ["new", "logo"]}]})
        run("add", self.b, self.tmp / "s.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def doc(self):
        return json.loads((self.b / "brand.json").read_text())

    def ev(self):
        return {e["id"]: e for e in json.loads((self.b / "evidence.json").read_text())}

    def fake_sample(self, colours):
        return mock.patch.object(media, "sample", side_effect=lambda image, k=6: {"image": str(image), "colours": colours.get(Path(str(image)).name, [])})

    def test_ownership_decision_on_a_file_stops_it_feeding(self):
        self.assertEqual(self.doc()["colours"]["items"][0]["hex"]["value"], "#AA0000")
        run("ownership", self.b, self.id["old"], "uncertain")
        self.assertEqual(self.doc()["colours"]["items"][0]["hex"]["value"], "#AA0000")  # its screenshot still feeds it
        run("ownership", self.b, self.id["s_old"], "uncertain", "--reason", "old identity")
        self.assertEqual(self.doc()["colours"]["items"], [])
        e = self.ev()[self.id["s_old"]]
        self.assertEqual((e["ownership"], e["ownership_status"]), ("uncertain", "confirmed"))

    def test_keep_records_the_choices_and_the_logo_file(self):
        with mock.patch.object(media, "available", return_value=False):
            out = cli("keep", self.b, "--no-previews", self.id["new"], self.id["s_new"], "--logo", self.id["logo"])
        self.assertIn("colours not measured", out)
        ev = self.ev()
        self.assertEqual([ev[self.id[k]]["ownership"] for k in ("new", "s_new", "logo")], ["official"] * 3)
        self.assertEqual([ev[self.id[k]]["ownership"] for k in ("old", "s_old", "web")], ["uncertain"] * 3)
        d = self.doc()
        self.assertEqual(d["colours"]["items"], [])  # the discarded site's CSS colour is gone
        logo = d["logo"]["items"][0]
        self.assertEqual((logo["file"]["value"], logo["file"]["status"], logo["file"]["source"]["type"]), ("collect/logo.png", "confirmed", "typed"))
        decisions = json.loads((self.b / "decisions.json").read_text())
        self.assertEqual([x["reason"] for x in decisions if x["evidence"] == self.id["old"]], ["discarded in review"])
        # a later keep that leaves the site out does not discard the logo it gave
        with mock.patch.object(media, "available", return_value=False):
            cli("keep", self.b, "--no-previews", self.id["old"])
        self.assertEqual(self.ev()[self.id["logo"]]["ownership"], "official")
        self.assertEqual(self.doc()["logo"]["items"][0]["file"]["value"], "collect/logo.png")

    def test_keep_wants_ids_or_none_and_a_logo_that_is_a_file(self):
        self.assertNotEqual(run("keep", self.b, "--no-previews", ok=False).returncode, 0)
        run("keep", self.b, "--no-previews", "--none")
        self.assertEqual({e["ownership"] for e in self.ev().values()}, {"uncertain"})
        self.assertNotEqual(run("keep", self.b, "--no-previews", "--none", "--logo", self.id["web"], ok=False).returncode, 0)
        self.assertNotEqual(run("keep", self.b, "--no-previews", "ev-00000000", ok=False).returncode, 0)

    def test_keep_measures_the_kept_visuals_and_rewrites_at_each_run(self):
        reds = {"screen-new.png": [{"hex": "#102030", "share": 0.6}, {"hex": "#f0e0d0", "share": 0.4}]}
        with mock.patch.object(media, "available", return_value=True), self.fake_sample(reds):
            out = cli("keep", self.b, "--no-previews", self.id["s_new"], self.id["new"])
        self.assertIn("#102030", out)
        cols = [(it["hex"]["value"], it["role"]["value"], it["hex"]["status"], it["hex"]["source"]["origin"]) for it in self.doc()["colours"]["items"]]
        self.assertEqual([c[:3] for c in cols], [("#102030", "dominant", "to_confirm"), ("#f0e0d0", "dominant 2", "to_confirm")])
        self.assertTrue(cols[0][3].startswith("measured on the kept visuals"))
        # the site's CSS colour came from a discarded source: it does not sit next to the measured ones
        self.assertNotIn("#aa0000", [c[0] for c in cols])
        with mock.patch.object(media, "available", return_value=True), self.fake_sample({"screen-old.png": [{"hex": "#00ff00", "share": 1.0}]}):
            cli("keep", self.b, "--no-previews", self.id["s_old"])
        self.assertEqual([it["hex"]["value"] for it in self.doc()["colours"]["items"] if it["hex"]["source"]["type"] == "inferred" and it["role"]["value"].startswith("dominant")], ["#00ff00"])
        self.assertEqual(len([f for f in (self.b / "sources").glob("*kept-colours*")]), 1)

    def test_keep_samples_a_web_image_by_its_og_image_and_keeps_nothing(self):
        seen = []
        with mock.patch.object(media, "available", return_value=True), \
                mock.patch.object(media, "preview_url", side_effect=lambda x, t=4: "https://press.example/poster.jpg"), \
                mock.patch.object(media, "sample", side_effect=lambda image, k=6: seen.append(image) or {"colours": [{"hex": "#cc3300", "share": 0.5}]}):
            cli("keep", self.b, "--no-previews", self.id["web"])
        self.assertEqual(seen, ["https://press.example/poster.jpg"])
        item = self.doc()["colours"]["items"][0]
        self.assertEqual(item["hex"]["value"], "#cc3300")
        self.assertEqual(item["hex"]["evidence"], [self.id["web"]])
        web = self.ev()[self.id["web"]]
        self.assertFalse(web["kept"])
        self.assertNotIn("file", web)
        self.assertEqual(check(self.doc(), list(self.ev().values())), [])

    @unittest.skipUnless(media.available(), "ffmpeg is not installed")
    def test_keep_measures_a_real_local_image(self):
        png = self.b / "collect" / "screen-new.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x1040a0:s=32x32", "-frames:v", "1", str(png)], check=True)
        cli("keep", self.b, "--no-previews", self.id["s_new"])
        hexes = [it["hex"]["value"] for it in self.doc()["colours"]["items"]]
        self.assertTrue(hexes and media_close(hexes[0], "#1040a0"), hexes)

    def test_review_html_is_the_arbitration_page(self):
        run("review-html", self.b, "--no-previews")
        page = (self.b / "review.html").read_text()
        for k in ("old", "new", "s_old", "s_new", "web"):
            self.assertIn(f"data-id='{self.id[k]}'", page)
        self.assertNotIn(f"data-id='{self.id['logo']}'", page)  # the logo candidate is in its own section
        self.assertIn(f"name='logo' value='{self.id['logo']}'", page)
        self.assertIn("data-set='keep'", page)
        self.assertIn(f"{(BK).resolve()} keep {self.b.resolve()}", page)  # the command carries absolute paths
        self.assertNotIn("data:image", page)
        run("keep", self.b, "--no-previews", self.id["s_new"], "--logo", self.id["logo"])
        run("review-html", self.b, "--no-previews", "--lang", "fr")
        page = (self.b / "review.html").read_text()
        self.assertIn(f"data-id='{self.id['s_new']}' data-choice='keep'", page)
        self.assertIn(f"data-id='{self.id['web']}' data-choice='discard'", page)
        self.assertIn(f"value='{self.id['logo']}' checked", page)
        self.assertIn("J'écarte", page)

    def test_previews_are_hotlinked_from_og_image_never_downloaded(self):
        doc, evidence, review = json.loads((self.b / "brand.json").read_text()), list(self.ev().values()), {}
        with mock.patch.object(media, "preview_url", side_effect=lambda x, t=4: "https://cdn.example/p.jpg" if x["kind"] == "web_image" else None):
            page = visual.render_html(doc, evidence, review, self.b, self.b / "review.html", "en", previews=True)
        self.assertIn("src='https://cdn.example/p.jpg'", page)
        self.assertIn("referrerpolicy='no-referrer'", page)
        self.assertEqual([p.name for p in self.b.iterdir() if p.suffix in (".jpg", ".png")], [])


def media_close(a, b, tol=12):
    from model import hex_distance
    return hex_distance(a, b) < tol


class Previews(unittest.TestCase):
    """Reading a page's og:image, against a throwaway local server."""

    @classmethod
    def setUpClass(cls):
        pages = {"/a": b'<html><head><meta content="/img/a.jpg" property="og:image"></head></html>',
                 "/b": b'<html><head><meta name="twitter:image" content="https://cdn.example/t.png"></head></html>',
                 "/c": b"<html><head><title>nothing</title></head></html>"}

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = pages.get(self.path)
                self.send_response(200 if body else 404)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body or b"")

            def log_message(self, *a):
                pass

        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_og_image_relative_twitter_fallback_and_nothing(self):
        self.assertEqual(media.og_image(self.base + "/a", 2), self.base + "/img/a.jpg")
        self.assertEqual(media.og_image(self.base + "/b", 2), "https://cdn.example/t.png")
        self.assertIsNone(media.og_image(self.base + "/c", 2))
        self.assertIsNone(media.og_image(self.base + "/missing", 2))
        self.assertIsNone(media.og_image("http://127.0.0.1:9/", 1))

    def test_an_image_address_is_its_own_preview(self):
        self.assertEqual(media.preview_url({"where": "https://x.example/a.PNG?w=1"}), "https://x.example/a.PNG?w=1")
        self.assertIsNone(media.preview_url({"where": "collect/screen.png"}))


if __name__ == "__main__":
    unittest.main()
