/* app.js: the interface that drives the studio. React 18 without JSX, components of the design system.
   It talks to the studio only through window.studioApi (api.js, see app/API.md): no simulated data lives here.

   The idea: the home screen is the list of what waits for the person, and nothing else. A task opens on one thing and two
   gestures; the answer brings back the list (or the next task when it follows). The power lives behind "Plus" and the command
   palette (Cmd/Ctrl+K), which open the same functions. The journal is kept on this side (localStorage): the API has no journal route yet. */
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
    const left = Math.max(...jobs.map((j) => j.eta || 0));
    return "Le studio " + parts.join(" et ") + ", " + eta(left);
  }
  const FORMAT_WORDS = { "post-4x5": "post 4×5", "post-1x1": "post carré", story: "story", "poster-a3": "affiche A3", "poster-3x2": "affiche 3×2", linkedin: "bandeau 1200×627" };
  const fmtKey = (t) => t.trim().toLowerCase().replace(/ /g, "-");
  const fmtWord = (t) => FORMAT_WORDS[fmtKey(t)] || t.trim();
  const STEP_LABELS = { brand: "Apprendre la marque", brief: "Le brief", mandates: "Les consignes aux agents", diverge: "La divergence", series: "La série" };
  const SHORT = { "brand-how": "La marque", "brand-sort": "Les visuels", brief: "Le brief", mandates: "Les consignes", "diverge-launch": "La divergence", "diverge-pick": "Les variantes",
    prompt: "Le prompt", compose: "La composition", decide: "La décision" };

  /* the journal of decisions, per project, on this side */
  const loadJournal = (pid) => { try { return JSON.parse(localStorage.getItem("studio-journal:" + pid) || "[]"); } catch (e) { return []; } };
  const saveJournal = (pid, list) => { try { localStorage.setItem("studio-journal:" + pid, JSON.stringify(list.slice(0, 200))); } catch (e) { /* private window: no journal */ } };

  /* a panel gives its own commands to the palette and to "Plus": the ref holds the list of the panel on screen */
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
  const Swatches = ({ colours }) => colours.length === 0 ? h("p", { className: "muted" }, "Aucune couleur mesurée pour cette marque.") :
    h("ul", { className: "swatches", "aria-label": "Couleurs mesurées" }, colours.map((c) => h("li", { key: c.hex, className: "swatch" },
      h("i", { style: { background: c.hex }, role: "img", "aria-label": "Couleur " + c.hex }), h("span", { className: "mono small" }, c.hex))));

  /* ================= 1. brand: how to learn it ================= */
  function BrandHow({ ctx, pid }) {
    const [say, setSay] = useState(false);
    const [answers, setAnswers] = useState("");
    useCmds(ctx, []);
    const go = (mode) => ctx.act(async (snap) => {
      await api.learnBrand(pid, mode, mode === "answer" ? answers : undefined);
      const what = { learn: "Le studio cherche la marque", answer: "Tu décris la marque toi-même", create: "On part de rien" }[mode];
      ctx.log(pid, "toi", what, mode === "answer" ? answers : "");
      await ctx.answered(pid, { learn: "La recherche est lancée : le studio lit le site et les images.", answer: "Ta description est notée.", create: "On part de rien, aucun visuel à trier." }[mode], { before: snap });
    });
    if (say) {
      return h("div", { className: "task" }, h(Head, null, "Dis ce que tu sais de la marque"),
        h("div", { className: "field" }, h("label", { htmlFor: "answers", className: "sr" }, "Ce que tu sais de la marque"),
          h("textarea", { id: "answers", value: answers, autoFocus: true, onChange: (e) => setAnswers(e.target.value), placeholder: "Qui c'est, à quoi ça ressemble, ce qu'il ne faut jamais faire." })),
        h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || !answers.trim(), onClick: () => go("answer"), "aria-label": "Envoyer ma description de la marque" }, "Envoyer"),
          h(Button, { variant: "ghost", size: "lg", onClick: () => setSay(false), "aria-label": "Revenir aux trois façons d'apprendre la marque" }, "Retour")));
    }
    return h("div", { className: "task" }, h(Head, null, "Comment le studio apprend la marque ?"),
      h("p", { className: "lead" }, "Il lit le site et les images, puis te propose quoi garder. Ou tu lui racontes la marque toi-même."),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", disabled: ctx.busy, onClick: () => go("learn"), "aria-label": "Laisser le studio chercher la marque" }, "Laisse le studio chercher"),
        h(Button, { variant: "secondary", size: "lg", disabled: ctx.busy, onClick: () => setSay(true), "aria-label": "Raconter la marque moi-même" }, "Je raconte la marque")),
      h("p", { className: "aside" }, "Ou ", h("button", { type: "button", className: "linkbtn", disabled: ctx.busy, onClick: () => go("create"), "aria-label": "Partir de rien, sans visuel à trier" }, "pars de rien"), " : pas de visuel à trier, tu poseras la marque dans le brief."));
  }

  /* ================= 2. brand: sort the visuals one by one, then the logo, then the colours ================= */
  function BrandSort({ ctx, pid }) {
    const [brand, setBrand] = useState(null);
    useEffect(() => { api.brand(pid).then(setBrand).catch(ctx.fail); }, [pid]);
    if (!brand) return h("div", { className: "task" }, h(Wait, { text: "Chargement des visuels." }));
    return h(Sorter, { ctx, pid, brand });
  }

  function Sorter({ ctx, pid, brand }) {
    const { evidence, logos } = brand;
    const [dec, setDec] = useState(() => { const m = {}; evidence.forEach((e) => { if (typeof e.kept === "boolean") m[e.id] = e.kept; }); return m; });
    const [cur, setCur] = useState(() => Math.max(0, evidence.findIndex((e) => typeof e.kept !== "boolean")));
    const [stage, setStage] = useState(() => (evidence.length === 0 ? "end" : "visuals")); // visuals, end, colours
    const [logo, setLogo] = useState(brand.logo || (logos.length === 1 ? logos[0].id : null));
    const [said, setSaid] = useState("");
    const [result, setResult] = useState(null);
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
    H.current = { decide, undo, move, stage };

    useEffect(() => {
      const f = (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.altKey || ctx.overlayRef.current) return;
        const t = ev.target, tag = t && t.tagName;
        if (tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable) || (tag === "INPUT" && !["radio", "checkbox", "button"].includes(t.type))) return;
        const k = ev.key.toLowerCase();
        if (H.current.stage === "visuals" && k === "g") { ev.preventDefault(); H.current.decide(true); }
        else if (H.current.stage === "visuals" && k === "e") { ev.preventDefault(); H.current.decide(false); }
        else if (k === "u") { ev.preventDefault(); H.current.undo(); }
        else if (ev.key === "ArrowRight") { ev.preventDefault(); H.current.move(1); }
        else if (ev.key === "ArrowLeft") { ev.preventDefault(); H.current.move(-1); }
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
    ].filter(Boolean) : stage === "end" ? [{ id: "undo", label: "Annuler le dernier geste", hint: "U", run: undo }] : []);

    const submit = () => ctx.act(async () => {
      const r = await api.keep(pid, kept.map((x) => x.id), logo);
      const lg = logos.find((l) => l.id === logo);
      ctx.log(pid, "toi", "Tri de la marque : " + plural(r.kept, "gardé", "gardés") + ", " + plural(r.discarded, "écarté", "écartés") + (lg ? ", logo : " + lg.note : ""),
        dropped.length ? "Écartés : " + dropped.map((x) => x.note).join(" ; ") : "");
      setResult(r); setStage("colours");
    });

    if (stage === "colours") {
      return h(Colours, { ctx, pid, colours: result.colours, line: "Tri enregistré : " + summary + ".", revise: () => setStage("visuals"), after: "Tri et couleurs de la marque validés : " + plural(result.kept, "visuel gardé", "visuels gardés") + "." });
    }
    if (stage === "end") {
      const needLogo = logos.length > 0 && !logo;
      return h("div", { className: "task" },
        h(Head, null, evidence.length === 0 ? "Aucun visuel à trier" : logos.length ? "Quel logo garder ?" : "Le tri est fait"),
        evidence.length === 0 ? h("p", { className: "lead" }, "On part de rien : le studio ne te montre aucun visuel. Tu poseras la marque dans le brief.") : h("p", { className: "lead muted" }, summary + "."),
        logos.length > 0 && h("div", { className: "logos", role: "radiogroup", "aria-label": "Logo de la marque" }, logos.map((l) => h("button", { key: l.id, type: "button", role: "radio", "aria-checked": logo === l.id, className: "logo", onClick: () => setLogo(l.id) },
          h("img", { src: l.preview, alt: "" }), h("span", { className: "small" }, l.note)))),
        h("div", { className: "gestures" },
          h(Button, { variant: "primary", size: "lg", disabled: ctx.busy || needLogo, onClick: submit, "aria-label": "Valider le tri de la marque" }, "Valider le tri"),
          evidence.length > 0 && h(Button, { variant: "ghost", size: "lg", onClick: () => { setStage("visuals"); setCur(evidence.length - 1); }, "aria-label": "Revoir les visuels" }, "Revoir les visuels")),
        needLogo && h("p", { className: "small muted" }, "Choisis un logo pour continuer."));
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

  function Colours({ ctx, pid, colours, line, revise, after }) {
    const next = () => ctx.answered(pid, after, { before: ctx.snap() });
    useCmds(ctx, []);
    return h("div", { className: "task" }, h(Head, null, "Voilà les couleurs de la marque"),
      h("p", { className: "lead muted" }, "Mesurées sur les visuels que tu as gardés." + (line ? " " + line : "")),
      h(Swatches, { colours }),
      h("div", { className: "gestures" },
        h(Button, { variant: "primary", size: "lg", onClick: next, "aria-label": "Les couleurs sont bonnes, continuer" }, "Les couleurs sont bonnes"),
        h(Button, { variant: "secondary", size: "lg", onClick: revise, "aria-label": "Revoir mon tri des visuels" }, "Revoir mon tri")));
  }

  /* the colours of a brand already sorted, reopened from "Rouvrir une étape" */
  function BrandDone({ ctx, pid }) {
    const [brand, setBrand] = useState(null);
    const [again, setAgain] = useState(false);
    useEffect(() => { api.brand(pid).then(setBrand).catch(ctx.fail); }, [pid]);
    useCmds(ctx, []);
    if (!brand) return h("div", { className: "task" }, h(Wait, null));
    if (again) return h(Sorter, { ctx, pid, brand });
    const n = brand.evidence.filter((x) => x.kept).length;
    return h(Colours, { ctx, pid, colours: brand.colours, line: plural(n, "visuel gardé", "visuels gardés") + ", " + plural(brand.evidence.length - n, "écarté", "écartés") + ".", revise: () => setAgain(true), after: "Marque relue." });
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

  /* ================= screens opened from "Plus" ================= */
  function Rows({ items }) {
    return h("ul", { className: "rows" }, items.map((it) => h("li", { key: it.key }, h("button", { type: "button", className: "row-btn", onClick: it.onClick, "aria-label": it.aria },
      h("span", { className: "t" }, it.title), h("span", { className: "m" }, it.meta)))));
  }
  const Blocked = ({ ctx, text }) => h("div", { className: "task" }, h(Head, null, text), h("div", { className: "gestures" }, h(Button, { variant: "secondary", size: "lg", onClick: () => ctx.go({ kind: "home" }), "aria-label": "Revenir à la liste des tâches" }, "Retour à la liste")));
  const Busy = ({ text }) => h("div", { className: "task" }, h(Head, null, text), h("p", { className: "lead muted" }, "Tu le retrouves dans ta liste quand c'est prêt."));

  function Steps({ ctx, pid }) {
    const [p, setP] = useState(null);
    useEffect(() => { api.project(pid).then(setP).catch(ctx.fail); }, [pid]);
    useCmds(ctx, []);
    if (!p) return h("div", { className: "task" }, h(Wait, null));
    const word = (s) => (s ? ({ todo: "À venir", waiting: "Attend ta réponse", running: "Le studio travaille", done: "Fait" })[s.status] : "");
    const by = (k) => p.steps.find((s) => s.key === k);
    const rows = [["brand", "Apprendre la marque"], ["brief", "Le brief"], ["mandates", "Les consignes aux agents"], ["diverge", "La divergence"]].map(([k, t]) => ({ key: k, title: t, meta: word(by(k)), aria: "Rouvrir : " + t + ", " + word(by(k)).toLowerCase(), onClick: () => ctx.go({ kind: "step", pid, step: k }) }));
    rows.push({ key: "series", title: "La série", meta: p.pieces.length ? plural(p.pieces.length, "pièce", "pièces") : "Pas encore de pièce", aria: "Voir la série", onClick: () => ctx.go({ kind: "series", pid }) });
    return h("div", { className: "task" }, h(Head, null, "Quelle étape rouvrir ?"), h(Rows, { items: rows }));
  }

  function StepAny({ ctx, pid, step }) {
    const [p, setP] = useState(null);
    useEffect(() => { api.project(pid).then(setP).catch(ctx.fail); }, [pid, step]);
    useCmds(ctx, []);
    if (!p) return h("div", { className: "task" }, h(Wait, null));
    const S = (k) => (p.steps.find((s) => s.key === k) || {}).status;
    if (step === "brand") { const st = S("brand"); return st === "done" ? h(BrandDone, { ctx, pid }) : st === "waiting" ? h(BrandSort, { ctx, pid }) : st === "running" ? h(Busy, { text: "Le studio lit le site et les images." }) : h(BrandHow, { ctx, pid }); }
    if (step === "brief") return S("brand") !== "done" ? h(Blocked, { ctx, text: "Le brief s'ouvre quand la marque est triée." }) : h(Brief, { ctx, pid });
    if (step === "mandates") return S("brief") !== "done" ? h(Blocked, { ctx, text: "Les consignes s'ouvrent quand le brief est validé." }) : h(Mandates, { ctx, pid });
    const st = S("diverge");
    if (st === "running") return h(Busy, { text: "Les quatre agents écrivent." });
    if (st === "waiting") return h(DivergePick, { ctx, pid });
    if (st === "done") return h(DivergePick, { ctx, pid, readOnly: true });
    return S("mandates") === "done" ? h(DivergeLaunch, { ctx, pid }) : h(Blocked, { ctx, text: "La divergence s'ouvre quand les consignes sont relues." });
  }

  function Series({ ctx, pid }) {
    const [p, setP] = useState(null);
    useEffect(() => { api.project(pid).then(setP).catch(ctx.fail); }, [pid]);
    useCmds(ctx, []);
    if (!p) return h("div", { className: "task" }, h(Wait, null));
    if (p.pieces.length === 0) return h("div", { className: "task" }, h(Head, null, "Pas encore de série"), h("p", { className: "lead muted" }, "Les pièces arrivent quand tu as choisi des variantes à la divergence."));
    return h("div", { className: "task" }, h(Head, null, "La série : " + plural(p.pieces.length, "pièce", "pièces")),
      h(Rows, { items: p.pieces.map((pc) => { const w = STAGE_WORDS[stageOf(pc, p.jobs)]; return { key: pc.id, title: pc.label, meta: w, aria: pc.label + " : " + w.toLowerCase(), onClick: () => ctx.go({ kind: "piece", pid, piece: pc.id, label: pc.label }) }; }) }));
  }

  function Journal({ ctx, pid }) {
    const list = useMemo(() => loadJournal(pid), [pid]);
    useCmds(ctx, []);
    return h("div", { className: "task" }, h(Head, null, "Le journal des décisions"),
      list.length === 0 ? h("p", { className: "lead muted" }, "Chaque décision s'écrit ici avec son heure et sa raison.") :
        h("ol", { className: "journal" }, list.slice(0, 60).map((e, i) => h("li", { key: e.at + "-" + i },
          h("time", { dateTime: new Date(e.at).toISOString() }, clock(e.at)), h("span", null, h("strong", null, e.who === "toi" ? "Toi : " : "Studio : "), e.text), e.why && h("span", { className: "why" }, e.why)))));
  }

  function Projects({ ctx, focus }) {
    const [name, setName] = useState("");
    const [from, setFrom] = useState("");
    const projects = ctx.data.projects;
    const nameRef = useRef(null), fromRef = useRef(null);
    useEffect(() => { const el = focus === "from" ? fromRef.current : nameRef.current; if (el) el.focus(); }, []);
    useCmds(ctx, []);
    const create = (e) => {
      e.preventDefault();
      ctx.act(async (snap) => {
        const p = await api.createProject(name.trim(), from || undefined);
        ctx.setPid(p.id);
        ctx.log(p.id, "toi", from ? "Déclinaison créée : " + p.name : "Projet créé : " + p.name, from ? "Reprend la marque et le brief de l'original" : "");
        await ctx.answered(p.id, from ? "Déclinaison créée : " + p.name + "." : "Projet créé : " + p.name + ".", { before: snap });
      });
    };
    return h("div", { className: "task" }, h(Head, null, "Nouveau projet"),
      h("form", { className: "sec", onSubmit: create },
        h("div", { className: "field" }, h("label", { htmlFor: "np-name" }, "Nom du projet"), h("input", { id: "np-name", ref: nameRef, type: "text", value: name, onChange: (e) => setName(e.target.value), autoComplete: "off", placeholder: "Par exemple : la campagne de rentrée" })),
        projects.length > 0 && h("div", { className: "field" }, h("label", { htmlFor: "np-from" }, "Partir d'un projet existant"),
          h("select", { id: "np-from", ref: fromRef, value: from, onChange: (e) => setFrom(e.target.value), "aria-describedby": "np-hint" },
            h("option", { value: "" }, "Non, on part de zéro"), projects.map((p) => h("option", { key: p.id, value: p.id }, p.name))),
          h("span", { id: "np-hint", className: "small muted" }, "Une déclinaison reprend la marque et le brief de l'original : tu ne corriges que ce qui change.")),
        h("div", { className: "gestures" }, h(Button, { type: "submit", variant: "primary", size: "lg", disabled: ctx.busy || !name.trim(), "aria-label": from ? "Créer la déclinaison" : "Créer le projet" }, from ? "Créer la déclinaison" : "Créer le projet"))),
      projects.length > 1 && h("div", { className: "sec" }, h("p", { className: "cap" }, "Projet en cours pour la série, le journal et les étapes"),
        h("ul", { className: "rows" }, projects.map((p) => h("li", { key: p.id }, h("button", { type: "button", className: "row-btn", "aria-current": p.id === ctx.pid ? "true" : undefined, onClick: () => { ctx.setPid(p.id); ctx.go({ kind: "home" }); },
          "aria-label": "Prendre ce projet : " + p.name }, h("span", { className: "t" }, p.name), h("span", { className: "m" }, p.id === ctx.pid ? "En cours" : plural(p.waiting, "tâche", "tâches"))))))));
  }

  /* ================= the home: the list of what waits ================= */
  function Home({ ctx }) {
    const { tasks, loaded, jobs, projects } = ctx.data;
    const n = tasks.length;
    useCmds(ctx, []);
    const many = projects.length > 1;
    return h("div", { className: "task home" },
      h(Head, null, !loaded ? "Un instant" : n === 0 ? "Rien ne t'attend" : n === 1 ? "Une chose t'attend" : n + " choses t'attendent"),
      n === 0 && loaded && h("div", { className: "sec" },
        h("p", { className: "lead muted" }, jobs.length ? "Le studio travaille. Ce que tu auras à faire apparaîtra ici." : projects.length ? "Le studio n'a rien à te demander pour l'instant." : "Aucun projet pour l'instant."),
        projects.length === 0 && h("div", { className: "gestures" }, h(Button, { variant: "primary", size: "lg", onClick: () => ctx.go({ kind: "projects" }), "aria-label": "Créer un projet" }, "Créer un projet"))),
      n > 0 && h("ul", { className: "tasks", "aria-label": "Tâches" }, tasks.map((t) => {
        const when = t.since ? ago(t.since, ctx.now()) : "";
        return h("li", { key: t.id }, h("button", { type: "button", className: "task-row", onClick: () => ctx.openTask(t), "aria-label": t.title + (many ? ", " + t.project_name : "") + (when ? ", " + when : "") },
          h("span", { className: "t" }, t.title), h("span", { className: "m" }, (many ? t.project_name + (when ? " · " : "") : "") + when || " ")));
      })));
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

  function PlusMenu({ cmds, onClose, wrapRef }) {
    const ref = useRef(null);
    const [i, setI] = useState(0);
    const items = cmds.filter((c) => c.plus !== false);
    useEffect(() => {
      const out = (e) => { if (ref.current && !ref.current.contains(e.target) && !(wrapRef.current && wrapRef.current.contains(e.target))) onClose(false); };
      document.addEventListener("mousedown", out);
      return () => document.removeEventListener("mousedown", out);
    }, []);
    useEffect(() => { const els = ref.current && ref.current.querySelectorAll('[role="menuitem"]'); if (els && els[i]) els[i].focus(); }, [i]);
    const key = (ev) => {
      if (ev.key === "ArrowDown") { ev.preventDefault(); setI((i + 1) % items.length); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); setI((i - 1 + items.length) % items.length); }
      else if (ev.key === "Home") { ev.preventDefault(); setI(0); }
      else if (ev.key === "End") { ev.preventDefault(); setI(items.length - 1); }
      else if (ev.key === "Escape") { ev.preventDefault(); onClose(true); }
      else if (ev.key === "Tab") { onClose(false); }
    };
    return h("div", { className: "menu", role: "menu", "aria-label": "Plus", ref, onKeyDown: key },
      groups(items).map((g) => h("div", { key: g.name, role: "none" }, h("p", { className: "pal-group", "aria-hidden": "true" }, g.name),
        g.items.map((c) => h("button", { key: c.id, type: "button", role: "menuitem", tabIndex: -1, className: "pal-item", onClick: () => { onClose(false); c.run(); } },
          h("span", null, c.label), c.hint && h("span", { className: "pal-hint" }, c.hint))))));
  }

  /* ================= the application ================= */
  function App() {
    const [data, setData] = useState({ tasks: [], jobs: [], projects: [], now: 0, loaded: false });
    const [view, setView] = useState({ kind: "home" });
    const [notice, setNotice] = useState(null);
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(false);
    const [palette, setPalette] = useState(false);
    const [menu, setMenu] = useState(false);
    const [pid, setPid] = useState(null);
    const [, setTick] = useState(0);
    const tasksRef = useRef([]), skew = useRef(0), prevJobs = useRef([]), cmdsRef = useRef([]), overlayRef = useRef(false), plusRef = useRef(null);
    overlayRef.current = palette || menu;

    const log = useCallback((p, who, text, why) => {
      if (!p) return;
      saveJournal(p, [{ at: Date.now(), who, text, why: why || "" }, ...loadJournal(p)]);
    }, []);
    const fail = useCallback((e) => setError(e && e.message ? e.message : String(e)), []);

    const refresh = useCallback(async () => {
      try {
        const r = await api.tasks();
        skew.current = r.now * 1000 - Date.now();
        prevJobs.current.filter((j) => !r.jobs.some((x) => x.id === j.id)).forEach((j) =>
          log(j.project, "studio", j.kind === "learn" ? "Lecture de la marque terminée" : j.kind === "diverge" ? "Les quatre variantes sont écrites" : "Image prête : " + j.piece, ""));
        prevJobs.current = r.jobs;
        tasksRef.current = r.tasks;
        setData({ ...r, loaded: true });
        return r;
      } catch (e) { setError("Le serveur du studio ne répond pas."); return null; }
    }, [log]);
    useEffect(() => { refresh(); }, []);
    const running = data.jobs.length > 0;
    useEffect(() => { const t = setInterval(refresh, running ? 700 : 4000); return () => clearInterval(t); }, [refresh, running]);
    useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 20000); return () => clearInterval(t); }, []);
    useEffect(() => { if (!pid && data.projects.length) setPid(data.tasks[0] ? data.tasks[0].project : data.projects[0].id); }, [data.projects.length]);

    const go = useCallback((v, keepNotice) => {
      if (!keepNotice) setNotice(null);
      setView(v); setMenu(false); setPalette(false); setError(null);
      if (v.pid) setPid(v.pid);
      window.scrollTo(0, 0);
    }, []);
    const openTask = useCallback((t, keepNotice) => go({ kind: "task", pid: t.project, step: t.step, piece: t.piece, tkind: t.kind, title: t.title, label: t.piece_label, key: t.id }, keepNotice), [go]);

    /* an action runs under `busy`; `snap` is the set of tasks before it, to know which ones are new afterwards */
    const snap = useCallback(() => new Set(tasksRef.current.map((t) => t.id)), []);
    const act = useCallback(async (fn) => {
      setBusy(true); setError(null);
      const s = snap();
      try { return await fn(s); } catch (e) { fail(e); } finally { setBusy(false); }
    }, [fail, snap]);

    /* an answer settles a task: back to the next one if it follows, else to the list, with one line that says what was done */
    const answered = useCallback(async (p, text, o = {}) => {
      const before = o.before || snap();
      const r = await refresh();
      const mine = r ? r.tasks.filter((t) => t.project === p) : [];
      const isNew = (t) => !before.has(t.id);
      const next = (o.prefer && mine.find((t) => isNew(t) && o.prefer(t))) || (o.any !== false && mine.find(isNew)) || (o.sibling && mine.find(o.sibling)) || null;
      setNotice(text);
      if (next) openTask(next, true); else go({ kind: "home" }, true);
    }, [refresh, go, openTask, snap]);

    const now = () => Date.now() + skew.current;
    const info = (p) => data.projects.find((x) => x.id === p) || { name: "", brand: "" };
    const cp = pid && data.projects.find((x) => x.id === pid) ? pid : null;
    const ctx = { data, busy, pid: cp, setPid, act, answered, snap, log, fail, go, openTask, now, cmdsRef, overlayRef };

    /* what the breadcrumb says, and what the screen shows */
    let crumb = [{ label: "Studio créatif" }], body;
    const pi = view.pid ? info(view.pid) : null;
    const trail = (last) => [{ label: pi.brand || "Studio", home: true }, { label: pi.name, home: true }, { label: last }];
    if (view.kind === "home") body = h(Home, { ctx });
    else if (view.kind === "projects") { crumb = [{ label: "Studio créatif", home: true }, { label: "Nouveau projet" }]; body = h(Projects, { ctx, focus: view.focus, key: "pr" + (view.focus || "") }); }
    else if (view.kind === "steps") { crumb = trail("Rouvrir une étape"); body = h(Steps, { ctx, pid: view.pid }); }
    else if (view.kind === "step") { crumb = trail(STEP_LABELS[view.step]); body = h(StepAny, { ctx, pid: view.pid, step: view.step, key: "st" + view.pid + view.step }); }
    else if (view.kind === "series") { crumb = trail("La série"); body = h(Series, { ctx, pid: view.pid }); }
    else if (view.kind === "journal") { crumb = trail("Le journal"); body = h(Journal, { ctx, pid: view.pid }); }
    else if (view.kind === "piece") { crumb = trail(view.label || view.piece); body = h(PieceAny, { ctx, pid: view.pid, id: view.piece, key: "pc" + view.piece }); }
    else {
      const k = view.tkind, p = view.pid, key = view.key;
      crumb = trail(SHORT[k] + (view.label ? " · " + view.label : ""));
      body = k === "brand-how" ? h(BrandHow, { ctx, pid: p, key }) : k === "brand-sort" ? h(BrandSort, { ctx, pid: p, key }) : k === "brief" ? h(Brief, { ctx, pid: p, key })
        : k === "mandates" ? h(Mandates, { ctx, pid: p, key }) : k === "diverge-launch" ? h(DivergeLaunch, { ctx, pid: p, key }) : k === "diverge-pick" ? h(DivergePick, { ctx, pid: p, key })
        : k === "prompt" ? h(Prompt, { ctx, pid: p, id: view.piece, key }) : k === "compose" ? h(Compose, { ctx, pid: p, id: view.piece, key }) : h(Decide, { ctx, pid: p, id: view.piece, key });
    }

    /* the commands: one list, behind "Plus" and behind the palette */
    const cmds = [];
    if (palette || menu) {
      (cmdsRef.current || []).forEach((c) => cmds.push({ ...c, group: "Cette tâche" }));
      if (view.kind !== "home") cmds.push({ id: "home", group: "Aller", label: "Revenir à la liste des tâches", run: () => go({ kind: "home" }) });
      data.tasks.forEach((t) => cmds.push({ id: "task:" + t.id, group: "Ouvrir une tâche", label: t.title, hint: data.projects.length > 1 ? t.project_name : "", plus: false, run: () => openTask(t) }));
      if (cp) {
        cmds.push({ id: "steps", group: "Ce projet", label: "Rouvrir une étape", run: () => go({ kind: "steps", pid: cp }) });
        ["brand", "brief", "mandates", "diverge"].forEach((s) => cmds.push({ id: "step:" + s, group: "Ce projet", label: "Rouvrir : " + STEP_LABELS[s].toLowerCase(), plus: false, run: () => go({ kind: "step", pid: cp, step: s }) }));
        cmds.push({ id: "series", group: "Ce projet", label: "Voir la série", run: () => go({ kind: "series", pid: cp }) });
        cmds.push({ id: "journal", group: "Ce projet", label: "Voir le journal des décisions", run: () => go({ kind: "journal", pid: cp }) });
      }
      cmds.push({ id: "new", group: "Projets", label: "Nouveau projet", run: () => go({ kind: "projects", focus: "name" }) });
      if (data.projects.length) cmds.push({ id: "from", group: "Projets", label: "Partir d'un projet existant", run: () => go({ kind: "projects", focus: "from" }) });
      if (data.projects.length > 1) cmds.push({ id: "switch", group: "Projets", label: "Changer de projet", run: () => go({ kind: "projects", focus: "name" }) });
      if (menu) cmds.push({ id: "palette", group: "Commandes", label: "Palette de commandes", hint: MOD + " K", run: () => setPalette(true) });
    }

    /* the palette key, wherever the focus is */
    useEffect(() => {
      const f = (ev) => { if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "k") { ev.preventDefault(); setMenu(false); setPalette((v) => !v); } };
      window.addEventListener("keydown", f);
      return () => window.removeEventListener("keydown", f);
    }, []);

    const n = data.tasks.length;
    const last = crumb[crumb.length - 1].label;
    useEffect(() => { document.title = (n ? "(" + n + ") " : "") + (view.kind === "home" ? "Ce qui t'attend" : last) + " · Studio créatif"; }, [n, view.kind, last]);

    const line = studioLine(data.jobs);
    return h("div", { className: "app" },
      h("a", { href: "#main", className: "skip", onClick: (e) => { e.preventDefault(); const m = document.getElementById("main"); if (m) m.focus(); } }, "Aller au contenu"),
      h("header", { className: "bar" },
        h("nav", { "aria-label": "Fil d'Ariane" }, h("ol", { className: "crumb" }, crumb.map((c, i) => h("li", { key: i },
          c.home ? h("button", { type: "button", className: "crumb-link", onClick: () => go({ kind: "home" }), "aria-label": c.label + " : revenir à la liste des tâches" }, c.label) : h("span", { "aria-current": i === crumb.length - 1 ? "page" : undefined }, c.label))))),
        h("div", { className: "plus", ref: plusRef },
          h(Button, { variant: "ghost", size: "sm", "aria-haspopup": "menu", "aria-expanded": menu, "aria-label": "Plus : étapes, série, journal, projets", onClick: () => { setPalette(false); setMenu(!menu); } }, "Plus"),
          menu && h(PlusMenu, { cmds, wrapRef: plusRef, onClose: (back) => { setMenu(false); if (back && plusRef.current) { const b = plusRef.current.querySelector("button"); if (b) b.focus(); } } }))),
      h("main", { id: "main", tabIndex: -1, className: "page" },
        error && h("div", { role: "alert", className: "err" }, h(Callout, { tone: "risk", label: "Le studio refuse" }, error, " ", h("button", { type: "button", className: "linkbtn", onClick: () => setError(null) }, "Fermer"))),
        h(Notice, { text: notice }),
        body),
      h("div", { className: "studio-line", role: "status", "aria-live": "polite", hidden: !line }, line),
      palette && h(Palette, { cmds, onClose: () => setPalette(false) }));
  }

  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
