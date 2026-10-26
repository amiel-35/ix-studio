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
import workflow  # noqa: E402
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

    def fetch(self, path, code=200):
        """A route that answers a file: (headers, bytes)."""
        try:
            with urllib.request.urlopen(self.base + path) as r:
                got, head, data = r.status, r.headers, r.read()
        except urllib.error.HTTPError as err:
            got, head, data = err.code, err.headers, err.read()
            err.close()
        self.assertEqual(got, code, data[:200])
        return head, data

    def drop(self, bid, data, ctype="image/png", name="logo.png", code=200):
        """A file sent as the body of the request (the logo): its type is the Content-Type, its name the X-Filename header."""
        req = urllib.request.Request(self.base + f"/api/brands/{bid}/logo", method="POST", data=data, headers={"Content-Type": ctype, "X-Filename": name})
        try:
            with urllib.request.urlopen(req) as r:
                got, out = r.status, json.loads(r.read())
        except urllib.error.HTTPError as err:
            got, out = err.code, json.loads(err.read())
            err.close()
        self.assertEqual(got, code, out)
        return out

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

    def test_a_logo_dropped_makes_a_brand_without_site_ready(self):
        bid = self.call("POST", "/api/brands", {"name": "Fonds de Cuve Deux"})["id"]
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un fonds de cuve"}})
        self.assertEqual(self.stage(bid), "to_brief")  # no site and no logo: it can never be ready like this
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 40
        b = self.drop(bid, png)
        self.assertEqual((b["assets"]["logo"]["state"], b["assets"]["logo"]["source"], [x["note"] for x in b["assets"]["logos"]]),
                         ("confirmed", "choisi par toi", ["Logo déposé, png"]))
        self.assertTrue(b["assets"]["logo"]["preview"].startswith("data:image/png;base64,"))
        self.assertEqual((b["stage"], [(t["kind"], t["title"]) for t in b["waiting"]]), ("to_brief", [("brand-brief", "Choisir les couleurs de la marque")]))  # a logo is not enough
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un fonds de cuve", "colours": [{"hex": "#F4EFE6", "role": "background"}, {"hex": "#1e2a24", "role": "text"}]}})
        self.assertEqual((r["stage"], r["needs"]), ("ready", []))
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["waiting"], [])
        svg = self.drop(bid, b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><rect width="4" height="4"/></svg>', "image/svg+xml", "l.svg")
        self.assertEqual(len(svg["assets"]["logos"]), 2)  # the first one stays a candidate; the last one dropped is chosen
        self.assertEqual(svg["assets"]["logo"]["id"], svg["assets"]["logos"][1]["id"])

    def test_a_brand_is_ready_with_a_logo_and_two_colours_chosen_with_the_pickers(self):
        bid = self.call("POST", "/api/brands", {"name": "Deux Couleurs"})["id"]
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "une cave"}})
        self.drop(bid, b"\x89PNG\r\n\x1a\n" + b"0" * 8)
        g = self.call("GET", f"/api/brands/{bid}/brief")
        self.assertEqual((g["needs"], g["palette"]), (["colours"], {"background": None, "text": None, "accent": None}))
        for bad in ([{"hex": "#ffffff", "role": "background"}], [{"hex": "#ffffff", "role": "background"}, {"hex": "#ffffff", "role": "text"}],
                    [{"hex": "ffffff", "role": "background"}, {"hex": "#000000", "role": "text"}], [{"hex": "#ffffff", "role": "background"}, {"hex": "#000000", "role": "title"}],
                    [{"hex": "#ffffff", "role": "background"}, {"hex": "#000000", "role": "text"}, {"hex": "#ff0000", "role": "text"}]):
            self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "une cave", "colours": bad}}, code=400)
        self.assertEqual(self.stage(bid), "to_brief")
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"colours": [{"hex": "#ffffff", "role": "background"}, {"hex": "#112233", "role": "text"}, {"hex": "#C8553D", "role": "accent"}]}})
        self.assertEqual((r["stage"], r["needs"], r["palette"]), ("ready", [], {"background": "#ffffff", "text": "#112233", "accent": "#c8553d"}))
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual([(c["hex"], c["role"], c["state"]) for c in b["assets"]["colours"]], [("#ffffff", "background", "confirmed"), ("#112233", "text", "confirmed"), ("#c8553d", "accent", "confirmed")])
        self.assertEqual(b["identity"]["colours"]["state"], "confirmed")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Premier"})["id"]
        self.assertEqual(self.asks(pid), ["brief"])  # the project passes step one

    def test_a_site_that_gave_one_colour_is_not_ready(self):
        bid = self.read(name="Une Couleur")
        ev = self.call("GET", f"/api/brands/{bid}")["assets"]["evidence"]
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": [ev[0]["id"]], "logo": "logo-1"})  # one visual kept: one colour measured
        self.assertEqual(len(r["assets"]["colours"]), 1)
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "x"}})
        self.call("POST", f"/api/brands/{bid}/confirm", {})
        b = self.call("GET", f"/api/brands/{bid}")
        self.assertEqual((b["stage"], [t["title"] for t in b["waiting"]]), ("to_brief", ["Choisir les couleurs de la marque"]))
        self.assertEqual(self.call("GET", f"/api/brands/{bid}/brief")["palette"]["background"], b["assets"]["colours"][0]["hex"])  # the one colour is proposed
        self.assertEqual(self.asks(self.call("POST", f"/api/brands/{bid}/projects", {"name": "x"})["id"]), [])  # the project waits for its brand
        r = self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"colours": [{"hex": "#ffffff", "role": "background"}, {"hex": "#112233", "role": "text"}]}})
        self.assertEqual((r["stage"], r["needs"]), ("ready", []))

    def test_a_logo_dropped_is_checked(self):
        bid = self.call("POST", "/api/brands", {"name": "Contrôle Logo"})["id"]
        self.drop(bid, b"hello", "text/plain", code=400)
        self.drop(bid, b"GIF89a....", "image/gif", code=400)
        self.drop(bid, b"not a png at all", "image/png", code=400)
        self.drop(bid, b"\xff\xd8\xff" + b"0" * 10, "image/png", code=400)  # a jpg sent as a png
        self.drop(bid, b"", "image/png", code=400)
        self.drop(bid, b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "image/svg+xml", code=400)
        self.drop(bid, b'<svg xmlns="http://www.w3.org/2000/svg" onload="x()"></svg>', "image/svg+xml", code=400)
        self.drop(bid, b"<html></html>", "image/svg+xml", code=400)
        self.drop(bid, b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024), "image/png", code=400)  # too big
        self.drop("nope", b"\x89PNG\r\n\x1a\n" + b"0" * 4, code=404)
        self.assertIsNone(self.call("GET", f"/api/brands/{bid}")["assets"]["logo"])
        self.call("POST", f"/api/brands/{bid}/logo", {"x": 1}, code=400)  # JSON is not a file
        self.assertTrue(self.drop(bid, b"\xff\xd8\xff" + b"0" * 10, "image/jpeg")["assets"]["logo"])

    def test_a_logo_dropped_after_the_reading_leaves_the_sort_as_it_was(self):
        bid = self.read(name="Logo Après")
        ev = self.call("GET", f"/api/brands/{bid}")["assets"]["evidence"]
        b = self.drop(bid, b"\x89PNG\r\n\x1a\n" + b"0" * 8)
        self.assertEqual((b["stage"], len(b["assets"]["logos"]), b["assets"]["evidence"] == ev), ("to_sort", 3, True))  # still to sort, with the logo already chosen
        r = self.call("POST", f"/api/brands/{bid}/keep", {"kept": [e["id"] for e in ev if e["proposed"]], "logo": b["assets"]["logo"]["id"]})
        self.assertEqual((r["stage"], r["assets"]["logo"]["id"]), ("to_brief", b["assets"]["logo"]["id"]))

    def test_a_project_of_the_brand_says_when_it_is_done(self):
        b = self.call("GET", "/api/brands/marrowbay-ferments")
        self.assertEqual([p["done"] for p in b["projects"]], [False, False])
        self.assertTrue(all(isinstance(p["done"], bool) for x in self.call("GET", "/api/brands") for p in x["projects"]))

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
        self.assertEqual(self.asks(pid).count("image"), 2)  # one prompt task per variant, not per piece
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

    def a_series(self, name, variants=("v1", "v3"), formats="post-4x5, story"):
        bid = self.ready_brand(name=name)
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "La série"})["id"]
        brief = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**brief, "format": formats}})
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": m["items"], "common": m["common"]})
        self.wait(self.call("POST", f"/api/projects/{pid}/diverge"))
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": list(variants)})
        return pid

    def test_a_prompt_is_one_task_per_variant_and_its_formats_share_it(self):
        pid = self.a_series("Par Variante")
        t = [x for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == pid]
        self.assertEqual([(x["kind"], x["variant"], x["pieces"], x["piece"], x["piece_label"], x["title"]) for x in t],
                         [("prompt", "v1", ["v1-post-4x5", "v1-story"], "v1-post-4x5", "v1", "Relire le prompt de v1 (2 formats)"),
                          ("prompt", "v3", ["v3-post-4x5", "v3-story"], "v3-post-4x5", "v3", "Relire le prompt de v3 (2 formats)")])
        self.assertEqual(t[0]["id"], f"{pid}:image:v1-post-4x5")
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": "Un verre, lumière du jour, aucun texte."})
        self.assertEqual([x["id"] for x in r], ["v1-post-4x5", "v1-story"])
        for i in ("v1-post-4x5", "v1-story"):
            self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/{i}")["prompt"], "Un verre, lumière du jour, aucun texte.")
        self.assertNotEqual(self.call("GET", f"/api/projects/{pid}/pieces/v3-story")["prompt"], "Un verre, lumière du jour, aucun texte.")  # the other variant stays
        self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": " "}, code=400)
        self.call("PUT", f"/api/projects/{pid}/variants/v9/prompt", {"prompt": "x"}, code=404)
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/prompt", {"prompt": "Un autre."})  # only the piece that still waits for its image
        self.assertEqual([x["id"] for x in r], ["v1-post-4x5"])
        self.assertEqual([x["variant"] for x in self.call("GET", "/api/tasks")["tasks"] if x["project"] == pid and x["kind"] == "prompt"], ["v1", "v3"])

    def test_the_words_of_a_variant_can_be_corrected_until_it_is_composed(self):
        pid = self.a_series("Les Mots")
        self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "  "}, code=400)
        self.call("PUT", f"/api/projects/{pid}/variants/v9/text", {"headline": "x"}, code=404)
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Acide,\npuis doux.", "subline": "Servez-vous."})
        self.assertEqual([(x["id"], x["headline"], x["subline"]) for x in r], [("v1-post-4x5", "Acide, puis doux.", "Servez-vous."), ("v1-story", "Acide, puis doux.", "Servez-vous.")])
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v3-story")["headline"], "Quatorze jours dans une ville de port.")  # the other variant stays
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Acide, puis doux, puis rien."})  # the subline left out stays
        self.assertEqual((r[0]["headline"], r[0]["subline"]), ("Acide, puis doux, puis rien.", "Servez-vous."))
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Acide.", "subline": ""})  # an empty one takes it off
        self.assertEqual((r[0]["headline"], r[0]["subline"]), ("Acide.", ""))
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-story/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/compose")
        r = self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Doux."})  # only the piece that is not composed yet
        self.assertEqual([x["id"] for x in r], ["v1-post-4x5"])
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/pieces/v1-story")["headline"], "Acide.")
        self.wait(self.call("POST", f"/api/projects/{pid}/pieces/v1-post-4x5/image"))
        self.call("POST", f"/api/projects/{pid}/pieces/v1-post-4x5/compose")
        self.call("PUT", f"/api/projects/{pid}/variants/v1/text", {"headline": "Trop tard."}, code=409)

    def test_all_the_images_are_drawn_at_once_and_all_the_pieces_composed(self):
        pid = self.a_series("Par Lot")
        self.call("POST", f"/api/projects/{pid}/images", {"variant": "v9"}, code=400)
        jobs = self.call("POST", f"/api/projects/{pid}/images", {"variant": "v1"})["jobs"]
        self.assertEqual(sorted(j["piece"] for j in jobs), ["v1-post-4x5", "v1-story"])
        self.call("POST", f"/api/projects/{pid}/images", {"variant": "v1"}, code=409)  # drawn or being drawn
        jobs = self.call("POST", f"/api/projects/{pid}/images")["jobs"]  # all the others
        self.assertEqual(sorted(j["piece"] for j in jobs), ["v3-post-4x5", "v3-story"])
        self.call("POST", f"/api/projects/{pid}/compose", code=409)  # no image yet (the jobs have not ended): nothing to compose
        for _ in range(100):
            if not self.call("GET", "/api/tasks")["jobs"] or all(j["project"] != pid for j in self.call("GET", "/api/tasks")["jobs"]):
                break
            time.sleep(0.02)
        self.assertEqual(self.asks(pid), ["piece"] * 4)
        r = self.call("POST", f"/api/projects/{pid}/compose")
        self.assertEqual((sorted(r["composed"]), r["failed"]), (["v1-post-4x5", "v1-story", "v3-post-4x5", "v3-story"], []))
        self.assertEqual(self.asks(pid), ["decide"] * 4)
        self.call("POST", f"/api/projects/{pid}/compose", code=409)
        self.call("POST", f"/api/projects/{pid}/images", code=409)

    def test_the_pieces_are_taken_out_one_by_one_and_in_a_zip(self):
        import io
        import zipfile
        bid = self.ready_brand(name="Sortie")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "La sortie"})["id"]
        brief = self.call("GET", f"/api/projects/{pid}/brief")["fields"]
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {**brief, "format": "post-4x5, story"}})
        m = self.call("GET", f"/api/projects/{pid}/mandates")
        self.call("PUT", f"/api/projects/{pid}/mandates", {"items": m["items"], "common": m["common"]})
        self.wait(self.call("POST", f"/api/projects/{pid}/diverge"))
        self.call("POST", f"/api/projects/{pid}/pick", {"variants": ["v1", "v2"]})
        self.fetch(f"/api/projects/{pid}/pieces/v1-story/download", code=409)  # not composed yet
        self.fetch(f"/api/projects/{pid}/download", code=409)  # nothing kept yet
        for pc in ("v1-story", "v2-story"):
            self.wait(self.call("POST", f"/api/projects/{pid}/pieces/{pc}/image"))
            self.call("POST", f"/api/projects/{pid}/pieces/{pc}/compose")
        head, data = self.fetch(f"/api/projects/{pid}/pieces/v1-story/download")
        self.assertEqual((head["Content-Type"], head["Content-Disposition"]), ("image/png", f'attachment; filename="{pid}-v1-story.png"'))
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.fetch(f"/api/projects/{pid}/pieces/nope/download", code=404)
        self.fetch(f"/api/projects/{pid}/download", code=409)  # composed is not kept
        self.call("POST", f"/api/projects/{pid}/pieces/v2-story/decide", {"verdict": "keep"})
        self.call("POST", f"/api/projects/{pid}/pieces/v1-story/decide", {"verdict": "again", "words": "trop sombre"})
        head, data = self.fetch(f"/api/projects/{pid}/download")
        self.assertEqual((head["Content-Type"], head["Content-Disposition"]), ("application/zip", f'attachment; filename="{pid}.zip"'))
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertEqual(z.namelist(), [f"{pid}-v2-story.png"])  # only what is kept
        self.assertTrue(z.read(z.namelist()[0]).startswith(b"\x89PNG"))

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

    def test_the_personas_of_a_brand_are_proposed_then_corrected_and_only_the_kept_ones_stay(self):
        bid = self.call("POST", "/api/brands", {"name": "Pour les personas"})["id"]
        empty = self.call("GET", f"/api/brands/{bid}/personas")
        self.assertEqual((empty["personas"], empty["proposed"], empty["can_propose"], empty["job"]), ([], [], False, None))
        self.call("POST", f"/api/brands/{bid}/personas/propose", code=409)  # no brief of the brand yet: nothing to work from
        self.call("PUT", f"/api/brands/{bid}/personas", {"personas": ["Tu écris ce persona toi-même."]})  # but the person may write them
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un kombucha de port"}})
        job = self.call("POST", f"/api/brands/{bid}/personas/propose")
        self.assertEqual(job["kind"], "personas")
        self.call("POST", f"/api/brands/{bid}/personas/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/brands/{bid}/personas")
        self.assertEqual(got["personas"], ["Tu écris ce persona toi-même."])  # a proposal never becomes the brand's by itself
        self.assertTrue(1 <= len(got["proposed"]) <= 4)
        for text in got["proposed"]:
            lines = text.splitlines()
            self.assertEqual(lines[0], "Hypothèses à corriger, pas des faits.")
            self.assertTrue(lines[1].startswith("Besoin principal : "))
            self.assertTrue(all(ln.startswith(("(dossier) ", "(supposé) ")) for ln in lines[2:]), text)
        self.assertEqual(len({t.splitlines()[1] for t in got["proposed"]}), len(got["proposed"]))  # each its own need
        kept = [got["proposed"][0] + "\nTu lis le journal du quartier.", "", got["personas"][0]]
        r = self.call("PUT", f"/api/brands/{bid}/personas", {"personas": kept})
        self.assertEqual((r["personas"], r["proposed"]), ([kept[0], kept[2]], []))
        self.call("PUT", f"/api/brands/{bid}/personas", {"personas": ["a", "b", "c", "d", "e"]}, code=400)
        self.call("PUT", f"/api/brands/{bid}/personas", {"personas": "a"}, code=400)
        self.call("GET", "/api/brands/nope/personas", code=404)

    def test_the_storyboard_of_a_project_is_proposed_saved_and_only_then_rendered(self):
        pid = next(x["id"] for x in self.call("GET", "/api/projects") if x["name"] == "Campagne de rentrée")  # its brief is confirmed
        got = self.call("GET", f"/api/projects/{pid}/storyboard")
        self.assertEqual((got["shots"], got["saved"], got["can_propose"], got["film"]), ([], False, True, None))
        self.call("POST", f"/api/projects/{pid}/storyboard/render", code=409)
        job = self.call("POST", f"/api/projects/{pid}/storyboard/propose")
        self.assertEqual(job["kind"], "storyboard")
        self.call("POST", f"/api/projects/{pid}/storyboard/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/projects/{pid}/storyboard")
        self.assertTrue(5 <= len(got["shots"]) <= 8 and 15 <= sum(x["seconds"] for x in got["shots"]) <= 30)
        self.assertEqual((got["saved"], got["film"]), (False, None))
        self.call("POST", f"/api/projects/{pid}/storyboard/render", code=409)  # proposed, not saved
        shots = [{**got["shots"][0], "text": "Corrigé"}, *got["shots"][1:]]
        self.call("PUT", f"/api/projects/{pid}/storyboard", {"script": got["script"], "shots": [{**shots[0], "seconds": 0}, *shots[1:]]}, code=400)
        self.assertEqual(self.call("PUT", f"/api/projects/{pid}/storyboard", {"script": got["script"], "shots": shots})["saved"], True)
        self.wait(self.call("POST", f"/api/projects/{pid}/storyboard/render"))
        got = self.call("GET", f"/api/projects/{pid}/storyboard")
        self.assertEqual((got["shots"][0]["text"], got["film_job"]), ("Corrigé", None))
        self.assertEqual(self.fetch("/" + got["film"]["url"])[1][4:8], b"ftyp")
        self.assertEqual(self.fetch(f"/api/projects/{pid}/storyboard/film")[0]["Content-Type"], "video/mp4")
        self.call("GET", "/api/projects/nope/storyboard", code=404)

    def test_names_of_a_brand_are_proposed_kept_or_dropped_and_the_chosen_one_becomes_its_name(self):
        bid = self.call("POST", "/api/brands", {"name": "sans nom"})["id"]
        empty = self.call("GET", f"/api/brands/{bid}/names")
        self.assertEqual((empty["name"], empty["names"], empty["proposed"], empty["can_propose"], empty["job"]), ("sans nom", [], [], False, None))
        self.call("POST", f"/api/brands/{bid}/names/propose", code=409)  # no brief of the brand yet
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un kombucha de port"}})
        job = self.call("POST", f"/api/brands/{bid}/names/propose")
        self.assertEqual(job["kind"], "names")
        self.call("POST", f"/api/brands/{bid}/names/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/brands/{bid}/names")
        self.assertEqual(got["names"], [])  # a proposal never becomes the brand's by itself
        self.assertTrue(1 <= len(got["proposed"]) <= 8)
        self.assertTrue(all(x["name"] and x["why"] for x in got["proposed"]))
        kept = [got["proposed"][0], {"name": "Mon nom à moi", "why": ""}, {"name": "", "why": "vide"}, {"name": "mon nom à moi"}]
        r = self.call("PUT", f"/api/brands/{bid}/names", {"names": kept})  # the others dropped, one written, the empty and the repeated left out
        self.assertEqual((r["names"], r["proposed"], r["name"]), (kept[:2], [], "sans nom"))
        self.call("PUT", f"/api/brands/{bid}/names", {"names": kept[:2], "chosen": "Ailleurs"}, code=400)
        r = self.call("PUT", f"/api/brands/{bid}/names", {"names": kept[:2], "chosen": "Mon nom à moi"})
        self.assertEqual(r["name"], "Mon nom à moi")
        self.assertEqual(self.call("GET", f"/api/brands/{bid}")["name"], "Mon nom à moi")
        self.call("PUT", f"/api/brands/{bid}/names", {"names": [{"name": str(n)} for n in range(9)]}, code=400)
        self.call("PUT", f"/api/brands/{bid}/names", {"names": ["a"]}, code=400)
        self.call("GET", "/api/brands/nope/names", code=404)
    # export
    def test_the_brand_folder_is_a_zip_with_brand_md_and_a_brand_json_that_says_what_is_missing(self):
        import io, zipfile
        bid = self.call("POST", "/api/brands", {"name": "Pour l'export"})["id"]
        head, data = self.fetch(f"/api/brands/{bid}/export")
        self.assertIn(f'filename="{bid}-dossier-de-marque.zip"', head["Content-Disposition"])
        z = zipfile.ZipFile(io.BytesIO(data))
        card = json.loads(z.read("brand.json"))
        self.assertEqual(sorted(z.namelist()), ["brand.json", "brand.md"])
        self.assertEqual(card["name"], "Pour l'export")
        self.assertEqual(card["missing"], ["promise.signature_line"])
        self.assertTrue(all(v["value"] is None for v in card["values"] if v["status"] == "ask"))
        self.assertEqual(self.fetch(f"/api/brands/{bid}/export")[1], data)  # plausible and fixed
        self.fetch("/api/brands/nope/export", code=404)

    # interview
    def test_the_interview_pre_fills_the_brief_and_what_nobody_said_stays_empty(self):
        pid = self.call("GET", "/api/projects")[0]["id"]
        got = self.call("GET", f"/api/projects/{pid}/interview")
        self.assertEqual((len(got["questions"]), got["proposed"], got["job"], got["error"]), (5, None, None, None))
        self.call("POST", f"/api/projects/{pid}/interview", {"answers": ["a"] * 6}, code=400)
        self.call("POST", f"/api/projects/{pid}/interview", {"answers": ["", " "]}, code=400)
        self.call("POST", f"/api/projects/{pid}/interview", {}, code=400)
        job = self.call("POST", f"/api/projects/{pid}/interview", {"answers": ["Faire connaître", "", "Du thé qui a fait la fête"]})
        self.assertEqual(job["kind"], "interview")
        self.call("POST", f"/api/projects/{pid}/interview", {"answers": ["a"]}, code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/projects/{pid}/interview")
        f = got["proposed"]["fields"]
        self.assertEqual((f["audience"], f["cta"], got["proposed"]["missing"]), ("", "", ["audience"]))  # not answered: empty and flagged
        self.assertTrue(f["objective"] and f["message"])
        job = self.call("POST", f"/api/projects/{pid}/interview", {"answers": ["fail"]})  # a simulated failure
        self.wait(job, "failed")
        got = self.call("GET", f"/api/projects/{pid}/interview")
        self.assertEqual((got["proposed"], bool(got["error"])), (None, True))
        self.call("GET", "/api/projects/nope/interview", code=404)

    def test_the_interview_answer_is_checked(self):
        ok = {"objective": "Vendre.", "audience": "Les familles.", "message": "M", "cta": "", "fixed": ""}
        self.assertEqual(workflow.parse_interview("Voici " + json.dumps(ok), ["a", "b", "c"]),
                         {"fields": {**ok, "message": "M", "cta": "", "fixed": ""}, "missing": []})
        self.assertEqual(workflow.parse_interview(ok, ["a"])["missing"], ["audience"])
        for bad in ("rien", "{pas du json}", {"objective": 3}, ["x"]):
            with self.assertRaises(ValueError):
                workflow.parse_interview(bad, ["a"])

    # logos
    def test_logo_tracks_are_proposed_kept_or_dropped_and_the_chosen_one_becomes_the_logo(self):
        bid = self.call("POST", "/api/brands", {"name": "Cabane"})["id"]
        empty = self.call("GET", f"/api/brands/{bid}/logo/tracks")
        self.assertEqual((empty["tracks"], empty["proposed"], empty["can_propose"], empty["job"]), ([], [], True, None))
        job = self.call("POST", f"/api/brands/{bid}/logo/propose")  # a name is enough
        self.assertEqual(job["kind"], "logos")
        self.call("POST", f"/api/brands/{bid}/logo/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/brands/{bid}/logo/tracks")
        self.assertEqual(got["tracks"], [])  # a proposal never becomes the brand's by itself
        self.assertTrue(1 <= len(got["proposed"]) <= 4)
        self.assertTrue(all(t["id"] and t["idea"] and "cabane" in t["svg"].lower() for t in got["proposed"]))
        first = got["proposed"][0]
        self.call("POST", f"/api/brands/{bid}/logo/choose", {"id": first["id"]}, code=400)  # not kept yet
        self.call("PUT", f"/api/brands/{bid}/logo/tracks", {"keep": ["nope"]}, code=400)
        r = self.call("PUT", f"/api/brands/{bid}/logo/tracks", {"keep": [first["id"]]})
        self.assertEqual((r["tracks"], r["proposed"]), ([first], []))
        self.assertFalse(self.call("GET", f"/api/brands/{bid}")["assets"]["logo"])
        self.call("POST", f"/api/brands/{bid}/logo/choose", {"id": first["id"]})
        self.assertTrue(self.call("GET", f"/api/brands/{bid}")["assets"]["logo"])
        self.call("GET", "/api/brands/nope/logo/tracks", code=404)

    # competitors
    def test_the_competitors_of_a_brand_are_proposed_then_corrected_and_only_the_kept_ones_stay(self):
        bid = self.call("POST", "/api/brands", {"name": "Pour les concurrents"})["id"]
        empty = self.call("GET", f"/api/brands/{bid}/competitors")
        self.assertEqual((empty["competitors"], empty["proposed"], empty["can_propose"], empty["job"]), ([], [], False, None))
        self.call("POST", f"/api/brands/{bid}/competitors/propose", code=409)  # no brief of the brand yet: nothing to work from
        self.call("PUT", f"/api/brands/{bid}/competitors", {"competitors": ["Écrit à la main."]})  # but the person may write them
        self.call("PUT", f"/api/brands/{bid}/brief", {"fields": {"what": "un kombucha de port"}})
        job = self.call("POST", f"/api/brands/{bid}/competitors/propose")
        self.assertEqual(job["kind"], "competitors")
        self.call("POST", f"/api/brands/{bid}/competitors/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/brands/{bid}/competitors")
        self.assertEqual(got["competitors"], ["Écrit à la main."])  # a proposal never becomes the brand's by itself
        self.assertTrue(1 <= len(got["proposed"]) <= 6)
        for text in got["proposed"]:
            lines = text.splitlines()
            self.assertEqual(lines[0], "Hypothèse à vérifier, pas un fait.")
            self.assertRegex(lines[1], r"^Nom : .+ \((dossier|supposé)\)$")
            self.assertTrue(lines[2].startswith("Vend : ") and lines[3].startswith("Se distingue : "), text)
        kept = [got["proposed"][0] + " Corrigé.", "", got["competitors"][0]]  # one kept and corrected, the others dropped, the hand-written one kept
        r = self.call("PUT", f"/api/brands/{bid}/competitors", {"competitors": kept})
        self.assertEqual((r["competitors"], r["proposed"]), ([kept[0], kept[2]], []))
        self.call("PUT", f"/api/brands/{bid}/competitors", {"competitors": ["a"] * 7}, code=400)
        self.call("PUT", f"/api/brands/{bid}/competitors", {"competitors": "a"}, code=400)
        self.call("GET", "/api/brands/nope/competitors", code=404)

    def test_landscape_a_market_gives_its_players_and_nothing_is_kept_until_attached(self):
        bid = self.call("POST", "/api/brands", {"name": "Cabane"})["id"]
        self.call("POST", "/api/competitors", {}, code=400)
        self.call("POST", "/api/competitors", {"market": "  "}, code=400)
        got = self.call("POST", "/api/competitors", {"market": "Le kombucha en canette."})["competitors"]
        self.assertEqual(len(got), 4)
        self.assertTrue(all(t.startswith("Hypothèse à vérifier, pas un fait.\nNom : ") for t in got))
        self.assertEqual(self.call("GET", f"/api/brands/{bid}/competitors")["competitors"], [])  # shown, not kept
        r = self.call("PUT", f"/api/brands/{bid}/competitors", {"competitors": got[:2]})  # attached to a brand
        self.assertEqual(r["competitors"], got[:2])

    def test_the_competitors_agent_answer_is_checked(self):
        ok = {"competitors": [{"name": "A", "from": "suppose", "sells": "du thé", "differs": "plus doux"}]}
        self.assertEqual(workflow.parse_competitors("Voici " + json.dumps(ok)), ["Hypothèse à vérifier, pas un fait.\nNom : A (supposé)\nVend : du thé\nSe distingue : plus doux"])
        for bad in ("rien", "{pas du json}", {"competitors": []}, {"competitors": [ok["competitors"][0]] * 7},
                    {"competitors": [ok["competitors"][0], ok["competitors"][0]]}, {"competitors": [{**ok["competitors"][0], "from": "vu"}]},
                    {"competitors": [{**ok["competitors"][0], "differs": ""}]}):
            with self.assertRaises(ValueError):
                workflow.parse_competitors(bad)

    def test_the_brief_of_a_project_is_downloaded_in_markdown(self):
        bid = self.ready_brand(name="Brief à emporter")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "À emporter"})["id"]
        head, data = self.fetch(f"/api/briefs/{pid}/export")  # confirmed or not, the same fixed brief
        self.assertTrue(head["Content-Type"].startswith("text/markdown"))
        self.assertRegex(head["Content-Disposition"], r'^attachment; filename="[^"]+\.md"$')
        md = data.decode("utf-8")
        for title in ("## Objectif", "## Cible", "## Message", "## Format", "## Ce qui est fixé", "## Appel à l'action", "## Ce qui manque"):
            self.assertIn(title, md)
        self.fetch("/api/briefs/nope/export", code=404)

    def test_a_project_named_outside_latin_1_is_downloaded_under_an_ascii_name_in_the_simulated_studio_too(self):
        bid = self.ready_brand(name="Marque hors latin-1")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Cœur 投资"})["id"]
        head, _ = self.fetch(f"/api/briefs/{pid}/export")
        self.assertEqual(head["Content-Disposition"], 'attachment; filename="brief-cur.md"')

    def test_the_research_of_a_brand_is_proposed_then_kept_or_dropped_and_only_the_kept_ones_stay(self):
        bid = self.call("POST", "/api/brands", {"name": "Pour la recherche"})["id"]
        empty = self.call("GET", f"/api/brands/{bid}/research")
        self.assertEqual((empty["research"], empty["proposed"], empty["job"]), ([], [], None))
        job = self.call("POST", f"/api/brands/{bid}/research/propose")  # a name is enough
        self.assertEqual(job["kind"], "research")
        self.call("POST", f"/api/brands/{bid}/research/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/brands/{bid}/research")
        self.assertEqual(got["research"], [])  # a proposal never becomes the brand's by itself
        self.assertTrue(1 <= len(got["proposed"]) <= 10)
        for x in got["proposed"]:
            self.assertTrue(x["url"].startswith("https://") and x["brings"])
            self.assertIn(x["belonging"], ("officielle", "officielle relayée", "probable", "incertaine"))
        r = self.call("PUT", f"/api/brands/{bid}/research", {"research": got["proposed"][:2]})
        self.assertEqual((r["research"], r["proposed"]), (got["proposed"][:2], []))
        self.call("PUT", f"/api/brands/{bid}/research", {"research": [{"url": "", "brings": "x", "belonging": "probable"}]}, code=400)
        self.call("PUT", f"/api/brands/{bid}/research", {"research": got["proposed"] * 3}, code=400)
        self.call("PUT", f"/api/brands/{bid}/research", {"research": "a"}, code=400)
        self.assertEqual(self.call("PUT", f"/api/brands/{bid}/research", {"research": []})["research"], [])
        self.call("GET", "/api/brands/nope/research", code=404)

    # texts
    def test_the_texts_of_a_project_are_proposed_then_corrected_and_only_the_kept_ones_stay(self):
        bid = self.ready_brand(name="Pour les textes")
        pid = self.call("POST", f"/api/brands/{bid}/projects", {"name": "Textes"})["id"]
        empty = self.call("GET", f"/api/projects/{pid}/texts")
        self.assertEqual((empty["texts"], empty["proposed"], empty["can_propose"], empty["job"]), ([], [], False, None))
        self.call("POST", f"/api/projects/{pid}/texts/propose", code=409)  # the brief is not confirmed: nothing to work from
        self.call("PUT", f"/api/projects/{pid}/texts", {"texts": ["Écrit à la main."]})  # but the person may write them
        self.call("PUT", f"/api/projects/{pid}/brief", {"fields": {"objective": "o", "audience": "a", "message": "m"}})
        job = self.call("POST", f"/api/projects/{pid}/texts/propose")
        self.assertEqual(job["kind"], "texts")
        self.call("POST", f"/api/projects/{pid}/texts/propose", code=409)  # it runs
        self.wait(job)
        got = self.call("GET", f"/api/projects/{pid}/texts")
        self.assertEqual(got["texts"], ["Écrit à la main."])  # a proposal never becomes the project's by itself
        self.assertTrue(got["can_propose"] and 1 <= len(got["proposed"]) <= 6)
        kept = [got["proposed"][0] + " Corrigé.", "", got["texts"][0]]  # one kept and corrected, the others dropped, the hand-written one kept
        r = self.call("PUT", f"/api/projects/{pid}/texts", {"texts": kept})
        self.assertEqual((r["texts"], r["proposed"]), ([kept[0], kept[2]], []))
        self.assertEqual(self.call("GET", f"/api/projects/{pid}/texts")["texts"], r["texts"])
        self.call("PUT", f"/api/projects/{pid}/texts", {"texts": ["a"] * 7}, code=400)
        self.call("PUT", f"/api/projects/{pid}/texts", {"texts": "a"}, code=400)
        self.call("GET", "/api/projects/nope/texts", code=404)

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



class StepOneRule(unittest.TestCase):
    """Step 1 is done when the brand is ready, or once the project's brief is validated: an advanced project does not go
    back to step 1 because its brand changed afterwards."""

    def view(self, **kw):
        import workflow
        s = {"id": "p", "name": "p", "brand": "b", "since": {}, "running": [], "brief_confirmed": False, "mandates_confirmed": False,
             "pieces": [], "variants": [], "brand_ready": False}
        s.update(kw)
        return {x["key"]: x["status"] for x in workflow.project_view(s, 0)["steps"]}

    def test_brand_not_ready_blocks_a_new_project(self):
        st = self.view()
        self.assertNotEqual(st["brand"], "done")
        self.assertEqual(st["brief"], "todo")

    def test_a_validated_brief_keeps_step_one_done(self):
        st = self.view(brief_confirmed=True)
        self.assertEqual(st["brand"], "done")
        self.assertNotEqual(st["brief"], "todo")

class Machine(unittest.TestCase):
    """What the machine lacks, said by the simulated studio on request (STUDIO_STUB_MISSING): the line of the studio's column."""

    def serve(self, missing):
        httpd = server.serve("127.0.0.1", 0, StubBackend(speed=0.01, missing=missing))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(self, base, path):
        with urllib.request.urlopen(base + path) as r:
            return json.loads(r.read())

    def test_nothing_is_missing_unless_it_is_simulated(self):
        self.assertEqual(self.get(self.serve([]), "/api/machine"), {"ok": True, "missing": []})
        got = self.get(self.serve(["image", "chrome"]), "/api/machine")
        self.assertEqual((got["ok"], [m["key"] for m in got["missing"]]), (False, ["chrome", "image"]))  # in the order they are told
        self.assertEqual(sorted(got["missing"][0]), ["key", "label", "say"])
        self.assertIn("Google Chrome", got["missing"][0]["say"])
        self.assertIn("Codex", got["missing"][1]["say"])
        self.assertEqual(self.get(self.serve(["claude"]), "/api/machine")["missing"][0]["label"], "Claude Code")


class FilmBusy(unittest.TestCase):
    """While the film of a project is being made, its storyboard is not touched: the simulated studio, at full speed so that the job is still running."""

    def test_the_storyboard_is_not_proposed_nor_saved_while_the_film_is_rendered(self):
        from backend_stub import STORYBOARD
        httpd = server.serve("127.0.0.1", 0, StubBackend(speed=1.0))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (httpd.shutdown(), httpd.server_close()))
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def call(method, path, body=None, code=200):
            req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req) as r:
                    got, data = r.status, json.loads(r.read())
            except urllib.error.HTTPError as err:
                got, data = err.code, json.loads(err.read())
                err.close()
            self.assertEqual(got, code, data)
            return data

        pid = next(x["id"] for x in call("GET", "/api/projects") if x["name"] == "Campagne de rentrée")
        call("PUT", f"/api/projects/{pid}/storyboard", STORYBOARD)
        call("POST", f"/api/projects/{pid}/storyboard/render")
        for method, path, body in (("PUT", "storyboard", STORYBOARD), ("POST", "storyboard/propose", None)):
            err = call(method, f"/api/projects/{pid}/{path}", body, code=409)
            self.assertIn("rendu", err["error"])


if __name__ == "__main__":
    unittest.main()
