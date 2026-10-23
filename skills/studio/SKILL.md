---
name: studio
description: Entry point of the creative studio. Takes a brand (even one you know nothing about) and a request for a creative piece (a film or motion graphic, a still visual, a screen or mock-up, a visual identity direction), and routes it through the studio's modules in order, starting with the brand dossier. Use on "/studio", "creative studio", "make a film / a visual / a screen / a logo direction for <brand>", "studio créatif", "fais-moi un visuel pour <marque>", or whenever creative work for a brand starts and it is not clear what to do first.
---

# Studio

The studio turns a brand and a request into creative pieces that really diverge before anyone chooses, respect the
brand, and are executed by the right tool without that tool's own look taking over. It is built in parts; this skill
knows which ones exist and sends the work to them in order.

| Module | What it does | Status |
|---|---|---|
| Brand dossier | what is known about the brand, where each value came from, what is missing | **available**: skill `brand-dossier` |
| Brief | cleans the request of solutions drawn into it; holds the project's content and format | planned |
| Divergence | mandates that each look somewhere else, blind variants, the user picks | available as a separate plugin: [design-divergent](https://github.com/amiel-35/ix-design-divergent) |
| Treatment and execution | per family (film, still, screen, identity), with third-party executors behind adapters | planned |
| Checks and memory | the brand's design system used as a filter on the output; refusals remembered as bans | planned |

The architecture and the contracts between modules: `docs/en/architecture.md` in the repository.

## Routing

1. **Is there a brand dossier?** Look for `brand/brand.json` in the project. None: run the `brand-dossier` skill
   first, whatever the request. Nothing creative starts on a brand without one.
2. **Is the dossier usable for this request?** Read the fields the request needs with
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brandkit" get brand <path>`. A field that comes back missing is asked or the
   work stops; it is never filled in. A "to confirm" value may feed an exploration, and a final piece that uses one
   says so.
3. **Divergence.** If `design-divergent` is installed, hand it the request with the dossier's confirmed values as hard
   constraints (palette, type and logo do not diverge; the idea does). If it is not, say that the divergence module
   is a separate plugin and how to install it; do not imitate it.
4. **The rest** (treatment, execution, checks) is not built yet: say so plainly, and offer what exists.

## Rules

- The brand's design system, when there is one, is imposed: the idea diverges, never the palette or the type.
- Nothing is invented: no figure, no testimonial, no logo redrawn from memory.
- A reference serves its grammar, never a model to copy.
- Nothing is published or sent outside without the user's explicit yes.
