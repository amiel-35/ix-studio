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
        self.assertEqual(len(ck["judge"]), 5)
        self.assertEqual(ck["judge"][0]["level"], "minor")
        self.assertIn("check: 9 pass · 2 warn · 0 fail · 0 major judge notes (5 notes)", self.out.stdout)

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
        self.assertIn("warning: v1, v2, v3, v4 share the layout ground: the layout can diverge too", run("diverge", d).stdout)
        self.assertIn("ground", (d / "3-divergence.html").read_text())

    def test_bad_layout(self):
        d = piece()
        p = d / "variants" / "v1.json"
        p.write_text(json.dumps({**json.loads(p.read_text()), "layout": "middle"}))
        self.assertIn("overlay-top", run("diverge", d, ok=False).stderr)


class SquareStack(unittest.TestCase):
    def test_full_width_text_whole_image_zone_ratio(self):
        d = prep()
        kv(d, "brief.md", format="post-1x1")
        run("brief", d)
        run("image", d, "--engine", "none")
        self.assertIn("Format 1080x626, ratio 16:9, for the image zone of a 1080x1080 post-1x1 poster", json.loads((d / "image.json").read_text())["prompt"])
        sized(d, 0)
        run("compose", d, "--layout", "stack")
        h = (d / "piece.html").read_text()
        self.assertIn("object-fit:contain", h)
        self.assertRegex(h, r"\.blk\{[^}]*padding:\d+px 56px \d+px 56px;")
        self.assertGreater(int(re.search(r"\.hl\{[^}]*font-size:(\d+)px", h).group(1)), 47)  # 47 with the old side padding


    def test_long_headline_grows_text_zone(self):
        """Accroche de 80 caractères, sans logo : l'ancien rendu tenait à 26 px ; la zone de texte grandit, l'image rétrécit."""
        sys.path.insert(0, str(ST))
        from compose import wrap_lines
        head = "Slow fermented vegetables from a small kitchen, packed by hand every single week"
        d = prep(logo="none")
        kv(d, "brief.md", format="post-1x1")
        run("brief", d)
        run("image", d, "--engine", "none")
        sized(d, 0)
        run("compose", d, "--layout", "stack", "--headline", head)
        h = (d / "piece.html").read_text()
        size = int(re.search(r"\.hl\{[^}]*font-size:(\d+)px", h).group(1))
        self.assertGreaterEqual(size, 1.5 * 26)
        self.assertGreater(wrap_lines(head, size, 1080 - 112), 1)
        self.assertLess(int(re.search(r"\.bg\{[^}]*height:(\d+)px", h).group(1)), 626)


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


class Round3(unittest.TestCase):
    def test_hierarchy_warns_and_check(self):
        d = prep()
        kv(d, "brief.md", format="linkedin")
        r = run("compose", d, "--layout", "stack", "--headline", "Tea that got a little wild again",
                "--subline", "Brewed in a harbour town and poured anywhere you like to be, with friends, family, neighbours and the odd stranger met at the market on a sunny morning")
        self.assertRegex(r.stdout, r"warning: headline \d+px is under 1\.4x the subline \d+px: try the layout side")
        run("check", d)
        self.assertEqual(results(d)["hierarchy"]["status"], "fail")
        h = (d / "piece.html").read_text()
        for sz, want in ((30, "warn"), (20, "pass")):
            (d / "piece.html").write_text(re.sub(r"(\.hl\{[^}]*font-size:)\d+px", r"\g<1>40px", re.sub(r"(\.sub\{[^}]*font-size:)\d+px", rf"\g<1>{sz}px", h)))
            run("check", d)
            self.assertEqual(results(d)["hierarchy"]["status"], want)

    def test_orphans_and_slogan_one_line(self):
        d = prep()
        run("compose", d, "--headline", "Boire le thé sauvage")
        h = (d / "piece.html").read_text()
        self.assertIn("Boire le\xa0thé\xa0sauvage", h)
        self.assertIn("text-wrap:balance", h)
        self.assertIn("white-space:nowrap", re.search(r"\.slogan\{[^}]*\}", h).group(0))
        run("check", d)
        self.assertEqual(results(d)["never"]["status"], "pass")

    def test_pick_subline(self):
        d = piece()
        for cmd in ("brand", "brief", "diverge"):
            run(cmd, d)
        self.assertIn("with subline 'Only this.'", run("pick", d, "v2", "--subline", "Only this.").stdout)
        run("compose", d)
        self.assertIn('<p class="sub">Only this.</p>', (d / "piece.html").read_text())

    def test_cta_repeats_subline(self):
        d = prep()
        run("compose", d, "--subline", "Find us at the market on Saturday")
        run("check", d)
        self.assertEqual(results(d)["cta"]["status"], "warn")
        kv(d, "brief.md", cta="Visit example.org")
        run("compose", d, "--subline", "Poured fresh, example.org")
        run("check", d)
        self.assertEqual(results(d)["cta"]["status"], "warn")
        run("compose", d, "--subline", "Poured anywhere")
        run("check", d)
        self.assertEqual(results(d)["cta"]["status"], "pass")

    def test_decide_again_archives_variants(self):
        d = piece()
        build(d)
        self.assertIn("variants/round-1", run("decide", d, "again", "no").stdout)
        self.assertEqual(len(list((d / "variants").glob("*.json"))), 0)
        self.assertEqual(len(list((d / "variants" / "round-1").glob("*.json"))), 4)
        self.assertIn("write new variants", run("status", d).stdout)
        self.assertIn("need at least 2", run("diverge", d, ok=False).stderr)
        h = piece()  # a piece written by hand has no variants to archive
        shutil.rmtree(h / "variants")
        run("compose", h, "--headline", "Tea, by hand")
        run("check", h)
        self.assertNotIn("round-", run("decide", h, "again", "no").stdout)


if __name__ == "__main__":
    unittest.main()


SLOGAN = "Brewed slowly. Drunk quickly."
DOSSIER = ROOT / "examples" / "marrowbay" / "brand"


def slogan_el(d):
    m = re.search(r'<p class="slogan">(.*?)</p>', (d / "piece.html").read_text())
    return m and m.group(1)


class Slogan(unittest.TestCase):
    def test_parsed_and_on_every_layout_and_logo_kind(self):
        sys.path.insert(0, str(ST))
        from files import load_brand
        self.assertEqual(load_brand(EXAMPLE)["slogan"], SLOGAN)
        for kind in ("placeholder", "file", None):
            for lay in ("side", "stack", "ground", "overlay-top", "overlay-bottom"):
                for pos in ("bottom-right", "top-left"):
                    d = prep(logo_position=pos)
                    if kind == "file":
                        (d / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>")
                    kv(d, "brand.md", logo={"file": "logo.svg", "placeholder": "placeholder"}.get(kind))
                    run("compose", d, "--layout", lay)
                    run("check", d)
                    self.assertEqual(slogan_el(d), SLOGAN, (kind, lay, pos))
                    self.assertEqual(results(d)["palette"]["status"], "pass", (kind, lay, pos))
                    self.assertEqual(results(d)["slogan"]["status"], "pass")
                    h = (d / "piece.html").read_text()
                    self.assertEqual(".blk~.slogan{position:absolute" in h, bool(kind))
        d = prep(logo=None)
        run("compose", d)
        self.assertRegex((d / "piece.html").read_text(), r'<div class="sig">Marrowbay Ferments<p class="slogan">Brewed slowly\. Drunk quickly\.</p></div>')

    def test_slogan_side_of_logo(self):
        for pos, side in (("bottom-right", "right"), ("top-left", "left")):
            d = prep(logo_position=pos)
            run("compose", d)
            self.assertIn(side + ":", re.search(r"\.blk~\.slogan\{[^}]*\}", (d / "piece.html").read_text()).group(0))

    def test_check_fails_when_altered_or_missing(self):
        d = prep()
        run("compose", d)
        h = (d / "piece.html").read_text()
        (d / "piece.html").write_text(h.replace("Drunk quickly.", "Drunk fast."))
        run("check", d)
        self.assertEqual(results(d)["slogan"]["status"], "fail")
        self.assertIn("not the brand's exact words", results(d)["slogan"]["say"])
        (d / "piece.html").write_text(re.sub(r'<p class="slogan">.*?</p>', "", h))
        run("check", d)
        self.assertIn("missing from the piece", results(d)["slogan"]["say"])

    def test_no_slogan_no_result(self):
        d = prep(slogan=None)
        run("compose", d)
        run("check", d)
        self.assertNotIn("slogan", results(d))
        self.assertNotIn('class="slogan"', (d / "piece.html").read_text())

    def test_brand_page_shows_it(self):
        d = prep()
        self.assertIn(SLOGAN, (d / "1-brand.html").read_text())


class Unconfirmed(unittest.TestCase):
    def test_marker_parsing(self):
        sys.path.insert(0, str(ST))
        from files import load_brand
        d = prep(accent="#E07A2F (À confirmer)", slogan="Brewed slowly. Drunk quickly. (to confirm: https://marrowbay.example/about)",
                 extra_colours="#112233, #445566 (to confirm; the old label)", voice="warm (to confirm)")
        b = load_brand(d)
        self.assertEqual(b["accent"], "#e07a2f")
        self.assertEqual(b["slogan"], SLOGAN)
        self.assertEqual(b["extras"], ["#112233", "#445566"])
        self.assertEqual(b["voice"], "warm")
        self.assertEqual(b["unconfirmed"], {"accent": "", "slogan": "https://marrowbay.example/about", "extra colours": "the old label", "voice": ""})
        self.assertEqual(load_brand(EXAMPLE)["unconfirmed"], {})

    def test_nested_parenthesis_in_source(self):
        sys.path.insert(0, str(ST))
        from files import load_brand
        d = prep(slogan='Hi there (to confirm: web search "Marrowbay" (2026-10-23))')
        self.assertEqual(load_brand(d)["unconfirmed"]["slogan"], 'web search "Marrowbay" (2026-10-23)')
        self.assertEqual(load_brand(d)["slogan"], "Hi there")

    def test_check_warns_and_page_banner(self):
        d = prep(accent="#E07A2F (to confirm)", slogan=f"{SLOGAN} (to confirm: https://marrowbay.example/about)")
        run("compose", d)
        run("check", d)
        r = results(d)["unconfirmed"]
        self.assertEqual(r["status"], "warn")
        self.assertIn("accent, slogan (source https://marrowbay.example/about)", r["say"])
        self.assertEqual(results(d)["palette"]["status"], "pass")
        self.assertIn("This piece relies on values to confirm", (d / "5-check.html").read_text())
        self.assertIn("pill warn", (d / "1-brand.html").read_text())

    def test_no_banner_when_confirmed(self):
        d = prep()
        run("compose", d)
        run("check", d)
        self.assertNotIn("unconfirmed", results(d))
        self.assertNotIn("relies on values", (d / "5-check.html").read_text())

    def test_marker_never_reaches_the_image_prompt(self):
        d = prep(voice="warm and plain (to confirm: somewhere)", never_show="anyone drinking to camera (to confirm)")
        run("image", d, "--engine", "none")
        self.assertNotIn("to confirm", (d / "image.json").read_text())


class FromDossier(unittest.TestCase):
    def md(self, *args):
        d = Path(tempfile.mkdtemp(prefix="ixs-dz-"))
        run("brand", d, "--from-dossier", DOSSIER, *args)
        return (d / "brand.md").read_text()

    def test_default_leaves_out_to_confirm(self):
        t = self.md("--look", "old-identity")
        self.assertNotIn("#2F5D3A", t.split("# missing")[0])
        self.assertNotIn("(to confirm", t.split("# left out")[0])
        self.assertRegex(t, r"# left out, to confirm in the dossier \(rerun with --include-unconfirmed to take them\): colours\[old-identity #2F5D3A\]")

    def test_include_unconfirmed_marks(self):
        t = self.md("--look", "old-identity", "--include-unconfirmed")
        self.assertRegex(t, r"- background: #2F5D3A \(to confirm: web image search")
        self.assertRegex(t, r"- accent: #C9A227 \(to confirm: ")
        self.assertIn("# imported unconfirmed, marked (to confirm): colours[old-identity #2F5D3A]", t)

    def test_marked_brand_md_loads(self):
        sys.path.insert(0, str(ST))
        from files import load_brand
        d = Path(tempfile.mkdtemp(prefix="ixs-dz-"))
        run("brand", d, "--from-dossier", DOSSIER, "--look", "old-identity", "--include-unconfirmed")
        kv(d, "brand.md", text="#1E2A24")
        b = load_brand(d)
        self.assertEqual((b["background"], b["accent"]), ("#2f5d3a", "#c9a227"))
        self.assertEqual(set(b["unconfirmed"]), {"background", "accent"})
        self.assertIn("web image search", b["unconfirmed"]["accent"])

    def test_slogan_from_tagline_and_no_references(self):
        for args in ((), ("--include-unconfirmed",)):
            t = self.md(*args)
            self.assertIn(f"- slogan: {SLOGAN}\n", t)
            self.assertNotIn("ev-", t)
            self.assertNotIn("reference", t.lower())
            self.assertNotIn("summer-2026", t.split("# missing")[0])
