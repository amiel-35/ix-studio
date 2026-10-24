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

  /* a file as the body of the request (the logo): its type is the Content-Type, its name goes in X-Filename */
  async function upload(path, file) {
    const h = { "Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name || "") };
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
    tasks: () => call("GET", "/api/tasks"),
    projects: () => call("GET", "/api/projects"),
    project: (p) => call("GET", P(p)),
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
