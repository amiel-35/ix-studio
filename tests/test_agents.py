"""The agents of the studio (scripts/agents), each command run alone in a terminal, on files, with a fake `claude`: a right answer, an answer that
does not read, an agent that fails. The fake is a program given by STUDIO_CLAUDE_BIN, as the backend of the interface gives it. Nothing here calls
claude, codex or the network.

    python3 -m unittest discover -s tests
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "scripts" / "agents"

FAKE = '''#!{python}
import json, os, re, sys
mode, prompt = os.environ["FAKE_MODE"], sys.argv[2]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "ls": sorted(os.listdir(".")), "key": "ANTHROPIC_API_KEY" in os.environ}}) + "\\n")
if mode == "down":
    print("Claude Code is not signed in", file=sys.stderr)
    sys.exit(1)
ok = mode == "ok"
ANSWERS = {{
    '{{"personas": [': {{"personas": [{{"need": "goûter avant d'acheter", "lines": [{{"from": "supposé", "say": "Tu as la cinquantaine."}}]}}]}},
    '{{"names": [': {{"names": [{{"name": "Quai Ambré", "why": "Le port et la couleur."}}]}},
    '{{"competitors": [': {{"competitors": [{{"name": "Kombucha du Coin", "from": "supposé", "sells": "du kombucha", "differs": "plus sucré"}}]}},
    '{{"objective": ': {{"objective": "Faire connaître le kombucha.", "audience": "Les citadins curieux.", "message": "Du thé qui a fait la fête.", "cta": "Venir goûter.", "fixed": "La signature."}},
    '{{"common": ': {{"common": "Écrire en français.", "mandates": ["Un", "Deux", "Trois", "Rupture : Quatre"]}},
}}
for key, body in ANSWERS.items():
    if key in prompt:
        print("Voici :\\n" + json.dumps(body, ensure_ascii=False) if ok else "pas de json ici")
        sys.exit(0)
WRITES = {{
    "./verdict.json": ("verdict.json", {{"target": {{"reached": "partly", "why": "Un citadin comprend."}}, "works": [], "snags": [], "unsourced": []}}),
    "./reading.json": ("reading.json", {{"aimed": "yes", "why": "Je me reconnais.", "understand": "Une boisson.", "retain": "", "bother": "", "unread": "", "lacks": ""}}),
}}
m = re.search(r"\\./(v\\d+)\\.json", prompt)
if m:
    WRITES["./" + m.group(1) + ".json"] = (m.group(1) + ".json", {{"mandate": "Un", "default": {{"headline": "H", "image": "I"}}, "headline": "Titre", "subline": "",
                                                              "image_prompt": "Une image", "layout": "side", "ground": "background", "why": "Parce que."}})
for key, (name, body) in WRITES.items():
    if key in prompt:
        with open(name, "w") as f:
            f.write(json.dumps(body) if ok else "{{pas du json")
        print(name)
        sys.exit(0)
sys.exit(2)
'''


class Agents(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ixs-agents-"))
        self.claude = self.tmp / "claude"
        self.claude.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        self.claude.chmod(0o755)
        self.log = self.tmp / "calls.log"
        (self.tmp / "piece.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        piece = self.tmp / "piece"
        piece.mkdir()
        (piece / "brand.md").write_text("# Marque\n- logo : logo.png\n- voix : franche\n", encoding="utf-8")
        (piece / "brief.md").write_text("# Brief\n- objectif : faire goûter\n", encoding="utf-8")
        (self.tmp / "brand.json").write_text('{"name": "Cabane"}', encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cmd(self, cmd, inputs, mode="ok", *args, env=None):
        f = self.tmp / "inputs.json"
        f.write_text(json.dumps(inputs), encoding="utf-8")
        e = {k: v for k, v in os.environ.items() if not k.startswith("STUDIO_MODEL_") and k not in ("ANTHROPIC_API_KEY", "STUDIO_CLAUDE_USE_API_KEY")}
        e.update(STUDIO_CLAUDE_BIN=str(self.claude), FAKE_MODE=mode, FAKE_LOG=str(self.log), **(env or {}))
        return subprocess.run([sys.executable, str(AGENTS), cmd, str(f), *args], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def model_of(self, call):
        return call["argv"][call["argv"].index("--model") + 1]

    BRAND = {"name": "Cabane", "site": "cabane.fr", "description": "Un kombucha de port.", "words": "franc",
             "brief": [{"key": "what", "value": "un kombucha", "state": "confirmed"}, {"key": "voice", "value": "franche", "state": "deduced"}], "dossier": "brand.json"}
    PIECE = {"image": "piece.png", "brief": {"objective": "faire goûter", "audience": "les citadins", "message": "c'est bon", "cta": "viens"}, "brand": {}}
    CASES = {
        "personas": (BRAND, "personas", ["personas"]),
        "names": (BRAND, "names", ["names"]),
        "competitors": (BRAND, "competitors", ["competitors"]),
        "mandates": ({"dir": "piece", "language": "fr"}, "common", ["common", "mandates"]),
        "variant": ({"dir": "piece", "id": "v1", "mandate": "Un", "common": "Rien d'inventé.", "language": "fr"}, "headline", ["headline", "layout"]),
        "judge": (PIECE, "target", ["target", "works", "snags", "unsourced", "brand", "missing"]),
        "reader": ({"image": "piece.png", "persona": "Tu as la cinquantaine.", "texts": {"headline": "H", "subline": ""}}, "aimed", ["aimed", "why"]),
    }

    def test_every_command_gives_its_answer_as_json(self):
        for cmd, (inputs, _, keys) in self.CASES.items():
            with self.subTest(cmd=cmd):
                r = self.run_cmd(cmd, inputs)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = json.loads(r.stdout)
                for k in keys:
                    self.assertIn(k, got)

    def test_the_answer_can_also_go_in_a_file(self):
        out = self.tmp / "answer.json"
        r = self.run_cmd("names", self.BRAND, "ok", "--out", str(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(out.read_text())["names"][0]["name"], "Quai Ambré")
        self.assertEqual(json.loads(r.stdout), json.loads(out.read_text()))

    def test_an_answer_that_does_not_read_is_an_error_with_its_reason(self):
        for cmd, (inputs, _, _) in self.CASES.items():
            with self.subTest(cmd=cmd):
                r = self.run_cmd(cmd, inputs, "bad")
                self.assertEqual((r.returncode, r.stdout), (1, ""))
                self.assertTrue(r.stderr.strip().splitlines()[-1].startswith("agents: "), r.stderr)  # the reason is the last line
                self.assertRegex(r.stderr, "illisible|pas de JSON|JSON")
                if cmd not in ("judge", "reader", "variant"):  # those write a file: claude says nothing on its output
                    self.assertIn("pas de json ici", r.stderr)  # the raw answer is kept for the log

    def test_an_agent_that_fails_is_an_error_with_its_reason(self):
        for cmd, (inputs, _, _) in self.CASES.items():
            with self.subTest(cmd=cmd):
                r = self.run_cmd(cmd, inputs, "down")
                self.assertEqual((r.returncode, r.stdout), (1, ""))
                self.assertIn("Claude Code is not signed in", r.stderr)

    def test_a_missing_input_or_file_is_an_error(self):
        self.assertEqual(self.run_cmd("judge", {"brief": {}}).returncode, 1)
        r = self.run_cmd("reader", {"image": "absent.png", "persona": "x"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("image", r.stderr)
        self.assertEqual(self.run_cmd("variant", {"dir": "piece"}).returncode, 1)

    def test_the_variant_is_written_in_the_piece_and_only_its_own_files_are_seen(self):
        r = self.run_cmd("variant", self.CASES["variant"][0])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.tmp / "piece" / "variants" / "v1.json").read_text())["headline"], "Titre")
        self.assertEqual(self.calls()[0]["ls"], ["brand.md", "brief.md", "refs"])  # the logo line of the brand is left out of its copy

    def test_the_judge_and_the_readers_run_on_the_best_model_the_others_on_sonnet(self):
        for cmd, (inputs, _, _) in self.CASES.items():
            self.run_cmd(cmd, inputs)
        self.assertEqual([self.model_of(c) for c in self.calls()], ["sonnet"] * 5 + ["claude-fable-5-1"] * 2)

    def test_the_model_changes_by_option_or_by_variable_without_touching_the_code(self):
        self.run_cmd("judge", self.PIECE, "ok", "--model", "opus")
        self.run_cmd("judge", self.PIECE, "ok", env={"STUDIO_MODEL_JUDGE": "claude-opus-5-5"})
        self.run_cmd("names", self.BRAND, "ok", env={"STUDIO_MODEL_NAMES": "haiku"})
        self.assertEqual([self.model_of(c) for c in self.calls()], ["opus", "claude-opus-5-5", "haiku"])

    def test_the_plan_pays_not_a_key_left_in_the_environment(self):
        self.run_cmd("names", self.BRAND, env={"ANTHROPIC_API_KEY": "sk-test"})
        self.run_cmd("names", self.BRAND, env={"ANTHROPIC_API_KEY": "sk-test", "STUDIO_CLAUDE_USE_API_KEY": "1"})
        self.assertEqual([c["key"] for c in self.calls()], [False, True])
        self.assertEqual(self.calls()[0]["argv"][0], "-p")
        self.assertIn("--restricted", self.calls()[0]["argv"])

    # interview: the questions, then the brief the answers make
    ANSWERS = ["Faire connaître", "Les citadins curieux", "Du thé qui a fait la fête", "Venir goûter", "La signature"]

    def test_the_interview_gives_its_questions_without_asking_claude(self):
        r = self.run_cmd("interview", {})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(json.loads(r.stdout)["questions"]), 5)
        self.assertEqual(self.calls(), [])

    def test_the_interview_writes_the_brief_from_the_answers_and_shows_what_it_lacks(self):
        r = self.run_cmd("interview", {"answers": self.ANSWERS, "brand": {"name": "Cabane", "who": "des citadins", "personas": ["Besoin : goûter"]}})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["fields"]["objective"], got["fields"]["audience"], got["missing"]), ("Faire connaître le kombucha.", "Les citadins curieux.", []))
        prompt = self.calls()[0]["argv"][1]
        self.assertIn("persona of the brand 1: Besoin : goûter", prompt)
        self.assertIn("réponse (objective) : Faire connaître", prompt)
        # nobody said the objective or the target: empty and flagged, whatever the agent wrote
        r = self.run_cmd("interview", {"answers": ["", "", "Du thé qui a fait la fête"]})
        got = json.loads(r.stdout)
        self.assertEqual((got["fields"]["objective"], got["fields"]["audience"], got["fields"]["cta"], got["missing"]), ("", "", "", ["objective", "audience"]))
        self.assertEqual(got["fields"]["message"], "Du thé qui a fait la fête.")
        self.assertIn("réponse (objective) : (aucune)", self.calls()[-1]["argv"][1])

    def test_the_interview_refuses_what_is_not_five_answers_or_none(self):
        for bad in ({"answers": ["a"] * 6}, {"answers": "a"}, {"answers": ["", " "]}):
            self.assertEqual(self.run_cmd("interview", bad).returncode, 1)
        self.assertEqual(self.calls(), [])

    def test_the_interview_answer_that_does_not_read_or_that_fails_is_an_error_with_its_reason(self):
        r = self.run_cmd("interview", {"answers": self.ANSWERS}, "bad")
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertRegex(r.stderr, "illisible|pas de JSON")
        self.assertIn("pas de json ici", r.stderr)
        r = self.run_cmd("interview", {"answers": self.ANSWERS}, "down")
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("Claude Code is not signed in", r.stderr)
        self.assertEqual(self.model_of(self.calls()[0]), "sonnet")


if __name__ == "__main__":
    unittest.main()
