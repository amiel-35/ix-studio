---
name: studio
description: Entry point of the creative studio. Makes a still ad (a poster or a social post) for a brand in one session - minimal brand, brief of the piece, divergence, the piece, a check, the person decides - with one page per step to look at. Also routes to the brand dossier when a rich one is wanted. Use on "/studio", "make a poster / an ad / a post for <brand>", "creative studio", "fais-moi une affiche / une pub / un post pour <marque>", "studio créatif", or whenever creative work for a brand starts and it is not clear what to do first.
---

# Studio

One piece, one folder, five pages. The studio carries a still ad from a few lines about the brand to a poster the
person keeps or sends back. For an ad, the unit is the pair **headline + image**: the headline first, the image
answers it. The image model never writes text; the headline is set in HTML in the brand's type.

All the bookkeeping is done by `studio` (Python 3.10+, no dependencies). You write the files that need judgement
(the brand lines, the brief, the variants, the judge's notes); the tool checks them, generates, measures and renders.

```bash
ST="${CLAUDE_PLUGIN_ROOT}/scripts/studio"      # installed as a plugin
# from a clone: ST=<repo>/scripts/studio
python3 "$ST" status <piece dir>               # where we are, and the exact next command
```

Talk to the user in their language. Ask little: one global goal is enough to start; fill what you can, show it, let
the person correct on the page. Use `poster/` in the current project as the piece dir unless told otherwise. After
each step, give the path of the page to open and the one question it asks.

## The flow

1. **Brand, minimal.** `<dir>/brand.md`, about ten `key: value` lines: `name`, `background`, `text`, `accent`
   (hex), `extra colours` (a comma-separated list of hex: `extra colours: #E8C547, #7A8B6F`), `headline colour`
   (hex), `headline font`, `body font`, `logo` (a file path, or `placeholder` when the logo exists but was not given:
   the piece shows a dashed square), `logo position` (`bottom-right` default, `bottom-left`, `top-right`, `top-left`, `bottom-center`: the logo centred at
   the bottom, the slogan under it in spaced letters), `headline case` (`as written` default, or `upper`),
   `voice`, `slogan` (the brand's tagline or signature line, exact words: the piece sets it next to the logo),
   `never` (the exact words or characters that must not appear in the copy, `;`-separated, e.g.
   `never: detox; superfood; —`; prose there shows up as "not verifiable"), `never show` (what the image must not
   show, free prose, `;`-separated). Take them, in this
   order, from: a design-system skill that speaks for the brand (read it as it prescribes, copy only what it says);
   an existing brand dossier (`python3 "$ST" brand <dir> --from-dossier <brand dir> [--look <name>]`; when the dossier
   has several looks and no master, the tool stops and asks for `--look`); the user's words. Never
   invent a colour, a font or a logo: what nobody gave stays out, and you say so. Most brands have a slogan: when
   nobody gave it, look for it yourself (the brand's own site first, then the web) and write it with its source,
   marked to confirm, without asking: `slogan: <exact words> (to confirm: <url>)`. Approximate is fine, made up is
   not: if you find nothing, leave it out. Any value can carry that marker (`(to confirm)` or `(à confirmer)`): the
   piece uses it, and `check` and its page warn that the piece relies on it.
   From a dossier, only confirmed values are imported; `--include-unconfirmed` also takes the rest, marked to
   confirm. The dossier's reference visuals and web images whose ownership the person has not confirmed never feed
   an image prompt, in any mode. Then `python3 "$ST" brand <dir>`.
   The rich dossier (skill `brand-dossier`) stays available but is not required.
2. **Brief of the piece.** `<dir>/brief.md`: `objective` (awareness, purchase, engagement...), `audience`,
   `message`, `format` (`post-4x5`, `post-1x1`, `story`, `poster-a3`, `poster-3x2`, `linkedin`, or a free size `WxH` like `1600x900`; several, comma-separated, make one piece per format at the pick; a film or a TV spot is
   left out with a message, the studio makes stills), optional `fixed`, `cta`, `language`. Clean
   the message of drawn-in solutions ("a photo of the bottle on a beach" is a solution, not a message). Optional
   `layout`: when set (`full` for a campaign poster), every variant and the piece take it; the idea diverges, the
   layout does not. Never hand the person a brief they have not read: `python3 "$ST" form <dir>` writes
   `0-brief-form.html`, the brief as a form, prefilled from `brief.md` when there is one, or from another piece with
   `--from <piece dir>` (a declination of a campaign: it also takes that piece's brand and references, and the person
   only changes what changes); the page builds the command that writes `brief.md`. Then `python3 "$ST" brief <dir>`.
   `references.md` (`- <file or url> | <what it shows>` per line) lists the visuals the person kept for the brand;
   `brand --from-dossier` writes it from the dossier's kept visuals, and the brief page shows them.
3. **Divergence.** The method is the one of [design-divergent](https://github.com/amiel-35/ix-design-divergent):
   if that plugin is installed, follow it for the mandates and the attractor; it is the reference. Here, scaled to
   an ad: propose 3 stances that each look somewhere else, plus one rupture; then run **one subagent per mandate,
   in parallel, blind** (each sees the brand, the brief, `bans.md` if any, `references.md` if any, opening the local
   images, and its own mandate only; the references give the grammar to keep, light included, never a picture to
   copy). Each writes
   `variants/<id>.json`: `mandate`, `default` (an object `{"headline": "...", "image": "..."}`: what it would have made by default, written
   down, then set aside), `headline`, `subline`, `image_prompt` (what the image shows, no text in it), `layout`
   (`side|stack|ground|overlay-top|overlay-bottom|full`), `ground` (`background|text|accent`), `why`, optionally `fit` (`contain`, the default: the whole image shows; `cover`: it may be cropped). The brand does not
   diverge: the idea does. **Pick a layout that does not cover the subject of the image.** `side` (image and a flat
   brand panel next to each other; stacks in a portrait or square piece), `stack` (image above, panel below) and
   `ground` (flat brand colour, the image a framed inset) never overlap the image; use `overlay-top` or
   `overlay-bottom` only when the image prompt leaves that edge calm. `full` is the campaign poster: the photo fills
   the frame, the headline sits centred in its upper part (one sentence per line), the subline and the CTA centred
   above the logo; use it when the brief's `fixed` asks for the campaign's look, and then every mandate keeps it.
   Otherwise each mandate chooses its own layout: the stances should not all share one (`diverge` warns when they do). Before returning, each subagent rereads its own
   headline and subline in the piece's language as a reader would, looking for any second reading (sexual, vulgar,
   ridiculous, hurtful), slang included; if it finds one, it rewrites the line. No word list: a human eye.
   Then `python3 "$ST" diverge <dir>` and let the person pick: `python3 "$ST" pick <dir> <id> [--headline "..."] [--subline "..."]`.
   A campaign is a series: `python3 "$ST" pick <dir> v1 v3 v4` makes one piece per kept variant under
   `<dir>/pieces/<id>/` (same brand, brief and references), each carried on with its own `image`, `compose`, `check`.
4. **The piece.** `python3 "$ST" image <dir>` then `python3 "$ST" compose <dir>`. The image comes from an
   executor behind an adapter: the user's key (`OPENAI_API_KEY`), or locally their own plan through the Codex CLI.
   With neither, the piece is composed on a flat brand ground and the page says so: say it too, with how to plug a
   generator, and carry on. A user's own `image.png` dropped in the folder is kept.
5. **Check.** Look at `piece.png` (or `piece.html`) as a judge with a fresh eye, ideally a subagent that did not
   write the variants: does the headline read in three seconds, does the image answer it, does it feel like the
   brand, anything off (cropping, contrast, a cliché), and flag as `[major]` any claim that is in neither the brand nor the
   brief (a figure, a place, a label or award, a promise). Then reread the headline and the subline in the piece's
   language, slowly, as a reader with a dirty mind or a mocking one would: any double meaning (sexual, vulgar,
   ridiculous, hurtful), slang included, is a `[major]` note that quotes the problem reading
   (`- [major] double meaning: "<line>" reads as "<the other reading>"`). No word list: a human eye; a human
   copywriter would have pulled the line. Check that the slogan is there when the brand has one. Write `<dir>/judge.md`, one `- ` line per note, prefixed
   `[minor]` or `[major]`. Notes annotate, they never block; the summary counts the majors. Then `python3 "$ST" check <dir>`: the mechanical
   checks (palette, type, contrast, banned words) plus your notes, on one page.
6. **The person decides.** `python3 "$ST" decide <dir> keep "<their words>"` or
   `python3 "$ST" decide <dir> again "<their words>"`. "Again" writes a ban that the next round of variants reads.

Each step works alone if its input file is written by hand. A user who already has a headline (and maybe an image,
dropped in as `<dir>/image.png`) skips the divergence: `python3 "$ST" compose <dir> --headline "..."`, then `check`.
After `decide again`, the pick and the piece are cleared: write new variants (they read `bans.md`) and run
`diverge` again; `status` says so.

## The agents, as commands

The studio's agents are commands, the same ones the interface runs (`AG="${CLAUDE_PLUGIN_ROOT}/scripts/agents"`, from a clone
`<repo>/scripts/agents`). Each takes an `inputs.json` (its keys are listed by `python3 "$AG" --help`; paths in it are read from its folder) and gives
JSON, or stops with its reason and a non-zero code. Write the inputs from what you know, show what comes back, let the person correct it.

- `python3 "$AG" mandates in.json` (`dir`: the piece folder): the common rule and four mandates, when the person wants them proposed rather than written by you.
- `python3 "$AG" variant in.json` (`dir`, `id`, `mandate`, `common`): one blind variant, written in `<dir>/variants/<id>.json`; one call per mandate, in parallel.
- `python3 "$AG" judge in.json` (`image`, `brief`, `brand`, `texts`): the judge's verdict on a piece, without a score; after `compose` and `check`, or on a piece dropped by the person.
- `python3 "$AG" reader in.json` (`image`, `persona`, `texts`): what one persona understands of a piece; one call per persona of the brief.
- `python3 "$AG" engines [in.json]` (`image_engine`, `text_engine`, `openrouter_model`, `openrouter_key`, all optional): keeps the engines the person chooses and gives `{image_engine, text_engine, openrouter_model, key_saved}`; the key is kept on this machine, never given back, never written in the project. `text_engine` `openrouter` makes the agents that only answer (personas, names, competitors, mandates) use OpenRouter; `STUDIO_TEXT_ENGINE` and `STUDIO_IMAGE_ENGINE` say the same in the environment.

The judge and the readers run on `claude-fable-5-1`, the others on `sonnet`; `--model` or `STUDIO_MODEL_<COMMAND>` (`STUDIO_MODEL_JUDGE`) changes it.
The brand's agents (personas, names, competitors) are in the `brand-dossier` skill.

## Which tool for which job

Claude writes the brief, the mandates, the headlines and the judge's notes. It does not make images: for the image,
use a dedicated image model (`gpt-image-1` by default through the adapters; set `STUDIO_IMAGE_MODEL` to change it).
For anything with text inside the image, do not ask the image model: the text is HTML.

## Rules

- The brand's values are imposed: the idea diverges, never the palette or the type.
- Nothing is invented: no figure, no testimonial, no claim, no logo redrawn from memory.
- Matter the person was asked to confirm and did not (a colour, a visual, an image's ownership) is not the brand:
  leave it out, or mark it to confirm and say the piece relies on it.
- A reference serves its grammar, never a model to copy.
- Nothing is published or sent outside without the user's explicit yes.
