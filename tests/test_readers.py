"""The readers: a brief with one to four personas written by the person, one reader per persona, each in a call of its own, beside the judge.
Each reading in "I": does the piece aim at me, what I understand, keep, do not read, miss, what bothers me; never whether I would buy.

The real backend's agents are the fake runner of test_backend_studio. Nothing here calls claude, codex or the network.

    python3 -m unittest discover -s tests
"""

import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
import workflow  # noqa: E402
from backend_stub import StubBackend  # noqa: E402
from test_backend_studio import png  # noqa: E402
from test_judge import BRIEF, RealJudge, StubJudge, drop  # noqa: E402

ARTISAN = "Tu as 55 ans, artisan, tu ne vas chez le médecin que quand ta femme insiste."
ETUDIANTE = "Tu as 20 ans, étudiante, tu bois ce que boivent tes amis."
KEYS = {"aimed", "why", "understand", "retain", "bother", "unread", "lacks"}


class Reading(unittest.TestCase):
    def test_personas_are_one_to_four_texts(self):
        self.assertEqual(workflow.personas_of(None), [])
        self.assertEqual(workflow.personas_of([" a ", "", "b\nc"]), ["a", "b c"])
        for bad in (["a"] * 5, "un texte", [1]):
            with self.assertRaises(ValueError):
                workflow.personas_of(bad)
        self.assertEqual(workflow.judge_brief({**BRIEF, "personas": [ARTISAN]})["personas"], [ARTISAN])
        self.assertEqual(workflow.judge_brief(BRIEF)["personas"], [])

    def test_a_reading_is_put_in_its_one_shape(self):
        r = workflow.parse_reading('Voilà : {"aimed": "no", "why": "Je ne bois pas de thé.", "understand": "", "retain": "", "bother": "",'
                                   ' "unread": "", "lacks": "", "buy": "non"}')
        self.assertEqual(set(r), KEYS)  # whether it would buy is never kept
        for bad in ("rien", {"aimed": "maybe"}, {"aimed": "yes", "why": " ", **{k: "" for k in workflow.READING_KEYS[1:]}}, {"aimed": "yes", "why": "x"}):
            with self.assertRaises(ValueError):
                workflow.parse_reading(bad)

    def test_where_a_reader_stands(self):
        ok = {"persona": "a", "reading": {"aimed": "yes"}}
        self.assertEqual(workflow.reader_view(0, "a", {"id": "j", "status": "running"}, ok)["status"], "running")
        self.assertEqual(workflow.reader_view(0, "a", {"id": "j", "status": "done"}, ok)["status"], "done")
        self.assertEqual(workflow.reader_view(0, "a", {"id": "j", "status": "failed", "error": "x"}, None)["error"], "x")
        self.assertEqual(workflow.reader_view(0, "b", None, ok)["status"], "todo")  # its persona changed since


class StubReaders(StubJudge):
    def readers_when(self, jid, done):
        return self.until(lambda: (lambda x: x if x["status"] != "running" and all(r["status"] in done for r in x["readers"]) else None)(self.call("GET", f"/api/judgements/{jid}")), "readers")

    def test_one_reader_per_persona_beside_the_judge(self):
        jg = drop(self.base, png(), meta={"brief": {**BRIEF, "personas": [ARTISAN, "fail " + ETUDIANTE]}})
        self.assertEqual([(r["n"], r["persona"], r["status"]) for r in jg["readers"]], [(0, ARTISAN, "running"), (1, "fail " + ETUDIANTE, "running")])
        jg = self.readers_when(jg["id"], ("done", "failed"))
        a, b = jg["readers"]
        self.assertEqual((a["status"], set(a["reading"])), ("done", KEYS))
        self.assertEqual((b["status"], b["reading"]), ("failed", None))
        self.assertIn("simulé", b["error"])
        self.assertEqual(jg["status"], "done")  # the judge stays as it is
        self.assertEqual(set(jg["verdict"]), {"target", "works", "snags", "unsourced", "brand", "missing"})
        job = self.call("POST", f"/api/judgements/{jg['id']}/readers/1/run")  # a reader is run again alone
        self.assertEqual(job["kind"], "reader")
        self.call("POST", f"/api/judgements/{jg['id']}/readers/1/run", code=409)
        self.call("POST", f"/api/judgements/{jg['id']}/readers/2/run", code=404)
        self.assertEqual(self.call("GET", f"/api/judgements/{jg['id']}")["readers"][0]["status"], "done")  # the other one keeps its reading

    def test_without_persona_nothing_changes(self):
        jg = drop(self.base, png(), meta={"brief": BRIEF})
        self.assertEqual((jg["readers"], jg["brief"]["personas"]), ([], []))

    def test_in_the_chain(self):
        pid = self.composed()
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "personas": ["a"] * 5}}, code=400)
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "personas": [ARTISAN]}})
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/brief")["fields"]["personas"], [ARTISAN])
        pc = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        self.assertEqual([r["status"] for r in pc["readers"]], ["running"])
        pc = self.until(lambda: (lambda x: x if x["readers"][0]["status"] == "done" else None)(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")), "reader")
        self.assertEqual(pc["readers"][0]["persona"], ARTISAN)
        self.assertEqual(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/readers/0/run")["kind"], "reader")
        d = self.call("POST", f"/api/projects/{pid}/pieces/v1-story/decide", {"verdict": "again", "words": "trop sombre"})
        self.assertEqual(d["readers"], [])  # sent back: a new piece will be read anew


class RealReaders(RealJudge):
    def test_each_reader_reads_alone(self):
        before = len(self.fake.calls)
        jg = drop(self.base, png(), meta={"brief": {**BRIEF, "personas": [ARTISAN, ETUDIANTE]}})
        jg = self.until(lambda: (lambda x: x if x["status"] == "done" and all(r["status"] == "done" for r in x["readers"]) else None)(
            self.call("GET", f"/api/judgements/{jg['id']}")), "readers")
        self.assertEqual([r["persona"] for r in jg["readers"]], [ARTISAN, ETUDIANTE])
        self.assertEqual(set(jg["readers"][0]["reading"]), KEYS)  # "buy" is left out
        calls = [c for c in self.fake.calls[before:] if Path(c["argv"][0]).name == "claude" and "./reading.json" in c["argv"][2]]
        self.assertEqual(len(calls), 2)  # one call per persona
        self.assertTrue(all(c["ls"] == ["inputs.md", "piece.png"] for c in calls))
        self.assertEqual(len({c["cwd"] for c in calls}), 2)  # each in a folder of its own
        self.assertIn("would buy", calls[0]["argv"][2])
        for text, me, other in ((t, *([ARTISAN, ETUDIANTE] if ARTISAN in t else [ETUDIANTE, ARTISAN])) for t in self.fake.readers):
            self.assertIn(me, text)
            self.assertNotIn(other, text)  # it does not see the other reader
            self.assertNotIn(BRIEF["message"], text)  # nor the brief
        self.assertNotIn(ARTISAN, self.fake.inputs)  # the judge does not read the personas
        saved = json.loads((self.home / "jugements" / jg["id"] / "jugement.json").read_text())
        self.assertEqual(saved["readings"]["1"]["persona"], ETUDIANTE)  # on the disk

    def test_a_failed_reader_is_run_again_alone(self):
        jg = drop(self.base, png(), meta={"brief": {**BRIEF, "personas": [ARTISAN, "fail"]}})
        jg = self.until(lambda: (lambda x: x if x["readers"][1]["status"] == "failed" and x["readers"][0]["status"] == "done" else None)(
            self.call("GET", f"/api/judgements/{jg['id']}")), "a failed reader")
        self.assertIn("le lecteur n'a pas écrit sa lecture", jg["readers"][1]["error"])
        self.wait(self.call("POST", f"/api/judgements/{jg['id']}/readers/1/run"), "failed")
        n = len(self.fake.readers)
        self.wait(self.call("POST", f"/api/judgements/{jg['id']}/readers/0/run"))
        self.assertEqual(len(self.fake.readers), n + 1)  # only that one
        self.call("POST", f"/api/judgements/{jg['id']}/readers/3/run", code=404)

    def test_in_the_chain(self):
        pid = self.composed()
        f = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**f, "personas": [ARTISAN]}})
        self.assertNotIn(ARTISAN, (self.pdir(pid) / "piece" / "brief.md").read_text())  # the studio's brief does not carry them
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        pc = self.until(lambda: (lambda x: x if x["readers"] and x["readers"][0]["status"] == "done" else None)(
            self.call("GET", f"/api/projects/{pid}/pieces/v1-story")), "reader")
        self.assertEqual(pc["readers"][0]["reading"]["aimed"], "partly")
        self.assertIn("titre : Titre de v1", self.fake.readers[-1])  # the words of the piece
        d = self.pdir(pid) / "piece" / "pieces" / "v1"
        self.assertTrue((d / "reader-0.json").exists())
        self.assertEqual(self.asks(pid), ["decide"])  # it blocks nothing
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")["readers"], [])
        self.assertFalse((d / "reader-0.json").exists())


def load_tests(loader, tests, pattern):
    """Only the tests written here: those the readers' classes take from the judge's run from test_judge."""
    suite = unittest.TestSuite()
    for cls in (Reading, StubReaders, RealReaders):
        suite.addTests(cls(n) for n in loader.getTestCaseNames(cls) if n in vars(cls))
    return suite

if __name__ == "__main__":
    unittest.main()
