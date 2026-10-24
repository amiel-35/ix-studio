/* app.js: the interface that drives the studio. React 18 without JSX, components of the design system.
   It talks to the studio only through window.studioApi (api.js, see app/API.md): no simulated data lives here.

   The idea: the levels of the studio are side by side, from the widest to the most precise, and the position is read by following what is
   selected from left to right. The studio (what waits everywhere, then the brands) / a brand (its brief, its assets, its projects) / a project
   (its seven steps, what waits) / the detail of a step already done. A task opens on one thing and two gestures: diving into it folds the
   columns into thin vertical strips that keep their names; a click on a strip, Escape or the left arrow brings them back. Every column has
   its "+" to make what it holds (a brand, a project). The command palette (Cmd/Ctrl+K) reaches everything. The journal is kept on this side
   (localStorage): the API has no journal route yet. */
(function () {
  "use strict";
  const DS = window[Object.keys(window).find((k) => k.endsWith("DesignSystem_9fde59"))]; // the design system's global, found by its suffix
  const { Button, Badge, Callout, Eyebrow } = DS;
  const api = window.studioApi;
  const h = React.createElement;
  const { useState, useEffect, useRef, useCallback, useMemo } = React;

  /* ---------- small helpers ---------- */
  const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");
  const MOD = IS_MAC ? "⌘" : "Ctrl";
  const plural = (n, one, many) => n + " " + (n > 1 ? many : one);
  const norm = (s) => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const clock = (ms) => new Date(ms).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  function ago(sec, now) {
    if (!sec) return "";
    const s = Math.max(0, Math.round(now / 1000 - sec));
    if (s < 60) return "à l'instant";
    const m = Math.floor(s / 60);
    if (m < 60) return "depuis " + m + " min";
    const hh = Math.floor(m / 60);
    if (hh < 48) return "depuis " + hh + " h";
    return "depuis " + Math.floor(hh / 24) + " j";
  }
  function eta(sec) {
    if (sec == null) return "";
    if (sec <= 5) return "presque fini";
    if (sec < 50) return "environ " + Math.round(sec / 5) * 5 + " s";
    return "environ " + Math.max(1, Math.round(sec / 60)) + " min";
  }
  function studioLine(jobs) {
    if (!jobs.length) return "";
    const n = (k) => jobs.filter((j) => j.kind === k).length;
    const parts = [];
    if (n("image")) parts.push("dessine " + plural(n("image"), "image", "images"));
    if (n("diverge")) parts.push("écrit les variantes");
    if (n("learn")) parts.push("lit la marque");
    if (n("mandates")) parts.push("prépare les consignes");
    const left = Math.max(...jobs.map((j) => j.eta || 0));
    return "Le studio " + parts.join(" et ") + ", " + eta(left);
  }
  const FORMAT_WORDS = { "post-4x5": "post 4×5", "post-1x1": "post carré", story: "story", "poster-a3": "affiche A3", "poster-3x2": "affiche 3×2", linkedin: "bandeau 1200×627" };
  const fmtKey = (t) => t.trim().toLowerCase().replace(/ /g, "-");
  const fmtWord = (t) => FORMAT_WORDS[fmtKey(t)] || t.trim();
  /* the seven steps of a project, in plain words: the project column lists them, and `rankOf` places a task among them */
  const SEVEN = [
    { key: "brand", label: "La marque" },
    { key: "brief", label: "Le brief" },
    { key: "mandates", label: "Les consignes" },
    { key: "diverge", label: "La divergence" },
    { key: "image", label: "Les images" },
    { key: "piece", label: "La composition" },
    { key: "decide", label: "La décision" },
  ];
  const rankOf = (step) => { const k = step === "check" ? "piece" : step; const i = SEVEN.findIndex((s) => s.key === k); return i < 0 ? null : i + 1; };
  const STEP_WORD = { todo: "à venir", waiting: "t'attend", running: "le studio travaille", done: "faite" };
  const BRAND_STAGE = { new: "À décrire", discovering: "Lecture du site en cours", to_sort: "Visuels à trier", to_brief: "Brief à écrire", to_confirm: "À confirmer", ready: "Prête" };
  const FIELD_LABEL = { what: "Ce qu'elle est", who: "Pour qui", voice: "Sa voix", signature: "Sa signature", never: "Ce qu'elle ne dit jamais", colours: "Ses couleurs", logo: "Son logo" };
  const host = (url) => String(url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  /* the titles the studio gives to a brand's tasks say "la marque": the interface says which one */
  function taskTitle(t) {
    if (t.scope !== "brand" || !t.brand_name) return t.title;
    const n = t.brand_name, de = /^[aeiouyhàâéèêîôû]/i.test(n) ? "d'" + n : "de " + n;
    return t.title.replace("de la marque", de).replace(/la marque\b/, n);
  }
  /* what a task waits on, for a list: where it belongs, and how long it has waited */
  const taskPlace = (t) => t.scope === "brand" ? t.brand_name : t.brand_name + " · " + t.project_name;
  const owner = (t) => (t.scope === "brand" ? "@" + t.brand : t.project);

  /* the journal of decisions, per project, on this side */
  const loadJournal = (pid) => { try { return JSON.parse(localStorage.getItem("studio-journal:" + pid) || "[]"); } catch (e) { return []; } };
  const saveJournal = (pid, list) => { try { localStorage.setItem("studio-journal:" + pid, JSON.stringify(list.slice(0, 200))); } catch (e) { /* private window: no journal */ } };

  /* a core screen gives its own commands to the palette: the ref holds the list of the screen on screen */
  function useCmds(ctx, list) {
    const mine = useRef(null);
    mine.current = list;
    ctx.cmdsRef.current = list;
    useEffect(() => () => { if (ctx.cmdsRef.current === mine.current) ctx.cmdsRef.current = []; }, []);
  }

  /* ---------- building blocks ---------- */
  /* the one heading of a screen: it takes the focus when the screen opens, so the screen reader says where we are */
  function Head({ children, sr, focus = true }) {
    const ref = useRef(null);
    useEffect(() => { if (focus && ref.current) ref.current.focus({ preventScroll: true }); }, []);
    return h("h1", { ref, tabIndex: -1, className: sr ? "sr" : "head" }, children);
  }
  const Notice = ({ text }) => text ? h("p", { className: "notice", role: "status" }, h(Badge, { tone: "success" }, "Fait"), h("span", null, text)) : null;
  const Wait = ({ text }) => h("p", { className: "muted", role: "status" }, text || "Un instant.");
  function Frame({ src, alt, size }) {
    const ratio = size ? size[0] / size[1] : 4 / 5;
    return h("div", { className: "frame", style: { "--ratio": ratio } }, h("img", { src, alt }));
  }
  /* ================= a failed reading, or a failed job ================= */
  function JobFailed({ ctx, t }) {
    useCmds(ctx, []);
    const reason = String(t.question || "").replace(/^Le dernier essai a échoué : /, "").replace(/\.$/, "");
    const retry = () => ctx.act(async (snap) => {
      if (t.scope === "brand") await api.discover(t.brand);
      else if (t.step === "diverge") await api.diverge(t.project);
      else await api.drawImage(t.project, t.piece);
      ctx.log(owner(t), "toi", "Relancé : " + taskTitle(t), reason);
      await ctx.answered(owner(t), "C'est relancé.", { before: snap, any: false });
    });
    return h("div", { className: "task" }, h(Head, null, taskTitle(t)),
      h(Callout, { tone: "risk", label: "Ça n'a pas marché" }, reason),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: retry, "aria-label": "Relancer : " + taskTitle(t) }, "Relancer")));
  }

  /* ================= the logo: dropped as a file, chosen at once ================= */
  const LOGO_MAX = 2 * 1024 * 1024;
  function LogoDrop({ ctx, bid, label, variant = "secondary", size = "sm", onDone }) {
    const input = useRef(null);
    const pick = (ev) => {
      const f = ev.target.files && ev.target.files[0];
      ev.target.value = "";
      if (!f) return;
      if (f.size > LOGO_MAX) { ctx.fail(new Error("Ce fichier fait plus de 2 Mo : un logo est un petit fichier.")); return; }
      if (!/^image\/(png|jpeg|svg\+xml)$/.test(f.type)) { ctx.fail(new Error("Un logo se dépose en png, jpg ou svg.")); return; }
      ctx.act(async (snap) => {
        const b = await api.uploadLogo(bid, f);
        ctx.log("@" + bid, "toi", "Logo déposé : " + f.name, "");
        ctx.touch();
        if (onDone) await onDone(b, f, snap);
      });
    };
    return h(React.Fragment, null,
      h("input", { ref: input, type: "file", className: "sr", accept: "image/png,image/jpeg,image/svg+xml", onChange: pick, tabIndex: -1, "aria-hidden": "true", "data-logo-input": "1" }),
      h(Button, { variant, size, disabled: ctx.busy, onClick: () => input.current && input.current.click(), "aria-label": label + " (png, jpg ou svg, 2 Mo au plus)" }, label));
  }

  /* the colours of a brand, each with its state: measured and not confirmed yet, or confirmed */
  const Swatches = ({ colours, mini, quiet }) => colours.length === 0 ? h("p", { className: "muted small" }, "Aucune couleur pour cette marque.") :
    h("ul", { className: "swatches" + (mini ? " mini" : ""), "aria-label": "Couleurs de la marque" }, colours.map((c) => h("li", { key: c.hex, className: "swatch" },
      h("i", { style: { background: c.hex }, role: "img", "aria-label": "Couleur " + c.hex + (c.state === "deduced" ? ", à confirmer" : "") }),
      h("span", { className: "mono small" }, c.hex), !mini && !quiet && c.state === "deduced" && h("span", { className: "small muted" }, "à confirmer"))));

  /* ================= a brand: sort the visuals one by one, then choose (or drop) the logo ================= */
  function BrandSort({ ctx, t }) {
    const [brand, setBrand] = useState(null);
    useEffect(() => { api.getBrand(t.brand).then(setBrand).catch(ctx.fail); }, [t.brand]);
    if (!brand) return h("div", { className: "task" }, h(Wait, { text: "Chargement des visuels." }));
    return h(Sorter, { ctx, bid: t.brand, brand });
  }

  function Sorter({ ctx, bid, brand }) {
    const { evidence } = brand.assets;
    const [logos, setLogos] = useState(brand.assets.logos);
    const [dec, setDec] = useState(() => { const m = {}; evidence.forEach((e) => { if (typeof e.kept === "boolean") m[e.id] = e.kept; }); return m; });
    const [cur, setCur] = useState(() => Math.max(0, evidence.findIndex((e) => typeof e.kept !== "boolean")));
    const [stage, setStage] = useState(() => (evidence.length === 0 ? "end" : "visuals")); // visuals, end
    const [logo, setLogo] = useState(() => (brand.assets.logo && brand.assets.logo.id) || (brand.assets.logos.length === 1 ? brand.assets.logos[0].id : null));
    const [said, setSaid] = useState("");
    const hist = useRef([]);
    const H = useRef({});

    const decide = (val) => {
      const e = evidence[cur];
      if (!e) return;
      hist.current.push({ id: e.id, prev: dec[e.id], at: cur });
      const next = { ...dec, [e.id]: val };
      setDec(next);
      setSaid((val ? "Gardé : " : "Écarté : ") + e.note);
      const nxt = evidence.findIndex((x, i) => i > cur && next[x.id] === undefined);
      const any = evidence.findIndex((x) => next[x.id] === undefined);
      if (nxt >= 0) setCur(nxt);
      else if (any >= 0) setCur(any);
      else setStage("end");
    };
    const undo = () => {
      const last = hist.current.pop();
      if (!last) return;
      setDec((d) => { const n = { ...d }; if (last.prev === undefined) delete n[last.id]; else n[last.id] = last.prev; return n; });
      setCur(last.at); setStage("visuals"); setSaid("Annulé.");
    };
    const move = (n) => { if (stage === "visuals") setCur((c) => Math.max(0, Math.min(evidence.length - 1, c + n))); };
    const followStudio = () => {
      const n = { ...dec };
      evidence.forEach((x) => { if (n[x.id] === undefined && typeof x.proposed === "boolean") n[x.id] = x.proposed; });
      setDec(n);
      setSaid("Propositions du studio appliquées à ce qui restait.");
      const any = evidence.findIndex((x) => n[x.id] === undefined);
      if (any >= 0) setCur(any); else setStage("end");
    };
    H.current = { decide, undo, move, stage, cur };
    ctx.arrowsRef.current = stage === "visuals" && cur > 0; // from the second visual on, the left arrow goes back one visual; on the first, it brings the columns back
    useEffect(() => () => { ctx.arrowsRef.current = false; }, []);

    useEffect(() => {
      const f = (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.altKey || ctx.overlayRef.current) return;
        const t = ev.target, tag = t && t.tagName;
        if (tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable) || (tag === "INPUT" && !["radio", "checkbox", "button"].includes(t.type))) return;
        const k = ev.key.toLowerCase();
        if (H.current.stage === "visuals" && k === "g") { ev.preventDefault(); H.current.decide(true); }
        else if (H.current.stage === "visuals" && k === "e") { ev.preventDefault(); H.current.decide(false); }
        else if (k === "u") { ev.preventDefault(); H.current.undo(); }
        else if (ev.key === "ArrowRight" && H.current.stage === "visuals") { ev.preventDefault(); H.current.move(1); }
        else if (ev.key === "ArrowLeft" && H.current.stage === "visuals" && H.current.cur > 0) { ev.preventDefault(); H.current.move(-1); } // at the first visual, the left arrow brings the columns back
      };
      window.addEventListener("keydown", f);
      return () => window.removeEventListener("keydown", f);
    }, []);

    const kept = evidence.filter((e) => dec[e.id] === true), dropped = evidence.filter((e) => dec[e.id] === false);
    const left = evidence.length - kept.length - dropped.length;
    const hasProposals = evidence.some((x) => dec[x.id] === undefined && typeof x.proposed === "boolean");
    const e = evidence[cur];
    const summary = plural(kept.length, "gardé", "gardés") + ", " + plural(dropped.length, "écarté", "écartés");

    useCmds(ctx, stage === "visuals" ? [
      e && { id: "keep", label: "Garder ce visuel", hint: "G", run: () => decide(true) },
      e && { id: "drop", label: "Écarter ce visuel", hint: "E", run: () => decide(false) },
      { id: "undo", label: "Annuler le dernier geste", hint: "U", run: undo },
      hasProposals && { id: "follow", label: "Suivre les propositions du studio pour les " + left + " restants", run: followStudio },
    ].filter(Boolean) : [{ id: "undo", label: "Annuler le dernier geste", hint: "U", run: undo }]);

    const submit = () => ctx.act(async (snap) => {
      const r = await api.keepBrand(bid, kept.map((x) => x.id), logo);
      const lg = logos.find((l) => l.id === logo);
      ctx.log("@" + bid, "toi", "Tri de la marque : " + plural(r.kept, "gardé", "gardés") + ", " + plural(r.discarded, "écarté", "écartés") + (lg ? ", logo : " + lg.note : ""),
        dropped.length ? "Écartés : " + dropped.map((x) => x.note).join(" ; ") : "");
      await ctx.answered("@" + bid, "Tri enregistré : " + summary + ".", { before: snap });
    });
    const dropped_ = (b) => { setLogos(b.assets.logos); setLogo(b.assets.logo ? b.assets.logo.id : null); setSaid("Logo déposé et choisi."); };

    if (stage === "end") {
      return h("div", { className: "task" },
        h(Head, null, logos.length ? "Quel logo garder ?" : evidence.length === 0 ? "Dépose le logo de la marque" : "Le tri est fait : il manque le logo"),
        evidence.length > 0 && h("p", { className: "lead muted" }, summary + "."),
        logos.length === 0 && h("p", { className: "lead" }, "Le site n'en a pas donné. Dépose le fichier de ton logo : sans lui, la marque ne peut pas être prête."),
        logos.length > 0 && h("div", { className: "logos", role: "radiogroup", "aria-label": "Logo de la marque" }, logos.map((l) => h("button", { key: l.id, type: "button", role: "radio", "aria-checked": logo === l.id, className: "logo", onClick: () => setLogo(l.id) },
          h("img", { src: l.preview, alt: "" }), h("span", { className: "small" }, l.note)))),
        h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !logo, onClick: submit, "aria-label": "Valider le tri de la marque" }, "Valider le tri"),
          h(LogoDrop, { ctx, bid, label: logos.length ? "Déposer un autre logo" : "Déposer un logo", size: "lg", variant: logos.length ? "secondary" : "primary", onDone: dropped_ }),
          evidence.length > 0 && h(Button, { variant: "ghost", size: "lg", onClick: () => { setStage("visuals"); setCur(evidence.length - 1); }, "aria-label": "Revoir les visuels" }, "Revoir les visuels")),
        !logo && h("p", { className: "small muted" }, "Choisis un logo, ou dépose le tien, pour continuer."),
        h("span", { className: "sr", role: "status", "aria-live": "polite" }, said));
    }
    const mark = dec[e.id] === true ? "gardé" : dec[e.id] === false ? "écarté" : null;
    const proposal = e.proposed === true ? "Le studio propose de garder." : e.proposed === false ? "Le studio propose d'écarter." : "Le studio ne tranche pas : à toi.";
    return h("div", { className: "task" },
      h(Eyebrow, null, "Visuel " + (cur + 1) + " sur " + evidence.length),
      h(Head, { focus: false }, e.note),
      h("figure", { className: "frame wide" }, h("img", { src: e.preview, alt: e.note })),
      h("p", { className: "small muted" }, mark ? "Tu l'as " + mark + ". " : "", proposal),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", onClick: () => decide(true), "aria-label": "Garder ce visuel : " + e.note }, "Garder"),
        h(Button, { variant: "secondary", size: "lg", onClick: () => decide(false), "aria-label": "Écarter ce visuel : " + e.note }, "Écarter"),
        left === 0 && h(Button, { variant: "ghost", size: "lg", onClick: () => setStage("end"), "aria-label": "Continuer vers le choix du logo" }, "Continuer")),
      h("p", { className: "keys small muted" }, "Clavier : G garder, E écarter, U annuler, flèches pour naviguer."),
      h("span", { className: "sr", role: "status", "aria-live": "polite" }, said));
  }

  /* ================= a brand: its brief, as one sentence whose pieces are corrected ================= */
  const BPARTS = [
    { k: "what", before: ", c'est ", label: "ce qu'elle est", area: true },
    { k: "who", before: ". Elle parle à ", label: "pour qui", area: true },
    { k: "voice", before: ". Sa voix : ", label: "sa voix" },
    { k: "signature", before: ". Sa signature : « ", after: " »", label: "sa signature" },
    { k: "never", before: ". Elle ne dit jamais : ", label: "ce qu'elle ne dit jamais" },
    { k: "colours", before: ". Ses couleurs : ", label: "ses couleurs" },
  ];

  function BrandBrief({ ctx, t }) {
    const bid = t.brand, name = t.brand_name;
    const [data, setData] = useState(null);
    const [fields, setFields] = useState(null);
    const [open, setOpen] = useState(null);
    useEffect(() => {
      api.brandBrief(bid).then((b) => { setData(b); const f = {}; Object.keys(b.fields).forEach((k) => { f[k] = b.fields[k].value || ""; }); setFields(f); }).catch(ctx.fail);
    }, [bid]);
    useEffect(() => {
      if (!open) return;
      const f = (ev) => { if (ev.key === "Escape" && !ctx.overlayRef.current) { ev.stopPropagation(); ev.preventDefault(); setOpen(null); } };
      window.addEventListener("keydown", f, true);
      return () => window.removeEventListener("keydown", f, true);
    }, [open]);
    useCmds(ctx, []);
    if (!fields) return h("div", { className: "task" }, h(Wait, { text: "Chargement du brief de la marque." }));
    if (data.done && !t.reopen) return h(NeedLogo, { ctx, bid, name });
    const set = (k, v) => setFields({ ...fields, [k]: v });
    const stateOf = (k) => (data.fields[k].state === "deduced" && (fields[k] || "") === data.fields[k].value ? "deduced" : "typed");
    const anyDeduced = BPARTS.some((p) => stateOf(p.k) === "deduced");
    const piece = (p) => h(React.Fragment, { key: p.k }, p.before, h("span", {
      role: "button", tabIndex: 0, className: "bit", "aria-expanded": open === p.k, "data-open": open === p.k, "data-state": stateOf(p.k),
      "aria-label": "Corriger " + p.label + " : " + (fields[p.k] || "vide") + (stateOf(p.k) === "deduced" ? " (déduit par le studio, à confirmer)" : ""),
      onClick: () => setOpen(open === p.k ? null : p.k),
      onKeyDown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setOpen(open === p.k ? null : p.k); } },
    }, (fields[p.k] || "").trim() || h("span", { className: "blank" }, "à écrire")), p.after || "");
    const cur = BPARTS.find((p) => p.k === open);
    const submit = () => ctx.act(async (snap) => {
      const changed = BPARTS.filter((p) => (fields[p.k] || "") !== (data.fields[p.k].value || "")).map((p) => p.label);
      await api.saveBrandBrief(bid, fields);
      ctx.log("@" + bid, "toi", "Brief de la marque validé", changed.length ? "Corrigé : " + changed.join(", ") : "Rien à corriger");
      await ctx.answered("@" + bid, "Brief de " + name + " enregistré.", { before: snap, sibling: (t) => t.kind === "brand-brief" }); // a brand with no logo and no site still asks for one: the same task, said otherwise
    });
    return h("div", { className: "task" }, h(Head, { sr: true }, "Relis le brief de " + name),
      h("p", { className: "sentence" }, name, BPARTS.map(piece), "."),
      h("p", { className: "small muted" }, "Touche un passage pour le corriger." + (anyDeduced ? " Les passages en pointillé sont ce que le studio a déduit : validés tels quels, ils sont confirmés." : "")),
      cur && h("div", { className: "editor" },
        h("label", { htmlFor: "bed", className: "small" }, "Corriger " + cur.label),
        cur.area ? h("textarea", { id: "bed", autoFocus: true, value: fields[cur.k] || "", onChange: (e) => set(cur.k, e.target.value) })
          : h("input", { id: "bed", type: "text", autoFocus: true, value: fields[cur.k] || "", onChange: (e) => set(cur.k, e.target.value), onKeyDown: (e) => { if (e.key === "Enter") setOpen(null); } }),
        (cur.k === "voice" || cur.k === "never") && h("span", { className: "small muted" }, "Sépare par des virgules."),
        h("div", { className: "row" }, h(Button, { variant: "secondary", size: "sm", onClick: () => setOpen(null), "aria-label": "Terminer la correction de " + cur.label }, "Fait"))),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !(fields.what || "").trim(), onClick: submit, "aria-label": "Valider le brief de la marque" }, data.done ? "Enregistrer le brief" : "Valider le brief")),
      !(fields.what || "").trim() && h("p", { className: "small muted", role: "status" }, "Il manque : ce qu'elle est."));
  }

  /* the brief is done, the brand has no logo and the studio has no site to find one in: drop one, or give the site */
  function NeedLogo({ ctx, bid, name }) {
    const [site, setSite] = useState("");
    useCmds(ctx, []);
    const read = () => ctx.act(async (snap) => {
      await api.updateBrand(bid, { site: site.trim() });
      await api.discover(bid);
      ctx.log("@" + bid, "toi", "Site donné : " + site.trim(), "Le studio le lit pour y trouver un logo");
      await ctx.answered("@" + bid, "Le studio lit le site de " + name + ".", { before: snap, any: false });
    });
    return h("div", { className: "task" }, h(Head, null, name + " n'a pas de logo"),
      h("p", { className: "lead" }, "Dépose le fichier de son logo, ou donne l'adresse de son site pour que le studio le cherche."),
      h("div", { className: "gestures" },
        h(LogoDrop, { ctx, bid, label: "Déposer un logo", size: "lg", variant: "primary", onDone: (b, f, snap) => ctx.answered("@" + bid, "Logo déposé : " + name + " a un logo.", { before: snap, any: false }) })),
      h("form", { className: "sec", onSubmit: (e) => { e.preventDefault(); if (site.trim()) read(); } },
        h("div", { className: "field" }, h("label", { htmlFor: "nl-site" }, "Ou son site"), h("input", { id: "nl-site", type: "text", inputMode: "url", value: site, onChange: (e) => setSite(e.target.value), autoComplete: "off", placeholder: "ma-marque.example" })),
        h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "secondary", size: "lg", disabled: ctx.busy || !site.trim(), "aria-label": "Lire ce site pour y trouver le logo" }, "Lire le site"))));
  }

  /* ================= a brand: confirm what the studio deduced, in one gesture ================= */
  function BrandConfirm({ ctx, t }) {
    const bid = t.brand, name = t.brand_name;
    const [brand, setBrand] = useState(null);
    const [fix, setFix] = useState(false);
    useEffect(() => { api.getBrand(bid).then(setBrand).catch(ctx.fail); }, [bid]);
    useCmds(ctx, []);
    if (!brand) return h("div", { className: "task" }, h(Wait, null));
    if (fix) return h(BrandBrief, { ctx, t: { ...t, reopen: true } });
    const a = brand.assets;
    const keys = Object.keys(FIELD_LABEL).filter((k) => (k === "logo" ? a.logo : brand.identity[k].state !== "absent"));
    const toConfirm = keys.filter((k) => (k === "logo" ? a.logo.state === "deduced" : brand.identity[k].state === "deduced"));
    const shown = toConfirm.length ? toConfirm : keys;
    const confirm = () => ctx.act(async (snap) => {
      await api.confirmBrand(bid);
      ctx.log("@" + bid, "toi", "Marque confirmée", toConfirm.map((k) => FIELD_LABEL[k].toLowerCase()).join(", "));
      await ctx.answered("@" + bid, name + " est confirmée.", { before: snap });
    });
    return h("div", { className: "task" }, h(Head, null, toConfirm.length ? "Confirme ce que le studio a déduit de " + name : "Regarde " + name + ", puis confirme"),
      h("ul", { className: "rows facts" }, shown.map((k) => h("li", { key: k, className: "fact" },
        h("span", { className: "cap" }, FIELD_LABEL[k]),
        k === "logo" ? h("img", { src: a.logo.preview, alt: "Logo de " + name, className: "factlogo" })
          : k === "colours" && a.colours.length ? h(Swatches, { colours: a.colours, quiet: true })
          : h("span", { className: "factval" }, brand.identity[k].value),
        h("span", { className: "small muted" }, k === "logo" ? a.logo.source : brand.identity[k].source)))),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: confirm, "aria-label": "Confirmer la marque" }, toConfirm.length ? "Tout confirmer" : "Confirmer"),
        h(Button, { variant: "secondary", size: "lg", onClick: () => setFix(true), "aria-label": "Corriger dans le brief de la marque" }, "Corriger")));
  }

  /* ================= 3. the brief, as one sentence whose pieces are corrected ================= */
  const PARTS = [
    { k: "objective", before: "Je veux ", label: "l'objectif", area: true },
    { k: "audience", before: ". Pour ", label: "le public", area: true },
    { k: "message", before: ". Le message : ", label: "le message", area: true },
    { k: "format", before: ". Sur ", label: "les formats" },
    { k: "fixed", before: ". Ce qui ne bouge pas : ", label: "ce qui ne bouge pas", area: true },
    { k: "cta", before: ". Pour finir : « ", after: " »", label: "l'appel à l'action" },
  ];
  const EXTRA = [
    { k: "layout", before: ". Mise en page : ", label: "la mise en page", empty: "libre", area: true },
    { k: "language", before: ". Langue : ", label: "la langue", empty: "fr" },
  ];
  const REQUIRED = { objective: "l'objectif", audience: "le public", message: "le message" };

  function Brief({ ctx, pid }) {
    const [data, setData] = useState(null);
    const [fields, setFields] = useState(null);
    const [open, setOpen] = useState(null);
    const [extra, setExtra] = useState(false);
    useEffect(() => { api.brief(pid).then((b) => { setData(b); setFields(b.fields); }).catch(ctx.fail); }, [pid]);
    useEffect(() => {
      if (!open) return;
      const f = (ev) => { if (ev.key === "Escape" && !ctx.overlayRef.current) { ev.stopPropagation(); setOpen(null); } };
      window.addEventListener("keydown", f);
      return () => window.removeEventListener("keydown", f);
    }, [open]);
    useCmds(ctx, data ? [{ id: "extra", label: extra ? "Cacher la mise en page et la langue" : "Corriger la mise en page ou la langue", run: () => setExtra(!extra) }] : []);
    if (!fields) return h("div", { className: "task" }, h(Wait, { text: "Chargement du brief." }));
    const set = (k, v) => setFields({ ...fields, [k]: v });
    const tokens = (fields.format || "").split(",").map((x) => x.trim()).filter(Boolean);
    const known = new Set(data.formats);
    const away = tokens.filter((t) => !known.has(fmtKey(t)));
    const missing = Object.keys(REQUIRED).filter((k) => !(fields[k] || "").trim());
    const toggleFormat = (f) => set("format", (tokens.some((t) => fmtKey(t) === f) ? tokens.filter((t) => fmtKey(t) !== f) : [...tokens, f]).join(", "));

    const shown = (p) => {
      if (p.k === "format") {
        if (tokens.length === 0) return h("span", { className: "blank" }, "à choisir");
        return tokens.map((t, i) => h(React.Fragment, { key: i }, i ? ", " : "", known.has(fmtKey(t)) ? fmtWord(t) : h("span", { className: "away" }, t)));
      }
      const v = (fields[p.k] || "").trim();
      return v || h("span", { className: "blank" }, p.empty || "à écrire");
    };
    const piece = (p) => h(React.Fragment, { key: p.k }, p.before, h("span", {
      role: "button", tabIndex: 0, className: "bit", "aria-expanded": open === p.k, "aria-label": "Corriger " + p.label + " : " + (fields[p.k] || "vide"),
      "data-open": open === p.k, onClick: () => setOpen(open === p.k ? null : p.k),
      onKeyDown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setOpen(open === p.k ? null : p.k); } },
    }, shown(p)), p.after || "");
    const cur = [...PARTS, ...EXTRA].find((p) => p.k === open);

    const submit = () => ctx.act(async (snap) => {
      const changed = [...PARTS, ...EXTRA].filter((p) => (fields[p.k] || "") !== (data.fields[p.k] || "")).map((p) => p.label);
      const r = await api.saveBrief(pid, fields);
      ctx.log(pid, "toi", "Brief relu et validé", changed.length ? "Corrigé : " + changed.join(", ") : "Rien à corriger");
      if (r.left_out.length) ctx.log(pid, "studio", "Formats mis de côté : " + r.left_out.join(", "), fields.left_out_note || "");
      await ctx.answered(pid, "Brief validé" + (r.left_out.length ? ". Mis de côté : " + r.left_out.join(", ") : "") + ".", { before: snap });
    });
    return h("div", { className: "task" }, h(Head, { sr: true }, "Relis le brief"),
      h("p", { className: "sentence" }, PARTS.map(piece), extra && EXTRA.map(piece), "."),
      h("p", { className: "small muted" }, "Touche un passage pour le corriger.",
        !extra && h(React.Fragment, null, " ", h("button", { type: "button", className: "linkbtn", onClick: () => setExtra(true), "aria-label": "Corriger aussi la mise en page ou la langue" }, "Mise en page, langue"))),
      cur && h("div", { className: "editor" },
        h("label", { htmlFor: "ed", className: "small" }, "Corriger " + cur.label),
        cur.k === "format" ? h("div", { className: "sec" },
          h("input", { id: "ed", type: "text", autoFocus: true, value: fields.format || "", onChange: (e) => set("format", e.target.value), "aria-describedby": "ed-hint" }),
          h("div", { className: "row", role: "group", "aria-label": "Formats que le studio sait faire" }, data.formats.map((f) => h("button", { key: f, type: "button", className: "chip", "aria-pressed": tokens.some((t) => fmtKey(t) === f), onClick: () => toggleFormat(f) }, fmtWord(f)))),
          h("p", { id: "ed-hint", className: "small muted" }, "Sépare par des virgules. Un format que le studio ne sait pas faire est mis de côté, pas oublié."))
          : cur.area ? h("textarea", { id: "ed", autoFocus: true, value: fields[cur.k] || "", onChange: (e) => set(cur.k, e.target.value) })
          : h("input", { id: "ed", type: "text", autoFocus: true, value: fields[cur.k] || "", onChange: (e) => set(cur.k, e.target.value), onKeyDown: (e) => { if (e.key === "Enter") setOpen(null); } }),
        h("div", { className: "row" }, h(Button, { variant: "secondary", size: "sm", onClick: () => setOpen(null), "aria-label": "Terminer la correction de " + cur.label }, "Fait"))),
      away.length > 0 && h("div", { className: "aside" },
        h("p", null, "Le studio ne sait pas faire « " + away.join(", ") + " ». On le met de côté, il reste dans le brief."),
        h("div", { className: "field" }, h("label", { htmlFor: "away-note", className: "small" }, "Un mot, pour t'en souvenir"),
          h("input", { id: "away-note", type: "text", value: fields.left_out_note || "", onChange: (e) => set("left_out_note", e.target.value) }))),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || missing.length > 0, onClick: submit, "aria-label": away.length ? "Valider le brief et mettre de côté : " + away.join(", ") : "Valider le brief" },
          data.confirmed ? "Enregistrer le brief" : away.length ? "Valider et mettre de côté" : "Valider le brief")),
      missing.length > 0 && h("p", { className: "small muted", role: "status" }, "Il manque : " + missing.map((k) => REQUIRED[k]).join(", ") + "."));
  }

  /* ================= 4. the instructions to the agents ================= */
  function Mandates({ ctx, pid }) {
    const [m, setM] = useState(null);
    const [edit, setEdit] = useState(false);
    useEffect(() => { api.mandates(pid).then(setM).catch(ctx.fail); }, [pid]);
    useCmds(ctx, m ? [{ id: "edit", label: edit ? "Arrêter de corriger les consignes" : "Corriger les consignes", run: () => setEdit(!edit) }] : []);
    if (!m) return h("div", { className: "task" }, h(Wait, null));
    const setItem = (id, v) => setM({ ...m, items: m.items.map((x) => (x.id === id ? { ...x, mandate: v } : x)) });
    const submit = () => ctx.act(async (snap) => {
      await api.saveMandates(pid, m.items, m.common);
      ctx.log(pid, "toi", "Consignes aux agents relues et validées", "Mandats : " + m.items.map((x) => x.mandate).join(" ; "));
      await ctx.answered(pid, "Consignes validées : la divergence peut partir.", { before: snap });
    });
    return h("div", { className: "task" }, h(Head, null, "Voilà ce que les quatre agents vont recevoir"),
      edit ? h("div", { className: "sec" },
        h("div", { className: "field" }, h("label", { htmlFor: "common" }, "La consigne commune"), h("textarea", { id: "common", value: m.common, onChange: (e) => setM({ ...m, common: e.target.value }) })),
        m.items.map((it) => h("div", { key: it.id, className: "field" }, h("label", { htmlFor: "m-" + it.id }, "Agent " + it.id.toUpperCase()),
          h("input", { id: "m-" + it.id, type: "text", value: it.mandate, onChange: (e) => setItem(it.id, e.target.value) }))))
        : h("div", { className: "sec" },
          h("p", { className: "lead" }, m.common),
          h("ul", { className: "plain" }, m.items.map((it) => h("li", { key: it.id }, h("span", { className: "cap" }, "Agent " + it.id.toUpperCase()), h("span", null, it.mandate))))),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: submit, "aria-label": m.confirmed ? "Enregistrer les consignes aux agents" : "Valider les consignes aux agents" }, m.confirmed ? "Enregistrer" : "C'est bon"),
        h(Button, { variant: "secondary", size: "lg", onClick: () => setEdit(!edit), "aria-label": edit ? "Arrêter de corriger" : "Corriger les consignes" }, edit ? "Arrêter de corriger" : "Corriger")));
  }

  /* ================= 5. divergence: launch, then pick ================= */
  function DivergeLaunch({ ctx, pid }) {
    useCmds(ctx, []);
    const launch = () => ctx.act(async (snap) => {
      await api.diverge(pid);
      ctx.log(pid, "toi", "Divergence lancée", "Quatre agents écrivent chacun leur variante, à l'aveugle");
      await ctx.answered(pid, "Divergence lancée : quatre agents écrivent chacun leur variante.", { before: snap });
    });
    return h("div", { className: "task" }, h(Head, null, "Lance la divergence"),
      h("p", { className: "lead" }, "Quatre agents écrivent chacun une variante, sans voir celles des autres. Tu choisis ensuite."),
      h("div", { className: "gestures" }, h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: launch, "aria-label": "Lancer la divergence" }, "Lancer")));
  }

  function DivergePick({ ctx, pid, readOnly }) {
    const [variants, setVariants] = useState(null);
    const [formats, setFormats] = useState([]);
    const [chosen, setChosen] = useState([]);
    const [inSeries, setInSeries] = useState([]);
    useEffect(() => {
      api.variants(pid).then(setVariants).catch(ctx.fail);
      api.brief(pid).then((b) => setFormats(b.chosen)).catch(ctx.fail);
      if (readOnly) api.project(pid).then((p) => setInSeries([...new Set(p.pieces.map((x) => x.variant))])).catch(ctx.fail);
    }, [pid]);
    useCmds(ctx, []);
    if (!variants) return h("div", { className: "task" }, h(Wait, null));
    const toggle = (id) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
    const pick = () => ctx.act(async (snap) => {
      const pcs = await api.pick(pid, chosen);
      ctx.log(pid, "toi", "Série choisie : " + plural(chosen.length, "variante", "variantes") + ", " + plural(pcs.length, "pièce", "pièces"),
        chosen.map((id) => { const v = variants.find((x) => x.id === id); return v.mandate + " : " + v.headline; }).join(" ; "));
      await ctx.answered(pid, "Série créée : " + plural(pcs.length, "pièce", "pièces") + " à faire.", { before: snap });
    });
    return h("div", { className: "task" }, h(Head, null, readOnly ? "Les variantes de la série" : "Quelle variante, ou lesquelles ?"),
      !readOnly && h("p", { className: "lead muted" }, "Chaque variante gardée devient une pièce par format."),
      h("ul", { className: "variants", "aria-label": "Variantes" }, variants.map((v) => {
        const on = readOnly ? inSeries.includes(v.id) : chosen.includes(v.id);
        return h("li", { key: v.id }, h("button", { type: "button", className: "var", "aria-pressed": on, disabled: readOnly, onClick: () => toggle(v.id), "aria-label": v.headline + (v.subline ? " " + v.subline : "") + ", " + v.mandate + (on ? ", choisie" : "") },
          h("span", { className: "hl" }, v.headline), v.subline && h("span", null, v.subline), h("span", { className: "cap" }, v.mandate)));
      })),
      !readOnly && h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || chosen.length === 0, onClick: pick, "aria-label": "Créer la série avec les variantes choisies" }, "Créer la série"),
        h("span", { className: "small muted" }, chosen.length ? plural(chosen.length, "variante", "variantes") + " × " + plural(formats.length, "format", "formats") + " = " + plural(chosen.length * formats.length, "pièce", "pièces") : "Choisis au moins une variante.")),
      readOnly && h("p", { className: "small muted" }, "La série est lancée. Pour la refaire, relance la divergence."));
  }

  /* ================= 6. a piece: prompt, composition, decision ================= */
  const stageOf = (pc, jobs) => {
    if ((jobs || []).some((j) => j.kind === "image" && j.piece === pc.id)) return "running";
    if (pc.decision && pc.decision.verdict === "keep") return "kept";
    if (pc.composed) return "decide";
    if (pc.image) return "compose";
    return "prompt";
  };
  const STAGE_WORDS = { running: "Le studio dessine l'image", kept: "Gardée", decide: "À décider", compose: "À composer", prompt: "Prompt à relire" };

  function usePiece(ctx, pid, id) {
    const [pc, setPc] = useState(null);
    useEffect(() => { api.piece(pid, id).then(setPc).catch(ctx.fail); }, [pid, id]);
    return [pc, setPc];
  }
  const PieceHead = ({ pc }) => h(React.Fragment, null,
    h(Eyebrow, null, pc.label + " · " + pc.size[0] + " × " + pc.size[1]),
    h(Head, null, pc.headline));

  function Prompt({ ctx, pid, id }) {
    const [pc] = usePiece(ctx, pid, id);
    const [prompt, setPrompt] = useState(null);
    useEffect(() => { if (pc) setPrompt(pc.prompt); }, [pc && pc.id]);
    useCmds(ctx, []);
    if (!pc || prompt === null) return h("div", { className: "task" }, h(Wait, null));
    const draw = () => ctx.act(async (snap) => {
      await api.savePrompt(pid, id, prompt);
      await api.drawImage(pid, id);
      ctx.log(pid, "toi", "Image lancée pour " + pc.label, "Prompt relu : " + prompt);
      await ctx.answered(pid, "Image lancée pour " + pc.label + ".", { before: snap, any: false, sibling: (t) => t.kind === "prompt" && t.piece !== id });
    });
    return h("div", { className: "task" }, h(PieceHead, { pc }),
      pc.bans && pc.bans.length > 0 && h("p", { className: "small" }, "Tu avais refusé : " + pc.bans.join(" ; ") + ". Le studio le retient."),
      h("div", { className: "field" }, h("label", { htmlFor: "prompt" }, "Le prompt de l'image"),
        h("textarea", { id: "prompt", className: "mono", value: prompt, onChange: (e) => setPrompt(e.target.value) })),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !prompt.trim(), onClick: draw, "aria-label": "Lancer l'image de " + pc.label }, "Dessiner l'image")));
  }

  function Compose({ ctx, pid, id }) {
    const [pc] = usePiece(ctx, pid, id);
    const [redo, setRedo] = useState(false);
    const [prompt, setPrompt] = useState("");
    useEffect(() => { if (pc) setPrompt(pc.prompt); }, [pc && pc.id]);
    useCmds(ctx, pc ? [{ id: "redo", label: "Refaire l'image de " + pc.label, run: () => setRedo(true) }] : []);
    if (!pc) return h("div", { className: "task" }, h(Wait, null));
    const compose = () => ctx.act(async (snap) => {
      const r = await api.compose(pid, id);
      ctx.log(pid, "studio", "Pièce composée : " + pc.label, r.check.pass + " réussis, " + r.check.warn + " alertes, " + r.check.fail + " échecs");
      await ctx.answered(pid, "Pièce composée et vérifiée : " + r.check.pass + " contrôles réussis, " + plural(r.check.warn, "alerte", "alertes") + ".", { before: snap, prefer: (t) => t.piece === id, any: false });
    });
    const again = () => ctx.act(async (snap) => {
      await api.savePrompt(pid, id, prompt);
      await api.drawImage(pid, id);
      ctx.log(pid, "toi", "Image refaite pour " + pc.label, "Prompt : " + prompt);
      await ctx.answered(pid, "Nouvelle image lancée pour " + pc.label + ".", { before: snap, any: false, sibling: (t) => t.kind === "compose" && t.piece !== id });
    });
    return h("div", { className: "task" }, h(PieceHead, { pc }),
      h("div", { className: "pair" }, h(Frame, { src: pc.image, alt: "Image de " + pc.label, size: pc.size }),
      redo ? h("div", { className: "sec" },
        h("div", { className: "field" }, h("label", { htmlFor: "prompt" }, "Le prompt de l'image"), h("textarea", { id: "prompt", className: "mono", autoFocus: true, value: prompt, onChange: (e) => setPrompt(e.target.value) })),
        h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !prompt.trim(), onClick: again, "aria-label": "Refaire l'image avec ce prompt" }, "Refaire l'image"),
          h(Button, { variant: "ghost", size: "lg", onClick: () => setRedo(false), "aria-label": "Garder cette image" }, "Garder cette image")))
        : h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: compose, "aria-label": "Composer la pièce et la vérifier" }, "Composer et vérifier"),
          h(Button, { variant: "secondary", size: "lg", onClick: () => setRedo(true), "aria-label": "Refaire l'image de " + pc.label }, "Refaire l'image"))));
  }

  function Decide({ ctx, pid, id }) {
    const [pc] = usePiece(ctx, pid, id);
    const [notes, setNotes] = useState(false);
    const [back, setBack] = useState(false);
    const [words, setWords] = useState("");
    const send = (verdict) => ctx.act(async (snap) => {
      await api.decide(pid, id, verdict, words);
      ctx.log(pid, "toi", (verdict === "keep" ? "Gardée : " : "Renvoyée : ") + pc.label, words.trim() || "Sans commentaire");
      await ctx.answered(pid, verdict === "keep" ? pc.label + " : gardée." : pc.label + " : renvoyée, le studio retient « " + words.trim() + " ».",
        { before: snap, prefer: (t) => t.piece === id, any: false, sibling: verdict === "keep" ? (t) => t.kind === "decide" && t.piece !== id : undefined });
    });
    useCmds(ctx, pc ? [
      !pc.decision && { id: "keep", label: "Garder " + pc.label, run: () => send("keep") },
      { id: "back", label: "Renvoyer " + pc.label + " avec une raison", run: () => setBack(true) },
      { id: "notes", label: notes ? "Cacher les alertes" : "Voir les alertes de la vérification", run: () => setNotes(!notes) },
    ].filter(Boolean) : []);
    if (!pc) return h("div", { className: "task" }, h(Wait, null));
    const c = pc.check || { pass: 0, warn: 0, fail: 0, notes: [] };
    const alerts = c.notes.filter((n) => n.status !== "pass");
    const line = c.pass + " contrôles réussis" + (c.warn ? ", " + plural(c.warn, "alerte", "alertes") : "") + (c.fail ? ", " + plural(c.fail, "échec", "échecs") : "");
    return h("div", { className: "task" }, h(PieceHead, { pc }),
      h("div", { className: "pair" }, h(Frame, { src: pc.composed, alt: "Pièce composée : " + pc.label, size: pc.size }),
      h("div", { className: "side" },
      h("p", { className: "check" }, line, alerts.length > 0 && h(React.Fragment, null, " ",
        h("button", { type: "button", className: "linkbtn", "aria-expanded": notes, onClick: () => setNotes(!notes), "aria-label": notes ? "Cacher les alertes" : "Voir les " + plural(alerts.length, "alerte", "alertes") }, notes ? "Cacher" : "Voir les alertes"))),
      notes && h("ul", { className: "notes" }, alerts.map((n, i) => h("li", { key: i }, n.say))),
      pc.decision && h("p", { className: "small" }, h(Badge, { tone: "success" }, "Gardée"), " ", pc.decision.words || "Sans commentaire."),
      back ? h("div", { className: "sec" },
        h("div", { className: "field" }, h("label", { htmlFor: "words" }, "Qu'est-ce qui ne va pas ?"),
          h("textarea", { id: "words", autoFocus: true, value: words, onChange: (e) => setWords(e.target.value), "aria-describedby": "words-hint", placeholder: "Par exemple : trop sombre, le titre se lit mal" }),
          h("span", { id: "words-hint", className: "small muted" }, "La raison est obligatoire : le studio la retient pour le tour suivant.")),
        h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !words.trim(), onClick: () => send("again"), "aria-label": "Renvoyer la pièce avec cette raison" }, "Renvoyer"),
          h(Button, { variant: "ghost", size: "lg", onClick: () => setBack(false), "aria-label": "Ne pas renvoyer" }, "Annuler")))
        : h("div", { className: "gestures" },
          !pc.decision && h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: () => send("keep"), "aria-label": "Garder cette pièce" }, "Garder"),
          h(Button, { variant: pc.decision ? "primary" : "secondary", size: "lg", onClick: () => setBack(true), "aria-label": pc.decision ? "Revenir sur cette décision et renvoyer la pièce" : "Renvoyer la pièce en disant pourquoi" }, "Renvoyer")))));
  }

  /* a piece opened from the series, wherever it stands */
  function PieceAny({ ctx, pid, id }) {
    const [state, setState] = useState(null);
    useEffect(() => { Promise.all([api.piece(pid, id), api.project(pid)]).then(([pc, p]) => setState({ pc, st: stageOf(pc, p.jobs) })).catch(ctx.fail); }, [pid, id]);
    useCmds(ctx, []);
    if (!state) return h("div", { className: "task" }, h(Wait, null));
    const { pc, st } = state;
    if (st === "running") return h("div", { className: "task" }, h(PieceHead, { pc }), h("p", { className: "lead muted" }, "Le studio dessine l'image. Tu la retrouves dans ta liste quand elle est prête."));
    if (st === "prompt") return h(Prompt, { ctx, pid, id });
    if (st === "compose") return h(Compose, { ctx, pid, id });
    return h(Decide, { ctx, pid, id });
  }

  /* ================= the core: one thing, two gestures ================= */
  function Core({ ctx, t }) {
    const k = t.kind, key = t.id;
    if (t.scope === "brand") {
      return k === "brand-sort" ? h(BrandSort, { ctx, t, key }) : k === "brand-brief" ? h(BrandBrief, { ctx, t, key })
        : k === "brand-confirm" ? h(BrandConfirm, { ctx, t, key }) : h(JobFailed, { ctx, t, key });
    }
    const p = t.project;
    return k === "brief" ? h(Brief, { ctx, pid: p, key }) : k === "mandates" ? h(Mandates, { ctx, pid: p, key })
      : k === "diverge-launch" ? h(DivergeLaunch, { ctx, pid: p, key }) : k === "diverge-pick" ? h(DivergePick, { ctx, pid: p, readOnly: t.readOnly, key })
      : k === "job-failed" ? h(JobFailed, { ctx, t, key })
      : k === "piece-any" ? h(PieceAny, { ctx, pid: p, id: t.piece, key })
      : k === "prompt" ? h(Prompt, { ctx, pid: p, id: t.piece, key }) : k === "compose" ? h(Compose, { ctx, pid: p, id: t.piece, key }) : h(Decide, { ctx, pid: p, id: t.piece, key });
  }


  /* ================= the columns ================= */
  /* the live data of a column: fetched again when what it shows changes (`rev` moves each time the studio's list does) */
  function useLive(ctx, fn, id) {
    const [box, setBox] = useState({ id: null, v: null });
    useEffect(() => {
      let on = true;
      Promise.resolve(fn()).then((v) => { if (on) setBox({ id, v }); }).catch((e) => { if (on) ctx.fail(e); });
      return () => { on = false; };
    }, [id, ctx.rev]);
    return box.id === id ? box.v : null;
  }

  const Count = ({ n }) => n > 0 ? h("span", { className: "n", title: n + " en attente", "aria-hidden": "true" }, n) : null;
  const Plus = ({ label, onClick, disabled }) => h("button", { type: "button", className: "add", onClick, disabled, "aria-label": label, title: label }, "+");
  /* the seven segments of a project: done in teal, the one in progress in gold */
  const Segments = ({ rank, done }) => h("span", { className: "seg", "aria-hidden": "true" }, SEVEN.map((s, i) => h("i", { key: s.key, className: done || i < rank - 1 ? "done" : i === rank - 1 ? "now" : "" })));
  const Where = ({ children }) => h("div", { className: "groupe" }, children);

  /* a row of a list: the one shape of the columns. `select` rows open the next column; the others open a task */
  function Row({ col, sel, select, onClick, label, task, children }) {
    return h("button", { type: "button", className: "row", "data-col": col, "data-sel": sel || undefined, "data-select": select ? "1" : undefined, "data-task": task || undefined,
      "aria-current": sel ? "true" : undefined, "aria-label": label, onClick }, children, h("span", { className: "chev", "aria-hidden": "true" }, sel === "strong" ? "›" : ""));
  }

  function JobLine({ jobs }) {
    const t = studioLine(jobs);
    return t ? h("p", { className: "working", role: "status" }, h("b", { "aria-hidden": "true" }), t) : null;
  }

  function TaskRow({ ctx, col, t, place }) {
    const r = t.scope === "project" ? rankOf(t.step) : null;
    const when = (r ? "Étape " + r + " sur 7" : "") + (r && t.since ? " · " : "") + (t.since ? ago(t.since, ctx.now()) : "");
    const meta = place ? taskPlace(t) + (when ? " · " + when : "") : when || (t.scope === "brand" && t.since ? ago(t.since, ctx.now()) : "");
    return h(Row, { col, task: t.id, sel: ctx.sel.task === t.id ? "strong" : null, onClick: () => ctx.openTask(t, false, col),
      label: taskTitle(t) + (place ? ", " + taskPlace(t) : "") + (when ? ", " + when : "") },
      h("span", { className: "main" }, h("span", { className: "nom" }, taskTitle(t)), meta && h("span", { className: "meta" }, meta)));
  }

  /* ---------- 1. the studio: what waits everywhere, then the brands ---------- */
  function StudioCol({ ctx }) {
    const { tasks, brands, jobs, loaded } = ctx.data, { sel } = ctx;
    const level = ctx.level(0);
    const total = (b) => b.waiting + b.projects.reduce((n, p) => n + p.waiting, 0);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h("h2", { className: "sr" }, "Le studio")),
      h(Row, { col: 0, select: true, sel: !sel.brand && sel.panel !== "newBrand" ? level : null, onClick: ctx.selectStudio, label: "Tout le studio : " + plural(tasks.length, "chose t'attend", "choses t'attendent") },
        h("span", { className: "main" }, h("span", { className: "nom" }, "Le studio")), h(Count, { n: tasks.length })),
      h(JobLine, { jobs }),
      h(Where, null, "Ce qui t'attend"),
      !loaded ? h("p", { className: "vide" }, "Un instant.") : tasks.length === 0 ? h("p", { className: "vide" }, jobs.length ? "Rien pour l'instant : le studio travaille." : "Rien ne t'attend.")
        : tasks.map((t) => h(TaskRow, { key: t.id, ctx, col: 0, t, place: true })),
      h("div", { className: "groupe split" }, h("span", null, "Marques"), h(Plus, { label: "Nouvelle marque", onClick: ctx.newBrand })),
      loaded && brands.length === 0 && h("p", { className: "vide" }, "Aucune marque. Le « + » en crée une."),
      brands.map((b) => h(Row, { key: b.id, col: 0, select: true, sel: sel.brand === b.id ? level : null, onClick: () => ctx.selectBrand(b.id),
        label: b.name + ", " + (BRAND_STAGE[b.stage] || b.stage).toLowerCase() + (total(b) ? ", " + plural(total(b), "tâche", "tâches") : "") },
        h("span", { className: "main" }, h("span", { className: "nom" }, b.name), h("span", { className: "meta" }, BRAND_STAGE[b.stage] || b.stage)), h(Count, { n: total(b) }))));
  }

  /* ---------- 2. a brand: its brief, its assets, its projects ---------- */
  const BRIEF_BITS = [["what", ", c'est "], ["who", ". Elle parle à "], ["voice", ". Sa voix : "], ["signature", ". Sa signature : « ", " »"], ["never", ". Elle ne dit jamais : "], ["colours", ". Ses couleurs : "]];

  function BrandCol({ ctx, bid }) {
    const b = useLive(ctx, () => api.getBrand(bid), bid);
    const jobs = ctx.data.jobs.filter((j) => j.brand === bid && !j.project);
    const level = ctx.level(1);
    if (!b) return h("div", { className: "colhead" }, h(Eyebrow, null, "Marque"), h("p", { className: "vide" }, "Un instant."));
    const a = b.assets, id = b.identity;
    const known = BRIEF_BITS.filter(([k]) => id[k].state !== "absent");
    const logo = a.logo;
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, "Marque"), h("h2", { className: "titre" }, b.name),
        h("p", { className: "sub" }, (BRAND_STAGE[b.stage] || b.stage) + " · " + (b.site ? host(b.site) : "sans site")),
        h("button", { type: "button", className: "linkbtn modif", onClick: ctx.editBrand, "aria-label": "Modifier la marque " + b.name + " : nom, site, description" }, "Modifier")),
      h(JobLine, { jobs }),
      b.description && h("p", { className: "desc" }, b.description),
      b.waiting.length > 0 && h(React.Fragment, null, h(Where, null, "Ce qui attend"), b.waiting.map((t) => h(TaskRow, { key: t.id, ctx, col: 1, t, place: false }))),
      h("div", { className: "groupe split" }, h("span", null, "Projets"), h(Plus, { label: "Nouveau projet dans " + b.name, onClick: ctx.newProject })),
      b.projects.length === 0 && h("p", { className: "vide" }, "Aucun projet. Le « + » en crée un."),
      b.projects.map((p) => h(Row, { key: p.id, col: 1, select: true, sel: ctx.sel.project === p.id ? level : null, onClick: () => ctx.selectProject(p.id),
        label: p.name + ", " + (p.done ? "terminé" : "étape " + p.rank + " sur 7, " + p.step_label.toLowerCase()) + (p.waiting ? ", " + plural(p.waiting, "tâche", "tâches") : "") },
        h("span", { className: "main" }, h("span", { className: "nom" }, p.name), h("span", { className: "meta" }, p.done ? "Terminé" : "Étape " + p.rank + " sur 7 · " + p.step_label), h(Segments, { rank: p.rank, done: p.done })),
        h(Count, { n: p.waiting }))),
      h(Where, null, "Son brief"),
      known.length === 0 ? h("p", { className: "vide" }, "Pas encore de brief : il se fait en une phrase.")
        : h("p", { className: "bphrase" }, b.name, BRIEF_BITS.map(([k, before, after]) => id[k].state === "absent" ? null :
          h(React.Fragment, { key: k }, before, h("span", { className: "v", "data-state": id[k].state, title: id[k].state === "deduced" ? "Déduit par le studio, à confirmer" : undefined }, id[k].value,
            id[k].state === "deduced" && h("span", { className: "sr" }, " (à confirmer)")), after || "")), "."),
      h(Where, null, "Ses assets"),
      h("div", { className: "assets" },
        h("div", { className: "asset" }, h("span", { className: "cap" }, "Logo"),
          logo ? h("div", { className: "logobox" }, h("img", { src: logo.preview, alt: "Logo de " + b.name }), h("span", { className: "small muted" }, logo.state === "deduced" ? "à confirmer" : "confirmé"))
            : h("p", { className: "small muted" }, "Pas de logo : sans lui, la marque ne peut pas être prête."),
          h("div", null, h(LogoDrop, { ctx, bid, label: logo ? "Changer de logo" : "Déposer un logo", variant: logo ? "ghost" : "secondary", onDone: (r) => ctx.notify("Logo déposé : " + r.name + " a un logo.") }))),
        h("div", { className: "asset" }, h("span", { className: "cap" }, "Couleurs"), a.colours.length ? h(Swatches, { colours: a.colours, mini: true }) : h("p", { className: "small muted" }, "Pas encore de couleur."),
          a.colours.some((c) => c.state === "deduced") && h("span", { className: "small muted" }, "à confirmer")),
        h("div", { className: "asset" }, h("span", { className: "cap" }, "Visuels gardés" + (a.visuals.length ? " · " + a.visuals.length : "")),
          a.visuals.length ? h("ul", { className: "thumbs", "aria-label": "Visuels gardés" }, a.visuals.map((v) => h("li", { key: v.id }, h("img", { src: v.preview, alt: v.note, title: v.note }))))
            : h("p", { className: "small muted" }, b.can_discover ? "Aucun pour l'instant." : "Aucun : la marque n'a pas de site à lire."))));
  }

  /* ---------- 3. a project: its seven steps, what waits ---------- */
  function ProjectCol({ ctx, pid }) {
    const p = useLive(ctx, () => api.project(pid), pid);
    const { sel } = ctx;
    const level = ctx.level(2);
    if (!p) return h("div", { className: "colhead" }, h(Eyebrow, null, "Projet"), h("p", { className: "vide" }, "Un instant."));
    const st = (k) => (p.steps.find((s) => s.key === k) || {}).status || "todo";
    const done = SEVEN.filter((s) => st(s.key) === "done").length;
    const nowIdx = SEVEN.findIndex((s) => st(s.key) !== "done");
    const tasks = ctx.data.tasks.filter((t) => t.scope === "project" && t.project === pid);
    const brandTask = ctx.data.tasks.find((t) => t.scope === "brand" && t.brand === p.brand);
    const jobs = ctx.data.jobs.filter((j) => j.project === pid);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, "Projet"), h("h2", { className: "titre" }, p.name),
        h("p", { className: "sub" }, done === 7 ? "Terminé" : "Étape " + (nowIdx + 1) + " sur 7 · " + SEVEN[nowIdx].label),
        h("button", { type: "button", className: "linkbtn modif", onClick: ctx.editProject, "aria-label": "Modifier le projet " + p.name + " : son nom" }, "Modifier")),
      h(JobLine, { jobs }),
      h("ol", { className: "etapes", "aria-label": "Les sept étapes" }, SEVEN.map((s, i) => {
        const status = st(s.key), cur = i === nowIdx;
        const word = STEP_WORD[status];
        const inner = [h("i", { key: "d", "aria-hidden": "true" }), h("span", { key: "t", className: "t" }, s.label), h("span", { key: "m", className: cur ? "m" : "sr" }, cur ? word : " : " + word)];
        const open = status === "done" ? () => ctx.selectStep(s.key) : s.key === "brand" && brandTask ? () => ctx.openTask(brandTask) : null;
        const selected = sel.detail && sel.detail.kind === "step" && sel.detail.key === s.key;
        return h("li", { key: s.key, "data-etat": status, "data-cur": cur ? "1" : undefined, "aria-current": cur ? "step" : undefined },
          open ? h("button", { type: "button", className: "etape", "data-col": 2, "data-select": status === "done" ? "1" : undefined, "data-sel": selected ? level : undefined, "aria-current": selected ? "true" : undefined,
            onClick: open, "aria-label": (i + 1) + ". " + s.label + " : " + word + (status === "done" ? ". Voir ce qui a été décidé" : ". Ouvrir la tâche de la marque") }, inner)
            : h("div", { className: "etape" }, inner));
      })),
      p.brand_stage !== "ready" && h("p", { className: "vide" }, "Le projet attend sa marque" + (p.brand_waiting.length ? " : " + p.brand_waiting.map((x) => taskTitle({ scope: "brand", brand_name: p.brand_name, title: x.title }).toLowerCase()).join(", ") : "") + "."),
      h(Where, null, "Ce qui attend"),
      tasks.length ? tasks.map((t) => h(TaskRow, { key: t.id, ctx, col: 2, t, place: false })) : h("p", { className: "vide" }, done === 7 ? "Rien : le projet est terminé." : "Rien n'attend sur ce projet."));
  }

  /* ---------- 4. the detail of a step already done: what was decided, and a way to reopen it ---------- */
  const synth = (p, k, extra) => ({ id: p.id + ":reopen:" + k + ((extra && extra.piece) || ""), scope: "project", project: p.id, project_name: p.name, brand: p.brand, brand_name: p.brand_name, kind: k, step: null, piece: null, title: "", ...extra });

  function StepDetail({ ctx, pid, step }) {
    const key = pid + "|" + step;
    const p = useLive(ctx, () => api.project(pid), pid + "|p");
    const body = useLive(ctx, () => {
      if (step === "brand") return api.getBrand(ctx.sel.brand);
      if (step === "brief") return api.brief(pid);
      if (step === "mandates") return api.mandates(pid);
      if (step === "diverge") return api.variants(pid);
      return Promise.resolve({});
    }, key);
    const label = (SEVEN.find((s) => s.key === step) || {}).label || "";
    if (!p || !body) return h("div", { className: "colhead" }, h(Eyebrow, null, "Décidé"), h("p", { className: "vide" }, "Un instant."));
    const reopen = (k, extra) => ctx.openTask(synth(p, k, extra));
    let main, action;
    if (step === "brand") {
      const logo = body.assets.logo;
      main = h("div", { className: "sec" }, h("p", { className: "lead" }, "La marque est prête : " + body.name + (logo ? ", avec son logo." : ".")),
        logo && h("img", { src: logo.preview, alt: "Logo de " + body.name, className: "factlogo" }), body.assets.colours.length > 0 && h(Swatches, { colours: body.assets.colours, mini: true }));
      const bt = (k, title) => ({ id: "@" + body.id + ":reopen:" + k, scope: "brand", brand: body.id, brand_name: body.name, project: null, kind: k, title, reopen: true });
      action = h("div", { className: "gestures" },
        h(Button, { variant: "secondary", size: "sm", onClick: () => ctx.openTask(bt("brand-brief", "Relire le brief de la marque")), "aria-label": "Rouvrir le brief de la marque" }, "Rouvrir le brief"),
        body.assets.evidence.length > 0 && h(Button, { variant: "ghost", size: "sm", onClick: () => ctx.openTask(bt("brand-sort", "Revoir le tri des visuels")), "aria-label": "Rouvrir le tri des visuels de la marque" }, "Rouvrir le tri"));
    } else if (step === "brief") {
      const f = body.fields;
      main = h("p", { className: "sentence small" }, "Je veux " + (f.objective || "…") + ". Pour " + (f.audience || "…") + ". Le message : " + (f.message || "…") + ". Sur " + body.chosen.map(fmtWord).join(", ") + (f.cta ? ". Pour finir : « " + f.cta + " »" : "") + ".");
      action = h(Button, { variant: "secondary", size: "sm", onClick: () => reopen("brief"), "aria-label": "Rouvrir le brief du projet" }, "Rouvrir");
    } else if (step === "mandates") {
      main = h("div", { className: "sec" }, h("p", { className: "lead" }, body.common), h("ul", { className: "plain" }, body.items.map((it) => h("li", { key: it.id }, h("span", { className: "cap" }, "Agent " + it.id.toUpperCase()), h("span", null, it.mandate)))));
      action = h(Button, { variant: "secondary", size: "sm", onClick: () => reopen("mandates"), "aria-label": "Rouvrir les consignes aux agents" }, "Rouvrir");
    } else if (step === "diverge") {
      const inSeries = new Set(p.pieces.map((x) => x.variant));
      main = h("ul", { className: "plain" }, body.map((v) => h("li", { key: v.id }, h("span", { className: "cap" }, v.mandate + (inSeries.has(v.id) ? " · dans la série" : "")), h("span", { className: "hl" }, v.headline), v.subline && h("span", null, v.subline))));
      action = h(Button, { variant: "secondary", size: "sm", onClick: () => reopen("diverge-pick", { readOnly: true }), "aria-label": "Rouvrir les variantes de la série" }, "Rouvrir");
    } else {
      main = p.pieces.length === 0 ? h("p", { className: "vide" }, "Pas de pièce.") : h("ul", { className: "pieces", "aria-label": "Les pièces" }, p.pieces.map((pc) => { const w = STAGE_WORDS[stageOf(pc, p.jobs)];
        return h("li", { key: pc.id }, h("button", { type: "button", className: "row", "data-col": 3, onClick: () => reopen("piece-any", { piece: pc.id, title: pc.label }), "aria-label": "Rouvrir " + pc.label + " : " + w.toLowerCase() },
          h("span", { className: "main" }, h("span", { className: "nom" }, pc.label), h("span", { className: "meta" }, w)))); }));
      action = null;
    }
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, "Décidé"), h("h2", { className: "titre" }, label), h("p", { className: "sub" }, "Étape faite. Ce qui a été décidé, tel quel.")),
      h("div", { className: "bodyc" }, main, action));
  }

  function JournalCol({ ctx, pid }) {
    const list = useMemo(() => loadJournal(pid), [pid, ctx.rev]);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, "Projet"), h("h2", { className: "titre" }, "Le journal des décisions")),
      list.length === 0 ? h("p", { className: "vide" }, "Chaque décision s'écrit ici avec son heure et sa raison.") :
        h("ol", { className: "journal" }, list.slice(0, 60).map((e, i) => h("li", { key: e.at + "-" + i },
          h("time", { dateTime: new Date(e.at).toISOString() }, clock(e.at)), h("span", null, h("strong", null, e.who === "toi" ? "Toi : " : "Studio : "), e.text), e.why && h("span", { className: "why" }, e.why)))));
  }

  /* ---------- the "+" and "Modifier" forms, in the column to the right of the one that holds them ---------- */
  function NewBrandForm({ ctx }) {
    const [name, setName] = useState(""), [site, setSite] = useState("");
    const create = (e) => {
      e.preventDefault();
      ctx.act(async () => {
        const b = await api.createBrand(name.trim(), site.trim() || undefined);
        ctx.log("@" + b.id, "toi", "Marque créée : " + b.name, b.site ? "Le studio lit " + host(b.site) : "Sans site");
        await ctx.refresh(); ctx.touch();
        ctx.selectBrand(b.id, b.site ? b.name + " est créée : le studio lit son site." : b.name + " est créée. Son brief l'attend.");
      });
    };
    return h(React.Fragment, null, h("div", { className: "colhead" }, h(Eyebrow, null, "Studio"), h("h2", { className: "titre" }, "Nouvelle marque")),
      h("form", { className: "sec form", onSubmit: create },
        h("div", { className: "field" }, h("label", { htmlFor: "nb-name" }, "Nom de la marque"), h("input", { id: "nb-name", type: "text", autoFocus: true, value: name, onChange: (e) => setName(e.target.value), autoComplete: "off" })),
        h("div", { className: "field" }, h("label", { htmlFor: "nb-site" }, "Son site (facultatif)"), h("input", { id: "nb-site", type: "text", inputMode: "url", value: site, onChange: (e) => setSite(e.target.value), autoComplete: "off", placeholder: "ma-marque.example", "aria-describedby": "nb-hint" }),
          h("span", { id: "nb-hint", className: "small muted" }, "Un site lance la lecture : le studio y cherche les visuels, le logo, les couleurs. Sans site, tu écris son brief et tu déposes son logo.")),
        h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "md", disabled: ctx.busy || !name.trim(), "aria-label": "Créer la marque" }, "Créer la marque"),
          h(Button, { type: "button", variant: "ghost", size: "md", onClick: ctx.close, "aria-label": "Ne pas créer de marque" }, "Annuler"))));
  }

  function EditBrandForm({ ctx, bid }) {
    const b = useLive(ctx, () => api.getBrand(bid), "edit|" + bid);
    const [f, setF] = useState(null);
    useEffect(() => { if (b && !f) setF({ name: b.name, site: b.site ? host(b.site) : "", description: b.description || "" }); }, [b]);
    if (!b || !f) return h("div", { className: "colhead" }, h("p", { className: "vide" }, "Un instant."));
    const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
    const save = (e) => {
      e.preventDefault();
      ctx.act(async () => {
        const siteChanged = (f.site.trim() ? host(f.site.trim()) : "") !== (b.site ? host(b.site) : "");
        await api.updateBrand(bid, { name: f.name.trim(), site: f.site.trim(), description: f.description });
        ctx.log("@" + bid, "toi", "Marque modifiée : " + f.name.trim(), "");
        await ctx.refresh(); ctx.touch();
        ctx.close(f.name.trim() + " est enregistrée." + (siteChanged && f.site.trim() ? " Le nouveau site n'est pas lu : « Relire le site » le fait." : ""));
      });
    };
    const reread = () => ctx.act(async () => { await api.discover(bid); await ctx.refresh(); ctx.touch(); ctx.close("Le studio relit le site de " + b.name + "."); });
    return h(React.Fragment, null, h("div", { className: "colhead" }, h(Eyebrow, null, "Marque"), h("h2", { className: "titre" }, "Modifier " + b.name)),
      h("form", { className: "sec form", onSubmit: save },
        h("div", { className: "field" }, h("label", { htmlFor: "eb-name" }, "Nom"), h("input", { id: "eb-name", type: "text", autoFocus: true, value: f.name, onChange: set("name"), autoComplete: "off" })),
        h("div", { className: "field" }, h("label", { htmlFor: "eb-site" }, "Site"), h("input", { id: "eb-site", type: "text", inputMode: "url", value: f.site, onChange: set("site"), autoComplete: "off", placeholder: "ma-marque.example" })),
        h("div", { className: "field" }, h("label", { htmlFor: "eb-desc" }, "Description"), h("textarea", { id: "eb-desc", value: f.description, onChange: set("description") })),
        h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "md", disabled: ctx.busy || !f.name.trim(), "aria-label": "Enregistrer la marque" }, "Enregistrer"),
          h(Button, { type: "button", variant: "ghost", size: "md", onClick: () => ctx.close(), "aria-label": "Fermer sans enregistrer" }, "Annuler")),
        b.can_discover && h("p", { className: "small muted" }, "Le site enregistré se relit à part : ", h("button", { type: "button", className: "linkbtn", disabled: ctx.busy, onClick: reread, "aria-label": "Relire le site de la marque" }, "Relire le site"), ".")));
  }

  function NewProjectForm({ ctx, bid }) {
    const b = useLive(ctx, () => api.getBrand(bid), "np|" + bid);
    const [name, setName] = useState(""), [from, setFrom] = useState("");
    if (!b) return h("div", { className: "colhead" }, h("p", { className: "vide" }, "Un instant."));
    const create = (e) => {
      e.preventDefault();
      ctx.act(async () => {
        const p = await api.createProjectIn(bid, name.trim(), from || undefined);
        ctx.log(p.id, "toi", from ? "Déclinaison créée : " + p.name : "Projet créé : " + p.name, from ? "Reprend le brief de l'original" : "");
        await ctx.refresh(); ctx.touch();
        ctx.selectProject(p.id, "Projet créé : " + p.name + (p.brand_stage !== "ready" ? ". Il attend sa marque." : "."), bid);
      });
    };
    return h(React.Fragment, null, h("div", { className: "colhead" }, h(Eyebrow, null, b.name), h("h2", { className: "titre" }, "Nouveau projet")),
      h("form", { className: "sec form", onSubmit: create },
        h("div", { className: "field" }, h("label", { htmlFor: "np-name" }, "Nom du projet"), h("input", { id: "np-name", type: "text", autoFocus: true, value: name, onChange: (e) => setName(e.target.value), autoComplete: "off", placeholder: "Par exemple : la campagne de rentrée" })),
        b.projects.length > 0 && h("div", { className: "field" }, h("label", { htmlFor: "np-from" }, "Partir d'un projet existant"),
          h("select", { id: "np-from", value: from, onChange: (e) => setFrom(e.target.value), "aria-describedby": "np-hint" }, h("option", { value: "" }, "Non, on part de zéro"), b.projects.map((p) => h("option", { key: p.id, value: p.id }, p.name))),
          h("span", { id: "np-hint", className: "small muted" }, "Une déclinaison reprend le brief de l'original : tu ne corriges que ce qui change.")),
        h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "md", disabled: ctx.busy || !name.trim(), "aria-label": from ? "Créer la déclinaison" : "Créer le projet" }, from ? "Créer la déclinaison" : "Créer le projet"),
          h(Button, { type: "button", variant: "ghost", size: "md", onClick: () => ctx.close(), "aria-label": "Ne pas créer de projet" }, "Annuler"))));
  }

  function EditProjectForm({ ctx, pid }) {
    const p = useLive(ctx, () => api.project(pid), "ep|" + pid);
    const [name, setName] = useState(null);
    useEffect(() => { if (p && name === null) setName(p.name); }, [p]);
    if (!p || name === null) return h("div", { className: "colhead" }, h("p", { className: "vide" }, "Un instant."));
    const save = (e) => {
      e.preventDefault();
      ctx.act(async () => { await api.updateProject(pid, { name: name.trim() }); ctx.log(pid, "toi", "Projet renommé : " + name.trim(), ""); await ctx.refresh(); ctx.touch(); ctx.closeDetail(name.trim() + " est enregistré."); });
    };
    return h(React.Fragment, null, h("div", { className: "colhead" }, h(Eyebrow, null, "Projet"), h("h2", { className: "titre" }, "Modifier " + p.name)),
      h("form", { className: "sec form", onSubmit: save },
        h("div", { className: "field" }, h("label", { htmlFor: "ep-name" }, "Nom du projet"), h("input", { id: "ep-name", type: "text", autoFocus: true, value: name, onChange: (e) => setName(e.target.value), autoComplete: "off" })),
        h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "md", disabled: ctx.busy || !name.trim(), "aria-label": "Enregistrer le projet" }, "Enregistrer"),
          h(Button, { type: "button", variant: "ghost", size: "md", onClick: () => ctx.closeDetail(), "aria-label": "Fermer sans enregistrer" }, "Annuler"))));
  }

  /* ================= the palette and the menu ================= */
  function matches(c, q) {
    const words = norm(q).split(/\s+/).filter(Boolean);
    const hay = norm(c.label + " " + (c.hint || "") + " " + (c.group || ""));
    return words.every((w) => hay.includes(w));
  }
  function groups(list) {
    const out = [];
    list.forEach((c) => { let g = out.find((x) => x.name === c.group); if (!g) { g = { name: c.group, items: [] }; out.push(g); } g.items.push(c); });
    return out;
  }

  function Palette({ cmds, onClose }) {
    const [q, setQ] = useState("");
    const [i, setI] = useState(0);
    const input = useRef(null), listRef = useRef(null);
    const prev = useRef(document.activeElement);
    useEffect(() => { input.current.focus(); return () => { const p = prev.current; if (p && p.isConnected && p.focus) p.focus(); }; }, []);
    const items = cmds.filter((c) => matches(c, q));
    const at = Math.min(i, Math.max(0, items.length - 1));
    useEffect(() => { const el = listRef.current && listRef.current.querySelector('[aria-selected="true"]'); if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" }); }, [at, q]);
    const run = (c) => { onClose(); c.run(); };
    const key = (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); setI((at + 1) % Math.max(1, items.length)); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); setI((at - 1 + items.length) % Math.max(1, items.length)); }
      else if (ev.key === "Enter") { ev.preventDefault(); if (items[at]) run(items[at]); }
      else if (ev.key === "Escape") { ev.preventDefault(); onClose(); }
      else if (ev.key === "Tab") { ev.preventDefault(); }
    };
    let idx = -1;
    return h("div", { className: "scrim", onMouseDown: (e) => { if (e.target === e.currentTarget) onClose(); } },
      h("div", { className: "palette", role: "dialog", "aria-modal": "true", "aria-label": "Palette de commandes", onKeyDown: key },
        h("input", { ref: input, type: "text", className: "pal-input", role: "combobox", "aria-expanded": "true", "aria-controls": "pal-list", "aria-autocomplete": "list", "aria-label": "Que veux-tu faire ?",
          "aria-activedescendant": items[at] ? "pal-" + at : undefined, placeholder: "Que veux-tu faire ?", value: q, autoComplete: "off", onChange: (e) => { setQ(e.target.value); setI(0); } }),
        h("div", { id: "pal-list", ref: listRef, className: "pal-list", role: "listbox", "aria-label": "Commandes" },
          items.length === 0 && h("p", { className: "pal-none" }, "Aucune commande ne correspond."),
          groups(items).map((g) => h("div", { key: g.name, role: "group", "aria-label": g.name },
            h("p", { className: "pal-group", "aria-hidden": "true" }, g.name),
            g.items.map((c) => { idx += 1; const my = idx; return h("div", { key: c.id, id: "pal-" + my, role: "option", "aria-selected": my === at, className: "pal-item", onMouseMove: () => setI(my), onClick: () => run(c) },
              h("span", null, c.label), c.hint && h("span", { className: "pal-hint" }, c.hint)); })))),
        h("p", { className: "pal-foot" }, "Flèches pour choisir, Entrée pour lancer, Échap pour fermer.")));
  }

  /* ================= the application ================= */
  /* what each column is, from left to right, for a selection: the studio always, then a brand (or the form of a new one), a project (or the
     form that edits or creates), the detail of a step (or its form) */
  const EMPTY = { brand: null, project: null, detail: null, panel: null, task: null };
  function columnsOf(sel) {
    const c = ["studio"];
    if (sel.panel === "newBrand") { c.push("newBrand"); return c; }
    if (!sel.brand) return c;
    c.push("brand");
    if (sel.panel === "editBrand") { c.push("editBrand"); return c; }
    if (sel.panel === "newProject") { c.push("newProject"); return c; }
    if (!sel.project) return c;
    c.push("project");
    if (sel.detail) c.push(sel.detail.kind);
    return c;
  }
  const popOnce = (sel) => sel.detail ? { ...sel, detail: null, task: null } : sel.panel ? { ...sel, panel: null } : sel.project ? { ...sel, project: null, task: null } : sel.brand ? { ...sel, brand: null, task: null } : sel;

  function useNarrow() {
    const q = "(max-width: 760px)";
    const [n, setN] = useState(() => window.matchMedia(q).matches);
    useEffect(() => { const m = window.matchMedia(q); const f = () => setN(m.matches); m.addEventListener("change", f); return () => m.removeEventListener("change", f); }, []);
    return n;
  }

  function App() {
    const [data, setData] = useState({ tasks: [], jobs: [], projects: [], brands: [], now: 0, loaded: false });
    const [sel, setSel] = useState(EMPTY);
    const [dive, setDive] = useState(null); // the task opened, or null
    const [notice, setNotice] = useState(null);
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(false);
    const [palette, setPalette] = useState(false);
    const [rev, setRev] = useState(0);
    const [, setTick] = useState(0);
    const narrow = useNarrow();
    const tasksRef = useRef([]), skew = useRef(0), prevJobs = useRef([]), digest = useRef(""), cmdsRef = useRef([]), overlayRef = useRef(false), arrowsRef = useRef(false), backTo = useRef(null);
    const selRef = useRef(sel), diveRef = useRef(dive), opened = useRef(0);
    overlayRef.current = palette;
    selRef.current = sel; diveRef.current = dive;

    const log = useCallback((p, who, text, why) => {
      if (!p) return;
      saveJournal(p, [{ at: Date.now(), who, text, why: why || "" }, ...loadJournal(p)]);
    }, []);
    const fail = useCallback((e) => setError(e && e.message ? e.message : String(e)), []);

    const refresh = useCallback(async () => {
      try {
        const r = await api.tasks();
        skew.current = r.now * 1000 - Date.now();
        const STEP_OF = { learn: "brand", mandates: "mandates", diverge: "diverge", image: "image" };
        prevJobs.current.filter((j) => !r.jobs.some((x) => x.id === j.id)).forEach((j) => {
          const failed = r.tasks.find((t) => t.kind === "job-failed" && (j.project ? t.project === j.project && t.step === STEP_OF[j.kind] && (t.piece || null) === (j.piece || null) : t.scope === "brand" && t.brand === j.brand));
          const where = j.project || "@" + j.brand;
          if (failed) log(where, "studio", "Échec : " + taskTitle(failed), failed.question);
          else log(where, "studio", j.kind === "learn" ? "Lecture du site terminée" : j.kind === "mandates" ? "Les consignes sont proposées" : j.kind === "diverge" ? "Les quatre variantes sont écrites" : "Image prête : " + j.piece, "");
        });
        prevJobs.current = r.jobs;
        tasksRef.current = r.tasks;
        const d = JSON.stringify({ ...r, now: 0 });
        if (d !== digest.current) { digest.current = d; setRev((x) => x + 1); }
        setData({ ...r, loaded: true });
        return r;
      } catch (e) { setError("Le serveur du studio ne répond pas."); return null; }
    }, [log]);
    useEffect(() => { refresh(); }, []);
    const running = data.jobs.length > 0;
    useEffect(() => { const t = setInterval(refresh, running ? 700 : 4000); return () => clearInterval(t); }, [refresh, running]);
    useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 20000); return () => clearInterval(t); }, []);

    /* ----- moving about the columns ----- */
    const move = useCallback((fn, text) => { setSel(fn); setNotice(text || null); setError(null); setDive(null); }, []);
    const selectStudio = useCallback(() => move(() => EMPTY), [move]);
    const selectBrand = useCallback((id, text) => move(() => ({ ...EMPTY, brand: id }), text), [move]);
    const selectProject = useCallback((id, text, brand) => move((s) => ({ ...EMPTY, brand: brand || s.brand, project: id }), text), [move]);
    const selectStep = useCallback((key) => move((s) => ({ ...s, detail: { kind: "step", key }, panel: null, task: null })), [move]);
    const newBrand = useCallback(() => move(() => ({ ...EMPTY, panel: "newBrand" })), [move]);
    const editBrand = useCallback(() => move((s) => ({ ...s, project: null, detail: null, panel: "editBrand", task: null })), [move]);
    const newProject = useCallback(() => move((s) => ({ ...s, project: null, detail: null, panel: "newProject", task: null })), [move]);
    const editProject = useCallback(() => move((s) => ({ ...s, detail: { kind: "editProject" }, task: null })), [move]);
    const showJournal = useCallback(() => move((s) => ({ ...s, detail: { kind: "journal" }, task: null })), [move]);
    const close = useCallback((text) => move((s) => ({ ...s, panel: null }), typeof text === "string" ? text : null), [move]);
    const closeDetail = useCallback((text) => move((s) => ({ ...s, detail: null }), typeof text === "string" ? text : null), [move]);
    const popTo = useCallback((n) => { setNotice(null); setSel((s) => { let x = s; while (columnsOf(x).length > n) { const y = popOnce(x); if (y === x) break; x = y; } return x; }); }, []);

    /* ----- diving into a task, and coming back ----- */
    const openTask = useCallback((t, keepNotice, col) => {
      if (!keepNotice) setNotice(null);
      setError(null);
      backTo.current = { id: t.id, col };
      setSel((s) => ({ ...EMPTY, brand: t.brand || s.brand, project: t.project || null, task: t.id }));
      setDive({ ...t, _k: ++opened.current }); // a new key each time: the same task opened again (a sibling that keeps its id) starts afresh
      window.scrollTo(0, 0);
    }, []);
    const back = useCallback(() => setDive(null), []);

    /* an action runs under `busy`; `snap` is the set of tasks before it, to know which ones are new afterwards */
    const snap = useCallback(() => new Set(tasksRef.current.map((t) => t.id)), []);
    const act = useCallback(async (fn) => {
      setBusy(true); setError(null);
      const s = snap();
      try { return await fn(s); } catch (e) { fail(e); } finally { setBusy(false); }
    }, [fail, snap]);

    /* an answer settles a task: on to the next one of the same owner if it follows, else back to the columns, with one line that says what was done.
       `who` is a project id, or `@<brand>` */
    const answered = useCallback(async (who, text, o = {}) => {
      const before = o.before || snap();
      const r = await refresh();
      const isBrand = who[0] === "@", key = isBrand ? who.slice(1) : who;
      const mine = r ? r.tasks.filter((t) => (isBrand ? t.scope === "brand" && t.brand === key : t.scope === "project" && t.project === key)) : [];
      const isNew = (t) => !before.has(t.id);
      const next = (o.prefer && mine.find((t) => isNew(t) && o.prefer(t))) || (o.any !== false && mine.find(isNew)) || (o.sibling && mine.find(o.sibling)) || null;
      setNotice(text);
      if (next) openTask(next, true); else { setSel((s) => ({ ...s, task: null })); setDive(null); }
    }, [refresh, openTask, snap]);

    const now = () => Date.now() + skew.current;
    const touch = useCallback(() => setRev((x) => x + 1), []);
    const notify = useCallback((text) => setNotice(text), []);
    const cols = columnsOf(sel);
    const level = (i) => (i === cols.length - 1 ? "strong" : "soft");
    const ctx = { data, sel, busy, act, answered, snap, log, fail, openTask, now, cmdsRef, overlayRef, arrowsRef, rev, touch, notify, refresh, level, close, closeDetail,
      selectStudio, selectBrand, selectProject, selectStep, newBrand, editBrand, newProject, editProject };

    const brandName = (id) => (data.brands.find((b) => b.id === id) || {}).name || "";
    const projectInfo = (id) => data.projects.find((p) => p.id === id) || { name: "" };

    /* ----- the commands of the palette ----- */
    const cmds = [];
    if (palette) {
      (cmdsRef.current || []).forEach((c) => cmds.push({ ...c, group: "Cette tâche" }));
      if (dive) cmds.push({ id: "cols", group: "Aller", label: "Revenir aux colonnes", hint: "Échap", run: back });
      cmds.push({ id: "studio", group: "Aller", label: "Le studio", run: selectStudio });
      data.tasks.forEach((t) => cmds.push({ id: "task:" + t.id, group: "Ouvrir une tâche", label: taskTitle(t), hint: taskPlace(t), run: () => openTask(t) }));
      data.brands.forEach((b) => cmds.push({ id: "brand:" + b.id, group: "Aller à une marque", label: b.name, run: () => selectBrand(b.id) }));
      data.brands.forEach((b) => b.projects.forEach((p) => cmds.push({ id: "project:" + p.id, group: "Aller à un projet", label: p.name, hint: b.name, run: () => selectProject(p.id, null, b.id) })));
      cmds.push({ id: "new-brand", group: "Créer", label: "Nouvelle marque", run: newBrand });
      const here = sel.brand || (dive && dive.brand);
      data.brands.slice().sort((a, b) => (b.id === here) - (a.id === here)).forEach((b) => cmds.push({ id: "new-project:" + b.id, group: "Créer", label: "Nouveau projet dans " + b.name, run: () => move(() => ({ ...EMPTY, brand: b.id, panel: "newProject" })) }));
      if (sel.brand && sel.project) {
        cmds.push({ id: "journal", group: "Ce projet", label: "Voir le journal des décisions", run: showJournal });
        cmds.push({ id: "edit-project", group: "Ce projet", label: "Modifier le projet", run: editProject });
      }
      if (sel.brand) cmds.push({ id: "edit-brand", group: "Cette marque", label: "Modifier la marque", run: editBrand });
    }

    /* the palette key, wherever the focus is */
    useEffect(() => {
      const f = (ev) => { if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") { ev.preventDefault(); setPalette((v) => !v); } };
      window.addEventListener("keydown", f);
      return () => window.removeEventListener("keydown", f);
    }, []);

    /* ----- the keyboard: up and down in a column, right to go deeper, left or Escape to come back ----- */
    const focusIn = useCallback((col, last, label) => {
      const go = (n) => {
        const c = document.querySelector('.col[data-col="' + col + '"]');
        const rows = c ? [...c.querySelectorAll("button[data-col]")] : [];
        const el = last ? rows.find((r) => label ? r.getAttribute("aria-label") === label : r.getAttribute("aria-current") === "true") || rows.find((r) => r.getAttribute("aria-current") === "true") || rows[0] : rows[0];
        if (el) el.focus(); else if (n > 0) setTimeout(() => go(n - 1), 70);
      };
      setTimeout(() => go(12), 0);
    }, []);
    useEffect(() => {
      const f = (ev) => {
        if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.altKey || overlayRef.current) return;
        const t = ev.target, tag = t && t.tagName, k = ev.key;
        if (tag === "TEXTAREA" || tag === "SELECT" || tag === "INPUT" || (t && t.isContentEditable)) return;
        if (diveRef.current) { if (k === "Escape" || (k === "ArrowLeft" && !arrowsRef.current)) { ev.preventDefault(); back(); } return; } // a core that uses the left arrow itself (the sort of visuals) says so in arrowsRef
        if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Escape"].includes(k)) return;
        const n = columnsOf(selRef.current).length;
        const row = t && t.closest ? t.closest("button[data-col]") : null;
        const ci = row ? +row.dataset.col : n - 1;
        if (k === "ArrowUp" || k === "ArrowDown") {
          const c = document.querySelector('.col[data-col="' + ci + '"]');
          const rows = c ? [...c.querySelectorAll("button[data-col]")] : [];
          if (!rows.length) return;
          ev.preventDefault();
          const at = row ? rows.indexOf(row) : rows.findIndex((r) => r.getAttribute("aria-current") === "true");
          const nx = rows[Math.max(0, Math.min(rows.length - 1, at < 0 ? 0 : row ? at + (k === "ArrowDown" ? 1 : -1) : at))]; // with no row focused yet, the first arrow lands on the selected one
          nx.focus();
          if (nx.dataset.select && nx !== row) nx.click(); // a selection follows the arrows: the column to its right shows what it holds
        } else if (k === "ArrowRight") {
          if (!row) return;
          ev.preventDefault();
          if (!row.dataset.select) { row.click(); return; } // a task, a piece: it opens
          if (row.getAttribute("aria-current") !== "true") row.click();
          focusIn(ci + 1, false);
        } else if (n > 1) {
          ev.preventDefault();
          const to = Math.max(1, ci);
          const from = document.querySelector('.col[data-col="' + (to - 1) + '"] button[aria-current="true"]'); // the row that opened the column we leave
          popTo(to);
          focusIn(to - 1, true, from && from.getAttribute("aria-label"));
        }
      };
      window.addEventListener("keydown", f);
      return () => window.removeEventListener("keydown", f);
    }, []);

    /* the task row that opened a dive takes the focus back when the columns return */
    useEffect(() => {
      if (!dive && backTo.current) {
        const { id, col } = backTo.current; backTo.current = null;
        setTimeout(() => { const el = document.querySelector((col != null ? '.col[data-col="' + col + '"] ' : "") + 'button[data-task="' + CSS.escape(id) + '"]'); if (el) el.focus(); }, 120);
      }
    }, [dive]);

    const n = data.tasks.length;
    const deepest = dive ? taskTitle(dive) : sel.project ? projectInfo(sel.project).name : sel.brand ? brandName(sel.brand) : "Studio";
    useEffect(() => { document.title = (n ? "(" + n + ") " : "") + deepest + " · Studio créatif"; }, [n, deepest]);

    const err = error && h("div", { role: "alert", className: "err" }, h(Callout, { tone: "risk", label: "Le studio refuse" }, error, " ", h("button", { type: "button", className: "linkbtn", onClick: () => setError(null) }, "Fermer")));
    const skip = h("a", { href: "#main", className: "skip", onClick: (e) => { e.preventDefault(); const m = document.getElementById("main"); if (m) m.focus(); } }, "Aller au contenu");
    const pal = palette && h(Palette, { cmds, onClose: () => setPalette(false) });

    /* ----- a task opened: the columns fold into strips that keep their names ----- */
    if (dive) {
      const t = dive;
      const names = [["Le studio", "b1"], [t.brand_name || brandName(t.brand), "b2"], ...(t.scope === "project" ? [[t.project_name || projectInfo(t.project).name, "b3"]] : [])];
      const last = names[names.length - 1][0];
      return h("div", { className: "app plonge" + (narrow ? " narrow" : "") }, skip,
        narrow ? h("button", { type: "button", className: "retour", onClick: back, "aria-label": "Revenir aux colonnes : " + last }, "‹ " + last)
          : names.map(([name, cl]) => h("button", { key: cl, type: "button", className: "bande " + cl, onClick: back, "aria-label": "Revenir aux colonnes : " + name }, h("span", null, name))),
        h("main", { id: "main", tabIndex: -1, className: "coeur" }, h("div", { className: "coeur-in" }, err, h(Core, { ctx, t, key: t._k }))), pal);
    }

    /* ----- the columns ----- */
    const node = (kind) => kind === "studio" ? h(StudioCol, { ctx }) : kind === "newBrand" ? h(NewBrandForm, { ctx }) : kind === "brand" ? h(BrandCol, { ctx, bid: sel.brand, key: sel.brand })
      : kind === "editBrand" ? h(EditBrandForm, { ctx, bid: sel.brand, key: sel.brand }) : kind === "newProject" ? h(NewProjectForm, { ctx, bid: sel.brand })
      : kind === "project" ? h(ProjectCol, { ctx, pid: sel.project, key: sel.project })
      : kind === "step" ? h(StepDetail, { ctx, pid: sel.project, step: sel.detail.key, key: sel.project + sel.detail.key })
      : kind === "journal" ? h(JournalCol, { ctx, pid: sel.project }) : h(EditProjectForm, { ctx, pid: sel.project, key: sel.project });
    const labels = { studio: "Le studio", newBrand: "Nouvelle marque", brand: brandName(sel.brand), editBrand: "Modifier la marque", newProject: "Nouveau projet", project: projectInfo(sel.project).name,
      step: "Ce qui a été décidé", journal: "Journal", editProject: "Modifier le projet" };
    const shell = (kind, i) => {
      const last = i === cols.length - 1;
      return h("section", { key: kind + i, className: "col c" + Math.min(i + 1, 4) + (last && i > 0 ? " last" : ""), "data-col": i, "aria-label": labels[kind] },
        last && err, last && h(Notice, { text: notice }), node(kind));
    };
    if (narrow) {
      const i = cols.length - 1;
      return h("div", { className: "app narrow" }, skip, h("h1", { className: "sr" }, "Studio créatif"),
        i > 0 && h("button", { type: "button", className: "retour", onClick: () => popTo(i), "aria-label": "Retour : " + labels[cols[i - 1]] }, "‹ " + labels[cols[i - 1]]),
        h("main", { id: "main", tabIndex: -1, className: "cols" }, shell(cols[i], i)), pal);
    }
    return h("div", { className: "app" }, skip, h("h1", { className: "sr" }, "Studio créatif"),
      h("main", { id: "main", tabIndex: -1, className: "cols" }, cols.map(shell),
        cols.length === 1 && h("div", { className: "rest" }, err, h(Notice, { text: notice }), h("p", { className: "muted" }, "Choisis une marque, ou ouvre une tâche. ", h("span", { className: "mono" }, MOD + " K"), " pour tout trouver."))),
      pal);
  }

  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
