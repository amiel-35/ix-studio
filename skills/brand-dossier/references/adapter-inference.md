# Adapter: inference from the brand's own material

Covers everything: colours with their role, type, logo, imagery, voice, motion, bans. Everything it produces is
`inferred`, "to confirm", with its evidence and a confidence. What is read badly (a voice from three texts, a ban
deduced from an absence) comes out with a **low** confidence, never at the level of a colour read on the page.

## 1. Collect the site (mechanical)

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/collect/collect.mjs" https://brand.example brand/collect/web-brand [--shots 6] [--videos]
python3 "$BK" infer-site brand brand/collect/web-brand [--look <id> --look-name "..." --look-kind brand|campaign|old_identity|sub_brand]
```

`collect.mjs` drives the Chrome already installed (headless, nothing downloaded, no cookie banner clicked) and writes
screenshots, logo candidates, the largest images and `facts.json`: colours really painted, weighted by area (grounds)
and characters (text, headings), accents from buttons and links, CSS colour variables with whether they are painted
on anything visible, typefaces per role checked against what the browser really rendered, headings and paragraphs.
`infer-site` turns those facts into a source: declared-and-used colours outrank merely rendered ones, declared but
unused variables and fonts are listed as ignored, header SVG logos outrank icons, a favicon is kept as a favicon.

Give each site its look: a campaign site, a sub-brand or an archive is collected with its own `--look`, so nothing is
averaged with the main identity. If a site is blocked or empty (all JavaScript, a wall), say so in the review; do not
compensate.

Folders and files the user gives (a brand book PDF, a logo folder, exported visuals) go in as `file` evidence.

## 2. Look, then write what the model must judge

Open the screenshots, the collected images and the texts in `facts.json`, and write a second inferred source for:

- `imagery.style`, `imagery.do`, `imagery.dont`: what the images show and how (light, framing, subjects, finish);
- `voice.register`, `voice.address`, `voice.traits`: from the texts, quoting a few of them in `voice.samples`
  (exact words). Fewer than ten paragraphs read: confidence low;
- `motion.*`: only from real footage (step 3), never from stills;
- `motion.never`, `imagery.dont`: what never appears, always low confidence;
- `identity.one_liner`, `promise.*`: only words the brand itself wrote, quoted, with the page as evidence; a claim
  you would have to rephrase stays out.

Each value cites the screenshot or page it comes from.

## 3. Videos: measure, then look

```bash
python3 "$BK" frames <video file or address> brand/collect/frames-<name> [--scene 0.3]
```

Extracts one frame per cut and writes `cuts.json`: duration, frame rate, cut times, mean shot length. A video found
on the web is read from a temporary folder and deleted; keep only `cuts.json` and frames needed as evidence for a
video that is the brand's own (`ownership` official). Then look at the frames for entrances, holds, exits, easing,
texture. Tempo and frame rate are `rank: "measured"`.

## 4. Search the web for the brand's visuals

See `image-search.md`. Every image consulted becomes a `web_image` evidence with its address, date and ownership; no
file is kept. Colours read from them rank last (`web_image`), and only official, relayed or probable images feed.

## 5. Say what was not found

Fill `not_found` honestly: no video, no logo file, no font licence, a page that would not load. The review shows it.
