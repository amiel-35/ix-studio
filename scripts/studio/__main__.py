"""studio: carry one still ad (a poster or a social post) from a minimal brand to a decision.

    python3 scripts/studio <command> <piece dir> ...

brand → brief → diverge → pick → image → compose → check → decide. Each step reads and writes plain files in the
piece folder and renders one HTML page. Run `python3 scripts/studio --help` for the list.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402
import compose  # noqa: E402
import dossier  # noqa: E402
import images  # noqa: E402
import pages  # noqa: E402
from files import (GROUNDS, LAYOUTS, StudioError, image_file, load_brand, load_brief, load_pick, load_variants, palette, picked,  # noqa: E402
                   read_json, today, write_json)
from ui import PAGES, cli  # noqa: E402


def lang_of(a):
    if a.lang:
        return a.lang
    try:
        return "fr" if load_brief(a.dir)["language"].lower().startswith("fr") else "en"
    except StudioError:
        return "en"


def page(a, step):
    p = pages.RENDER[step](a.dir, lang_of(a))
    print(f"page: {p}")


def need_pick(d):
    v, headline = picked(d, load_variants(d))
    if not v:
        raise StudioError("no pick yet: " + cli(d, "pick", "<id>"))
    return v, headline


def cmd_brand(a):
    d = Path(a.dir)
    if a.from_dossier:
        target = d / "brand.md"
        if target.exists() and not a.force:
            raise StudioError(f"{target} exists: use --force to overwrite it")
        d.mkdir(parents=True, exist_ok=True)
        text, miss = dossier.brand_md(a.from_dossier, d)
        target.write_text(text, encoding="utf-8")
        print(f"brand.md written from {a.from_dossier}" + (f" (missing: {', '.join(miss)})" if miss else ""))
        try:
            load_brand(d)
        except StudioError as err:
            print(f"incomplete: {err}; fill it in, then rerun `brand`")
            return
    b = load_brand(d)
    print(f"brand ok: {b['name']} · {len(palette(b))} colours · fonts {b['hfont'] or '-'} / {b['bfont'] or '-'}")
    page(a, 1)


def cmd_brief(a):
    load_brand(a.dir)
    br = load_brief(a.dir)
    print(f"brief ok: {br['objective']} · {br['format']} {br['size'][0]}x{br['size'][1]}")
    page(a, 2)


def cmd_diverge(a):
    load_brand(a.dir), load_brief(a.dir)
    vs = load_variants(a.dir)
    print(f"{len(vs)} variants ok: {', '.join(v['id'] for v in vs)}")
    page(a, 3)


def cmd_pick(a):
    vs = load_variants(a.dir)
    if a.id not in [v["id"] for v in vs]:
        raise StudioError(f"no variant {a.id!r}: choose one of {', '.join(v['id'] for v in vs)}")
    pick = {"variant": a.id, "at": today()}
    if a.headline:
        pick["headline"] = a.headline
    write_json(Path(a.dir) / "pick.json", pick)
    print(f"picked {a.id}" + (f" with headline {a.headline!r}" if a.headline else ""))
    page(a, 3)


def cmd_image(a):
    d = Path(a.dir)
    brand, brief = load_brand(d), load_brief(d)
    have, meta = image_file(d), read_json(d / "image.json", {})
    if a.variant:
        v = next((x for x in load_variants(d) if x["id"] == a.variant), None)
        if not v:
            raise StudioError(f"no variant {a.variant!r}")
    else:
        v = need_pick(d)[0] if load_pick(d) else None
    stale = bool(v and have and meta.get("engine") != "user" and meta.get("variant", v["id"]) != v["id"])
    if have and not a.force and not stale:
        if not meta:
            write_json(d / "image.json", {"engine": "user", "variant": "", "prompt": "", "model": "", "message": f"{have} provided by you"})
        print(f"{have} already there: kept (use --force to draw a new one)")
        return
    if not v and not a.prompt:
        raise StudioError('no pick yet: give the image prompt with --prompt "...", or put your own image.png in ' + str(d))
    prompt = images.build_prompt(brand, brief, {"layout": "top", **(v or {}), "image_prompt": a.prompt or v["image_prompt"]})
    tmp = d / "image.new.png"
    tmp.unlink(missing_ok=True)
    engine, ok, msg = images.generate(a.engine, prompt, images.api_size(brief), tmp)
    if ok:
        os.replace(tmp, d / "image.png")
        (d / "image.jpg").unlink(missing_ok=True)
    else:
        tmp.unlink(missing_ok=True)
    if ok or not have:
        write_json(d / "image.json", {"engine": engine, "variant": v["id"] if v else "hand", "prompt": prompt,
                                      "model": os.environ.get("STUDIO_IMAGE_MODEL", "gpt-image-1") if engine == "openai" else "", "message": msg})
    else:
        msg += f" The existing {have} is kept."
    print(f"image: {engine}: {msg}")


def cmd_compose(a):
    d = Path(a.dir)
    brand, brief = load_brand(d), load_brief(d)
    if load_pick(d):
        v, headline = need_pick(d)
        meta = read_json(d / "image.json", {})
        if image_file(d) and meta.get("variant") and meta["variant"] != v["id"]:
            print(f"warning: the image was drawn for {meta['variant']}, the pick is {v['id']}: " + cli(d, "image"))
    elif a.headline:
        v, headline = {"id": "hand", "layout": "top", "ground": "background", "subline": ""}, None
    else:
        raise StudioError("no pick yet: " + cli(d, "pick", "<id>") + " or write the piece by hand: " + cli(d, "compose", "--headline", '"..."'))
    headline = a.headline or headline
    v = {**v, **{k: x for k, x in (("subline", a.subline), ("layout", a.layout), ("ground", a.ground)) if x is not None}}
    (d / "piece.html").write_text(compose.render(d, brand, brief, v, headline), encoding="utf-8")
    print(f"piece.html written ({brief['size'][0]}x{brief['size'][1]}): {headline!r}")
    (d / "piece.png").unlink(missing_ok=True)
    print(compose.screenshot(d / "piece.html", d / "piece.png", brief["size"])[1])
    page(a, 4)


def cmd_check(a):
    d = Path(a.dir)
    brand = load_brand(d)
    if not (d / "piece.html").exists():
        raise StudioError("no piece.html: " + cli(d, "compose"))
    results, notes = checks.run(d, brand), checks.judge_notes(d)
    s = checks.summary(results, notes)
    if load_pick(d):
        v, headline = need_pick(d)
    else:
        v, headline = {"id": "hand"}, checks.text((d / "piece.html").read_text(encoding="utf-8"), "hl") or ""
    write_json(d / "check.json", {"at": today(), "variant": v["id"], "headline": headline, "summary": s,
                                  "results": results, "judge": notes})
    for r in results:
        if r["status"] != "pass":
            print(f"  {r['status']}: {r['id']}: {r['say']}")
    print(checks.line(s))
    page(a, 5)


def cmd_decide(a):
    d = Path(a.dir)
    ck = read_json(d / "check.json")
    if not ck:
        raise StudioError("no check.json: " + cli(d, "check"))
    v, headline = need_pick(d) if load_pick(d) else ({"id": "hand"}, ck.get("headline", ""))
    (d / "decision.md").write_text(f"# Decision\n\n- verdict: {a.verdict}\n- words: {a.words}\n- date: {today()}\n"
                                   f"- variant: {v['id']}\n- headline: {headline}\n", encoding="utf-8")
    print(f"decision: {a.verdict} ({v['id']})")
    if a.verdict == "again":
        bans = d / "bans.md"
        head = "" if bans.exists() else "# Bans: what the person refused, read before the next round\n\n"
        with bans.open("a", encoding="utf-8") as f:
            f.write(f'{head}- {today()} {v["id"]} "{headline}": {a.words}\n')
        gone = ["pick.json", "piece.html", "piece.png", "check.json"]
        if read_json(d / "image.json", {}).get("engine", "user") != "user":
            gone += ["image.png", "image.jpg", "image.json"]
        for n in gone:
            (d / n).unlink(missing_ok=True)
        print("bans.md updated; pick, piece and check cleared for round 2")
        return
    page(a, 5)


def cmd_pages(a):
    for step, fn in pages.RENDER.items():
        try:
            print(f"page: {fn(a.dir, lang_of(a))}")
        except StudioError as err:
            print(f"skipped {PAGES[step]}: {err}")


def cmd_status(a):
    d = Path(a.dir)
    names = ["brand.md", "1-brand.html", "brief.md", "2-brief.html", "variants", "3-divergence.html", "pick.json", "image.json",
             "image.png", "piece.html", "piece.png", "judge.md", "check.json", "5-check.html", "decision.md", "bans.md"]
    have = {n: (d / n).exists() for n in names}
    have["image.png"] = bool(image_file(d))
    nvar = len(list((d / "variants").glob("*.json"))) if (d / "variants").is_dir() else 0
    for n in names:
        extra = f" ({nvar})" if n == "variants" else ""
        print(f"  {'x' if have[n] else '-'} {n}{extra}")
    t = lambda n: (d / n).stat().st_mtime if (d / n).exists() else 0
    img = image_file(d)
    hand = not have["pick.json"] and have["piece.html"]  # written by hand: no variants, no pick
    again = not have["pick.json"] and have["decision.md"] and "verdict: again" in (d / "decision.md").read_text(encoding="utf-8")
    newest = max([t(f"variants/{p.name}") for p in (d / "variants").glob("*.json")] or [0]) if nvar else 0
    steps = [(not have["brand.md"], "write brand.md (about ten `key: value` lines) or: " + cli(d, "brand", "--from-dossier", "<brandkit dir>")),
             (not have["1-brand.html"], cli(d, "brand")),
             (not have["brief.md"], "write brief.md (objective, audience, message, format, ...)"),
             (not have["2-brief.html"], cli(d, "brief")),
             (again and newest <= t("decision.md"), "write new variants under variants/ (bans.md lists what was refused), then: " + cli(d, "diverge")),
             (not hand and nvar < 2, "an agent writes variants/v1.json … v4.json (at least 2)"),
             (not hand and t("3-divergence.html") < newest, cli(d, "diverge")),
             (not hand and not have["pick.json"], cli(d, "pick", "<id>")),
             (not hand and not have["image.json"], cli(d, "image")),
             (not have["piece.html"] or t("piece.html") < max(t("pick.json"), t(img) if img else 0), cli(d, "compose")),
             (not have["check.json"] or t("check.json") < t("piece.html"), cli(d, "check") + "   (an agent may write judge.md first)"),
             (not have["decision.md"] or t("decision.md") < t("check.json"), cli(d, "decide", "keep|again", '"<words>"'))]
    nxt = next((c for need, c in steps if need), None)
    print("next: " + (nxt or ("done. The next round reads bans.md." if have["bans.md"] else "done.")))


def build_parser():
    p = argparse.ArgumentParser(prog="studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help, lang=True):
        s = sub.add_parser(name, help=help)
        s.set_defaults(fn=fn)
        s.add_argument("dir", help="the piece folder")
        if lang:
            s.add_argument("--lang", choices=("en", "fr"), help="language of the pages (default: the brief's)")
        return s

    s = add("brand", cmd_brand, "check brand.md, render 1-brand.html (or write brand.md from a brandkit dossier)")
    s.add_argument("--from-dossier", metavar="BRANDKIT_DIR")
    s.add_argument("--force", action="store_true", help="overwrite an existing brand.md")
    add("brief", cmd_brief, "check brief.md, render 2-brief.html")
    add("diverge", cmd_diverge, "check variants/*.json, render 3-divergence.html")
    s = add("pick", cmd_pick, "choose a variant")
    s.add_argument("id")
    s.add_argument("--headline", help="your own headline instead of the variant's")
    s = add("image", cmd_image, "generate the image (or keep yours)", lang=False)
    s.add_argument("--engine", default="auto", choices=("auto", "openai", "codex", "none"))
    s.add_argument("--variant")
    s.add_argument("--prompt", help="the image prompt, when there is no pick")
    s.add_argument("--force", action="store_true", help="draw a new image even if image.png exists")
    s = add("compose", cmd_compose, "write piece.html (and piece.png), render 4-piece.html")
    s.add_argument("--headline", help="your own headline (required when there is no pick)")
    s.add_argument("--subline")
    s.add_argument("--layout", choices=LAYOUTS)
    s.add_argument("--ground", choices=GROUNDS)
    add("check", cmd_check, "check piece.html against the brand, render 5-check.html")
    s = add("decide", cmd_decide, "keep the piece or ask again")
    s.add_argument("verdict", choices=("keep", "again"))
    s.add_argument("words", help="why, in your words")
    add("pages", cmd_pages, "re-render every page that can be")
    add("status", cmd_status, "which files exist, and the next command", lang=False)
    return p


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except StudioError as err:
        print(f"studio: {err}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
