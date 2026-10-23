"""Fusion: every source file plus the user's decisions become one dossier (brand.json) and one evidence list.

Rules applied here (spec section 5):
  R1 provenance on every value · R3 priority skill > typed > inferred, and inside inferred
  declared-and-used > rendered > image sample > web image · R4 conflicts kept in `discarded` · R5 nothing guessed ·
  R6 inferred stays "to_confirm" until the user confirms · R8 only official / relayed / probable visuals feed ·
  R9 the logo is a file, a missing vector is asked · R10 several looks are named, never averaged · R12 a skill whose
  version changed gives back "to_confirm" values.
"""

from model import (CONF_RANK, DEFAULT_LOOK, FEEDING, INFER_RANK, LISTS, RESERVED, SCALARS, SCHEMA, TYPE_RANK,
                   VECTOR_FORMATS, fingerprint, hex_distance, missing, norm, set_path, today)


def _key(c):
    return (TYPE_RANK[c["type"]], INFER_RANK.get(c.get("rank"), 1) if c["type"] == "inferred" else 0,
            CONF_RANK.get(c.get("confidence")), -c["order"])


def item_fp(item):
    return fingerprint({k: v for k, v in item.items() if v not in (None, "", [])})


def _source(c):
    return {"type": c["type"], "origin": c["origin"], "at": c["at"]}


class Fusion:
    def __init__(self, sources, decisions, state):
        self.sources = sources
        self.decisions = decisions
        self.state = state or {}
        self.review = {"conflicts": [], "dropped": [], "stale": [], "notes": [], "ignored": [], "looks": None}
        self.evidence = {}
        self.cands = []

    # ---------- evidence and candidates ----------
    def _collect(self):
        own = {d["evidence"]: d["ownership"] for d in self.decisions if d.get("action") == "ownership"}
        for s in self.sources:
            for e in s.get("evidence", []):
                prev = self.evidence.get(e["id"], {})
                ev = {**prev, **e}
                if "ownership" in e:
                    ev["ownership_proposed"] = prev.get("ownership_proposed", e["ownership"])
                    if e["id"] in own:
                        ev["ownership"] = own[e["id"]]
                        ev["ownership_status"] = "confirmed" if own[e["id"]] == ev["ownership_proposed"] else "corrected"
                    elif e.get("ownership_given_by_user"):
                        ev["ownership_status"] = "confirmed"
                    else:
                        ev["ownership_status"] = "to_confirm"
                ev.pop("ownership_given_by_user", None)
                self.evidence[e["id"]] = ev
            for n in s.get("not_found", []) or []:
                self.review["notes"].append({"origin": s["origin"], "text": n})
            for n in s.get("notes", []) or []:
                self.review["notes"].append({"origin": s["origin"], "text": n})
            for n in s.get("ignored", []) or []:
                self.review["ignored"].append({"origin": s["origin"], **n})

        skills_now = self.state.get("skills", {})
        stale_seen = set()
        for s in self.sources:
            stale = None
            if s["adapter"] == "skill":
                sk = s["skill"]
                now = skills_now.get(sk["name"])
                if now and (now.get("unavailable") or str(now.get("version")) != sk["version"]):
                    stale = now
                    if sk["name"] not in stale_seen:
                        stale_seen.add(sk["name"])
                        self.review["stale"].append({"skill": sk["name"], "read": sk["version"],
                                                     "now": "unavailable" if now.get("unavailable") else now.get("version")})
            for v in s["values"]:
                c = {**v, "type": s["adapter"], "origin": v.get("origin") or s["origin"], "at": s["at"],
                     "order": s["_order"], "stale": stale, "validated": s.get("validated")}
                if c["type"] == "inferred" and c.get("evidence"):
                    if not any(self._feeds(e) for e in c["evidence"]):
                        self.review["dropped"].append({"path": c["path"], "value": c.get("value", c.get("item")),
                                                       "origin": c["origin"], "evidence": c["evidence"]})
                        continue
                self.cands.append(c)

    def _feeds(self, eid):
        ev = self.evidence.get(eid)
        if not ev:
            return False
        return "ownership" not in ev or ev["ownership"] in FEEDING

    def _decided(self, action, path, look=None):
        return [d for d in self.decisions if d.get("action") == action and d.get("path") == path
                and (look is None or d.get("look", DEFAULT_LOOK) == look)]

    def _value(self, c, value, confirmed_at=None):
        v = {"value": value, "status": "to_confirm", "source": _source(c)}
        if c["type"] in ("skill", "typed"):
            v["status"] = "confirmed"
        elif c["type"] == "created" and c.get("validated"):
            v["status"] = "confirmed"
        if c["type"] == "inferred":
            v["confidence"] = c.get("confidence")
            v["evidence"] = list(c.get("evidence", []))
            if c.get("rank"):
                v["rank"] = c["rank"]
        if c.get("stale"):
            v["status"] = "to_confirm"
            now = c["stale"]
            v["note"] = "skill unavailable at last check" if now.get("unavailable") else f"skill changed since it was read (now {now.get('version')})"
        if v["status"] == "to_confirm" and not c.get("stale") and confirmed_at:
            v["status"] = "confirmed"
            v["confirmed"] = {"by": "user", "at": confirmed_at}
        if c.get("note"):
            v.setdefault("note", c["note"])
        return v

    @staticmethod
    def _discard(c, value, status, conflict=False, reason=None):
        d = {"value": value, "source": _source(c), "status": status}
        if c["type"] == "inferred":
            d["confidence"] = c.get("confidence")
            d["evidence"] = c.get("evidence", [])
        if conflict:
            d["conflict"] = True
        if reason:
            d["reason"] = reason
        return d

    # ---------- scalars ----------
    def _scalar(self, path, spec):
        cs = [c for c in self.cands if c["path"] == path and not c.get("hint")]
        hints = [c for c in self.cands if c["path"] == path and c.get("hint")]
        rejected = {d["fp"]: d for d in self._decided("reject", path)}
        confirmed = {d["fp"]: d["at"] for d in self._decided("confirm", path)}
        live = [c for c in cs if fingerprint(c["value"]) not in rejected]
        rej = [c for c in cs if fingerprint(c["value"]) in rejected]
        if live:
            win = min(live, key=_key)
            wfp = fingerprint(win["value"])
            v = self._value(win, win["value"], confirmed.get(wfp))
            if win["type"] == "inferred":  # the same value seen by several inferred sources: one value, all the proof
                for c in live:
                    if c is not win and c["type"] == "inferred" and fingerprint(c["value"]) == wfp:
                        v["evidence"] += [e for e in c.get("evidence", []) if e not in v["evidence"]]
            disc = []
            for c in live:
                if c is win or (c["type"] == win["type"] == "inferred" and fingerprint(c["value"]) == wfp):
                    continue
                disc.append(self._discard(c, c["value"], "overridden", conflict=fingerprint(c["value"]) != wfp))
            disc += [self._discard(c, c["value"], "rejected", reason=rejected[fingerprint(c["value"])].get("reason")) for c in rej]
            if disc:
                v["discarded"] = disc
            for d in disc:
                if d.get("conflict"):
                    self.review["conflicts"].append({"path": path, "kept": v["value"], "kept_source": v["source"], "other": d})
        else:
            status = "to_create" if (spec.get("create") or self._decided("to_create", path)) else "ask"
            v = missing(status, self._nobody(path))
            if rej:
                v["discarded"] = [self._discard(c, c["value"], "rejected", reason=rejected[fingerprint(c["value"])].get("reason")) for c in rej]
        if hints:
            v["closest"] = [{"value": c["value"], "source": _source(c), "note": "closest thing found, not filled in"} for c in hints]
        return v

    def _nobody(self, path):
        n = len(self.sources)
        return f"no source gave {path} ({n} source{'s' if n != 1 else ''} consulted)"

    # ---------- list rubrics ----------
    def _item_key(self, rubric, item):
        k = LISTS[rubric]["key"]
        return norm(item.get(k) if k != "variant" else item.get("variant") or item.get("file"))

    def _tier_rubric(self, rubric, spec):
        cs = [c for c in self.cands if c["path"] == rubric and not c.get("hint")]
        looks = sorted({c.get("look") or DEFAULT_LOOK for c in cs})
        items, discarded, gaps = [], [], []
        visual_sources = any(e["kind"] in ("page", "file", "web_image", "video") for e in self.evidence.values())
        for look in looks:
            lc = [c for c in cs if (c.get("look") or DEFAULT_LOOK) == look]
            rejected = {(d.get("key") and norm(d["key"])) or d.get("fp"): d for d in self._decided("reject", rubric, look)}
            confirmed = {}
            for d in self._decided("confirm", rubric, look):
                for fp in d.get("fps", []):
                    confirmed[fp] = d["at"]
            live, rej = [], []
            for c in lc:
                (rej if (self._item_key(rubric, c["item"]) in rejected or item_fp(c["item"]) in rejected) else live).append(c)
            if live:
                tier = min(TYPE_RANK[c["type"]] for c in live)
                best = {}
                for c in sorted(live, key=_key):
                    if TYPE_RANK[c["type"]] != tier:
                        continue
                    k = self._item_key(rubric, c["item"])
                    if k not in best:
                        best[k] = c
                winners = list(best.values())
                for c in live:
                    if c in winners:
                        continue
                    conflict = self._conflicts(rubric, c, winners)
                    d = self._discard(c, c["item"], "overridden", conflict=conflict)
                    d["look"] = look
                    discarded.append(d)
                    if conflict:
                        k = self._item_key(rubric, c["item"])
                        same = [w for w in winners if self._item_key(rubric, w["item"]) == k]
                        kept = same[0]["item"] if same else [w["item"].get("hex") or w["item"].get("family") or w["item"].get("file") for w in winners]
                        self.review["conflicts"].append({"path": rubric, "look": look, "kept": kept,
                                                         "kept_source": _source(winners[0]), "other": d})
                for c in winners:
                    it = {"look": look, "fp": item_fp(c["item"])}
                    at = confirmed.get(it["fp"])
                    for f in spec["required"] + spec["optional"]:
                        if f in c["item"] and c["item"][f] not in (None, ""):
                            it[f] = self._value(c, c["item"][f], at)
                        elif f in spec["required"]:
                            it[f] = missing("ask", f"{rubric}.{f} not given by {c['origin']}")
                    items.append(it)
                if rubric == "logo" and not any(str(norm(c["item"].get("format", ""))) in VECTOR_FORMATS for c in winners):
                    g = missing("ask", f"only a raster or icon logo found for look {look!r} (R9: the logo is never redrawn)")
                    g["what"] = "vector logo"
                    g["look"] = look
                    hints = [c for c in self.cands if c["path"] == rubric and c.get("hint") and (c.get("look") or DEFAULT_LOOK) == look]
                    if hints:
                        g["closest"] = [{"value": c["item"], "source": _source(c), "note": c.get("note") or "closest thing found, not filled in"} for c in hints]
                    gaps.append(g)
            for c in rej:
                d = self._discard(c, c["item"], "rejected", reason=(rejected.get(self._item_key(rubric, c["item"])) or {}).get("reason"))
                d["look"] = look
                discarded.append(d)
        out = {"items": items}
        if discarded:
            out["discarded"] = discarded
        if gaps:
            out["gaps"] = gaps
        if not items:
            make = (spec.get("create") and not visual_sources) or self._decided("to_create", rubric)
            out.update(missing("to_create" if make else "ask", self._nobody(rubric)))
            out.pop("value")
            hints = [c for c in self.cands if c["path"] == rubric and c.get("hint")]
            if hints:
                out["closest"] = [{"value": c["item"], "source": _source(c), "note": c.get("note") or "closest thing found, not filled in"} for c in hints]
        else:
            out["status"] = self._aggregate(items, gaps)
        return out

    def _conflicts(self, rubric, c, winners):
        if rubric == "colours":
            h = c["item"].get("hex", "")
            return not any(hex_distance(h, w["item"].get("hex", "")) < 8 for w in winners)
        if rubric == "typography":
            fam = norm(c["item"].get("family", "")).lower()
            return not any(norm(w["item"].get("family", "")).lower() == fam for w in winners)
        return False

    @staticmethod
    def _aggregate(items, gaps=()):
        sts = [v["status"] for it in items for k, v in it.items() if isinstance(v, dict) and "status" in v]
        sts += [g["status"] for g in gaps]
        if "to_confirm" in sts:
            return "to_confirm"
        if "ask" in sts:
            return "confirmed_with_gaps" if "confirmed" in sts else "ask"
        return "confirmed"

    def _union_rubric(self, rubric, spec):
        cs = [c for c in self.cands if c["path"] == rubric and not c.get("hint")]
        if rubric == "looks":
            return self._looks(cs, spec)
        best = {}
        for c in sorted(cs, key=_key):
            best.setdefault(self._item_key(rubric, c["item"]), c)
        confirmed = {fp: d["at"] for d in self._decided("confirm", rubric) for fp in d.get("fps", [])}
        items = []
        for c in best.values():
            it = {"fp": item_fp(c["item"])}
            for f in spec["required"] + spec["optional"]:
                if f in c["item"]:
                    it[f] = self._value(c, c["item"][f], confirmed.get(it["fp"]))
                elif f in spec["required"]:
                    it[f] = missing("ask", f"{rubric}.{f} not given by {c['origin']}")
            items.append(it)
        out = {"items": items}
        if items:
            out["status"] = self._aggregate(items)
        elif spec.get("reserved"):
            out.update({"status": "reserved", "source": {"type": "none", "origin": "reserved: filled from the user's refusals (part 5, memory)", "at": today()}})
        else:
            out.update(missing("ask", self._nobody(rubric)))
            out.pop("value")
        return out

    def _looks(self, cs, spec):
        used = {c.get("look") or DEFAULT_LOOK for c in self.cands if c["path"] in ("colours", "typography", "logo") or c.get("look")}
        best = {}
        for c in sorted(cs, key=_key):
            best.setdefault(c["item"]["id"], c)
        master_d = [d for d in self.decisions if d.get("action") == "master"]
        master = master_d[-1]["look"] if master_d else None
        typed_master = [c for c in best.values() if c["type"] in ("skill", "typed") and c["item"].get("master")]
        if not master and typed_master:
            master = typed_master[0]["item"]["id"]
        confirmed = {fp: d["at"] for d in self._decided("confirm", "looks") for fp in d.get("fps", [])}
        items = []
        ids = list(best) + sorted(i for i in used if i not in best)
        for lid in ids:
            c = best.get(lid)
            it = {"id": lid}
            if c:
                it["fp"] = item_fp(c["item"])
                for f in spec["required"] + spec["optional"]:
                    if f in c["item"]:
                        it[f] = self._value(c, c["item"][f], confirmed.get(it["fp"]))
                    elif f in spec["required"]:
                        it[f] = missing("ask", f"looks.{f} not given by {c['origin']}")
                evs = set(c.get("evidence", []))
                for o in cs:
                    if o["item"]["id"] == lid:
                        evs.update(o.get("evidence", []))
                if evs:
                    it["evidence"] = sorted(evs)
            else:
                first = next(x for x in self.cands if (x.get("look") or DEFAULT_LOOK) == lid)
                src = _source(first)
                st = "confirmed" if first["type"] in ("skill", "typed") else "to_confirm"
                it["name"] = {"value": "Brand identity" if lid == DEFAULT_LOOK else lid, "status": st, "source": {**src, "origin": f"implied by values without a look, from {src['origin']}"}}
                it["kind"] = {"value": "brand" if lid == DEFAULT_LOOK else "unknown", "status": st, "source": it["name"]["source"]}
                if first["type"] == "inferred":
                    for k in ("name", "kind"):
                        it[k]["confidence"] = "medium"
                        it[k]["evidence"] = first.get("evidence", [])
            items.append(it)
        for it in items:
            if master:
                src = {"type": "typed", "origin": "review: master look chosen by the user" if master_d else f"declared by {typed_master[0]['origin']}", "at": master_d[-1]["at"] if master_d else today()}
                it["master"] = {"value": it["id"] == master, "status": "confirmed", "source": src}
            elif len(items) == 1:
                kind_src = it["name"]["source"]
                it["master"] = {"value": True, "status": "confirmed" if kind_src["type"] in ("skill", "typed") else "to_confirm",
                                "source": {**kind_src, "origin": "the only look found"}}
                if kind_src["type"] == "inferred":
                    it["master"]["confidence"] = "medium"
                    it["master"]["evidence"] = it.get("evidence") or it["name"].get("evidence", [])
            else:
                it["master"] = missing("ask", "several looks found: which one is the master look? (R10, never averaged)")
        if len(items) > 1 and not master:
            self.review["looks"] = [it["id"] for it in items]
        out = {"items": items}
        out["status"] = self._aggregate(items) if items else "ask"
        if not items:
            out["source"] = {"type": "none", "origin": "no look described yet", "at": today()}
        return out

    # ---------- whole dossier ----------
    def run(self):
        self._collect()
        doc = {"schema": SCHEMA}
        for path, spec in SCALARS.items():
            if path.startswith("meta."):
                continue
            set_path(doc, path, self._scalar(path, spec))
        for rubric, spec in LISTS.items():
            doc[rubric] = self._tier_rubric(rubric, spec) if spec["merge"] == "tier" else self._union_rubric(rubric, spec)
        for r in RESERVED:
            doc[r] = {"value": None, "status": "reserved", "source": {"type": "none", "origin": "reserved (out of scope: made once, then entered as an asset)", "at": today()}}
        doc["meta"] = {"version": 0, "validated_at": None, "draft": True, "generated_at": today(),
                       "language": self._scalar("meta.language", SCALARS["meta.language"]),
                       "sources": [{"file": s["_file"], "type": s["adapter"], "origin": s["origin"], "at": s["at"]} for s in self.sources]}
        doc["meta"]["to_create"] = to_create(doc)
        # stable order: identity first, meta last
        order = ["schema", "identity", "audience", "promise", "voice", "colours", "typography", "logo", "imagery",
                 "motion", "bans", "references", "looks", "signature", "meta"]
        doc = {k: doc[k] for k in order if k in doc}
        evidence = sorted(self.evidence.values(), key=lambda e: e["id"])
        return doc, evidence, self.review


def to_create(doc):
    out = []
    for path, v in iter_values(doc):
        if v.get("status") == "to_create":
            out.append(path)
    return out


def iter_values(doc, prefix=""):
    """Every value in the dossier, with its path. List items are addressed as rubric[look:key].field."""
    for k, v in doc.items():
        if k in ("schema",) or (prefix == "" and k == "meta"):
            if k == "meta" and isinstance(v.get("language"), dict):
                yield "meta.language", v["language"]
            continue
        path = f"{prefix}{k}"
        if isinstance(v, dict) and "status" in v and "items" not in v and ("value" in v or v.get("status") in ("ask", "to_create", "reserved")):
            yield path, v
        elif isinstance(v, dict) and "items" in v:
            if not v["items"]:
                yield path, v
            spec = LISTS.get(k, {})
            for i, it in enumerate(v["items"]):
                key = it.get("id") or (it.get(spec.get("key", ""), {}) or {}).get("value") or i
                for f, fv in it.items():
                    if isinstance(fv, dict) and "status" in fv:
                        yield f"{path}[{it.get('look', '') + ':' if it.get('look') else ''}{key}].{f}", fv
            for g in v.get("gaps", []):
                yield f"{path}[{g.get('look')}].{g.get('what', 'gap').replace(' ', '_')}", g
        elif isinstance(v, dict):
            yield from iter_values(v, path + ".")
