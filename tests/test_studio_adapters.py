"""Tests of the studio adapters: image prompt and engines (mocked network), dossier looks, Google Fonts check.

    python3 -m unittest discover -s tests
"""

import base64
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "studio"))
sys.path.insert(0, str(ROOT / "scripts"))

import dossier  # noqa: E402
import gfonts  # noqa: E402
import images  # noqa: E402
from files import StudioError  # noqa: E402

BRAND = {"background": "#F4EFE6", "text": "#1E2A24", "accent": "#C8553D", "voice": "warm", "never": ["cheap"], "never_show": ["people", "bottles"]}
BRIEF = {"size": (1200, 1600), "format": "poster"}
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


def env(**kw):
    base = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "STUDIO_IMAGE_MODEL", "STUDIO_OFFLINE")}
    return mock.patch.dict(os.environ, {**base, **kw}, clear=True)


class Prompt(unittest.TestCase):
    def prompt(self, layout):
        return images.build_prompt(BRAND, BRIEF, {"image_prompt": "A jar on a table", "layout": layout})

    def test_never_not_copied_never_show_is(self):
        p = self.prompt("side")
        self.assertNotIn("cheap", p)
        self.assertIn("Do not show: people; bottles.", p)
        self.assertIn("No text, no letters, no words, no logos, no watermark.", p)
        self.assertNotIn("Do not show", images.build_prompt({**BRAND, "never_show": []}, BRIEF, {"image_prompt": "A jar", "layout": "side"}))

    def test_suffix_per_layout(self):
        for layout, where in (("overlay-top", "top"), ("top", "top"), ("overlay-bottom", "bottom"), ("bottom", "bottom")):
            self.assertIn(f"Leave the {where} ~40%", self.prompt(layout))
        for layout in ("side", "stack", "ground"):
            self.assertIn("beside the image, not on it", self.prompt(layout))
            self.assertNotIn("~40%", self.prompt(layout))

    def test_api_size_and_ratio(self):
        self.assertEqual(images.api_size({"size": (1800, 1200)}), "1536x1024")
        self.assertEqual(images.api_size({"size": (1080, 1080)}), "1024x1024")
        self.assertEqual(images.api_size({"size": (1200, 1600)}), "1024x1536")
        self.assertEqual(images.api_ratio((1200, 627)), "16:9")
        self.assertEqual(images.api_ratio((1080, 1350)), "4:5")
        self.assertEqual(images.api_ratio((1080, 1080)), "1:1")

    def test_model_for(self):
        with env():
            self.assertEqual(images.model_for("openai"), "gpt-image-1")
            self.assertEqual(images.model_for("openrouter"), "google/gemini-2.5-flash-image")
            self.assertEqual(images.model_for("codex"), "codex (its own image tool)")
            self.assertEqual(images.model_for("none"), "")
        with env(STUDIO_IMAGE_MODEL="m/x"):
            self.assertEqual(images.model_for("openai"), "m/x")
            self.assertEqual(images.model_for("openrouter"), "m/x")
            self.assertEqual(images.model_for("none"), "")


class OpenRouter(unittest.TestCase):
    def run_or(self, side_effect):
        out = Path(tempfile.mkdtemp(prefix="ixs-or-")) / "image.png"
        with env(OPENROUTER_API_KEY="k"), mock.patch("urllib.request.urlopen", side_effect=side_effect) as m:
            res = images.openrouter("a jar", (1200, 627), out)
        return res, out, m

    def test_success(self):
        url = "data:image/png;base64," + base64.b64encode(PNG).decode()
        body = {"choices": [{"message": {"images": [{"image_url": {"url": url}}]}}]}
        (ok, msg), out, m = self.run_or(lambda req, timeout=None: Resp(json.dumps(body).encode()))
        self.assertTrue(ok, msg)
        self.assertEqual(out.read_bytes(), PNG)
        self.assertIn("OpenRouter", msg)

    def test_request_shape(self):
        seen = []
        self.run_or(lambda req, timeout=None: seen.append(req) or Resp(b"{}"))
        req = seen[0]
        self.assertEqual(req.full_url, "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer k")
        body = json.loads(req.data)
        self.assertEqual(body["image_config"], {"aspect_ratio": "16:9"})
        self.assertEqual(body["modalities"], ["image", "text"])
        self.assertEqual(body["model"], "google/gemini-2.5-flash-image")

    def test_http_error(self):
        (ok, msg), out, _ = self.run_or(http_error(402, {"error": {"message": "no credits"}}))
        self.assertFalse(ok)
        self.assertIn("402", msg)
        self.assertIn("no credits", msg)
        self.assertFalse(out.exists())

    def test_no_image(self):
        body = {"choices": [{"message": {"content": "sorry"}}]}
        (ok, msg), out, _ = self.run_or(lambda req, timeout=None: Resp(json.dumps(body).encode()))
        self.assertFalse(ok)
        self.assertIn("no image", msg)

    def test_network_failure_and_no_key(self):
        (ok, msg), _, _ = self.run_or(OSError("down"))
        self.assertFalse(ok)
        with env():
            self.assertFalse(images.openrouter("p", (1, 1), "x")[0])


class Auto(unittest.TestCase):
    def test_order(self):
        with env(OPENROUTER_API_KEY="k"), mock.patch("shutil.which", return_value="/bin/codex"):
            self.assertEqual(images.auto_engine(), "openrouter")
        with env(OPENROUTER_API_KEY="k", OPENAI_API_KEY="o"):
            self.assertEqual(images.auto_engine(), "openai")
        with env(), mock.patch("shutil.which", return_value="/bin/codex"):
            self.assertEqual(images.auto_engine(), "codex")
        with env(), mock.patch("shutil.which", return_value=None):
            self.assertEqual(images.auto_engine(), "none")

    def test_generate_auto_openrouter(self):
        with env(OPENROUTER_API_KEY="k"), mock.patch.dict(images.ENGINES, {"openrouter": lambda p, wh, o: (True, f"ok {wh}")}):
            self.assertEqual(images.generate("auto", "p", (1200, 627), "x"), ("openrouter", True, "ok (1200, 627)"))
        self.assertIn("OPENROUTER_API_KEY", images.none_msg(Path(".")))


def look_dossier(looks, master=None):
    d = Path(tempfile.mkdtemp(prefix="ixs-look-")) / "brand"
    shutil.copytree(ROOT / "examples" / "marrowbay" / "brand", d)
    doc = json.loads((d / "brand.json").read_text())
    src = {"type": "typed", "origin": "test", "at": "2026-10-23"}
    val = lambda v: {"value": v, "status": "confirmed", "source": src}  # noqa: E731
    doc["looks"] = {"items": [{"id": i, "name": val(i), "kind": val("brand"), **({"master": val(i == master)} if master else {})} for i in looks]}
    (d / "brand.json").write_text(json.dumps(doc))
    return d, doc


class Looks(unittest.TestCase):
    def md(self, d, **kw):
        return dossier.brand_md(d, Path(tempfile.mkdtemp(prefix="ixs-p-")), **kw)[0]

    def test_several_looks_no_master(self):
        d, _ = look_dossier(["a", "b"])
        with self.assertRaises(StudioError) as c:
            self.md(d)
        self.assertIn("a, b", str(c.exception))
        self.assertIn("--look", str(c.exception))
        self.assertIn("name: Marrowbay Ferments", self.md(d, look="a"))

    def test_unknown_look(self):
        d, _ = look_dossier(["a", "b"])
        with self.assertRaises(StudioError) as c:
            self.md(d, look="zzz")
        self.assertIn("a, b", str(c.exception))

    def test_master_and_single(self):
        d, _ = look_dossier(["a", "brand"], master="brand")
        self.assertIn("background:", self.md(d))
        d, _ = look_dossier(["brand"])
        self.assertIn("background:", self.md(d))

    def test_items_filtered_by_look(self):
        d, doc = look_dossier(["a", "b"])
        src = {"type": "typed", "origin": "test", "at": "2026-10-23"}
        for c in doc["colours"]["items"]:
            c["look"] = "a"
        doc["colours"]["items"].append({"look": "b", "hex": {"value": "#112233", "status": "confirmed", "source": src},
                                        "role": {"value": "background", "status": "confirmed", "source": src}})
        doc["colours"]["items"].append({"hex": {"value": "#445566", "status": "confirmed", "source": src},
                                        "role": {"value": "highlight", "status": "confirmed", "source": src}})
        (d / "brand.json").write_text(json.dumps(doc))
        a, b = self.md(d, look="a"), self.md(d, look="b")
        self.assertIn("background: #F4EFE6", a)
        self.assertIn("background: #112233", b)
        self.assertNotIn("#112233", a)
        self.assertIn("#445566", a)
        self.assertIn("#445566", b)

    def test_no_duplicate_colours(self):
        d, doc = look_dossier(["brand"], master="brand")
        src = {"type": "typed", "origin": "test", "at": "2026-10-23"}
        for h in ("#f4efe6", "#AABBCC", "#aabbcc"):
            doc["colours"]["items"].append({"look": "brand", "hex": {"value": h, "status": "confirmed", "source": src},
                                            "role": {"value": "highlight", "status": "confirmed", "source": src}})
        (d / "brand.json").write_text(json.dumps(doc))
        t = self.md(d).lower()
        self.assertEqual(t.count("#f4efe6"), 1)
        self.assertEqual(t.count("#aabbcc"), 1)

    def test_imagery_dont_goes_to_never_show(self):
        d, doc = look_dossier(["brand"], master="brand")
        src = {"type": "typed", "origin": "test", "at": "2026-10-23"}
        doc["imagery"]["dont"] = {"value": ["stock handshakes"], "status": "confirmed", "source": src}
        doc["voice"]["banned_words"] = {"value": ["synergy"], "status": "confirmed", "source": src}
        (d / "brand.json").write_text(json.dumps(doc))
        lines = self.md(d).splitlines()
        self.assertIn("- never: synergy", lines)
        self.assertIn("- never show: stock handshakes", lines)


class Fonts(unittest.TestCase):
    def test_codes(self):
        def fake(req, timeout=None):
            self.assertEqual(timeout, 5)
            if "Nope" in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, None)
            if "Down" in req.full_url:
                raise OSError("offline")
            return Resp(b"")
        with env(), mock.patch("urllib.request.urlopen", side_effect=fake) as m:
            w = gfonts.check(["Fraunces", "Nope Sans", "", "Down"])
        self.assertEqual(len(w), 1)
        self.assertIn('"Nope Sans" is not on Google Fonts', w[0])
        self.assertIn("family=Nope+Sans", m.call_args_list[1][0][0].full_url)

    def test_offline(self):
        with env(STUDIO_OFFLINE="1"), mock.patch("urllib.request.urlopen") as m:
            self.assertEqual(gfonts.check(["Nope Sans"]), [])
        m.assert_not_called()


if __name__ == "__main__":
    unittest.main()
