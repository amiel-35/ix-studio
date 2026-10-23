# Source file format

One JSON file per adapter run. `python3 "$BK" add brand <file>` checks it, gives its evidence stable ids, stores it
under `brand/sources/` and merges. A rejected file changes nothing.

```json
{
  "adapter": "skill | typed | inferred | created",
  "origin": "who or what said it: a page and its date, a file, an interview",
  "skill": {"name": "acme-ds", "version": "2.3.0", "read": "what was read, in the order the skill prescribes"},
  "label": "short name for the file",
  "at": "2026-10-23",
  "evidence": [
    {"id": "home", "kind": "page", "where": "https://acme.example/", "ownership": "official", "ownership_given_by_user": true},
    {"id": "poster", "kind": "web_image", "where": "https://news.example/acme.jpg", "page": "https://news.example/acme",
     "ownership": "official_relayed", "look": "spring-campaign", "note": "article names the brand and its agency"}
  ],
  "values": [
    {"path": "voice.register", "value": "Plain, warm", "confidence": "low", "rank": "text", "evidence": ["home"]},
    {"path": "colours", "look": "brand", "item": {"hex": "#1F3A5F", "role": "text", "share": 0.31},
     "confidence": "high", "rank": "declared_used", "evidence": ["home"]}
  ],
  "not_found": ["no video on the site"],
  "ignored": [{"what": "14 CSS variables of a UI kit", "why": "declared, painted on nothing visible"}]
}
```

- `skill` is required for a skill source (name and the exact version read); `origin` is then `name@version`.
- An **inferred** value needs `confidence` (high, medium, low) and `evidence` (ids declared in the same file). Its
  `rank` says how it was read: `declared_used`, `rendered`, `text`, `measured`, `image_sample`, `web_image`.
- `ownership` is required for a page, a video or a web image: `official` (the brand's domain or account),
  `official_relayed` (a press article that names the brand and its agency), `probable`, `uncertain`. Only the first
  three feed the inference. Set `ownership_given_by_user` when the user gave the address themself.
- A `web_image` never has a `file`: it is not kept.
- `hint: true` on a value shows it as "the closest thing found" next to an ASK line, without filling it.
- Leave a field out rather than sending it empty.

## Fields

Scalars (`value` is a string, or a list of strings where marked):

| Path | | Path | |
|---|---|---|---|
| `identity.name` | | `voice.traits` | list |
| `identity.one_liner` | | `voice.banned_words` | list |
| `identity.offer` | | `voice.samples` | list, exact words |
| `identity.links` | list | `imagery.style` | |
| `audience.who` | | `imagery.do`, `imagery.dont` | lists |
| `audience.situation` | | `motion.entrances`, `holds`, `exits`, `easing`, `tempo` | |
| `promise.tagline` | exact words | `motion.never` | list |
| `promise.signature_line` | exact words | `motion.frame_rate`, `texture`, `example` | |
| `promise.key_messages` | list, exact words | `meta.language` | |
| `voice.register`, `voice.address` | | | |

List rubrics (`item` is an object; `look` defaults to `brand`):

| Rubric | Item fields (required first) | Merge |
|---|---|---|
| `colours` | `hex`, `role`; `share`, `name` | the best source tier wins the whole look |
| `typography` | `family`, `role`, `files`, `licence`; `sizes`, `weights` | same |
| `logo` | `file`, `format`; `variant`, `background` | same; no vector format means "vector logo: ASK" |
| `references` | `url`, `grammar` (what is taken from it, never a model to copy) | union |
| `looks` | `id`, `name`, `kind` (brand, old_identity, campaign, sub_brand); `summary` | union |
| `bans` | `rule`, `origin` (refusal of a date, verbatim) | reserved for the memory module |
