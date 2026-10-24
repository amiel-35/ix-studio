/* app.js: the interface that drives the studio. React 18 without JSX, components of the design system.
   It talks to the studio only through window.studioApi (api.js, see app/API.md): no simulated data lives here.
   The journal of decisions is kept on this side (localStorage) for this first version: the API has no journal route yet. */
(function () {
  "use strict";
  const DS = window[Object.keys(window).find((k) => k.endsWith("DesignSystem_9fde59"))]; // the design system's global, found by its suffix
  const { Button, Badge, Tag, Callout, Eyebrow } = DS;
  const api = window.studioApi;
  const h = React.createElement;
  const { useState, useEffect, useRef, useCallback } = React;

  /* ---------- small helpers ---------- */
  const FRISE = [
    { key: "brand", label: "Marque" }, { key: "brief", label: "Brief" }, { key: "mandates", label: "Consignes" },
    { key: "diverge", label: "Divergence" }, { key: "image", label: "Images" },
    { key: "piece", label: "Composition et vérification" }, { key: "decide", label: "Décision" },
  ];
  const TITLES = {
    brand: "Apprendre la marque", brief: "Le brief", mandates: "Les consignes aux agents", diverge: "La divergence",
    image: "Les images", piece: "Composition et vérification", check: "Composition et vérification", decide: "La décision",
  };
  const KIND = { learn: "Lecture de la marque", diverge: "Écriture des variantes", image: "Image" };
  const stepKey = (k) => (k === "check" ? "piece" : k);
  const pct = (x) => Math.round((x || 0) * 100) + " %";
  const clock = (ms) => new Date(ms).toLocaleTimeString("fr-FR");
  function dur(ms) {
    const s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    if (m < 60) return m + " min " + (s % 60) + " s";
    return Math.floor(m / 60) + " h " + (m % 60) + " min";
  }
  const stepOf = (p, key) => p.steps.find((s) => s.key === key);
  const plural = (n, one, many) => n + " " + (n > 1 ? many : one);

  function loadJournal(pid) {
    try { return JSON.parse(localStorage.getItem("studio-journal:" + pid) || "[]"); } catch (e) { return []; }
  }
  function saveJournal(pid, list) {
    try { localStorage.setItem("studio-journal:" + pid, JSON.stringify(list.slice(0, 200))); } catch (e) { /* private window: the journal lives on screen only */ }
  }

  /* where a piece stands, from what the API says */
  function stageOf(pc, jobs) {
    const job = jobs.find((j) => j.kind === "image" && j.piece === pc.id);
    if (job) return { key: "running", label: "Image en cours, " + pct(job.progress), job };
    if (pc.decision && pc.decision.verdict === "keep") return { key: "done", label: "Gardée" };
    if (pc.composed) return { key: "decide", label: "À décider" };
    if (pc.image) return { key: "compose", label: "À composer" };
    return { key: "prompt", label: pc.bans && pc.bans.length ? "À refaire" : "Prompt à relire" };
  }

  /* ---------- little building blocks ---------- */
  function Field({ id, label, hint, children }) {
    return h("div", { className: "field" }, h("label", { htmlFor: id }, label), children, hint && h("span", { className: "hint" }, hint));
  }
  function Progress({ value }) {
    return h("div", { className: "bar", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": Math.round((value || 0) * 100) },
      h("i", { style: { width: Math.round((value || 0) * 100) + "%" } }));
  }
  function Frame({ src, alt, size, empty }) {
    const ratio = size ? size[0] / size[1] : 4 / 5;
    return h("div", { className: "frame", style: { aspectRatio: String(ratio) } },
      src ? h("img", { src, alt }) : h("span", { style: { padding: "var(--space-3)" } }, empty || "Pas encore d'image"));
  }
  const Kbd = (t) => h("span", { className: "kbd" }, t);

  /* ---------- the job being followed, shown where the person waits ---------- */
  function JobBar({ job, label }) {
    return h("div", { className: "sec" },
      h("div", { className: "job" }, h("span", null, label || KIND[job.kind] || job.kind), h("span", { className: "mono" }, pct(job.progress)), h(Progress, { value: job.progress })),
      h("p", { className: "small muted" }, job.message || "En cours."));
  }

  /* ================= projects ================= */
  function ProjectsPanel({ ctx }) {
    const [name, setName] = useState("");
    const [from, setFrom] = useState("");
    const list = ctx.projects;
    return h("div", { className: "inner" },
      h("div", { className: "sec" },
        h("h2", null, "Tes projets"),
        list.length === 0 ? h("p", { className: "muted" }, "Aucun projet pour l'instant.") :
          h("ul", { className: "rows" }, list.map((p) => h("li", { key: p.id },
            h("button", { className: "rowbtn", "aria-current": p.id === ctx.pid ? "true" : undefined, onClick: () => ctx.selectProject(p.id) },
              h("span", { className: "t" }, p.name),
              h("span", { className: "s" }, p.waiting ? plural(p.waiting, "question attend", "questions attendent") : "Rien n'attend")))))),
      h("hr", { className: "rule", style: { marginTop: "var(--space-6)" } }),
      h("form", { className: "form sec", style: { marginTop: "var(--space-5)" }, onSubmit: (e) => { e.preventDefault(); ctx.createProject(name.trim(), from || undefined); setName(""); } },
        h("h2", null, "Créer un projet"),
        h(Field, { id: "np-name", label: "Nom du projet" },
          h("input", { id: "np-name", type: "text", value: name, onChange: (e) => setName(e.target.value), placeholder: "Par exemple : la campagne de rentrée", autoComplete: "off" })),
        h(Field, { id: "np-from", label: "Partir d'un projet existant", hint: "Une déclinaison reprend la marque et le brief de la pièce d'origine. Tu n'as à corriger que ce qui change." },
          h("select", { id: "np-from", value: from, onChange: (e) => setFrom(e.target.value) },
            h("option", { value: "" }, "Non, on part de zéro"),
            list.map((p) => h("option", { key: p.id, value: p.id }, p.name)))),
        h("div", { className: "row" }, h(Button, { type: "submit", variant: "primary", disabled: ctx.busy || !name.trim() }, from ? "Créer la déclinaison" : "Créer le projet"))));
  }

  /* ================= brand ================= */
  function Tri({ evidence, logos, initial, initialLogo, onSubmit, busy, submitLabel }) {
    const [dec, setDec] = useState(() => {
      const m = {};
      evidence.forEach((e) => { if (typeof initial[e.id] === "boolean") m[e.id] = initial[e.id]; });
      return m;
    });
    const [cur, setCur] = useState(() => Math.max(0, evidence.findIndex((e) => typeof initial[e.id] !== "boolean")));
    const [filter, setFilter] = useState("all");
    const [logo, setLogo] = useState(initialLogo || (logos.length === 1 ? logos[0].id : null));
    const [said, setSaid] = useState("");
    const hist = useRef([]);
    const H = useRef({});

    const decide = (val) => {
      const e = evidence[cur];
      if (!e) return;
      hist.current.push({ id: e.id, prev: dec[e.id], at: cur });
      setDec((d) => ({ ...d, [e.id]: val }));
      setSaid((val ? "Gardé : " : "Écarté : ") + e.note);
      const nxt = evidence.findIndex((x, i) => i > cur && dec[x.id] === undefined);
      setCur(nxt >= 0 ? nxt : Math.min(cur + 1, evidence.length - 1));
    };
    const undo = () => {
      const last = hist.current.pop();
      if (!last) return;
      setDec((d) => { const n = { ...d }; if (last.prev === undefined) delete n[last.id]; else n[last.id] = last.prev; return n; });
      setCur(last.at);
      setSaid("Annulé.");
    };
    const move = (n) => setCur((c) => Math.max(0, Math.min(evidence.length - 1, c + n)));
    H.current = { decide, undo, move };

    useEffect(() => {
      const f = (ev) => {
        if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
        const t = ev.target, tag = t && t.tagName;
        if (tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
        if (tag === "INPUT" && !["radio", "checkbox", "button"].includes(t.type)) return;
        const k = ev.key.toLowerCase();
        if (k === "g") { ev.preventDefault(); H.current.decide(true); }
        else if (k === "e") { ev.preventDefault(); H.current.decide(false); }
        else if (k === "u") { ev.preventDefault(); H.current.undo(); }
        else if (ev.key === "ArrowRight" && !(tag === "INPUT" && t.type === "radio")) { ev.preventDefault(); H.current.move(1); }
        else if (ev.key === "ArrowLeft" && !(tag === "INPUT" && t.type === "radio")) { ev.preventDefault(); H.current.move(-1); }
      };
      window.addEventListener("keydown", f);
      return () => window.removeEventListener("keydown", f);
    }, []);

    const kept = evidence.filter((e) => dec[e.id] === true), dropped = evidence.filter((e) => dec[e.id] === false);
    const left = evidence.length - kept.length - dropped.length;
    const e = evidence[cur];
    const kindOf = (x) => (dec[x.id] === true ? "yes" : dec[x.id] === false ? "no" : "");
    const shown = evidence.map((x, i) => ({ x, i })).filter(({ x }) => filter === "all" || (filter === "left" ? dec[x.id] === undefined : filter === "yes" ? dec[x.id] === true : dec[x.id] === false));
    const needLogo = logos.length > 0 && !logo;
    const ready = left === 0 && !needLogo;
    const proposal = (x) => (x.proposed === true ? "Le studio propose de garder" : x.proposed === false ? "Le studio propose d'écarter" : "Le studio ne tranche pas, à toi");
    const followStudio = () => {
      setDec((d) => { const n = { ...d }; evidence.forEach((x) => { if (n[x.id] === undefined && typeof x.proposed === "boolean") n[x.id] = x.proposed; }); return n; });
      setSaid("Propositions du studio appliquées à ce qui restait.");
    };

    if (evidence.length === 0) {
      return h("div", { className: "sec" },
        h(Callout, { tone: "info", label: "Rien à trier" }, "On part de rien : le studio n'a trouvé aucun visuel et ne t'en montre aucun. Tu poseras la marque dans le brief."),
        h("div", { className: "actions" }, h(Button, { variant: "primary", disabled: busy, onClick: () => onSubmit([], null) }, submitLabel)));
    }
    return h("div", { className: "sec" },
      h("p", { className: "small muted" }, "Clavier : ", Kbd("←"), " ", Kbd("→"), " naviguer, ", Kbd("G"), " garder, ", Kbd("E"), " écarter, ", Kbd("U"), " annuler le dernier geste. Les écartés restent consultables."),
      h("div", { className: "board" },
        e && h("figure", { className: "focus-card" },
          h("div", { className: "pic" }, h("img", { src: e.preview, alt: e.note })),
          h("figcaption", { className: "cap-body" },
            h("span", { className: "cap" }, "Visuel " + (cur + 1) + " sur " + evidence.length),
            h("strong", { style: { color: "var(--text-strong)" } }, e.note),
            h("div", { className: "row" },
              h(Tag, null, e.kind === "page" ? "Page" : "Image"),
              dec[e.id] === true ? h(Badge, { tone: "success" }, "Gardé") : dec[e.id] === false ? h(Badge, { tone: "neutral" }, "Écarté") : h(Badge, { tone: "info" }, "À trier")),
            h("span", { className: "small muted" }, proposal(e)),
            h("div", { className: "row" },
              h(Button, { variant: "primary", size: "sm", onClick: () => decide(true) }, "Garder (G)"),
              h(Button, { variant: "secondary", size: "sm", onClick: () => decide(false) }, "Écarter (E)"),
              h(Button, { variant: "ghost", size: "sm", onClick: undo, disabled: hist.current.length === 0 && !said }, "Annuler (U)")))),
        h("div", { className: "sec" },
          h("div", { className: "row", role: "group", "aria-label": "Filtrer les visuels" },
            [["all", "Tous (" + evidence.length + ")"], ["left", "À trier (" + left + ")"], ["yes", "Gardés (" + kept.length + ")"], ["no", "Écartés (" + dropped.length + ")"]].map(([k, t]) =>
              h("button", { key: k, type: "button", className: "chip", "aria-pressed": filter === k, onClick: () => setFilter(k) }, t))),
          h("ul", { className: "tiles" }, shown.map(({ x, i }) => h("li", { key: x.id },
            h("button", { type: "button", className: "tile", "data-k": kindOf(x), "aria-current": i === cur ? "true" : undefined, onClick: () => setCur(i), "aria-label": x.note + ", " + (kindOf(x) === "yes" ? "gardé" : kindOf(x) === "no" ? "écarté" : "à trier") },
              h("img", { src: x.preview, alt: "" }),
              h("span", { className: "tl" }, h("span", { className: "mark" }, kindOf(x) === "yes" ? "Gardé" : kindOf(x) === "no" ? "Écarté" : "À trier"), h("span", { className: "n" }, x.note)))))),
          shown.length === 0 && h("p", { className: "muted small" }, "Rien dans ce filtre."),
          left > 0 && evidence.some((x) => dec[x.id] === undefined && typeof x.proposed === "boolean") && h("div", { className: "row" },
            h(Button, { variant: "ghost", size: "sm", onClick: followStudio }, "Suivre le studio pour les " + left + " restants")))),
      h("span", { className: "sr", role: "status", "aria-live": "polite" }, said),
      logos.length > 0 && h("fieldset", { className: "sec", style: { border: 0, marginTop: "var(--space-5)" } },
        h("legend", { style: { fontFamily: "var(--font-display)", fontSize: "var(--fs-h3)", fontWeight: "var(--fw-semibold)", color: "var(--text-heading)", padding: 0, marginBottom: "var(--space-3)" } }, "Le logo"),
        h("div", { className: "logos" }, logos.map((l) => h("label", { key: l.id, className: "logo-opt" },
          h("input", { type: "radio", name: "logo", value: l.id, "aria-label": l.note, checked: logo === l.id, onChange: () => setLogo(l.id) }),
          h("span", { className: "sec" }, h("img", { src: l.preview, alt: l.note }), h("span", { className: "small" }, l.note)))))),
      h("div", { className: "actions" },
        h(Button, { variant: "primary", disabled: busy || !ready, onClick: () => onSubmit(kept.map((x) => x.id), logo) }, submitLabel),
        h("span", { className: "small muted" }, plural(kept.length, "gardé", "gardés") + " · " + plural(dropped.length, "écarté", "écartés") + " · " + left + " à trier"),
        !ready && h("span", { className: "small muted note" }, left > 0 ? "Il reste " + plural(left, "visuel", "visuels") + " à trier." : "Choisis un logo."))
    );
  }

  function Colours({ colours }) {
    if (!colours || colours.length === 0) return h("p", { className: "muted" }, "Aucune couleur mesurée pour l'instant.");
    return h("div", { className: "swatches" }, colours.map((c) => h("div", { key: c.hex, className: "swatch" },
      h("i", { style: { background: c.hex }, role: "img", "aria-label": "Couleur " + c.hex }),
      h("span", { className: "mono small" }, c.hex),
      h(Badge, { tone: c.status === "to confirm" ? "info" : "success" }, c.status === "to confirm" ? "À confirmer" : "Confirmée"),
      h("span", { className: "small muted" }, c.source))));
  }

  function BrandPanel({ ctx }) {
    const { project, pid } = ctx;
    const step = stepOf(project, "brand");
    const [brand, setBrand] = useState(null);
    const [answers, setAnswers] = useState("");
    const [editing, setEditing] = useState(false);
    useEffect(() => {
      setBrand(null);
      if (step.status === "waiting" || step.status === "done") api.brand(pid).then(setBrand).catch((e) => ctx.fail(e));
    }, [pid, step.status, editing]);
    const job = project.jobs.find((j) => j.kind === "learn");

    const learn = (mode) => ctx.act(async () => {
      ctx.pin();
      await api.learnBrand(pid, mode, mode === "answer" ? answers : undefined);
      ctx.log("toi", { learn: "Le studio cherche la marque", answer: "Tu décris la marque toi-même", create: "On part de rien" }[mode], mode === "answer" ? answers : "");
      await ctx.refresh();
      if (mode !== "learn") ctx.done("Marque : " + (mode === "answer" ? "ta description est notée." : "on part de rien."));
    });
    const submit = (kept, logo) => ctx.act(async () => {
      ctx.pin();
      const r = await api.keep(pid, kept, logo);
      const dropped = brand.evidence.filter((e) => !kept.includes(e.id)).map((e) => e.note);
      ctx.log("toi", "Tri de la marque : " + plural(r.kept, "gardé", "gardés") + ", " + plural(r.discarded, "écarté", "écartés") + (logo ? ", logo : " + ((brand.logos.find((l) => l.id === logo) || {}).note || logo) : ""), dropped.length ? "Écartés : " + dropped.join(" ; ") : "");
      setEditing(false);
      await ctx.refresh();
      ctx.done("Tri de la marque enregistré : " + plural(r.kept, "visuel gardé", "visuels gardés") + ".");
      await ctx.refresh();
    });

    if (step.status === "running" && job) return h("div", { className: "inner sec" }, h(JobBar, { job, label: "Le studio lit le site et les images" }), h("p", { className: "muted" }, "Tu peux ouvrir une autre étape ou revenir plus tard : le studio continue."));
    if (step.status === "todo") {
      return h("div", { className: "inner" },
        h("div", { className: "grid2", style: { gridTemplateColumns: "repeat(3, minmax(0, 1fr))" } },
          h("div", { className: "sec" }, h("h2", null, "Le studio cherche"), h("p", { className: "small" }, "Il lit le site et les images trouvées, et te propose quoi garder. C'est le plus rapide."),
            h(Button, { variant: "primary", disabled: ctx.busy, onClick: () => learn("learn") }, "Lancer la recherche")),
          h("div", { className: "sec" }, h("h2", null, "Je réponds"), h("p", { className: "small" }, "Tu racontes la marque avec tes mots, le studio part de là."),
            h("div", { className: "field" }, h("label", { htmlFor: "answers", className: "sr" }, "Ce que tu sais de la marque"),
              h("textarea", { id: "answers", value: answers, onChange: (e) => setAnswers(e.target.value), placeholder: "Qui est-ce, à quoi ça ressemble, ce qu'il ne faut jamais faire" })),
            h(Button, { variant: "secondary", disabled: ctx.busy || !answers.trim(), onClick: () => learn("answer") }, "Envoyer mes réponses")),
          h("div", { className: "sec" }, h("h2", null, "Partir de rien"), h("p", { className: "small" }, "Pas de recherche, pas de visuel à trier. Tu poseras la marque dans le brief."),
            h(Button, { variant: "secondary", disabled: ctx.busy, onClick: () => learn("create") }, "Partir de rien"))));
    }
    if (!brand) return h("p", { className: "muted" }, "Chargement de la marque.");
    const initial = {};
    brand.evidence.forEach((e) => { if (typeof e.kept === "boolean") initial[e.id] = e.kept; });
    if (step.status === "waiting" || editing) {
      return h("div", { className: "inner sec" },
        brand.answers && h(Callout, { tone: "neutral", label: "Ce que tu as dit de la marque" }, brand.answers),
        h(Tri, { evidence: brand.evidence, logos: brand.logos, initial: editing ? initial : {}, initialLogo: editing ? brand.logo : null, busy: ctx.busy, onSubmit: submit, submitLabel: "Valider ce tri" }));
    }
    const keptN = brand.evidence.filter((e) => e.kept).length, dropN = brand.evidence.length - keptN;
    const logo = brand.logos.find((l) => l.id === brand.logo);
    const briefDone = stepOf(project, "brief").status === "done";
    return h("div", { className: "inner sec" },
      h("p", { className: "lead" }, plural(keptN, "visuel gardé", "visuels gardés") + ", " + plural(dropN, "écarté", "écartés") + (logo ? ", logo : " + logo.note : ", pas de logo") + "."),
      h("h2", null, "Les couleurs, mesurées sur ce que tu as gardé"),
      h(Colours, { colours: brand.colours }),
      h("ul", { className: "tiles", "aria-label": "Visuels triés" }, brand.evidence.map((x) => h("li", { key: x.id },
        h("div", { className: "tile", "data-k": x.kept ? "yes" : "no", style: { cursor: "default" } }, h("img", { src: x.preview, alt: x.note }),
          h("span", { className: "tl" }, h("span", { className: "mark" }, x.kept ? "Gardé" : "Écarté"), h("span", { className: "n" }, x.note)))))),
      h("div", { className: "actions" },
        !briefDone && h(Button, { variant: "primary", onClick: ctx.follow }, "Les couleurs sont bonnes, passer au brief"),
        h(Button, { variant: briefDone ? "primary" : "secondary", onClick: () => setEditing(true) }, "Revoir mon tri")));
  }

  /* ================= brief ================= */
  const BRIEF_LABELS = { objective: "Objectif", audience: "Public", message: "Message", format: "Formats", layout: "Mise en page", fixed: "Ce qui ne bouge pas", cta: "Appel à l'action", language: "Langue" };
  const BRIEF_LONG = ["objective", "audience", "message", "layout", "fixed"];

  function BriefPanel({ ctx }) {
    const { pid } = ctx;
    const [data, setData] = useState(null);
    const [fields, setFields] = useState(null);
    const [saved, setSaved] = useState(false);
    const load = () => api.brief(pid).then((b) => { setData(b); setFields(b.fields); }).catch(ctx.fail);
    useEffect(() => { load(); }, [pid]);
    if (!fields) return h("p", { className: "muted" }, "Chargement du brief.");
    const set = (k, v) => { setFields({ ...fields, [k]: v }); setSaved(false); };
    const tokens = (fields.format || "").split(",").map((x) => x.trim()).filter(Boolean);
    const has = (f) => tokens.some((t) => t.toLowerCase().replace(/ /g, "-") === f);
    const toggle = (f) => set("format", (has(f) ? tokens.filter((t) => t.toLowerCase().replace(/ /g, "-") !== f) : [...tokens, f]).join(", "));
    const submit = (e) => {
      e.preventDefault();
      ctx.act(async () => {
        ctx.pin();
        const changed = Object.keys(fields).filter((k) => fields[k] !== data.fields[k]).map((k) => BRIEF_LABELS[k] || k);
        const r = await api.saveBrief(pid, fields);
        ctx.log("toi", "Brief relu et validé", changed.length ? "Corrigé : " + changed.join(", ") : "Rien à corriger");
        await ctx.refresh();
        ctx.done("Brief validé" + (r.left_out && r.left_out.length ? " ; mis de côté : " + r.left_out.join(", ") : "") + ".");
        setSaved(true);
        await load();
        await ctx.refresh();
        if (r.left_out.length) ctx.log("studio", "Formats mis de côté : " + r.left_out.join(", "), "");
      });
    };
    const keys = Object.keys(fields);
    return h("form", { className: "inner form", onSubmit: submit, noValidate: false },
      h("p", { className: "muted" }, "Le brief est pré-rempli. Corrige ce qui change, laisse le reste."),
      keys.map((k) => h(Field, { key: k, id: "f-" + k, label: BRIEF_LABELS[k] || k,
        hint: k === "format" ? "Sépare par des virgules. Un format que le studio ne sait pas faire est mis de côté, pas oublié." : undefined },
        BRIEF_LONG.includes(k) ? h("textarea", { id: "f-" + k, value: fields[k], required: ["objective", "audience", "message"].includes(k), onChange: (e) => set(k, e.target.value), style: { minHeight: "72px" } })
          : h("input", { id: "f-" + k, type: "text", value: fields[k], onChange: (e) => set(k, e.target.value) }))),
      h("div", { className: "field" }, h("span", { className: "lab" }, "Formats que le studio sait faire"),
        h("div", { className: "row" }, data.formats.map((f) => h("button", { key: f, type: "button", className: "chip", "aria-pressed": has(f), onClick: () => toggle(f) }, f)))),
      saved && h("div", { className: "sec" },
        h(Callout, { tone: "success", label: "Brief validé" }, "Formats retenus : " + (data.chosen.join(", ") || "aucun") + "."),
        data.left_out.length > 0 && h(Callout, { tone: "info", label: "Mis de côté" }, data.left_out.join(", ") + " : le studio ne produit que des images fixes pour l'instant. Ce format est noté dans le brief, aucune pièce ne sera fabriquée pour lui.")),
      !saved && data.left_out.length > 0 && h(Callout, { tone: "info", label: "Mis de côté" }, data.left_out.join(", ") + " : hors des formats que le studio sait faire."),
      h("div", { className: "actions" },
        h(Button, { type: "submit", variant: saved ? "secondary" : "primary", disabled: ctx.busy }, data.confirmed ? "Enregistrer les corrections" : "Valider le brief"),
        saved && h(Button, { variant: "primary", onClick: ctx.follow }, "Continuer vers les consignes")));
  }

  /* ================= instructions to the agents ================= */
  function MandatesPanel({ ctx }) {
    const { pid } = ctx;
    const [m, setM] = useState(null);
    useEffect(() => { api.mandates(pid).then(setM).catch(ctx.fail); }, [pid]);
    if (!m) return h("p", { className: "muted" }, "Chargement des consignes.");
    const setItem = (id, v) => setM({ ...m, items: m.items.map((x) => (x.id === id ? { ...x, mandate: v } : x)) });
    const submit = (e) => {
      e.preventDefault();
      ctx.act(async () => {
        ctx.pin();
        await api.saveMandates(pid, m.items, m.common);
        ctx.log("toi", "Consignes aux agents relues et validées", "Mandats : " + m.items.map((x) => x.mandate).join(" ; "));
        await ctx.refresh();
        ctx.done("Consignes validées : la divergence peut partir.");
        ctx.follow();
      });
    };
    return h("form", { className: "inner form", onSubmit: submit },
      h("p", { className: "muted" }, "Voici ce que chaque agent recevra. Rien ne part avant que tu les aies relues."),
      h(Field, { id: "common", label: "Consigne commune à tous les agents" }, h("textarea", { id: "common", value: m.common, onChange: (e) => setM({ ...m, common: e.target.value }) })),
      h("div", { className: "sec" }, h("h2", null, "Un mandat par agent"),
        m.items.map((it) => h(Field, { key: it.id, id: "m-" + it.id, label: "Agent " + it.id.toUpperCase() },
          h("input", { id: "m-" + it.id, type: "text", value: it.mandate, onChange: (e) => setItem(it.id, e.target.value) })))),
      h("div", { className: "actions" }, h(Button, { type: "submit", variant: "primary", disabled: ctx.busy }, m.confirmed ? "Enregistrer les corrections" : "Valider ces consignes")));
  }

  /* ================= divergence ================= */
  function DivergePanel({ ctx }) {
    const { pid, project } = ctx;
    const step = stepOf(project, "diverge");
    const [variants, setVariants] = useState([]);
    const [chosen, setChosen] = useState([]);
    const [formats, setFormats] = useState([]);
    useEffect(() => {
      if (step.status === "waiting" || step.status === "done") {
        api.variants(pid).then(setVariants).catch(ctx.fail);
        api.brief(pid).then((b) => setFormats(b.chosen)).catch(ctx.fail);
      }
    }, [pid, step.status]);
    const job = project.jobs.find((j) => j.kind === "diverge");
    const launch = () => ctx.act(async () => {
      ctx.pin();
      await api.diverge(pid);
      ctx.log("toi", "Divergence lancée", "Quatre agents écrivent chacun leur variante, à l'aveugle");
      await ctx.refresh();
    });
    if (step.status === "running" && job) return h("div", { className: "inner sec" }, h(JobBar, { job, label: "Les quatre agents écrivent" }), h("p", { className: "muted" }, "Chacun écrit sans voir les autres. Tu peux ouvrir une autre étape : le studio continue."));
    if (step.status === "todo") {
      const ready = stepOf(project, "mandates").status === "done";
      return h("div", { className: "inner sec" },
        h("p", { className: "lead" }, ready ? "Les consignes sont relues. Quatre agents vont écrire chacun une variante : une accroche, une sous-ligne, une image décrite." : "La divergence démarre quand les consignes aux agents sont relues."),
        h("div", { className: "actions" }, h(Button, { variant: "primary", disabled: ctx.busy || !ready, onClick: launch }, "Lancer la divergence")));
    }
    const inSeries = new Set(project.pieces.map((p) => p.variant));
    const done = step.status === "done";
    const toggle = (id) => setChosen((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id]));
    const pick = () => ctx.act(async () => {
      ctx.pin();
      const pcs = await api.pick(pid, chosen);
      ctx.log("toi", "Série choisie : " + plural(chosen.length, "variante", "variantes") + ", " + plural(pcs.length, "pièce", "pièces"), chosen.map((id) => { const v = variants.find((x) => x.id === id); return v.mandate + " : " + v.headline; }).join(" ; "));
      await ctx.refresh();
      ctx.follow();
    });
    return h("div", { className: "inner sec" },
      done ? h("p", { className: "lead" }, "La série est lancée : " + plural(project.pieces.length, "pièce", "pièces") + ".") :
        h("p", { className: "lead" }, "Choisis une variante, ou plusieurs pour faire une série. Chaque variante devient une pièce par format."),
      h("div", { className: "variants" }, variants.map((v) => {
        const on = done ? inSeries.has(v.id) : chosen.includes(v.id);
        return h("button", { key: v.id, type: "button", className: "var", "aria-pressed": on, disabled: done, style: done ? { cursor: "default" } : undefined, onClick: () => toggle(v.id) },
          h("span", { className: "cap" }, v.id.toUpperCase() + " · " + v.mandate),
          h("span", { className: "hl" }, v.headline),
          v.subline ? h("span", null, v.subline) : h("span", { className: "muted small" }, "Pas de sous-ligne"),
          h("span", { className: "small muted" }, "Image décrite : " + v.image_prompt),
          on && h("span", null, h(Badge, { tone: "success" }, done ? "Dans la série" : "Choisie")));
      })),
      !done && h("div", { className: "actions" },
        h(Button, { variant: "primary", disabled: ctx.busy || chosen.length === 0, onClick: pick }, "Créer la série"),
        h("span", { className: "small muted" }, chosen.length ? plural(chosen.length, "variante", "variantes") + " × " + plural(formats.length, "format", "formats") + " = " + plural(chosen.length * formats.length, "pièce", "pièces") + (formats.length ? " (" + formats.join(", ") + ")" : "") : "Aucune variante choisie.")));
  }

  /* ================= a piece: prompt, image, composition, check, decision ================= */
  function PiecePanel({ ctx, id }) {
    const { pid, project } = ctx;
    const pc = project.pieces.find((p) => p.id === id);
    const [prompt, setPrompt] = useState(pc ? pc.prompt : "");
    const [words, setWords] = useState("");
    const [redo, setRedo] = useState(false);
    const lastPrompt = useRef(pc && pc.prompt);
    useEffect(() => { if (pc && pc.prompt !== lastPrompt.current) { lastPrompt.current = pc.prompt; setPrompt(pc.prompt); } }, [pc && pc.prompt]);
    useEffect(() => { setRedo(false); setWords(""); }, [id]);
    if (!pc) return h("p", { className: "muted" }, "Cette pièce n'existe pas (encore).");
    const st = stageOf(pc, project.jobs);
    const idx = project.pieces.findIndex((p) => p.id === id);
    const next = project.pieces.find((p, i) => i > idx && stageOf(p, project.jobs).key !== "done");

    const draw = () => ctx.act(async () => {
      ctx.pin(); setRedo(false);
      await api.savePrompt(pid, id, prompt);
      await api.drawImage(pid, id);
      ctx.log("toi", "Image lancée pour " + pc.label, "Prompt relu : " + prompt);
      await ctx.refresh();
      ctx.done("Image lancée pour " + pc.label + " : son avancement est sur la ligne du haut.");
    });
    const compose = () => ctx.act(async () => {
      ctx.pin();
      const r = await api.compose(pid, id);
      ctx.log("studio", "Pièce composée : " + pc.label, r.check.pass + " réussis, " + r.check.warn + " alertes, " + r.check.fail + " échecs");
      await ctx.refresh();
    });
    const decide = (verdict) => ctx.act(async () => {
      ctx.pin();
      await api.decide(pid, id, verdict, words);
      ctx.log("toi", (verdict === "keep" ? "Gardée : " : "Recommencer : ") + pc.label, words.trim() || "Sans commentaire");
      setWords("");
      await ctx.refresh();
      ctx.done((verdict === "keep" ? "Gardée : " : "À refaire : ") + pc.label + ".");
    });

    const head = h("div", { className: "row" }, h(Tag, null, pc.variant.toUpperCase()), h(Tag, null, pc.format + " · " + pc.size[0] + " × " + pc.size[1]),
      h("span", { className: "cap" }, "Pièce " + (idx + 1) + " sur " + project.pieces.length));
    const copy = h("div", { className: "sec" }, h("strong", { style: { fontFamily: "var(--font-display)", fontSize: "var(--fs-h3)", color: "var(--text-heading)", lineHeight: "var(--lh-heading)" } }, pc.headline), pc.subline && h("p", null, pc.subline));
    const bans = pc.bans && pc.bans.length > 0 && h(Callout, { tone: "neutral", label: "Ce que tu as refusé, le studio le retient" }, h("ul", null, pc.bans.map((b, i) => h("li", { key: i }, b))));

    if (st.key === "prompt" || st.key === "running" || st.key === "compose") {
      const running = st.key === "running";
      const editable = st.key === "prompt" || redo;
      return h("div", { className: "inner sec" }, head, copy, bans,
        h("div", { className: "piece" },
          h(Frame, { src: pc.image, alt: "Image de " + pc.label, size: pc.size, empty: running ? "Le modèle dessine" : "Pas encore d'image" }),
          h("div", { className: "sec" },
            running && h(JobBar, { job: st.job, label: "Image de " + pc.label }),
            h(Field, { id: "prompt", label: "Le prompt de l'image", hint: editable ? "C'est ce que le modèle d'image va recevoir. Corrige-le avant de lancer." : undefined },
              h("textarea", { id: "prompt", className: "mono", value: prompt, readOnly: !editable, onChange: (e) => setPrompt(e.target.value) })),
            running && h("p", { className: "small muted" }, "Le studio dessine, tu peux ouvrir une autre pièce ou une autre étape."),
            editable && h("div", { className: "actions" },
              h(Button, { variant: "primary", disabled: ctx.busy || !prompt.trim(), onClick: draw }, st.key === "prompt" ? "Lancer l'image" : "Refaire l'image avec ce prompt"),
              redo && h(Button, { variant: "ghost", onClick: () => { setRedo(false); setPrompt(pc.prompt); } }, "Garder le prompt d'origine")),
            st.key === "compose" && h("div", { className: "actions" },
              h(Button, { variant: "primary", disabled: ctx.busy || redo, onClick: compose }, "Composer la pièce et la vérifier"),
              !redo && h(Button, { variant: "secondary", onClick: () => setRedo(true) }, "Corriger le prompt et refaire l'image")))));
    }
    /* composed: the piece, its check, the decision */
    const c = pc.check || { pass: 0, warn: 0, fail: 0, notes: [] };
    const badgeFor = (s) => (s === "fail" ? h(Badge, { tone: "danger" }, "Échec") : s === "warn" ? h(Badge, { tone: "neutral" }, "Alerte") : s === "pass" ? h(Badge, { tone: "success" }, "Réussi") : h(Badge, { tone: "info" }, "Note"));
    return h("div", { className: "inner sec" }, head,
      h("div", { className: "piece" },
        h(Frame, { src: pc.composed, alt: "Pièce composée : " + pc.label, size: pc.size }),
        h("div", { className: "sec" }, copy,
          h("h2", null, "La vérification"),
          h("div", { className: "counts" }, h(Badge, { tone: "success" }, c.pass + " réussis"), h(Badge, { tone: "neutral" }, plural(c.warn, "alerte", "alertes")), h(Badge, { tone: c.fail ? "danger" : "neutral" }, plural(c.fail, "échec", "échecs"))),
          c.notes.length > 0 ? h("ul", { className: "notes" }, c.notes.map((n, i) => h("li", { key: i }, badgeFor(n.status), h("span", null, n.say)))) : h("p", { className: "muted small" }, "Aucune note du juge."))),
      pc.decision && h(Callout, { tone: "success", label: "Gardée à " + clock(pc.decision.at * 1000) }, pc.decision.words || "Sans commentaire."),
      h("div", { className: "sec" },
        h(Field, { id: "words", label: pc.decision ? "Revenir sur cette décision ?" : "Garder, ou recommencer ?", hint: "Pour recommencer, dis pourquoi : c'est retenu pour le tour suivant. Pour garder, un mot est facultatif." },
          h("textarea", { id: "words", value: words, onChange: (e) => setWords(e.target.value), placeholder: "Par exemple : trop sombre, le titre se lit mal" })),
        h("div", { className: "actions" },
          !pc.decision && h(Button, { variant: "primary", disabled: ctx.busy, onClick: () => decide("keep") }, "Garder cette pièce"),
          h(Button, { variant: pc.decision ? "secondary" : "secondary", disabled: ctx.busy || !words.trim(), onClick: () => decide("again") }, "Recommencer"),
          !words.trim() && h("span", { className: "small muted" }, "Recommencer demande une raison."),
          next && h(Button, { variant: "ghost", onClick: () => ctx.open({ step: "image", piece: next.id }) }, "Pièce suivante"))));
  }

  function SeriesPanel({ ctx }) {
    const { project } = ctx;
    if (project.pieces.length === 0) return h("div", { className: "inner" }, h(Callout, { tone: "info", label: "Pas encore de série" }, "Les images, la composition et la décision commencent quand tu as choisi des variantes à la divergence."));
    return h("div", { className: "inner sec" }, h("p", { className: "lead" }, "Choisis une pièce pour la reprendre là où elle en est."), h(SeriesList, { ctx, current: null }));
  }

  function SeriesList({ ctx, current }) {
    const { project } = ctx;
    return h("ul", { className: "rows" }, project.pieces.map((pc) => {
      const st = stageOf(pc, project.jobs);
      return h("li", { key: pc.id }, h("button", { className: "rowbtn", "aria-label": pc.label + " : " + st.label.toLowerCase(), "aria-current": pc.id === current ? "true" : undefined, onClick: () => ctx.open({ step: "image", piece: pc.id }) },
        h("span", { className: "t" }, pc.label), h("span", { className: "s" }, st.label),
        st.job && h("span", { className: "sub" }, h(Progress, { value: st.job.progress }))));
    }));
  }

  /* ================= the frieze, the hand line, the journal ================= */
  function Frise({ ctx, targetStep }) {
    const { project } = ctx;
    const [open, setOpen] = useState(false);
    const cur = project.waiting[0] ? stepKey(project.waiting[0].step) : null;
    const items = FRISE.map((f) => {
      const s = stepOf(project, f.key);
      const state = f.key === cur ? "current" : s.status === "running" ? "running" : s.status === "done" ? "done" : s.status === "waiting" ? "waiting" : "todo";
      const text = state === "current" ? (s.status === "running" ? "À toi, studio au travail" : "À toi") : state === "running" ? "Studio au travail" : state === "waiting" ? "À toi" : state === "done" ? "Fait" : "À venir";
      return { ...f, state, text };
    });
    const at = Math.max(0, items.findIndex((i) => i.key === (targetStep || cur)));
    return h("nav", { className: "frise", "aria-label": "Les sept étapes", "data-open": open },
      h("button", { type: "button", className: "frise-toggle", "aria-expanded": open, onClick: () => setOpen(!open) },
        h("span", null, "Étape " + (at + 1) + " sur 7 : " + items[at].label), h("span", { className: "small muted" }, items[at].text)),
      h("ol", null, items.map((i) => h("li", { key: i.key },
        h("button", { type: "button", className: "step", "data-s": i.state, "aria-label": i.label + " : " + i.text.toLowerCase(), "aria-current": i.key === targetStep ? "step" : undefined,
          onClick: () => { setOpen(false); ctx.openStep(i.key); } },
          h("span", { className: "dotline" }, h("span", { className: "dot", "aria-hidden": "true" }), h("span", { className: "line", "aria-hidden": "true" })),
          h("span", { className: "state" }, i.text), h("span", { className: "label" }, i.label))))));
  }

  function HandLine({ ctx }) {
    const { project } = ctx;
    const now = ctx.now();
    const jobs = project.jobs, asks = project.waiting;
    const first = asks[0];
    const personSince = first ? (stepOf(project, first.step) || {}).since : null;
    const studioSince = jobs.length ? Math.min(...jobs.map((j) => j.since)) : null;
    const lines = [];
    if (first) lines.push(h("span", { key: "p" }, h("strong", null, "À toi"), personSince ? " depuis " + dur(now - personSince * 1000) : "", asks.length > 1 ? " · " + plural(asks.length - 1, "autre question attend", "autres questions attendent") : ""));
    if (jobs.length) lines.push(h("span", { key: "s" }, h("strong", null, "Le studio a la main"), " depuis " + dur(now - studioSince * 1000), " · " + plural(jobs.length, "travail en cours", "travaux en cours")));
    if (!first && !jobs.length) lines.push(h("span", { key: "n" }, h("strong", null, "Rien n'attend"), project.pieces.length ? " : toutes les pièces sont décidées." : " pour l'instant."));
    return h("div", { className: "hand" },
      h("p", { className: "says" }, lines.map((l, i) => h("span", { key: i, style: { display: "block" } }, l))),
      jobs.length > 0 && h("ul", { className: "jobs", "aria-label": "Travaux du studio en cours" }, jobs.slice(0, 4).map((j) => {
        const pc = j.piece && project.pieces.find((p) => p.id === j.piece);
        return h("li", { key: j.id, className: "job" }, h("span", null, (KIND[j.kind] || j.kind) + (pc ? " : " + pc.label : "")), h("span", { className: "mono" }, pct(j.progress)), h(Progress, { value: j.progress }));
      }), jobs.length > 4 && h("li", { className: "small muted" }, "et " + plural(jobs.length - 4, "autre", "autres"))));
  }

  function Journal({ entries }) {
    return h("section", { "aria-labelledby": "journal-h" },
      h("h2", { id: "journal-h", className: "cap", style: { marginBottom: "var(--space-3)" } }, "Journal des décisions"),
      entries.length === 0 ? h("p", { className: "small muted" }, "Chaque décision s'écrit ici avec son heure et sa raison.") :
        h("ol", { className: "journal" }, entries.slice(0, 40).map((e, i) => h("li", { key: e.at + "-" + i },
          h("time", { dateTime: new Date(e.at).toISOString() }, clock(e.at)),
          h("span", null, h("span", { className: "who" }, e.who === "toi" ? "Toi : " : "Studio : "), e.text),
          e.why && h("span", { className: "why" }, e.why)))));
  }

  /* ================= the application ================= */
  function App() {
    const [projects, setProjects] = useState([]);
    const [pid, setPid] = useState(null);
    const [project, setProject] = useState(null);
    const [view, setView] = useState({ kind: "projects" });
    const [journal, setJournal] = useState([]);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [, setTick] = useState(0);
    const [notice, setNotice] = useState(null);
    useEffect(() => { if (!notice) return; const t = setTimeout(() => setNotice(null), 8000); return () => clearTimeout(t); }, [notice]);
    const skew = useRef(0);
    const prevJobs = useRef([]);
    const headRef = useRef(null);

    const fail = useCallback((e) => setError(e.message || String(e)), []);
    const jr = useRef([]);
    const pidRef = useRef(null);
    pidRef.current = pid;
    const log = useCallback((who, text, why) => {
      const n = [{ at: Date.now(), who, text, why: why || "" }, ...jr.current];
      jr.current = n;
      setJournal(n);
      if (pidRef.current) saveJournal(pidRef.current, n);
    }, []);

    const loadList = useCallback(() => api.projects().then(setProjects).catch(fail), []);
    const refresh = useCallback(async () => {
      if (!pid) return null;
      try {
        const p = await api.project(pid);
        skew.current = p.now * 1000 - Date.now();
        const gone = prevJobs.current.filter((j) => !p.jobs.some((x) => x.id === j.id));
        gone.forEach((j) => {
          const pc = j.piece && p.pieces.find((x) => x.id === j.piece);
          log("studio", j.kind === "learn" ? "Lecture de la marque terminée" : j.kind === "diverge" ? "Les quatre variantes sont écrites" : "Image prête : " + (pc ? pc.label : j.piece), "");
        });
        prevJobs.current = p.jobs;
        setProject(p);
        return p;
      } catch (e) { fail(e); return null; }
    }, [pid, log, fail]);

    useEffect(() => { loadList(); api.health().catch(() => setError("Le serveur du studio ne répond pas.")); }, []);
    useEffect(() => {
      const fromHash = () => {
        const id = decodeURIComponent((location.hash || "").replace(/^#/, ""));
        if (id) { setPid(id); setView({ kind: "follow" }); } else setView({ kind: "projects" });
      };
      fromHash();
      addEventListener("hashchange", fromHash);
      return () => removeEventListener("hashchange", fromHash);
    }, []);
    useEffect(() => {
      if (!pid) return;
      setProject(null); prevJobs.current = []; jr.current = loadJournal(pid); setJournal(jr.current);
      refresh();
    }, [pid]);
    useEffect(() => { const t = setInterval(() => setTick((x) => x + 1), 1000); return () => clearInterval(t); }, []);
    const running = project && project.jobs.length > 0;
    useEffect(() => {
      if (!pid) return;
      const t = setInterval(refresh, running ? 600 : 5000);
      return () => clearInterval(t);
    }, [pid, running, refresh]);

    const act = useCallback(async (fn) => {
      setBusy(true); setError(null);
      try { return await fn(); } catch (e) { fail(e); } finally { setBusy(false); }
    }, [fail]);

    /* the question on screen stays until it is answered: a job that ends elsewhere does not change it under the person's eyes */
    const shown = useRef(null);
    const askKey = (a) => a.step + ":" + (a.piece || "");
    const front = project && (project.waiting.find((a) => shown.current && askKey(a) === shown.current) || project.waiting[0]);
    if (view.kind === "follow") shown.current = front ? askKey(front) : null;
    const target = view.kind === "step" ? { step: view.step, piece: view.piece } : front ? { step: front.step, piece: front.piece } : { step: null };
    const targetKey = view.kind + ":" + (target.step || "") + ":" + (target.piece || "");
    useEffect(() => { if (headRef.current) headRef.current.focus({ preventScroll: true }); }, [targetKey, pid]);

    const ctx = {
      pid, project, projects, busy, view, act, log, refresh, fail,
      now: () => Date.now() + skew.current,
      pin: () => setView((v) => (v.kind === "follow" && target.step ? { kind: "step", step: target.step, piece: target.piece } : v)),
      follow: () => setView({ kind: "follow" }),
      /* an answer that settles the question: back to the next one, with a line that says what was done */
      done: (text) => { shown.current = null; setNotice(text); setView({ kind: "follow" }); },
      open: (t) => setView({ kind: "step", step: t.step, piece: t.piece }),
      openStep: (key) => {
        if (key === "image" || key === "piece" || key === "decide") {
          const ask = project.waiting.find((a) => stepKey(a.step) === key && a.piece);
          return setView({ kind: "step", step: key, piece: ask ? ask.piece : undefined });
        }
        setView({ kind: "step", step: key });
      },
      selectProject: (id) => { location.hash = id; setPid(id); setView({ kind: "follow" }); },
      createProject: (name, from) => act(async () => {
        const p = await api.createProject(name, from);
        saveJournal(p.id, [{ at: Date.now(), who: "toi", text: from ? "Déclinaison créée : " + p.name : "Projet créé : " + p.name, why: from ? "Reprend la marque et le brief de l'original" : "" }]);
        await loadList();
        location.hash = p.id; setPid(p.id); setView({ kind: "follow" });
      }),
    };

    /* what the main area shows */
    let body, question, eyebrow;
    if (view.kind === "projects" || !pid) {
      eyebrow = "Projets"; question = "Choisis un projet ou crée-en un"; body = h(ProjectsPanel, { ctx });
    } else if (!project) {
      eyebrow = "Studio"; question = "Chargement du projet"; body = h("p", { className: "muted" }, "Un instant.");
    } else {
      const ask = view.kind === "follow" ? front : project.waiting.find((a) => a.step === target.step && (!target.piece || a.piece === target.piece));
      const t = target.step;
      const atFront = !!ask && ask === front;
      if (view.kind === "follow" || atFront) {
        eyebrow = ask ? "Ta question" + ((stepOf(project, ask.step) || {}).since ? " · posée il y a " + dur(ctx.now() - stepOf(project, ask.step).since * 1000) : "") : "Studio";
        question = ask ? ask.question : "Rien n'attend ta décision";
      } else {
        const st0 = stepOf(project, stepKey(t || "brand"));
        const pcx = target.piece && project.pieces.find((x) => x.id === target.piece);
        eyebrow = pcx ? "La série · pièce " + (project.pieces.indexOf(pcx) + 1) + " sur " + project.pieces.length : !ask && st0 && st0.status === "running" ? "Le studio travaille" : "Étape ouverte seule";
        question = ask ? ask.question : pcx ? pcx.label + " : " + stageOf(pcx, project.jobs).label.toLowerCase() : TITLES[t];
      }
      if (!t) body = project.pieces.length ? h("div", { className: "inner sec" }, h(Callout, { tone: "success", label: "À jour" }, project.pieces.every((p) => p.decision) ? "Toutes les pièces sont décidées. Tu peux relire la série à droite, ou créer une déclinaison depuis la liste des projets." : "Le studio travaille, rien ne demande ta décision pour l'instant. Ouvre une étape de la frise pour la reprendre.")) : h("div", { className: "inner" }, h(Callout, { tone: "info", label: "Rien en attente" }, "Ouvre une étape de la frise."));
      else if (t === "brand") body = h(BrandPanel, { ctx, key: "brand" + pid });
      else if (t === "brief") body = h(BriefPanel, { ctx, key: "brief" + pid });
      else if (t === "mandates") body = h(MandatesPanel, { ctx, key: "mand" + pid });
      else if (t === "diverge") body = h(DivergePanel, { ctx, key: "div" + pid });
      else if (target.piece) body = h(PiecePanel, { ctx, id: target.piece, key: target.piece });
      else body = h(SeriesPanel, { ctx });
    }

    let targetStep = view.kind === "step" ? stepKey(view.step) : undefined;
    const tpc = project && target.piece && project.pieces.find((x) => x.id === target.piece);
    if (view.kind === "step" && tpc) targetStep = { prompt: "image", running: "image", compose: "piece", decide: "decide", done: "decide" }[stageOf(tpc, project.jobs).key];
    const lastStudio = journal.find((e) => e.who === "studio");
    return h("div", null,
      h("span", { className: "sr", role: "status", "aria-live": "polite" }, lastStudio ? lastStudio.text : ""),
      h("header", { className: "top" },
        h("span", { className: "cap" }, "Studio"),
        project && view.kind !== "projects" ? h("span", { className: "name" }, project.name) : h("span", { className: "name" }, "Studio créatif"),
        project && view.kind !== "projects" && h("span", { className: "muted small" }, project.brand),
        h("span", { className: "grow" }),
        project && view.kind !== "projects" && h("span", { className: "small muted" }, project.waiting.length ? plural(project.waiting.length, "question attend", "questions attendent") : "Rien n'attend"),
        h("button", { type: "button", className: "linkbtn", onClick: () => { loadList(); setView({ kind: "projects" }); } }, "Projets")),
      project && view.kind !== "projects" && h(Frise, { ctx, targetStep: targetStep || (project.waiting[0] ? stepKey(project.waiting[0].step) : undefined) }),
      project && view.kind !== "projects" && h(HandLine, { ctx }),
      h("div", { className: "stage" },
        h("main", { className: "main" },
          error && h("div", { role: "alert" }, h(Callout, { tone: "risk", label: "Le studio refuse" }, error, " ", h("button", { className: "linkbtn", onClick: () => setError(null) }, "Fermer"))),
          notice && view.kind === "follow" && h("div", { className: "inner", role: "status" }, h(Callout, { tone: "success", label: "Fait" }, notice)),
          h("div", { className: "inner" },
            h(Eyebrow, null, eyebrow),
            h("h1", { className: "q", tabIndex: -1, ref: headRef }, question),
            view.kind === "step" && project && !(project.waiting[0] && target.step === project.waiting[0].step && (target.piece || null) === (project.waiting[0].piece || null)) && h("p", { className: "small", style: { marginTop: "var(--space-2)" } }, h("button", { className: "linkbtn", onClick: ctx.follow }, project.waiting[0] ? "Revenir à la question qui attend" : "Revenir à l'écran de départ"))),
          body),
        h("aside", { className: "side", "aria-label": "La série et le journal" },
          project && project.pieces.length > 0 && view.kind !== "projects" && h("section", { "aria-labelledby": "serie-h" },
            h("h2", { id: "serie-h", className: "cap", style: { marginBottom: "var(--space-3)" } }, "La série · " + plural(project.pieces.length, "pièce", "pièces")),
            h(SeriesList, { ctx, current: view.kind === "step" ? view.piece : (project.waiting[0] && project.waiting[0].piece) })),
          pid && h(Journal, { entries: journal }))));
  }

  ReactDOM.createRoot(document.getElementById("root")).render(h(App));
})();
