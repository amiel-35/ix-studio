# Third-party work

## Code

**React** 18.3.1, MIT License, Copyright (c) Facebook, Inc. and its affiliates, https://github.com/facebook/react

- `app/static/ds-public/components/lib/react.production.min.js` and `react-dom.production.min.js` are the UMD builds of
  `react@18.3.1` and `react-dom@18.3.1`, unchanged, with their licence header.

**huashu-motion**, MIT License, Copyright (c) 2026 Huashu, https://github.com/alchaincyf/huashu-motion

- `scripts/collect/vendor/cdp.js` and `scripts/collect/vendor/browser.js` are copied unchanged from
  `cli/lib/cdp.js` and `cli/lib/browser.js` (commit 52467f9), with a header naming their origin.
- `scripts/collect/collect.mjs` is adapted from `cli/lib/grab.js` (`om grab`): the page walk, the screenshots, the
  logo candidates, the colours weighted by area and characters, the downloads. Changes: CSS variables count only
  when painted on a visible element, typefaces are read per role and checked against the fonts really rendered,
  texts are kept for the tone, downloads fall back to the page's own fetch.

```
MIT License

Copyright (c) 2026 Huashu

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Formats and ideas

**brand-intake**, from motion-graphics-skills by Charlie, MIT License,
https://github.com/charlie947/motion-graphics-skills

- `brand.md` and `MOTION.md` are exported with brand-intake's sections, and a missing value is written "ASK ME", so
  that the skills of that pack read the dossier as is.
- The interview reuses brand-intake's two batches of questions.
- Three of its findings shaped the rules: a hex sampled from a JPEG drifts (CSS and typed values rank above samples),
  mixed reference frames give mixed looks (several looks are named, never averaged), and "ASK ME" is a feature.
- Unlike brand-intake, the studio never writes a rule into the project's `CLAUDE.md` without asking.

**huashu-motion** also gave the idea of collecting the product's real material (logo as a file, real colours and
type) before any direction is drawn.
