"""Where a dossier lives on disk, and how a source file enters it.

<brand dir>/
  brand.json        the dossier, the only source (annex A)
  brand.md          generated for brand-intake readers, never edited
  MOTION.md         generated, never edited
  review.md         the latest review
  evidence.json     every source consulted: where, when, ownership
  history/vN/       validated versions
  sources/          one file per adapter run (what each adapter found, with its proof)
  decisions.json    what the user confirmed, rejected, chose
  state.json        settings and the last known version of each skill that speaks for the brand
  collect/          material collected from the brand's own site or files (never images found on the web)
"""

import json
import re
from pathlib import Path

from model import (EVIDENCE_KINDS, LISTS, OWNERSHIP, SCALARS, SOURCE_TYPES, CONFIDENCE, INFER_RANK,
                   evidence_id, today)


class BrandError(Exception):
    pass


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower().replace("https://", "").replace("http://", "")).strip("-")[:40] or "source"


class Dossier:
    def __init__(self, root):
        self.root = Path(root)

    # paths
    @property
    def brand(self): return self.root / "brand.json"
    @property
    def evidence(self): return self.root / "evidence.json"
    @property
    def review(self): return self.root / "review.md"
    @property
    def sources_dir(self): return self.root / "sources"
    @property
    def decisions_file(self): return self.root / "decisions.json"
    @property
    def state_file(self): return self.root / "state.json"
    @property
    def history(self): return self.root / "history"

    def exists(self) -> bool:
        return self.state_file.exists()

    def require(self):
        if not self.exists():
            raise BrandError(f"{self.root} is not a brand dossier (run: brandkit init {self.root} --name ...)")
        return self

    def state(self) -> dict:
        return read_json(self.state_file, {})

    def save_state(self, st: dict) -> None:
        write_json(self.state_file, st)

    def decisions(self) -> list:
        return read_json(self.decisions_file, [])

    def add_decision(self, d: dict) -> None:
        ds = self.decisions()
        d.setdefault("at", today())
        ds.append(d)
        write_json(self.decisions_file, ds)

    def sources(self) -> list:
        out = []
        for f in sorted(self.sources_dir.glob("*.json")):
            s = read_json(f)
            s["_file"] = f.name
            s["_order"] = len(out)
            out.append(s)
        return out

    def add_source(self, raw: dict) -> Path:
        src = normalise_source(raw)
        nums = [int(f.name[:3]) for f in self.sources_dir.glob("*.json") if f.name[:3].isdigit()]
        n = max(nums, default=0) + 1
        name = f"{n:03d}-{src['adapter']}-{slug(src.get('label') or src['origin'])}.json"
        path = self.sources_dir / name
        write_json(path, src)
        return path


def _need(cond, msg):
    if not cond:
        raise BrandError(msg)


def normalise_source(raw: dict) -> dict:
    """Check a source file written by an adapter, and give its evidence stable ids.

    The adapter refers to its proof with its own short ids; inside the dossier an evidence id is derived from
    (kind, where), so the same page found twice is one piece of evidence.
    """
    _need(isinstance(raw, dict), "a source file is a JSON object")
    adapter = raw.get("adapter")
    _need(adapter in SOURCE_TYPES, f"adapter must be one of {SOURCE_TYPES}, got {adapter!r}")
    src = {"adapter": adapter, "at": raw.get("at") or today()}
    if adapter == "skill":
        sk = raw.get("skill") or {}
        _need(sk.get("name") and sk.get("version"), "a skill source needs skill.name and skill.version (R12)")
        src["skill"] = {"name": sk["name"], "version": str(sk["version"])}
        if sk.get("read"):
            src["skill"]["read"] = sk["read"]
        src["origin"] = raw.get("origin") or f"{sk['name']}@{sk['version']}"
    else:
        _need(raw.get("origin"), "a source needs an origin (who or what said it: a page, a file, an interview)")
        src["origin"] = raw["origin"]
    for k in ("label", "not_found", "notes", "ignored", "validated"):
        if raw.get(k) is not None:
            src[k] = raw[k]

    ids = {}
    evidence = []
    for e in raw.get("evidence", []):
        _need(e.get("kind") in EVIDENCE_KINDS, f"evidence kind must be one of {EVIDENCE_KINDS}: {e}")
        _need(e.get("where"), f"evidence needs where (an address or a path): {e}")
        ev = {"id": evidence_id(e["kind"], e["where"]), "kind": e["kind"], "where": e["where"], "at": e.get("at") or src["at"]}
        if e["kind"] in ("page", "web_image", "video") or e.get("ownership"):
            _need(e.get("ownership") in OWNERSHIP, f"evidence {e['where']} needs ownership in {OWNERSHIP} (R8)")
            ev["ownership"] = e["ownership"]
            ev["ownership_given_by_user"] = bool(e.get("ownership_given_by_user"))
        if e["kind"] == "web_image":
            _need(not e.get("file"), f"an image found on the web is never kept (R8): {e['where']}")
            ev["kept"] = False
        else:
            ev["kept"] = bool(e.get("kept", e["kind"] in ("file",) or bool(e.get("file"))))
            if e.get("file"):
                ev["file"] = e["file"]
        for k in ("page", "note", "look", "title"):
            if e.get(k):
                ev[k] = e[k]
        if e.get("id"):
            ids[e["id"]] = ev["id"]
        ids[ev["id"]] = ev["id"]
        evidence.append(ev)
    src["evidence"] = evidence

    values = []
    for v in raw.get("values", []):
        path = v.get("path")
        _need(path in SCALARS or path in LISTS, f"unknown field {path!r}")
        out = {"path": path}
        if path in LISTS:
            item = v.get("item")
            _need(isinstance(item, dict), f"{path}: a list rubric takes an item object")
            spec = LISTS[path]
            if path == "looks":
                _need(item.get("id"), "a look needs an id")
            else:
                _need(item.get(spec["key"]) or spec["key"] == "variant", f"{path}: an item needs its key field {spec['key']!r}")
            out["item"] = item
            out["look"] = v.get("look")
        else:
            _need("value" in v and v["value"] not in (None, "", []), f"{path}: a value is required (leave the field out instead of sending it empty)")
            if SCALARS[path]["kind"] == "list" and isinstance(v["value"], str):
                v["value"] = [v["value"]]
            out["value"] = v["value"]
        if adapter == "inferred":
            _need(v.get("confidence") in CONFIDENCE, f"{path}: an inferred value needs a confidence in {CONFIDENCE}")
            _need(v.get("evidence"), f"{path}: an inferred value needs its evidence")
            if v.get("rank"):
                _need(v["rank"] in INFER_RANK, f"{path}: rank must be one of {tuple(INFER_RANK)}")
        if v.get("evidence"):
            refs = []
            for r in v["evidence"]:
                _need(r in ids, f"{path}: evidence {r!r} is not declared in this source")
                refs.append(ids[r])
            out["evidence"] = refs
        for k in ("confidence", "rank", "origin", "hint", "note"):
            if v.get(k) is not None:
                out[k] = v[k]
        values.append(out)
    src["values"] = values
    return src
