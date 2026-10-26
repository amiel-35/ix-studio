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
    '{{"logos": [': {{"logos": [{{"idea": "Le nom en capitales.", "svg": "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 120'><text x='10' y='60' fill='#123456'>Cabane</text></svg>"}}]}},
    '"script": "...",': {{"script": "Une question, puis le geste, puis la marque.", "shots": [
        {{"seconds": 3, "visual": "texte", "text": "C'est quoi ?", "colour": "#1E2A24", "read": "C'est quoi ?"}},
        {{"seconds": 3, "visual": "texte", "text": "Du thé qui fermente.", "colour": "#c8553d", "read": "Du thé qui fermente."}},
        {{"seconds": 4, "visual": "texte", "text": "Brassé au port.", "colour": "#f4efe6", "read": "Brassé au port."}},
        {{"seconds": 4, "visual": "texte", "text": "Un goût franc.", "colour": "#1e2a24", "read": "Un goût franc."}},
        {{"seconds": 3, "visual": "texte", "text": "Servez-vous.", "colour": "#c8553d", "read": "Servez-vous."}},
        {{"seconds": 3, "visual": "logo", "text": "", "colour": "#1e2a24", "read": "Cabane."}}]}},
    '{{"texts": [': {{"texts": [{{"kind": "accroche", "text": "Du thé qui a fait la fête."}}, {{"kind": "post", "text": "Goûte.\\nC'est bon."}}]}},
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
        "logos": ({**BRAND, "colours": ["#123456", "#FFFFFF"], "fonts": ["Georgia"]}, "logos", ["logos"]),
        "texts": ({"brief": {"objective": "faire goûter", "audience": "les citadins", "message": "c'est bon", "cta": "viens"}, "brand": {"name": "Cabane", "voice": "franche"}, "language": "fr"}, "texts", ["texts"]),
        "mandates": ({"dir": "piece", "language": "fr"}, "common", ["common", "mandates"]),
        "variant": ({"dir": "piece", "id": "v1", "mandate": "Un", "common": "Rien d'inventé.", "language": "fr"}, "headline", ["headline", "layout"]),
        "judge": (PIECE, "target", ["target", "works", "snags", "unsourced", "brand", "missing"]),
        "reader": ({"image": "piece.png", "persona": "Tu as la cinquantaine.", "texts": {"headline": "H", "subline": ""}}, "aimed", ["aimed", "why"]),
        "storyboard": ({"name": "Cabane", "brand": {"what": "un kombucha"}, "colours": ["#1e2a24", "#c8553d", "#f4efe6"],
                        "brief": {"objective": "faire goûter", "audience": "les citadins", "message": "c'est bon", "cta": "viens"}}, "script", ["script", "shots"]),
    }

    def test_every_command_gives_its_answer_as_json(self):
        for cmd, (inputs, _, keys) in self.CASES.items():
            with self.subTest(cmd=cmd):
                r = self.run_cmd(cmd, inputs)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = json.loads(r.stdout)
                for k in keys:
                    self.assertIn(k, got)

    def test_the_storyboard_is_checked_and_its_prompt_gives_only_the_brief_and_the_brand(self):
        inputs = self.CASES["storyboard"][0]
        got = json.loads(self.run_cmd("storyboard", inputs).stdout)
        self.assertEqual((len(got["shots"]), sum(x["seconds"] for x in got["shots"])), (6, 20))
        self.assertEqual(got["shots"][0]["colour"], "#1e2a24")  # lower case
        self.assertEqual(got["shots"][-1], {"seconds": 3, "visual": "logo", "text": "", "colour": "#1e2a24", "read": "Cabane."})
        call = self.calls()[-1]
        self.assertEqual(call["argv"][call["argv"].index("--tools") + 1], "")  # no tool, no search
        self.assertEqual(call["ls"], [])
        self.assertFalse(call["key"])
        self.assertEqual(self.model_of(call), "sonnet")
        # a colour that is not the brand's, a film too short, too few shots: refused with the reason
        for colours, why in ((["#000000"], "couleur de la marque"),):
            r = self.run_cmd("storyboard", {**inputs, "colours": colours})
            self.assertEqual(r.returncode, 1)
            self.assertIn(why, r.stderr)
        from importlib import util
        spec = util.spec_from_file_location("ixs_answers", AGENTS / "answers.py")
        answers = util.module_from_spec(spec)
        spec.loader.exec_module(answers)
        ok = json.loads(self.run_cmd("storyboard", inputs).stdout)
        for bad, word in (({**ok, "shots": ok["shots"][:4]}, "de 5 à 8"), ({**ok, "shots": [{**x, "seconds": 2} for x in ok["shots"]]}, "il en faut de 15 à 30"),
                          ({**ok, "script": ""}, "script"), ({**ok, "shots": [{**ok["shots"][0], "visual": "video"}, *ok["shots"][1:]]}, "visual"),
                          ({**ok, "shots": [{**ok["shots"][0], "text": ""}, *ok["shots"][1:]]}, "texte à l'écran"),
                          ({**ok, "shots": [{**ok["shots"][0], "read": ""}, *ok["shots"][1:]]}, "ce qu'on lit")):
            with self.assertRaisesRegex(ValueError, word):
                answers.parse_storyboard(bad)

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

    def test_the_logos_are_drawings_checked_before_they_are_given(self):
        r = self.run_cmd("logos", self.CASES["logos"][0])
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)["logos"]
        self.assertEqual((len(got), got[0]["idea"]), (1, "Le nom en capitales."))
        self.assertIn("#123456", self.calls()[0]["argv"][1])  # the colours and the fonts of the brand are in the prompt
        self.assertIn("Georgia", self.calls()[0]["argv"][1])
        sys.path.insert(0, str(AGENTS))
        from answers import parse_logos
        good = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'><circle r='4' fill='#000'/></svg>"
        self.assertEqual(parse_logos({"logos": [{"idea": "Un rond.", "svg": good}] * 4})[0]["svg"], good)
        bad_svgs = ["pas du svg", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><g></svg>", "<svg xmlns='http://www.w3.org/2000/svg'><g/></svg>",  # not well formed, no viewBox
                    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><script>alert(1)</script></svg>", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1' onload='x()'/>",
                    "<svg viewBox='0 0 1 1'><circle r='1'/></svg>", "<svg:svg xmlns:svg='http://example.org/not-svg' viewBox='0 0 1 1'/>",  # no SVG namespace: not an SVG for a browser
                    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><image href='https://x.fr/a.png'/></svg>", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><rect fill='url(http://x.fr/a)'/></svg>",
                    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><foreignObject/></svg>", "<!DOCTYPE svg [<!ENTITY a 'b'>]><svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'>&a;</svg>",
                    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'><style>@import 'x';</style></svg>", "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'>" + "<g/>" * 6000 + "</svg>"]
        for svg in bad_svgs:
            with self.subTest(svg=svg[:50]), self.assertRaises(ValueError):
                parse_logos({"logos": [{"idea": "Un rond.", "svg": svg}]})
        for bad in ({"logos": []}, {"logos": [{"idea": "Un rond.", "svg": good}] * 5}, {"logos": [{"idea": "", "svg": good}]}, {"logos": [{"svg": good}]}):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(ValueError):
                parse_logos(bad)

    def test_a_missing_input_or_file_is_an_error(self):
        self.assertEqual(self.run_cmd("judge", {"brief": {}}).returncode, 1)
        r = self.run_cmd("reader", {"image": "absent.png", "persona": "x"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("image", r.stderr)
        self.assertEqual(self.run_cmd("variant", {"dir": "piece"}).returncode, 1)

    def test_the_texts_are_checked_and_never_invent_a_figure(self):
        inputs = self.CASES["texts"][0]
        got = json.loads(self.run_cmd("texts", inputs).stdout)
        self.assertEqual(got["texts"], ["Du thé qui a fait la fête.", "Goûte.\nC'est bon."])
        self.assertIn("Nothing invented", json.loads(self.log.read_text().splitlines()[0])["argv"][1])
        self.assertEqual(self.run_cmd("texts", {"brief": {}}).returncode, 1)  # no brief: nothing to write from
        sys.path.insert(0, str(AGENTS))
        from answers import parse_texts
        one = {"kind": "accroche", "text": "Le goût d'abord."}
        for bad in ({"texts": [{**one, "text": "100 % naturel."}]}, {"texts": [{**one, "text": "Un thé — et c'est bon."}]}, {"texts": [one, one]},
                    {"texts": [{**one, "kind": "slogan"}]}, {"texts": [{**one, "text": "x" * 121}]}, {"texts": [one] * 2 + [{**one, "text": str(n)} for n in range(5)]}, {"texts": []}):
            with self.assertRaises(ValueError):
                parse_texts(bad)
        self.assertEqual(parse_texts({"texts": [{**one, "text": "100 % naturel."}]}, "100 % naturel"), ["100 % naturel."])  # a figure of the brief is allowed

    def test_the_variant_is_written_in_the_piece_and_only_its_own_files_are_seen(self):
        r = self.run_cmd("variant", self.CASES["variant"][0])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.tmp / "piece" / "variants" / "v1.json").read_text())["headline"], "Titre")
        self.assertEqual(self.calls()[0]["ls"], ["brand.md", "brief.md", "refs"])  # the logo line of the brand is left out of its copy

    def test_the_judge_and_the_readers_run_on_the_best_model_the_others_on_sonnet(self):
        for cmd, (inputs, _, _) in self.CASES.items():
            self.run_cmd(cmd, inputs)
        self.assertEqual([self.model_of(c) for c in self.calls()], ["sonnet"] * 7 + ["claude-fable-5-1"] * 2 + ["sonnet"])

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


if __name__ == "__main__":
    unittest.main()
