/* api.js: the only place the interface talks to the studio (see app/API.md).
   Today the local server answers with a simulated studio; tomorrow a central one, behind an authentication:
   set `api.token` (or replace `headers`) and nothing else in the interface changes. */
(function () {
  const api = { base: "", token: null };

  function headers() {
    const h = { "Content-Type": "application/json" };
    if (api.token) h.Authorization = "Bearer " + api.token;
    return h;
  }

  async function call(method, path, body) {
    const r = await fetch(api.base + path, { method, headers: headers(), body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(data.error || r.status + " " + r.statusText);
      err.status = r.status;
      throw err;
    }
    return data;
  }

  /* a file as the body of the request (the logo, a piece to judge): its type is the Content-Type, its name goes in X-Filename, and what comes
     with it, if anything, in X-Judge (JSON) */
  async function upload(path, file, meta) {
    const h = { "Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name || "") };
    if (meta) h["X-Judge"] = encodeURIComponent(JSON.stringify(meta));
    if (api.token) h.Authorization = "Bearer " + api.token;
    const r = await fetch(api.base + path, { method: "POST", headers: h, body: file });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const err = new Error(data.error || r.status + " " + r.statusText);
      err.status = r.status;
      throw err;
    }
    return data;
  }

  /* a file (a png, a zip): fetched with the headers, so that a token goes with it; answers {blob, name}, the name being the one the studio gave */
  async function download(path) {
    const h = {};
    if (api.token) h.Authorization = "Bearer " + api.token;
    const r = await fetch(api.base + path, { headers: h });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      const err = new Error(data.error || r.status + " " + r.statusText);
      err.status = r.status;
      throw err;
    }
    const m = /filename="([^"]+)"/.exec(r.headers.get("Content-Disposition") || "");
    return { blob: await r.blob(), name: m ? m[1] : "piece" };
  }

  const P = (p) => "/api/projects/" + encodeURIComponent(p);
  const B = (b) => "/api/brands/" + encodeURIComponent(b);
  Object.assign(api, {
    health: () => call("GET", "/api/health"),
    machine: () => call("GET", "/api/machine"), // what the machine lacks to run the studio for real: { ok, missing: [{ key, label, say }] }
    /* engines: the engine of the images and the engine of the texts (claude, or openrouter with its key and its model). The key goes in, never comes back: only key_saved. */
    engines: () => call("GET", "/api/engines"), // { image_engine, image_engines, text_engine, text_engines, openrouter_model, key_saved }
    saveEngine: (engine) => call("PUT", "/api/engines/image", { engine }),
    saveTextEngine: (engine, key, model) => call("PUT", "/api/engines/text", { engine, key, model }), // key: undefined keeps the saved one, "" forgets it
    tasks: () => call("GET", "/api/tasks"),
    projects: () => call("GET", "/api/projects"),
    project: (p) => call("GET", P(p)),
    brief: (p) => call("GET", P(p) + "/brief"),
    saveBrief: (p, fields) => call("PUT", P(p) + "/brief", { fields }),
    /* interview: a few questions, an agent pre-fills the brief from the answers (a job); the person corrects it in the brief's form */
    interview: (p, answers) => (answers ? call("POST", P(p) + "/interview", { answers }) : call("GET", P(p) + "/interview")), // GET { questions, proposed: { fields, missing } | null, job, error }; POST answers: [text], the job
    mandates: (p) => call("GET", P(p) + "/mandates"),
    saveMandates: (p, items, common) => call("PUT", P(p) + "/mandates", { items, common }),
    diverge: (p) => call("POST", P(p) + "/diverge"),
    variants: (p) => call("GET", P(p) + "/variants"),
    pick: (p, variants) => call("POST", P(p) + "/pick", { variants }),
    piece: (p, i) => call("GET", P(p) + "/pieces/" + encodeURIComponent(i)),
    savePrompt: (p, i, prompt) => call("PUT", P(p) + "/pieces/" + encodeURIComponent(i) + "/prompt", { prompt }),
    saveVariantPrompt: (p, v, prompt) => call("PUT", P(p) + "/variants/" + encodeURIComponent(v) + "/prompt", { prompt }), // the prompt of a variant, shared by its formats
    saveVariantText: (p, v, headline, subline) => call("PUT", P(p) + "/variants/" + encodeURIComponent(v) + "/text", { headline, subline }), // the words of a variant, corrected before it is composed
    drawImages: (p, variant) => call("POST", P(p) + "/images", variant ? { variant } : {}), // every image that is missing (those of one variant): answers {jobs}
    composeAll: (p) => call("POST", P(p) + "/compose"), // every piece that has its image: answers {composed, failed}
    drawImage: (p, i) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/image"),
    compose: (p, i) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/compose"),
    decide: (p, i, verdict, words) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/decide", { verdict, words }),
    judgePiece: (p, i) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/judge"), // the judge of a composed piece, run again
    runReader: (p, i, n) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/readers/" + n + "/run"), // reader n of a composed piece, run again alone
    /* a piece judged on its own: dropped with the brief it answers and, if any, its brand */
    judgements: () => call("GET", "/api/judgements"),
    judgement: (j) => call("GET", "/api/judgements/" + encodeURIComponent(j)),
    judge: (file, meta) => upload("/api/judgements", file, meta), // a png or jpg File; meta: { brand, brief: { objective, audience, message, cta, fixed, personas } }. Answers the judgement
    runJudgement: (j) => call("POST", "/api/judgements/" + encodeURIComponent(j) + "/run"),
    runJudgementReader: (j, n) => call("POST", "/api/judgements/" + encodeURIComponent(j) + "/readers/" + n + "/run"), // reader n, run again alone
    rounds: (j) => call("GET", "/api/judgements/" + encodeURIComponent(j) + "/rounds"), // {status, synthesis: {holds, ambiguous, once}, error, job}: the piece judged three times
    runRounds: (j) => call("POST", "/api/judgements/" + encodeURIComponent(j) + "/rounds"), // launch the three rounds (again, once done): a job
    judgementPage: (j) => download("/api/judgements/" + encodeURIComponent(j) + "/page"), // the flat page of the verdict, an html file
    /* The studio holds brands, a brand holds projects. (The routes of a project's brand, `/api/projects/{p}/brand…`, are kept by the studio but the interface no longer uses them.) */
    brands: () => call("GET", "/api/brands"),
    getBrand: (b) => call("GET", B(b)),
    createBrand: (name, site) => call("POST", "/api/brands", { name, site }),
    updateBrand: (b, fields) => call("PUT", B(b), fields), // fields: any of { name, site, description }
    uploadLogo: (b, file) => upload(B(b) + "/logo", file), // a png, jpg or svg File: chosen as the logo at once. Answers the brand
    discover: (b) => call("POST", B(b) + "/discover"),
    keepBrand: (b, kept, logo) => call("POST", B(b) + "/keep", { kept, logo }),
    brandBrief: (b) => call("GET", B(b) + "/brief"),
    saveBrandBrief: (b, fields) => call("PUT", B(b) + "/brief", { fields }), // fields: { what, who, voice, signature, never, colours }
    confirmBrand: (b, keys) => call("POST", B(b) + "/confirm", { keys }), // no keys: every value to confirm
    /* the personas of a brand: the studio proposes up to four (a job), the person keeps the ones they corrected or wrote */
    personas: (b) => call("GET", B(b) + "/personas"), // { personas: [text], proposed: [text], can_propose, job, error }
    proposePersonas: (b) => call("POST", B(b) + "/personas/propose"),
    savePersonas: (b, personas) => call("PUT", B(b) + "/personas", { personas }), // only these are the brand's; the proposal is settled
    /* the names of a brand: the studio proposes up to eight (a job), the person keeps some, writes some, and chooses one as the brand's name */
    names: (b) => call("GET", B(b) + "/names"), // { name, names: [{name, why}], proposed: [{name, why}], can_propose, job, error }
    proposeNames: (b) => call("POST", B(b) + "/names/propose"),
    saveNames: (b, names, chosen) => call("PUT", B(b) + "/names", { names, chosen }), // chosen: one of names, becomes the brand's name
    /* export: the brand folder, a zip (brand.md, MOTION.md if any, the logo, brand.json with each value's source and status); answers {blob, name} */
    exportBrand: (b) => download(B(b) + "/export"),
    /* brief_export: the brief of a project (confirmed or not) as a Markdown file to download; `r` is the project's id */
    exportBrief: (r) => download("/api/briefs/" + encodeURIComponent(r) + "/export"),
    /* competitors: the studio proposes up to six (a job), the person keeps the ones they corrected or wrote */
    competitors: (b) => call("GET", B(b) + "/competitors"), // { competitors: [text], proposed: [text], can_propose, job, error }
    proposeCompetitors: (b) => call("POST", B(b) + "/competitors/propose"),
    saveCompetitors: (b, competitors) => call("PUT", B(b) + "/competitors", { competitors }), // only these are the brand's; the proposal is settled
    /* files: the person drops the charter and visuals (twenty at most) on a brand; the studio reads them and proposes brand values, each to confirm */
    brandFiles: (b) => call("GET", B(b) + "/files"), // { files: [{name, size}], max, proposed: [{kind, value, role, file, state}], fonts: [{family, role}], can_propose, job, error }
    addBrandFiles: async (b, files) => { // a list of Files (pdf, png, jpg, webp or gif), sent one by one; answers the last view
      let r = null;
      for (const f of files) r = await upload(B(b) + "/files", f);
      return r;
    },
    readBrandFiles: (b) => call("POST", B(b) + "/files/read"), // a job: the studio proposes values read in the files
    keepBrandValues: (b, values, replace) => call("PUT", B(b) + "/files/values", { values, replace }), // only these enter the brand; 409 if confirmed colours would be replaced and replace is not true
    /* landscape: the competitors of a market, without a brand; asked and answered at once, nothing is kept (the person keeps through saveCompetitors) */
    landscape: (market) => call("POST", "/api/competitors", { market }), // { competitors: [text] }
    /* research: the studio searches the web for what is said of a brand (a job, ten results at most), the person keeps or drops each; only addresses are kept */
    research: (b) => call("GET", B(b) + "/research"), // { research: [{url, brings, belonging}], proposed: [{url, brings, belonging}], job, error }
    proposeResearch: (b) => call("POST", B(b) + "/research/propose"),
    saveResearch: (b, research) => call("PUT", B(b) + "/research", { research }), // only these are the brand's; the proposal is settled
    /* logos: the studio proposes up to four tracks drawn in SVG (a job), the person keeps or drops each, and chooses one of the kept as the brand's logo */
    logos: (b) => call("GET", B(b) + "/logo/tracks"), // { tracks: [{id, idea, svg}], proposed: [{id, idea, svg}], can_propose, job, error }
    proposeLogos: (b) => call("POST", B(b) + "/logo/propose"),
    keepLogos: (b, keep) => call("PUT", B(b) + "/logo/tracks", { keep }), // keep: ids among tracks and proposed; only these stay
    chooseLogo: (b, id) => call("POST", B(b) + "/logo/choose", { id }), // id: one of tracks, becomes the brand's logo
    /* texts: the studio proposes up to six hooks and posts for a project (a job), the person keeps the ones they corrected or wrote */
    texts: (p) => call("GET", P(p) + "/texts"), // { texts: [text], proposed: [text], can_propose, job, error }
    proposeTexts: (p) => call("POST", P(p) + "/texts/propose"),
    saveTexts: (p, texts) => call("PUT", P(p) + "/texts", { texts }), // only these are the project's; the proposal is settled
    /* storyboard: the script and the shots of a project's film: the studio proposes (a job), the person corrects and saves, then the film is rendered (a job) */
    storyboard: (p) => call("GET", P(p) + "/storyboard"), // { script, shots: [{ seconds, visual, text, colour, read }], saved, can_propose, job, error, film: { url, seconds } | null, film_job, film_error }
    proposeStoryboard: (p) => call("POST", P(p) + "/storyboard/propose"),
    saveStoryboard: (p, script, shots) => call("PUT", P(p) + "/storyboard", { script, shots }),
    renderFilm: (p) => call("POST", P(p) + "/storyboard/render"),
    downloadFilm: (p) => download(P(p) + "/storyboard/film"), // the film, an mp4
    createProjectIn: (b, name, from) => call("POST", B(b) + "/projects", { name, from }),
    downloadPiece: (p, i) => download(P(p) + "/pieces/" + encodeURIComponent(i) + "/download"), // the composed piece, a png at its size
    downloadKept: (p) => download(P(p) + "/download"), // every piece kept, a zip
    updateProject: (p, fields) => call("PUT", P(p), fields), // fields: { name }
    job: (j) => call("GET", "/api/jobs/" + encodeURIComponent(j)),
    /* Follows a job until it ends; onProgress(job) at each step. Resolves with the finished job. */
    async waitJob(job, onProgress, every = 400) {
      let j = job;
      while (j && j.id && j.status === "running") {
        if (onProgress) onProgress(j);
        await new Promise((r) => setTimeout(r, every));
        j = await api.job(j.id);
      }
      if (onProgress) onProgress(j);
      return j;
    },
  });

  window.studioApi = api;
})();
