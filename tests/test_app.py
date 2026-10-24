"""The interface's API, served by the simulated studio: the whole path, the errors, the authentication hook."""

import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import server  # noqa: E402
from backend_stub import StubBackend  # noqa: E402


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve("127.0.0.1", 0, StubBackend(speed=0.01))
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method, path, body=None, code=200, headers=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                got, data = r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            got, data = err.code, json.loads(err.read())
            err.close()
        self.assertEqual(got, code, data)
        return data

    def wait(self, job):
        for _ in range(100):
            j = self.call("GET", f"/api/jobs/{job['id']}")
            if j["status"] != "running":
                return j
            time.sleep(0.02)
        self.fail("job never ended")

    def asks(self, pid):
        return [a["step"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]]

    def test_the_whole_path(self):
        pid = self.call("POST", "/api/projects", {"name": "test"})["id"]
        self.assertEqual(self.asks(pid), ["brand"])
        self.call("POST", f"/api/projects/{pid}/brief/../diverge", code=404)
        self.wait(self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"}))
        b = self.call("GET", f"/api/projects/{pid}/brand")
        self.assertEqual(len(b["evidence"]), 8)
        self.assertIn("brand", self.asks(pid))
        kept = [e["id"] for e in b["evidence"] if e["proposed"]]
        r = self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": kept, "logo": "logo-1"})
        self.assertEqual(r["discarded"], 8 - len(kept))
        self.assertEqual(self.asks(pid), ["brief"])
        self.call("POST", f"/api/projects/{pid}/diverge", code=409)
        brief = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        r = self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**brief, "format": "post-4x5, story, pub télé 30s"}})
        self.assertEqual(r["formats"], ["post-4x5", "story"])
        self.assertEqual(r["left_out"], ["pub télé 30s"])
        self.assertEqual(self.asks(pid), ["mandates"])
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": m["items"], "common": m["common"] + " Lumière du jour."})
        self.wait(self.call("POST", f"/api/projects/{pid}/diverge"))
        vs = self.call("GET", f"/api/projects/{pid}/variants")
        self.assertEqual([v["id"] for v in vs], ["v1", "v2", "v3", "v4"])
        pieces = self.call("POST", f"/api/projects/{pid}/pick", {"variants": ["v1", "v3"]})
        self.assertEqual([p["id"] for p in pieces], ["v1-post-4x5", "v1-story", "v3-post-4x5", "v3-story"])
        self.assertEqual(self.asks(pid).count("image"), 4)
        pc = "v1-story"
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose", code=409)
        self.call("PUT", f"/api/projects/{pid}/pieces/{pc}/prompt", {"prompt": "Un verre, lumière du jour, aucun texte."})
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        c = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        self.assertEqual(c["check"]["fail"], 0)
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "again"}, code=400)
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "again", "words": "trop sombre"})
        self.assertEqual(d["bans"], ["trop sombre"])
        self.assertIsNone(d["image"])
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        d = self.call("POST", f"/api/projects/{pid}/pieces/{pc}/decide", {"verdict": "keep", "words": "bon"})
        self.assertEqual(d["decision"]["verdict"], "keep")
        steps = {s["key"]: s["status"] for s in self.call("GET", f"/api/projects/{pid}")["steps"]}
        self.assertEqual(steps["brand"], "done")
        self.assertEqual(steps["diverge"], "done")

    def test_tasks_across_projects(self):
        a = self.call("POST", "/api/projects", {"name": "tâches A"})["id"]
        b = self.call("POST", "/api/projects", {"name": "tâches B"})["id"]
        t = self.call("GET", "/api/tasks")
        mine = [x for x in t["tasks"] if x["project"] in (a, b)]
        self.assertEqual([(x["project"], x["kind"], x["id"]) for x in mine], [(a, "brand-how", f"{a}:brand:"), (b, "brand-how", f"{b}:brand:")])
        self.assertEqual(mine[0]["project_name"], "tâches A")
        self.assertTrue(all(x["title"] and x["since"] for x in mine))
        self.assertEqual({x["id"] for x in t["projects"]} >= {a, b}, True)
        self.wait(self.call("POST", f"/api/projects/{a}/brand/learn", {"mode": "learn"}))
        mine = [x for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == a]
        self.assertEqual([(x["kind"], x["title"]) for x in mine], [("brand-sort", "Trier 8 visuels de la marque")])
        self.call("POST", f"/api/projects/{a}/brand/keep", {"kept": ["ev-01"], "logo": "logo-1"})
        self.assertEqual([x["kind"] for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == a], ["brief"])
        self.assertEqual(self.call("GET", f"/api/projects/{a}")["waiting"][0]["kind"], "brief")
        self.assertIsNone([x for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == a][0]["piece_label"])

    def test_tasks_lists_the_running_jobs_with_an_eta(self):
        pid = self.call("POST", "/api/projects", {"name": "en cours"})["id"]
        job = self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "learn"})
        running = [j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == job["id"]]
        for j in running:  # the stub runs at 1/100 speed: the job may already be over
            self.assertEqual((j["project"], j["kind"]), (pid, "learn"))
            self.assertGreaterEqual(j["eta"], 0)
        self.wait(job)
        self.assertEqual([j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == job["id"]], [])

    def test_declination_starts_from_another_project(self):
        src = self.call("POST", "/api/projects", {"name": "source"})["id"]
        self.wait(self.call("POST", f"/api/projects/{src}/brand/learn"))
        self.call("POST", f"/api/projects/{src}/brand/keep", {"kept": ["ev-01"], "logo": "logo-1"})
        new = self.call("POST", "/api/projects", {"name": "déclinaison", "from": src})
        self.assertEqual(new["waiting"][0]["step"], "brief")

    def test_brand_modes_since_and_running_jobs(self):
        pid = self.call("POST", "/api/projects", {"name": "modes"})["id"]
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer"}, code=400)
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer", "answers": "Un kombucha de port."})
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/brand")["answers"], "Un kombucha de port.")
        pid2 = self.call("POST", "/api/projects", {"name": "de rien"})["id"]
        self.call("POST", f"/api/projects/{pid2}/brand/learn", {"mode": "create"})
        self.assertEqual(self.call("GET", f"/api/projects/{pid2}/brand")["evidence"], [])
        p = self.call("GET", f"/api/projects/{pid}")
        self.assertIn("now", p)
        self.assertIsNotNone(p["steps"][0]["since"])
        self.assertEqual(p["jobs"], [])
        pid3 = self.call("POST", "/api/projects", {"name": "job"})["id"]
        job = self.call("POST", f"/api/projects/{pid3}/brand/learn", {"mode": "learn"})
        p = self.call("GET", f"/api/projects/{pid3}")
        if p["steps"][0]["status"] == "running":  # the stub runs at 1/100 speed: the job may already be over
            self.assertEqual([j["id"] for j in p["jobs"]], [job["id"]])
        self.wait(job)
        self.assertEqual(self.call("GET", f"/api/projects/{pid3}")["jobs"], [])

    def test_diverge_waits_for_the_person_once_instructions_are_read(self):
        pid = self.call("POST", "/api/projects", {"name": "d"})["id"]
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "answer", "answers": "x"})
        self.call("POST", f"/api/projects/{pid}/brand/keep", {"kept": ["ev-01"], "logo": "logo-1"})
        brief = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": brief})
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": m["items"], "common": m["common"]})
        self.assertEqual(self.asks(pid), ["diverge"])
        got = self.call("GET", f"/api/projects/{pid}/brief")
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**got["fields"], "format": "story, film 30s"}})
        got = self.call("GET", f"/api/projects/{pid}/brief")
        self.assertEqual((got["chosen"], got["left_out"]), (["story"], ["film 30s"]))

    def test_errors_and_health(self):
        self.assertTrue(self.call("GET", "/api/health")["ok"])
        self.call("GET", "/api/projects/nope", code=404)
        self.call("GET", "/api/nothing", code=404)
        pid = self.call("POST", "/api/projects", {})["id"]
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "guess"}, code=400)
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": ""}}, code=400)

    def test_token_auth(self):
        os.environ.update(STUDIO_AUTH="token", STUDIO_TOKEN="s3cret")
        try:
            self.call("GET", "/api/projects", code=401)
            self.call("GET", "/api/projects", headers={"Authorization": "Bearer wrong"}, code=401)
            self.call("GET", "/api/projects", headers={"Authorization": "Bearer s3cret"})
            self.call("GET", "/api/health")
        finally:
            os.environ.pop("STUDIO_AUTH")
            os.environ.pop("STUDIO_TOKEN")

    def test_static_stays_inside(self):
        with urllib.request.urlopen(self.base + "/stub/image.png") as r:
            self.assertEqual(r.headers["Content-Type"], "image/png")
        with urllib.request.urlopen(self.base + "/stub/image%2Epng") as r:  # an encoded name (the fonts have brackets) is found
            self.assertEqual(r.status, 200)
        req = urllib.request.Request(self.base + "/../server.py")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 404)
        cm.exception.close()


if __name__ == "__main__":
    unittest.main()
