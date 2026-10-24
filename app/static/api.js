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

  const P = (p) => "/api/projects/" + encodeURIComponent(p);
  const B = (b) => "/api/brands/" + encodeURIComponent(b);
  Object.assign(api, {
    health: () => call("GET", "/api/health"),
    tasks: () => call("GET", "/api/tasks"),
    projects: () => call("GET", "/api/projects"),
    createProject: (name, from, brand, site) => call("POST", "/api/projects", { name, from, brand, site }),
    project: (p) => call("GET", P(p)),
    learnBrand: (p, mode, answers) => call("POST", P(p) + "/brand/learn", { mode, answers }),
    brand: (p) => call("GET", P(p) + "/brand"),
    keep: (p, kept, logo) => call("POST", P(p) + "/brand/keep", { kept, logo }),
    brief: (p) => call("GET", P(p) + "/brief"),
    saveBrief: (p, fields) => call("PUT", P(p) + "/brief", { fields }),
    mandates: (p) => call("GET", P(p) + "/mandates"),
    saveMandates: (p, items, common) => call("PUT", P(p) + "/mandates", { items, common }),
    diverge: (p) => call("POST", P(p) + "/diverge"),
    variants: (p) => call("GET", P(p) + "/variants"),
    pick: (p, variants) => call("POST", P(p) + "/pick", { variants }),
    piece: (p, i) => call("GET", P(p) + "/pieces/" + encodeURIComponent(i)),
    savePrompt: (p, i, prompt) => call("PUT", P(p) + "/pieces/" + encodeURIComponent(i) + "/prompt", { prompt }),
    drawImage: (p, i) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/image"),
    compose: (p, i) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/compose"),
    decide: (p, i, verdict, words) => call("POST", P(p) + "/pieces/" + encodeURIComponent(i) + "/decide", { verdict, words }),
    /* The studio holds brands, a brand holds projects. (`brand(p)` above is the old route of a project's brand; `getBrand(b)` is a brand.) */
    brands: () => call("GET", "/api/brands"),
    getBrand: (b) => call("GET", B(b)),
    createBrand: (name, site) => call("POST", "/api/brands", { name, site }),
    updateBrand: (b, fields) => call("PUT", B(b), fields), // fields: any of { name, site, description }
    discover: (b) => call("POST", B(b) + "/discover"),
    keepBrand: (b, kept, logo) => call("POST", B(b) + "/keep", { kept, logo }),
    brandBrief: (b) => call("GET", B(b) + "/brief"),
    saveBrandBrief: (b, fields) => call("PUT", B(b) + "/brief", { fields }), // fields: { what, who, voice, signature, never, colours }
    confirmBrand: (b, keys) => call("POST", B(b) + "/confirm", { keys }), // no keys: every value to confirm
    createProjectIn: (b, name, from) => call("POST", B(b) + "/projects", { name, from }),
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
