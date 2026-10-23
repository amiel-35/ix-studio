<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-8f8a7c"></a>
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude%20Code-plugin-D97757">
  <img alt="Part" src="https://img.shields.io/badge/part%201-brand%20dossier-3d9a8b">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-e07a3f">
</p>

<p align="center">
  <a href="#quick-start"><b>Quick start</b></a> ·
  <a href="#what-it-looks-like"><b>What it looks like</b></a> ·
  <a href="#documentation"><b>Documentation</b></a> ·
  <a href="README.fr.md"><b>Français</b></a>
</p>

---

# studio

Ask a model for "a visual for this brand" and it will give the brand a palette, a typeface and a tone. Its own.

**studio** is a Claude Code plugin for creative work on any brand, even one you know nothing about. It starts where
every creative brief should: by writing down what is actually known about the brand, where each piece of it came
from, and what nobody has said yet. This first release is that part, the **brand dossier**. The rest of the studio
(brief, divergence, execution, checks) reads it.

## What it does

- **Gathers** what a design-system skill says, what the brand's own site, files and videos show, what turns up in a
  web image search, and what you type.
- **Keeps the provenance of every value**: typed, skill, inferred, created; the page and date, the file, the skill's
  version; for anything inferred, its evidence and a confidence.
- **Never guesses.** A missing value is "ASK", in the dossier and in the exports. No default palette, no "temporary"
  font, no tagline written for the brand.
- **Merges with a fixed priority** (skill, then typed, then inferred) and **keeps the conflicts** where you can see
  them.
- **Names several looks instead of averaging them** (the current identity, an older one, a campaign) and asks which
  one is the master.
- **Shows one review**, as a page you look at: each look with its swatches, typefaces, logos and screenshots, and
  the images found on the web as links, with the ownership it proposes for you to confirm or correct.
- **Exports** `brand.md` and `MOTION.md` in the format of
  [brand-intake](https://github.com/charlie947/motion-graphics-skills), so the skills that read it work as is.

## What it looks like

A fictional brand, Marrowbay Ferments, built from a design-system skill, its site, a web image search and a short
interview ([the whole example](examples/marrowbay)). An extract of the review:

```
## Colours
- **Conflict** `colours` (look brand): kept hex: #C8553D, role: accent, name: Brick [skill: marrowbay-ds@1.2.0] over hex: #E07A2F, role: accent, share: 0.04 [inferred: https://marrowbay.example (2026-10-23)]
- Inferred, to confirm `colours[old-identity:background]`: hex #2F5D3A · role background (confidence low; proof ev-d5fff827)

## Looks
**Several looks were found. Which one is the master look? Nothing is averaged meanwhile.**
- `summer-2026`: Summer 2026 campaign (campaign), proof ev-16125880
- `old-identity`: Identity before 2021 (old_identity), proof ev-d5fff827
- `brand`: Brand identity (brand)

## Visuals and pages: are they the brand's?
- `ev-9aee9706` web_image https://pins.example/kombucha-moodboard-44: **uncertain** · moodboard with a Marrowbay bottle among others
- `ev-b0cba8e4` web_image https://social.example/marrowbayferments/p/123: **official** · post on the brand's own account: bottles on a market stall
```

The founder answered that the social post was a reseller's, not theirs: what rested only on it left the dossier. And
what a downstream module gets when it asks for a field nobody filled:

```bash
$ python3 scripts/brandkit get examples/marrowbay/brand audience.situation
{"path": "audience.situation", "status": "ask", "missing": true,
 "say": "no value: ask the user or stop. Never fill it in."}
```

## Quick start

```bash
claude plugin marketplace add amiel-35/ix-studio
claude plugin install studio@ix-studio
```

Or as a plain clone, if you want to read and edit it in place: clone the repository anywhere and point Claude Code
at it with `claude --plugin-dir <clone>`.

Then, in Claude Code: "set up the brand dossier for <brand>", with whatever you have (a site, a folder, the name of
a design-system skill). Or call `/studio` and it will route you.

Requirements: Python 3.10+; for the site inference, Node 22+ and an installed Chrome (or Chromium, Edge, Brave); for
videos and image colours, ffmpeg.

From a clone, without installing: `python3 scripts/brandkit --help`, and `sh examples/marrowbay/build.sh` to rebuild
the example.

## Documentation

- [The brand dossier](docs/en/brand-dossier.md): goal, rules, adapters, data model, edge cases, acceptance criteria.
- [Architecture](docs/en/architecture.md): the studio's modules and the contracts between them.
- [The skill](skills/brand-dossier/SKILL.md) and its references: source format, each adapter, the web image search.
- [Third-party work](THIRD_PARTY.md): what comes from huashu-motion and brand-intake, under their licences.

## Status

Experimental. Part 1 of five. Divergence is the separate plugin
[design-divergent](https://github.com/amiel-35/ix-design-divergent); treatment, execution, checks and memory are
planned.

## Licence

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).
