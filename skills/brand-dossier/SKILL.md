---
name: brand-dossier
description: Builds the brand dossier every other part of the creative studio reads, for any brand, even one you know nothing about. Gathers what a design-system skill says, what the brand's own site, files, videos and images found on the web show, and what the user types; keeps where every value came from; never guesses (a missing value is "ASK"); merges with a fixed priority (skill, then typed, then inferred) and keeps the conflicts; shows one grouped review; validates numbered versions; exports brand.md and MOTION.md for the skills that read the brand-intake format. Use on "set up a brand", "build the brand dossier", "brand file for X", "what do we know about this brand", "infer the brand from its site", "constitue le dossier de marque", "fais le dossier de marque", or before any creative work for a brand that has no dossier yet.
---

# Brand dossier

The dossier is a folder, `brand/` in the project of the brand, whose only source is `brand.json`. Every value in it
says where it came from (typed, skill, inferred, created), and whether it is sure. What nobody provided is written as
missing, never guessed. `brand.md` and `MOTION.md` are generated from it, never edited by hand.

Talk to the user in their language. Keep the files' keys in English and the brand's values in the brand's language.

## The tool

All the bookkeeping is done by `brandkit` (Python 3.10+, no dependencies):

```bash
BK="${CLAUDE_PLUGIN_ROOT}/scripts/brandkit"      # installed as a plugin
# from a clone: BK=<repo>/scripts/brandkit
python3 "$BK" --help
```

You write **source files** (JSON, one per adapter run, format in `references/source-format.md`) and record the user's
**decisions**; brandkit merges them, checks them and writes the dossier. Never edit `brand.json`, `evidence.json` or
the exports yourself.

## Steps

1. **Launch.** Ask for the brand's name and what the user has at hand: a site address, folders, files, videos, the
   name of a skill that speaks for the brand, a text. Only the name is required. Then
   `python3 "$BK" init brand --name "<name>" --lang <en|fr>` (the review's language).
2. **A skill that speaks for the brand, first** (it saves useless inferences). Follow
   `references/adapter-skill.md`. Its values are confirmed; it wins every conflict.
3. **Inference, second.** Follow `references/adapter-inference.md`: collect the site, turn the facts into a source,
   then read screenshots, texts and video frames yourself for tone, imagery and motion, and search the web for the
   brand's visuals (`references/image-search.md`). Every inferred value carries its evidence and a confidence, and
   stays "to confirm".
4. **Free text, last, to fill the gaps.** `python3 "$BK" missing brand` lists the only questions still worth asking.
   Ask them in two or three batches, as in `references/adapter-free-text.md`. Record the answers as a typed source.
5. **Review.** `python3 "$BK" merge brand` writes `brand/review.md` and `brand/review.html`. **Show the visual one**:
   `python3 "$BK" review-html brand --embed` builds a standalone page (the brand's own screenshots and logos
   embedded, web images as links only) that you send or open for the user; a text review alone shows nothing. The
   same page is the **keep / discard sheet** (step 6): one card per visual, with a preview hotlinked from the page's
   og:image for web images (never downloaded; `--no-previews` to stay offline). Then
   sum up in **one** message:
   conflicts, what is inferred and waits for confirmation, the ASK lines, what is to create, the visuals whose
   ownership needs confirming, and the master look when there are several. For an ASK line you may show the closest
   thing found, marked as such; never fill it in.
6. **Apply the answers**, one command each:
   - `answer brand <path> "<value>"` (a list or an item: add `--json`), the user's words, verbatim for the promise;
   - `confirm brand <path> [--look L] [--key K]` for an inferred value or a look's items;
   - `reject brand <path> [--look L --key K] --reason "<the user's words>"`;
   - `master brand <look-id>`;
   - `ownership brand <evidence-id> <official|official_relayed|probable|uncertain> --reason "..."`: when the user says
     a visual is not the brand's, what rested only on it leaves the dossier;
   - `to-create brand <path>` when the user wants an asset made by the identity family;
   - `keep brand <kept ids…> [--logo <id>]`: the outcome of the keep / discard sheet in one go (the page builds the
     command live, the user copies it to you). The listed visuals become `official`, **every other visual becomes
     `uncertain`** (screenshots included, so a discarded site stops feeding colours, type and looks), the logo
     file is recorded as the confirmed logo of the master look, and the dominant colours of the kept visuals are
     measured (ffmpeg) and added as "measured on the kept visuals", to confirm. `--none` discards everything.
     Run it again after a new choice: the measured colours are rewritten, not stacked.
   Show the new review, repeat until the user validates.
7. **Validate** only when the user says so: `python3 "$BK" validate brand --by "<who>"`. A dossier can be validated
   with ASK lines left: they stay missing for every module downstream. Validation writes `history/vN/` and the
   exports.

## Personas, names, competitors

Three agents, run by the same commands as in the interface: `AG="${CLAUDE_PLUGIN_ROOT}/scripts/agents"` (from a clone `<repo>/scripts/agents`), then
`python3 "$AG" <command> inputs.json`. The inputs are `name`, `site`, `description`, `words` (what the person says of the brand), `brief` (a list of
`{key, value, state}` with the keys `what`, `who`, `voice`, `signature`, `never`, `colours` and the state `confirmed` or `deduced`, taken from the
dossier) and `dossier` (the path of `brand.json`). They give hypotheses to show and correct, never facts to file.

- `personas`: up to four people the brand's ads will meet, each with a main need; use it once the brief of the brand is done.
- `names`: up to eight names with their why; when the brand has only a working title. Nobody checked that a name is free.
- `competitors`: up to six, each marked `dossier` or `supposé`; no figure.

- `competitors` with `market` (one or two sentences) as the only input, no brand: the landscape of that market, up to six players with their position; one not in the description is `supposé`; show it to the person, who keeps or drops each.

They run on `sonnet`; `--model` or `STUDIO_MODEL_PERSONAS` (`_NAMES`, `_COMPETITORS`) changes it.

## Reading the dossier from another module

`python3 "$BK" get brand <path>` returns a value with its status and source, or only a status when the field is ASK
or to create (exit code 3). A missing value is asked or the work stops; it is never filled in. A "to confirm" value
may feed an exploration (a divergence variant), never a final deliverable without saying so.

## Rules that do not bend

- **Nothing is guessed.** No default palette, no "temporary" font, no tagline written for the brand.
- **Inferred is not confirmed** until the user says so.
- **Priority:** skill, then typed, then inferred. Inside inferred: declared in a source file *and* painted on visible
  elements, then read on the rendered page, then sampled from an image, then taken from an image found on the web.
  A value declared but not visible does not count (templates and UI kits declare colours that are not the brand's).
- **A disagreement with the skill is not settled in the dossier.** The skill wins; to change the value, change the
  design system.
- **The logo is a file.** Never redrawn. A favicon or a blurry PNG is kept with its nature, and the vector logo is ASK.
  When learning a brand, always take the logo file: it is chosen in its own section of the sheet, apart from the site
  screenshots, and it is never discarded because its site was.
- **Several looks are named, never averaged.** The user picks the master look.
- **Images found on the web are never kept**: their address, date and ownership are, nothing else.
- **The promise is quoted, never rephrased.**
- **Never write to the project's CLAUDE.md** (or any rules file) without the user's explicit yes.
- **Never read a skill's files behind its back**: follow the reading method the skill prescribes.

## What this skill does not do

It does not create a missing asset (it lists it as "to create" for the identity family), it does not make the brand
signature (a reserved field), and it does not hold a project's brief, content or format: those change with every
project and live with the brief.
