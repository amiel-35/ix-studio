"""agents: the agents of the studio, one command each. A command holds the prompt of its agent and the check of its answer, runs `claude -p`
and gives the answer as JSON (on the output, and in --out if asked). An answer that does not hold is an error: its reason on stderr, exit 1.

    python3 scripts/agents <command> <inputs.json> [--model MODEL] [--out FILE]

    personas     the personas of a brand            inputs: name, site, description, brief, words, dossier        gives {"personas": [texts]}
    names        the names of a brand               inputs: name, description, brief, words                       gives {"names": [{name, why}]}
    competitors  the competitors of a brand         inputs: as personas                                           gives {"competitors": [texts]}
                 or the landscape of a market       inputs: market (one or two sentences, no brand)               gives {"competitors": [texts]}
    research     what the web says of a brand       inputs: name, site, description                               gives {"research": [{url, brings, belonging}]}
    logos        the logo tracks of a brand         inputs: name, description, colours (hex), fonts, brief, words   gives {"logos": [{idea, svg}]}
    texts        the posts and hooks of a project     inputs: brief, brand, language                                  gives {"texts": [texts]}
    mandates     the instructions of a project      inputs: dir (a piece folder of scripts/studio), words, language   gives {"common", "mandates": [four]}
    variant      one variant of a project           inputs: dir, id, mandate, common, language, work (its folder)                   writes <dir>/variants/<id>.json, gives it
    judge        the verdict on a piece             inputs: image, brief, brand, texts, language                  gives the verdict (works, snags, unsourced, brand)
    storyboard   the script and the shots of a film   inputs: name, brand, colours, brief, language                  gives {"script", "shots": [{seconds, visual, text, colour, read}]}
    reader       the reading of a piece by a persona  inputs: image, persona, texts, language                     gives the reading (aimed, why, understand, ...)
    export-brief the brief of a project, to download  inputs: brief, name, brand_name, confirmed                  gives {"filename", "markdown"}; --out writes the Markdown itself
                 (no call to claude: the brief is written out as it is, what is missing said as missing)
    interview    the brief of a project from answers  inputs: answers (five at most), brand {name, who, personas}, language   gives {"fields", "missing"}
                 (with no `answers`: gives {"questions"}, the five to ask; `missing` lists the objective and the target nobody gave: empty, never guessed)
    engines      the engines of the studio          inputs (optional): image_engine, text_engine, openrouter_model, openrouter_key   keeps them, gives
                                                    {image_engine, text_engine, openrouter_model, key_saved}: the key is never given back

The inputs are a JSON object; a path in it is read from the folder of the inputs file. `brief` (of a brand) is a list of {key, value, state}
(what, who, voice, signature, never, colours; state confirmed or deduced); `brief` (of a piece) is {objective, audience, message, cta, fixed};
`brand` is {name, what, who, voice, signature, never} or {}; `texts` is {headline, subline}. Everything but the names of the files is optional.

The model of each command: --model, else the variable STUDIO_MODEL_<COMMAND> (STUDIO_MODEL_JUDGE...), else its default below. The program run
in place of `claude` is STUDIO_CLAUDE_BIN. The text engine is `claude`, or `openrouter` (STUDIO_TEXT_ENGINE, else the choice of `engines`) for the agents that
only answer (personas, names, competitors, texts, mandates); those that read an image or write a file (variant, judge, reader) stay on `claude`. `ANTHROPIC_API_KEY` is not passed to it unless STUDIO_CLAUDE_USE_API_KEY is set: the plan pays.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engines  # noqa: E402
from answers import (INTERVIEW_KEYS, INTERVIEW_QUESTIONS, ROUNDS, TEXT_KINDS, check_variant, judge_missing, one_line, parse_competitors, parse_interview, parse_logos, parse_names, parse_personas, parse_proposal,  # noqa: E402
                     parse_reading, parse_research, parse_rounds, parse_storyboard, parse_texts, parse_verdict)

BEST, DEFAULT = "claude-fable-5-1", "sonnet"
MODELS = {"personas": DEFAULT, "names": DEFAULT, "competitors": DEFAULT, "research": DEFAULT, "logos": DEFAULT, "texts": DEFAULT, "mandates": DEFAULT, "variant": DEFAULT, "judge": BEST, "reader": BEST, "storyboard": DEFAULT, "rounds": DEFAULT, "interview": DEFAULT}
WRITES = ["--tools=Read,Write", "--permission-mode=acceptEdits", "--permission-prompts=none"]  # an agent that writes a file in its own folder
SEARCHES = ["--tools=WebSearch", "--permission-prompts=none"]  # an agent that searches the web and nothing else
NOTHING = ["--tools", ""]  # an agent that only answers: no tool, no search, nothing but what it is given


class AgentError(Exception):
    """An answer that does not hold, or an agent that did not answer: a sentence a person can read."""


class Result(NamedTuple):
    code: int
    out: str
    err: str


def run_command(argv, cwd=None, env=None, timeout=None) -> Result:
    """The real runner. Never waits for an input (stdin is closed: claude would wait for it), never raises."""
    try:
        r = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=timeout)
        return Result(r.returncode, r.stdout or "", r.stderr or "")
    except subprocess.TimeoutExpired:
        return Result(124, "", f"no answer after {int(timeout or 0)} s")
    except FileNotFoundError:
        return Result(127, "", f"command not found: {argv[0]}")
    except OSError as err:
        return Result(126, "", f"cannot run {argv[0]}: {err}")


def tail(res, n=240) -> str:
    """The last meaningful line of a failed command, to say why in one line."""
    for text in (res.err, res.out):
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if lines:
            return lines[-1][:n]
    return f"exit {res.code}"


CALLS = []  # the answers of claude in this run: on a failure, the raw one goes to stderr, for the log of whoever ran the command


def ask(prompt, cmd, flags, cwd, timeout, model=None, runner=run_command):
    """One `claude -p` call, in `cwd`. The prompt comes first: --tools takes a list and would swallow what follows it."""
    if flags is NOTHING and engines.text_engine() == "openrouter":
        code, text, err = engines.openrouter_answer(prompt, model, timeout)
        res = Result(code, text, err)
        CALLS.append(res)
        return res
    exe = os.environ.get("STUDIO_CLAUDE_BIN") or "claude"
    model = model or os.environ.get("STUDIO_MODEL_" + cmd.upper()) or MODELS[cmd]
    env = dict(os.environ)
    if not env.get("STUDIO_CLAUDE_USE_API_KEY"):
        env.pop("ANTHROPIC_API_KEY", None)
    res = runner([exe, "-p", prompt, "--model", model, "--no-session-persistence", "--restricted", *flags], cwd=str(cwd) if cwd else None, env=env, timeout=timeout)
    CALLS.append(res)
    return res


def raw_answer(n=4000) -> str:
    """What claude said in its last call, for a failure: its output and its errors, the end of each. The reason stays on the last line."""
    if not CALLS:
        return ""
    res = CALLS[-1]
    parts = [f"--- {name} de claude ---\n{text.strip()[-n:]}\n" for name, text in (("réponse brute", res.out), ("erreurs", res.err)) if text.strip()]
    return "".join(parts)


def read_text(f) -> str:
    f = Path(f)
    return f.read_text(encoding="utf-8") if f.exists() else ""


# ---------- the brand: personas, names, competitors ----------
LABELS = {"what": "what it is", "who": "for whom", "voice": "its voice", "signature": "its signature", "never": "the words it never says", "colours": "its colours"}


def personas_prompt(i) -> str:
    brief = "\n".join(f"- {LABELS[x['key']]}: {x['value']} ({'confirmed by the person' if x['state'] == 'confirmed' else 'deduced, not confirmed'})" for x in i.get("brief") or [])
    words = one_line(i.get("words"))
    dossier = read_text(i["dossier"])[:30000] if i.get("dossier") else ""
    return (
        "You imagine the people a brand's still ads (a poster, a social post) will meet. You only use what is given below: no search, no other "
        "source. You write hypotheses for the person to correct, not facts.\n\n"
        f"=== the brand ===\nname: {i['name']}\nsite: {i.get('site') or '(none)'}\ndescription: {one_line(i.get('description')) or '(none)'}\n"
        f"=== the brief of the brand ===\n{brief or '(empty)'}\n"
        + (f"=== what the person says of the brand, in their words ===\n{words}\n" if words else "")
        + f"=== the dossier of the brand (brand.json) ===\n{dossier or '(empty)'}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"personas": [{"need": "...", "lines": [{"from": "dossier" | "supposé", "say": "..."}]}]}\n'
        "- personas: up to four, each with a different main need (need: what this person wants, in a few words).\n"
        "- lines: four to six short, concrete sentences, in French, addressing the persona as tu (\"tu as la cinquantaine, tu...\"): who they are; "
        "where and how they meet an ad of the brand (in the metro in three seconds, in a feed under the thumb...); what they already think of the "
        "brand and of its subject; their own words, quoted.\n"
        "- from: \"dossier\" when the line comes from what is given above, \"supposé\" when you suppose it. Most lines are supposed: say so.\n"
        "- No invented statistic, share, figure or number of people. An age is a guess, marked supposé.\n"
        "- Plain French, no em dash, no emoji.")


def names_prompt(i) -> str:
    brief = "\n".join(f"- {LABELS[x['key']]}: {x['value']}" for x in i.get("brief") or [] if x["key"] != "colours")
    words = one_line(i.get("words"))
    return (
        "You propose names for a brand. You only use what is given below: no search, no other source.\n\n"
        f"=== the brand ===\nits provisional name (a working title, not to keep): {i['name']}\ndescription: {one_line(i.get('description')) or '(none)'}\n"
        f"=== the brief of the brand ===\n{brief or '(empty)'}\n"
        + (f"=== what the person says of the brand, in their words ===\n{words}\n" if words else "")
        + "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"names": [{"name": "...", "why": "..."}]}\n'
        "- names: up to eight, each different from the others in what it suggests (a place, a gesture, a promise, a sound...).\n"
        "- name: one to three words, easy to say and to spell in French.\n"
        "- why: one sentence in French: why this name, and what it evokes.\n"
        "- Do not claim a name is free to use: nobody checked.\n"
        "- Plain French, no em dash, no emoji.")


def competitors_prompt(i) -> str:
    brief = "\n".join(f"- {LABELS[x['key']]}: {x['value']} ({'confirmed by the person' if x['state'] == 'confirmed' else 'deduced, not confirmed'})" for x in i.get("brief") or [])
    words = one_line(i.get("words"))
    dossier = read_text(i["dossier"])[:30000] if i.get("dossier") else ""
    return (
        "You name the competitors of a brand: the others its customers could buy from instead. You use what is given below and what you know "
        "of the market: no search, no other source. You write hypotheses for the person to check, not facts.\n\n"
        f"=== the brand ===\nname: {i['name']}\nsite: {i.get('site') or '(none)'}\ndescription: {one_line(i.get('description')) or '(none)'}\n"
        f"=== the brief of the brand ===\n{brief or '(empty)'}\n"
        + (f"=== what the person says of the brand, in their words ===\n{words}\n" if words else "")
        + f"=== the dossier of the brand (brand.json) ===\n{dossier or '(empty)'}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"competitors": [{"name": "...", "from": "dossier" | "supposé", "sells": "...", "differs": "..."}]}\n'
        "- competitors: up to six, each a different name.\n"
        "- sells: one line, in French: what it sells and to whom.\n"
        "- differs: one line, in French: what sets it apart from the brand (its angle, its tone).\n"
        "- from: \"dossier\" when the competitor is named in what is given above, \"supposé\" when you suppose it.\n"
        "- No invented figure: no market share, no turnover, no ranking, no number of customers.\n"
        "- Plain French, no em dash, no emoji.")


def research_prompt(i) -> str:
    return (
        "You search the web for what is said of a brand: its site, its campaigns, what the press writes of it. Use the web search tool. You find "
        "addresses to look at, you do not copy their content.\n\n"
        f"=== the brand ===\nname: {i['name']}\nsite: {i.get('site') or '(none)'}\ndescription: {one_line(i.get('description')) or '(none)'}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"research": [{"url": "https://...", "brings": "...", "belonging": "officielle" | "officielle relayée" | "probable" | "incertaine"}]}\n'
        "- research: ten at most, each a different address, each one you actually found. No result without its address, never an address you guess.\n"
        "- brings: one sentence, in French: what it brings to know the brand (its colours, its tone, a campaign, its logo).\n"
        "- belonging: \"officielle\" when the address is on the domain of the brand; \"officielle relayée\" when it is an article that names the brand "
        "and its agency; \"probable\" when it is very likely about this brand; \"incertaine\" when it may be about another brand of the same name.\n"
        "- Plain French, no em dash, no emoji.")


def answer_of(cmd, i, prompt, parse, model, runner, flags=NOTHING):
    """A brand agent: it only answers; what it said is checked by `parse`."""
    with tempfile.TemporaryDirectory(prefix=f"ixs-{cmd}-") as work:
        res = ask(prompt, cmd, flags, work, 300, model, runner)
    if res.code:
        raise AgentError("l'agent n'a pas répondu : " + tail(res))
    try:
        return {cmd: parse(res.out)}
    except ValueError as err:
        raise AgentError(f"réponse de l'agent illisible : {err}") from None


def cmd_personas(i, model, runner):
    return answer_of("personas", i, personas_prompt(i), parse_personas, model, runner)


def cmd_names(i, model, runner):
    return answer_of("names", i, names_prompt(i), parse_names, model, runner)


# landscape: the same agent, given a market instead of a brand
def landscape_prompt(i) -> str:
    return (
        "You draw the competitive landscape of a market: the players a customer of this market could buy from. You use what is given below and what "
        "you know of the market: no search, no other source. You write hypotheses for the person to check, not facts.\n\n"
        f"=== the market, in the person's words ===\n{one_line(i['market'])}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"competitors": [{"name": "...", "from": "dossier" | "supposé", "sells": "...", "differs": "..."}]}\n'
        "- competitors: up to six players of this market, each a different name.\n"
        "- sells: one line, in French: what it sells and to whom.\n"
        "- differs: one line, in French: its position in the market (its angle, its tone, what it is known for).\n"
        "- from: \"dossier\" when the player is named in the description of the market above, \"supposé\" otherwise. A player you are not sure exists "
        "is left out: nothing invented.\n"
        "- No invented figure: no market share, no turnover, no price, no ranking, no number of customers.\n"
        "- Plain French, no em dash, no emoji.")


def cmd_competitors(i, model, runner):
    if i.get("market"):
        return answer_of("competitors", i, landscape_prompt(i), parse_competitors, model, runner)
    return answer_of("competitors", i, competitors_prompt(i), parse_competitors, model, runner)


# ---------- logos: the logo tracks of a brand, drawn in SVG ----------
def logos_prompt(i) -> str:
    brief = "\n".join(f"- {LABELS[x['key']]}: {x['value']}" for x in i.get("brief") or [] if x["key"] != "colours")
    words, colours, fonts = one_line(i.get("words")), ", ".join(i.get("colours") or []), ", ".join(i.get("fonts") or [])
    return (
        "You draw logo tracks for a brand, in SVG, by hand: you write the SVG code, there is no image engine. You only use what is given below: no "
        "search, no other source.\n\n"
        f"=== the brand ===\nname: {i['name']}\ndescription: {one_line(i.get('description')) or '(none)'}\n"
        f"colours (hex): {colours or '(none given: choose two or three that fit)'}\nfonts: {fonts or '(none given: use a generic family such as Georgia or Arial)'}\n"
        f"=== the brief of the brand ===\n{brief or '(empty)'}\n"
        + (f"=== what the person says of the brand, in their words ===\n{words}\n" if words else "")
        + "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"logos": [{"idea": "...", "svg": "<svg ...>...</svg>"}]}\n'
        "- logos: up to four, each with a different idea (a wordmark, a monogram, a symbol with the name, a badge...).\n"
        "- idea: one sentence in French: what the logo says and why.\n"
        "- svg: one complete drawing, its root <svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 240 120\"> (the xmlns is required), the name of the brand written in it with a <text> element in the "
        "fonts of the brand, in its colours, on a transparent background or one of its colours. Simple shapes (rect, circle, path, line, text, g). "
        "No script, no <style>, no <image>, no link, no href, no external address, no filter, no animation; every attribute is written inline. "
        "Under 4000 characters each.\n"
        "- Do not claim a logo is free to use: nobody checked.\n"
        "- Plain French in the ideas, no em dash, no emoji.")


def cmd_logos(i, model, runner):
    return answer_of("logos", i, logos_prompt(i), parse_logos, model, runner)
# ---------- texts: the posts and hooks of a project ----------
def texts_source(i) -> str:
    """The brief and the brand as one text: what the numbers of the texts are checked against."""
    return json.dumps({"brief": i.get("brief") or {}, "brand": i.get("brand") or {}}, ensure_ascii=False)


def texts_prompt(i) -> str:
    brief, brand, lang = i.get("brief") or {}, i.get("brand") or {}, i.get("language") or "fr"
    lines = [f"- {label}: {one_line(brief.get(k))}" for k, label in (("objective", "objective"), ("audience", "audience"), ("message", "message"),
                                                                       ("cta", "call to action"), ("fixed", "what does not move")) if one_line(brief.get(k))]
    voice = [f"- {label}: {one_line(brand.get(k))}" for k, label in (("name", "name"), ("what", "what it is"), ("who", "for whom"), ("voice", "its voice"),
                                                                    ("signature", "its signature"), ("never", "the words it never says")) if one_line(brand.get(k))]
    return (
        "You write the short texts of a project for a brand: hooks and social posts. You only use what is given below: no search, no other source.\n\n"
        f"=== the brief of the project ===\n{chr(10).join(lines) or '(empty)'}\n"
        f"=== the brand ===\n{chr(10).join(voice) or '(none)'}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"texts": [{"kind": "accroche" | "post", "text": "..."}]}\n'
        "- texts: six at most, each different from the others in its angle; the message of the brief is what they say.\n"
        f"- accroche: one short line, {TEXT_KINDS['accroche']} characters at most. post: a few lines, {TEXT_KINDS['post']} characters at most, lines separated by a line break.\n"
        "- Write in the voice of the brand, and never use the words it never says.\n"
        "- Nothing invented: no figure, no label, no endorsement, no promise, no claim that is not in the brief or in the brand. When in doubt, leave it out.\n"
        f"- Write in the language of the brief ({lang}), plainly, addressing the reader as the brand does, without em dashes nor emoji.")


def cmd_texts(i, model, runner):
    if not isinstance(i.get("brief"), dict) or not any(one_line(v) for v in i["brief"].values()):
        raise AgentError("inputs: brief is empty, the texts come from it")
    return answer_of("texts", i, texts_prompt(i), lambda raw: parse_texts(raw, texts_source(i)), model, runner)


# ---------- the project: mandates, variants ----------
def mandates_prompt(i) -> str:
    piece, lang, words = Path(i["dir"]), i.get("language") or "fr", one_line(i.get("words"))
    return (
        "You prepare the instructions of four creative agents who will each write one variant of a still ad (a poster or a social post) "
        "for a brand. You only write the instructions, nothing else.\n\n"
        f"=== brand.md ===\n{read_text(piece / 'brand.md')}\n=== brief.md ===\n{read_text(piece / 'brief.md')}\n"
        f"=== references.md (the visuals the person kept; none if empty) ===\n{read_text(piece / 'references.md')}\n"
        + (f"=== what the person says of the brand, in their words ===\n{words}\n" if words else "")
        + (f"=== bans.md (already refused) ===\n{read_text(piece / 'bans.md')}\n" if (piece / "bans.md").exists() else "")
        + "\nReturn ONLY one JSON object, no prose, no code fence:\n"
          '{"common": "...", "mandates": ["...", "...", "...", "..."]}\n'
          "- common: one paragraph, plain sentences, the rules every agent follows: the language of the brief; nothing invented (no figure, "
          "place, label, award or promise that is in neither the brand nor the brief); each line reread for any second reading "
          "(sexual, vulgar, ridiculous, hurtful); the image carries no text.\n"
          "- mandates: four stances, each a short phrase (under 12 words) naming a way of looking at this brief; they must look somewhere "
          "else from one another. The fourth is a rupture: it breaks the codes of the category and starts with \"Rupture : \". A mandate gives "
          "a point of view, never a headline, a picture or a layout already drawn.\n"
          "- The brand does not diverge, the idea does: never ask for another palette, typeface or logo.\n"
          f"Write common and mandates in the language of the brief ({lang}).")


def cmd_mandates(i, model, runner):
    with tempfile.TemporaryDirectory(prefix="ixs-mandates-") as work:
        res = ask(mandates_prompt(i), "mandates", NOTHING, work, 240, model, runner)
    if res.code:
        raise AgentError(tail(res))
    try:
        return parse_proposal(res.out)
    except ValueError as err:
        raise AgentError(str(err)) from None


def variant_prompt(vid, mandate, common, lang) -> str:
    return (
        "You are one of several creative agents working blind, each on one mandate, for one still ad (a poster or a social post). "
        "You do not see the others' work.\n\n"
        "Read, in the current folder: brand.md, brief.md, references.md if there is one (open the local images it lists in refs/: they give the "
        "grammar to keep, light included, never a picture to copy) and bans.md if there is one (what the person already refused: do not repeat it).\n\n"
        f"Your mandate: {mandate}\nRules every agent follows: {common}\n\n"
        "Method:\n"
        "1. First write down what you would have made by default for this brief (a headline and the image), then set it aside: your variant must not be it.\n"
        "2. Write your variant from your mandate.\n"
        f"Write ONE file, ./{vid}.json, a UTF-8 JSON object with these keys and no other file:\n"
        '  "mandate": your mandate, as given;\n'
        '  "default": {"headline": "...", "image": "..."}, the default you set aside;\n'
        '  "headline": the headline;\n'
        '  "subline": a short line under it, or "";\n'
        '  "image_prompt": what the image shows, in plain words; the image carries no text and no letters;\n'
        '  "layout": one of side, stack, ground, overlay-top, overlay-bottom, full;\n'
        '  "ground": one of background, text, accent (the colour of the text zone);\n'
        '  "why": one or two sentences: why this answers the mandate;\n'
        '  optionally "fit": "contain" (the whole image shows, the default) or "cover" (it may be cropped).\n\n'
        "Rules:\n"
        "- The brand does not diverge, the idea does: never change the palette, the type or the logo.\n"
        "- Nothing is invented: no figure, testimonial, place, label, award or promise that is in neither brand.md nor brief.md.\n"
        "- Pick a layout that does not cover the subject of the image. side, stack and ground never overlap the image; use overlay-top or "
        "overlay-bottom only when your image prompt leaves that edge calm. When brief.md sets a layout, use exactly that one.\n"
        f"- Before you write the file, reread your headline and your subline in the language of the brief ({lang}) as a reader with a dirty mind or a "
        "mocking one would: any second reading (sexual, vulgar, ridiculous, hurtful), slang included. If you find one, rewrite the line. No word list: use your eye.\n"
        "- Write only that one file, and read and write nothing outside the current folder. When it is written, answer with its name and nothing else.")


def prepare_variant(piece: Path, wdir: Path):
    """A folder of its own for one agent: the brand, the brief, the bans and the references (their images copied), nothing of the others."""
    (wdir / "refs").mkdir(parents=True)
    brand = [l for l in read_text(piece / "brand.md").splitlines() if not re.match(r"^[-*]\s+logo\s*:", l.strip())]
    (wdir / "brand.md").write_text("\n".join(brand) + "\n", encoding="utf-8")
    for n in ("brief.md", "bans.md"):
        if (piece / n).exists():
            shutil.copy2(piece / n, wdir / n)
    refs, k = [], 0
    for line in read_text(piece / "references.md").splitlines():
        if not line.startswith("- "):
            continue
        ref, sep, note = line[2:].partition(" | ")
        ref = ref.strip()
        src = piece / ref
        if not ref.startswith(("http://", "https://")) and src.is_file():
            k += 1
            dst = f"refs/{k:02d}-{re.sub(r'[^A-Za-z0-9._-]+', '-', src.name)}"
            shutil.copy2(src, wdir / dst)
            ref = dst
        refs.append(f"- {ref}{sep}{note}")
    if refs:
        (wdir / "references.md").write_text("\n".join(refs) + "\n", encoding="utf-8")


def cmd_variant(i, model, runner):
    vid, piece = i["id"], Path(i["dir"])
    with tempfile.TemporaryDirectory(prefix=f"ixs-{vid}-") as tmp:
        wdir = Path(tmp)
        if i.get("work"):  # a folder the caller names (and cleans): it can look at what the agent left in it
            wdir = Path(i["work"])
            shutil.rmtree(wdir, ignore_errors=True)
        prepare_variant(piece, wdir)
        res = ask(variant_prompt(vid, i["mandate"], i.get("common", ""), i.get("language") or "fr"), "variant", WRITES, wdir, 600, model, runner)
        f = wdir / f"{vid}.json"
        if not f.exists():
            raise AgentError(f"{vid}: " + (tail(res) if res.code else "no variant file written"))
        ok, why = check_variant(f, vid)
        if not ok:
            raise AgentError(why)
        (piece / "variants").mkdir(exist_ok=True)
        shutil.copy2(f, piece / "variants" / f"{vid}.json")
        return json.loads(f.read_text(encoding="utf-8"))


# ---------- the piece: judge, reader ----------
def judge_inputs(brief: dict, brand: dict, texts=None) -> str:
    """inputs.md, what the judge reads beside the picture: the brief (what it lacks said as such), the words of the piece, the brand."""
    say = lambda v: v if (v or "").strip() else "(non donné)"
    lines = ["# Ce que le juge reçoit", "", "## Le brief", f"- objectif : {say(brief.get('objective'))}", f"- cible : {say(brief.get('audience'))}",
             f"- message : {say(brief.get('message'))}", f"- appel à l'action : {say(brief.get('cta'))}",
             f"- ce qui ne bouge pas (respecter ou non les assets) : {say(brief.get('fixed'))}", "", "## La pièce", "- son image : piece.png (ouvre-la)"]
    if texts:
        lines += [f"- titre : {say(texts.get('headline'))}", f"- sous-ligne : {say(texts.get('subline'))}"]
    else:
        lines.append("- ses textes : ceux qu'on lit sur l'image")
    lines += ["", "## La marque"]
    if brand:
        labels = {"name": "nom", "what": "ce qu'elle est", "who": "pour qui", "voice": "sa voix", "signature": "sa signature", "never": "ce qu'elle ne dit jamais"}
        lines += [f"- {labels[k]} : {v}" for k, v in brand.items()]
    else:
        lines.append("- aucune : pas de rubrique brand (\"brand\": null)")
    return "\n".join(lines) + "\n"


def judge_prompt(has_brand: bool, missing: list, lang="fr") -> str:
    return (
        "You are the judge of one still ad (a poster or a social post). You read it as the person it is aimed at would, and you write down what "
        "you see. You give no score, you block nothing, and you do not judge the morals of the brand or of its product.\n\n"
        "Read ./inputs.md (the brief, the words of the piece, the brand if there is one) and open ./piece.png with the Read tool: you see the "
        "image. Look at the image and its words together.\n\n"
        "Write ONE file, ./verdict.json, a UTF-8 JSON object with exactly these keys:\n"
        '  "target": {"reached": "yes" | "partly" | "no", "why": "..."}: is the person aimed at reached, and why, from their point of view;\n'
        '  "works": what works;\n'
        '  "snags": what catches: a double meaning, a hierarchy that does not read, a cliché, an image that does not answer the headline;\n'
        '  "unsourced": every fact one could check (a figure, a label, a guarantee, an award, a dated promise, a ranking) that is in the piece and in '
        "none of the entries: do not say it is false, say you were given nothing to believe it. The price, the product's name and the town are not "
        "aimed at;\n"
        + ('  "brand": the voice and the tone of the piece against the brand\'s (only that: colours, type, contrast, banned words, hierarchy and '
           "signature are checked elsewhere);\n" if has_brand else '  "brand": null (no brand is given);\n')
        + "Each of works, snags, unsourced" + (", brand" if has_brand else "") + ' is a list of {"where": "...", "say": "..."} (an empty list when '
        'there is nothing). "where" names what it aims at in words, as one would point at it ("le titre en haut", "le bandeau du bas", '
        '"l\'image"), never coordinates nor a drawn zone. Keep each list short: what matters, at most five.\n'
        "What the brief says does not move (its line \"ce qui ne bouge pas\") is imposed: never count it as a snag, and do not ask for "
        "what it rules out (an empty square where the logo goes, for instance, is the brief's choice, not a fault of the piece).\n"
        + (f"The brief lacks {', '.join(missing)}: do not ask anything. "
           + ('Set target to {"reached": "unjudgeable", "why": "non jugeable sur la cible : il manque la cible"} and ' if "la cible" in missing else "Say it where it matters and ")
           + "judge the rest.\n" if missing else "")
        + f"Write the text in the language of the brief ({lang}), plainly, addressing the person as tu, without em dashes nor emoji.\n"
        "Write only that one file, and read and write nothing outside the current folder. When it is written, answer with its name and nothing else.")


def reader_inputs(persona: str, texts=None) -> str:
    """inputs.md, what a reader reads beside the picture: who it is, and the words of the piece. Not the brief, not the brand, not the other readers."""
    lines = ["# Qui tu es", "", persona, "", "## La pièce", "- son image : piece.png (ouvre-la)"]
    if texts:
        lines += [f"- titre : {texts.get('headline') or '(aucun)'}", f"- sous-ligne : {texts.get('subline') or '(aucune)'}"]
    else:
        lines.append("- ses textes : ceux qu'on lit sur l'image")
    return "\n".join(lines) + "\n"


def reader_prompt(lang="fr") -> str:
    return (
        "You are not a critic. Read ./inputs.md: its first part says who you are. Be that person, and only that person. Then open ./piece.png "
        "with the Read tool: it is an ad (a poster or a social post) you come across. You are told nothing else about it.\n\n"
        "Write ONE file, ./reading.json, a UTF-8 JSON object with exactly these keys, every text in the first person (\"je\"), as this person "
        "would say it:\n"
        '  "aimed": "yes" | "partly" | "no": does this piece speak to me;\n'
        '  "why": why, from my life;\n'
        '  "understand": what I understand it says;\n'
        '  "retain": what I keep of it once I have looked away;\n'
        '  "bother": what bothers me, or "" if nothing;\n'
        '  "unread": what I do not read, do not see or skip, or "";\n'
        '  "lacks": what I miss to understand or to believe it, or "".\n'
        "Never say whether you would buy, try or do what it asks: say what you understand, what you do not read and what you miss. "
        "Do not grade the piece, do not give advice to whoever made it.\n"
        f"Write in the language of the piece ({lang}), plainly, a few sentences at most per key, without em dashes nor emoji.\n"
        "Write only that one file, and read and write nothing outside the current folder. When it is written, answer with its name and nothing else.")


def read_piece(cmd, i, inputs_md, prompt, written, model, runner, missing, unreadable, parse):
    """A judge or a reader, in a folder of its own: the picture and inputs.md in, a file out (`written`), checked by `parse`."""
    image = Path(i["image"])
    if not image.is_file():
        raise AgentError(f"image: no file {image}")
    with tempfile.TemporaryDirectory(prefix=f"ixs-{cmd}-") as tmp:
        wdir = Path(tmp)
        shutil.copy2(image, wdir / "piece.png")
        (wdir / "inputs.md").write_text(inputs_md, encoding="utf-8")
        res = ask(prompt, cmd, WRITES, wdir, 400, model, runner)
        f = wdir / written
        if not f.exists():
            raise AgentError(missing + (f" : {tail(res)}" if res.code else ""))
        try:
            return parse(f.read_text(encoding="utf-8", errors="replace"))
        except ValueError as err:
            raise AgentError(f"{unreadable} : {err}") from None


def cmd_judge(i, model, runner):
    brief, brand, lang = i.get("brief") or {}, i.get("brand") or {}, i.get("language") or "fr"
    return read_piece("judge", i, judge_inputs(brief, brand, i.get("texts")), judge_prompt(bool(brand), judge_missing(brief), lang), "verdict.json", model,
                      runner, "le juge n'a pas écrit de verdict", "verdict du juge illisible", lambda text: parse_verdict(text, bool(brand), brief))


def cmd_reader(i, model, runner):
    return read_piece("reader", i, reader_inputs(i["persona"], i.get("texts")), reader_prompt(i.get("language") or "fr"), "reading.json", model, runner,
                      "le lecteur n'a pas écrit sa lecture", "lecture illisible", parse_reading)

def cmd_research(i, model, runner):
    return answer_of("research", i, research_prompt(i), parse_research, model, runner, SEARCHES)

# ---------- the project: the interview ----------
def interview_prompt(i, answers) -> str:
    brand, personas = i.get("brand") or {}, [one_line(x)[:400] for x in (i.get("brand") or {}).get("personas") or []]
    qa = "\n".join(f"{n + 1}. {q}\n   réponse ({k}) : {one_line(answers[n]) if n < len(answers) and one_line(answers[n]) else '(aucune)'}"
                   for n, (q, k) in enumerate(zip(INTERVIEW_QUESTIONS, INTERVIEW_KEYS)))
    return (
        "You write the brief of a still ad (a poster or a social post) from the answers a person gave to a few questions. You only use what is "
        "given below: no search, no other source.\n\n"
        f"=== the brand ===\nname: {brand.get('name') or '(none)'}\nfor whom, as the brand says it: {one_line(brand.get('who')) or '(none)'}\n"
        + "".join(f"persona of the brand {n + 1}: {t}\n" for n, t in enumerate(personas))
        + f"=== the questions and the answers ===\n{qa}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"objective": "...", "audience": "...", "message": "...", "cta": "...", "fixed": "..."}\n'
        "- Each field is written from the answer of the same name, in a short sentence or a few words. Reword it, never add to it.\n"
        "- objective: what the piece must obtain (awareness, purchase, promotion...), as the person said it.\n"
        "- audience: the segment or the persona of the brand the person pointed to; you may name the persona of the brand they meant.\n"
        "- message: the one idea to remember, cleaned of any solution already drawn (\"a photo of the bottle on a beach\" is a solution, not a message).\n"
        "- A field whose answer is \"(aucune)\" is an empty string: never guess the objective, the audience or anything else.\n"
        "- No invented figure, place, label, award or promise.\n"
        f"Write in the language of the brief ({i.get('language') or 'fr'}), plain, no em dash, no emoji.")


def cmd_interview(i, model, runner):
    """With no `answers`: the questions (nothing is asked of claude). With the answers: the brief they make, and what it still lacks."""
    if "answers" not in i:
        return {"questions": INTERVIEW_QUESTIONS}
    answers = i["answers"]
    if not isinstance(answers, list) or len(answers) > len(INTERVIEW_QUESTIONS) or not all(isinstance(x, str) for x in answers):
        raise AgentError(f"inputs: answers is a list of {len(INTERVIEW_QUESTIONS)} texts at most")
    if not any(x.strip() for x in answers):
        raise AgentError("inputs: aucune réponse, rien à écrire")
    with tempfile.TemporaryDirectory(prefix="ixs-interview-") as work:
        res = ask(interview_prompt(i, answers), "interview", NOTHING, work, 240, model, runner)
    if res.code:
        raise AgentError("l'agent n'a pas répondu : " + tail(res))
    try:
        return parse_interview(res.out, answers)
    except ValueError as err:
        raise AgentError(f"réponse de l'agent illisible : {err}") from None


# ---------- the film: storyboard ----------
def storyboard_prompt(i) -> str:
    brand = "\n".join(f"- {LABELS[k]}: {one_line(v)}" for k, v in (i.get("brand") or {}).items() if k in LABELS and one_line(v))
    brief = "\n".join(f"- {k}: {one_line(v)}" for k, v in (i.get("brief") or {}).items() if one_line(v))
    lang = i.get("language") or "fr"
    return (
        "You write the script and the shots of a short film for a brand: a vertical film of 15 to 30 seconds, made by code (texts and the logo "
        "moving on colours of the brand). You only use what is given below: no search, no other source.\n\n"
        f"=== the brand ===\nname: {i['name']}\n{brand or '(nothing more)'}\ncolours of the brand: {', '.join(i.get('colours') or []) or '(none given)'}\n"
        f"=== the brief of the project (confirmed by the person) ===\n{brief or '(empty)'}\n"
        "\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"script": "...", "shots": [{"seconds": 3, "visual": "texte" | "logo", "text": "...", "colour": "#rrggbb", "read": "..."}]}\n'
        "- script: two or three sentences: what the film says, from the first shot to the last.\n"
        "- shots: five to eight, in order; the seconds of all the shots add up to 15 at least and 30 at most; one shot lasts from 1 to 8 seconds.\n"
        "- visual: \"texte\" shows the text on the screen; \"logo\" shows the logo of the brand alone (text empty). The last shot is the logo.\n"
        "- text: what is on the screen, at most 12 words, in the language of the brief; short enough to be read in the seconds of the shot.\n"
        "- colour: one of the colours of the brand given above, never another.\n"
        "- read: the line one reads or hears over the shot (a sentence in the language of the brief): the script of this shot.\n"
        "- Nothing is invented: no figure, price, date, label, award, testimonial or promise that is in neither the brand nor the brief. "
        "Never use the words the brand never says.\n"
        f"- Plain {lang}, addressing the audience as the brief does, no em dash, no emoji.")


def cmd_storyboard(i, model, runner):
    with tempfile.TemporaryDirectory(prefix="ixs-storyboard-") as work:
        res = ask(storyboard_prompt(i), "storyboard", NOTHING, work, 300, model, runner)
    if res.code:
        raise AgentError("l'agent n'a pas répondu : " + tail(res))
    try:
        return parse_storyboard(res.out, i.get("colours"))
    except ValueError as err:
        raise AgentError(f"réponse de l'agent illisible : {err}") from None


# ---------- rounds: the judge three times, then the remarks put side by side ----------
def rounds_prompt(verdicts: list) -> str:
    heads = {"works": "ce qui marche", "snags": "ce qui accroche", "unsourced": "sans provenance", "brand": "la marque"}
    text = "\n\n".join(f"=== tour {n} ===\n" + "\n".join(f"[{k}] {x['where']} : {x['say']}" for k in heads for x in v.get(k) or []) for n, v in enumerate(verdicts, 1))
    return (
        f"A judge read the same still ad {len(verdicts)} times, each time alone, and wrote its remarks. You only compare them: you judge nothing, "
        "you add nothing. You use only what is given below: no search, no other source.\n\n"
        f"{text}\n\nReturn ONLY one JSON object, no prose, no code fence:\n"
        '{"remarks": [{"heading": "works" | "snags" | "unsourced" | "brand", "where": "...", "say": "...", "rounds": [1, 3]}]}\n'
        "- remarks: one entry per idea, that is the remarks of different rounds that say the same thing about the same place are ONE entry. "
        "A remark that only one round makes is an entry of its own.\n"
        "- rounds: the numbers of the rounds in which the idea came out.\n"
        "- heading, where, say: those of the round that says it best, with its words, shortened if needed (say: 400 characters at most).\n"
        "- Two rounds that say the opposite of each other (one praises what the other catches) are two entries, each with its own rounds.\n"
        "- Plain French, no em dash, no emoji.")


def cmd_rounds(i, model, runner):
    with ThreadPoolExecutor(ROUNDS) as pool:  # independent: no round sees another
        verdicts = [f.result() for f in [pool.submit(cmd_judge, i, model, runner) for _ in range(ROUNDS)]]
    with tempfile.TemporaryDirectory(prefix="ixs-rounds-") as work:
        res = ask(rounds_prompt(verdicts), "rounds", NOTHING, work, 300, model, runner)
    if res.code:
        raise AgentError("l'agent n'a pas répondu : " + tail(res))
    try:
        return {"rounds": verdicts, "synthesis": parse_rounds(res.out)}
    except ValueError as err:
        raise AgentError(f"synthèse des tours illisible : {err}") from None


# ---------- brief_export: the brief of a project, in Markdown ----------
BRIEF_SECTIONS = [("objective", "Objectif", "l'objectif"), ("audience", "Cible", "la cible"), ("message", "Message", "le message"),
                  ("format", "Format", "le format"), ("fixed", "Ce qui est fixé", "ce qui est fixé"), ("cta", "Appel à l'action", "l'appel à l'action")]


def brief_markdown(i) -> str:
    """The brief as a text to read. What is empty is written as missing, never filled in."""
    brief = i["brief"]
    if not isinstance(brief, dict):
        raise AgentError("inputs: brief is an object of fields")
    if not any(one_line(brief.get(k)) for k, _, _ in BRIEF_SECTIONS):
        raise AgentError("le brief est vide : il n'y a rien à exporter")
    name, brand = one_line(i.get("name")), one_line(i.get("brand_name"))
    lines = [f"# Brief : {name or 'sans nom'}", ""]
    lines += [f"Marque : {brand}", ""] if brand else []
    lines += ["Statut : " + ("brief validé" if i.get("confirmed") else "brief non validé, à relire"), ""]
    missing = []
    for key, title, label in BRIEF_SECTIONS:
        value = one_line(brief.get(key))
        lines += [f"## {title}", "", value or f"Manquant : {label}."]
        lines.append("")
        if not value:
            missing.append(label)
    personas = [one_line(x) for x in brief.get("personas") or [] if one_line(x)]
    if personas:
        lines += ["## Personas", ""] + [f"- {x}" for x in personas] + [""]
    lines += ["## Ce qui manque", ""] + ([f"- {x}" for x in missing] if missing else ["Rien ne manque."]) + [""]
    return "\n".join(lines)


def cmd_export_brief(i, model, runner):
    slug = re.sub(r"[^\w-]+", "-", one_line(i.get("name")).lower()).strip("-") or "projet"
    return {"filename": f"brief-{slug}.md", "markdown": brief_markdown(i)}


# ---------- engines ----------
def cmd_engines(i, model, runner):
    try:
        engines.save(i)
    except ValueError as err:
        raise AgentError(f"inputs: {err}") from None
    return engines.view()


COMMANDS = {"personas": cmd_personas, "names": cmd_names, "competitors": cmd_competitors, "research": cmd_research, "logos": cmd_logos, "texts": cmd_texts, "mandates": cmd_mandates, "variant": cmd_variant,
            "judge": cmd_judge, "reader": cmd_reader, "interview": cmd_interview, "storyboard": cmd_storyboard, "engines": cmd_engines, "rounds": cmd_rounds, "export-brief": cmd_export_brief}
PATHS = ("dir", "image", "dossier", "work")  # the inputs that name a file or a folder


def load_inputs(path) -> dict:
    f = Path(path)
    try:
        i = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise AgentError(f"inputs: {f} is not readable JSON ({err})") from None
    if not isinstance(i, dict):
        raise AgentError("inputs: a JSON object")
    for k in PATHS:
        if i.get(k):
            i[k] = str((f.parent / i[k]).resolve())
    return i


def main(argv=None, runner=run_command, stdout=None, stderr=None) -> int:
    ap = argparse.ArgumentParser(prog="agents", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=sorted(COMMANDS))
    ap.add_argument("inputs", nargs="?", help="the inputs of the command, a JSON file (optional for engines)")
    ap.add_argument("--model", help="the model (else STUDIO_MODEL_<COMMAND>, else the default of the command)")
    ap.add_argument("--out", help="also write the answer in this file")
    a = ap.parse_args(argv)
    CALLS.clear()
    try:
        if a.inputs is None and a.command != "engines":
            raise AgentError("inputs: a JSON file is needed")
        i = load_inputs(a.inputs) if a.inputs else {}
        try:
            answer = COMMANDS[a.command](i, a.model, runner)
        except KeyError as err:
            raise AgentError(f"inputs: {err.args[0]} is missing") from None
    except AgentError as err:
        out = stderr or sys.stderr
        out.write(raw_answer())
        print(f"agents: {err}", file=out)
        return 1
    text = json.dumps(answer, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        Path(a.out).write_text(answer["markdown"] if a.command == "export-brief" else text, encoding="utf-8")
    (stdout or sys.stdout).write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
