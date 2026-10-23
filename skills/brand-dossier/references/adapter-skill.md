# Adapter: a skill that speaks for the brand

Some brands already have a design-system skill (tokens, fonts, logos, rules). Its values are sure: they enter as
`skill`, confirmed, and win every conflict.

## Read it the way it says

1. Open the skill's `SKILL.md` and read it in full before anything else.
2. **Follow its reading method.** If it says its source of truth lives elsewhere (a hosted page, an artifact, a
   tokens file, a package), read there, in the order it gives. If it says a local copy is a mirror that no longer
   holds, do not read the mirror instead. Never walk the skill's folders looking for values it does not point to.
3. If the source of truth cannot be reached, say so, and record it:
   `python3 "$BK" skill-check brand <skill> --unavailable`. Values taken from a fallback the skill allows go in as
   `skill` but come back "to confirm".
4. Note the **exact version you read**: a version field, the top entry of a changelog, a commit, a published
   version id. Write it in `skill.version`. If it changes later, `skill-check brand <skill> <new version>` gives the
   skill's values back to "to confirm" until they are read again (R12).

## Map, do not interpret

- **Colours:** every brand colour the system declares, `hex` as written (normalise the case only), `role` from the
  system's own naming (background, text, accent, the system's name in `name`). If the system writes colours in
  another notation (oklch, rgb), convert to hex and say so in `note`. Skip pure UI states (hover, disabled) unless the
  system treats them as brand colours.
- **Typography:** `family` as named, `role` (headings, body, mono…), `files` (paths as the system gives them),
  `licence` from the licence file next to the fonts; no licence file means the field is left out, so it becomes ASK.
  Sizes and weights if the system declares them.
- **Logo:** the files the system points to, with their format and variant. Never export or redraw one.
- **Voice, imagery, motion:** only what the system writes as a rule. Quote its words for anything that is a
  promise or a sample.
- Anything the system does not cover stays out: the other adapters or the interview will deal with it.

Write one source file, `adapter: "skill"`, with an `evidence` entry of kind `skill` for each file or page read
(`where` = the path or address), then `python3 "$BK" add brand <file>`.
