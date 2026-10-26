"""The engines of the studio (the settings): the command alone, with a fake `claude` and a fake OpenRouter on this machine; the routes of the
interface, on the simulated backend and on the real one. Nothing here calls claude, codex or the real network.

    python3 -m unittest discover -s tests
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "scripts" / "agents"
sys.path.insert(0, str(ROOT / "app"))

import server  # noqa: E402
from backend_stub import StubBackend  # noqa: E402
from backend_studio import StudioBackend  # noqa: E402

KEY = "sk-or-secret-123"
NAMES = {"names": [{"name": "Quai Ambré", "why": "Le port et la couleur."}]}
FAKE_CLAUDE = '''#!{python}
import json, sys
open({log!r}, "a").write(json.dumps(sys.argv[1:]) + "\\n")
print(json.dumps({names}))
'''


class OpenRouter(BaseHTTPRequestHandler):
    seen, mode = [], "ok"

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        OpenRouter.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "model": body["model"], "prompt": body["messages"][0]["content"]})
        code, out = (401, {"error": "bad key"}) if OpenRouter.mode == "refused" else (200, {"choices": [{"message": {"content": "pas de json ici"}}]}) if OpenRouter.mode == "bad" \
            else (200, {"choices": [{"message": {"content": "Voici :\n" + json.dumps(NAMES)}}]})
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class Command(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = HTTPServer(("127.0.0.1", 0), OpenRouter)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-engines-"))
        self.log = self.tmp / "claude.log"
        self.claude = self.tmp / "claude"
        self.claude.write_text(FAKE_CLAUDE.format(python=sys.executable, log=str(self.log), names=json.dumps(NAMES)), encoding="utf-8")
        self.claude.chmod(0o755)
        self.cfg = self.tmp / "config"
        OpenRouter.seen, OpenRouter.mode = [], "ok"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self, cmd, inputs=None, env=None):
        args = []
        if inputs is not None:
            f = self.tmp / "inputs.json"
            f.write_text(json.dumps(inputs), encoding="utf-8")
            args = [str(f)]
        e = {k: v for k, v in os.environ.items() if not k.startswith("STUDIO_") and k not in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY")}
        e.update(STUDIO_CONFIG_DIR=str(self.cfg), STUDIO_CLAUDE_BIN=str(self.claude), STUDIO_OPENROUTER_URL=f"http://127.0.0.1:{self.httpd.server_address[1]}/api/v1", **(env or {}))
        return subprocess.run([sys.executable, str(AGENTS), cmd, *args], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)

    def choose_openrouter(self):
        r = self.run_cmd("engines", {"text_engine": "openrouter", "openrouter_key": KEY, "openrouter_model": "mistral/medium"})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    BRAND = {"name": "Cabane", "description": "Un kombucha de port."}

    def test_without_settings_the_engines_are_the_default_ones(self):
        r = self.run_cmd("engines")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["image_engine"], got["text_engine"], got["key_saved"]), ("auto", "claude", False))

    def test_the_choices_are_kept_and_the_key_is_never_given_back(self):
        got = self.choose_openrouter()
        self.assertEqual((got["text_engine"], got["openrouter_model"], got["key_saved"]), ("openrouter", "mistral/medium", True))
        self.assertEqual(json.loads(self.run_cmd("engines", {"image_engine": "codex"}).stdout)["image_engine"], "codex")
        again = self.run_cmd("engines")
        self.assertEqual((json.loads(again.stdout)["text_engine"], json.loads(again.stdout)["image_engine"]), ("openrouter", "codex"))
        self.assertNotIn(KEY, again.stdout + again.stderr + self.run_cmd("engines", {"image_engine": "none"}).stdout)
        f = self.cfg / "engines.json"  # in the configuration of the person, readable by them alone
        self.assertEqual(json.loads(f.read_text())["openrouter_key"], KEY)
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        gone = json.loads(self.run_cmd("engines", {"openrouter_key": ""}).stdout)  # an empty key forgets it
        self.assertFalse(gone["key_saved"])

    def test_an_engine_that_does_not_exist_is_an_error(self):
        for patch in ({"image_engine": "midjourney"}, {"text_engine": "gpt"}, {"openrouter_key": 3}):
            r = self.run_cmd("engines", patch)
            self.assertEqual((r.returncode, r.stdout), (1, ""))
            self.assertTrue(r.stderr.strip().startswith("agents: inputs: "), r.stderr)
        self.assertFalse((self.cfg / "engines.json").exists())

    def test_the_variable_wins_over_the_choice_saved(self):
        self.run_cmd("engines", {"image_engine": "codex"})
        got = json.loads(self.run_cmd("engines", env={"STUDIO_IMAGE_ENGINE": "none", "STUDIO_TEXT_ENGINE": "openrouter"}).stdout)
        self.assertEqual((got["image_engine"], got["text_engine"]), ("none", "openrouter"))

    def test_an_agent_that_only_answers_uses_openrouter_when_chosen(self):
        self.choose_openrouter()
        r = self.run_cmd("names", self.BRAND_FILE())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["names"][0]["name"], "Quai Ambré")
        seen = OpenRouter.seen[0]
        self.assertEqual((seen["path"], seen["auth"], seen["model"]), ("/api/v1/chat/completions", "Bearer " + KEY, "mistral/medium"))
        self.assertIn("Cabane", seen["prompt"])
        self.assertFalse(self.log.exists())  # claude was not run

    def BRAND_FILE(self):
        return {**self.BRAND, "words": "franc"}

    def test_claude_stays_the_engine_by_default(self):
        r = self.run_cmd("names", self.BRAND_FILE())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.log.exists())
        self.assertEqual(OpenRouter.seen, [])

    def test_an_answer_of_openrouter_that_does_not_read_is_an_error(self):
        self.choose_openrouter()
        OpenRouter.mode = "bad"
        r = self.run_cmd("names", self.BRAND_FILE())
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertRegex(r.stderr, "illisible")
        self.assertNotIn(KEY, r.stderr)

    def test_a_refusal_of_openrouter_is_an_error_that_does_not_show_the_key(self):
        self.choose_openrouter()
        OpenRouter.mode = "refused"
        r = self.run_cmd("names", self.BRAND_FILE())
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("HTTP 401", r.stderr)
        self.assertNotIn(KEY, r.stderr)

    def test_openrouter_without_a_key_says_so(self):
        r = self.run_cmd("names", self.BRAND_FILE(), env={"STUDIO_TEXT_ENGINE": "openrouter"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("aucune clé", r.stderr)
        self.assertEqual(OpenRouter.seen, [])


class Routes:
    """The routes of the settings, the same on both backends."""

    def call(self, method, path, body=None, code=200):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                got, data = r.status, r.read()
        except urllib.error.HTTPError as err:
            got, data = err.code, err.read()
            err.close()
        self.assertEqual(got, code, data)
        return data.decode()

    def test_the_settings_are_read_and_the_engines_chosen(self):
        got = json.loads(self.call("GET", "/api/engines"))
        self.assertEqual((got["image_engine"], got["text_engine"], got["key_saved"]), ("auto", "claude", False))
        self.assertEqual(got["image_engines"], ["auto", "openai", "openrouter", "codex", "none"])
        self.assertEqual(got["text_engines"], ["claude", "openrouter"])
        got = json.loads(self.call("PUT", "/api/engines/image", {"engine": "codex"}))
        self.assertEqual(got["image_engine"], "codex")
        got = json.loads(self.call("PUT", "/api/engines/text", {"engine": "openrouter", "key": KEY, "model": "mistral/medium"}))
        self.assertEqual((got["text_engine"], got["openrouter_model"], got["key_saved"]), ("openrouter", "mistral/medium", True))
        again = json.loads(self.call("GET", "/api/engines"))
        self.assertEqual((again["image_engine"], again["text_engine"], again["key_saved"]), ("codex", "openrouter", True))
        kept = json.loads(self.call("PUT", "/api/engines/text", {"engine": "claude"}))  # no key sent: the saved one stays
        self.assertEqual((kept["text_engine"], kept["key_saved"]), ("claude", True))
        self.assertFalse(json.loads(self.call("PUT", "/api/engines/text", {"engine": "claude", "key": ""}))["key_saved"])

    def test_the_key_is_never_in_an_answer(self):
        seen = [self.call("PUT", "/api/engines/text", {"engine": "openrouter", "key": KEY}), self.call("GET", "/api/engines"),
                self.call("PUT", "/api/engines/image", {"engine": "none"})]
        for text in seen:
            self.assertNotIn(KEY, text)

    def test_an_engine_that_does_not_exist_is_refused(self):
        self.call("PUT", "/api/engines/image", {"engine": "midjourney"}, code=400)
        self.call("PUT", "/api/engines/text", {"engine": "gpt"}, code=400)
        self.call("PUT", "/api/engines/text", {"engine": "openrouter", "key": 3}, code=400)


class Served:
    """One backend and its server for each test: the settings of one do not leak into the next."""

    def serve(self, backend):
        self.httpd = server.serve("127.0.0.1", 0, backend)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))


class StubRoutes(Served, Routes, unittest.TestCase):
    def setUp(self):
        self.serve(StubBackend(speed=0.01))


class StudioRoutes(Served, Routes, unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-engines-routes-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        saved = {k: os.environ.pop(k, None) for k in ("STUDIO_IMAGE_ENGINE", "STUDIO_TEXT_ENGINE", "OPENROUTER_API_KEY")}
        os.environ["STUDIO_CONFIG_DIR"] = str(self.tmp / "config")
        self.addCleanup(lambda: (os.environ.pop("STUDIO_CONFIG_DIR", None), os.environ.update({k: v for k, v in saved.items() if v is not None})))
        self.backend = StudioBackend(self.tmp / "home")  # its runner is the real one: the command, for real
        self.serve(self.backend)

    def test_the_key_stays_outside_the_work_folder_and_the_logs(self):
        self.call("PUT", "/api/engines/text", {"engine": "openrouter", "key": KEY})
        self.assertEqual(json.loads((self.tmp / "config" / "engines.json").read_text())["openrouter_key"], KEY)
        for f in (self.tmp / "home").rglob("*"):
            if f.is_file():
                self.assertNotIn(KEY, f.read_text(errors="ignore"), f)

    def test_the_image_engine_chosen_is_the_one_the_images_use(self):
        self.assertEqual(self.backend.image_engine, "auto")
        self.call("PUT", "/api/engines/image", {"engine": "none"})
        self.assertEqual(self.backend.image_engine, "none")


if __name__ == "__main__":
    unittest.main()
