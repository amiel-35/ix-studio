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
    if (n("personas")) parts.push("imagine les personas");
    if (n("names")) parts.push("cherche des noms");
    if (n("competitors")) parts.push("cherche les concurrents");
    if (n("texts")) parts.push("écrit les textes");
    if (n("storyboard")) parts.push("écrit le découpage du film");
    if (n("film")) parts.push("fait le film");
    if (n("judge")) parts.push("fait relire " + plural(n("judge"), "pièce", "pièces") + " au juge");
    if (n("reader")) parts.push("fait lire " + plural(n("reader"), "lecteur", "lecteurs"));
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
  /* a name after "de": "d'Ondine", "du Port", "des Caves", "de Marrowbay" */
  const deName = (n) => /^les\s/i.test(n) ? "des " + n.slice(4) : /^le\s/i.test(n) ? "du " + n.slice(3) : /^[aeiouyhàâéèêîôû]/i.test(n) ? "d'" + n : "de " + n;
  /* what a person or the studio wrote is put in the middle of a sentence: no full stop of its own (the sentence has the next one), and
     no capital left over where the sentence goes on ("c'est Une brasserie", "à les caves") */
  const dot = (v) => String(v || "").trim().replace(/[.\s]+$/, "");
  const ARTICLE = /^(?:[LD]['’]|(?:Une?|Le|La|Les|Des|Du|De|Ce|Cet|Cette|Ces|Notre|Nos|Votre|Vos|Leur|Leurs|Mon|Ma|Mes|Son|Sa|Ses|Ton|Ta|Tes|Chaque|Tous|Toutes|Tout)(?=\s|$))/;
  const lc1 = (x) => x.charAt(0).toLowerCase() + x.slice(1);
  const lowerFirst = (v) => ARTICLE.test(v) ? v.charAt(0).toLowerCase() + v.slice(1) : v;
  const lowerVerb = (v) => /^[A-ZÀ-Ý][a-zà-ÿ]+(?:er|ir|re)(?=\s|$)/.test(v) ? v.charAt(0).toLowerCase() + v.slice(1) : lowerFirst(v);
  /* "à" and an article melt: à les artisans, aux artisans */
  const toWhom = (v) => { const x = lowerFirst(dot(v)); return /^les\s/i.test(x) ? "aux " + x.slice(4) : /^le\s/i.test(x) ? "au " + x.slice(3) : "à " + x; };
  /* a brand's brief in one sentence, a project's brief in one sentence: how each piece is written in it */
  const BRAND_SHOW = { what: (v) => lowerFirst(dot(v)), who: toWhom };
  const BRIEF_SHOW = { objective: (v) => lowerVerb(dot(v)), audience: (v) => lowerFirst(dot(v)) };
  /* the titles the studio gives to a brand's tasks say "la marque": the interface says which one */
  function taskTitle(t) {
    if (t.scope !== "brand" || !t.brand_name) return t.title;
    const n = t.brand_name;
    return t.title.replace("de la marque", deName(n)).replace(/la marque\b/, n);
  }
  /* what a task waits on, for a list: where it belongs, and how long it has waited */
  const taskPlace = (t) => t.scope === "brand" ? t.brand_name : t.brand_name + " · " + t.project_name;
  const owner = (t) => (t.scope === "brand" ? "@" + t.brand : t.project);

  /* the journal of decisions, per project, on this side */
  const loadJournal = (pid) => { try { return JSON.parse(localStorage.getItem("studio-journal:" + pid) || "[]"); } catch (e) { return []; } };
  const saveJournal = (pid, list) => { try { localStorage.setItem("studio-journal:" + pid, JSON.stringify(list.slice(0, 200))); } catch (e) { /* private window: no journal */ } };

  /* a file the studio gave ({blob, name}) is saved by the browser */
  function saveFile(f) {
    const url = URL.createObjectURL(f.blob), a = document.createElement("a");
    a.href = url; a.download = f.name; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  /* a core screen gives its own commands to the palette: the ref holds the list of the screen on screen */
  function useCmds(ctx, list) {
    const mine = useRef(null);
    mine.current = list;
    ctx.cmdsRef.current = list;
    useEffect(() => () => { if (ctx.cmdsRef.current === mine.current) ctx.cmdsRef.current = []; }, []);
  }

  /* a passage of a brief is being corrected: Escape closes that, and only that (not the task under it), then the focus goes back to the passage,
     so that the next Escape is a deliberate one */
  function useEscapeClose(ctx, open, setOpen) {
    useEffect(() => {
      if (!open) return;
      const f = (ev) => {
        if (ev.key !== "Escape" || ctx.overlayRef.current) return;
        ev.stopPropagation(); ev.preventDefault(); setOpen(null);
        setTimeout(() => { const el = document.querySelector('[data-bit="' + open + '"]'); if (el) el.focus(); }, 0);
      };
      window.addEventListener("keydown", f, true);
      return () => window.removeEventListener("keydown", f, true);
    }, [open]);
  }

  /* ---------- building blocks ---------- */
  /* the one heading of a screen: it takes the focus when the screen opens, so the screen reader says where we are */
  function Head({ children, sr, focus = true }) {
    const ref = useRef(null);
    useEffect(() => { if (focus && ref.current) ref.current.focus({ preventScroll: true }); }, []);
    return h("h1", { ref, tabIndex: -1, className: sr ? "sr" : "head" }, children);
  }
  /* what was just done, in a line; it may offer the one gesture that follows from it (`action`: {label, run}) */
  const Notice = ({ text, action, busy }) => text ? h("p", { className: "notice", role: "status" }, h(Badge, { tone: "success" }, "Fait"), h("span", null, text, action && h(React.Fragment, null, " ",
    h("button", { type: "button", className: "linkbtn", disabled: busy, onClick: action.run, "aria-label": action.label }, action.label)))) : null;
  const Wait = ({ text }) => h("p", { className: "muted", role: "status" }, text || "Un instant.");
  /* a piece or an image at the ratio it will have; a click opens it full screen (a click, Escape or "Fermer" brings it back) */
  function Frame({ src, alt, size }) {
    const [big, setBig] = useState(false);
    const ratio = size ? size[0] / size[1] : 4 / 5;
    return h(React.Fragment, null,
      h("button", { type: "button", className: "frame zoomable", style: { "--ratio": ratio }, onClick: () => setBig(true), "aria-label": "Voir en grand : " + alt }, h("img", { src, alt: "" })),
      big && h(Zoom, { src, alt, onClose: () => setBig(false) }));
  }
  function Zoom({ src, alt, onClose }) {
    const close = useRef(null);
    useEffect(() => {
      const prev = document.activeElement;
      const b = close.current && close.current.querySelector("button"); if (b) b.focus();
      const f = (ev) => {
        if (ev.metaKey || ev.ctrlKey) return; // the palette key still answers
        ev.stopPropagation(); // nothing under the picture reacts to the keys (the left arrow, Escape) while it is open
        if (ev.key === "Escape") { ev.preventDefault(); onClose(); } else if (ev.key === "Tab") ev.preventDefault();
      };
      window.addEventListener("keydown", f, true);
      return () => { window.removeEventListener("keydown", f, true); if (prev && prev.isConnected && prev.focus) prev.focus(); };
    }, []);
    return h("div", { className: "zoom", role: "dialog", "aria-modal": "true", "aria-label": alt, onClick: onClose },
      h("img", { src, alt }),
      h("div", { className: "zoom-close", ref: close }, h(Button, { variant: "secondary", size: "md", onClick: onClose, "aria-label": "Fermer l'image en grand" }, "Fermer")));
  }
  /* ================= a failed reading, or a failed job ================= */
  function JobFailed({ ctx, t }) {
    useCmds(ctx, []);
    const reason = String(t.question || "").replace(/^Le dernier essai a échoué : /, "").replace(/\.$/, "");
    const retry = () => ctx.act(async (snap) => {
      if (t.scope === "brand") await api.discover(t.brand);
      else if (t.step === "diverge") await api.diverge(t.project);
      else if (t.step === "check") await api.judgePiece(t.project, t.piece);
      else await api.drawImage(t.project, t.piece);
      ctx.log(owner(t), "toi", "Relancé : " + taskTitle(t), reason);
      await ctx.answered(owner(t), "C'est relancé.", { before: snap, any: false });
    }, "Le studio relance.");
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

  /* the colours of a brand, each with its state: measured and not confirmed yet, or confirmed. A swatch, and the word of its role: never a hexadecimal */
  const COLOUR_WORDS = { background: "Fond", text: "Texte", accent: "Accent", "headline colour": "Titres" };
  const Swatches = ({ colours, mini, quiet }) => colours.length === 0 ? h("p", { className: "muted small" }, "Aucune couleur pour cette marque.") :
    h("ul", { className: "swatches" + (mini ? " mini" : ""), "aria-label": "Couleurs de la marque" }, colours.map((c, i) => {
      const word = COLOUR_WORDS[c.role] || "";
      return h("li", { key: c.hex + i, className: "swatch" },
        h("i", { style: { background: c.hex }, role: "img", "aria-label": (word ? "Couleur : " + word.toLowerCase() : "Couleur " + (i + 1)) + (c.state === "deduced" ? ", à confirmer" : "") }),
        word && h("span", { className: "small" }, word), !mini && !quiet && c.state === "deduced" && h("span", { className: "small muted" }, "à confirmer"));
    }));
  /* a few colours in a line, as swatches */
  const Pastilles = ({ list }) => h("span", { className: "dots", role: "img", "aria-label": list.map((c) => c.word).filter(Boolean).join(", ") || plural(list.length, "couleur", "couleurs") },
    list.map((c, i) => h("i", { key: c.hex + i, style: { background: c.hex } })));

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
      hasProposals && h("p", { className: "small" }, h("button", { type: "button", className: "linkbtn", onClick: followStudio, "aria-label": "Suivre les propositions du studio pour les " + left + " visuels restants" }, "Suivre les propositions du studio"), " pour les " + plural(left, "visuel restant", "visuels restants") + "."),
      h("p", { className: "keys small muted" }, "Clavier : G garder, E écarter, U annuler, flèches pour naviguer."),
      h("span", { className: "sr", role: "status", "aria-live": "polite" }, said));
  }

  /* ================= a brand: its brief, as one sentence whose pieces are corrected ================= */
  const BPARTS = [
    { k: "what", before: ", c'est ", label: "ce qu'elle est", area: true },
    { k: "who", before: ". Elle parle ", label: "pour qui", area: true },
    { k: "voice", before: ". Sa voix : ", label: "sa voix" },
    { k: "signature", before: ". Sa signature : « ", after: " »", label: "sa signature" },
    { k: "never", before: ". Elle ne dit jamais : ", label: "ce qu'elle ne dit jamais" },
    { k: "colours", before: ". Ses couleurs : ", label: "ses couleurs", palette: true },
  ];
  const ROLE_WORDS = { background: "Fond", text: "Texte", accent: "Accent" };
  const ROLES = ["background", "text", "accent"];
  const SEED = "#808080"; // where the native picker starts when nothing is chosen yet: it is never stored

  /* a colour of the brand as a swatch, chosen with the browser's own picker: the person never types a hexadecimal */
  function Pick({ role, hex, onChange, onClear }) {
    return h("div", { className: "pickrow" },
      h("label", { className: "pick" },
        h("input", { type: "color", className: "sr", value: hex || SEED, onChange: (e) => onChange(e.target.value.toLowerCase()), "aria-label": "Couleur : " + ROLE_WORDS[role].toLowerCase() + (hex ? "" : " (à choisir)"), "data-role": role }),
        h("i", { className: "dot", "data-empty": hex ? undefined : "1", style: hex ? { background: hex } : undefined, "aria-hidden": "true" }),
        h("span", { className: "small" }, ROLE_WORDS[role] + (hex ? "" : " : à choisir"))),
      onClear && h("button", { type: "button", className: "linkbtn small", onClick: onClear, "aria-label": "Retirer la couleur d'accent" }, "Retirer"));
  }
  const Dots = ({ palette }) => h(Pastilles, { list: ROLES.filter((r) => palette[r]).map((r) => ({ hex: palette[r], word: ROLE_WORDS[r].toLowerCase() })) });

  function BrandBrief({ ctx, t }) {
    const bid = t.brand, name = t.brand_name;
    const [data, setData] = useState(null);
    const [fields, setFields] = useState(null);
    const [open, setOpen] = useState(null);
    const [palette, setPalette] = useState(null); // the colours as the pickers have them; null while they are not touched
    useEffect(() => {
      api.brandBrief(bid).then((b) => {
        setData(b); const f = {}; Object.keys(b.fields).forEach((k) => { f[k] = b.fields[k].value || ""; }); setFields(f);
        if (b.done && b.needs.includes("colours") && !b.needs.includes("logo")) setOpen("colours"); // the one thing missing: the pickers are open
      }).catch(ctx.fail);
    }, [bid]);
    useEscapeClose(ctx, open, setOpen);
    useCmds(ctx, []);
    if (!fields) return h("div", { className: "task" }, h(Wait, { text: "Chargement du brief de la marque." }));
    if (data.done && !t.reopen && !data.needs.includes("colours")) return h(NeedLogo, { ctx, bid, name });
    if (data.done && !t.reopen && data.needs.includes("logo")) return h(NeedLogo, { ctx, bid, name });
    const set = (k, v) => setFields({ ...fields, [k]: v });
    const pal = palette || data.palette; // what the pickers show: the person's choice, else what the studio proposes from the colours it has
    const touch = (role, hex) => setPalette({ ...pal, [role]: hex });
    const stateOf = (k) => (k === "colours" && palette ? "typed" : data.fields[k].state === "deduced" && (fields[k] || "") === data.fields[k].value ? "deduced" : "typed");
    const anyDeduced = BPARTS.some((p) => stateOf(p.k) === "deduced");
    const hasPal = ROLES.some((r) => pal[r]);
    const colourWords = (fields.colours || "").trim();
    const piece = (p) => h(React.Fragment, { key: p.k }, p.before, h("span", {
      role: "button", tabIndex: 0, className: "bit", "data-bit": p.k, "aria-expanded": open === p.k, "data-open": open === p.k, "data-state": stateOf(p.k),
      "aria-label": "Corriger " + p.label + " : " + (p.palette ? (hasPal ? ROLES.filter((r) => pal[r]).map((r) => ROLE_WORDS[r].toLowerCase()).join(", ") : "vide") : fields[p.k] || "vide") + (stateOf(p.k) === "deduced" ? " (déduit par le studio, à confirmer)" : ""),
      onClick: () => setOpen(open === p.k ? null : p.k),
      onKeyDown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setOpen(open === p.k ? null : p.k); } },
    }, p.palette ? (hasPal ? h(Dots, { palette: pal }) : colourWords || h("span", { className: "blank" }, "à choisir")) : (fields[p.k] || "").trim() ? (BRAND_SHOW[p.k] || dot)(fields[p.k]) : h("span", { className: "blank" }, "à écrire")), p.after || "");
    const cur = BPARTS.find((p) => p.k === open);
    const palWrong = palette && !(palette.background && palette.text);
    const needColours = data.done && data.needs.includes("colours");
    const submit = () => ctx.act(async (snap) => {
      const changed = BPARTS.filter((p) => p.palette ? !!palette : (fields[p.k] || "") !== (data.fields[p.k].value || "")).map((p) => p.label);
      await api.saveBrandBrief(bid, palette ? { ...fields, colours: ROLES.filter((r) => palette[r]).map((r) => ({ hex: palette[r], role: r })) } : fields);
      ctx.log("@" + bid, "toi", "Brief de la marque validé", changed.length ? "Corrigé : " + changed.join(", ") : "Rien à corriger");
      await ctx.answered("@" + bid, "Brief " + deName(name) + " enregistré.", { before: snap, sibling: (t) => t.kind === "brand-brief" }); // a brand with no logo and no site still asks for one: the same task, said otherwise
    });
    return h("div", { className: "task" }, h(Head, { sr: true }, needColours ? "Choisis les couleurs " + deName(name) : "Relis le brief " + deName(name)),
      needColours && h("p", { className: "lead" }, "Pour composer une pièce, il faut au moins deux couleurs : une pour le fond, une pour le texte."),
      h("p", { className: "sentence" }, name, BPARTS.map(piece), "."),
      h("p", { className: "small muted" }, "Touche un passage pour le corriger." + (anyDeduced ? " Les passages en pointillé sont ce que le studio a déduit : validés tels quels, ils sont confirmés." : "")),
      cur && cur.palette ? h("div", { className: "editor" },
        h("span", { className: "small cap", id: "bed-colours" }, "Corriger " + cur.label),
        h("div", { className: "pickers", role: "group", "aria-labelledby": "bed-colours" },
          h(Pick, { role: "background", hex: pal.background, onChange: (x) => touch("background", x) }),
          h(Pick, { role: "text", hex: pal.text, onChange: (x) => touch("text", x) }),
          pal.accent ? h(Pick, { role: "accent", hex: pal.accent, onChange: (x) => touch("accent", x), onClear: () => touch("accent", null) })
            : h("button", { type: "button", className: "linkbtn small", onClick: () => touch("accent", SEED), "aria-label": "Ajouter une couleur d'accent" }, "Ajouter un accent")),
        h("span", { className: "small muted" }, "Touche une pastille pour choisir sa couleur. Le fond et le texte suffisent, l'accent est facultatif."),
        h("div", { className: "row" }, h(Button, { variant: "secondary", size: "sm", onClick: () => setOpen(null), "aria-label": "Terminer la correction de " + cur.label }, "Fait")))
      : cur && h("div", { className: "editor" },
        h("label", { htmlFor: "bed", className: "small" }, "Corriger " + cur.label),
        cur.area ? h("textarea", { id: "bed", autoFocus: true, value: fields[cur.k] || "", onChange: (e) => set(cur.k, e.target.value) })
          : h("input", { id: "bed", type: "text", autoFocus: true, value: fields[cur.k] || "", onChange: (e) => set(cur.k, e.target.value), onKeyDown: (e) => { if (e.key === "Enter") setOpen(null); } }),
        (cur.k === "voice" || cur.k === "never") && h("span", { className: "small muted" }, "Sépare par des virgules."),
        h("div", { className: "row" }, h(Button, { variant: "secondary", size: "sm", onClick: () => setOpen(null), "aria-label": "Terminer la correction de " + cur.label }, "Fait"))),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !(fields.what || "").trim() || palWrong, onClick: submit, "aria-label": "Valider le brief de la marque" }, data.done ? "Enregistrer le brief" : "Valider le brief")),
      !(fields.what || "").trim() && h("p", { className: "small muted", role: "status" }, "Il manque : ce qu'elle est."),
      palWrong && h("p", { className: "small muted", role: "status" }, "Il manque : la couleur " + (palette.background ? "du texte" : "du fond") + "."));
  }

  /* the brief is done, the brand has no logo and the studio has no site to find one in: drop one, or give the site */
  function NeedLogo({ ctx, bid, name }) {
    const [site, setSite] = useState("");
    useCmds(ctx, []);
    const read = () => ctx.act(async (snap) => {
      await api.updateBrand(bid, { site: site.trim() });
      await api.discover(bid);
      ctx.log("@" + bid, "toi", "Site donné : " + site.trim(), "Le studio le lit pour y trouver un logo");
      await ctx.answered("@" + bid, "Le studio lit le site " + deName(name) + ".", { before: snap, any: false });
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
    return h("div", { className: "task" }, h(Head, null, toConfirm.length ? "Confirme ce que le studio a déduit " + deName(name) : "Regarde " + name + ", puis confirme"),
      h("ul", { className: "rows facts" }, shown.map((k) => h("li", { key: k, className: "fact" },
        h("span", { className: "cap" }, FIELD_LABEL[k]),
        k === "logo" ? h("img", { src: a.logo.preview, alt: "Logo " + deName(name), className: "factlogo" })
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
    useEscapeClose(ctx, open, setOpen);
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
      return v ? (BRIEF_SHOW[p.k] || dot)(v) : h("span", { className: "blank" }, p.empty || "à écrire");
    };
    const piece = (p) => h(React.Fragment, { key: p.k }, p.before, h("span", {
      role: "button", tabIndex: 0, className: "bit", "data-bit": p.k, "aria-expanded": open === p.k, "aria-label": "Corriger " + p.label + " : " + (fields[p.k] || "vide"),
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
    }, "Le studio prépare les consignes.");
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
      h(BriefPersonas, { list: fields.personas || [], set: (v) => set("personas", v), id: "pe" }),
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
      if (m.confirmed) { await ctx.answered(pid, "Consignes enregistrées.", { before: snap }); return; } // reopened: what was written stays, nothing starts again
      await api.diverge(pid); // « C'est bon » is the one gesture: the instructions are validated and the four agents start
      ctx.log(pid, "toi", "Divergence lancée", "Quatre agents écrivent chacun leur variante, à l'aveugle");
      await ctx.answered(pid, "Consignes validées : quatre agents écrivent chacun leur variante.", { before: snap, any: false });
    }, "Le studio lance la divergence.");
    return h("div", { className: "task" }, h(Head, null, "Voilà ce que les quatre agents vont recevoir"),
      edit ? h("div", { className: "sec" },
        h("div", { className: "field" }, h("label", { htmlFor: "common" }, "La consigne commune"), h("textarea", { id: "common", value: m.common, onChange: (e) => setM({ ...m, common: e.target.value }) })),
        m.items.map((it) => h("div", { key: it.id, className: "field" }, h("label", { htmlFor: "m-" + it.id }, "Agent " + it.id.toUpperCase()),
          h("input", { id: "m-" + it.id, type: "text", value: it.mandate, onChange: (e) => setItem(it.id, e.target.value) }))))
        : h("div", { className: "sec" },
          h("p", { className: "lead" }, m.common),
          h("ul", { className: "plain" }, m.items.map((it) => h("li", { key: it.id }, h("span", { className: "cap" }, "Agent " + it.id.toUpperCase()), h("span", null, it.mandate))))),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: submit, "aria-label": m.confirmed ? "Enregistrer les consignes aux agents" : "Valider les consignes et lancer la divergence" }, m.confirmed ? "Enregistrer" : "C'est bon"),
        h(Button, { variant: "secondary", size: "lg", onClick: () => setEdit(!edit), "aria-label": edit ? "Arrêter de corriger" : "Corriger les consignes" }, edit ? "Arrêter de corriger" : "Corriger")),
      !m.confirmed && h("p", { className: "small muted" }, "« C'est bon » lance aussitôt la divergence : chaque agent écrit sa variante, sans voir celles des autres."));
  }

  /* ================= 5. divergence: launch, then pick ================= */
  function DivergeLaunch({ ctx, pid }) {
    useCmds(ctx, []);
    const launch = () => ctx.act(async (snap) => {
      await api.diverge(pid);
      ctx.log(pid, "toi", "Divergence lancée", "Quatre agents écrivent chacun leur variante, à l'aveugle");
      await ctx.answered(pid, "Divergence lancée : quatre agents écrivent chacun leur variante.", { before: snap });
    }, "Le studio lance la divergence.");
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
    }, "Le studio prépare la série.");
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

  /* ================= the judge: five headings, in words, never a score ================= */
  const REACHED = { yes: "Atteinte", partly: "En partie", no: "Pas atteinte" };
  const JUDGE_HEADS = [["works", "Ce qui marche"], ["snags", "Ce qui accroche"], ["unsourced", "Sans provenance"], ["brand", "La marque"]];
  const cap1 = (x) => x.charAt(0).toUpperCase() + x.slice(1);
  function Verdict({ v }) {
    const heads = JUDGE_HEADS.filter(([k]) => k !== "brand" || v.brand !== null); // the brand is judged only when it is known
    return h("div", { className: "verdict" },
      v.missing.length > 0 && h("p", { className: "small muted" }, "Brief incomplet : il manque " + v.missing.join(", ") + ". Le reste est jugé."),
      h("section", null, h("h3", { className: "cap" }, "La cible"),
        v.target.reached === "unjudgeable" ? h("p", null, cap1(dot(v.target.why)) + ".") : h("p", null, h("strong", null, REACHED[v.target.reached] + ". "), v.target.why)),
      heads.map(([k, label]) => h("section", { key: k }, h("h3", { className: "cap" }, label),
        v[k].length ? h("ul", { className: "annots" }, v[k].map((n, i) => h("li", { key: i }, h("span", { className: "small muted" }, cap1(n.where)), h("span", null, n.say))))
          : h("p", { className: "small muted" }, "Rien à signaler."))));
  }

  /* ================= the readers: one per persona of the brief, side by side, without a synthesis ================= */
  const AIMED = { yes: "oui", partly: "en partie", no: "non" };
  const READ_HEADS = [["understand", "Ce que je comprends"], ["retain", "Ce que je retiens"], ["bother", "Ce qui me gêne"], ["unread", "Ce que je ne lis pas"], ["lacks", "Ce qui me manque"]];
  function BriefPersonas({ list, set, id }) {
    const put = (i, v) => set(list.map((x, j) => (j === i ? v : x)));
    return h("div", { className: "sec" },
      h("p", { className: "small muted" }, "Les personas visés, si tu veux : un à quatre, écrits par toi. Chacun lit la pièce seul, à côté du juge."),
      list.map((x, i) => h("div", { key: i, className: "field" },
        h("label", { htmlFor: id + i, className: "small" }, "Persona " + (i + 1)),
        h("textarea", { id: id + i, value: x, onChange: (e) => put(i, e.target.value), placeholder: "Par exemple : tu as 55 ans, artisan, tu ne vas chez le médecin que quand ta femme insiste" }),
        h("div", null, h("button", { type: "button", className: "linkbtn", onClick: () => set(list.filter((_, j) => j !== i)), "aria-label": "Retirer le persona " + (i + 1) }, "Retirer")))),
      list.length < 4 && h("div", null, h("button", { type: "button", className: "linkbtn", onClick: () => set([...list, ""]) }, list.length ? "Ajouter un persona" : "Viser un persona")));
  }
  function Readers({ readers, busy, run }) {
    if (!readers || !readers.length) return null;
    return h("div", { className: "lecteurs", "aria-live": "polite" }, h("p", { className: "cap" }, readers.length > 1 ? "Les lecteurs" : "Le lecteur"),
      h("div", { className: "cote" }, readers.map((r) => h("section", { key: r.n, className: "lecteur" },
        h("p", { className: "small muted" }, r.persona),
        r.status === "done" ? h(React.Fragment, null, h("p", null, h("strong", null, "Elle me vise : " + AIMED[r.reading.aimed] + ". "), r.reading.why),
          READ_HEADS.filter(([k]) => r.reading[k]).map(([k, label]) => h("div", { key: k }, h("h3", { className: "cap" }, label), h("p", null, r.reading[k]))))
          : r.status === "running" ? h("p", { className: "small muted" }, "Ce lecteur lit la pièce.")
          : h("p", { className: "small" }, r.status === "failed" ? "Ce lecteur n'a pas pu la lire : " + dot(r.error) + ". " : "Pas encore lue. ",
            h("button", { type: "button", className: "linkbtn", disabled: busy, onClick: () => run(r.n), "aria-label": "Relancer le lecteur " + (r.n + 1) }, "Relancer"))))));
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
  /* where the series stands: how many pieces have their image, are composed, are decided (kept) */
  const SERIES_STEPS = ["image", "piece", "decide"];
  const seriesCount = (pcs) => ({ total: pcs.length, image: pcs.filter((x) => x.image).length, piece: pcs.filter((x) => x.composed).length, decide: pcs.filter((x) => x.decision && x.decision.verdict === "keep").length });
  const SERIES_WORD = { image: " avec leur image", piece: " composées", decide: " gardées" };
  const pieceSrc = (pc) => pc.composed || pc.image || null;

  /* the series in a column: the pieces as thumbnails, each with where it stands; a click opens it */
  function Series({ ctx, p, col }) {
    const jobs = p.jobs, n = seriesCount(p.pieces);
    const open = (pc) => ctx.openTask(synth(p, "piece-any", { piece: pc.id, title: pc.label }));
    const toDraw = p.pieces.filter((x) => !x.image && !jobs.some((j) => j.kind === "image" && j.piece === x.id)).length, toCompose = p.pieces.filter((x) => x.image && !x.composed).length;
    const hasPrompt = ctx.data.tasks.some((t) => t.scope === "project" && t.project === p.id && t.kind === "prompt"); // an image that failed is a task of its own, not a prompt to read
    const takeKept = () => ctx.act(async () => { const f = await api.downloadKept(p.id); saveFile(f); ctx.notify(f.name + " est téléchargé : " + plural(n.decide, "pièce", "pièces") + "."); }, "Le studio prépare le zip.");
    return h(React.Fragment, null,
      h(Where, null, "La série · " + plural(n.total, "pièce", "pièces")),
      (toDraw > 1 && hasPrompt || toCompose > 1 || n.decide > 0) && h("div", { className: "take" },
        toDraw > 1 && hasPrompt && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy, onClick: () => ctx.act(() => ctx.drawAll(p.id), "Le studio lance toutes les images."), "aria-label": "Lancer les " + toDraw + " images qui manquent, sans relire les prompts" }, "Dessiner toutes les images"),
        toCompose > 1 && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy, onClick: () => ctx.act(() => ctx.composeAll(p.id), "Le studio compose les pièces, une par une."), "aria-label": "Composer et vérifier les " + toCompose + " pièces qui ont leur image" }, "Composer tout"),
        n.decide > 0 && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy, onClick: takeKept, "aria-label": n.decide === 1 ? "Télécharger en zip la pièce gardée" : "Télécharger en zip les " + plural(n.decide, "pièce gardée", "pièces gardées") }, n.decide === 1 ? "Télécharger la pièce gardée" : "Télécharger les " + plural(n.decide, "pièce gardée", "pièces gardées"))),
      h("ul", { className: "serie", "aria-label": "Les pièces de la série" }, p.pieces.map((pc) => {
        const w = STAGE_WORDS[stageOf(pc, jobs)], src = pieceSrc(pc);
        return h("li", { key: pc.id }, h("button", { type: "button", className: "vign", "data-col": col, "data-piece": pc.id, onClick: () => open(pc), "aria-label": pc.label + " : " + w.toLowerCase() },
          h("span", { className: "vf", style: { "--ratio": pc.size[0] / pc.size[1] } }, src ? h("img", { src, alt: "" }) : null),
          h("span", { className: "nom small" }, pc.label), h("span", { className: "meta" }, w)));
      })));
  }

  function usePiece(ctx, pid, id) {
    const [pc, setPc] = useState(null);
    useEffect(() => { api.piece(pid, id).then(setPc).catch(ctx.fail); }, [pid, id]);
    return [pc, setPc];
  }
  const PieceHead = ({ pc }) => h(React.Fragment, null,
    h(Eyebrow, null, pc.label + " · " + pc.size[0] + " × " + pc.size[1]),
    h(Head, null, pc.headline));

  /* the prompt of a variant: its formats share it, and the image of each is drawn from it */
  function Prompt({ ctx, pid, id }) {
    const [st, setSt] = useState(null);
    const [prompt, setPrompt] = useState(null);
    const [words, setWords] = useState(null); // the headline and the subline, which can be corrected before the image
    const [edit, setEdit] = useState(false);
    useEffect(() => { Promise.all([api.piece(pid, id), api.project(pid)]).then(([pc, p]) => { setSt({ pc, p }); setPrompt(pc.prompt); setWords({ headline: pc.headline, subline: pc.subline || "" }); }).catch(ctx.fail); }, [pid, id]);
    useCmds(ctx, st ? [{ id: "words", label: edit ? "Fermer la correction du titre" : "Corriger le titre et la sous-ligne", run: () => setEdit(!edit) }] : []);
    if (!st || prompt === null || !words) return h("div", { className: "task" }, h(Wait, null));
    const { pc, p } = st;
    const wordsChanged = words.headline.trim() !== pc.headline || words.subline.trim() !== (pc.subline || "");
    const waits = (x) => !x.image && !p.jobs.some((j) => j.kind === "image" && j.piece === x.id);
    const mine = p.pieces.filter((x) => x.variant === pc.variant && waits(x)); // the pieces this prompt is for
    const more = p.pieces.filter((x) => x.variant !== pc.variant && waits(x)).length; // the pieces of the other variants that wait too
    const several = mine.length > 1, formats = mine.map((x) => fmtWord(x.format)).join(", ");
    const draw = (all) => ctx.act(async (snap) => {
      if (wordsChanged) { await api.saveVariantText(pid, pc.variant, words.headline.trim(), words.subline.trim()); ctx.log(pid, "toi", "Mots corrigés pour " + pc.variant, words.headline.trim() + (words.subline.trim() ? " / " + words.subline.trim() : "")); }
      await api.saveVariantPrompt(pid, pc.variant, prompt);
      const r = await api.drawImages(pid, all ? undefined : pc.variant);
      ctx.log(pid, "toi", (all ? "Toutes les images lancées : " : "Images lancées pour " + pc.variant + " : ") + plural(r.jobs.length, "pièce", "pièces"), "Prompt relu : " + prompt);
      await ctx.answered(pid, all ? "Toutes les images sont lancées : " + plural(r.jobs.length, "pièce", "pièces") + "." : "Image" + (several ? "s lancées" : " lancée") + " pour " + pc.variant + ".",
        { before: snap, any: false, sibling: all ? undefined : (t) => t.kind === "prompt" && t.variant !== pc.variant });
    }, "Le studio lance les images.");
    return h("div", { className: "task" },
      h(Eyebrow, null, several ? pc.variant + " · " + formats : pc.label + " · " + pc.size[0] + " × " + pc.size[1]), h(Head, null, words.headline || pc.headline),
      !edit && words.subline && h("p", { className: "lead muted" }, words.subline),
      h("p", { className: "small" }, h("button", { type: "button", className: "linkbtn", "aria-expanded": edit, onClick: () => setEdit(!edit), "aria-label": edit ? "Fermer la correction du titre" : "Corriger le titre et la sous-ligne" }, edit ? "Fermer" : "Corriger le titre")),
      edit && h("div", { className: "sec" },
        h("div", { className: "field" }, h("label", { htmlFor: "w-head" }, "Titre"), h("input", { id: "w-head", type: "text", autoFocus: true, value: words.headline, onChange: (e) => setWords({ ...words, headline: e.target.value }) })),
        h("div", { className: "field" }, h("label", { htmlFor: "w-sub" }, "Sous-ligne (facultative)"), h("input", { id: "w-sub", type: "text", value: words.subline, onChange: (e) => setWords({ ...words, subline: e.target.value }) }))),
      pc.bans && pc.bans.length > 0 && h("p", { className: "small" }, "Tu avais refusé : " + dot(pc.bans.join(" ; ")) + ". Le studio le retient."),
      h("div", { className: "field" }, h("label", { htmlFor: "prompt" }, "Le prompt de l'image" + (several ? ", le même pour " + formats : "")),
        h("textarea", { id: "prompt", className: "prompt", value: prompt, onChange: (e) => setPrompt(e.target.value) })),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !prompt.trim() || !words.headline.trim(), onClick: () => draw(false), "aria-label": "Lancer " + (several ? "les images de " + pc.variant : "l'image de " + pc.label) }, several ? "Dessiner les " + mine.length + " images" : "Dessiner l'image"),
        more > 0 && h(Button, { variant: "secondary", size: "lg", disabled: ctx.busy || !prompt.trim() || !words.headline.trim(), onClick: () => draw(true), "aria-label": "Lancer les " + (mine.length + more) + " images du projet, sans relire les autres prompts" }, "Dessiner toutes les images")),
      more > 0 && h("p", { className: "small muted" }, "« Toutes » lance aussi les " + plural(more, "pièce", "pièces") + " des autres variantes, avec leur prompt tel qu'il est."));
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
    }, "Le studio compose la pièce et la vérifie.");
    const again = () => ctx.act(async (snap) => {
      await api.savePrompt(pid, id, prompt);
      await api.drawImage(pid, id);
      ctx.log(pid, "toi", "Image refaite pour " + pc.label, "Prompt : " + prompt);
      await ctx.answered(pid, "Nouvelle image lancée pour " + pc.label + ".", { before: snap, any: false, sibling: (t) => t.kind === "compose" && t.piece !== id });
    }, "Le studio relance l'image.");
    const ready = ctx.data.tasks.filter((t) => t.scope === "project" && t.project === pid && t.kind === "compose").length; // the pieces that have their image and wait to be composed
    const all = () => ctx.act(async (snap) => { await ctx.composeAll(pid, snap, true); }, "Le studio compose les pièces, une par une.");
    return h("div", { className: "task" }, h(PieceHead, { pc }),
      h("div", { className: "pair" }, h(Frame, { src: pc.image, alt: "Image de " + pc.label, size: pc.size }),
      redo ? h("div", { className: "sec" },
        h("div", { className: "field" }, h("label", { htmlFor: "prompt" }, "Le prompt de l'image"), h("textarea", { id: "prompt", className: "prompt", autoFocus: true, value: prompt, onChange: (e) => setPrompt(e.target.value) })),
        h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !prompt.trim(), onClick: again, "aria-label": "Refaire l'image avec ce prompt" }, "Refaire l'image"),
          h(Button, { variant: "ghost", size: "lg", onClick: () => setRedo(false), "aria-label": "Garder cette image" }, "Garder cette image")))
        : h("div", { className: "sec" },
          h("div", { className: "gestures" },
            h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: compose, "aria-label": "Composer la pièce et la vérifier" }, "Composer et vérifier"),
            h(Button, { variant: "secondary", size: "lg", onClick: () => setRedo(true), "aria-label": "Refaire l'image de " + pc.label }, "Refaire l'image")),
          ready > 1 && h("p", { className: "small muted" }, h("button", { type: "button", className: "linkbtn", disabled: ctx.busy, onClick: all, "aria-label": "Composer et vérifier les " + ready + " pièces qui ont leur image" }, "Composer tout"), " : les " + ready + " pièces qui ont leur image."))));
  }

  function Decide({ ctx, pid, id }) {
    const [pc, setPc] = usePiece(ctx, pid, id);
    useEffect(() => { if (pc && ((pc.judge && pc.judge.status === "running") || (pc.readers || []).some((r) => r.status === "running"))) api.piece(pid, id).then(setPc).catch(() => { /* the next look will say */ }); }, [ctx.rev]); // the judge ends: its verdict comes in
    const [notes, setNotes] = useState(false);
    const [back, setBack] = useState(false);
    const [words, setWords] = useState("");
    const send = (verdict) => ctx.act(async (snap) => {
      await api.decide(pid, id, verdict, words);
      ctx.log(pid, "toi", (verdict === "keep" ? "Gardée : " : "Renvoyée : ") + pc.label, words.trim() || "Sans commentaire");
      await ctx.answered(pid, verdict === "keep" ? pc.label + " : gardée." : pc.label + " : renvoyée, le studio retient « " + dot(words) + " ».",
        { before: snap, prefer: (t) => t.piece === id, any: false, sibling: verdict === "keep" ? (t) => t.kind === "decide" && t.piece !== id : undefined });
    });
    const take = () => ctx.act(async () => { const f = await api.downloadPiece(pid, id); saveFile(f); ctx.notify(f.name + " est téléchargé."); }, "Le studio prépare le png.");
    const rejudge = () => ctx.act(async () => { await api.judgePiece(pid, id); setPc(await api.piece(pid, id)); await ctx.refresh(); }, "Le studio relance le juge.");
    const reread = (n) => ctx.act(async () => { await api.runReader(pid, id, n); setPc(await api.piece(pid, id)); await ctx.refresh(); }, "Le studio relance ce lecteur.");
    useCmds(ctx, pc ? [
      !pc.decision && { id: "keep", label: "Garder " + pc.label, run: () => send("keep") },
      { id: "take", label: "Télécharger " + pc.label + " en png", run: take },
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
      pc.judge && h("div", { className: "juge", "aria-live": "polite" }, h("p", { className: "cap" }, "Le juge"),
        pc.judge.status === "running" ? h("p", { className: "small muted" }, "Le juge relit la pièce. Tu peux trancher sans l'attendre.")
          : pc.judge.status === "failed" ? h("p", { className: "small" }, "Le juge n'a pas pu la relire : " + dot(pc.judge.error) + ". ",
            h("button", { type: "button", className: "linkbtn", disabled: ctx.busy, onClick: rejudge, "aria-label": "Relancer le juge sur " + pc.label }, "Relancer"))
          : h(Verdict, { v: pc.judge.verdict })),
      h(Readers, { readers: pc.readers, busy: ctx.busy, run: reread }),
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
          // a piece already kept comes back to be taken out: "Télécharger" leads, "Renvoyer" (going back on the decision) is the second gesture
          pc.decision && h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: take, "aria-label": "Télécharger la pièce en png, à sa taille : " + pc.size[0] + " par " + pc.size[1] }, "Télécharger"),
          h(Button, { variant: "secondary", size: "lg", onClick: () => setBack(true), "aria-label": pc.decision ? "Revenir sur cette décision et renvoyer la pièce" : "Renvoyer la pièce en disant pourquoi" }, "Renvoyer"),
          !pc.decision && h(Button, { variant: "secondary", size: "lg", disabled: ctx.busy, onClick: take, "aria-label": "Télécharger la pièce en png, à sa taille : " + pc.size[0] + " par " + pc.size[1] }, "Télécharger")))));
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

  /* which project and which step a task belongs to, said above it: the core must not make you wonder where you are */
  const KIND_STEP = { brief: "brief", mandates: "mandates", "diverge-launch": "diverge", "diverge-pick": "diverge", prompt: "image", compose: "piece", decide: "decide" };
  function whereLine(t) {
    if (t.scope === "brand") return (t.brand_name || "") + " · La marque";
    const key = t.step === "check" ? "piece" : t.step || KIND_STEP[t.kind], s = SEVEN.find((x) => x.key === key);
    return (t.project_name || "") + " · " + (s ? s.label : "La série");
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

  /* what waits across the studio, without the wall: the next task of each project and of each brand (the oldest), the others behind "et n autres" */
  function nextPerOwner(tasks) {
    const groups = [];
    tasks.forEach((t) => {
      const key = owner(t), g = groups.find((x) => x.key === key);
      if (g) g.rest.push(t); else groups.push({ key, first: t, rest: [] });
    });
    return groups;
  }

  /* ---------- 1. the studio: what waits everywhere, then the brands ---------- */
  function StudioCol({ ctx }) {
    const { tasks, brands, jobs, loaded } = ctx.data, { sel } = ctx;
    const judgements = useLive(ctx, () => api.judgements(), "judgements");
    const level = ctx.level(0);
    const total = (b) => b.waiting + b.projects.reduce((n, p) => n + p.waiting, 0);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h("h2", { className: "sr" }, "Le studio")),
      h(Row, { col: 0, select: true, sel: !sel.brand && !sel.panel && !sel.judgement ? level : null, onClick: ctx.selectStudio, label: "Tout le studio : " + plural(tasks.length, "chose t'attend", "choses t'attendent") },
        h("span", { className: "main" }, h("span", { className: "nom" }, "Le studio")), h(Count, { n: tasks.length })),
      h(JobLine, { jobs }),
      ctx.machine.missing.length > 0 && h("div", { className: "machine", role: "status", "data-machine": "missing" },
        h("p", { className: "cap" }, "Il manque à ce poste"),
        h("ul", null, ctx.machine.missing.map((m) => h("li", { key: m.key, className: "small" }, h("strong", null, m.label), " : ", m.say)))),
      h(Where, null, "Ce qui t'attend"),
      !loaded ? h("p", { className: "vide" }, "Un instant.") : tasks.length === 0 ? h("p", { className: "vide" }, jobs.length ? "Rien pour l'instant : le studio travaille." : "Rien ne t'attend.")
        : nextPerOwner(tasks).map((g) => h("div", { key: g.key, className: "owner" }, h(TaskRow, { ctx, col: 0, t: g.first, place: true }),
          g.rest.length > 0 && h("button", { type: "button", className: "linkbtn small autres", onClick: () => (g.first.scope === "brand" ? ctx.selectBrand(g.first.brand) : ctx.selectProject(g.first.project, null, g.first.brand)),
            "aria-label": plural(g.rest.length, "autre tâche", "autres tâches") + " pour " + (g.first.scope === "brand" ? g.first.brand_name : g.first.project_name) + " : ouvrir" }, "et " + plural(g.rest.length, "autre", "autres")))),
      h("div", { className: "groupe split" }, h("span", null, "Marques"), h(Plus, { label: "Nouvelle marque", onClick: ctx.newBrand })),
      loaded && brands.length === 0 && h("p", { className: "vide" }, "Aucune marque. Le « + » en crée une."),
      brands.map((b) => h(Row, { key: b.id, col: 0, select: true, sel: sel.brand === b.id ? level : null, onClick: () => ctx.selectBrand(b.id),
        label: b.name + ", " + (BRAND_STAGE[b.stage] || b.stage).toLowerCase() + (total(b) ? ", " + plural(total(b), "tâche", "tâches") : "") },
        h("span", { className: "main" }, h("span", { className: "nom" }, b.name), h("span", { className: "meta" }, BRAND_STAGE[b.stage] || b.stage)), h(Count, { n: total(b) }))),
      h(Where, null, "Le juge"),
      h(Row, { col: 0, select: true, sel: sel.panel === "newJudge" ? level : null, onClick: ctx.newJudge, label: "Juger une pièce : déposer une image et son brief" },
        h("span", { className: "main" }, h("span", { className: "nom" }, "Juger une pièce"), h("span", { className: "meta" }, "Une image, son brief, un verdict"))),
      (judgements || []).map((j) => h(Row, { key: j.id, col: 0, select: true, sel: sel.judgement === j.id ? level : null, onClick: () => ctx.selectJudgement(j.id),
        label: j.name + ", " + JUDGEMENT_WORD[j.status].toLowerCase() + (j.brand_name ? ", " + j.brand_name : "") },
        h("span", { className: "main" }, h("span", { className: "nom" }, j.name), h("span", { className: "meta" }, [JUDGEMENT_WORD[j.status], j.brand_name, day(j.at)].filter(Boolean).join(" · "))))),
      h(Where, null, "Réglages"), // engines
      h(Row, { col: 0, select: true, sel: sel.panel === "settings" ? level : null, onClick: ctx.openSettings, label: "Réglages : choisir les moteurs d'image et de texte" },
        h("span", { className: "main" }, h("span", { className: "nom" }, "Réglages"), h("span", { className: "meta" }, "Les moteurs d'image et de texte"))));
  }
  const JUDGEMENT_WORD = { running: "Le juge relit", done: "Jugée", failed: "Le juge a échoué" };
  const day = (sec) => sec ? new Date(sec * 1000).toLocaleDateString("fr-FR", { day: "numeric", month: "short" }) : "";

  /* ---------- 2. a brand: its brief, its assets, its projects ---------- */
  const BRIEF_BITS = [["what", ", c'est "], ["who", ". Elle parle "], ["voice", ". Sa voix : "], ["signature", ". Sa signature : « ", " »"], ["never", ". Elle ne dit jamais : "], ["colours", ". Ses couleurs : "]];

  function BrandCol({ ctx, bid }) {
    const b = useLive(ctx, () => api.getBrand(bid), bid);
    const jobs = ctx.data.jobs.filter((j) => j.brand === bid && !j.project);
    const level = ctx.level(1);
    const [fold, setFold] = useState(null); // the identity and the assets, folded under a title; open of itself only while the brand has no project to show
    if (!b) return h("div", { className: "colhead" }, h(Eyebrow, null, "Marque"), h("p", { className: "vide" }, "Un instant."));
    const shown = fold === null ? b.projects.length === 0 : fold;
    const a = b.assets, id = b.identity;
    const known = BRIEF_BITS.filter(([k]) => id[k].state !== "absent");
    const logo = a.logo;
    /* what the missing logo and colours mean now: while the site is read or the visuals are sorted, they are not missing yet */
    const reading = b.stage === "discovering", unsorted = a.evidence.some((e) => typeof e.kept !== "boolean");
    const noLogo = reading ? "Le studio lit le site : le logo viendra de là." : unsorted ? "Le logo se choisit pendant le tri des visuels."
      : a.logos.length ? "Le logo reste à choisir parmi " + plural(a.logos.length, "candidat", "candidats") + "." : "Pas de logo : sans lui, la marque ne peut pas être prête.";
    const noColours = reading ? "Le studio les cherche sur le site." : unsorted ? "Elles se mesurent sur les visuels gardés, après le tri." : "Pas encore de couleur.";
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
      h("button", { type: "button", className: "groupe fold", "aria-expanded": shown, "aria-controls": "ident", onClick: () => setFold(!shown) }, h("span", null, "Identité et assets"), h("span", { className: "small" }, shown ? "Replier" : "Voir")),
      shown && h("div", { id: "ident" }, h(Where, null, "Son brief"),
      known.length === 0 ? h("p", { className: "vide" }, reading ? "Le studio lit le site : le brief se pré-remplit avec ce qu'il y trouve." : "Pas encore de brief : il se fait en une phrase.")
        : h("p", { className: "bphrase" }, b.name, BRIEF_BITS.map(([k, before, after]) => id[k].state === "absent" ? null :
          h(React.Fragment, { key: k }, before, h("span", { className: "v", "data-state": id[k].state, title: id[k].state === "deduced" ? "Déduit par le studio, à confirmer" : undefined }, k === "colours" && /^[#0-9a-f,;\s]+$/i.test(id[k].value) ? h(Pastilles, { list: (id[k].value.match(/#[0-9a-f]{3,6}\b/gi) || []).map((x) => ({ hex: x })) }) : (BRAND_SHOW[k] || dot)(id[k].value),
            id[k].state === "deduced" && h("span", { className: "sr" }, " (à confirmer)")), after || "")), "."),
      h(Where, null, "Ses assets"),
      h("div", { className: "assets" },
        h("div", { className: "asset" }, h("span", { className: "cap" }, "Logo"),
          logo ? h("div", { className: "logobox" }, h("img", { src: logo.preview, alt: "Logo " + deName(b.name) }), h("span", { className: "small muted" }, logo.state === "deduced" ? "à confirmer" : "confirmé"))
            : h("p", { className: "small muted" }, noLogo),
          h("div", null, h(LogoDrop, { ctx, bid, label: logo ? "Changer de logo" : "Déposer un logo", variant: logo ? "ghost" : "secondary", onDone: (r) => ctx.notify("Logo déposé : " + r.name + " a un logo.") }))),
        h("div", { className: "asset" }, h("span", { className: "cap" }, "Couleurs"), a.colours.length ? h(Swatches, { colours: a.colours, mini: true }) : h("p", { className: "small muted" }, noColours),
          a.colours.some((c) => c.state === "deduced") && h("span", { className: "small muted" }, "à confirmer"),
          a.colours.length < 2 && !reading && !unsorted && h("span", { className: "small muted" }, "Il en faut deux, une pour le fond et une pour le texte.")),
        h("div", { className: "asset" }, h("span", { className: "cap" }, "Visuels gardés" + (a.visuals.length ? " · " + a.visuals.length : "")),
          a.visuals.length ? h("ul", { className: "thumbs", "aria-label": "Visuels gardés" }, a.visuals.map((v) => h("li", { key: v.id }, h("img", { src: v.preview, alt: v.note, title: v.note }))))
            : h("p", { className: "small muted" }, reading ? "Le studio lit le site." : b.can_discover ? "Aucun pour l'instant." : "Aucun : la marque n'a pas de site à lire.")))),
      h(Names, { ctx, bid }),
      h(Personas, { ctx, bid }),
      h(Competitors, { ctx, bid }));
  }

  /* ---------- the names of a brand: the studio proposes up to eight, the person keeps or drops each, or writes one, and chooses one of
     the kept as the brand's name (its id does not change) ---------- */
  const NAMES_MAX = 8;
  function Names({ ctx, bid }) {
    const data = useLive(ctx, () => api.names(bid), bid);
    const [ed, setEd] = useState(null); // the list being decided, [{name, why, kept}] (`kept` false: a proposal not decided yet); null: nothing touched
    useEffect(() => setEd(null), [bid]);
    if (!data) return null;
    const list = ed || data.names.map((x) => ({ ...x, kept: true })).concat(data.proposed.map((x) => ({ ...x, kept: false })));
    const kept = list.filter((x) => x.kept).length, undecided = list.length - kept;
    const change = (i, o) => setEd(list.map((x, k) => (k === i ? { ...x, ...o } : x)));
    const drop = (i) => setEd(list.filter((x, k) => k !== i));
    const dirty = ed !== null || data.proposed.length > 0;
    const propose = () => ctx.act(async () => { await api.proposeNames(bid); ctx.log("@" + bid, "toi", "Noms demandés au studio", ""); await ctx.refresh(); ctx.touch(); });
    const save = (chosen) => ctx.act(async () => {
      const names = list.filter((x) => x.kept && x.name.trim()).map((x) => ({ name: x.name.trim(), why: x.why || "" }));
      await api.saveNames(bid, names, chosen);
      ctx.log("@" + bid, "toi", chosen ? "Nom choisi : " + chosen : "Noms enregistrés", plural(names.length, "nom gardé", "noms gardés"));
      setEd(null); ctx.touch(); await ctx.refresh();
      ctx.notify(chosen ? "La marque s'appelle maintenant " + chosen + "." : plural(names.length, "nom est gardé", "noms sont gardés") + " dans la marque.");
    });
    return h("div", { id: "names" }, h(Where, null, "Ses noms"),
      h("p", { className: "small muted" }, "Son nom aujourd'hui : " + data.name),
      data.job ? h("p", { className: "small muted", role: "status" }, "Le studio cherche des noms à partir du brief de la marque.")
        : list.length === 0 && h("p", { className: "vide" }, data.can_propose ? "Aucun nom proposé. Le studio peut en proposer jusqu'à huit, ou tu en écris un toi-même."
          : "Aucun nom proposé. Le studio en propose une fois le brief de la marque validé ; tu peux aussi en écrire un toi-même."),
      data.error && !data.job && h(Callout, { tone: "risk", label: "La proposition n'a pas marché" }, data.error),
      data.proposed.length > 0 && h("p", { className: "small muted" }, "Garde ou écarte chaque nom. Personne n'a vérifié qu'il est libre."),
      list.map((x, i) => h("div", { key: i, className: "editor", "data-name": x.kept ? "kept" : "proposed" },
        h("label", { htmlFor: "name-" + i, className: "small cap" }, (x.kept ? "Nom gardé " : "Proposition ") + (i + 1)),
        h("input", { id: "name-" + i, type: "text", value: x.name, readOnly: !!data.job, onChange: (e) => change(i, { name: e.target.value }) }),
        x.why && h("p", { className: "small muted" }, x.why),
        h("div", { className: "row" },
          !x.kept && h(Button, { variant: "secondary", size: "sm", disabled: kept >= NAMES_MAX || !x.name.trim(), onClick: () => change(i, { kept: true }), "aria-label": "Garder la proposition " + (i + 1) }, "Garder"),
          x.kept && x.name.trim() === data.name ? h("span", { className: "small muted" }, "C'est son nom.")
            : x.kept && h(Button, { variant: "primary", size: "sm", disabled: ctx.busy || undecided > 0 || !x.name.trim(), onClick: () => save(x.name.trim()), "aria-label": "Choisir " + x.name.trim() + " comme nom de la marque" }, "Choisir"),
          h(Button, { variant: "ghost", size: "sm", disabled: !!data.job, onClick: () => drop(i), "aria-label": (x.kept ? "Écarter le nom " : "Écarter la proposition ") + (i + 1) }, "Écarter")))),
      h("div", { className: "gestures" },
        h(Button, { variant: "secondary", size: "sm", disabled: kept >= NAMES_MAX || !!data.job, onClick: () => setEd(list.concat([{ name: "", why: "", kept: true }])), "aria-label": "Écrire un nom toi-même" }, "Écrire un nom"),
        data.can_propose && !data.job && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy || dirty, onClick: propose, "aria-label": "Demander au studio de proposer des noms" }, list.length ? "En proposer d'autres" : "Proposer des noms"),
        dirty && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy || undecided > 0, onClick: () => save(), "aria-label": "Enregistrer les noms gardés dans la marque" }, "Enregistrer")),
      dirty && undecided > 0 && h("p", { className: "small muted", role: "status" }, "Garde ou écarte chaque proposition avant de choisir ou d'enregistrer."),
      kept >= NAMES_MAX && h("p", { className: "small muted" }, "Huit noms au plus."));
  }

  /* ---------- the personas of a brand: the studio proposes up to four, the person corrects each, keeps or drops it, or writes one by hand.
     Only the kept ones are saved in the brand ---------- */
  const PERSONAS_MAX = 4;
  function Personas({ ctx, bid }) {
    const data = useLive(ctx, () => api.personas(bid), bid);
    const [ed, setEd] = useState(null); // the list being corrected, [{text, kept}] (`kept` false: a proposal not decided yet); null: nothing touched
    useEffect(() => setEd(null), [bid]);
    if (!data) return null;
    const list = ed || data.personas.map((text) => ({ text, kept: true })).concat(data.proposed.map((text) => ({ text, kept: false })));
    const kept = list.filter((x) => x.kept).length, undecided = list.length - kept;
    const change = (i, o) => setEd(list.map((x, k) => (k === i ? { ...x, ...o } : x)));
    const drop = (i) => setEd(list.filter((x, k) => k !== i));
    const dirty = ed !== null || data.proposed.length > 0;
    const propose = () => ctx.act(async () => { await api.proposePersonas(bid); ctx.log("@" + bid, "toi", "Personas demandés au studio", ""); await ctx.refresh(); ctx.touch(); });
    const save = () => ctx.act(async () => {
      const texts = list.filter((x) => x.kept).map((x) => x.text.trim()).filter(Boolean);
      await api.savePersonas(bid, texts);
      ctx.log("@" + bid, "toi", "Personas enregistrés", plural(texts.length, "persona gardé", "personas gardés"));
      setEd(null); ctx.touch(); ctx.notify(texts.length ? plural(texts.length, "persona est enregistré", "personas sont enregistrés") + " dans la marque." : "La marque n'a plus de persona.");
    });
    return h("div", { id: "personas" }, h(Where, null, "Ses personas"),
      data.job ? h("p", { className: "small muted", role: "status" }, "Le studio imagine les personas à partir de ce qu'il sait de la marque.")
        : list.length === 0 && h("p", { className: "vide" }, data.can_propose ? "Aucun persona. Le studio peut en proposer jusqu'à quatre, ou tu les écris toi-même."
          : "Aucun persona. Le studio en propose une fois le brief de la marque validé ; tu peux aussi les écrire toi-même."),
      data.error && !data.job && h(Callout, { tone: "risk", label: "La proposition n'a pas marché" }, data.error),
      data.proposed.length > 0 && h("p", { className: "small muted" }, "Ce sont des hypothèses à corriger : chaque ligne dit si elle vient du dossier ou si elle est supposée. Corrige, garde ou écarte chacun."),
      list.map((x, i) => h("div", { key: i, className: "editor", "data-persona": x.kept ? "kept" : "proposed" },
        h("label", { htmlFor: "persona-" + i, className: "small cap" }, (x.kept ? "Persona gardé " : "Proposition ") + (i + 1)),
        h("textarea", { id: "persona-" + i, rows: 7, value: x.text, readOnly: !!data.job, onChange: (e) => change(i, { text: e.target.value }) }),
        h("div", { className: "row" },
          !x.kept && h(Button, { variant: "secondary", size: "sm", disabled: kept >= PERSONAS_MAX || !x.text.trim(), onClick: () => change(i, { kept: true }), "aria-label": "Garder la proposition " + (i + 1) }, "Garder"),
          h(Button, { variant: "ghost", size: "sm", disabled: !!data.job, onClick: () => drop(i), "aria-label": (x.kept ? "Écarter le persona " : "Écarter la proposition ") + (i + 1) }, "Écarter")))),
      h("div", { className: "gestures" },
        h(Button, { variant: "secondary", size: "sm", disabled: kept >= PERSONAS_MAX || !!data.job, onClick: () => setEd(list.concat([{ text: "", kept: true }])), "aria-label": "Écrire un persona toi-même" }, "Écrire un persona"),
        data.can_propose && !data.job && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy || dirty, onClick: propose, "aria-label": "Demander au studio de proposer des personas" }, list.length ? "En proposer d'autres" : "Proposer des personas"),
        dirty && h(Button, { variant: "primary", size: "sm", disabled: ctx.busy || undecided > 0, onClick: save, "aria-label": "Enregistrer les personas gardés dans la marque" }, "Enregistrer")),
      dirty && undecided > 0 && h("p", { className: "small muted", role: "status" }, "Garde ou écarte chaque proposition avant d'enregistrer."),
      kept >= PERSONAS_MAX && h("p", { className: "small muted" }, "Quatre personas au plus."));
  }

  /* ---------- competitors of a brand: the studio proposes up to six, the person corrects each, keeps or drops it, or writes one by hand.
     Only the kept ones are saved in the brand ---------- */
  const COMPETITORS_MAX = 6;
  function Competitors({ ctx, bid }) {
    const data = useLive(ctx, () => api.competitors(bid), bid);
    const [ed, setEd] = useState(null); // the list being corrected, [{text, kept}] (`kept` false: a proposal not decided yet); null: nothing touched
    useEffect(() => setEd(null), [bid]);
    if (!data) return null;
    const list = ed || data.competitors.map((text) => ({ text, kept: true })).concat(data.proposed.map((text) => ({ text, kept: false })));
    const kept = list.filter((x) => x.kept).length, undecided = list.length - kept;
    const change = (i, o) => setEd(list.map((x, k) => (k === i ? { ...x, ...o } : x)));
    const drop = (i) => setEd(list.filter((x, k) => k !== i));
    const dirty = ed !== null || data.proposed.length > 0;
    const propose = () => ctx.act(async () => { await api.proposeCompetitors(bid); ctx.log("@" + bid, "toi", "Concurrents demandés au studio", ""); await ctx.refresh(); ctx.touch(); });
    const save = () => ctx.act(async () => {
      const texts = list.filter((x) => x.kept).map((x) => x.text.trim()).filter(Boolean);
      await api.saveCompetitors(bid, texts);
      ctx.log("@" + bid, "toi", "Concurrents enregistrés", plural(texts.length, "concurrent gardé", "concurrents gardés"));
      setEd(null); ctx.touch(); ctx.notify(texts.length ? plural(texts.length, "concurrent est enregistré", "concurrents sont enregistrés") + " dans la marque." : "La marque n'a plus de concurrent.");
    });
    return h("div", { id: "concurrents" }, h(Where, null, "Ses concurrents"),
      data.job ? h("p", { className: "small muted", role: "status" }, "Le studio cherche les concurrents à partir de ce qu'il sait de la marque et du marché.")
        : list.length === 0 && h("p", { className: "vide" }, data.can_propose ? "Aucun concurrent. Le studio peut en proposer jusqu'à six, ou tu les écris toi-même."
          : "Aucun concurrent. Le studio en propose une fois le brief de la marque validé ; tu peux aussi les écrire toi-même."),
      data.error && !data.job && h(Callout, { tone: "risk", label: "La proposition n'a pas marché" }, data.error),
      data.proposed.length > 0 && h("p", { className: "small muted" }, "Ce sont des hypothèses à vérifier : chaque fiche dit si elle vient du dossier ou si elle est supposée. Corrige, garde ou écarte chacune."),
      list.map((x, i) => h("div", { key: i, className: "editor", "data-competitor": x.kept ? "kept" : "proposed" },
        h("label", { htmlFor: "concurrent-" + i, className: "small cap" }, (x.kept ? "Concurrent gardé " : "Proposition ") + (i + 1)),
        h("textarea", { id: "concurrent-" + i, rows: 4, value: x.text, readOnly: !!data.job, onChange: (e) => change(i, { text: e.target.value }) }),
        h("div", { className: "row" },
          !x.kept && h(Button, { variant: "secondary", size: "sm", disabled: kept >= COMPETITORS_MAX || !x.text.trim(), onClick: () => change(i, { kept: true }), "aria-label": "Garder la proposition " + (i + 1) }, "Garder"),
          h(Button, { variant: "ghost", size: "sm", disabled: !!data.job, onClick: () => drop(i), "aria-label": (x.kept ? "Écarter le concurrent " : "Écarter la proposition ") + (i + 1) }, "Écarter")))),
      h("div", { className: "gestures" },
        h(Button, { variant: "secondary", size: "sm", disabled: kept >= COMPETITORS_MAX || !!data.job, onClick: () => setEd(list.concat([{ text: "", kept: true }])), "aria-label": "Écrire un concurrent toi-même" }, "Écrire un concurrent"),
        data.can_propose && !data.job && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy || dirty, onClick: propose, "aria-label": "Demander au studio de proposer des concurrents" }, list.length ? "En proposer d'autres" : "Proposer des concurrents"),
        dirty && h(Button, { variant: "primary", size: "sm", disabled: ctx.busy || undecided > 0, onClick: save, "aria-label": "Enregistrer les concurrents gardés dans la marque" }, "Enregistrer")),
      dirty && undecided > 0 && h("p", { className: "small muted", role: "status" }, "Garde ou écarte chaque proposition avant d'enregistrer."),
      kept >= COMPETITORS_MAX && h("p", { className: "small muted" }, "Six concurrents au plus."));
  }

  /* ---------- texts of a project: the studio proposes up to six hooks and posts, the person corrects each, keeps or drops it, or writes one by hand.
     Only the kept ones are saved in the project, and copied in one gesture ---------- */
  const TEXTS_MAX = 6;
  function Texts({ ctx, pid }) {
    const data = useLive(ctx, () => api.texts(pid), pid);
    const [ed, setEd] = useState(null); // the list being corrected, [{text, kept}] (`kept` false: a proposal not decided yet); null: nothing touched
    useEffect(() => setEd(null), [pid]);
    if (!data) return null;
    const list = ed || data.texts.map((text) => ({ text, kept: true })).concat(data.proposed.map((text) => ({ text, kept: false })));
    const kept = list.filter((x) => x.kept).length, undecided = list.length - kept;
    const change = (i, o) => setEd(list.map((x, k) => (k === i ? { ...x, ...o } : x)));
    const drop = (i) => setEd(list.filter((x, k) => k !== i));
    const dirty = ed !== null || data.proposed.length > 0;
    const propose = () => ctx.act(async () => { await api.proposeTexts(pid); ctx.log(pid, "toi", "Textes demandés au studio", ""); await ctx.refresh(); ctx.touch(); });
    const save = () => ctx.act(async () => {
      const texts = list.filter((x) => x.kept).map((x) => x.text.trim()).filter(Boolean);
      await api.saveTexts(pid, texts);
      ctx.log(pid, "toi", "Textes enregistrés", plural(texts.length, "texte gardé", "textes gardés"));
      setEd(null); ctx.touch(); ctx.notify(texts.length ? plural(texts.length, "texte est enregistré", "textes sont enregistrés") + " dans le projet." : "Le projet n'a plus de texte.");
    });
    const copy = (text) => navigator.clipboard.writeText(text).then(() => ctx.notify("Texte copié."), () => ctx.notify("La copie n'a pas marché : sélectionne le texte et copie-le."));
    return h("div", { id: "textes" }, h(Where, null, "Ses textes"),
      data.job ? h("p", { className: "small muted", role: "status" }, "Le studio écrit les textes à partir du brief et de la marque.")
        : list.length === 0 && h("p", { className: "vide" }, data.can_propose ? "Aucun texte. Le studio peut en proposer jusqu'à six, ou tu les écris toi-même."
          : "Aucun texte. Le studio en propose une fois le brief validé ; tu peux aussi les écrire toi-même."),
      data.error && !data.job && h(Callout, { tone: "risk", label: "La proposition n'a pas marché" }, data.error),
      data.proposed.length > 0 && h("p", { className: "small muted" }, "Relis chaque texte : rien ne doit y être que le brief ou la marque n'a dit. Corrige, garde ou écarte chacun."),
      list.map((x, i) => h("div", { key: i, className: "editor", "data-text": x.kept ? "kept" : "proposed" },
        h("label", { htmlFor: "texte-" + i, className: "small cap" }, (x.kept ? "Texte gardé " : "Proposition ") + (i + 1)),
        h("textarea", { id: "texte-" + i, rows: 3, value: x.text, readOnly: !!data.job, onChange: (e) => change(i, { text: e.target.value }) }),
        h("div", { className: "row" },
          !x.kept && h(Button, { variant: "secondary", size: "sm", disabled: kept >= TEXTS_MAX || !x.text.trim(), onClick: () => change(i, { kept: true }), "aria-label": "Garder la proposition " + (i + 1) }, "Garder"),
          x.kept && !dirty && h(Button, { variant: "secondary", size: "sm", onClick: () => copy(x.text), "aria-label": "Copier le texte " + (i + 1) }, "Copier"),
          h(Button, { variant: "ghost", size: "sm", disabled: !!data.job, onClick: () => drop(i), "aria-label": (x.kept ? "Écarter le texte " : "Écarter la proposition ") + (i + 1) }, "Écarter")))),
      h("div", { className: "gestures" },
        h(Button, { variant: "secondary", size: "sm", disabled: kept >= TEXTS_MAX || !!data.job, onClick: () => setEd(list.concat([{ text: "", kept: true }])), "aria-label": "Écrire un texte toi-même" }, "Écrire un texte"),
        data.can_propose && !data.job && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy || dirty, onClick: propose, "aria-label": "Demander au studio de proposer des textes" }, list.length ? "En proposer d'autres" : "Proposer des textes"),
        dirty && h(Button, { variant: "primary", size: "sm", disabled: ctx.busy || undecided > 0, onClick: save, "aria-label": "Enregistrer les textes gardés dans le projet" }, "Enregistrer")),
      dirty && undecided > 0 && h("p", { className: "small muted", role: "status" }, "Garde ou écarte chaque proposition avant d'enregistrer."),
      kept >= TEXTS_MAX && h("p", { className: "small muted" }, "Six textes au plus."));

  /* ---------- storyboard: "Son film". The studio proposes the script and the shots (a job); the person reads them, corrects the seconds and the words,
     saves, and only then renders the film (a job): motion made by code, an mp4 to watch and to download ---------- */
  function Storyboard({ ctx, pid }) {
    const data = useLive(ctx, () => api.storyboard(pid), pid + "|sb");
    const [ed, setEd] = useState(null); // the storyboard being corrected, { script, shots }; null: nothing touched
    useEffect(() => setEd(null), [pid]);
    if (!data || !data.can_propose) return null;
    const shots = ed ? ed.shots : data.shots, script = ed ? ed.script : data.script;
    const total = shots.reduce((a, x) => a + (Number(x.seconds) || 0), 0);
    const colours = [...new Set(data.shots.map((x) => x.colour))];
    const dirty = ed !== null, saved = data.saved && !dirty;
    const change = (i, o) => setEd({ script, shots: shots.map((x, k) => (k === i ? { ...x, ...o } : x)) });
    const propose = () => ctx.act(async () => { await api.proposeStoryboard(pid); ctx.log(pid, "toi", "Découpage du film demandé au studio", ""); await ctx.refresh(); ctx.touch(); });
    const save = () => ctx.act(async () => {
      await api.saveStoryboard(pid, script, shots.map((x) => ({ ...x, seconds: Number(x.seconds) })));
      ctx.log(pid, "toi", "Découpage du film enregistré", plural(shots.length, "plan", "plans"));
      setEd(null); ctx.touch(); ctx.notify("Le découpage est enregistré. Tu peux lancer le rendu du film.");
    });
    const render = () => ctx.act(async () => { await api.renderFilm(pid); ctx.log(pid, "toi", "Rendu du film demandé", ""); await ctx.refresh(); ctx.touch(); });
    const download = () => ctx.act(async () => saveFile(await api.downloadFilm(pid)));
    return h("div", { id: "film" }, h(Where, null, "Son film"),
      data.job ? h("p", { className: "small muted", role: "status" }, "Le studio écrit le script et le découpage à partir du brief.")
        : shots.length === 0 && h("p", { className: "vide" }, "Pas encore de film. Le studio peut écrire un script et un découpage en plans, que tu corriges avant le rendu."),
      data.error && !data.job && h(Callout, { tone: "risk", label: "Le découpage n'a pas marché" }, data.error),
      shots.length > 0 && h("div", { className: "sec" },
        !data.saved && !dirty && h("p", { className: "small muted" }, "Ce découpage est une proposition : relis-le, corrige-le, puis enregistre-le. Le rendu ne se lance qu'après."),
        h("label", { htmlFor: "sb-script", className: "small cap" }, "Le script"),
        h("textarea", { id: "sb-script", rows: 3, value: script, readOnly: !!data.job, onChange: (e) => setEd({ script: e.target.value, shots }) }),
        shots.map((x, i) => h("div", { key: i, className: "editor", "data-shot": i + 1 },
          h("span", { className: "small cap" }, "Plan " + (i + 1) + " sur " + shots.length + (x.visual === "logo" ? " : le logo de la marque" : "")),
          h("div", { className: "row" },
            h("label", { htmlFor: "sb-s-" + i, className: "small" }, "Secondes"),
            h("input", { id: "sb-s-" + i, type: "number", min: 1, max: 8, step: 0.5, value: x.seconds, onChange: (e) => change(i, { seconds: e.target.value }) }),
            h("label", { htmlFor: "sb-c-" + i, className: "small" }, "Couleur"),
            h("select", { id: "sb-c-" + i, value: x.colour, onChange: (e) => change(i, { colour: e.target.value }), style: { borderLeft: "1.5rem solid " + x.colour } },
              colours.map((c) => h("option", { key: c, value: c }, c)))),
          x.visual === "texte" && h(React.Fragment, null,
            h("label", { htmlFor: "sb-t-" + i, className: "small" }, "Texte à l'écran"),
            h("input", { id: "sb-t-" + i, type: "text", maxLength: 90, value: x.text, onChange: (e) => change(i, { text: e.target.value }) })),
          h("label", { htmlFor: "sb-r-" + i, className: "small" }, "Ce qu'on lit"),
          h("input", { id: "sb-r-" + i, type: "text", maxLength: 300, value: x.read, onChange: (e) => change(i, { read: e.target.value }) }))),
        h("p", { className: "small muted", role: "status" }, "Le film fait " + total + " s" + (total >= 15 && total <= 30 ? "." : " : il en faut entre 15 et 30."))),
      h("div", { className: "gestures" },
        !data.job && h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy || dirty, onClick: propose, "aria-label": "Demander au studio d'écrire le découpage du film" }, shots.length ? "En proposer un autre" : "Écrire le découpage"),
        dirty && h(Button, { variant: "primary", size: "sm", disabled: ctx.busy || total < 15 || total > 30, onClick: save, "aria-label": "Enregistrer le découpage corrigé" }, "Enregistrer"),
        saved && !data.film_job && h(Button, { variant: "primary", size: "sm", disabled: ctx.busy, onClick: render, "aria-label": "Lancer le rendu du film" }, data.film ? "Refaire le rendu" : "Lancer le rendu")),
      data.film_job && h("p", { className: "small muted", role: "status" }, "Le studio fait le film : chaque plan est animé, capturé image par image, puis assemblé. Compte quelques minutes."),
      data.film_error && !data.film_job && h(Callout, { tone: "risk", label: "Le rendu n'a pas marché" }, data.film_error),
      data.film && !data.film_job && h("div", { className: "sec" },
        h("video", { src: data.film.url, controls: true, width: 270, "aria-label": "Le film du projet" }),
        h("div", { className: "gestures" }, h(Button, { variant: "secondary", size: "sm", disabled: ctx.busy, onClick: download, "aria-label": "Télécharger le film en mp4" }, "Télécharger le film"))));
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
    const sc = seriesCount(p.pieces);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, "Projet"), h("h2", { className: "titre" }, p.name),
        h("p", { className: "sub" }, done === 7 ? "Terminé" : "Étape " + (nowIdx + 1) + " sur 7 · " + SEVEN[nowIdx].label),
        h("button", { type: "button", className: "linkbtn modif", onClick: ctx.editProject, "aria-label": "Modifier le projet " + p.name + " : son nom" }, "Modifier")),
      h(JobLine, { jobs }),
      h("ol", { className: "etapes", "aria-label": "Les sept étapes" }, SEVEN.map((s, i) => {
        const status = st(s.key), cur = i === nowIdx;
        const word = STEP_WORD[status];
        const serie = SERIES_STEPS.includes(s.key) && p.pieces.length > 0 && status !== "todo"; // steps 5 to 7, once they have begun: "x sur y pièces"
        const count = serie ? sc[s.key] + " sur " + plural(sc.total, "pièce", "pièces") : "";
        const meta = [cur ? word : "", count].filter(Boolean).join(" · ");
        const inner = [h("i", { key: "d", "aria-hidden": "true" }), h("span", { key: "t", className: "t" }, s.label), h("span", { key: "m", className: meta ? "m" : "sr" }, meta || " : " + word)];
        const readable = status === "done" || serie;
        const open = readable ? () => ctx.selectStep(s.key) : s.key === "brand" && brandTask ? () => ctx.openTask(brandTask) : null;
        const selected = sel.detail && sel.detail.kind === "step" && sel.detail.key === s.key;
        return h("li", { key: s.key, "data-etat": status, "data-cur": cur ? "1" : undefined, "aria-current": cur ? "step" : undefined },
          open ? h("button", { type: "button", className: "etape", "data-col": 2, "data-select": readable ? "1" : undefined, "data-sel": selected ? level : undefined, "aria-current": selected ? "true" : undefined,
            onClick: open, "aria-label": (i + 1) + ". " + s.label + " : " + word + (count ? ", " + count : "") + (status === "done" ? ". Voir ce qui a été décidé" : serie ? ". Voir les pièces" : ". Ouvrir la tâche de la marque") }, inner)
            : h("div", { className: "etape" }, inner));
      })),
      p.pieces.length > 0 && h(Series, { ctx, p, col: 2 }),
      st("brief") === "done" && h(Texts, { ctx, pid }),
      st("brief") === "done" && h(Storyboard, { ctx, pid, key: pid + "|film" }),
      h(Where, null, "Ce qui attend"),
      tasks.length ? tasks.map((t) => h(TaskRow, { key: t.id, ctx, col: 2, t, place: false }))
        : st("brand") !== "done" ? h("p", { className: "vide", "data-waits": "brand" }, "Rien à faire sur le projet : il attend sa marque. ",
          brandTask ? h(React.Fragment, null, "Il lui faut : ", h("button", { type: "button", className: "linkbtn", onClick: () => ctx.openTask(brandTask), "aria-label": "Ouvrir la tâche de la marque : " + taskTitle(brandTask) }, lc1(taskTitle(brandTask))), ".")
            : p.brand_stage === "discovering" ? "Le studio lit le site de la marque." : "")
        : h("p", { className: "vide" }, done === 7 ? "Rien : le projet est terminé." : "Rien n'attend sur ce projet."));
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
    const stepDone = ((p.steps.find((x) => x.key === step) || {}).status || "todo") === "done", sc = seriesCount(p.pieces);
    const reopen = (k, extra) => ctx.openTask(synth(p, k, extra));
    let main, action;
    if (step === "brand") {
      const logo = body.assets.logo;
      main = h("div", { className: "sec" }, h("p", { className: "lead" }, "La marque est prête : " + body.name + (logo ? ", avec son logo." : ".")),
        logo && h("img", { src: logo.preview, alt: "Logo " + deName(body.name), className: "factlogo" }), body.assets.colours.length > 0 && h(Swatches, { colours: body.assets.colours, mini: true }));
      const bt = (k, title) => ({ id: "@" + body.id + ":reopen:" + k, scope: "brand", brand: body.id, brand_name: body.name, project: null, kind: k, title, reopen: true });
      action = h("div", { className: "gestures" },
        h(Button, { variant: "secondary", size: "sm", onClick: () => ctx.openTask(bt("brand-brief", "Relire le brief de la marque")), "aria-label": "Rouvrir le brief de la marque" }, "Rouvrir le brief"),
        body.assets.evidence.length > 0 && h(Button, { variant: "ghost", size: "sm", onClick: () => ctx.openTask(bt("brand-sort", "Revoir le tri des visuels")), "aria-label": "Rouvrir le tri des visuels de la marque" }, "Rouvrir le tri"));
    } else if (step === "brief") {
      const f = body.fields;
      main = h("p", { className: "sentence small" }, "Je veux " + (f.objective ? BRIEF_SHOW.objective(f.objective) : "…") + ". Pour " + (f.audience ? BRIEF_SHOW.audience(f.audience) : "…") + ". Le message : " + (f.message ? dot(f.message) : "…") + ". Sur " + body.chosen.map(fmtWord).join(", ") + (f.cta ? ". Pour finir : « " + dot(f.cta) + " »" : "") + ".");
      action = h(Button, { variant: "secondary", size: "sm", onClick: () => reopen("brief"), "aria-label": "Rouvrir le brief du projet" }, "Rouvrir");
    } else if (step === "mandates") {
      main = h("div", { className: "sec" }, h("p", { className: "lead" }, body.common), h("ul", { className: "plain" }, body.items.map((it) => h("li", { key: it.id }, h("span", { className: "cap" }, "Agent " + it.id.toUpperCase()), h("span", null, it.mandate)))));
      action = h(Button, { variant: "secondary", size: "sm", onClick: () => reopen("mandates"), "aria-label": "Rouvrir les consignes aux agents" }, "Rouvrir");
    } else if (step === "diverge") {
      const inSeries = new Set(p.pieces.map((x) => x.variant));
      main = h("ul", { className: "plain" }, body.map((v) => h("li", { key: v.id }, h("span", { className: "cap" }, v.mandate + (inSeries.has(v.id) ? " · dans la série" : "")), h("span", { className: "hl" }, v.headline), v.subline && h("span", null, v.subline))));
      action = h(Button, { variant: "secondary", size: "sm", onClick: () => reopen("diverge-pick", { readOnly: true }), "aria-label": "Rouvrir les variantes de la série" }, "Rouvrir");
    } else {
      main = p.pieces.length === 0 ? h("p", { className: "vide" }, "Pas de pièce.") : h("ul", { className: "pieces", "aria-label": "Les pièces" }, p.pieces.map((pc) => { const w = STAGE_WORDS[stageOf(pc, p.jobs)], src = pieceSrc(pc);
        return h("li", { key: pc.id }, h("button", { type: "button", className: "row", "data-col": 3, onClick: () => reopen("piece-any", { piece: pc.id, title: pc.label }), "aria-label": (stepDone ? "Rouvrir " : "Ouvrir ") + pc.label + " : " + w.toLowerCase() },
          h("span", { className: "vf mini", style: { "--ratio": pc.size[0] / pc.size[1] } }, src ? h("img", { src, alt: "" }) : null),
          h("span", { className: "main" }, h("span", { className: "nom" }, pc.label), h("span", { className: "meta" }, w)))); }));
      action = null;
    }
    const serie = SERIES_STEPS.includes(step);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, stepDone ? "Décidé" : "En cours"), h("h2", { className: "titre" }, label),
        h("p", { className: "sub" }, serie && !stepDone ? sc[step] + " sur " + plural(sc.total, "pièce", "pièces") + SERIES_WORD[step] + "." : "Étape faite. Ce qui a été décidé, tel quel.")),
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
        // a new site is not read by itself: the notice offers it, so that nobody has to remember to come back to this form
        ctx.close(siteChanged && f.site.trim() ? { text: f.name.trim() + " est enregistrée. Son nouveau site n'est pas encore lu.", action: { label: "Relire le site", run: () => rereadSite(f.name.trim()) } } : f.name.trim() + " est enregistrée.");
      });
    };
    const rereadSite = (name) => ctx.act(async () => {
      await api.discover(bid); ctx.log("@" + bid, "toi", "Site relu", "Le studio lit " + (f.site.trim() ? host(f.site.trim()) : "le site"));
      await ctx.refresh(); ctx.touch(); ctx.notify("Le studio relit le site " + deName(name) + ".");
    }, "Le studio relit le site.");
    const reread = () => ctx.act(async () => { await api.discover(bid); await ctx.refresh(); ctx.touch(); ctx.close("Le studio relit le site " + deName(b.name) + "."); }, "Le studio relit le site.");
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

  /* ---------- the judge on its own: a piece dropped with the brief it answers, then its verdict ---------- */
  const JUDGE_MAX = 10 * 1024 * 1024;
  const JPARTS = [...PARTS.filter((p) => p.k !== "format" && p.k !== "fixed" && p.k !== "cta"),
    { k: "cta", before: ". Pour finir : « ", after: " »", label: "l'appel à l'action" },
    { k: "fixed", before: ". Les assets : ", label: "le cadre (respecter ou non les assets)", empty: "rien de dit, c'est facultatif", area: true }];
  const JNEEDED = { objective: "l'objectif", audience: "la cible", message: "le message", cta: "l'appel à l'action" };

  /* ---------- engines: the settings, the engine of the images and the engine of the texts with its key ---------- */
  const TEXT_WORD = { claude: "Claude Code", openrouter: "OpenRouter" };
  const IMAGE_WORD = { auto: "Au choix du studio", openai: "OpenAI", openrouter: "OpenRouter", codex: "Codex", none: "Aucun" };
  function Settings({ ctx }) {
    const [cfg, setCfg] = useState(null), [image, setImage] = useState(""), [text, setText] = useState(""), [model, setModel] = useState(""), [key, setKey] = useState("");
    const show = (c) => { setCfg(c); setImage(c.image_engine); setText(c.text_engine); setModel(c.openrouter_model); setKey(""); };
    useEffect(() => { api.engines().then(show).catch(ctx.fail); }, []);
    const saveImage = (e) => { e.preventDefault(); ctx.act(async () => { show(await api.saveEngine(image)); ctx.notify("Le moteur d'image est enregistré."); }); };
    const saveText = (e) => { e.preventDefault(); ctx.act(async () => { show(await api.saveTextEngine(text, key.trim() || undefined, model.trim() || undefined)); ctx.notify("Le moteur de texte est enregistré."); }); };
    const forget = () => ctx.act(async () => { show(await api.saveTextEngine(text, "")); ctx.notify("La clé est oubliée."); });
    return h(React.Fragment, null, h("div", { className: "colhead" }, h(Eyebrow, null, "Studio"), h("h2", { className: "titre" }, "Réglages")),
      !cfg ? h("p", { className: "vide" }, "Un instant.") : h(React.Fragment, null,
        h("form", { className: "sec form", onSubmit: saveImage },
          h("div", { className: "field" }, h("label", { htmlFor: "st-image" }, "Moteur d'image"),
            h("select", { id: "st-image", value: image, onChange: (e) => setImage(e.target.value) }, cfg.image_engines.map((k) => h("option", { key: k, value: k }, IMAGE_WORD[k] || k)))),
          h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "md", disabled: ctx.busy || image === cfg.image_engine, "aria-label": "Enregistrer le moteur d'image" }, "Enregistrer"))),
        h("form", { className: "sec form", onSubmit: saveText },
          h("div", { className: "field" }, h("label", { htmlFor: "st-text" }, "Moteur de texte"),
            h("select", { id: "st-text", value: text, onChange: (e) => setText(e.target.value) }, cfg.text_engines.map((k) => h("option", { key: k, value: k }, TEXT_WORD[k] || k)))),
          text === "openrouter" && h(React.Fragment, null,
            h("div", { className: "field" }, h("label", { htmlFor: "st-key" }, "Clé OpenRouter"),
              h("input", { id: "st-key", type: "password", value: key, onChange: (e) => setKey(e.target.value), autoComplete: "off", placeholder: cfg.key_saved ? "Une clé est enregistrée" : "", "aria-describedby": "st-key-hint" }),
              h("span", { id: "st-key-hint", className: "small muted", "data-key-saved": cfg.key_saved }, cfg.key_saved ? "Une clé est enregistrée. Elle reste sur ce poste et ne s'affiche jamais. Écris-en une autre pour la remplacer." : "Aucune clé enregistrée. Elle reste sur ce poste et ne s'affiche jamais.")),
            h("div", { className: "field" }, h("label", { htmlFor: "st-model" }, "Modèle"), h("input", { id: "st-model", type: "text", value: model, onChange: (e) => setModel(e.target.value), autoComplete: "off" }))),
          h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "md", disabled: ctx.busy || (text === "openrouter" && !key.trim() && !cfg.key_saved), "aria-label": "Enregistrer le moteur de texte" }, "Enregistrer"),
            text === "openrouter" && cfg.key_saved && h(Button, { type: "button", variant: "ghost", size: "md", onClick: forget, disabled: ctx.busy, "aria-label": "Oublier la clé" }, "Oublier la clé"),
            h(Button, { type: "button", variant: "ghost", size: "md", onClick: ctx.close, "aria-label": "Fermer les réglages" }, "Fermer")))));
  }

  function JudgeForm({ ctx }) {
    const [file, setFile] = useState(null);
    const [url, setUrl] = useState(null);
    const [fields, setFields] = useState({ objective: "", audience: "", message: "", cta: "", fixed: "", personas: [] });
    const [open, setOpen] = useState(null);
    const [brand, setBrand] = useState("");
    const input = useRef(null);
    useEscapeClose(ctx, open, setOpen);
    useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
    const pick = (ev) => {
      const f = ev.target.files && ev.target.files[0];
      ev.target.value = "";
      if (!f) return;
      if (!/^image\/(png|jpeg)$/.test(f.type)) { ctx.fail(new Error("Une pièce à juger se dépose en png ou en jpg.")); return; }
      if (f.size > JUDGE_MAX) { ctx.fail(new Error("Ce fichier fait plus de 10 Mo.")); return; }
      setFile(f); setUrl(URL.createObjectURL(f));
    };
    const set = (k, v) => setFields({ ...fields, [k]: v });
    const missing = Object.keys(JNEEDED).filter((k) => !fields[k].trim());
    const piece = (p) => h(React.Fragment, { key: p.k }, p.before, h("span", {
      role: "button", tabIndex: 0, className: "bit", "data-bit": p.k, "aria-expanded": open === p.k, "aria-label": "Écrire " + p.label + " : " + (fields[p.k] || "vide"),
      "data-open": open === p.k, onClick: () => setOpen(open === p.k ? null : p.k),
      onKeyDown: (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); setOpen(open === p.k ? null : p.k); } },
    }, fields[p.k].trim() ? (BRIEF_SHOW[p.k] || dot)(fields[p.k]) : h("span", { className: "blank" }, p.empty || "à écrire")), p.after || "");
    const cur = JPARTS.find((p) => p.k === open);
    const launch = () => ctx.act(async () => {
      const jg = await api.judge(file, { brand: brand || null, brief: fields });
      ctx.touch(); await ctx.refresh();
      ctx.selectJudgement(jg.id, "Le juge relit " + jg.name + ".");
    }, "Le studio envoie la pièce au juge.");
    return h(React.Fragment, null, h("div", { className: "colhead" }, h(Eyebrow, null, "Le juge"), h("h2", { className: "titre" }, "Juger une pièce")),
      h("div", { className: "sec form" },
        h("input", { ref: input, type: "file", className: "sr", accept: "image/png,image/jpeg", onChange: pick, tabIndex: -1, "aria-hidden": "true" }),
        url && h("figure", { className: "frame wide" }, h("img", { src: url, alt: "La pièce à juger : " + file.name })),
        h("div", null, h(Button, { variant: file ? "ghost" : "secondary", size: "md", disabled: ctx.busy, onClick: () => input.current && input.current.click(), "aria-label": (file ? "Changer d'image" : "Déposer l'image de la pièce") + " (png ou jpg, 10 Mo au plus)" }, file ? "Changer d'image" : "Déposer l'image")),
        h("p", { className: "small muted" }, "Le brief d'origine, celui auquel la pièce répond. Touche un passage pour l'écrire."),
        h("p", { className: "sentence" }, JPARTS.map(piece), "."),
        cur && h("div", { className: "editor" },
          h("label", { htmlFor: "jed", className: "small" }, "Écrire " + cur.label),
          cur.area ? h("textarea", { id: "jed", autoFocus: true, value: fields[cur.k], onChange: (e) => set(cur.k, e.target.value) })
            : h("input", { id: "jed", type: "text", autoFocus: true, value: fields[cur.k], onChange: (e) => set(cur.k, e.target.value), onKeyDown: (e) => { if (e.key === "Enter") setOpen(null); } }),
          h("div", { className: "row" }, h(Button, { variant: "secondary", size: "sm", onClick: () => setOpen(null), "aria-label": "Terminer : " + cur.label }, "Fait"))),
        h(BriefPersonas, { list: fields.personas, set: (v) => set("personas", v), id: "jpe" }),
        h("div", { className: "field" }, h("label", { htmlFor: "jb" }, "Sa marque (facultatif)"),
          h("select", { id: "jb", value: brand, onChange: (e) => setBrand(e.target.value), "aria-describedby": "jb-hint" }, h("option", { value: "" }, "Sans marque"), ctx.data.brands.map((b) => h("option", { key: b.id, value: b.id }, b.name))),
          h("span", { id: "jb-hint", className: "small muted" }, "Avec une marque, le juge regarde aussi sa voix et son ton.")),
        h("div", { className: "gestures" }, h(Button, { variant: "primary", size: "md", disabled: ctx.busy || !file, onClick: launch, "aria-label": "Lancer le juge sur cette pièce" }, "Lancer le juge"),
          h(Button, { variant: "ghost", size: "md", onClick: () => ctx.close(), "aria-label": "Ne pas juger de pièce" }, "Annuler")),
        !file ? h("p", { className: "small muted", role: "status" }, "Il manque l'image.")
          : missing.length > 0 && h("p", { className: "small muted", role: "status" }, "Il manque " + missing.map((k) => JNEEDED[k]).join(", ") + " : le juge le dira et jugera le reste.")));
  }

  function JudgementCol({ ctx, jid }) {
    const jg = useLive(ctx, () => api.judgement(jid), jid);
    if (!jg) return h("div", { className: "colhead" }, h(Eyebrow, null, "Jugement"), h("p", { className: "vide" }, "Un instant."));
    const b = jg.brief;
    const again = () => ctx.act(async () => { await api.runJudgement(jid); ctx.touch(); await ctx.refresh(); ctx.notify("Le juge relit " + jg.name + "."); }, "Le studio relance le juge.");
    const reread = (n) => ctx.act(async () => { await api.runJudgementReader(jid, n); ctx.touch(); await ctx.refresh(); }, "Le studio relance ce lecteur.");
    const page = () => ctx.act(async () => { const f = await api.judgementPage(jid); saveFile(f); ctx.notify(f.name + " est téléchargée."); }, "Le studio prépare la page.");
    const said = [b.objective && "Je veux " + BRIEF_SHOW.objective(b.objective), b.audience && "Pour " + BRIEF_SHOW.audience(b.audience), b.message && "Le message : " + dot(b.message),
      b.cta && "Pour finir : « " + dot(b.cta) + " »", b.fixed && "Les assets : " + dot(b.fixed)].filter(Boolean);
    return h(React.Fragment, null,
      h("div", { className: "colhead" }, h(Eyebrow, null, "Jugement"), h("h2", { className: "titre" }, jg.name),
        h("p", { className: "sub" }, [jg.brand_name || "Sans marque", day(jg.at)].filter(Boolean).join(" · "))),
      h("div", { className: "bodyc" },
        jg.image && h("figure", { className: "frame wide" }, h("img", { src: jg.image, alt: "La pièce jugée : " + jg.name })),
        said.length > 0 && h("p", { className: "small muted" }, said.join(". ") + "."),
        jg.status === "running" ? h("p", { className: "muted", role: "status" }, "Le juge relit la pièce.")
          : jg.status === "failed" ? h(React.Fragment, null, h(Callout, { tone: "risk", label: "Le juge n'a pas pu la relire" }, jg.error || "raison inconnue"),
            h("div", { className: "gestures" }, h(Button, { variant: "primary", size: "md", disabled: ctx.busy, onClick: again, "aria-label": "Relancer le juge sur " + jg.name }, "Relancer")))
          : h(React.Fragment, null, h(Verdict, { v: jg.verdict }),
            h("div", { className: "gestures" }, h(Button, { variant: "secondary", size: "md", disabled: ctx.busy, onClick: page, "aria-label": "Télécharger la page du verdict : la pièce en haut, la liste dessous" }, "Télécharger la page"))),
        h(Readers, { readers: jg.readers, busy: ctx.busy, run: reread })));
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
  const EMPTY = { brand: null, project: null, detail: null, panel: null, task: null, judgement: null };
  function columnsOf(sel) {
    const c = ["studio"];
    if (sel.panel === "newBrand") { c.push("newBrand"); return c; }
    if (sel.panel === "newJudge") { c.push("newJudge"); return c; }
    if (sel.panel === "settings") { c.push("settings"); return c; } // engines
    if (sel.judgement) { c.push("judgement"); return c; }
    if (!sel.brand) return c;
    c.push("brand");
    if (sel.panel === "editBrand") { c.push("editBrand"); return c; }
    if (sel.panel === "newProject") { c.push("newProject"); return c; }
    if (!sel.project) return c;
    c.push("project");
    if (sel.detail) c.push(sel.detail.kind);
    return c;
  }
  const popOnce = (sel) => sel.detail ? { ...sel, detail: null, task: null } : sel.panel ? { ...sel, panel: null } : sel.judgement ? { ...sel, judgement: null } : sel.project ? { ...sel, project: null, task: null } : sel.brand ? { ...sel, brand: null, task: null } : sel;

  /* the width of the window, to know how many columns fit side by side */
  function useWidth() {
    const [w, setW] = useState(window.innerWidth);
    useEffect(() => { const f = () => setW(window.innerWidth); window.addEventListener("resize", f); return () => window.removeEventListener("resize", f); }, []);
    return w;
  }
  /* what each column asks for (the last one takes what is left, down to LAST_MIN) and what a folded one costs */
  const COL_W = [300, 360, 360, 420], LAST_MIN = 360, STRIP_W = 44;
  /* how many of the columns on the left fold into strips so that the rest fits: the least that does it (the last column is never folded) */
  function foldCount(n, width) {
    const need = (i) => STRIP_W * i + Array.from({ length: n - i }, (_, k) => (i + k === n - 1 ? LAST_MIN : COL_W[Math.min(i + k, 3)])).reduce((a, b) => a + b, 0);
    let i = 0;
    while (i < n - 1 && need(i) > width) i++;
    return i;
  }

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
    const [wait, setWait] = useState(null); // the word said while a slow gesture runs
    const [palette, setPalette] = useState(false);
    const [machine, setMachine] = useState({ ok: true, missing: [] }); // what the machine lacks (Chrome, Claude Code, an image engine); said in the studio's column
    const [rev, setRev] = useState(0);
    const [, setTick] = useState(0);
    const narrow = useNarrow();
    const width = useWidth();
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
        const STEP_OF = { learn: "brand", mandates: "mandates", diverge: "diverge", image: "image", judge: "check" };
        prevJobs.current.filter((j) => !r.jobs.some((x) => x.id === j.id) && !j.judgement && j.kind !== "reader").forEach((j) => { // a piece judged on its own has no journal, nor do the readers
          const failed = r.tasks.find((t) => t.kind === "job-failed" && (j.project ? t.project === j.project && t.step === STEP_OF[j.kind] && (t.piece || null) === (j.piece || null) : j.kind === "learn" && t.scope === "brand" && t.brand === j.brand));
          const where = j.project || "@" + j.brand;
          if (failed) log(where, "studio", "Échec : " + taskTitle(failed), failed.question);
          else log(where, "studio", j.kind === "learn" ? "Lecture du site terminée" : j.kind === "mandates" ? "Les consignes sont proposées" : j.kind === "diverge" ? "Les quatre variantes sont écrites" : j.kind === "judge" ? "Le juge a relu : " + j.piece : j.kind === "personas" ? "Les personas sont proposés" : j.kind === "names" ? "Les noms sont proposés" : j.kind === "competitors" ? "Les concurrents sont proposés" : j.kind === "texts" ? "Les textes sont proposés" : j.kind === "storyboard" ? "Le découpage du film est proposé" : j.kind === "film" ? "Le film est prêt" : "Image prête : " + j.piece, "");
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
    useEffect(() => {
      const look = () => api.machine().then(setMachine).catch(() => { /* an older server has no such route: nothing is said */ });
      look();
      const t = setInterval(look, 60000);
      return () => clearInterval(t);
    }, []);
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
    const newJudge = useCallback(() => move(() => ({ ...EMPTY, panel: "newJudge" })), [move]);
    const openSettings = useCallback(() => move(() => ({ ...EMPTY, panel: "settings" })), [move]); // engines
    const selectJudgement = useCallback((id, text) => move(() => ({ ...EMPTY, judgement: id }), text), [move]);
    const editBrand = useCallback(() => move((s) => ({ ...s, project: null, detail: null, panel: "editBrand", task: null })), [move]);
    const newProject = useCallback(() => move((s) => ({ ...s, project: null, detail: null, panel: "newProject", task: null })), [move]);
    const editProject = useCallback(() => move((s) => ({ ...s, detail: { kind: "editProject" }, task: null })), [move]);
    const showJournal = useCallback(() => move((s) => ({ ...s, detail: { kind: "journal" }, task: null })), [move]);
    const close = useCallback((text) => move((s) => ({ ...s, panel: null }), typeof text === "string" || (text && text.text) ? text : null), [move]);
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
    const act = useCallback(async (fn, word) => {
      setBusy(true); setError(null);
      const s = snap();
      const timer = setTimeout(() => setWait(word || "Un instant."), 1000); // a gesture that takes more than a second says so
      try { return await fn(s); } catch (e) { fail(e); } finally { clearTimeout(timer); setWait(null); setBusy(false); }
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

    /* acting on the whole series: every missing image, every piece ready to compose. Inside a task (`core`), the next one opens; from a column, a line says it */
    const composeAll = useCallback(async (pid, snap, core) => {
      const r = await api.composeAll(pid);
      const text = plural(r.composed.length, "pièce composée et vérifiée", "pièces composées et vérifiées") + (r.failed.length ? ". " + plural(r.failed.length, "n'a pas pu l'être", "n'ont pas pu l'être") + " : " + dot(r.failed[0].error) : "") + ".";
      log(pid, "studio", "Pièces composées d'un coup : " + r.composed.length, r.failed.map((f) => f.piece + " : " + f.error).join(" ; "));
      if (core) await answered(pid, text, { before: snap }); else { await refresh(); setRev((x) => x + 1); setNotice(text); }
    }, [answered, refresh, log]);
    const drawAll = useCallback(async (pid) => {
      const r = await api.drawImages(pid);
      log(pid, "toi", "Toutes les images lancées : " + plural(r.jobs.length, "pièce", "pièces"), "");
      await refresh(); setRev((x) => x + 1); setNotice("Toutes les images sont lancées : " + plural(r.jobs.length, "pièce", "pièces") + ".");
    }, [refresh, log]);

    const now = () => Date.now() + skew.current;
    const touch = useCallback(() => setRev((x) => x + 1), []);
    const notify = useCallback((text) => setNotice(text), []);
    /* what was just done is said once, in the core or in the columns, and goes: it is not a state of the screen */
    useEffect(() => {
      if (!notice) return;
      const t = setTimeout(() => setNotice(null), notice.action ? 20000 : 9000); // a line that offers a gesture stays a little longer
      return () => clearTimeout(t);
    }, [notice]);
    const cols = columnsOf(sel);
    const level = (i) => (i === cols.length - 1 ? "strong" : "soft");
    const ctx = { data, machine, sel, busy, act, answered, snap, log, fail, openTask, now, cmdsRef, overlayRef, arrowsRef, rev, touch, notify, refresh, level, close, closeDetail, composeAll, drawAll,
      selectStudio, selectBrand, selectProject, selectStep, newBrand, editBrand, newProject, editProject, newJudge, selectJudgement, openSettings };

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
      cmds.push({ id: "new-judge", group: "Créer", label: "Juger une pièce", run: newJudge });
      cmds.push({ id: "settings", group: "Aller", label: "Réglages : les moteurs", run: openSettings }); // engines
      const here = sel.brand || (dive && dive.brand);
      data.brands.slice().sort((a, b) => (b.id === here) - (a.id === here)).forEach((b) => cmds.push({ id: "new-project:" + b.id, group: "Créer", label: "Nouveau projet dans " + b.name, run: () => move(() => ({ ...EMPTY, brand: b.id, panel: "newProject" })) }));
      if (sel.brand && sel.project) {
        const mine = data.tasks.filter((t) => t.scope === "project" && t.project === sel.project);
        if (mine.some((t) => t.kind === "prompt")) cmds.push({ id: "draw-all", group: "Ce projet", label: "Dessiner toutes les images", run: () => act(() => drawAll(sel.project), "Le studio lance toutes les images.") });
        if (mine.filter((t) => t.kind === "compose").length > 1) cmds.push({ id: "compose-all", group: "Ce projet", label: "Composer tout", run: () => act(() => composeAll(sel.project), "Le studio compose les pièces, une par une.") });
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
        if (k === "Escape" && ev.repeat) return; // a key held down must not unwind every column, one after the other
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

    const note = notice && typeof notice === "object" ? notice : { text: notice };
    const noticeEl = h(Notice, { text: note.text, action: note.action, busy });
    const slow = wait && h("p", { className: "working slow", role: "status" }, h("b", { "aria-hidden": "true" }), wait);
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
        h("main", { id: "main", tabIndex: -1, className: "coeur" }, h("div", { className: "coeur-in" }, noticeEl, h("p", { className: "ou small muted" }, whereLine(t)), slow, err, h(Core, { ctx, t, key: t._k }))), pal);
    }

    /* ----- the columns ----- */
    const node = (kind) => kind === "studio" ? h(StudioCol, { ctx }) : kind === "newBrand" ? h(NewBrandForm, { ctx })
      : kind === "settings" ? h(Settings, { ctx }) : kind === "newJudge" ? h(JudgeForm, { ctx }) : kind === "judgement" ? h(JudgementCol, { ctx, jid: sel.judgement, key: sel.judgement }) : kind === "brand" ? h(BrandCol, { ctx, bid: sel.brand, key: sel.brand })
      : kind === "editBrand" ? h(EditBrandForm, { ctx, bid: sel.brand, key: sel.brand }) : kind === "newProject" ? h(NewProjectForm, { ctx, bid: sel.brand })
      : kind === "project" ? h(ProjectCol, { ctx, pid: sel.project, key: sel.project })
      : kind === "step" ? h(StepDetail, { ctx, pid: sel.project, step: sel.detail.key, key: sel.project + sel.detail.key })
      : kind === "journal" ? h(JournalCol, { ctx, pid: sel.project }) : h(EditProjectForm, { ctx, pid: sel.project, key: sel.project });
    const labels = { studio: "Le studio", newBrand: "Nouvelle marque", newJudge: "Juger une pièce", settings: "Réglages", judgement: "Le jugement", brand: brandName(sel.brand), editBrand: "Modifier la marque", newProject: "Nouveau projet", project: projectInfo(sel.project).name,
      step: "Ce qui a été décidé", journal: "Journal", editProject: "Modifier le projet" };
    const shell = (kind, i) => {
      const last = i === cols.length - 1;
      return h("section", { key: kind + i, className: "col c" + Math.min(i + 1, 4) + (last && i > 0 ? " last" : ""), "data-col": i, "aria-label": labels[kind] },
        last && slow, last && err, last && noticeEl, node(kind));
    };
    if (narrow) {
      const i = cols.length - 1;
      return h("div", { className: "app narrow" }, skip, h("h1", { className: "sr" }, "Studio créatif"),
        i > 0 && h("button", { type: "button", className: "retour", onClick: () => popTo(i), "aria-label": "Retour : " + labels[cols[i - 1]] }, "‹ " + labels[cols[i - 1]]),
        h("main", { id: "main", tabIndex: -1, className: "cols" }, shell(cols[i], i)), pal);
    }
    const fold = foldCount(cols.length, width); // when the columns do not fit, those on the left fold into strips that keep their names, as they do in a task
    const strip = (kind, i) => h("button", { key: "strip" + i, type: "button", className: "bande b" + Math.min(i + 1, 3), "data-strip": i, onClick: () => popTo(i + 1), "aria-label": "Revenir à : " + labels[kind] }, h("span", null, labels[kind]));
    return h("div", { className: "app" }, skip, h("h1", { className: "sr" }, "Studio créatif"),
      h("main", { id: "main", tabIndex: -1, className: "cols" }, cols.map((kind, i) => i < fold ? strip(kind, i) : shell(kind, i)),
        cols.length === 1 && h("div", { className: "rest" }, slow, err, noticeEl, h("p", { className: "muted" }, "Choisis une marque, ou ouvre une tâche. " + MOD + " K pour tout trouver."))),
      pal);
  }

  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
