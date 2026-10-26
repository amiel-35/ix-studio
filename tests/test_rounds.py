"""The rounds: a piece judged three times, alone each time, then the remarks put in three shelves (what holds, what is ambiguous, what came out
once). Three doors: the command alone (a fake `claude`), the simulated studio and the real one (its runner faked), through the routes.
Nothing here calls claude, codex or the network.

    python3 -m unittest discover -s tests
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "scripts" / "agents"
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
import workflow  # noqa: E402
from backend_stub import StubBackend  # noqa: E402
from test_backend_studio import Base, Result, png  # noqa: E402
from test_judge import BRIEF, drop  # noqa: E402

SYNTHESIS = {"remarks": [
    {"heading": "works", "where": "l'image", "say": "La lumière installe le marché.", "rounds": [1, 2, 3]},
    {"heading": "snags", "where": "le titre", "say": "Le double sens joue contre la boisson.", "rounds": [3, 1]},
    {"heading": "snags", "where": "le bandeau", "say": "L'appel à l'action est trop petit.", "rounds": [2]},
    {"heading": "unsourced", "where": "la sous-ligne", "say": "« petite cuvée » n'est dans aucune source.", "rounds": [1]}]}
VERDICT = {"target": {"reached": "partly", "why": "Un citadin comprend."}, "works": [{"where": "l'image", "say": "La lumière installe le marché."}],
           "snags": [{"where": "le titre", "say": "Le double sens."}], "unsourced": []}
FAKE = '''#!{python}
import json, os, sys
mode, prompt = os.environ["FAKE_MODE"], sys.argv[2]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:]}}) + "\\n")
if mode == "down":
    print("Claude Code is not signed in", file=sys.stderr)
    sys.exit(1)
if '{{"remarks": [' in prompt:
    print("Voici :\\n" + json.dumps({synthesis}, ensure_ascii=False) if mode == "ok" else "pas de json ici")
    sys.exit(0)
with open("verdict.json", "w") as f:
    f.write(json.dumps({verdict}))
print("verdict.json")
'''


class RoundsCommand(unittest.TestCase):
    """`scripts/agents rounds` alone, on files."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-rounds-"))
        self.claude = self.tmp / "claude"
        self.claude.write_text(FAKE.format(python=sys.executable, synthesis=SYNTHESIS, verdict=VERDICT), encoding="utf-8")
        self.claude.chmod(0o755)
        self.log = self.tmp / "calls.log"
        (self.tmp / "piece.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.tmp / "inputs.json").write_text(json.dumps({"image": "piece.png", "brief": BRIEF, "brand": {}}), encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self, mode="ok", *args):
        e = {k: v for k, v in os.environ.items() if not k.startswith("STUDIO_MODEL_") and k != "ANTHROPIC_API_KEY"}
        e.update(STUDIO_CLAUDE_BIN=str(self.claude), FAKE_MODE=mode, FAKE_LOG=str(self.log))
        return subprocess.run([sys.executable, str(AGENTS), "rounds", str(self.tmp / "inputs.json"), *args], capture_output=True, text=True, env=e,
                              stdin=subprocess.DEVNULL)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_three_rounds_of_the_judge_then_the_synthesis(self):
        r = self.run_cmd()
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual([set(v) for v in got["rounds"]], [{"target", "works", "snags", "unsourced", "brand", "missing"}] * 3)
        s = got["synthesis"]
        self.assertEqual([x["say"] for x in s["holds"]], ["La lumière installe le marché."])
        self.assertEqual([(x["where"], x["rounds"]) for x in s["ambiguous"]], [("le titre", [1, 3])])
        self.assertEqual([(x["where"], x["rounds"]) for x in s["once"]], [("le bandeau", [2]), ("la sous-ligne", [1])])
        calls = self.calls()
        self.assertEqual(len(calls), 4)  # three judges, one comparison
        models = sorted(c["argv"][c["argv"].index("--model") + 1] for c in calls)
        self.assertEqual(models, ["claude-fable-5-1"] * 3 + ["sonnet"])  # the judge as it is, with its own model
        self.assertIn("=== tour 3 ===", [c for c in calls if '{"remarks": [' in c["argv"][1]][0]["argv"][1])

    def test_the_answer_can_go_in_a_file(self):
        out = self.tmp / "tours.json"
        self.assertEqual(self.run_cmd("ok", "--out", str(out)).returncode, 0)
        self.assertEqual(set(json.loads(out.read_text())), {"rounds", "synthesis"})

    def test_a_synthesis_that_does_not_read_is_an_error_with_its_reason(self):
        r = self.run_cmd("bad")
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("synthèse des tours illisible", r.stderr.strip().splitlines()[-1])
        self.assertIn("pas de json ici", r.stderr)  # the raw answer is kept for the log

    def test_an_agent_that_fails_is_an_error_with_its_reason(self):
        r = self.run_cmd("down")
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("Claude Code is not signed in", r.stderr)

    def test_the_synthesis_is_checked(self):
        bad = [{"remarks": "x"}, {"remarks": [{"heading": "mood", "where": "a", "say": "b", "rounds": [1]}]},
               {"remarks": [{"heading": "works", "where": "a", "say": "b", "rounds": [4]}]},
               {"remarks": [{"heading": "works", "where": "a", "say": "b", "rounds": []}]},
               {"remarks": [{"heading": "works", "where": "", "say": "b", "rounds": [1]}]}]
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                workflow.parse_rounds(raw)
        out = workflow.parse_rounds({"remarks": [{"heading": "works", "where": "a", "say": "b", "rounds": [2, 2]}]})
        self.assertEqual(len(out["once"]), 1)  # the same round twice is one round


class StubRounds(unittest.TestCase):
    """The simulated studio: a fixed synthesis, through the same routes."""

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

    def call(self, method, path, code=200):
        import urllib.error
        import urllib.request
        req = urllib.request.Request(self.base + path, method=method, data=b"{}" if method == "POST" else None, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                got, data = r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            got, data = err.code, json.loads(err.read())
            err.close()
        self.assertEqual(got, code, data)
        return data

    def until(self, jid, status):
        for _ in range(200):
            v = self.call("GET", f"/api/judgements/{jid}/rounds")
            if v["status"] == status:
                return v
            time.sleep(0.02)
        self.fail(status)

    def test_three_rounds_and_a_synthesis(self):
        jg = drop(self.base, png(), meta={"brief": BRIEF})
        self.assertEqual(self.call("GET", f"/api/judgements/{jg['id']}/rounds")["status"], "none")  # never launched
        job = self.call("POST", f"/api/judgements/{jg['id']}/rounds")
        self.assertEqual(job["kind"], "rounds")
        self.call("POST", f"/api/judgements/{jg['id']}/rounds", code=409)
        self.assertTrue(any(j["kind"] == "rounds" and j["judgement"] == jg["id"] for j in self.call("GET", "/api/tasks")["jobs"]))
        v = self.until(jg["id"], "done")
        self.assertEqual(set(v), {"status", "synthesis", "error", "job"})
        self.assertEqual(set(v["synthesis"]), {"holds", "ambiguous", "once"})
        self.assertTrue(v["synthesis"]["holds"] and v["synthesis"]["ambiguous"] and v["synthesis"]["once"])
        self.assertEqual(self.call("GET", f"/api/judgements/{jg['id']}")["status"], "done")  # the judge itself is as it was
        self.call("POST", f"/api/judgements/{jg['id']}/rounds")  # again, once done
        self.call("GET", "/api/judgements/nope/rounds", code=404)
        self.call("POST", "/api/judgements/nope/rounds", code=404)

    def test_a_failure_is_said(self):
        jg = drop(self.base, png(), name="fail.png", meta={"brief": BRIEF})
        self.call("POST", f"/api/judgements/{jg['id']}/rounds")
        self.assertIn("simulé", self.until(jg["id"], "failed")["error"])


class RealRounds(Base):
    """The real studio: the command for real, its `claude` faked by the runner."""

    def setUp(self):
        super().setUp()
        self.fake.rounds = "ok"
        orig = self.fake.claude

        def claude(argv, cwd):
            if '{"remarks": [' in argv[2]:
                if self.fake.rounds == "none":
                    return Result(1, "", "the comparison gave up")
                self.fake.rounds_prompt = argv[2]
                return Result(0, json.dumps(SYNTHESIS), "")
            return orig(argv, cwd)
        self.fake.claude = claude

    def tearDown(self):
        del self.fake.claude  # back to the class's own
        super().tearDown()

    def dropped(self, meta):
        return drop(self.base, png(), "image/png", "affiche.png", meta)

    def until(self, jid, status):
        for _ in range(500):
            v = self.call("GET", f"/api/judgements/{jid}/rounds")
            if v["status"] == status:
                return v
            time.sleep(0.02)
        self.fail(status)

    def test_three_rounds_kept_on_the_disk(self):
        jg = self.dropped({"brief": BRIEF})
        self.assertEqual(self.call("GET", f"/api/judgements/{jg['id']}/rounds")["status"], "none")
        self.wait(self.call("POST", f"/api/judgements/{jg['id']}/rounds"))
        v = self.until(jg["id"], "done")
        self.assertEqual([len(v["synthesis"][k]) for k in ("holds", "ambiguous", "once")], [1, 1, 2])
        saved = json.loads((self.home / "jugements" / jg["id"] / "jugement.json").read_text())["rounds"]
        self.assertEqual(len(saved["rounds"]), 3)  # on the disk: a restart finds it
        self.assertIn("=== tour 3 ===", self.fake.rounds_prompt)

    def test_a_failure_is_said_and_run_again(self):
        jg = self.dropped({"brief": BRIEF})
        self.fake.rounds = "none"
        self.call("POST", f"/api/judgements/{jg['id']}/rounds")
        self.assertIn("l'agent n'a pas répondu", self.until(jg["id"], "failed")["error"])
        self.fake.rounds = "ok"
        self.call("POST", f"/api/judgements/{jg['id']}/rounds")
        self.until(jg["id"], "done")
        self.call("GET", "/api/judgements/nope/rounds", code=404)


if __name__ == "__main__":
    unittest.main()
