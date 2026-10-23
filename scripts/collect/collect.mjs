#!/usr/bin/env node
// collect — what a brand's own site really shows, before anything is inferred from it.
//
//   node collect.mjs <url> <out-dir> [--shots 6] [--images 24] [--videos]
//
// Writes <out-dir>/facts.json plus screenshots, logo candidates and the largest images. Adapted from `om grab` in
// huashu-motion (MIT, Copyright (c) 2026 Huashu, https://github.com/alchaincyf/huashu-motion, cli/lib/grab.js),
// with three changes the brand dossier needs:
//   1. a CSS custom property counts only if its colour is really painted on a visible element (declared but unused
//      values belong to a template or a UI kit, not to the brand);
//   2. typefaces are read per role (headings, body, interface) and checked against the fonts the browser really
//      rendered (CSS.getPlatformFontsForNode), not only the declared stack;
//   3. headings, paragraphs and buttons are kept as text, for the tone.
// Nothing is ever accepted on the page: a cookie banner is refused when it offers a refusal, left alone otherwise.
// Chrome is the one already installed.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, statSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { findChrome, NO_CHROME } from './vendor/browser.js';
import { launch, newPage } from './vendor/cdp.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function args(argv) {
  const o = { shots: 6, images: 24, videos: false, _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--shots') o.shots = Number(argv[++i]);
    else if (a === '--images') o.images = Number(argv[++i]);
    else if (a === '--videos') o.videos = true;
    else o._.push(a);
  }
  return o;
}

function curl(url, file, referer) {
  const r = spawnSync('curl', ['-sSL', '--max-time', '40', '--max-filesize', String(60 << 20), '-A', 'Mozilla/5.0 (ix-studio collect)', ...(referer ? ['-e', referer] : []), '-o', file, url], { encoding: 'utf8' });
  return r.status === 0 && existsSync(file) && statSync(file).size > 200;
}

const PAGE_FACTS = `(() => {
  const vis = (el) => { const r = el.getBoundingClientRect(), s = getComputedStyle(el); return r.width > 1 && r.height > 1 && s.visibility !== 'hidden' && s.display !== 'none' && Number(s.opacity) > 0.05; };
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return null; } };
  const ownText = (el) => [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ').trim();
  const images = [];
  for (const im of document.images) if (im.naturalWidth >= 240 && im.naturalHeight >= 120) images.push({ src: abs(im.currentSrc || im.src), w: im.naturalWidth, h: im.naturalHeight, alt: (im.alt || '').slice(0, 120) });
  for (const el of document.querySelectorAll('*')) { const b = getComputedStyle(el).backgroundImage; const m = b && /url\\(["']?([^"')]+)["']?\\)/.exec(b); if (m && el.getBoundingClientRect().width >= 240) images.push({ src: abs(m[1]), w: Math.round(el.getBoundingClientRect().width), h: Math.round(el.getBoundingClientRect().height), alt: 'background' }); }
  const videos = [...document.querySelectorAll('video')].map((v) => ({ src: abs(v.currentSrc || v.src || (v.querySelector('source') || {}).src), poster: abs(v.poster) })).filter((v) => v.src || v.poster);
  const embeds = [...document.querySelectorAll('iframe')].map((f) => abs(f.src)).filter((s) => s && /youtube|vimeo|dailymotion|wistia/i.test(s));
  const logos = [];
  for (const l of document.querySelectorAll('link[rel~="icon"],link[rel="apple-touch-icon"],link[rel="mask-icon"]')) logos.push({ src: abs(l.href), where: 'link', note: l.rel + (l.sizes && l.sizes.value ? ' ' + l.sizes.value : '') });
  const share = [];
  for (const m of document.querySelectorAll('meta[property="og:image"],meta[name="twitter:image"]')) share.push({ src: abs(m.content), note: m.getAttribute('property') || m.getAttribute('name') });
  const isLogo = (el) => /logo|brand|wordmark|lockup/i.test([el.id, el.getAttribute('class'), el.getAttribute('alt'), el.getAttribute('aria-label'), el.getAttribute('src')].join(' '));
  const inHeader = (el) => !!el.closest('header, nav, [class*=header], [id*=header]');
  for (const im of document.querySelectorAll('img')) if (vis(im) && (isLogo(im) || isLogo(im.parentElement || im))) logos.push({ src: abs(im.currentSrc || im.src), where: inHeader(im) ? 'header img' : 'img', note: 'img ' + (im.alt || '') });
  const svgs = [];
  for (const s of document.querySelectorAll('svg')) { if (!vis(s) || s.parentElement.closest('svg')) continue; const host = s.closest('a,header,nav,[class*=logo],[id*=logo]'); if (isLogo(s) || (host && (isLogo(host) || host.matches('header a:first-of-type, nav a:first-of-type')))) svgs.push({ svg: s.outerHTML.slice(0, 200000), where: inHeader(s) ? 'header svg' : 'svg' }); }

  // colours really painted, weighted: grounds by area, type by characters, headings apart, accents from buttons and links
  // every colour normalised through a canvas, so oklch(), lab(), color-mix() come out as rgb like the rest
  const cv = document.createElement('canvas'); cv.width = cv.height = 1; const cx = cv.getContext('2d', { willReadFrequently: true });
  const memo = {};
  const toRgb = (c) => { if (!c || c === 'none' || c === 'transparent') return null; if (c in memo) return memo[c]; cx.clearRect(0, 0, 1, 1); cx.fillStyle = 'rgba(0,0,0,0)'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1); const d = cx.getImageData(0, 0, 1, 1).data; return (memo[c] = d[3] < 13 ? null : 'rgb(' + d[0] + ', ' + d[1] + ', ' + d[2] + ')'); };
  const tally = {}, add = (c, role, w) => { const rgb = toRgb(c); if (!rgb) return; const k = role + '|' + rgb; tally[k] = (tally[k] || 0) + w; };
  const painted = new Set();
  const all = [...document.querySelectorAll('body, body *')].slice(0, 8000);
  const isHeading = (el, s) => /^H[1-3]$/.test(el.tagName) || parseFloat(s.fontSize) >= 28;
  for (const el of all) {
    if (!vis(el)) continue;
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    for (const p of ['color', 'backgroundColor', 'borderTopColor', 'fill', 'stroke']) { const v = toRgb(s[p]); if (v && (p !== 'borderTopColor' || parseFloat(s.borderTopWidth) > 0)) painted.add(v); }
    add(s.backgroundColor, 'ground', Math.min(r.width * r.height, 4e6));
    const own = ownText(el).length;
    if (own) add(s.color, isHeading(el, s) ? 'heading' : 'type', own);
    if (el.matches('button, a[class*=btn], a[class*=button], [role=button], .btn, .button, input[type=submit]')) { add(s.backgroundColor, 'accent', 400); if (parseFloat(s.borderTopWidth) > 0) add(s.borderTopColor, 'accent', 100); }
    else if (el.matches('a')) add(s.color, 'accent', 30);
  }
  // typefaces per role: family from the computed stack, weighted by characters
  const fonts = { heading: {}, body: {}, ui: {} };
  const samples = { heading: [], body: [], ui: [] };
  for (const el of all) {
    if (!vis(el)) continue;
    const own = ownText(el).length; if (!own) continue;
    const s = getComputedStyle(el);
    const role = el.matches('button, nav *, [role=button], input, label, .btn, .button') ? 'ui' : isHeading(el, s) ? 'heading' : 'body';
    const f = s.fontFamily.split(',')[0].replace(/["']/g, '').trim();
    const k = f + '|' + s.fontWeight;
    fonts[role][k] = fonts[role][k] || { family: f, weight: s.fontWeight, chars: 0, sizes: {} };
    fonts[role][k].chars += own;
    fonts[role][k].sizes[s.fontSize] = (fonts[role][k].sizes[s.fontSize] || 0) + own;
    if (samples[role].length < 6) { const id = 'ixs-' + role + '-' + samples[role].length; el.setAttribute('data-ixs', id); samples[role].push(id); }
  }
  const faces = [];
  for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (e) { continue; } for (const r of rules) { if (r.type === 5 && r.style) { const fam = r.style.getPropertyValue('font-family').replace(/["']/g, '').trim(); const src = r.style.getPropertyValue('src'); const m = /url\\(["']?([^"')]+)["']?\\)/.exec(src || ''); faces.push({ family: fam, src: m ? abs(m[1]) : null }); } } }
  const loaded = []; try { for (const f of document.fonts) if (f.status === 'loaded') loaded.push(f.family.replace(/["']/g, '')); } catch (e) {}
  // custom properties holding a colour, with the stylesheet rule that declares them
  const vars = {};
  for (const sh of document.styleSheets) { let rules; try { rules = sh.cssRules; } catch (e) { continue; } const walk = (rs) => { for (const r of rs) { if (r.cssRules && !r.style) { walk(r.cssRules); continue; } if (!r.style) continue; for (const p of r.style) if (p.startsWith('--')) { const v = r.style.getPropertyValue(p).trim(); if (/^(#[0-9a-f]{3,8}|rgba?\\(|hsla?\\(|oklch\\(|oklab\\(|lab\\(|hwb\\()/i.test(v)) { vars[p] = { value: v, rgb: toRgb(v), selector: (r.selectorText || '').slice(0, 60) }; } } } }; walk(rules); }
  for (const k in vars) vars[k].used = !!vars[k].rgb && painted.has(vars[k].rgb);
  const texts = { h1: [], h2: [], p: [], buttons: [] };
  const push = (arr, t, n) => { t = t.replace(/\\s+/g, ' ').trim(); if (t && t.length > 2 && !arr.includes(t) && arr.length < n) arr.push(t.slice(0, 400)); };
  for (const el of document.querySelectorAll('h1')) if (vis(el)) push(texts.h1, el.innerText || '', 10);
  for (const el of document.querySelectorAll('h2, h3')) if (vis(el)) push(texts.h2, el.innerText || '', 30);
  for (const el of document.querySelectorAll('p, li')) if (vis(el) && (el.innerText || '').length > 40) push(texts.p, el.innerText || '', 40);
  for (const el of document.querySelectorAll('button, a[class*=btn], a[class*=button], [role=button]')) if (vis(el)) push(texts.buttons, el.innerText || '', 20);
  return { title: document.title, description: (document.querySelector('meta[name=description]') || {}).content || '', lang: document.documentElement.lang || '', height: document.documentElement.scrollHeight, images, videos, embeds, logos, share, svgs, tally, fonts, samples, faces, loaded: [...new Set(loaded)], vars, texts };
})()`;

const toHex = (c) => { const m = /rgba?\(([^)]+)\)/.exec(c || ''); if (!m) return c; const [r, g, b] = m[1].split(/[\s,/]+/).map(Number); return '#' + [r, g, b].map((x) => Math.round(x).toString(16).padStart(2, '0')).join(''); };

async function main() {
  const o = args(process.argv.slice(2));
  const [url, outArg] = o._;
  if (!url || !outArg || !/^https?:\/\//.test(url)) { console.error('usage: node collect.mjs <url> <out-dir> [--shots 6] [--images 24] [--videos]'); process.exit(2); }
  const chrome = findChrome();
  if (!chrome) { console.error(NO_CHROME); process.exit(3); }
  const out = resolve(outArg);
  mkdirSync(out, { recursive: true });
  const conn = await launch(chrome, { args: ['--window-size=1440,900'] });
  const files = [], missing = [];
  let facts, finalUrl = url, platform = {}, cookie = null;
  const logos = [], shareImgs = [], images = [], videos = [];
  try {
    const page = await newPage(conn);
    await Promise.all([page.send('Page.enable'), page.send('Runtime.enable'), page.send('DOM.enable')]);
    await page.send('CSS.enable');
    await page.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    const loaded = new Promise((ok) => page.on('Page.loadEventFired', ok));
    const nav = await page.send('Page.navigate', { url });
    if (nav.errorText) throw new Error(`could not open ${url}: ${nav.errorText}`);
    await Promise.race([loaded, sleep(30_000)]);
    await sleep(2000);
    // a cookie banner hides the page and paints its own colours: refuse it (the most privacy-preserving choice), never accept
    const REFUSE = `(() => { const rx = /^(tout refuser|refuser( tout| et fermer)?|continuer sans accepter|reject all|decline all|decline|refuse all|only necessary|nécessaires uniquement)$/i; let hit = null; for (const el of document.querySelectorAll('button, a, [role=button]')) { const t = (el.innerText || '').trim(); const r = el.getBoundingClientRect(); if (rx.test(t) && r.width > 0 && r.height > 0) { el.click(); hit = t; } } return hit; })()`;
    cookie = await page.evaluate(REFUSE);
    if (cookie) await sleep(1200);
    const h0 = await page.evaluate('document.documentElement.scrollHeight');
    for (let y = 0; y < Math.min(h0, 900 * Math.max(o.shots, 4)); y += 700) { await page.evaluate(`window.scrollTo(0, ${y})`); await sleep(200); }
    await page.evaluate('window.scrollTo(0, 0)'); await sleep(800);
    const late = await page.evaluate(REFUSE);  // banners that appear after a delay or on scroll
    if (late) { cookie = late; await sleep(1200); }
    finalUrl = await page.evaluate('location.href');
    facts = await page.evaluate(PAGE_FACTS);
    // which fonts were really rendered for a few nodes of each role
    const { root } = await page.send('DOM.getDocument', { depth: -1 });
    for (const role of ['heading', 'body', 'ui']) {
      platform[role] = {};
      for (const id of facts.samples[role]) {
        try {
          const { nodeId } = await page.send('DOM.querySelector', { nodeId: root.nodeId, selector: `[data-ixs="${id}"]` });
          if (!nodeId) continue;
          const { fonts } = await page.send('CSS.getPlatformFontsForNode', { nodeId });
          for (const f of fonts || []) platform[role][f.familyName] = (platform[role][f.familyName] || 0) + f.glyphCount;
        } catch { /* node gone */ }
      }
    }
    const shots = Math.max(1, Math.min(o.shots, Math.ceil(facts.height / 900)));
    for (let i = 0; i < shots; i++) {
      await page.evaluate(`window.scrollTo(0, ${i * 900})`); await sleep(500);
      const { data } = await page.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, 30_000);
      const file = join(out, `screen-${String(i + 1).padStart(2, '0')}.png`);
      writeFileSync(file, Buffer.from(data, 'base64'));
      files.push({ kind: 'screen', file: `screen-${String(i + 1).padStart(2, '0')}.png`, note: `y=${i * 900}px` });
    }
    if (facts.height > 900 * o.shots) missing.push(`page continues below ${900 * o.shots}px (raise --shots)`);
    // some sites refuse curl (bot shields) but serve the page's own browser: fetch from inside the page
    const viaPage = async (src, file) => {
      try {
        const b64 = await page.evaluate(`fetch(${JSON.stringify(src)}).then(r => r.ok ? r.arrayBuffer() : null).then(b => { if (!b) return null; let s = ''; const u = new Uint8Array(b); for (let i = 0; i < u.length; i += 32768) s += String.fromCharCode.apply(null, u.subarray(i, i + 32768)); return btoa(s); })`);
        if (!b64) return false;
        writeFileSync(file, Buffer.from(b64, 'base64'));
        return statSync(file).size > 200;
      } catch { return false; }
    };
    const seen = new Set();
    const take = async (src, kind, n, extra = {}) => {
      if (!src || seen.has(src) || (src.startsWith('data:') && src.length > 2e6)) return null;
      seen.add(src);
      const ext = (/\.(png|jpe?g|webp|gif|svg|avif|ico|mp4|webm|mov)(\?|#|$)/i.exec(src)?.[1] || (src.startsWith('data:image/svg') ? 'svg' : kind === 'video' ? 'mp4' : 'png')).toLowerCase();
      const name = `${kind}-${String(n).padStart(2, '0')}.${ext}`;
      const file = join(out, name);
      let ok;
      if (src.startsWith('data:')) { const m = /^data:[^;,]+(;base64)?,(.*)$/s.exec(src); ok = !!m; if (m) writeFileSync(file, m[1] ? Buffer.from(m[2], 'base64') : decodeURIComponent(m[2])); }
      else ok = curl(src, file, finalUrl) || await viaPage(src, file);
      if (!ok) { missing.push(`${kind} ${src.slice(0, 90)}`); return null; }
      const f = { kind, file: name, src: src.startsWith('data:') ? 'data: URI on the page' : src, format: ext === 'jpeg' ? 'jpg' : ext, ...extra };
      files.push(f);
      return f;
    };
    let n = 0;
    for (const l of facts.logos) { const f = await take(l.src, 'logo', ++n, { where: l.where, note: l.note }); if (f) logos.push(f); }
    facts.svgs.slice(0, 4).forEach((s, i) => { const name = `logo-svg-${i + 1}.svg`; writeFileSync(join(out, name), s.svg.includes('xmlns=') ? s.svg : s.svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"')); const f = { kind: 'logo', file: name, src: 'inline SVG on the page', format: 'svg', where: s.where }; files.push(f); logos.push(f); });
    n = 0;
    for (const s of facts.share) { const f = await take(s.src, 'share', ++n, { note: s.note }); if (f) shareImgs.push(f); }
    n = 0;
    for (const im of facts.images.sort((a, b) => b.w * b.h - a.w * a.h).slice(0, o.images)) { const f = await take(im.src, 'image', ++n, { w: im.w, h: im.h, alt: im.alt }); if (f) images.push(f); }
    n = 0;
    for (const v of facts.videos) {
      const entry = { src: v.src, poster: v.poster };
      if (o.videos && v.src) { const f = await take(v.src, 'video', ++n); if (f) entry.file = f.file; }
      if (v.poster) { const f = await take(v.poster, 'image', 100 + n); if (f) entry.poster_file = f.file; }
      videos.push(entry);
    }

  } finally { await conn.close(); }

  const total = {};
  const colours = { ground: [], type: [], heading: [], accent: [] };
  for (const [k, w] of Object.entries(facts.tally)) { const [role, c] = k.split('|'); const hex = toHex(c); const key = role + hex; total[role] = (total[role] || 0) + w; const ex = colours[role].find((x) => x.hex === hex); if (ex) ex.w += w; else colours[role].push({ hex, w }); }
  for (const role of Object.keys(colours)) { colours[role].sort((a, b) => b.w - a.w); colours[role] = colours[role].slice(0, 6).map((c) => ({ ...c, share: total[role] ? +(c.w / total[role]).toFixed(3) : 0 })); }
  const usedHex = new Set(Object.values(colours).flat().map((c) => c.hex));
  const vars = Object.entries(facts.vars).map(([name, v]) => ({ name, value: v.value, hex: v.rgb ? toHex(v.rgb) : null, used: v.used, selector: v.selector }));
  const fonts = {};
  for (const role of ['heading', 'body', 'ui']) {
    const tot = Object.values(facts.fonts[role]).reduce((a, f) => a + f.chars, 0);
    fonts[role] = Object.values(facts.fonts[role]).sort((a, b) => b.chars - a.chars).slice(0, 5).map((f) => ({ ...f, share: tot ? +(f.chars / tot).toFixed(3) : 0, sizes: Object.entries(f.sizes).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([s]) => s) }));
  }
  const result = {
    tool: 'ix-studio collect (adapted from huashu-motion om grab, MIT)',
    url, final_url: finalUrl, at: new Date().toISOString(), title: facts.title, description: facts.description, lang: facts.lang,
    files, logos, share: shareImgs, images, videos, embeds: facts.embeds,
    colours, painted_hex: [...usedHex], vars, fonts, rendered_fonts: platform, font_faces: facts.faces, loaded_fonts: facts.loaded,
    texts: facts.texts, cookie_banner: cookie ? `refused ("${cookie}")` : 'none found or not refusable', missing,
  };
  writeFileSync(join(out, 'facts.json'), JSON.stringify(result, null, 2));
  const unused = vars.filter((v) => !v.used).length;
  console.log(`collect  ${url}${facts.title ? `  "${facts.title}"` : ''}`);
  console.log(`  ${out}  screens ${files.filter((f) => f.kind === 'screen').length} · logos ${logos.length} · images ${images.length} · videos ${videos.length}`);
  console.log(`  colours  ${['ground', 'type', 'heading', 'accent'].map((r) => `${r} ${colours[r].slice(0, 2).map((c) => c.hex).join(' ')}`).join(' · ')}`);
  console.log(`  type     ${['heading', 'body', 'ui'].map((r) => `${r} ${(fonts[r][0] || {}).family || '?'}`).join(' · ')}`);
  console.log(`  css vars ${vars.length} colour variables, ${unused} declared but not painted`);
  for (const m of missing.slice(0, 6)) console.log(`  ! ${m}`);
}

main().catch((e) => { console.error(String(e && e.message || e)); process.exit(1); });
