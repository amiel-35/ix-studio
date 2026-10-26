"""answers: what each agent of the studio is allowed to answer. One check per agent: it returns the answer in its one shape or raises a
ValueError that says what does not hold. The commands of scripts/agents call them; the app imports them through app/workflow.py (the simulated
backend and the tests use them too). Nothing here runs a command or touches a disk, except `check_variant`, which reads the format of
scripts/studio.
"""

import importlib.util
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

STUDIO = Path(__file__).resolve().parent.parent / "studio"


def one_line(text) -> str:
    return " ".join(str(text or "").split())


JUDGE_BRIEF = [("objective", "l'objectif"), ("audience", "la cible"), ("message", "le message"), ("cta", "l'appel à l'action"),
               ("fixed", "ce qui ne bouge pas")]  # `fixed` (respect the assets or not) is optional
JUDGE_NEEDED = ("objective", "audience", "message", "cta")
JUDGE_REACHED = ("yes", "partly", "no", "unjudgeable")
JUDGE_LISTS = ("works", "snags", "unsourced", "brand")
JUDGE_ITEMS = 8  # annotations kept per heading


def judge_missing(brief: dict) -> list:
    """What the brief lacks to be judged in full, in words: the target cannot be judged without `audience`, the rest goes on without what is missing."""
    return [label for k, label in JUDGE_BRIEF if k in JUDGE_NEEDED and not (brief.get(k) or "").strip()]


def _notes(raw, what):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{what}: a list of {{where, say}}")
    out = []
    for x in raw:
        if not isinstance(x, dict):
            raise ValueError(f"{what}: each annotation is {{where, say}}")
        where, say = one_line(x.get("where"))[:120], one_line(x.get("say"))[:400]
        if not where or not say:
            raise ValueError(f"{what}: each annotation says where (in words) and what")
        out.append({"where": where, "say": say})
    return out[:JUDGE_ITEMS]


def parse_verdict(raw, has_brand: bool, brief: dict) -> dict:
    """The verdict of a judge, checked and put in its one shape (see above), or a ValueError that says what is wrong. `raw` is the JSON the agent
    wrote (a string, a fenced block is accepted) or a dict. What the backend knows wins over what the agent says: no brand, no `brand` heading;
    no target in the brief, the target is `unjudgeable` with the sentence that says so. A score, if the agent gives one, is left out."""
    if isinstance(raw, (str, bytes)):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < a:
            raise ValueError("no JSON object in the verdict")
        try:
            raw = json.loads(text[a:b + 1])
        except ValueError as err:
            raise ValueError(f"the verdict is not readable JSON ({err})") from None
    if not isinstance(raw, dict):
        raise ValueError("the verdict is a JSON object")
    t = raw.get("target")
    if not isinstance(t, dict) or t.get("reached") not in JUDGE_REACHED or not one_line(t.get("why")):
        raise ValueError(f"target: {{reached, why}}, reached one of {', '.join(JUDGE_REACHED)}")
    missing = judge_missing(brief)
    if "la cible" in missing:
        target = {"reached": "unjudgeable", "why": "non jugeable sur la cible : il manque la cible"}
    else:
        target = {"reached": t["reached"], "why": one_line(t["why"])[:600]}
    out = {"target": target}
    for k in ("works", "snags", "unsourced"):
        if k not in raw:
            raise ValueError(f"{k}: missing (an empty list says there is nothing)")
        out[k] = _notes(raw[k], k)
    if has_brand:
        if not isinstance(raw.get("brand"), list):
            raise ValueError("brand: a list of {where, say} (the brand is known)")
        out["brand"] = _notes(raw["brand"], "brand")
    else:
        out["brand"] = None
    out["missing"] = missing
    return out


PERSONAS_MAX = 4


READING_AIMED = ("yes", "partly", "no")
READING_KEYS = ("why", "understand", "retain", "bother", "unread", "lacks")


PERSONA_HEAD = "Hypothèses à corriger, pas des faits."
PERSONA_FROM = {"dossier": "dossier", "supposé": "supposé", "suppose": "supposé"}


def parse_reading(raw) -> dict:
    """The reading of one reader, checked and put in its one shape (see above), or a ValueError that says what is wrong."""
    if isinstance(raw, (str, bytes)):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < a:
            raise ValueError("no JSON object in the reading")
        try:
            raw = json.loads(text[a:b + 1])
        except ValueError as err:
            raise ValueError(f"the reading is not readable JSON ({err})") from None
    if not isinstance(raw, dict):
        raise ValueError("the reading is a JSON object")
    if raw.get("aimed") not in READING_AIMED:
        raise ValueError(f"aimed: one of {', '.join(READING_AIMED)}")
    out = {"aimed": raw["aimed"]}
    for k in READING_KEYS:
        if not isinstance(raw.get(k), str):
            raise ValueError(f"{k}: a text (an empty one says there is nothing)")
        out[k] = one_line(raw[k])[:600]
    if not out["why"]:
        raise ValueError("why: say why")
    return out


def parse_personas(raw) -> list:
    """What the personas agent answers, checked and written as texts: `{"personas": [{"need", "lines": [{"say", "from"}]}]}`, one to four,
    each with its own need, each line `from` the dossier or supposed. A text starts with PERSONA_HEAD, then its need, then one line each,
    prefixed `(dossier)` or `(supposé)`. A ValueError says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    items = raw.get("personas") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= PERSONAS_MAX:
        raise ValueError(f"il faut de un à {PERSONAS_MAX} personas")
    out, needs = [], set()
    for it in items:
        need = one_line(it.get("need")) if isinstance(it, dict) else ""
        lines = it.get("lines") if isinstance(it, dict) else None
        if not need or not isinstance(lines, list) or not lines:
            raise ValueError("chaque persona a un besoin principal et des lignes")
        if need.casefold() in needs:
            raise ValueError("deux personas ont le même besoin principal")
        needs.add(need.casefold())
        rows = []
        for ln in lines:
            say = one_line(ln.get("say")) if isinstance(ln, dict) else ""
            src = PERSONA_FROM.get(str(ln.get("from", "")).strip().lower()) if isinstance(ln, dict) else None
            if not say or not src:
                raise ValueError("chaque ligne dit ce qu'elle dit et si elle vient du dossier ou si elle est supposée")
            rows.append(f"({src}) {say}")
        out.append("\n".join([PERSONA_HEAD, f"Besoin principal : {need}", *rows]))
    return out


NAMES_MAX = 8


def _name_item(x) -> dict:
    return {"name": one_line(x.get("name"))[:80], "why": one_line(x.get("why"))[:300]} if isinstance(x, dict) else {"name": "", "why": ""}


def parse_names(raw) -> list:
    """What the names agent answers, checked: `{"names": [{"name", "why"}]}`, one to eight, each with its line, no name twice. A ValueError
    says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    items = raw.get("names") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= NAMES_MAX:
        raise ValueError(f"il faut de un à {NAMES_MAX} noms")
    out = [_name_item(x) for x in items]
    if not all(x["name"] and x["why"] for x in out):
        raise ValueError("chaque nom vient avec sa ligne : pourquoi ce nom, et ce qu'il évoque")
    if len({x["name"].casefold() for x in out}) < len(out):
        raise ValueError("un nom est proposé deux fois")
    return out


COMPETITORS_MAX = 6


COMPETITOR_HEAD = "Hypothèse à vérifier, pas un fait."


def parse_competitors(raw) -> list:
    """What the competitors agent answers, checked and written as texts: `{"competitors": [{"name", "sells", "differs", "from"}]}`, one to six,
    each its own name, `from` the dossier or supposed. A text starts with COMPETITOR_HEAD, then `Nom : … (dossier|supposé)`, `Vend : …`,
    `Se distingue : …`. A ValueError says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    items = raw.get("competitors") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= COMPETITORS_MAX:
        raise ValueError(f"il faut de un à {COMPETITORS_MAX} concurrents")
    out, names = [], set()
    for it in items:
        it = it if isinstance(it, dict) else {}
        name, sells, differs = (one_line(it.get(k))[:300] for k in ("name", "sells", "differs"))
        src = PERSONA_FROM.get(str(it.get("from", "")).strip().lower())
        if not name or not sells or not differs or not src:
            raise ValueError("chaque concurrent a un nom, ce qu'il vend, ce qui le distingue, et dit s'il vient du dossier ou s'il est supposé")
        if name.casefold() in names:
            raise ValueError("deux concurrents ont le même nom")
        names.add(name.casefold())
        out.append("\n".join([COMPETITOR_HEAD, f"Nom : {name} ({src})", f"Vend : {sells}", f"Se distingue : {differs}"]))
    return out


# ---------- logos: up to four tracks of logo, each drawn in SVG by the agent ----------
LOGOS_MAX = 4
LOGO_SVG_MAX = 20000  # characters of one drawing
LOGO_BANNED_TAGS = {"script", "foreignobject", "image", "iframe", "object", "embed", "a", "use", "style", "animate", "set"}
LOGO_SVG_ROOT = "{http://www.w3.org/2000/svg}svg"  # the root must be in the SVG namespace, or a browser shows nothing
LOGO_BANNED_VALUES = ("http", "javascript:", "data:", "@import", "//")


def check_svg(text) -> str:
    """A drawing the agent made, kept only if it is well formed, drawn on a viewBox, with no script, no image, no link and nothing outside it.
    Returns it as it is, or raises a ValueError that says what does not hold."""
    text = str(text or "").strip()
    if not text or len(text) > LOGO_SVG_MAX:
        raise ValueError(f"le dessin est vide ou dépasse {LOGO_SVG_MAX} caractères")
    if "<!" in text.replace("<!--", ""):
        raise ValueError("le dessin déclare un type ou une entité")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as err:
        raise ValueError(f"le dessin n'est pas du SVG bien formé ({err})") from None
    if root.tag != LOGO_SVG_ROOT or not root.get("viewBox"):
        raise ValueError("le dessin est un élément svg de l'espace de noms SVG (xmlns), avec un viewBox")
    for el in root.iter():
        if not isinstance(el.tag, str) or el.tag.rsplit("}", 1)[-1].lower() in LOGO_BANNED_TAGS:
            raise ValueError("le dessin contient un script, une image, un lien ou un style")
        for k, v in el.attrib.items():
            if k.rsplit("}", 1)[-1].lower().startswith(("on", "href")) or any(w in v.lower() for w in LOGO_BANNED_VALUES):
                raise ValueError("le dessin contient un script, une image ou un lien extérieur")
    return text


def parse_logos(raw) -> list:
    """What the logos agent answers, checked: `{"logos": [{"idea", "svg"}]}`, one to four, each with its idea in a sentence and its drawing
    (see check_svg). A ValueError says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    items = raw.get("logos") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= LOGOS_MAX:
        raise ValueError(f"il faut de une à {LOGOS_MAX} pistes de logo")
    out = []
    for it in items:
        it = it if isinstance(it, dict) else {}
        idea = one_line(it.get("idea"))[:300]
        if not idea:
            raise ValueError("chaque piste dit son idée en une phrase")
        out.append({"idea": idea, "svg": check_svg(it.get("svg"))})
    return out


# ---------- texts: the posts and the hooks of a project ----------
TEXTS_MAX = 6
TEXT_KINDS = {"accroche": 120, "post": 700}  # the kind of a text, and its length at most


def parse_texts(raw, source="") -> list:
    """What the texts agent answers, checked and written as texts: `{"texts": [{"kind": "accroche" | "post", "text"}]}`, one to six, none twice,
    a hook on one line, a post on a few, no em dash. A number that is not in `source` (the brief and the brand, as text) is a figure invented:
    a ValueError. A ValueError says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    items = raw.get("texts") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= TEXTS_MAX:
        raise ValueError(f"il faut de un à {TEXTS_MAX} textes")
    out, known = [], re.findall(r"\d+", source)
    for it in items:
        it = it if isinstance(it, dict) else {}
        kind, text = str(it.get("kind", "")).strip().lower(), it.get("text")
        if kind not in TEXT_KINDS or not isinstance(text, str):
            raise ValueError("chaque texte dit s'il est une accroche ou un post, et le texte")
        text = one_line(text) if kind == "accroche" else "\n".join(x for x in (one_line(l) for l in text.splitlines()) if x)
        if not text or len(text) > TEXT_KINDS[kind]:
            raise ValueError(f"une accroche tient en une ligne de {TEXT_KINDS['accroche']} signes, un post en {TEXT_KINDS['post']} au plus")
        if "\u2014" in text:
            raise ValueError("pas de tiret cadratin dans les textes")
        if any(n not in known for n in re.findall(r"\d+", text)):
            raise ValueError("un chiffre n'est ni dans le brief ni dans la marque : il est inventé")
        if text.casefold() in (x.casefold() for x in out):
            raise ValueError("un texte est proposé deux fois")
        out.append(text)
    return out


# ---------- research: what the web says of a brand ----------
RESEARCH_MAX = 10
RESEARCH_BELONGING = {"officielle": "officielle", "officielle relayée": "officielle relayée", "officielle relayee": "officielle relayée",
                      "probable": "probable", "incertaine": "incertaine"}


def research_item(x) -> dict:
    """One result, checked: `{"url", "brings", "belonging"}`. A ValueError says what does not hold: no result without an address."""
    x = x if isinstance(x, dict) else {}
    url, brings = one_line(x.get("url"))[:500], one_line(x.get("brings"))[:300]
    belonging = RESEARCH_BELONGING.get(one_line(x.get("belonging")).lower())
    if not url.startswith(("http://", "https://")) or " " in url:
        raise ValueError("chaque résultat a une adresse (http ou https)")
    if not brings or not belonging:
        raise ValueError("chaque résultat dit ce qu'il apporte et son appartenance (officielle, officielle relayée, probable, incertaine)")
    return {"url": url, "brings": brings, "belonging": belonging}


def research_list(items) -> list:
    if not isinstance(items, list) or not 1 <= len(items) <= RESEARCH_MAX:
        raise ValueError(f"il faut de un à {RESEARCH_MAX} résultats")
    out = [research_item(x) for x in items]
    if len({x["url"] for x in out}) < len(out):
        raise ValueError("une adresse est rendue deux fois")
    return out


def parse_research(raw) -> list:
    """What the research agent answers, checked: `{"research": [{"url", "brings", "belonging"}]}`, one to ten, each with its address, a sentence on
    what it brings, and its belonging (officielle, officielle relayée, probable, incertaine). A ValueError says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    return research_list(raw.get("research") if isinstance(raw, dict) else None)


# ---------- interview: the questions asked of the person, the brief the agent writes from the answers ----------
INTERVIEW_QUESTIONS = [  # five at most; the answer to the nth one feeds the nth field of INTERVIEW_KEYS
    "Que veux-tu obtenir avec cette pièce : faire connaître la marque, vendre, promouvoir une offre, autre chose ?",
    "À qui parles-tu : quel segment, ou quel persona de la marque ?",
    "Quelle idée, une seule, doit rester en tête ?",
    "Que doit faire la personne qui la voit : acheter, venir, s'abonner, autre chose ?",
    "Qu'est-ce qui ne bouge pas : un mot, un style, une contrainte ?",
]
INTERVIEW_KEYS = ("objective", "audience", "message", "cta", "fixed")
INTERVIEW_NEEDED = ("objective", "audience")  # never guessed: empty when the person did not say, and then flagged


def parse_interview(raw, answers: list) -> dict:
    """What the interview agent answers, checked: `{"objective", "audience", "message", "cta", "fixed"}`, texts. Gives `{"fields", "missing"}`:
    a field whose question got no answer is empty, whatever the agent wrote; `missing` lists the empty `objective` and `audience`. A ValueError
    says what does not hold."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k, ""), str) for k in INTERVIEW_KEYS):
        raise ValueError("il faut un objet dont les champs sont des textes")
    said = [one_line(a) for a in answers] + [""] * len(INTERVIEW_KEYS)
    fields = {k: one_line(raw.get(k))[:600] if said[n] else "" for n, k in enumerate(INTERVIEW_KEYS)}
    return {"fields": fields, "missing": [k for k in INTERVIEW_NEEDED if not fields[k]]}


def parse_proposal(text: str) -> dict:
    """What the mandates agent answers: `{"common": "...", "mandates": [four]}`, checked and put on one line each."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError("pas de JSON dans la réponse")
    try:
        d = json.loads(text[a:b + 1])
    except ValueError as err:
        raise ValueError(f"JSON illisible ({err})")
    ms = d.get("mandates") if isinstance(d, dict) else None
    if not isinstance(d.get("common"), str) or not d["common"].strip() or not isinstance(ms, list) or len(ms) != 4 or not all(isinstance(x, str) and x.strip() for x in ms):
        raise ValueError("il faut une consigne commune et quatre mandats")
    return {"common": one_line(d["common"]), "mandates": [one_line(x) for x in ms]}


_FILES = None


def studio_files():
    """scripts/studio/files.py, loaded where it is, to read the variants as the studio does (one source of truth for their format)."""
    global _FILES
    if _FILES is None:
        spec = importlib.util.spec_from_file_location("ixs_studio_files", STUDIO / "files.py")
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(STUDIO))
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(str(STUDIO))
        _FILES = mod
    return _FILES


def check_variant(path: Path, vid: str):
    """(ok, why not) for one variant file, with the rules of studio's load_variants."""
    f = studio_files()
    try:
        v = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return False, f"{vid}: not readable JSON ({err})"
    if not isinstance(v, dict):
        return False, f"{vid}: not a JSON object"
    for k in f.VARIANT_KEYS:
        if v.get(k) in ("", None):
            return False, f"{vid}: missing key {k!r}"
    if not isinstance(v["default"], dict) or not all(v["default"].get(k) for k in ("headline", "image")):
        return False, f"{vid}: 'default' needs 'headline' and 'image'"
    if f.norm_layout(v["layout"]) not in f.LAYOUTS:
        return False, f"{vid}: layout must be one of {', '.join(f.LAYOUTS)}"
    if v["ground"] not in f.GROUNDS:
        return False, f"{vid}: ground must be one of {', '.join(f.GROUNDS)}"
    if v.get("fit", "contain") not in ("contain", "cover"):
        return False, f"{vid}: fit must be contain or cover"
    return True, ""


# ---------- storyboard: the script and the shots of a film ----------
SHOTS_MIN, SHOTS_MAX, FILM_MIN, FILM_MAX, SHOT_MAX = 5, 8, 15, 30, 8  # shots; seconds of the film; seconds of a shot
SHOT_VISUALS = ("texte", "logo")


def parse_storyboard(raw, colours=None) -> dict:
    """What the storyboard agent answers, checked: `{"script", "shots": [{seconds, visual, text, colour, read}]}`, five to eight shots, a film of fifteen
    to thirty seconds, each shot on a colour of the brand (`colours`, when they are given). `visual` is `texte` (the text on the screen) or `logo`
    (the brand's logo, no text). A ValueError says what does not hold. The person's corrections go through the same check."""
    if isinstance(raw, str):
        a, b = raw.find("{"), raw.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            raw = json.loads(raw[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})") from None
    script = one_line(raw.get("script"))[:1500] if isinstance(raw, dict) else ""
    items = raw.get("shots") if isinstance(raw, dict) else None
    if not script:
        raise ValueError("il manque le script du film")
    if not isinstance(items, list) or not SHOTS_MIN <= len(items) <= SHOTS_MAX:
        raise ValueError(f"il faut de {SHOTS_MIN} à {SHOTS_MAX} plans")
    allowed = {str(c).lower() for c in colours or []}
    shots = []
    for n, it in enumerate(items, 1):
        it = it if isinstance(it, dict) else {}
        sec, visual, colour = it.get("seconds"), it.get("visual"), str(it.get("colour") or "").strip().lower()
        text, read = one_line(it.get("text"))[:90], one_line(it.get("read"))[:300]
        if isinstance(sec, bool) or not isinstance(sec, (int, float)) or not 1 <= sec <= SHOT_MAX:
            raise ValueError(f"plan {n} : sa durée est un nombre de secondes, de 1 à {SHOT_MAX}")
        if visual not in SHOT_VISUALS:
            raise ValueError(f"plan {n} : visual vaut {' ou '.join(SHOT_VISUALS)}")
        if not re.fullmatch(r"#[0-9a-f]{6}", colour) or (allowed and colour not in allowed):
            raise ValueError(f"plan {n} : sa couleur est une couleur de la marque (#rrggbb)")
        if visual == "texte" and not text:
            raise ValueError(f"plan {n} : le texte à l'écran manque")
        if not read:
            raise ValueError(f"plan {n} : ce qu'on lit manque")
        shots.append({"seconds": sec, "visual": visual, "text": text if visual == "texte" else "", "colour": colour, "read": read})
    total = sum(x["seconds"] for x in shots)
    if not FILM_MIN <= total <= FILM_MAX:
        raise ValueError(f"le film fait {total:g} s : il en faut de {FILM_MIN} à {FILM_MAX}")
    return {"script": script, "shots": shots}


# ---------- rounds: the same piece judged three times, the remarks put side by side ----------
ROUNDS = 3  # the number of rounds: not an option


def parse_rounds(raw, n=ROUNDS) -> dict:
    """The synthesis of the rounds of a judge, checked and put in its one shape, or a ValueError that says what is wrong. `raw` is what the agent
    answered: {"remarks": [{heading, where, say, rounds: [numbers from 1]}]}. The agent says in which rounds each remark came out; the shelf is not
    its to choose: all the rounds is `holds`, one round is `once`, the others are `ambiguous` (the rounds disagree)."""
    if isinstance(raw, (str, bytes)):
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < a:
            raise ValueError("no JSON object in the synthesis")
        try:
            raw = json.loads(text[a:b + 1])
        except ValueError as err:
            raise ValueError(f"the synthesis is not readable JSON ({err})") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("remarks"), list):
        raise ValueError("the synthesis is {remarks: [{heading, where, say, rounds}]}")
    out = {"holds": [], "ambiguous": [], "once": []}
    for x in raw["remarks"]:
        if not isinstance(x, dict) or x.get("heading") not in JUDGE_LISTS:
            raise ValueError(f"remark: heading is one of {', '.join(JUDGE_LISTS)}")
        where, say, rounds = one_line(x.get("where"))[:120], one_line(x.get("say"))[:400], x.get("rounds")
        if not where or not say:
            raise ValueError("remark: says where (in words) and what")
        if not isinstance(rounds, list) or not rounds or not all(isinstance(r, int) and not isinstance(r, bool) and 1 <= r <= n for r in rounds):
            raise ValueError(f"remark: rounds is a list of numbers from 1 to {n}")
        rounds = sorted(set(rounds))
        out["holds" if len(rounds) == n else "once" if len(rounds) == 1 else "ambiguous"].append(
            {"heading": x["heading"], "where": where, "say": say, "rounds": rounds})
    return out
