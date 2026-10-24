"""backend_studio: the real studio behind the API. Same methods and same shapes as backend_stub, but every step runs the
tools of this repository (scripts/brandkit, scripts/studio, scripts/collect) and, for the writing, `claude -p`.

A project is a folder of STUDIO_HOME (default ~/ix-studio-projets):

    <id>/project.json   name, brand, site, origin, the person's choices, the brief and the instructions, the pieces, the jobs
    <id>/brand/         the brand dossier of scripts/brandkit (collect/ holds what was read on the site)
    <id>/piece/         the piece of scripts/studio: brand.md, brief.md, references.md, variants/, pieces/<piece>/
    <id>/logs/          one log per job (every command, its output)

The state lives on that disk only: a restart finds everything (a job that was running is then marked failed). The long
steps are jobs: a thread that runs sub-processes through an injected `runner(argv, cwd, env, timeout) -> Result`, so the
tests give it a fake one that calls neither `claude`, nor `codex`, nor the network.
"""

import contextlib
import importlib.util
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import uuid
from pathlib import Path
from typing import NamedTuple

import workflow
from workflow import FORMATS, Conflict, NotFound

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
STUDIO = SCRIPTS / "studio"
BRANDKIT = SCRIPTS / "brandkit"
COLLECT = SCRIPTS / "collect" / "collect.mjs"

DURATION = {"learn": 75.0, "mandates": 45.0, "diverge": 150.0, "image": 150.0}  # expected seconds: the progress is an estimate on these
CAP = 0.95  # a running job never reads more than this
DEFAULT_COMMON = ("Écrire dans la langue du brief ; aucun chiffre, lieu, label ni promesse qui ne soit dans la marque ou dans le brief ; "
                  "relire chaque ligne pour y traquer un double sens ; l'image ne contient aucun texte.")
DEFAULT_MANDATES = ["La chose elle-même, vue de près", "Démonter une idée reçue", "Le point de vue de celui qui l'achète",
                    "Rupture : ce que personne ne montre dans cette catégorie"]
DEFAULT_BRIEF = {"objective": "", "audience": "", "message": "", "format": "post-4x5", "layout": "",
                 "fixed": "les couleurs et les polices de la marque", "cta": "", "language": "fr"}
BRIEF_FILE_KEYS = ("objective", "audience", "message", "format", "layout", "fixed", "cta", "language")


class ToolError(ValueError):
    """A command failed: a sentence a person can read. A ValueError, so an API call that hits it answers 400."""


class Result(NamedTuple):
    code: int
    out: str
    err: str


def run_command(argv, cwd=None, env=None, timeout=None) -> Result:
    """The real runner. Never waits for an input (stdin is closed: codex and claude would wait for it), never raises."""
    try:
        r = subprocess.run([str(a) for a in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           errors="replace", timeout=timeout)
        return Result(r.returncode, r.stdout or "", r.stderr or "")
    except subprocess.TimeoutExpired as err:
        out = err.stdout.decode("utf-8", "replace") if isinstance(err.stdout, bytes) else (err.stdout or "")
        return Result(124, out, f"no answer after {int(timeout or 0)} s")
    except FileNotFoundError:
        return Result(127, "", f"command not found: {argv[0]}")
    except OSError as err:
        return Result(126, "", f"cannot run {argv[0]}: {err}")


def tail(res: Result, n=240) -> str:
    """The last meaningful line of a failed command, to say why in one line."""
    for text in (res.err, res.out):
        lines = [x.strip() for x in text.splitlines() if x.strip()]
        if lines:
            return re.sub(r"^studio: ", "", lines[-1])[:n]
    return f"exit {res.code}"


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:32]


def normalise_site(raw: str) -> str:
    """The address of a brand's site, as https://host/path, or "" when none is given. Refuses what is not a public web address."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    u = urllib.parse.urlsplit(raw)
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not host:
        raise ValueError("site: give a web address (https://…)")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        local = ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified
    else:
        local = host == "localhost" or host.endswith((".local", ".localhost", ".internal")) or "." not in host
    if local:
        raise ValueError("site: a private or local address cannot be read")
    port = f":{u.port}" if u.port else ""
    return urllib.parse.urlunsplit((u.scheme, host + port, u.path or "/", u.query, ""))  # no credentials, no fragment


def hex_of(text: str):
    m = re.search(r"#[0-9a-fA-F]{6}\b", text or "")
    return m.group(0).lower() if m else None


def luminance(h: str) -> float:
    rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


_FILES = None


def studio_files():
    """scripts/studio/files.py, loaded where it is, to read the variants as the studio does (one source of truth for their format)."""
    global _FILES
    if _FILES is None:
        spec = importlib.util.spec_from_file_location("ixs_studio_files", STUDIO / "files.py")
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(STUDIO))
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.path.remove(str(STUDIO))
        _FILES = mod
    return _FILES


def check_variant(path: Path, vid: str):
    """(ok, why not) for one variant file, with the rules of studio's load_variants."""
    f = studio_files()
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return False, f"{vid}: not readable JSON ({err})"
    if not isinstance(v, dict):
        return False, f"{vid}: not a JSON object"
    for k in f.VARIANT_KEYS:
        if v.get(k) in ("", None):
            return False, f"{vid}: missing key {k!r}"
    if not isinstance(v["default"], dict) or not all(v["default"].get(k) for k in ("headline", "image")):
        return False, f"{vid}: 'default' needs 'headline' and 'image'"
    if f.norm_layout(v["layout"]) not in f.LAYOUTS:
        return False, f"{vid}: layout must be one of {', '.join(f.LAYOUTS)}"
    if v["ground"] not in f.GROUNDS:
        return False, f"{vid}: ground must be one of {', '.join(f.GROUNDS)}"
    if v.get("fit", "contain") not in ("contain", "cover"):
        return False, f"{vid}: fit must be contain or cover"
    return True, ""


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def one_line(text: str) -> str:
    return " ".join(str(text or "").split())


class StudioBackend:
    name = "studio"

    def __init__(self, home=None, runner=run_command, claude_model="sonnet", image_engine=None):
        self.home = Path(home or os.environ.get("STUDIO_HOME") or Path.home() / "ix-studio-projets").expanduser()
        self.home.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.claude_model = claude_model
        self.image_engine = image_engine or os.environ.get("STUDIO_IMAGE_ENGINE", "auto")
        self._state = threading.RLock()  # short: reading and writing project.json
        self._locks = {}  # one lock per project for the long operations that rewrite files (keep, pick, compose, decide)
        self._log_lock = threading.Lock()
        self._jobs = {}  # job id -> project id
        self._recover()

    # ---------- the disk ----------
    def _dir(self, pid) -> Path:
        if not re.fullmatch(r"[\w-]+", pid or ""):
            raise NotFound(f"no project {pid}")
        return self.home / pid

    def _load(self, pid) -> dict:
        p = read_json(self._dir(pid) / "project.json")
        if not isinstance(p, dict):
            raise NotFound(f"no project {pid}")
        return p

    def _save(self, p):
        write_json(self._dir(p["id"]) / "project.json", p)

    def _mutate(self, pid, fn):
        with self._state:
            p = self._load(pid)
            out = fn(p)
            self._save(p)
            return out

    @contextlib.contextmanager
    def _op(self, pid):
        with self._state:
            lock = self._locks.setdefault(pid, threading.Lock())
        with lock:
            yield

    def _ids(self) -> list:
        found = []
        for d in self.home.iterdir() if self.home.is_dir() else []:
            p = read_json(d / "project.json") if d.is_dir() else None
            if isinstance(p, dict) and p.get("id") == d.name:
                found.append((p.get("created", 0), d.name))
        return [i for _, i in sorted(found)]

    def _recover(self):
        """After a restart: the jobs that were running died with the server. Say so, and index the others."""
        for pid in self._ids():
            def fix(p):
                for j in p["jobs"]:
                    self._jobs[j["id"]] = pid
                    if j["status"] == "running":
                        j.update(status="failed", end=time.time(), error="interrompu : le serveur a redémarré", message="interrompu : le serveur a redémarré")
                        p["since"][workflow.KIND_STEP[j["kind"]]] = time.time()
            self._mutate(pid, fix)

    @staticmethod
    def _mark(p, *keys):
        """Note that the hand changed on these steps now: the interface says who holds it and since when."""
        for k in keys:
            p["since"][k] = time.time()

    def _brand_dir(self, pid) -> Path:
        return self._dir(pid) / "brand"

    def _piece_dir(self, pid) -> Path:
        return self._dir(pid) / "piece"

    # ---------- commands ----------
    def _env(self, claude=False):
        env = dict(os.environ)
        if claude and not env.get("STUDIO_CLAUDE_USE_API_KEY"):
            env.pop("ANTHROPIC_API_KEY", None)  # `claude -p` bills the plan, not an API key left in the environment
        return env

    def _sh(self, log, argv, cwd=None, timeout=None, claude=False) -> Result:
        """Run a command through the runner and write what it did in the log."""
        res = self.runner([str(a) for a in argv], cwd=str(cwd) if cwd else None, env=self._env(claude), timeout=timeout)
        if log:
            with self._log_lock:
                Path(log).parent.mkdir(parents=True, exist_ok=True)
                with open(log, "a", encoding="utf-8") as f:
                    f.write("$ " + " ".join(shlex_quote(a) for a in argv) + f"\n[exit {res.code}]\n")
                    if res.out.strip():
                        f.write(res.out.rstrip() + "\n")
                    if res.err.strip():
                        f.write("[stderr]\n" + res.err.rstrip() + "\n")
                    f.write("\n")
        return res

    def _must(self, log, argv, **kw) -> Result:
        res = self._sh(log, argv, **kw)
        if res.code:
            raise ToolError(tail(res))
        return res

    def _py(self, script, *args):
        return [sys.executable, script, *args]

    def _studio(self, log, *args, **kw):
        return self._must(log, self._py(STUDIO, *args), **kw)

    def _brandkit(self, log, *args, **kw):
        return self._must(log, self._py(BRANDKIT, *args), **kw)

    def _claude(self, prompt, *flags):
        exe = os.environ.get("STUDIO_CLAUDE_BIN") or "claude"
        # the prompt comes first: --tools takes a list and would swallow what follows it
        return [exe, "-p", prompt, "--model", self.claude_model, "--no-session-persistence", "--restricted", *flags]

    def _cmd_log(self, pid) -> Path:
        return self._dir(pid) / "logs" / "commands.log"

    # ---------- jobs ----------
    def _job_public(self, j, now=None):
        now = now or time.time()
        progress, eta = 1.0 if j["status"] == "done" else 0.0, 0.0
        if j["status"] == "running":
            dur = DURATION[j["kind"]]
            progress = min(CAP, max(0.0, (now - j["start"]) / dur))
            eta = max(3.0, round(dur - (now - j["start"]), 1))
        return {"id": j["id"], "kind": j["kind"], "status": j["status"], "progress": round(progress, 3), "message": j.get("message", ""),
                "result": j.get("result"), "piece": j.get("piece"), "error": j.get("error"), "eta": eta}

    def _spawn(self, pid, kind, piece, body):
        job = {"id": "job-" + uuid.uuid4().hex[:10], "kind": kind, "piece": piece, "status": "running", "start": time.time(),
               "message": "", "error": None, "result": None}

        def add(p):
            p["jobs"].append(job)
            if len(p["jobs"]) > 80:
                p["jobs"] = [j for j in p["jobs"] if j["status"] == "running"] + [j for j in p["jobs"] if j["status"] != "running"][-60:]
            self._mark(p, workflow.KIND_STEP[kind])
        self._mutate(pid, add)
        self._jobs[job["id"]] = pid
        threading.Thread(target=self._run_job, args=(pid, job["id"], body), daemon=True, name=job["id"]).start()
        return self._job_public(job)

    def _run_job(self, pid, jid, body):
        status, error, message = "done", None, "terminé"
        try:
            message = body(jid) or message  # a body may return what it wants said when it ends
        except ToolError as err:
            status, error = "failed", str(err)
            message = error
        except Exception as err:  # a bug is shown to the person as a failed job, not lost in a thread
            status, error = "failed", f"erreur interne : {type(err).__name__}: {err}"
            message = error

        def end(p):
            for j in p["jobs"]:
                if j["id"] == jid:
                    j.update(status=status, end=time.time(), error=error, message=message)
                    steps = [workflow.KIND_STEP[j["kind"]]] + (["piece"] if j["kind"] == "image" and status == "done" else [])
                    self._mark(p, *steps)
        self._mutate(pid, end)

    def _phase(self, pid, jid, message):
        def say(p):
            for j in p["jobs"]:
                if j["id"] == jid:
                    j["message"] = message
        self._mutate(pid, say)

    def _joblog(self, pid, jid) -> Path:
        return self._dir(pid) / "logs" / f"{jid}.log"

    def _running(self, p, kind, piece=None):
        return next((j for j in p["jobs"] if j["kind"] == kind and j["status"] == "running" and (piece is None or j.get("piece") == piece)), None)

    def job(self, jid):
        pid = self._jobs.get(jid)
        if not pid:
            raise NotFound(f"no job {jid}")
        for j in self._load(pid)["jobs"]:
            if j["id"] == jid:
                return self._job_public(j)
        raise NotFound(f"no job {jid}")

    # ---------- the project and what waits for the person ----------
    def _variant_files(self, pid) -> list:
        return sorted((self._piece_dir(pid) / "variants").glob("*.json"), key=lambda f: (len(f.stem), f.stem))

    def _url(self, pid, rel, f: Path) -> str:
        return f"/files/{urllib.parse.quote(pid)}/{urllib.parse.quote(rel)}?v={int(f.stat().st_mtime)}"

    def _piece_view(self, pid, e) -> dict:
        d = self._piece_dir(pid) / e["dir"]
        rel = f"piece/{e['dir']}".rstrip("/")
        v = read_json(d / "variants" / f"{e['variant']}.json", {}) or {}
        img = next((n for n in ("image.png", "image.jpg") if (d / n).exists()), None)
        png, chk = d / "piece.png", read_json(d / "check.json")
        composed = bool(png.exists() and isinstance(chk, dict))
        check = None
        if composed:
            s = chk.get("summary", {})
            notes = [{"status": r["status"], "say": r["say"]} for r in chk.get("results", []) if r.get("status") != "pass"]
            notes += [{"status": n.get("level", "note"), "say": n.get("say", "")} for n in chk.get("judge", [])]
            check = {"pass": s.get("pass", 0), "warn": s.get("warn", 0), "fail": s.get("fail", 0), "major": s.get("major", 0), "notes": notes}
        decision = e.get("decision")
        status = "composed" if composed else "image" if img else "again" if e.get("bans") else "picked"
        return {"id": e["id"], "label": e["label"], "variant": e["variant"], "format": e["format"], "size": list(FORMATS[e["format"]]),
                "headline": v.get("headline", ""), "subline": v.get("subline", ""), "prompt": v.get("image_prompt", ""),
                "image": self._url(pid, f"{rel}/{img}", d / img) if img else None,
                "composed": self._url(pid, f"{rel}/piece.png", png) if composed else None, "check": check, "decision": decision,
                "status": status, "bans": list(e.get("bans", []))}

    def _failed(self, p) -> list:
        last = {}
        for j in p["jobs"]:  # in order: the last job of a kind (and a piece) decides
            last[(j["kind"], j.get("piece"))] = j
        return [{"kind": j["kind"], "piece": j.get("piece"), "error": j.get("error"), "at": j.get("end")} for j in last.values() if j["status"] == "failed"]

    def _evidence_count(self, p) -> int:
        return len(self._sortable(p)[0]) if p["learn"]["learned"] and not p["brand"]["kept"] else 0

    def _wf_state(self, p, now) -> dict:
        pid = p["id"]
        return {"id": pid, "name": p["name"], "brand": p["brand_name"], "can_learn": bool(p["site"]),
                "learned": p["learn"]["learned"], "kept": p["brand"]["kept"], "evidence": self._evidence_count(p),
                "brief_confirmed": p["brief"]["confirmed"], "mandates_confirmed": p["mandates"]["confirmed"],
                "variants": len(self._variant_files(pid)), "pieces": [self._piece_view(pid, e) for e in p["pieces"]],
                "running": [{"id": j["id"], "kind": j["kind"], "piece": j.get("piece"), "start": j["start"],
                             **{k: v for k, v in self._job_public(j, now).items() if k in ("progress", "message")}}
                            for j in p["jobs"] if j["status"] == "running"],
                "failed": self._failed(p), "since": p["since"]}

    def _view(self, p):
        now = time.time()
        return workflow.project_view(self._wf_state(p, now), now)

    # ---------- routes ----------
    def health(self):
        which = shutil.which
        return {"ok": True, "backend": self.name, "tools": {"claude": bool(which(os.environ.get("STUDIO_CLAUDE_BIN") or "claude")),
                                                              "codex": bool(which("codex")), "node": bool(which("node")),
                                                              "ffmpeg": bool(which("ffmpeg"))}}

    def list_projects(self):
        return [{"id": v["id"], "name": v["name"], "waiting": len(v["waiting"])} for v in (self._view(self._load(i)) for i in self._ids())]

    def tasks(self):
        entries, jobs, now = [], [], time.time()
        for pid in self._ids():
            p = self._load(pid)
            s = self._wf_state(p, now)
            entries.append((s, workflow.project_view(s, now)))
            for j in p["jobs"]:
                if j["status"] == "running":
                    pub = self._job_public(j, now)
                    jobs.append({"id": j["id"], "project": pid, "kind": j["kind"], "piece": j.get("piece"), "progress": pub["progress"],
                                 "message": pub["message"], "since": j["start"], "eta": pub["eta"]})
        return workflow.tasks_payload(entries, jobs, now)

    def project(self, pid):
        return self._view(self._load(pid))

    def _new_pid(self, name) -> str:
        base = slug(name) or "projet"
        pid, n = base, 1
        while (self.home / pid).exists():
            n += 1
            pid = f"{base}-{n}"
        return pid

    def create_project(self, name, src=None, brand=None, site=None):
        name = one_line(name) or "Nouveau projet"
        with self._state:
            base = self._load(src) if src else None
            if base:
                brand_name, url = base["brand_name"], base["site"]
            else:
                brand_name, url = one_line(brand), normalise_site(site)
                if not brand_name:
                    raise ValueError("brand: give the brand's name")
            pid = self._new_pid(name)
            d = self._dir(pid)
            (d / "piece").mkdir(parents=True)
            (d / "logs").mkdir()
            p = {"id": pid, "name": name, "brand_name": brand_name, "site": url, "origin": {"from": src} if base else None, "created": time.time(),
                 "since": {}, "learn": {"learned": False, "mode": None, "answers": ""},
                 "brand": {"kept": False, "kept_ids": [], "discarded_ids": [], "logo": None, "colours": []},
                 "brief": {"confirmed": False, "fields": dict(DEFAULT_BRIEF)},
                 "mandates": {"confirmed": False, "proposed": False, "common": DEFAULT_COMMON,
                              "items": [{"id": f"v{i + 1}", "mandate": m} for i, m in enumerate(DEFAULT_MANDATES)]},
                 "pieces": [], "jobs": []}
            if base:  # a declination keeps the brand and the brief, and only changes what changes
                srcd = self._dir(src)
                if (srcd / "brand").is_dir():
                    shutil.copytree(srcd / "brand", d / "brand")
                for n in ("brand.md", "references.md"):
                    if (srcd / "piece" / n).exists():
                        shutil.copy2(srcd / "piece" / n, d / "piece" / n)
                p["learn"], p["brand"] = json.loads(json.dumps(base["learn"])), json.loads(json.dumps(base["brand"]))
                p["brief"]["fields"] = dict(base["brief"]["fields"])
            self._mark(p, "brand", *(["brief"] if base and base["brand"]["kept"] else []))
            self._save(p)
            return self._view(p)

    # ---------- 1. the brand ----------
    def _fresh_dossier(self, p, log):
        b = self._brand_dir(p["id"])
        if b.exists():
            shutil.rmtree(b)
        self._ensure_dossier(p, log)

    def _ensure_dossier(self, p, log):
        b = self._brand_dir(p["id"])
        if not (b / "state.json").exists():
            b.mkdir(parents=True, exist_ok=True)
            self._brandkit(log, "init", b, "--name", p["brand_name"], "--lang", "fr")

    def learn(self, pid, mode="learn", answers=None):
        if mode not in ("learn", "answer", "create"):
            raise ValueError("mode is learn, answer or create")
        if mode == "answer" and not (answers or "").strip():
            raise ValueError("answer: say what you know of the brand")
        with self._op(pid):
            p = self._load(pid)
            if p["brand"]["kept"]:
                raise Conflict("the brand is already sorted")
            if self._running(p, "learn"):
                raise Conflict("the studio is already reading the brand")
            if mode == "learn":
                if not p["site"]:
                    raise ValueError("this brand has no site: the studio cannot search it. Tell what you know of it, or start from nothing")
                if answers:
                    self._mutate(pid, lambda q: q["learn"].update(answers=str(answers)))
                return self._spawn(pid, "learn", None, lambda jid: self._learn_body(pid, jid))
            log = self._cmd_log(pid)
            self._ensure_dossier(p, log)
            if mode == "answer":
                self._sh(log, self._py(BRANDKIT, "answer", self._brand_dir(pid), "identity.one_liner", one_line(answers)[:600]))  # best effort: the words also stay in project.json

            def done(q):
                q["learn"].update(learned=True, mode=mode, answers=str(answers) if answers else q["learn"]["answers"])
                self._mark(q, "brand")
            self._mutate(pid, done)
        return {"id": None, "status": "done", "progress": 1.0, "message": "sans recherche", "result": None}

    def _learn_body(self, pid, jid):
        p, log = self._load(pid), self._joblog(pid, jid)
        host = re.sub(r"[^a-z0-9.-]+", "-", (urllib.parse.urlsplit(p["site"]).hostname or "site").lower())
        self._fresh_dossier(p, log)
        out = self._brand_dir(pid) / "collect" / f"web-{host}"
        self._phase(pid, jid, "lecture du site et des images")
        self._must(log, ["node", COLLECT, p["site"], out], timeout=420)
        self._phase(pid, jid, "analyse de la marque")
        self._brandkit(log, "infer-site", self._brand_dir(pid), out)
        self._brandkit(log, "review-html", self._brand_dir(pid), "--no-previews")

        def done(q):
            q["learn"].update(learned=True, mode="learn")
            self._mark(q, "brand")
        self._mutate(pid, done)

    def _sortable(self, p):
        """(visuals to sort, logo candidates, ids of the pages that stand for the site) read from the dossier."""
        b = self._brand_dir(p["id"])
        ev = read_json(b / "evidence.json", []) or []
        doc = read_json(b / "brand.json", {}) or {}
        files = set()
        for it in (doc.get("logo") or {}).get("items", []):
            f = (it.get("file") or {}).get("value")
            if f:
                files.add(f)
        visuals, logos, pages = [], [], []
        for x in sorted(ev, key=lambda x: x.get("where", "")):
            if x.get("kind") == "page":
                pages.append(x["id"])
            elif x.get("kind") == "file":
                is_logo = x.get("where") in files or str(x.get("note", "")).startswith(("logo candidate", "icon ("))
                (logos if is_logo else visuals).append(x)
        return visuals, logos, pages

    @staticmethod
    def _say_evidence(x) -> str:
        m = re.search(r"y=(\d+)px", x.get("note", ""))
        if m:
            return "Capture du site, haut de la page" if int(m.group(1)) == 0 else f"Capture du site, plus bas ({m.group(1)} px)"
        return one_line(x.get("note") or x.get("title") or "Visuel")

    def brand(self, pid):
        p = self._load(pid)
        visuals, logos, _ = self._sortable(p)
        kept, dropped = set(p["brand"]["kept_ids"]), set(p["brand"]["discarded_ids"])
        pre = lambda x: f"/files/{urllib.parse.quote(pid)}/brand/{urllib.parse.quote(x['where'])}"
        ev = [{"id": x["id"], "slug": Path(x["where"]).stem, "note": self._say_evidence(x), "kind": "image",
               "proposed": x["kept"] if isinstance(x.get("kept"), bool) else None,
               "kept": True if x["id"] in kept else False if x["id"] in dropped else None, "preview": pre(x)} for x in visuals]
        lg = [{"id": x["id"], "note": ("Icône du site" if str(x.get("note", "")).startswith("icon") else "Logo du site") + f", {Path(x['where']).suffix.lstrip('.')}",
               "preview": pre(x)} for x in logos]
        return {"name": p["brand_name"], "evidence": ev, "logos": lg, "logo": p["brand"]["logo"], "colours": p["brand"]["colours"],
                "kept": p["brand"]["kept"], "answers": p["learn"]["answers"]}

    def keep(self, pid, kept, logo):
        with self._op(pid):
            p = self._load(pid)
            if not p["learn"]["learned"]:
                raise Conflict("the brand is not learned yet")
            visuals, logos, pages = self._sortable(p)
            ids = {x["id"] for x in visuals}
            kept = list(dict.fromkeys(kept or []))
            if set(kept) - ids:
                raise ValueError(f"unknown evidence: {', '.join(sorted(set(kept) - ids))}")
            if logo and logo not in {x["id"] for x in logos}:
                raise ValueError(f"unknown logo: {logo}")
            log, b, piece = self._cmd_log(pid), self._brand_dir(pid), self._piece_dir(pid)
            self._ensure_dossier(p, log)
            args = ["keep", b, *kept, *pages] if kept or pages else ["keep", b, "--none"]
            self._brandkit(log, *args, *(["--logo", logo] if logo else []))
            self._studio(log, "brand", piece, "--from-dossier", b, "--include-unconfirmed", "--force")
            self._complete_brand_md(p, log)
            self._studio(log, "brand", piece)
            colours = self._colours(p)

            def done(q):
                q["brand"].update(kept=True, kept_ids=kept, discarded_ids=sorted(ids - set(kept)), logo=logo, colours=colours)
                self._mark(q, "brand", "brief")
            self._mutate(pid, done)
            return {"kept": len(kept), "discarded": len(ids) - len(kept), "logo": logo, "colours": colours}

    def _dossier_colours(self, p) -> list:
        doc = read_json(self._brand_dir(p["id"]) / "brand.json", {}) or {}
        out = []
        for it in (doc.get("colours") or {}).get("items", []):
            h = hex_of((it.get("hex") or {}).get("value"))
            if h:
                out.append({"hex": h, "role": str((it.get("role") or {}).get("value", "")), "status": (it.get("hex") or {}).get("status")})
        return out

    def _colours(self, p) -> list:
        cols = self._dossier_colours(p)
        measured = [c for c in cols if c["role"].startswith("dominant")]
        picked = measured or cols
        out, seen = [], set()
        for c in picked:
            if c["hex"] not in seen:
                seen.add(c["hex"])
                out.append({"hex": c["hex"], "status": "to confirm" if c["status"] != "confirmed" else "confirmed",
                            "source": "mesurée sur les visuels gardés" if measured else "lue sur le site"})
        return out[:6]

    def _brand_kv(self, p) -> dict:
        f = self._piece_dir(p["id"]) / "brand.md"
        kv = {}
        for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
            m = re.match(r"^[-*]\s+([^:#]+):\s*(.*)$", line.strip())
            if m:
                kv[m.group(1).strip().lower()] = m.group(2).strip()
        return kv

    def _complete_brand_md(self, p, log):
        """brand.md must give a name, a background and a text colour. What the dossier lacks is completed with the colours it
        measured, marked to confirm; with nothing at all, neutral black and white, marked too: the piece then warns."""
        f = self._piece_dir(p["id"]) / "brand.md"
        kv = self._brand_kv(p)
        if not f.exists() or (kv.get("background") and kv.get("text") and kv.get("name")):
            return
        pool = [c["hex"] for c in self._dossier_colours(p)]
        for k in ("background", "text", "accent", "headline colour"):
            if hex_of(kv.get(k)):
                pool.append(hex_of(kv[k]))
        pool += re.findall(r"#[0-9a-fA-F]{6}\b", kv.get("extra colours", ""))
        pool = list(dict.fromkeys(h.lower() for h in pool))
        add = []
        if not kv.get("name"):
            add.append(f"- name: {p['brand_name']}")
        bg = hex_of(kv.get("background")) or (max(pool, key=luminance) if pool else None)
        if not kv.get("background"):
            add.append(f"- background: {bg or '#ffffff'} (à confirmer: {'la plus claire des couleurs mesurées' if bg else 'aucune couleur connue, fond neutre'})")
            bg = bg or "#ffffff"
        if not kv.get("text"):
            rest = [h for h in pool if h != bg]
            tx = max(rest, key=lambda h: contrast(h, bg)) if rest else None
            add.append(f"- text: {tx or '#111111'} (à confirmer: {'la plus contrastée des couleurs mesurées' if tx else 'aucune couleur connue, texte neutre'})")
        with open(f, "a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(add) + "\n")

    # ---------- 2. the brief ----------
    def get_brief(self, pid):
        p = self._load(pid)
        raw = p["brief"]["fields"].get("format", "")
        return {"fields": p["brief"]["fields"], "confirmed": p["brief"]["confirmed"], "formats": list(FORMATS),
                "chosen": workflow.formats_of(raw), "left_out": workflow.left_out_of(raw)}

    def put_brief(self, pid, fields):
        with self._op(pid):
            p = self._load(pid)
            if not p["brand"]["kept"]:
                raise Conflict("the brand is not sorted yet")
            for k in ("objective", "audience", "message"):
                if not (fields.get(k) or "").strip():
                    raise ValueError(f"brief: {k} is required")
            merged = {**p["brief"]["fields"], **{k: str(v) for k, v in fields.items()}}
            chosen = workflow.formats_of(merged.get("format", ""))
            lines = [f"{k}: {one_line(merged.get(k, '')) if k != 'format' else ', '.join(chosen)}" for k in BRIEF_FILE_KEYS if k == "format" or merged.get(k, "").strip()]
            piece = self._piece_dir(pid)
            old = (piece / "brief.md").read_text(encoding="utf-8") if (piece / "brief.md").exists() else None
            (piece / "brief.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            try:
                self._studio(self._cmd_log(pid), "brief", piece)
            except ToolError:
                if old is None:
                    (piece / "brief.md").unlink(missing_ok=True)
                else:
                    (piece / "brief.md").write_text(old, encoding="utf-8")
                raise

            def done(q):
                q["brief"].update(fields=merged, confirmed=True)
                self._mark(q, "brief", "mandates")
            self._mutate(pid, done)
            p = self._load(pid)
            if not p["mandates"]["confirmed"] and not p["mandates"]["proposed"] and not self._running(p, "mandates"):
                self._spawn(pid, "mandates", None, lambda jid: self._mandates_body(pid, jid))
            return {"fields": merged, "formats": chosen, "left_out": workflow.left_out_of(merged.get("format", ""))}

    # ---------- 3. the instructions to the agents ----------
    def get_mandates(self, pid):
        p = self._load(pid)
        if self._running(p, "mandates"):
            raise Conflict("the studio is writing the instructions")
        return {k: p["mandates"][k] for k in ("confirmed", "common", "items")}

    def put_mandates(self, pid, items, common):
        with self._op(pid):
            p = self._load(pid)
            if not p["brief"]["confirmed"]:
                raise Conflict("the brief is not confirmed yet")
            if self._running(p, "mandates"):
                raise Conflict("the studio is writing the instructions")
            if items is not None:
                if not isinstance(items, list) or len(items) < 2 or not all(isinstance(x, dict) and re.fullmatch(r"[\w-]+", str(x.get("id", ""))) and one_line(x.get("mandate")) for x in items):
                    raise ValueError("mandates: at least two items, each with an id and a mandate")
                items = [{"id": str(x["id"]), "mandate": one_line(x["mandate"])} for x in items]

            def done(q):
                m = q["mandates"]
                m.update(items=items or m["items"], common=str(common) if common is not None else m["common"], confirmed=True)
                self._mark(q, "mandates", "diverge")
                return {k: m[k] for k in ("confirmed", "common", "items")}
            return self._mutate(pid, done)

    def _read_text(self, f: Path) -> str:
        return f.read_text(encoding="utf-8") if f.exists() else ""

    def _mandates_prompt(self, p) -> str:
        piece = self._piece_dir(p["id"])
        lang = p["brief"]["fields"].get("language") or "fr"
        words = (p["learn"]["answers"] or "").strip()
        return (
            "You prepare the instructions of four creative agents who will each write one variant of a still ad (a poster or a social post) "
            "for a brand. You only write the instructions, nothing else.\n\n"
            f"=== brand.md ===\n{self._read_text(piece / 'brand.md')}\n=== brief.md ===\n{self._read_text(piece / 'brief.md')}\n"
            f"=== references.md (the visuals the person kept; none if empty) ===\n{self._read_text(piece / 'references.md')}\n"
            + (f"=== what the person says of the brand, in their words ===\n{words}\n" if words else "")
            + (f"=== bans.md (already refused) ===\n{self._read_text(piece / 'bans.md')}\n" if (piece / "bans.md").exists() else "")
            + "\nReturn ONLY one JSON object, no prose, no code fence:\n"
              '{"common": "...", "mandates": ["...", "...", "...", "..."]}\n'
              "- common: one paragraph, plain sentences, the rules every agent follows: the language of the brief; nothing invented (no figure, "
              "place, label, award or promise that is in neither the brand nor the brief); each line reread for any second reading "
              "(sexual, vulgar, ridiculous, hurtful); the image carries no text.\n"
              "- mandates: four stances, each a short phrase (under 12 words) naming a way of looking at this brief; they must look somewhere "
              "else from one another. The fourth is a rupture: it breaks the codes of the category and starts with \"Rupture : \". A mandate gives "
              "a point of view, never a headline, a picture or a layout already drawn.\n"
              "- The brand does not diverge, the idea does: never ask for another palette, typeface or logo.\n"
              f"Write common and mandates in the language of the brief ({lang}).")

    def _mandates_body(self, pid, jid):
        p, log = self._load(pid), self._joblog(pid, jid)
        work = self._piece_dir(pid) / "work" / "mandates"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        self._phase(pid, jid, "un agent propose les consignes")
        res = self._sh(log, self._claude(self._mandates_prompt(p), "--tools", ""), cwd=work, timeout=240, claude=True)
        proposal, why = None, ""
        if res.code:
            why = tail(res)
        else:
            try:
                proposal = self._parse_proposal(res.out)
            except ValueError as err:
                why = str(err)
        shutil.rmtree(work, ignore_errors=True)

        def done(q):
            m = q["mandates"]
            if proposal and not m["confirmed"]:
                m.update(common=proposal["common"], items=[{"id": f"v{i + 1}", "mandate": t} for i, t in enumerate(proposal["mandates"])])
            m["proposed"] = True
            self._mark(q, "mandates")
            for j in q["jobs"]:
                if j["id"] == jid:
                    j["result"] = {"default": proposal is None, "why": why}
        self._mutate(pid, done)
        if proposal is None:
            return f"consignes par défaut (l'agent n'a pas répondu comme prévu : {why})"

    @staticmethod
    def _parse_proposal(text: str) -> dict:
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b < a:
            raise ValueError("pas de JSON dans la réponse")
        try:
            d = json.loads(text[a:b + 1])
        except ValueError as err:
            raise ValueError(f"JSON illisible ({err})")
        ms = d.get("mandates") if isinstance(d, dict) else None
        if not isinstance(d.get("common"), str) or not d["common"].strip() or not isinstance(ms, list) or len(ms) != 4 or not all(isinstance(x, str) and x.strip() for x in ms):
            raise ValueError("il faut une consigne commune et quatre mandats")
        return {"common": one_line(d["common"]), "mandates": [one_line(x) for x in ms]}

    # ---------- 4. the divergence ----------
    def diverge(self, pid):
        with self._op(pid):
            p = self._load(pid)
            if not p["mandates"]["confirmed"]:
                raise Conflict("the instructions to the agents are not read yet")
            if self._running(p, "diverge"):
                raise Conflict("the agents are already writing")
            self._mutate(pid, lambda q: q.update(pieces=[]))
            self._clear_series(pid)
            for f in self._variant_files(pid):
                f.unlink()
            return self._spawn(pid, "diverge", None, lambda jid: self._diverge_body(pid, jid))

    def _clear_series(self, pid):
        piece = self._piece_dir(pid)
        shutil.rmtree(piece / "pieces", ignore_errors=True)
        for n in ("series.json", "pick.json"):
            (piece / n).unlink(missing_ok=True)

    def _agent_prompt(self, vid, mandate, common, lang) -> str:
        return (
            "You are one of several creative agents working blind, each on one mandate, for one still ad (a poster or a social post). "
            "You do not see the others' work.\n\n"
            "Read, in the current folder: brand.md, brief.md, references.md if there is one (open the local images it lists in refs/: they give the "
            "grammar to keep, light included, never a picture to copy) and bans.md if there is one (what the person already refused: do not repeat it).\n\n"
            f"Your mandate: {mandate}\nRules every agent follows: {common}\n\n"
            "Method:\n"
            "1. First write down what you would have made by default for this brief (a headline and the image), then set it aside: your variant must not be it.\n"
            "2. Write your variant from your mandate.\n"
            f"Write ONE file, ./{vid}.json, a UTF-8 JSON object with these keys and no other file:\n"
            '  "mandate": your mandate, as given;\n'
            '  "default": {"headline": "...", "image": "..."}, the default you set aside;\n'
            '  "headline": the headline;\n'
            '  "subline": a short line under it, or "";\n'
            '  "image_prompt": what the image shows, in plain words; the image carries no text and no letters;\n'
            '  "layout": one of side, stack, ground, overlay-top, overlay-bottom, full;\n'
            '  "ground": one of background, text, accent (the colour of the text zone);\n'
            '  "why": one or two sentences: why this answers the mandate;\n'
            '  optionally "fit": "contain" (the whole image shows, the default) or "cover" (it may be cropped).\n\n'
            "Rules:\n"
            "- The brand does not diverge, the idea does: never change the palette, the type or the logo.\n"
            "- Nothing is invented: no figure, testimonial, place, label, award or promise that is in neither brand.md nor brief.md.\n"
            "- Pick a layout that does not cover the subject of the image. side, stack and ground never overlap the image; use overlay-top or "
            "overlay-bottom only when your image prompt leaves that edge calm. When brief.md sets a layout, use exactly that one.\n"
            f"- Before you write the file, reread your headline and your subline in the language of the brief ({lang}) as a reader with a dirty mind or a "
            "mocking one would: any second reading (sexual, vulgar, ridiculous, hurtful), slang included. If you find one, rewrite the line. No word list: use your eye.\n"
            "- Write only that one file, and read and write nothing outside the current folder. When it is written, answer with its name and nothing else.")

    def _prepare_agent(self, piece: Path, wdir: Path):
        """A folder of its own for one agent: the brand, the brief, the bans and the references (their images copied), nothing of the others."""
        shutil.rmtree(wdir, ignore_errors=True)
        (wdir / "refs").mkdir(parents=True)
        brand = [l for l in self._read_text(piece / "brand.md").splitlines() if not re.match(r"^[-*]\s+logo\s*:", l.strip())]
        (wdir / "brand.md").write_text("\n".join(brand) + "\n", encoding="utf-8")
        for n in ("brief.md", "bans.md"):
            if (piece / n).exists():
                shutil.copy2(piece / n, wdir / n)
        refs, k = [], 0
        for line in self._read_text(piece / "references.md").splitlines():
            if not line.startswith("- "):
                continue
            ref, sep, note = line[2:].partition(" | ")
            ref = ref.strip()
            src = piece / ref
            if not ref.startswith(("http://", "https://")) and src.is_file():
                k += 1
                dst = f"refs/{k:02d}-{re.sub(r'[^A-Za-z0-9._-]+', '-', src.name)}"
                shutil.copy2(src, wdir / dst)
                ref = dst
            refs.append(f"- {ref}{sep}{note}")
        if refs:
            (wdir / "references.md").write_text("\n".join(refs) + "\n", encoding="utf-8")

    def _agent(self, pid, jid, item, common, lang, done: list, total: int) -> tuple:
        """One variant agent: (id, ok, why not)."""
        vid, log = item["id"], self._joblog(pid, jid)
        piece = self._piece_dir(pid)
        wdir = piece / "work" / vid
        try:
            self._prepare_agent(piece, wdir)
            res = self._sh(log, self._claude(self._agent_prompt(vid, item["mandate"], common, lang), "--tools=Read,Write", "--permission-mode=acceptEdits",
                                             "--permission-prompts=none"), cwd=wdir, timeout=600, claude=True)
            f = wdir / f"{vid}.json"
            if not f.exists():
                return vid, False, f"{vid}: " + (tail(res) if res.code else "no variant file written")
            ok, why = check_variant(f, vid)
            if not ok:
                return vid, False, why
            (piece / "variants").mkdir(exist_ok=True)
            shutil.copy2(f, piece / "variants" / f"{vid}.json")
            shutil.rmtree(wdir, ignore_errors=True)
            return vid, True, ""
        finally:
            done.append(vid)
            self._phase(pid, jid, f"{len(done)} agent{'s' if len(done) > 1 else ''} sur {total} {'ont' if len(done) > 1 else 'a'} fini")

    def _diverge_body(self, pid, jid):
        p = self._load(pid)
        piece, log = self._piece_dir(pid), self._joblog(pid, jid)
        items, common = p["mandates"]["items"], p["mandates"]["common"]
        lang = p["brief"]["fields"].get("language") or "fr"
        shutil.rmtree(piece / "work", ignore_errors=True)
        self._phase(pid, jid, "les agents écrivent, chacun à l'aveugle")
        results, done = [], []
        total = len(items)

        def run(item):
            r = self._agent(pid, jid, item, common, lang, done, total)
            results.append(r)
        threads = [threading.Thread(target=run, args=(it,), daemon=True) for it in items]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        good = [r for r in results if r[1]]
        if len(good) < 2:
            for f in self._variant_files(pid):
                f.unlink()  # a lone variant is not a divergence: nothing is left half done
            shutil.rmtree(piece / "work", ignore_errors=True)
            raise ToolError(f"seulement {len(good)} variante(s) valide(s) sur {total} : " + " ; ".join(r[2] for r in results if not r[1])[:300])
        self._studio(log, "diverge", piece)
        shutil.rmtree(piece / "work", ignore_errors=True)
        bad = [r[2] for r in results if not r[1]]

        def end(q):
            for j in q["jobs"]:
                if j["id"] == jid:
                    j["result"] = {"variants": sorted(r[0] for r in good), "left_out": bad}
        self._mutate(pid, end)

    def variants(self, pid):
        self._load(pid)
        out = []
        for f in self._variant_files(pid):
            v = read_json(f, {}) or {}
            out.append({"id": f.stem, "mandate": v.get("mandate", ""), "headline": v.get("headline", ""), "subline": v.get("subline", ""),
                        "image_prompt": v.get("image_prompt", ""), "layout": v.get("layout"), "ground": v.get("ground"), "why": v.get("why", "")})
        return out

    # ---------- 5. the series ----------
    def pick(self, pid, ids):
        with self._op(pid):
            p = self._load(pid)
            have = {f.stem for f in self._variant_files(pid)}
            ids = list(dict.fromkeys(ids or []))
            if self._running(p, "diverge"):
                raise Conflict("the agents are still writing")
            if not ids or set(ids) - have:
                raise ValueError("pick at least one known variant")
            formats = workflow.formats_of(p["brief"]["fields"].get("format", ""))
            piece = self._piece_dir(pid)
            self._clear_series(pid)
            # a single variant in a single format would stay in the folder itself: naming it twice makes the studio build a series
            self._studio(self._cmd_log(pid), "pick", piece, *(ids if len(ids) > 1 or len(formats) > 1 else ids * 2))
            entries = []
            for vid in ids:
                for fmt in formats:
                    sub = f"pieces/{vid}-{fmt}" if len(formats) > 1 else f"pieces/{vid}"
                    if not (piece / sub).is_dir():
                        raise ToolError(f"the studio did not make {sub}")
                    entries.append({"id": f"{vid}-{fmt}", "label": f"{vid} en {fmt}", "variant": vid, "format": fmt, "dir": sub, "decision": None, "bans": []})

            def done(q):
                q["pieces"] = entries
                self._mark(q, "diverge", "image")
            self._mutate(pid, done)
            return [self._piece_view(pid, e) for e in entries]

    def _entry(self, p, i) -> dict:
        for e in p["pieces"]:
            if e["id"] == i:
                return e
        raise NotFound(f"no piece {i}")

    def piece(self, pid, i):
        p = self._load(pid)
        return self._piece_view(pid, self._entry(p, i))

    def put_prompt(self, pid, i, prompt):
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            if not (prompt or "").strip():
                raise ValueError("the prompt is empty")
            f = self._piece_dir(pid) / e["dir"] / "variants" / f"{e['variant']}.json"
            v = read_json(f)
            if not isinstance(v, dict):
                raise NotFound(f"no variant for {i}")
            v["image_prompt"] = str(prompt)
            write_json(f, v)
            return self._piece_view(pid, e)

    # ---------- 6. the image ----------
    def image(self, pid, i):
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            if self._running(p, "image", i):
                raise Conflict("the image is already being drawn")
            d = self._piece_dir(pid) / e["dir"]
            for n in ("image.png", "image.jpg", "image.json", "piece.html", "piece.png", "check.json", "decision.md"):
                (d / n).unlink(missing_ok=True)
            self._mutate(pid, lambda q: self._entry(q, i).update(decision=None))
            return self._spawn(pid, "image", i, lambda jid: self._image_body(pid, jid, i))

    def _image_body(self, pid, jid, i):
        e = self._entry(self._load(pid), i)
        d, log = self._piece_dir(pid) / e["dir"], self._joblog(pid, jid)
        self._phase(pid, jid, "le modèle d'image dessine")
        res = self._studio(log, "image", d, "--engine", self.image_engine, "--force")
        if not any((d / n).exists() for n in ("image.png", "image.jpg")):
            line = next((x for x in reversed(res.out.splitlines()) if x.startswith("image:")), "")
            raise ToolError(one_line(line.removeprefix("image:"))[:300] or "no image was drawn")

    # ---------- 7. compose, check, decide ----------
    def compose(self, pid, i):
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            d, log = self._piece_dir(pid) / e["dir"], self._cmd_log(pid)
            if not any((d / n).exists() for n in ("image.png", "image.jpg")):
                raise Conflict("no image yet")
            (d / "piece.png").unlink(missing_ok=True)
            self._studio(log, "compose", d)
            if not (d / "piece.png").exists():
                raise ToolError("the piece could not be rendered to an image: no headless Chrome found (set CHROME=/path/to/chrome)")
            self._studio(log, "check", d)
            self._mutate(pid, lambda q: self._mark(q, "image", "piece", "decide"))
            return self._piece_view(pid, e)

    def decide(self, pid, i, verdict, words):
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            if verdict not in ("keep", "again"):
                raise ValueError("verdict is keep or again")
            view = self._piece_view(pid, e)
            if not view["composed"]:
                raise Conflict("nothing to decide yet")
            if verdict == "again" and not (words or "").strip():
                raise ValueError("say what is wrong: it is remembered for the next round")
            d, log = self._piece_dir(pid) / e["dir"], self._cmd_log(pid)
            self._studio(log, "decide", d, verdict, words or "")
            if verdict == "again":
                self._reopen(d, e["variant"])
                with open(self._piece_dir(pid) / "bans.md", "a", encoding="utf-8") as f:
                    f.write(f'- {time.strftime("%Y-%m-%d")} {e["id"]}: {one_line(words)}\n')

            def done(q):
                x = self._entry(q, i)
                if verdict == "again":
                    x.update(decision=None, bans=x.get("bans", []) + [words])
                else:
                    x["decision"] = {"verdict": "keep", "words": words or "", "at": time.time()}
                self._mark(q, "decide")
            self._mutate(pid, done)
            return self._piece_view(pid, self._entry(self._load(pid), i))

    @staticmethod
    def _reopen(d: Path, vid: str):
        """`studio decide again` clears the pick and archives the variants for a new round. A piece of a series goes back to its
        prompt instead: the variants come back from the round it archived, and the pick with them."""
        rounds = sorted((x for x in (d / "variants").glob("round-*") if x.is_dir()), key=lambda x: int(x.name.split("-")[1]) if x.name.split("-")[1].isdigit() else 0)
        if rounds:
            for f in rounds[-1].glob("*.json"):
                shutil.copy2(f, d / "variants" / f.name)
        write_json(d / "pick.json", {"variant": vid, "at": time.strftime("%Y-%m-%d")})

    # ---------- the files of a project ----------
    def file(self, pid, rel) -> Path:
        """A file of the project's brand/ or piece/ folders, or NotFound. Anything that leaves the project folder is refused."""
        base = self._dir(pid).resolve()
        if not (base / "project.json").is_file() or "\x00" in (rel or ""):
            raise NotFound("no such file")
        f = (base / rel).resolve()
        if not f.is_relative_to(base) or f.relative_to(base).parts[:1] not in (("brand",), ("piece",)) or not f.is_file():
            raise NotFound("no such file")
        return f


def shlex_quote(a) -> str:
    s = str(a)
    s = s if len(s) <= 160 else s[:160] + f"… [{len(s)} chars]"
    return s if re.fullmatch(r"[\w@%+=:,./-]+", s) else "'" + s.replace("'", "'\\''") + "'"

