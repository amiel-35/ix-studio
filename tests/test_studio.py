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
    e["STUDIO_OFFLINE"] = "1"
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
        self.assertIn('width:1800px', (self.d / "piece.html").read_text())

    def test_divergence_page(self):
        h = (self.d / "3-divergence.html").read_text()
        self.assertIn("attractor", h)
        self.assertIn("picked", h)
        self.assertIn("Discover the taste of Marrowbay", h)

    def test_check_json(self):
        ck = json.loads((self.d / "check.json").read_text())
        st = {r["id"]: r["status"] for r in ck["results"]}
        self.assertEqual((st["palette"], st["fonts"], st["contrast"], st["never"]), ("pass",) * 4)
        self.assertEqual((st["image"], st["logo"], st["headline colour"]), ("warn", "warn", "pass"))
        self.assertEqual(len(ck["judge"]), 4)
        self.assertEqual(ck["judge"][0]["level"], "minor")
        self.assertIn("check: 6 pass · 2 warn · 0 fail · 0 major judge notes (4 notes)", self.out.stdout)

    def test_decide_keep_and_again(self):
        d = piece()
        build(d)
        run("decide", d, "keep", "good")
        self.assertIn("verdict: keep", (d / "decision.md").read_text())
        self.assertFalse((d / "bans.md").exists())
        run("decide", d, "again", "too polite")
        self.assertIn("verdict: again", (d / "decision.md").read_text())
        self.assertIn('v2 "It\'s tea that got a little wild.": too polite', (d / "bans.md").read_text())
        for n in ("pick.json", "piece.html", "check.json"):
            self.assertFalse((d / n).exists(), n)
        self.assertIn("write new variants", run("status", d).stdout)

    def test_status_and_pages(self):
        d = piece()
        self.assertRegex(run("status", d).stdout, r"next: python3 \S*scripts/studio brand ")
        build(d)
        self.assertRegex(run("status", d).stdout, r"next: python3 \S*scripts/studio decide")
        self.assertNotIn(str(ST), run("status", d).stdout)
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
        h = re.sub(r"(\.hl\{[^}]*?)color:#c8553d", r"\1color:#f4efe6", h)
        (d / "piece.html").write_text(h)
        run("check", d)
        ck = json.loads((d / "check.json").read_text())
        self.assertEqual({r["id"]: r["status"] for r in ck["results"]}["contrast"], "fail")
        self.assertEqual(ck["summary"]["fail"], 2)

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

    def test_hand_path(self):
        d = piece()
        shutil.rmtree(d / "variants")
        for cmd in ("brand", "brief"):
            run(cmd, d)
        self.assertEqual(run("compose", d, ok=False).returncode, 2)
        self.assertEqual(run("image", d, "--engine", "none", ok=False).returncode, 2)
        run("compose", d, "--headline", "Drink it slow", "--subline", "Tea, aged.", "--layout", "bottom")
        self.assertIn('data-layout="overlay-bottom"', (d / "piece.html").read_text())
        self.assertIn("Tea, aged.", (d / "piece.html").read_text())
        run("check", d)
        self.assertEqual(json.loads((d / "check.json").read_text())["headline"], "Drink it slow")
        run("decide", d, "keep", "fine")
        self.assertIn("variant: hand", (d / "decision.md").read_text())
        self.assertIn("done", run("status", d).stdout)

    def test_check_headline_forms_and_missing(self):
        d = piece()
        build(d)
        h = (d / "piece.html").read_text().replace('class="hl"', "class='x hl'")
        (d / "piece.html").write_text(h)
        run("check", d)
        st = {r["id"]: r for r in json.loads((d / "check.json").read_text())["results"]}
        self.assertEqual(st["length"]["status"], "pass")
        (d / "piece.html").write_text(h.replace("hl", "zz"))
        run("check", d)
        st = {r["id"]: r for r in json.loads((d / "check.json").read_text())["results"]}
        self.assertEqual((st["length"]["status"], st["never"]["status"]), ("fail", "fail"))
        self.assertIn("headline not found", st["never"]["say"])

    def test_never_splits_on_commas(self):
        d = piece()
        t = (d / "brand.md").read_text()
        (d / "brand.md").write_text(re.sub(r"(?im)^(- )?never:.*$", "never: alpha, beta; gamma", t))
        run("brand", d)
        sys.path.insert(0, str(ST))
        from files import load_brand
        self.assertEqual(load_brand(d)["never"], ["alpha", "beta", "gamma"])

    def test_bad_font_name(self):
        d = piece()
        (d / "brand.md").write_text((d / "brand.md").read_text() + '\nheadline font: Evil"><script>\n')
        r = run("brand", d, ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("headline font", r.stderr)

    def test_image_stale_after_new_pick_and_force_keeps_old(self):
        d = piece()
        for cmd in ("brand", "brief", "diverge"):
            run(cmd, d)
        run("pick", d, "v1")
        (d / "image.png").write_bytes(b"old")
        (d / "image.json").write_text(json.dumps({"engine": "openai", "variant": "v1", "prompt": "p"}))
        run("pick", d, "v2")
        self.assertIn("kept", run("image", d, "--variant", "v1", "--engine", "none").stdout)
        r = run("image", d, "--engine", "none")  # stale: regenerate, which fails and keeps the old file
        self.assertNotIn("already there", r.stdout)
        self.assertIn("is kept", r.stdout)
        self.assertEqual((d / "image.png").read_bytes(), b"old")
        run("compose", d)
        self.assertIn("warning: the image was drawn for v1", run("compose", d).stdout)
        self.assertIn("rerun compose and check", r.stdout)


def kv(d, name, **changes):
    t = (d / name).read_text()
    for k, v in changes.items():
        k = k.replace("_", " ")
        t = re.sub(rf"(?im)^(- )?{k}:.*\n?", "", t).rstrip("\n") + (f"\n- {k}: {v}\n" if v is not None else "\n")
    (d / name).write_text(t)


def prep(**brand):
    d = piece()
    kv(d, "brand.md", **brand)
    for cmd in ("brand", "brief", "diverge"):
        run(cmd, d)
    run("pick", d, "v2")
    return d


def results(d):
    return {r["id"]: r for r in json.loads((d / "check.json").read_text())["results"]}


def sized(d, n):
    (d / "image.png").write_bytes((EXAMPLE / "source" / "still-life.png").read_bytes())
    return d


class Formats(unittest.TestCase):
    def fmt(self, f, ok=True):
        d = piece()
        kv(d, "brief.md", format=f)
        return run("brief", d, ok=ok)

    def test_named_and_free(self):
        self.assertIn("poster-3x2 1800x1200", self.fmt("poster-3x2").stdout)
        self.assertIn("linkedin 1200x627", self.fmt("linkedin").stdout)
        self.assertIn("1600x900", self.fmt("1600x900").stdout)

    def test_bad_free_size(self):
        for f in ("1600x", "100x900", "5000x900", "wide"):
            r = self.fmt(f, ok=False)
            self.assertEqual(r.returncode, 2, f)
            self.assertIn("poster-3x2", r.stderr)
            self.assertIn("WxH", r.stderr)


class Layouts(unittest.TestCase):
    def test_each_layout_with_and_without_image(self):
        for fmt in ("poster-3x2", "post-4x5"):
            for lay in ("side", "stack", "ground", "overlay-top", "overlay-bottom"):
                for img in (False, True):
                    d = prep(logo_position="top-left")
                    kv(d, "brief.md", format=fmt)
                    run("brief", d)
                    if img:
                        sized(d, 0)
                    run("compose", d, "--layout", lay)
                    run("check", d)
                    h = (d / "piece.html").read_text()
                    want = "stack" if lay == "side" and fmt == "post-4x5" else lay
                    self.assertIn(f'<body data-layout="{want}">', h)
                    self.assertEqual(('class="bg"' in h), img)
                    self.assertEqual(results(d)["palette"]["status"], "pass", (fmt, lay, img))
                    for c in ("hl", "sub", "cta", "blk", "logo"):
                        self.assertIn(c, h)
                    if lay.startswith("overlay"):
                        self.assertIn("linear-gradient", h)
                        self.assertEqual(results(d)["contrast"]["status"], "warn")
                        self.assertIn("the image under it decides", results(d)["contrast"]["say"])

    def test_alias_and_diverge_warning(self):
        d = prep()
        run("compose", d, "--layout", "top")
        self.assertIn('data-layout="overlay-top"', (d / "piece.html").read_text())
        vs = [json.loads(p.read_text()) for p in sorted((d / "variants").glob("*.json"))]
        self.assertEqual(vs[1]["layout"], "side")
        self.assertNotIn("can diverge", run("diverge", d).stdout)
        for p in (d / "variants").glob("*.json"):
            v = json.loads(p.read_text())
            v["layout"] = "center"
            p.write_text(json.dumps(v))
        self.assertIn("warning: all variants use ground: the layout can diverge too", run("diverge", d).stdout)
        self.assertIn("ground", (d / "3-divergence.html").read_text())

    def test_bad_layout(self):
        d = piece()
        p = d / "variants" / "v1.json"
        p.write_text(json.dumps({**json.loads(p.read_text()), "layout": "middle"}))
        self.assertIn("overlay-top", run("diverge", d, ok=False).stderr)


class Logo(unittest.TestCase):
    def test_placeholder_positions_and_check(self):
        for pos in ("bottom-right", "bottom-left", "top-right", "top-left"):
            d = prep(logo_position=pos)
            run("compose", d)
            run("check", d)
            h = (d / "piece.html").read_text()
            self.assertIn('class="logo ph">logo<', h)
            self.assertIn(("left" if pos.endswith("left") else "right") + ":", re.search(r"\.logo\{[^}]*\}", h).group(0))
            self.assertEqual(results(d)["logo"]["status"], "warn")
            self.assertIn("logo placeholder", results(d)["logo"]["say"])

    def test_file_logo_and_bad_position(self):
        d = prep()
        (d / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>")
        kv(d, "brand.md", logo="logo.svg")
        run("compose", d)
        run("check", d)
        self.assertEqual(results(d)["logo"]["status"], "pass")
        kv(d, "brand.md", logo_position="middle")
        r = run("brand", d, ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("logo position", r.stderr)

    def test_no_logo_sets_the_name(self):
        d = prep(logo=None)
        run("compose", d)
        self.assertIn('class="sig"', (d / "piece.html").read_text())


class HeadlineColour(unittest.TestCase):
    def hl(self, d):
        return re.search(r"\.hl\{[^}]*?;color:(#\w+)", (d / "piece.html").read_text()).group(1)

    def test_used_and_checked(self):
        d = prep()
        run("compose", d)
        run("check", d)
        self.assertEqual(self.hl(d), "#c8553d")
        self.assertEqual(results(d)["headline colour"]["status"], "pass")

    def test_fallback_when_unreadable(self):
        d = prep()
        kv(d, "brand.md", headline_colour="#F4EFE6")
        run("compose", d)
        self.assertEqual(self.hl(d), "#1e2a24")
        run("check", d)
        r = results(d)["headline colour"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("#f4efe6", r["say"])
        self.assertIn("unreadable on", r["say"])

    def test_check_fails_on_wrong_colour(self):
        d = prep()
        run("compose", d)
        (d / "piece.html").write_text((d / "piece.html").read_text().replace("color:#c8553d", "color:#1e2a24", 1))
        run("check", d)
        self.assertEqual(results(d)["headline colour"]["status"], "fail")

    def test_bad_hex(self):
        d = prep()
        kv(d, "brand.md", headline_colour="red")
        self.assertIn("headline colour", run("brand", d, ok=False).stderr)


class Never(unittest.TestCase):
    def test_glued_character_fails(self):
        d = prep()
        run("pick", d, "v2", "--headline", "Tea\u2014a little wild")
        run("compose", d)
        run("check", d)
        self.assertEqual(results(d)["never"]["status"], "fail")
        self.assertIn("\u2014", results(d)["never"]["say"])
        self.assertIn("\u2014", (d / "3-divergence.html").read_text())

    def test_exclamation_glued(self):
        d = prep()
        run("pick", d, "v2", "--headline", "Wild!")
        run("compose", d)
        run("check", d)
        self.assertEqual(results(d)["never"]["status"], "fail")

    def test_prose_is_not_verifiable(self):
        d = prep(never="detox; a tone that sounds like a pharmacy leaflet")
        run("compose", d)
        run("check", d)
        r = results(d)["never"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("not verifiable: a tone that sounds like a pharmacy leaflet", r["say"])

    def test_never_show_parsed(self):
        d = prep(never_show="smiling people; a glass held to camera")
        sys.path.insert(0, str(ST))
        from files import load_brand
        self.assertEqual(load_brand(d)["never_show"], ["smiling people", "a glass held to camera"])
        self.assertIn("a glass held to camera", (d / "1-brand.html").read_text())


class Summary(unittest.TestCase):
    def test_counts_majors(self):
        d = prep()
        (d / "judge.md").write_text("- [major] a\n- [major] b\n- [minor] c\n- d\n")
        run("compose", d)
        out = run("check", d).stdout
        self.assertIn("2 major judge notes (4 notes)", out)
        ck = json.loads((d / "check.json").read_text())
        self.assertEqual((ck["summary"]["major"], ck["summary"]["judge"]), (2, 4))
        self.assertIn("2 major judge notes", (d / "5-check.html").read_text())
        run("check", d, "--lang", "fr")
        self.assertIn("2 notes majeures du juge", (d / "5-check.html").read_text())

    def test_status_legend(self):
        self.assertIn("x = present, - = not yet", run("status", piece()).stdout)


if __name__ == "__main__":
    unittest.main()
