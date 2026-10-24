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

    def wait(self, job, status="done"):
        for _ in range(100):
            j = self.call("GET", f"/api/jobs/{job['id']}")
            if j["status"] != "running":
                self.assertEqual(j["status"], status, j)
                return j
            time.sleep(0.02)
        self.fail("job never ended")

    def asks(self, pid):
        return [a["step"] for a in self.call("GET", f"/api/projects/{pid}")["waiting"]]

    # ---- the brand, in stages
    def brand(self, name="Brasserie du Quai", site="https://quai.example/"):
        body = {"name": name}
        if site:
            body["site"] = site
        return self.call("POST", "/api/brands", body)

    def read(self, name="Brasserie du Quai"):
        """A brand whose site is read: its visuals wait to be sorted."""
        b = self.brand(name)
        self.wait(b["jobs"][0])
        return b["id"]

    def sorted_brand(self, **kw):
        bid = self.read(**kw)
        ev = self.call("GET", f"/api/brands/{bid}")["assets"]["evidence"]
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in ev if e["proposed"]], "logo": "logo-1"})
        return bid

    def ready_brand(self, **kw):
        bid = self.sorted_brand(**kw)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "une brasserie de quartier", "who": "les voisins"}})
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["stage"], "ready")
        return bid

    def stage(self, bid):
        return self.call("GET", f"/api/brands/{bid}")["stage"]

    def test_the_studio_starts_with_brands_in_every_stage(self):
        brands = {b["id"]: b for b in self.call("GET", "/api/brands")}
        self.assertEqual({k: brands[k]["stage"] for k in ("marrowbay-ferments", "atelier-ondine", "kestrel-bakehouse")},
                         {"marrowbay-ferments": "ready", "atelier-ondine": "to_sort", "kestrel-bakehouse": "to_confirm"})
        ready = brands["marrowbay-ferments"]
        self.assertEqual([(p["name"], p["type"], p["rank"], p["step_label"]) for p in ready["projects"]],
                         [("Campagne de rentrée", "campagne", 4, "La divergence"), ("Lancement gingembre", "campagne", 2, "Le brief")])
        self.assertEqual((ready["waiting"], brands["atelier-ondine"]["waiting"]), (0, 1))
        ondine = brands["atelier-ondine"]["projects"][0]  # its brand is not sorted: step 1, and the rest waits
        self.assertEqual((ondine["rank"], ondine["step_label"], ondine["waiting"]), (1, "La marque", 0))

    def test_a_brand_in_full(self):
        b = self.call("GET", "/api/brands/marrowbay-ferments")
        self.assertEqual({k for k in b}, {"id", "name", "site", "description", "stage", "can_discover", "identity", "assets", "projects", "waiting", "jobs", "now"})
        self.assertEqual(list(b["identity"]), ["what", "who", "voice", "signature", "never", "colours"])
        self.assertTrue(all(set(v) == {"value", "state", "source"} for v in b["identity"].values()))
        self.assertEqual({v["state"] for v in b["identity"].values()}, {"confirmed"})
        a = b["assets"]
        self.assertEqual(set(a), {"logo", "colours", "visuals", "evidence", "logos"})
        self.assertEqual((a["logo"]["state"], len(a["colours"]), len(a["visuals"])), ("confirmed", 4, 4))
        self.assertTrue(all(set(c) == {"hex", "role", "state", "source"} for c in a["colours"]))
        self.assertTrue(all(set(e) == {"id", "kind", "note", "preview", "proposed", "kept"} for e in a["evidence"]))
        k = self.call("GET", "/api/brands/kestrel-bakehouse")  # the three states side by side
        self.assertEqual({n: v["state"] for n, v in k["identity"].items()},
                         {"what": "confirmed", "who": "confirmed", "voice": "deduced", "signature": "absent", "never": "absent", "colours": "deduced"})
        self.assertEqual(k["identity"]["signature"], {"value": "", "state": "absent", "source": ""})
        self.assertEqual((k["assets"]["logo"]["state"], k["waiting"][0]["kind"]), ("deduced", "brand-confirm"))
        self.call("GET", "/api/brands/nope", code=404)

    def test_the_brand_path_from_a_name_to_ready(self):
        b = self.brand()
        bid = b["id"]
        self.assertEqual((b["stage"], b["can_discover"], [j["kind"] for j in b["jobs"]], b["waiting"]), ("discovering", True, ["learn"], []))
        self.call("POST", f"/api/brands/{bid}/discover", code=409)  # already reading
        self.wait(b["jobs"][0])
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual((b["stage"], [t["kind"] for t in b["waiting"]], b["waiting"][0]["title"]), ("to_sort", ["brand-sort"], "Trier 8 visuels de la marque"))
        self.assertEqual(b["identity"]["voice"]["state"], "deduced")  # the brief is prefilled with what the reading found
        self.assertEqual(b["identity"]["never"]["state"], "absent")
        ev = b["assets"]["evidence"]
        kept = [e["id"] for e in ev if e["proposed"]]
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": ["ev-nope"], "logo": None}, code=400)
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": kept, "logo": "logo-9"}, code=400)
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": kept, "logo": "logo-1"})
        self.assertEqual((r["kept"], r["discarded"], r["stage"]), (len(kept), 8 - len(kept), "to_brief"))
        self.assertEqual((r["assets"]["logo"]["state"], len(r["assets"]["visuals"])), ("confirmed", len(kept)))
        self.assertEqual([t["kind"] for t in r["waiting"]], ["brand-brief"])
        g = self.call("GET", f"/api/brands/{bid}/brief")
        self.assertEqual((g["done"], g["fields"]["what"]["state"]), (False, "deduced"))
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"nope": "x"}}, code=400)
        brief = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "une brasserie de quartier", "who": "les voisins", "voice": "franc; chaleureux\ndrôle",
                                                                      "signature": "À la vôtre.", "never": "premium, artisanal", "colours": "du vert et du cuivre"}})
        self.assertEqual((brief["done"], brief["stage"]), (True, "to_confirm"))  # what is typed is confirmed; the measured colours still wait
        f = brief["fields"]
        self.assertEqual((f["what"]["state"], f["what"]["source"], f["voice"]["value"], f["never"]["value"]), ("confirmed", "tapé", "franc, chaleureux, drôle", "premium, artisanal"))
        self.assertEqual(f["colours"]["state"], "deduced")
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual(([t["kind"] for t in b["waiting"]], b["waiting"][0]["question"]), (["brand-confirm"], "Confirmer ce que le studio a déduit : ses couleurs."))
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": ["nope"]}, code=400)
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": ["signature", "logo"]})  # confirmed already: nothing changes
        self.assertEqual(self.stage(bid), "to_confirm")
        done = self.call("POST", f"/api/brands/{bid}/confirm", {"keys": ["colours"]})
        self.assertEqual((done["stage"], done["waiting"], {c["state"] for c in done["assets"]["colours"]}), ("ready", [], {"confirmed"}))

    def test_a_deduced_value_read_and_kept_is_confirmed_without_being_retyped(self):
        bid = self.sorted_brand(name="Maison Tide")
        got = self.call("GET", f"/api/brands/{bid}/brief")["fields"]
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {k: v["value"] for k, v in got.items()}})
        self.assertEqual(r["fields"]["what"], {"value": got["what"]["value"], "state": "confirmed", "source": got["what"]["source"]})  # confirmed, its source stays
        self.assertEqual((r["fields"]["colours"]["state"], r["stage"]), ("confirmed", "ready"))  # the whole form read and kept: nothing is left to confirm

    def test_the_rule_of_step_one(self):
        bid = self.read(name="Atelier Sel")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Premier tour"})["id"]
        p = self.call("GET", f"/api/projects/{pid}")
        self.assertEqual((p["brand"], p["brand_name"], p["type"], p["brand_stage"]), (bid, "Atelier Sel", "campagne", "to_sort"))
        self.assertEqual([(s["key"], s["status"]) for s in p["steps"][:3]], [("brand", "waiting"), ("brief", "todo"), ("mandates", "todo")])
        self.assertEqual(p["waiting"], [])  # the brand's tasks are the brand's, not the project's
        self.assertEqual(p["brand_waiting"], [{"kind": "brand-sort", "title": "Trier 8 visuels de la marque"}])
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o", "audience": "a", "message": "m"}}, code=409)
        ev = self.call("GET", f"/api/brands/{bid}")["assets"]["evidence"]
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in ev if e["proposed"]], "logo": "logo-1"})
        self.assertEqual(self.call("GET", f"/api/projects/{pid}")["steps"][0]["status"], "waiting")  # sorted, not ready: still waiting
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un atelier"}})
        self.assertEqual(self.call("GET", f"/api/projects/{pid}")["brand_stage"], "to_confirm")
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        p = self.call("GET", f"/api/projects/{pid}")
        self.assertEqual([(s["key"], s["status"]) for s in p["steps"][:2]], [("brand", "done"), ("brief", "waiting")])
        self.assertEqual(self.asks(pid), ["brief"])
        self.assertEqual(p["brand_waiting"], [])

    def test_a_project_while_the_brand_reads_its_site(self):
        b = self.brand(name="Atelier Vent")
        pid = self.call("POST", f"/api/brands/{b['id']}/projects", {"name": "Dès maintenant"})["id"]
        s = self.call("GET", f"/api/projects/{pid}")["steps"][0]
        self.assertEqual((s["status"], s["hand"], s["job"]), ("running", "studio", b["jobs"][0]["id"]))
        self.wait(b["jobs"][0])

    def test_brand_tasks_are_in_the_list_with_their_scope(self):
        t = self.call("GET", "/api/tasks")
        brand = [x for x in t["tasks"] if x["scope"] == "brand"]
        self.assertEqual({(x["brand"], x["kind"]) for x in brand} >= {("atelier-ondine", "brand-sort"), ("kestrel-bakehouse", "brand-confirm")}, True)
        one = next(x for x in brand if x["brand"] == "atelier-ondine")
        self.assertEqual((one["id"], one["brand_name"], one["project"]), ("@atelier-ondine:brand-sort", "Atelier Ondine", None))
        self.assertTrue(one["title"] and one["question"] and one["since"])
        proj = [x for x in t["tasks"] if x["scope"] == "project"]
        self.assertTrue(proj and all(x["brand"] and x["project"] and x["brand_name"] for x in proj))
        self.assertTrue(any(x["id"] == "campagne-de-rentree:diverge:" for x in proj))
        self.assertEqual([b["stage"] for b in t["brands"] if b["id"] == "marrowbay-ferments"], ["ready"])
        self.assertEqual(t["tasks"], sorted(t["tasks"], key=lambda x: (x["since"] is None, x["since"] or 0)))  # the oldest first, brand and project together
        self.assertEqual([x["brand"] for x in t["projects"] if x["id"] == "ouverture-de-la-saison"], ["atelier-ondine"])

    def test_a_brand_without_site_has_a_brief_and_no_reading(self):
        b = self.call("POST", "/api/brands", {"name": "Fonds de Cuve"})
        bid = b["id"]
        self.assertEqual((b["stage"], b["can_discover"], b["jobs"], [t["kind"] for t in b["waiting"]]), ("new", False, [], ["brand-brief"]))
        self.assertEqual(b["identity"]["what"], {"value": "", "state": "absent", "source": ""})
        self.call("POST", f"/api/brands/{bid}/discover", code=409)  # no site: nothing to read
        self.call("POST", f"/api/brands/{bid}/keep", {"kept": [], "logo": None}, code=409)  # nothing read: nothing to sort
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"who": "les caves"}}, code=400)  # what the brand is, at least
        self.assertFalse(self.call("GET", f"/api/brands/{bid}/brief")["done"])
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un fonds de cuve"}})
        self.assertEqual(r["stage"], "to_brief")  # no logo and nothing to find it in: a site is needed
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual((b["waiting"][0]["kind"], b["waiting"][0]["title"]), ("brand-brief", "Trouver le logo de la marque"))
        b = self.call("PUT", f"/api/brands/{bid}", {"site": "fonds.example"})
        self.assertEqual((b["site"], b["stage"], b["jobs"]), ("https://fonds.example/", "to_brief", []))  # a new site does not read by itself
        self.wait(self.call("POST", f"/api/brands/{bid}/discover"))
        self.assertEqual(self.stage(bid), "to_sort")

    def test_a_brand_is_created_from_a_name_alone(self):
        self.call("POST", "/api/brands", {"name": "  "}, code=400)
        self.call("POST", "/api/brands", {"name": "x", "site": "http://localhost:8000"}, code=400)
        a, b = self.call("POST", "/api/brands", {"name": "Même Nom"})["id"], self.call("POST", "/api/brands", {"name": "Même Nom"})["id"]
        self.assertNotEqual(a, b)

    def test_a_failed_reading_is_a_task_to_run_again(self):
        b = self.call("POST", "/api/brands", {"name": "Quai Mort", "site": "https://fail.example"})
        j = self.wait(b["jobs"][0], "failed")
        self.assertIn("n'a pas répondu", j["message"])
        b = self.call("GET", f"/api/brands/{b['id']}")
        self.assertEqual([t["kind"] for t in b["waiting"]], ["job-failed", "brand-brief"])
        self.assertIn("n'a pas répondu", b["waiting"][0]["question"])
        self.assertEqual(b["stage"], "to_brief")

    def test_a_brand_and_a_project_are_edited(self):
        bid = self.ready_brand(name="Nom Avant")
        b = self.call("PUT", f"/api/brands/{bid}", {"name": "Nom Après", "description": "Une brasserie.", "site": "https://apres.example/page"})
        self.assertEqual((b["id"], b["name"], b["description"], b["site"], b["stage"]), (bid, "Nom Après", "Une brasserie.", "https://apres.example/page", "ready"))
        self.call("PUT", f"/api/brands/{bid}", {"name": " "}, code=400)
        self.call("PUT", f"/api/brands/{bid}", {"site": "ftp://x.example"}, code=400)
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["name"], "Nom Après")
        self.call("PUT", "/api/brands/nope", {"name": "x"}, code=404)
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Avant"})["id"]
        p = self.call("PUT", f"/api/projects/{pid}", {"name": "Après"})
        self.assertEqual((p["id"], p["name"]), (pid, "Après"))
        self.call("PUT", f"/api/projects/{pid}", {"name": ""}, code=400)
        self.call("PUT", "/api/projects/nope", {"name": "x"}, code=404)
        self.assertEqual([x["name"] for x in self.call("GET", f"/api/brands/{bid}")["projects"]], ["Après"])

    def test_a_project_can_start_from_another_one_of_the_same_brand(self):
        a, other = self.ready_brand(name="Marque A"), self.ready_brand(name="Marque B")
        src = self.call("POST", f"/api/brands/{a}/projects", {"name": "Source"})["id"]
        f = self.call("GET", f"/api/projects/{src}/brief")["fields"]
        self.call("PUT", f"/api/projects/{src}/brief", {"fields": {**f, "objective": "o", "audience": "a", "message": "un message précis"}})
        new = self.call("POST", f"/api/brands/{a}/projects", {"name": "Déclinaison", "from": src})
        self.assertEqual((new["brand"], new["type"], [s["status"] for s in new["steps"][:3]]), (a, "campagne", ["done", "waiting", "todo"]))  # the brief is to read again
        got = self.call("GET", f"/api/projects/{new['id']}/brief")
        self.assertEqual((got["fields"]["message"], got["confirmed"]), ("un message précis", False))  # the fields, not the confirmation
        self.call("POST", f"/api/brands/{other}/projects", {"name": "x", "from": src}, code=400)  # another brand's project
        self.call("POST", f"/api/brands/{a}/projects", {"name": "x", "from": "nope"}, code=400)
        self.call("POST", "/api/brands/nope/projects", {"name": "x"}, code=404)

    def test_a_project_goes_its_way_in_a_ready_brand(self):
        bid = self.ready_brand(name="Chemin Complet")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Tout le chemin"})["id"]
        self.call("POST", f"/api/projects/{pid}/brief/../diverge", code=404)
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
        row = next(p for p in self.call("GET", f"/api/brands/{bid}")["projects"] if p["id"] == pid)
        self.assertEqual((row["rank"], row["step_label"]), (5, "Les images"))  # the other three pieces still wait for their image

    def test_tasks_lists_the_running_jobs_with_an_eta(self):
        b = self.brand(name="Quai Long")
        running = [j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == b["jobs"][0]["id"]]
        for j in running:  # the stub runs at 1/100 speed: the job may already be over
            self.assertEqual((j["project"], j["brand"], j["kind"]), (None, b["id"], "learn"))
            self.assertGreaterEqual(j["eta"], 0)
        self.wait(b["jobs"][0])
        self.assertEqual([j for j in self.call("GET", "/api/tasks")["jobs"] if j["id"] == b["jobs"][0]["id"]], [])
        self.assertEqual(self.call("GET", f"/api/brands/{b['id']}")["jobs"], [])

    def test_the_project_routes_of_the_brand_still_answer(self):
        """POST /api/projects finds the brand by its name (or makes it), and the brand routes of a project act on the brand."""
        bid = self.ready_brand(name="Marque Compat")
        pid = self.call("POST", "/api/projects", {"name": "En un coup", "brand": "marque compat"})["id"]
        self.assertEqual(self.call("GET", f"/api/projects/{pid}")["brand"], bid)
        new = self.call("POST", "/api/projects", {"name": "Neuve", "brand": "Marque Neuve", "site": "neuve.example"})
        self.assertEqual((new["brand_name"], new["brand_stage"]), ("Marque Neuve", "discovering"))
        self.call("POST", f"/api/projects/{new['id']}/brand/learn", {"mode": "learn"}, code=409)  # the site is being read already
        self.wait(self.call("GET", f"/api/brands/{new['brand']}")["jobs"][0])
        self.wait(self.call("POST", f"/api/projects/{new['id']}/brand/learn", {"mode": "learn"}))  # and can be read again
        b = self.call("GET", f"/api/projects/{new['id']}/brand")
        self.assertEqual(len(b["evidence"]), 8)
        r = self.call("POST", f"/api/projects/{new['id']}/brand/keep", {"kept": ["ev-01"], "logo": "logo-1"})
        self.assertEqual((r["kept"], r["logo"]), (1, "logo-1"))
        self.assertEqual(self.stage(new["brand"]), "to_brief")
        self.call("POST", f"/api/projects/{new['id']}/brand/learn", {"mode": "answer"}, code=400)
        self.call("POST", "/api/projects", {"name": "x"}, code=400)
        self.call("POST", "/api/projects", {"name": "x", "from": "nope"}, code=404)
        copy = self.call("POST", "/api/projects", {"name": "Copie", "from": pid})
        self.assertEqual(copy["brand"], bid)

    def test_errors_and_health(self):
        self.assertTrue(self.call("GET", "/api/health")["ok"])
        self.call("GET", "/api/projects/nope", code=404)
        self.call("GET", "/api/nothing", code=404)
        self.call("POST", "/api/projects", {}, code=400)
        self.call("POST", "/api/brands/nope/discover", code=404)
        self.call("GET", "/api/brands/nope/brief", code=404)
        self.call("POST", "/api/brands/nope/confirm", {}, code=404)
        bid = self.ready_brand(name="Pour les erreurs")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {})["id"]  # no name: a default one
        self.assertEqual(self.call("GET", f"/api/projects/{pid}")["name"], "Nouveau projet")
        self.call("POST", f"/api/projects/{pid}/brand/learn", {"mode": "guess"}, code=400)
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": ""}}, code=400)
        self.call("POST", f"/api/brands/{bid}/confirm", {"keys": "logo"}, code=400)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": ["what"]}, code=400)

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
