# Local settings (example)

Copy this file to `local.md` at the root of the repository (or to `~/.claude/studio.local.md` for a plugin
install). `local.md` is ignored by git: put there what only applies to you. The skills read it first.

## Language

- Language to talk in, and of the review (`--lang en|fr` at `brandkit init`).

## Skills that speak for your brands

- Brand name: skill name, and where its source of truth lives (the skill's own `SKILL.md` says how to read it).

## Private names

<!-- One per line. scripts/check_public.py fails if any of them appears in a published file. -->

## Run log

- Where to keep a private log of your runs and trials.
