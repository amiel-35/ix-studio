"""End-to-end tests of the studio piece tool, on the fictional Marrowbay poster inputs. No image generator, no Chrome needed.

    python3 -m unittest discover -s tests
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ST = ROOT / "scripts" / "studio"
EXAMPLE = ROOT / "examples" / "marrowbay" / "poster"
INPUTS = ("brand.md", "brief.md", "judge.md")


def env():
    e = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CHROME")}
    e["PATH"] = os.pathsep.join(p for p in e.get("PATH", "").split(os.pathsep) if p and not (Path(p) / "codex").exists())
    return e


def run(*args, ok=True):
    r = subprocess.run([sys.executable, str(ST), *map(str, args)], capture_output=True, text=True, env=env())
    if ok and r.returncode:
        raise AssertionError(r.stderr + r.stdout)
    return r


def piece():
    d = Path(tempfile.mkdtemp(prefix="ixs-piece-"))
    for n in INPUTS:
        shutil.copy(EXAMPLE / n, d / n)
    shutil.copytree(EXAMPLE / "variants", d / "variants")
    return d


def build(d):
    for cmd in ("brand", "brief", "diverge"):
        run(cmd, d)
    run("pick", d, "v2")
    run("image", d, "--engine", "none")
    run("compose", d)
    return run("check", d)


class Flow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = piece()
        cls.out = build(cls.d)

    def test_files_and_pages(self):
        for n in ("1-brand.html", "2-brief.html", "3-divergence.html", "4-piece.html", "5-check.html", "pick.json",
                  "image.json", "piece.html", "check.json"):
            self.assertTrue((self.d / n).exists(), n)
        self.assertFalse((self.d / "image.png").exists())
        self.assertEqual(json.loads((self.d / "image.json").read_text())["engine"], "none")
        self.assertIn('width:1080px', (self.d / "piece.html").read_text())

    def test_divergence_page(self):
        h = (self.d / "3-divergence.html").read_text()
        self.assertIn("attractor", h)
        self.assertIn("picked", h)
        self.assertIn("Discover the taste of Marrowbay", h)

    def test_check_json(self):
        ck = json.loads((self.d / "check.json").read_text())
        st = {r["id"]: r["status"] for r in ck["results"]}
        self.assertEqual((st["palette"], st["fonts"], st["contrast"], st["never"]), ("pass",) * 4)
        self.assertEqual((st["image"], st["logo"]), ("warn", "warn"))
        self.assertEqual(len(ck["judge"]), 3)
        self.assertEqual(ck["judge"][0]["level"], "major")
        self.assertIn("check: 5 pass · 2 warn · 0 fail · 3 judge notes", self.out.stdout)

    def test_decide_keep_and_again(self):
        run("decide", self.d, "keep", "good")
        self.assertIn("verdict: keep", (self.d / "decision.md").read_text())
        self.assertFalse((self.d / "bans.md").exists())
        run("decide", self.d, "again", "too polite")
        self.assertIn("verdict: again", (self.d / "decision.md").read_text())
        self.assertIn('v2 "It\'s tea that got a little wild.": too polite', (self.d / "bans.md").read_text())
        self.assertIn("decision", (self.d / "5-check.html").read_text().lower())

    def test_status_and_pages(self):
        d = piece()
        self.assertIn("next: python3 scripts/studio brand ", run("status", d).stdout)
        build(d)
        self.assertIn("next: python3 scripts/studio decide", run("status", d).stdout)
        self.assertIn("5-check.html", run("pages", d).stdout)

    def test_screenshot_when_chrome(self):
        if shutil.which("google-chrome") or shutil.which("chromium") or list(Path("/opt/pw-browsers").glob("chromium*/chrome-linux*/chrome")):
            r = run("compose", self.d, ok=False)
            self.assertEqual(r.returncode, 0)


class Edges(unittest.TestCase):
    def test_auto_falls_back_to_none(self):
        d = piece()
        for cmd in ("brand", "brief", "diverge"):
            run(cmd, d)
        run("pick", d, "v1")
        r = run("image", d)
        self.assertEqual(r.returncode, 0)
        self.assertIn("No image generator available", r.stdout)
        self.assertFalse((d / "image.png").exists())

    def test_user_image_kept(self):
        d = piece()
        for cmd in ("brand", "brief", "diverge"):
            run(cmd, d)
        run("pick", d, "v1")
        (d / "image.png").write_bytes(b"\x89PNG not really")
        r = run("image", d, "--engine", "none")
        self.assertIn("kept", r.stdout)
        self.assertEqual((d / "image.png").read_bytes(), b"\x89PNG not really")
        run("compose", d)
        self.assertIn('class="bg"', (d / "piece.html").read_text())

    def test_bad_variant_names_file_and_key(self):
        d = piece()
        v = json.loads((d / "variants" / "v3.json").read_text())
        del v["why"]
        (d / "variants" / "v3.json").write_text(json.dumps(v))
        r = run("diverge", d, ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("v3.json", r.stderr)
        self.assertIn("'why'", r.stderr)

    def test_one_variant_is_not_a_divergence(self):
        d = piece()
        for n in ("v2", "v3", "v4"):
            (d / "variants" / f"{n}.json").unlink()
        self.assertEqual(run("diverge", d, ok=False).returncode, 2)

    def test_missing_brand_key(self):
        d = piece()
        (d / "brand.md").write_text("- name: X\n- accent: #ff0000\n")
        r = run("brand", d, ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("background", r.stderr)

    def test_contrast_fail(self):
        d = piece()
        build(d)
        h = (d / "piece.html").read_text()
        h = re.sub(r"(\.hl\{[^}]*?)color:#1e2a24", r"\1color:#f4efe6", h)
        (d / "piece.html").write_text(h)
        run("check", d)
        ck = json.loads((d / "check.json").read_text())
        self.assertEqual({r["id"]: r["status"] for r in ck["results"]}["contrast"], "fail")
        self.assertEqual(ck["summary"]["fail"], 1)

    def test_never_word_fails(self):
        d = piece()
        for cmd in ("brand", "brief", "diverge"):
            run(cmd, d)
        run("pick", d, "v2", "--headline", "The detox you can drink")
        run("compose", d)
        run("check", d)
        ck = json.loads((d / "check.json").read_text())
        self.assertEqual({r["id"]: r["status"] for r in ck["results"]}["never"], "fail")
        self.assertIn("detox", (d / "3-divergence.html").read_text())

    def test_off_palette_colour_fails(self):
        d = piece()
        build(d)
        h = (d / "piece.html").read_text().replace("</style>", ".x{color:#123456}\n</style>")
        (d / "piece.html").write_text(h)
        run("check", d)
        ck = json.loads((d / "check.json").read_text())
        self.assertEqual({r["id"]: r["status"] for r in ck["results"]}["palette"], "fail")

    def test_from_dossier(self):
        d = Path(tempfile.mkdtemp(prefix="ixs-dz-"))
        r = run("brand", d, "--from-dossier", ROOT / "examples" / "marrowbay" / "brand")
        t = (d / "brand.md").read_text()
        self.assertIn("name: Marrowbay Ferments", t)
        self.assertIn("background: #F4EFE6", t)
        self.assertIn("headline font: Fraunces", t)
        self.assertIn("# missing:", t)
        self.assertTrue((d / "1-brand.html").exists(), r.stdout)
        self.assertEqual(run("brand", d, "--from-dossier", ROOT / "examples" / "marrowbay" / "brand", ok=False).returncode, 2)
        run("brand", d, "--from-dossier", ROOT / "examples" / "marrowbay" / "brand", "--force")


if __name__ == "__main__":
    unittest.main()
