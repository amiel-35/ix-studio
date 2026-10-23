"""brandkit: build, review and read a brand dossier.

    python3 scripts/brandkit <command> <brand dir> ...

Sources in, decisions in, one dossier out. Run `python3 scripts/brandkit help` for the list.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402
import exports  # noqa: E402
import infer  # noqa: E402
import interview  # noqa: E402
import media  # noqa: E402
import review as rv  # noqa: E402
import visual  # noqa: E402
from fuse import Fusion, iter_values  # noqa: E402
from model import DEFAULT_LOOK, LISTS, OWNERSHIP, SCALARS, fingerprint, get_path, today  # noqa: E402
from store import BrandError, Dossier, read_json, write_json  # noqa: E402


def _strip(doc):
    d = json.loads(json.dumps(doc))
    for k in ("generated_at", "version", "validated_at", "draft", "sources"):
        d.get("meta", {}).pop(k, None)
    return d


def merge(dz: Dossier, quiet=False):
    st = dz.state()
    doc, evidence, review = Fusion(dz.sources(), dz.decisions(), st).run()
    last = st.get("last_validated")
    if last:
        prev = read_json(dz.history / f"v{last['version']}" / "brand.json", {})
        doc["meta"]["version"] = last["version"]
        doc["meta"]["validated_at"] = last["at"]
        doc["meta"]["draft"] = _strip(prev) != _strip(doc)
    write_json(dz.brand, doc)
    write_json(dz.evidence, evidence)
    _reviews(dz, doc, evidence, review, st)
    if not quiet:
        counts = {}
        for _, v in iter_values(doc):
            counts[v.get("status")] = counts.get(v.get("status"), 0) + 1
        print(f"merged {len(dz.sources())} sources → {dz.brand}")
        print("  " + " · ".join(f"{k} {n}" for k, n in sorted(counts.items(), key=lambda x: str(x[0]))))
        print(f"  conflicts {len(review['conflicts'])} · review: {dz.review} and {dz.root / 'review.html'}")
    return doc, evidence, review


def _reviews(dz, doc, evidence, review, st):
    lang = st.get("ui_language", "en")
    dz.review.write_text(rv.render(doc, evidence, review, lang), encoding="utf-8")
    out = dz.root / "review.html"
    out.write_text(visual.render_html(doc, evidence, review, dz.root, out, lang), encoding="utf-8")


def cmd_init(a):
    dz = Dossier(a.dir)
    if dz.exists():
        raise BrandError(f"{a.dir} already holds a dossier")
    for sub in ("sources", "history", "collect"):
        (dz.root / sub).mkdir(parents=True, exist_ok=True)
    dz.save_state({"created_at": today(), "ui_language": a.lang, "skills": {}})
    dz.add_source({"adapter": "typed", "origin": "launch (name given by the user)", "label": "launch",
                   "values": [{"path": "identity.name", "value": a.name}]})
    merge(dz)


def cmd_add(a):
    dz = Dossier(a.dir).require()
    raw = json.loads(Path(a.file).read_text(encoding="utf-8"))
    path = dz.add_source(raw)
    print(f"added {path.name}")
    if not a.no_merge:
        merge(dz)


def _current(dz):
    return read_json(dz.brand) or merge(dz, quiet=True)[0]


def cmd_answer(a):
    dz = Dossier(a.dir).require()
    value = json.loads(a.value) if a.json else a.value
    v = {"path": a.path}
    if a.path in LISTS:
        v["item"] = value
        if a.look:
            v["look"] = a.look
    else:
        v["value"] = value
    dz.add_source({"adapter": "typed", "origin": a.origin or "review answer (typed by the user)", "label": "answer", "values": [v]})
    merge(dz)


def cmd_confirm(a):
    dz = Dossier(a.dir).require()
    doc = _current(dz)
    if a.path in LISTS:
        look = a.look or (None if a.path in ("looks", "references", "bans") else DEFAULT_LOOK)
        items = [it for it in doc[a.path]["items"] if (look is None or it.get("look", DEFAULT_LOOK) == look)
                 and (not a.key or str(it.get("id") or (it.get(LISTS[a.path]["key"]) or {}).get("value")).lower() == a.key.lower())]
        if not items:
            raise BrandError(f"nothing to confirm in {a.path} (look {look}, key {a.key})")
        dz.add_decision({"action": "confirm", "path": a.path, "look": look or DEFAULT_LOOK, "fps": [it["fp"] for it in items if it.get("fp")]})
    else:
        v = doc["meta"]["language"] if a.path == "meta.language" else get_path(doc, a.path)
        if not v or v.get("value") is None:
            raise BrandError(f"{a.path} has no value to confirm (status {v and v.get('status')}): answer it instead")
        dz.add_decision({"action": "confirm", "path": a.path, "fp": fingerprint(v["value"])})
    merge(dz)


def cmd_reject(a):
    dz = Dossier(a.dir).require()
    doc = _current(dz)
    d = {"action": "reject", "path": a.path, "reason": a.reason}
    if a.path in LISTS:
        if not a.key:
            raise BrandError("rejecting a list item needs --key (its role, variant, url or id)")
        d.update({"look": a.look or DEFAULT_LOOK, "key": a.key})
    else:
        v = doc["meta"]["language"] if a.path == "meta.language" else get_path(doc, a.path)
        if not v or v.get("value") is None:
            raise BrandError(f"{a.path} has no value to reject")
        d["fp"] = fingerprint(v["value"])
    dz.add_decision(d)
    merge(dz)


def cmd_master(a):
    dz = Dossier(a.dir).require()
    doc = _current(dz)
    ids = [it["id"] for it in doc["looks"]["items"]]
    if a.look not in ids:
        raise BrandError(f"unknown look {a.look!r}; looks: {', '.join(ids)}")
    dz.add_decision({"action": "master", "look": a.look})
    merge(dz)


def cmd_ownership(a):
    dz = Dossier(a.dir).require()
    ev = {e["id"] for e in read_json(dz.evidence, [])}
    if a.evidence not in ev:
        raise BrandError(f"unknown evidence {a.evidence}")
    dz.add_decision({"action": "ownership", "evidence": a.evidence, "ownership": a.ownership, "reason": a.reason})
    merge(dz)


def cmd_to_create(a):
    dz = Dossier(a.dir).require()
    dz.add_decision({"action": "to_create", "path": a.path})
    merge(dz)


def cmd_skill_check(a):
    dz = Dossier(a.dir).require()
    st = dz.state()
    st.setdefault("skills", {})[a.skill] = {"unavailable": True, "checked_at": today()} if a.unavailable else {"version": a.version, "checked_at": today()}
    dz.save_state(st)
    merge(dz)


def cmd_merge(a):
    merge(Dossier(a.dir).require())


def cmd_check(a):
    dz = Dossier(a.dir).require()
    doc, evidence, _ = merge(dz, quiet=True)
    errs = checks.check(doc, evidence)
    for e in errs:
        print(e)
    print("check: ok" if not errs else f"check: {len(errs)} problem(s)")
    sys.exit(1 if errs else 0)


def cmd_validate(a):
    dz = Dossier(a.dir).require()
    doc, evidence, review = merge(dz, quiet=True)
    errs = checks.check(doc, evidence)
    if errs:
        for e in errs:
            print(e)
        raise BrandError("not validated: fix the problems above first")
    st = dz.state()
    last = st.get("last_validated")
    if last and not doc["meta"]["draft"]:
        print(f"nothing changed since version {last['version']}")
        return
    n = (last or {}).get("version", 0) + 1
    doc["meta"].update({"version": n, "validated_at": today(), "draft": False, "validated_by": a.by})
    write_json(dz.brand, doc)
    hist = dz.history / f"v{n}"
    hist.mkdir(parents=True, exist_ok=True)
    write_json(hist / "brand.json", doc)
    write_json(hist / "evidence.json", evidence)
    st["last_validated"] = {"version": n, "at": today(), "by": a.by}
    dz.save_state(st)
    _reviews(dz, doc, evidence, review, st)
    _export(dz, doc)
    left = sum(1 for _, v in iter_values(doc) if v.get("status") in ("ask", "to_create"))
    print(f"validated version {n} ({left} value(s) still ASK or to create, visible as missing downstream)")


def _export(dz, doc):
    (dz.root / "brand.md").write_text(exports.brand_md(doc), encoding="utf-8")
    (dz.root / "MOTION.md").write_text(exports.motion_md(doc), encoding="utf-8")
    print(f"exported {dz.root / 'brand.md'} and {dz.root / 'MOTION.md'}")


def cmd_export(a):
    dz = Dossier(a.dir).require()
    doc = merge(dz, quiet=True)[0]
    if not a.draft and doc["meta"]["version"] == 0:
        raise BrandError("no validated version yet: validate first, or export --draft to preview")
    if not a.draft and doc["meta"]["draft"]:
        doc = read_json(dz.history / f"v{doc['meta']['version']}" / "brand.json")
    _export(dz, doc)


def cmd_get(a):
    dz = Dossier(a.dir).require()
    doc = read_json(dz.brand)
    if a.version:
        doc = read_json(dz.history / f"v{a.version}" / "brand.json")
    r = checks.read(doc, a.path, a.look)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    sys.exit(3 if r.get("missing") else 0)


def cmd_missing(a):
    dz = Dossier(a.dir).require()
    doc = merge(dz, quiet=True)[0]
    qs = interview.missing_questions(doc, a.lang or dz.state().get("ui_language", "en"))
    if a.json:
        print(json.dumps(qs, indent=2, ensure_ascii=False))
        return
    for b in (1, 2, 3):
        batch = [q for q in qs if q["batch"] == b]
        if batch:
            print(f"Batch {b}")
            for q in batch:
                print(f"  - {q['question']}   [{', '.join(q['fields'])}]")
    if not qs:
        print("nothing to ask: every field has a value or waits for confirmation in the review")


def cmd_infer_site(a):
    dz = Dossier(a.dir).require()
    facts = read_json(Path(a.collect) / "facts.json")
    if not facts:
        raise BrandError(f"no facts.json in {a.collect} (run scripts/collect/collect.mjs first)")
    src = infer.from_site(facts, a.collect, a.dir, look=a.look, look_name=a.look_name, look_kind=a.look_kind,
                          ownership=a.ownership, given_by_user=not a.not_given_by_user)
    path = dz.add_source(src)
    print(f"added {path.name} ({len(src['values'])} values)")
    merge(dz)


def cmd_frames(a):
    print(json.dumps(media.frames(a.video, a.out, a.scene, a.max), indent=2))


def cmd_sample(a):
    print(json.dumps(media.sample(a.image, a.k), indent=2))


def cmd_review_html(a):
    dz = Dossier(a.dir).require()
    doc, evidence, review = merge(dz, quiet=True)
    out = Path(a.out) if a.out else dz.root / ("review-standalone.html" if a.embed else "review.html")
    out.write_text(visual.render_html(doc, evidence, review, dz.root, out, a.lang or dz.state().get("ui_language", "en"), embed=a.embed), encoding="utf-8")
    print(f"{out} ({round(out.stat().st_size / 1e6, 2)} MB{', images embedded' if a.embed else ''})")


def cmd_status(a):
    dz = Dossier(a.dir).require()
    doc = read_json(dz.brand)
    rows = {}
    for path, v in iter_values(doc):
        rows.setdefault(v.get("status"), []).append(path)
    m = doc["meta"]
    print(f"{get_path(doc, 'identity.name')['value']} · version {m['version']}{' (draft changes)' if m.get('draft') else ''}")
    for k in ("confirmed", "to_confirm", "ask", "to_create", "reserved"):
        print(f"  {k:<11} {len(rows.get(k, []))}")


def build_parser():
    p = argparse.ArgumentParser(prog="brandkit", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help, *args):
        s = sub.add_parser(name, help=help)
        s.set_defaults(fn=fn)
        if "dir" in args:
            s.add_argument("dir", help="the brand dossier folder (usually <project>/brand)")
        return s

    s = add("init", cmd_init, "start a dossier from the brand's name", "dir")
    s.add_argument("--name", required=True)
    s.add_argument("--lang", default="en", choices=("en", "fr"), help="language of the review")
    s = add("add", cmd_add, "add a source file written by an adapter", "dir")
    s.add_argument("file")
    s.add_argument("--no-merge", action="store_true")
    add("merge", cmd_merge, "rebuild brand.json, evidence.json and review.md", "dir")
    s = add("answer", cmd_answer, "record a typed answer from the review or the interview", "dir")
    s.add_argument("path")
    s.add_argument("value")
    s.add_argument("--json", action="store_true", help="the value is JSON (a list, or an item object for a list rubric)")
    s.add_argument("--look")
    s.add_argument("--origin")
    s = add("confirm", cmd_confirm, "confirm an inferred value (or a list rubric's items for one look)", "dir")
    s.add_argument("path")
    s.add_argument("--look")
    s.add_argument("--key")
    s = add("reject", cmd_reject, "reject a value; the next source surfaces, or the field becomes ASK", "dir")
    s.add_argument("path")
    s.add_argument("--look")
    s.add_argument("--key")
    s.add_argument("--reason", required=True, help="the user's words, verbatim")
    s = add("master", cmd_master, "choose the master look (R10)", "dir")
    s.add_argument("look")
    s = add("ownership", cmd_ownership, "confirm or correct whether a visual or page is the brand's (R8)", "dir")
    s.add_argument("evidence")
    s.add_argument("ownership", choices=OWNERSHIP)
    s.add_argument("--reason")
    s = add("to-create", cmd_to_create, "mark an empty field as to be created by the identity family", "dir")
    s.add_argument("path")
    s = add("skill-check", cmd_skill_check, "record the version of a skill that speaks for the brand (R12)", "dir")
    s.add_argument("skill")
    s.add_argument("version", nargs="?")
    s.add_argument("--unavailable", action="store_true")
    add("check", cmd_check, "check the invariants (C1, C2, C4, C5, C8)", "dir")
    s = add("validate", cmd_validate, "validate: new version, history, exports", "dir")
    s.add_argument("--by", default="user")
    s = add("export", cmd_export, "regenerate brand.md and MOTION.md", "dir")
    s.add_argument("--draft", action="store_true")
    s = add("get", cmd_get, "read a field as a downstream module does (C11)", "dir")
    s.add_argument("path")
    s.add_argument("--look")
    s.add_argument("--version", type=int)
    s = add("missing", cmd_missing, "the interview questions still worth asking", "dir")
    s.add_argument("--lang", choices=("en", "fr"))
    s.add_argument("--json", action="store_true")
    s = add("infer-site", cmd_infer_site, "turn a collect folder into an inferred source", "dir")
    s.add_argument("collect")
    s.add_argument("--look")
    s.add_argument("--look-name")
    s.add_argument("--look-kind", choices=("brand", "old_identity", "campaign", "sub_brand", "unknown"))
    s.add_argument("--ownership", default="official", choices=OWNERSHIP)
    s.add_argument("--not-given-by-user", action="store_true", help="the site was found, not given: its ownership goes to the review")
    s = add("frames", cmd_frames, "extract frames at each cut of a video, with the cut times")
    s.add_argument("video")
    s.add_argument("out")
    s.add_argument("--scene", type=float, default=0.3)
    s.add_argument("--max", type=int, default=24)
    s = add("sample", cmd_sample, "dominant colours of an image (a web image is deleted after reading)")
    s.add_argument("image")
    s.add_argument("--k", type=int, default=6)
    s = add("review-html", cmd_review_html, "the visual review; --embed for one standalone file to send", "dir")
    s.add_argument("--embed", action="store_true", help="embed the brand's own images (web images are never embedded)")
    s.add_argument("--out")
    s.add_argument("--lang", choices=("en", "fr"))
    add("status", cmd_status, "counts by status", "dir")
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except BrandError as e:
        print(f"brandkit: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
