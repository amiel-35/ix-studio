"""backend_studio: the real studio behind the API. Same methods and same shapes as backend_stub, but every step runs the
tools of this repository (scripts/brandkit, scripts/studio, scripts/collect) and, for the writing, the agents of scripts/agents.

The studio holds brands, a brand holds projects. All of it is in STUDIO_HOME (default ~/ix-studio-projets):

    marques/<b>/marque.json              name, site, description, what the person chose (visuals, logo), the brief of the brand, the jobs
    marques/<b>/brand/                   the brand dossier of scripts/brandkit (collect/ holds what was read on the site)
    marques/<b>/logs/                    one log per job of the brand (every command, its output)
    marques/<b>/projets/<p>/project.json name, brand, type, origin, the brief and the instructions, the pieces, the jobs
    marques/<b>/projets/<p>/piece/       the piece of scripts/studio: brand.md, brief.md, references.md, variants/, pieces/<piece>/
    marques/<b>/projets/<p>/logs/        one log per job of the project
    jugements/<j>/jugement.json          a piece judged on its own: its name, its brand (if any), the brief it answers, the verdict, the jobs
    jugements/<j>/piece.png|jpg          the piece dropped; judge.md and page.html (the flat page of the verdict) once it is judged

A project id is unique in the whole studio (the routes name a project by its id alone). The brand of a project is learned once, at
the brand's level; the project's `brand.md` is written from the brand's dossier when its brief is saved.

A home in the old format (`<id>/project.json` with its own `brand/`, one dossier per project) is opened into this layout when the
backend starts (`_migrate`): see there for the rule.

The state lives on that disk only: a restart finds everything (a job that was running is then marked failed). The long
steps are jobs: a thread that runs sub-processes through an injected `runner(argv, cwd, env, timeout) -> Result`, so the
tests give it a fake one that calls neither `claude`, nor `codex`, nor the network.
"""

import base64
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import NamedTuple

import workflow
from workflow import FORMATS, Conflict, Download, NotFound, contrast, luminance, normalise_site, one_line, slug  # noqa: F401  (re-exported: the tests import them from here)

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
STUDIO = SCRIPTS / "studio"
BRANDKIT = SCRIPTS / "brandkit"
AGENTS = SCRIPTS / "agents"
COLLECT = SCRIPTS / "collect" / "collect.mjs"

DURATION = {"learn": 75.0, "mandates": 45.0, "diverge": 150.0, "image": 150.0, "judge": 120.0, "reader": 90.0, "personas": 60.0, "names": 60.0, "competitors": 60.0}  # expected seconds: the progress is an estimate on these
DURATION["rounds"] = 240.0  # rounds: three judges side by side, then the comparison
CAP = 0.95  # a running job never reads more than this
IMAGE_PARALLEL = 4  # images drawn at the same time: "draw them all" starts every job, the model is asked a few at a time
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
            return re.sub(r"^(studio|agents): ", "", lines[-1])[:n]
    return f"exit {res.code}"


def hex_of(text: str):
    m = re.search(r"#[0-9a-fA-F]{6}\b", text or "")
    return m.group(0).lower() if m else None


def probe_machine(env=None, which=shutil.which, isfile=os.path.isfile, glob_=None, image_engine="auto") -> dict:
    """What this machine has of the tools the studio asks of it: `{chrome, claude, image}`, each True or False. Nothing is run. The ways of finding
    Chrome are those of `studio compose`, and the engines those of `studio image`; `env`, `which`, `isfile` and `glob_` are injectable for the tests."""
    import glob as _glob
    env = os.environ if env is None else env
    glob_ = glob_ or _glob.glob
    if env.get("CHROME"):
        chrome = isfile(env["CHROME"])
    else:
        chrome = bool(glob_("/opt/pw-browsers/chromium*/chrome-linux*/chrome")) or any(which(n) for n in ("google-chrome", "chromium", "chromium-browser")) \
            or isfile("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    engines = {"openai": bool(env.get("OPENAI_API_KEY")), "openrouter": bool(env.get("OPENROUTER_API_KEY")), "codex": bool(which("codex")), "none": False}
    image = any(engines.values()) if image_engine == "auto" else engines.get(image_engine, False)
    return {"chrome": chrome, "claude": bool(which(env.get("STUDIO_CLAUDE_BIN") or "claude")), "image": image}


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


# what the person says of a brand, and where it goes in the dossier of scripts/brandkit: field -> (dossier path, is it a list)
FIELD_MAP = {"what": ("identity.one_liner", False), "who": ("audience.who", False), "voice": ("voice.traits", True),
             "signature": ("promise.signature_line", False), "never": ("voice.banned_words", True)}
# `colours` has no text field in the dossier (its colours are a list of items): what the person says of them is kept in marque.json
PALETTE_LABEL = "colours: chosen by the person"
SOURCES = {"typed": "tapé", "inferred": "déduit du site", "skill": "skill de la marque", "created": "créé"}


def dig(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


class StudioBackend:
    name = "studio"

    def __init__(self, home=None, runner=run_command, image_engine=None, probe=None):
        self.home = Path(home or os.environ.get("STUDIO_HOME") or Path.home() / "ix-studio-projets").expanduser()
        self.home.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.image_engine = image_engine or os.environ.get("STUDIO_IMAGE_ENGINE", "auto")
        self.probe = probe or (lambda: probe_machine(image_engine=self.image_engine))  # what the machine has, asked when the interface asks
        self._state = threading.RLock()  # short: reading and writing project.json and marque.json
        self._locks = {}  # one lock per project (and per brand) for the long operations that rewrite files (keep, pick, compose, decide)
        self._log_lock = threading.Lock()
        self._drawing = threading.BoundedSemaphore(IMAGE_PARALLEL)  # the images drawn at the same time, whatever the number asked for
        self._jobs = {}  # job id -> ("brand", id) or ("project", id)
        self._pidx = {}  # project id -> brand id
        self._migrate()
        self._recover()

    # ---------- the disk ----------
    def _mroot(self) -> Path:
        return self.home / "marques"

    def _mdir(self, bid) -> Path:
        if not re.fullmatch(r"[\w-]+", bid or ""):
            raise NotFound(f"no brand {bid}")
        return self._mroot() / bid

    def _bdir(self, bid) -> Path:
        """The brand dossier of scripts/brandkit."""
        return self._mdir(bid) / "brand"

    def _bid_of(self, pid) -> str:
        if not re.fullmatch(r"[\w-]+", pid or ""):
            raise NotFound(f"no project {pid}")
        with self._state:
            bid = self._pidx.get(pid)
            if bid and (self._mdir(bid) / "projets" / pid / "project.json").is_file():
                return bid
            self._pidx = {p: b for b in self._bids() for p, _ in self._project_rows(b)}
            if pid in self._pidx:
                return self._pidx[pid]
        raise NotFound(f"no project {pid}")

    def _pdir(self, pid) -> Path:
        return self._mdir(self._bid_of(pid)) / "projets" / pid

    def _load(self, pid) -> dict:
        p = read_json(self._pdir(pid) / "project.json")
        if not isinstance(p, dict):
            raise NotFound(f"no project {pid}")
        return p

    def _save(self, p):
        write_json(self._pdir(p["id"]) / "project.json", p)

    def _mutate(self, pid, fn):
        with self._state:
            p = self._load(pid)
            out = fn(p)
            self._save(p)
            return out

    def _loadb(self, bid) -> dict:
        b = read_json(self._mdir(bid) / "marque.json")
        if not isinstance(b, dict):
            raise NotFound(f"no brand {bid}")
        return b

    def _saveb(self, b):
        write_json(self._mdir(b["id"]) / "marque.json", b)

    def _mutateb(self, bid, fn):
        with self._state:
            b = self._loadb(bid)
            out = fn(b)
            self._saveb(b)
            return out

    @contextlib.contextmanager
    def _op(self, key):
        """The lock of a long operation: a project id, or `brand:<id>` for a brand."""
        with self._state:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            yield

    def _bids(self) -> list:
        found = []
        for d in self._mroot().iterdir() if self._mroot().is_dir() else []:
            b = read_json(d / "marque.json") if d.is_dir() else None
            if isinstance(b, dict) and b.get("id") == d.name:
                found.append((b.get("created", 0), d.name))
        return [i for _, i in sorted(found)]

    def _project_rows(self, bid) -> list:
        """[(project id, created)] of a brand, the oldest first."""
        root, found = self._mdir(bid) / "projets", []
        for d in root.iterdir() if root.is_dir() else []:
            p = read_json(d / "project.json") if d.is_dir() else None
            if isinstance(p, dict) and p.get("id") == d.name:
                found.append((p.get("created", 0), d.name))
        return [(i, c) for c, i in sorted(found)]

    def _pids_of(self, bid) -> list:
        return [i for i, _ in self._project_rows(bid)]

    def _ids(self) -> list:
        rows = sorted((c, i) for b in self._bids() for i, c in self._project_rows(b))
        return [i for _, i in rows]

    def _owner(self, owner):
        return ("project", owner) if isinstance(owner, str) else owner

    def _omutate(self, owner, fn):
        kind, oid = self._owner(owner)
        return {"brand": self._mutateb, "judgement": self._mutatej}.get(kind, self._mutate)(oid, fn)

    def _oload(self, owner) -> dict:
        kind, oid = self._owner(owner)
        return {"brand": self._loadb, "judgement": self._loadj}.get(kind, self._load)(oid)

    # a piece judged on its own: a folder of `jugements/`, outside any brand
    def _jroot(self) -> Path:
        return self.home / "jugements"

    def _jdir(self, jid) -> Path:
        if not re.fullmatch(r"[\w-]+", jid or ""):
            raise NotFound(f"no judgement {jid}")
        return self._jroot() / jid

    def _loadj(self, jid) -> dict:
        j = read_json(self._jdir(jid) / "jugement.json")
        if not isinstance(j, dict):
            raise NotFound(f"no judgement {jid}")
        return j

    def _mutatej(self, jid, fn):
        with self._state:
            j = self._loadj(jid)
            out = fn(j)
            write_json(self._jdir(jid) / "jugement.json", j)
            return out

    def _jids(self) -> list:
        found = []
        for d in self._jroot().iterdir() if self._jroot().is_dir() else []:
            j = read_json(d / "jugement.json") if d.is_dir() else None
            if isinstance(j, dict) and j.get("id") == d.name:
                found.append((j.get("created", 0), d.name))
        return [i for _, i in sorted(found, reverse=True)]  # the newest first

    def _recover(self):
        """After a restart: the jobs that were running died with the server. Say so, and index the others."""
        for bid in self._bids():
            def fixb(b):
                for j in b["jobs"]:
                    self._jobs[j["id"]] = ("brand", bid)
                    if j["status"] == "running":
                        j.update(status="failed", end=time.time(), error="interrompu : le serveur a redémarré", message="interrompu : le serveur a redémarré")
                self._retouch(b)
            self._mutateb(bid, fixb)
        for pid in self._ids():
            def fix(p):
                for j in p["jobs"]:
                    self._jobs[j["id"]] = ("project", pid)
                    if j["status"] == "running":
                        j.update(status="failed", end=time.time(), error="interrompu : le serveur a redémarré", message="interrompu : le serveur a redémarré")
                        p["since"][workflow.KIND_STEP[j["kind"]]] = time.time()
            self._mutate(pid, fix)
        for jid in self._jids():
            def fixj(q):
                for j in q["jobs"]:
                    self._jobs[j["id"]] = ("judgement", jid)
                    if j["status"] == "running":
                        j.update(status="failed", end=time.time(), error="interrompu : le serveur a redémarré", message="interrompu : le serveur a redémarré")
            self._mutatej(jid, fixj)

    @staticmethod
    def _mark(p, *keys):
        """Note that the hand changed on these steps now: the interface says who holds it and since when."""
        for k in keys:
            p["since"][k] = time.time()

    def _retouch(self, b):
        """Note when each task of the brand came to the person (the oldest first in the list, `since` for the interface): a task that was not
        there at the last look is dated now. Called inside a `_mutateb`, with the brand as it is about to be saved."""
        kinds = [a["kind"] for a in workflow.brand_asks(self._bstate(b))]
        for k in kinds:
            if k not in b.get("tasked", []):
                b.setdefault("since", {})[k] = time.time()
        b["tasked"] = kinds

    def _piece_dir(self, pid) -> Path:
        return self._pdir(pid) / "piece"

    # ---------- the old format ----------
    def _migrate(self):
        """Open a home in the old format into brands. The old format is `<home>/<p>/` with a `project.json` (a `brand_name`, a `site`, what the
        person chose of the brand) and its own `brand/` dossier. The rule:

        - the brand is the one named by the project's `brand_name`; projects that give the same name (by slug) go to the same brand;
        - the dossier of the project modified most recently (its `project.json` or `brand/brand.json`) becomes the `brand/` of the brand;
          the other projects keep their `brand/` where it is, inside their folder, and nothing is deleted;
        - the brand takes the choices of that project (visuals kept, logo, the words said of the brand) and its discovery jobs;
        - when several projects shared the name, the brand is marked `migrated`: it is `to_confirm` until the person confirms it;
        - each project moves to `marques/<b>/projets/<p>/`, its `brand` becomes the brand's id, its `type` is `campagne`; what the old
          format kept at the project's level (`brand`, `learn`, `brand_name`, `site`) is set aside under `legacy` in its `project.json`.
        """
        old = self.home / "marques"
        if (old / "project.json").is_file() and "brand_name" in (read_json(old / "project.json") or {}):  # a project called "marques" is in the way
            new, n = self.home / "marques-projet", 1
            while new.exists():
                n += 1
                new = self.home / f"marques-projet-{n}"
            old.rename(new)
            p = read_json(new / "project.json")
            p["id"] = new.name
            write_json(new / "project.json", p)
        legacy = []
        for d in sorted(self.home.iterdir()):
            p = read_json(d / "project.json") if d.is_dir() and d.name != "marques" else None
            if isinstance(p, dict) and p.get("id") == d.name and "brand_name" in p:
                legacy.append((d, p))
        groups = {}
        for d, p in legacy:
            groups.setdefault(slug(p.get("brand_name")) or "marque", []).append((d, p))
        for items in groups.values():
            def stamp(item):
                d = item[0]
                files = [d / "project.json"] + ([d / "brand" / "brand.json"] if (d / "brand" / "brand.json").exists() else [])
                return max(f.stat().st_mtime for f in files)
            items.sort(key=stamp, reverse=True)  # the most recently modified first
            lead = next((it for it in items if (it[0] / "brand" / "state.json").exists()), items[0])
            lp = lead[1]
            base, bid, n = slug(lp.get("brand_name")) or "marque", None, 1
            bid = base
            while (self._mroot() / bid).exists():
                n += 1
                bid = f"{base}-{n}"
            mdir = self._mroot() / bid
            (mdir / "projets").mkdir(parents=True)
            learn, brand = lp.get("learn") or {}, lp.get("brand") if isinstance(lp.get("brand"), dict) else {}
            b = {"id": bid, "name": one_line(lp.get("brand_name")) or bid, "site": next((p.get("site") for _, p in items if p.get("site")), ""),
                 "description": "", "created": min(p.get("created", time.time()) for _, p in items),
                 "discovered": bool(learn.get("learned")), "kept": bool(brand.get("kept")), "kept_ids": list(brand.get("kept_ids") or []),
                 "discarded_ids": list(brand.get("discarded_ids") or []), "logo": brand.get("logo"), "brief_done": bool(brand.get("kept")),
                 "answers": learn.get("answers") or "", "colours_words": "", "migrated": len(items) > 1, "since": {}, "tasked": [],
                 "jobs": [j for j in lp.get("jobs", []) if j.get("kind") == "learn"], "from": [d.name for d, _ in items]}
            self._saveb(b)
            if (lead[0] / "brand" / "state.json").exists():
                shutil.move(str(lead[0] / "brand"), str(mdir / "brand"))
            for d, p in items:
                legacy_part = {k: p.pop(k) for k in ("brand", "learn", "brand_name", "site") if k in p}
                p["legacy"] = legacy_part
                p["brand"], p["type"] = bid, "campagne"
                if d == lead[0]:
                    p["jobs"] = [j for j in p.get("jobs", []) if j.get("kind") != "learn"]
                shutil.move(str(d), str(mdir / "projets" / d.name))
                write_json(mdir / "projets" / d.name / "project.json", p)
            self._mutateb(bid, self._retouch)

    # ---------- commands ----------
    def _sh(self, log, argv, cwd=None, timeout=None) -> Result:
        """Run a command through the runner and write what it did in the log."""
        res = self.runner([str(a) for a in argv], cwd=str(cwd) if cwd else None, env=dict(os.environ), timeout=timeout)
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

    def _ask(self, log, cmd, inputs, where: Path, timeout) -> dict:
        """Run one agent of scripts/agents with its inputs written in `where`: its JSON answer, or a ToolError that says why not. The prompts and the
        checks of the answers are those of the command; nothing of them is here."""
        where.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f"inputs-{cmd}-", suffix=".json", dir=where)  # one file per call: the variants run side by side
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(inputs, f, ensure_ascii=False)
        try:
            return json.loads(self._must(log, self._py(AGENTS, cmd, name), timeout=timeout).out)
        finally:
            Path(name).unlink(missing_ok=True)

    def _cmd_log(self, pid) -> Path:
        return self._pdir(pid) / "logs" / "commands.log"

    def _bcmd_log(self, bid) -> Path:
        return self._mdir(bid) / "logs" / "commands.log"

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

    def _spawn(self, owner, kind, piece, body, reader=None):
        """Start a job of a project (`owner` is its id) or of a brand (`owner` is ("brand", id)). A `reader` job says which reader it is."""
        owner = self._owner(owner)
        job = {"id": "job-" + uuid.uuid4().hex[:10], "kind": kind, "piece": piece, "status": "running", "start": time.time(),
               "message": "", "error": None, "result": None, **({"reader": reader} if reader is not None else {})}

        def add(p):
            p["jobs"].append(job)
            if len(p["jobs"]) > 80:
                p["jobs"] = [j for j in p["jobs"] if j["status"] == "running"] + [j for j in p["jobs"] if j["status"] != "running"][-60:]
            if owner[0] == "brand":
                self._retouch(p)
            elif owner[0] == "project":
                self._mark(p, workflow.KIND_STEP[kind])
        self._omutate(owner, add)
        self._jobs[job["id"]] = owner
        threading.Thread(target=self._run_job, args=(owner, job["id"], body), daemon=True, name=job["id"]).start()
        return self._job_public(job)

    def _run_job(self, owner, jid, body):
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
                    if self._owner(owner)[0] == "project":
                        self._mark(p, *steps)
            if self._owner(owner)[0] == "brand":
                self._retouch(p)
        self._omutate(owner, end)

    def _phase(self, owner, jid, message):
        def say(p):
            for j in p["jobs"]:
                if j["id"] == jid:
                    j["message"] = message
        self._omutate(owner, say)

    def _joblog(self, owner, jid) -> Path:
        kind, oid = self._owner(owner)
        return {"brand": self._mdir, "judgement": self._jdir}.get(kind, self._pdir)(oid) / "logs" / f"{jid}.log"

    def _running(self, p, kind, piece=None):
        return next((j for j in p["jobs"] if j["kind"] == kind and j["status"] == "running" and (piece is None or j.get("piece") == piece)), None)

    def job(self, jid):
        owner = self._jobs.get(jid)
        if not owner:
            raise NotFound(f"no job {jid}")
        for j in self._oload(owner)["jobs"]:
            if j["id"] == jid:
                return self._job_public(j)
        raise NotFound(f"no job {jid}")

    # ---------- the brand as plain data ----------
    def _doc(self, bid) -> dict:
        return read_json(self._bdir(bid) / "brand.json", {}) or {}

    def _bfile(self, bid, rel) -> str:
        return f"/files/_marques/{urllib.parse.quote(bid)}/brand/{urllib.parse.quote(rel)}"

    def _sortable(self, b, doc=None):
        """(visuals to sort, logo candidates, ids of the pages that stand for the site) read from the dossier."""
        d = self._bdir(b["id"])
        doc = self._doc(b["id"]) if doc is None else doc
        ev = read_json(d / "evidence.json", []) or []
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

    @staticmethod
    def _dossier_field(v, is_list) -> dict:
        """A value of the dossier as a field of the identity: absent, deduced (to confirm) or confirmed, and where it comes from."""
        if not isinstance(v, dict):
            return workflow.field()
        val = v.get("value")
        text = ", ".join(str(x).strip() for x in val if str(x).strip()) if isinstance(val, list) else str(val or "").strip()
        state = {"confirmed": "confirmed", "to_confirm": "deduced"}.get(v.get("status"), "absent")
        if not text or state == "absent":
            return workflow.field()
        return workflow.field(text, state, SOURCES.get((v.get("source") or {}).get("type"), ""))

    def _dossier_colours(self, doc) -> list:
        out = []
        for it in (doc.get("colours") or {}).get("items", []):
            h = hex_of((it.get("hex") or {}).get("value"))
            if h:
                out.append({"hex": h, "role": str((it.get("role") or {}).get("value", "")), "status": (it.get("hex") or {}).get("status"),
                            "typed": ((it.get("hex") or {}).get("source") or {}).get("type") == "typed"})
        return out

    def _colours_of(self, doc) -> list:
        """The colours of the brand: those measured on the kept visuals if there are any, else those read on the site."""
        cols = self._dossier_colours(doc)
        measured = [c for c in cols if c["role"].startswith("dominant")]
        out, seen = [], set()
        for c in measured or cols:
            if c["hex"] not in seen:
                seen.add(c["hex"])
                out.append({"hex": c["hex"], "role": c["role"], "state": "confirmed" if c["status"] == "confirmed" else "deduced",
                            "source": "choisie par toi" if c["typed"] else "mesurée sur les visuels gardés" if measured else "lue sur le site"})
        return out[:6]

    def _identity(self, b, doc) -> dict:
        out = {k: self._dossier_field(dig(doc, path), is_list) for k, (path, is_list) in FIELD_MAP.items()}
        # `colours`: what the person said of them, or else the colours measured. The state is the state of the colours themselves: said in
        # words, they still have to be confirmed as long as the measured swatches are not.
        words, cols = one_line(b.get("colours_words")), self._colours_of(doc)
        if cols:
            deduced = any(c["state"] == "deduced" for c in cols)
            out["colours"] = workflow.field(words or ", ".join(c["hex"] for c in cols), "deduced" if deduced else "confirmed",
                                            "tapé" if words and not deduced else cols[0]["source"])
        elif words:
            out["colours"] = workflow.field(words, "confirmed", "tapé")
        return workflow.identity_of(out)

    def _logo(self, b, doc):
        """The logo the person chose: {id, where, state, source}, or None."""
        if not b.get("logo"):
            return None
        ev = next((x for x in self._sortable(b, doc)[1] if x["id"] == b["logo"]), None)
        if not ev:
            return None
        items = (doc.get("logo") or {}).get("items", [])
        it = next((i for i in items if (i.get("file") or {}).get("value") == ev["where"]), None)
        f = (it or {}).get("file") or {}
        state = "confirmed" if f.get("status") == "confirmed" else "deduced"
        return {"id": ev["id"], "where": ev["where"], "state": state, "source": "choisi par toi" if state == "confirmed" else "lu sur le site"}

    def _bstate(self, b, doc=None, now=None) -> dict:
        """The brand as plain data for workflow.brand_stage."""
        doc = self._doc(b["id"]) if doc is None else doc
        now = now or time.time()
        ident, logo = self._identity(b, doc), self._logo(b, doc)
        deduced = [k for k in workflow.FIELD_KEYS if ident[k]["state"] == "deduced"] + (["logo"] if logo and logo["state"] == "deduced" else [])
        seen = set(b.get("kept_ids", [])) | set(b.get("discarded_ids", []))
        unsorted = len([x for x in self._sortable(b, doc)[0] if x["id"] not in seen]) if b.get("discovered") else 0
        run = self._running(b, "learn")
        last = next((j for j in reversed(b["jobs"]) if j["kind"] == "learn"), None)
        return {"id": b["id"], "name": b["name"], "site": b.get("site", ""), "discovered": b.get("discovered", False), "kept": b.get("kept", False),
                "logo": logo is not None, "colours_ok": len(self._colours_of(doc)) >= 2, "brief_done": b.get("brief_done", False),
                "migrated": b.get("migrated", False), "deduced": deduced,
                "unsorted": unsorted, "since": b.get("since", {}),
                "running": ({"id": run["id"], "kind": "learn", "piece": None, "start": run["start"], **{k: v for k, v in self._job_public(run, now).items() if k in ("progress", "message")}}
                            if run else None),
                "failed": {"error": last.get("error"), "at": last.get("end")} if last and last["status"] == "failed" else None}

    def _assets(self, b, doc) -> dict:
        visuals, logos, _ = self._sortable(b, doc)
        kept, dropped = set(b.get("kept_ids", [])), set(b.get("discarded_ids", []))
        pre = lambda x: self._bfile(b["id"], x["where"])
        ev = [{"id": x["id"], "kind": "image", "note": self._say_evidence(x), "preview": pre(x),
               "proposed": x["kept"] if isinstance(x.get("kept"), bool) else None,
               "kept": True if x["id"] in kept else False if x["id"] in dropped else None} for x in visuals]
        logo = self._logo(b, doc)
        return {"logo": {"id": logo["id"], "preview": self._bfile(b["id"], logo["where"]), "state": logo["state"], "source": logo["source"]} if logo else None,
                "colours": self._colours_of(doc),
                "visuals": [{"id": e["id"], "note": e["note"], "preview": e["preview"]} for e in ev if e["kept"]],
                "evidence": ev,
                "logos": [{"id": x["id"], "note": ("Logo déposé" if "déposé" in str(x.get("note", "")) else "Icône du site" if str(x.get("note", "")).startswith("icon") else "Logo du site") + f", {Path(x['where']).suffix.lstrip('.')}",
                           "preview": pre(x)} for x in logos]}

    def _brand_payload(self, b, bs=None, now=None) -> dict:
        now = now or time.time()
        doc = self._doc(b["id"])
        bs = bs or self._bstate(b, doc, now)
        projects = [workflow.project_summary(self._view(self._load(pid), bs, now)) for pid in self._pids_of(b["id"])]
        jobs = [{"id": j["id"], "kind": j["kind"], "piece": None, "progress": self._job_public(j, now)["progress"], "message": j.get("message", ""), "since": j["start"]}
                for j in b["jobs"] if j["status"] == "running"]
        return workflow.brand_payload(bs, {"description": b.get("description", "")}, self._identity(b, doc), self._assets(b, doc), projects, jobs, now)

    # ---------- the project and what waits for the person ----------
    def _variant_files(self, pid) -> list:
        return sorted((self._piece_dir(pid) / "variants").glob("*.json"), key=lambda f: (len(f.stem), f.stem))

    def _url(self, pid, rel, f: Path) -> str:
        return f"/files/{urllib.parse.quote(pid)}/{urllib.parse.quote(rel)}?v={int(f.stat().st_mtime)}"

    def _judge_state(self, pid, e, d, composed, jobs):
        """Where the judge of a piece stands: running, done (its verdict, in judge.json), failed (the reason), or None (never judged)."""
        if not composed:
            return None
        mine = [j for j in jobs if j["kind"] == "judge" and j.get("piece") == e["id"]]
        run = next((j for j in mine if j["status"] == "running"), None)
        if run:
            return workflow.judge_view("running", None)
        v = read_json(d / "judge.json")
        if isinstance(v, dict) and v.get("target"):
            return workflow.judge_view("done", v)
        if mine and mine[-1]["status"] == "failed":
            return workflow.judge_view("failed", None, mine[-1].get("error"))
        return None

    def _piece_view(self, pid, e, jobs=None) -> dict:
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
            if not (d / "judge.json").exists():  # the studio's judge is given apart (`judge`); notes written by hand stay with the checks
                notes += [{"status": n.get("level", "note"), "say": n.get("say", "")} for n in chk.get("judge", [])]
            check = {"pass": s.get("pass", 0), "warn": s.get("warn", 0), "fail": s.get("fail", 0), "major": s.get("major", 0), "notes": notes}
        decision = e.get("decision")
        status = "composed" if composed else "image" if img else "again" if e.get("bans") else "picked"
        pk = read_json(d / "pick.json", {}) or {}  # what the person corrected of the words of the variant, for this piece
        return {"id": e["id"], "label": e["label"], "variant": e["variant"], "format": e["format"], "size": list(FORMATS[e["format"]]),
                "headline": pk.get("headline") or v.get("headline", ""), "subline": pk["subline"] if "subline" in pk else v.get("subline", ""),
                "prompt": v.get("image_prompt", ""),
                "image": self._url(pid, f"{rel}/{img}", d / img) if img else None,
                "composed": self._url(pid, f"{rel}/piece.png", png) if composed else None, "check": check, "decision": decision,
                "judge": self._judge_state(pid, e, d, composed, self._load(pid)["jobs"] if jobs is None else jobs),
                "readers": self._readers_state(pid, e, d, composed, jobs),
                "status": status, "bans": list(e.get("bans", []))}

    def _failed(self, p) -> list:
        last = {}
        for j in p["jobs"]:  # in order: the last job of a kind (and a piece) decides
            last[(j["kind"], j.get("piece"))] = j
        return [{"kind": j["kind"], "piece": j.get("piece"), "error": j.get("error"), "at": j.get("end")} for j in last.values() if j["status"] == "failed"]

    def _wf_state(self, p, now, bs=None) -> dict:
        pid = p["id"]
        b = self._loadb(p["brand"])
        bs = bs or self._bstate(b, now=now)
        since = dict(p["since"])
        if b.get("since"):
            since["brand"] = max(b["since"].values())
        return {"id": pid, "name": p["name"], "type": p.get("type", "campagne"), "brand": b["id"], "brand_name": b["name"],
                "brand_stage": workflow.brand_stage(bs), "brand_ready": workflow.brand_ready(bs), "brand_job": bs["running"],
                "brand_waiting": workflow.brand_asks(bs), "can_learn": bool(b.get("site")),
                "brief_confirmed": p["brief"]["confirmed"], "mandates_confirmed": p["mandates"]["confirmed"],
                "variants": len(self._variant_files(pid)), "pieces": [self._piece_view(pid, e, p["jobs"]) for e in p["pieces"]],
                "running": [{"id": j["id"], "kind": j["kind"], "piece": j.get("piece"), "start": j["start"],
                             **{k: v for k, v in self._job_public(j, now).items() if k in ("progress", "message")}}
                            for j in p["jobs"] if j["status"] == "running"],
                "failed": self._failed(p), "since": since}

    def _view(self, p, bs=None, now=None):
        now = now or time.time()
        return workflow.project_view(self._wf_state(p, now, bs), now)

    # ---------- routes ----------
    def health(self):
        which = shutil.which
        return {"ok": True, "backend": self.name, "tools": {"claude": bool(which(os.environ.get("STUDIO_CLAUDE_BIN") or "claude")),
                                                              "codex": bool(which("codex")), "node": bool(which("node")),
                                                              "ffmpeg": bool(which("ffmpeg"))}}

    def machine(self):
        """What the machine lacks to run the studio: Chrome, Claude Code, an image engine. The tools are looked for, never run."""
        return workflow.machine_view(self.probe())

    def list_projects(self):
        out = []
        for pid in self._ids():
            p = self._load(pid)
            v = self._view(p)
            out.append({"id": v["id"], "name": v["name"], "brand": v["brand"], "brand_name": v["brand_name"], "waiting": len(v["waiting"])})
        return out

    def tasks(self):
        entries, jobs, brands, now = [], [], [], time.time()
        for bid in self._bids():
            b = self._loadb(bid)
            bs = self._bstate(b, now=now)
            summaries = []
            for j in b["jobs"]:
                if j["status"] == "running":
                    pub = self._job_public(j, now)
                    jobs.append({"id": j["id"], "project": None, "brand": bid, "kind": j["kind"], "piece": None, "progress": pub["progress"],
                                 "message": pub["message"], "since": j["start"], "eta": pub["eta"], "judgement": None})
            for pid in self._pids_of(bid):
                p = self._load(pid)
                s = self._wf_state(p, now, bs)
                v = workflow.project_view(s, now)
                entries.append((s, v))
                summaries.append(workflow.project_summary(v))
                for j in p["jobs"]:
                    if j["status"] == "running":
                        pub = self._job_public(j, now)
                        jobs.append({"id": j["id"], "project": pid, "brand": bid, "kind": j["kind"], "piece": j.get("piece"), "progress": pub["progress"],
                                     "message": pub["message"], "since": j["start"], "eta": pub["eta"], "judgement": None})
            brands.append((bs, summaries))
        for jid in self._jids():
            for j in self._loadj(jid)["jobs"]:
                if j["status"] == "running":
                    pub = self._job_public(j, now)
                    jobs.append({"id": j["id"], "project": None, "brand": None, "kind": j["kind"], "piece": None, "progress": pub["progress"],
                                 "message": pub["message"], "since": j["start"], "eta": pub["eta"], "judgement": jid})
        return workflow.tasks_payload(entries, jobs, now, brands)

    def project(self, pid):
        return self._view(self._load(pid))

    # ---------- the brands ----------
    def list_brands(self):
        now, out = time.time(), []
        for bid in self._bids():
            b = self._loadb(bid)
            bs = self._bstate(b, now=now)
            out.append(workflow.brand_line(bs, [workflow.project_summary(self._view(self._load(pid), bs, now)) for pid in self._pids_of(bid)]))
        return out

    def brand_view(self, bid):
        return self._brand_payload(self._loadb(bid))

    def create_brand(self, name, site=None):
        name = one_line(name)
        if not name:
            raise ValueError("name: give the brand's name")
        url = normalise_site(site)
        with self._state:
            base, bid, n = slug(name) or "marque", None, 1
            bid = base
            while (self._mroot() / bid).exists():
                n += 1
                bid = f"{base}-{n}"
            b = {"id": bid, "name": name, "site": url, "description": "", "created": time.time(), "discovered": False, "kept": False, "kept_ids": [],
                 "discarded_ids": [], "logo": None, "brief_done": False, "answers": "", "colours_words": "", "migrated": False, "since": {}, "tasked": [],
                 "jobs": []}
            (self._mdir(bid) / "logs").mkdir(parents=True)
            self._retouch(b)
            self._saveb(b)
        if url:
            self._spawn(("brand", bid), "learn", None, lambda jid: self._learn_body(bid, jid))
        return self.brand_view(bid)

    def update_brand(self, bid, name=None, site=None, description=None):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            new_name = b["name"]
            if name is not None:
                new_name = one_line(name)
                if not new_name:
                    raise ValueError("name: give the brand's name")
            url = normalise_site(site) if site is not None else b.get("site", "")
            if new_name != b["name"] and (self._bdir(bid) / "state.json").exists():
                self._sh(self._bcmd_log(bid), self._py(BRANDKIT, "answer", self._bdir(bid), "identity.name", new_name))  # best effort: the dossier carries the name too

            def done(q):
                q.update(name=new_name, site=url)  # a new site reads nothing by itself
                if description is not None:
                    q["description"] = str(description)
                self._retouch(q)
            self._mutateb(bid, done)
        return self.brand_view(bid)

    def discover(self, bid):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            if not b.get("site"):
                raise Conflict("this brand has no site: the studio cannot read it. Give its site first")
            if self._running(b, "learn"):
                raise Conflict("the studio is already reading the brand")
            return self._spawn(("brand", bid), "learn", None, lambda jid: self._learn_body(bid, jid))

    def _ensure_dossier(self, b, log):
        d = self._bdir(b["id"])
        if not (d / "state.json").exists():
            d.mkdir(parents=True, exist_ok=True)
            self._brandkit(log, "init", d, "--name", b["name"], "--lang", "fr")

    def _learn_body(self, bid, jid):
        b, owner = self._loadb(bid), ("brand", bid)
        log = self._joblog(owner, jid)
        host = re.sub(r"[^a-z0-9.-]+", "-", (urllib.parse.urlsplit(b["site"]).hostname or "site").lower())
        self._ensure_dossier(b, log)  # an existing dossier is kept: what the person said stays, the reading adds a source
        out = self._bdir(bid) / "collect" / f"web-{host}"
        self._phase(owner, jid, "lecture du site et des images")
        self._must(log, ["node", COLLECT, b["site"], out], timeout=420)
        self._phase(owner, jid, "analyse de la marque")
        self._brandkit(log, "infer-site", self._bdir(bid), out)
        self._brandkit(log, "review-html", self._bdir(bid), "--no-previews")

        def done(q):
            q["discovered"] = True
            seen = set(q.get("kept_ids", [])) | set(q.get("discarded_ids", []))
            if q.get("kept") and any(x["id"] not in seen for x in self._sortable(q)[0]):
                q["kept"] = False  # something new to sort
        self._mutateb(bid, done)

    def keep_brand(self, bid, kept, logo):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            if not b.get("discovered"):
                raise Conflict("the brand is not read yet")
            visuals, logos, pages = self._sortable(b)
            ids = {x["id"] for x in visuals}
            kept = list(dict.fromkeys(kept or []))
            if set(kept) - ids:
                raise ValueError(f"unknown evidence: {', '.join(sorted(set(kept) - ids))}")
            if logo and logo not in {x["id"] for x in logos}:
                raise ValueError(f"unknown logo: {logo}")
            log, d = self._bcmd_log(bid), self._bdir(bid)
            self._ensure_dossier(b, log)
            args = ["keep", d, *kept, *pages] if kept or pages else ["keep", d, "--none"]
            self._brandkit(log, *args, *(["--logo", logo] if logo else []))

            def done(q):
                q.update(kept=True, kept_ids=kept, discarded_ids=sorted(ids - set(kept)), logo=logo)
                self._retouch(q)
            self._mutateb(bid, done)
            return {**self.brand_view(bid), "kept": len(kept), "discarded": len(ids) - len(kept)}

    def add_logo(self, bid, data, ctype="", name=""):
        """A logo dropped by the person: the file goes into the brand's dossier (`assets/`) as a source the person typed, which makes it a
        logo candidate (a confirmed one), and it is chosen as the logo at once. What was sorted stays as it was."""
        ext = workflow.logo_ext(data, ctype)
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            log, d = self._bcmd_log(bid), self._bdir(bid)
            self._ensure_dossier(b, log)
            rel = f"assets/logo-{hashlib.sha256(data).hexdigest()[:10]}.{ext}"
            (d / "assets").mkdir(parents=True, exist_ok=True)
            (d / rel).write_bytes(data)
            src = {"adapter": "typed", "origin": "logo dropped by the person", "label": "logo " + hashlib.sha256(data).hexdigest()[:8],
                   "evidence": [{"id": "logo", "kind": "file", "where": rel, "note": "logo candidate, déposé" + (f" ({one_line(name)[:60]})" if one_line(name) else "")}],
                   "values": [{"path": "logo", "item": {"file": rel, "format": ext, "variant": "primary"}, "evidence": ["logo"]}]}
            tmp = self._mdir(bid) / "logs" / f"logo-{uuid.uuid4().hex[:8]}.json"
            write_json(tmp, src)
            try:
                self._brandkit(log, "add", d, tmp)
            finally:
                tmp.unlink(missing_ok=True)
            ev = next((x for x in read_json(d / "evidence.json", []) or [] if x.get("where") == rel), None)
            if not ev:
                raise ToolError("the logo could not be added to the dossier")

            def done(q):
                q["logo"] = ev["id"]
                self._retouch(q)
            self._mutateb(bid, done)
        return self.brand_view(bid)

    # ---------- the brief of the brand, and its confirmation ----------
    def _brief_view(self, b):
        doc = self._doc(b["id"])
        bs = self._bstate(b, doc)
        return {"fields": self._identity(b, doc), "done": b.get("brief_done", False), "stage": workflow.brand_stage(bs), "keys": workflow.FIELD_KEYS,
                "needs": workflow.brand_needs(bs), "palette": workflow.palette_of(self._colours_of(doc))}

    def get_brand_brief(self, bid):
        return self._brief_view(self._loadb(bid))

    def put_brand_brief(self, bid, fields):
        if not isinstance(fields, dict):
            raise ValueError("fields: an object")
        unknown = set(fields) - set(workflow.FIELD_KEYS)
        if unknown:
            raise ValueError(f"brief: unknown field {', '.join(sorted(unknown))}")
        palette = workflow.parse_palette(fields["colours"]) if isinstance(fields.get("colours"), list) else None  # the pickers; a string is the person's words
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            now = self._identity(b, self._doc(bid))
            todo = {}
            for k in workflow.FIELD_KEYS:
                if k == "colours" and palette:
                    continue
                text = ", ".join(workflow.split_words(fields.get(k))) if k in ("voice", "never") else one_line(fields.get(k))
                if text:
                    todo[k] = text[:600] if k == "what" else text
            if not (todo.get("what") or now["what"]["value"]):
                raise ValueError("brief: what is required (what the brand is)")
            log = self._bcmd_log(bid)
            self._ensure_dossier(b, log)
            words = None
            for k, text in todo.items():
                cur = now[k]
                same = text == cur["value"]
                if k == "colours":
                    if cur["state"] == "deduced" and same and self._dossier_colours(self._doc(bid)):
                        self._brandkit(log, "confirm", self._bdir(bid), "colours")  # read and kept as it is: confirmed, not typed
                    elif not (cur["state"] == "confirmed" and same):
                        words = text
                    continue
                path, is_list = FIELD_MAP[k]
                if cur["state"] == "deduced" and same:
                    self._brandkit(log, "confirm", self._bdir(bid), path)
                elif not (cur["state"] == "confirmed" and same):
                    if is_list:
                        self._brandkit(log, "answer", self._bdir(bid), path, json.dumps(workflow.split_words(text), ensure_ascii=False), "--json")
                    else:
                        self._brandkit(log, "answer", self._bdir(bid), path, text)

            if palette:
                self._write_palette(bid, palette, log)
                words = ""  # the colours are now the ones chosen, not words about them

            def done(q):
                q["brief_done"] = True
                if words is not None:
                    q["colours_words"] = words
                self._retouch(q)
            self._mutateb(bid, done)
            return self._brief_view(self._loadb(bid))

    def _write_palette(self, bid, palette, log):
        """The colours chosen with the pickers: a source the person typed, in the dossier, replaced at each choice (a typed colour outranks the
        ones read on the site, so these become the brand's colours, confirmed)."""
        d = self._bdir(bid)
        for f in (d / "sources").glob("*.json"):
            if (read_json(f, {}) or {}).get("label") == PALETTE_LABEL:
                f.unlink()
        src = {"adapter": "typed", "origin": "colours chosen by the person", "label": PALETTE_LABEL,
               "values": [{"path": "colours", "item": {"hex": c["hex"], "role": c["role"]}} for c in palette]}
        tmp = self._mdir(bid) / "logs" / f"colours-{uuid.uuid4().hex[:8]}.json"
        write_json(tmp, src)
        try:
            self._brandkit(log, "add", d, tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def confirm(self, bid, keys=None):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            doc = self._doc(bid)
            ident, logo = self._identity(b, doc), self._logo(b, doc)
            if keys is None:
                keys = list(self._bstate(b, doc)["deduced"])
            if not isinstance(keys, list) or set(keys) - set(workflow.CONFIRMABLE):
                raise ValueError(f"keys: any of {', '.join(workflow.CONFIRMABLE)}")
            for k in keys:
                if (k == "logo" and not logo) or (k != "logo" and ident[k]["state"] == "absent"):
                    raise ValueError(f"{k}: there is nothing to confirm, give it instead")
            log, d = self._bcmd_log(bid), self._bdir(bid)
            for k in keys:
                if k == "logo":
                    if logo["state"] == "deduced":
                        self._brandkit(log, "confirm", d, "logo")
                elif k == "colours":
                    if ident[k]["state"] == "deduced":
                        self._brandkit(log, "confirm", d, "colours")
                elif ident[k]["state"] == "deduced":
                    self._brandkit(log, "confirm", d, FIELD_MAP[k][0])

            def done(q):
                if not self._bstate(q)["deduced"]:
                    q["migrated"] = False  # looked at, and nothing is left to confirm
                self._retouch(q)
            self._mutateb(bid, done)
            return self.brand_view(bid)

    # ---------- the personas of the brand ----------
    def _personas_view(self, b):
        run = self._running(b, "personas")
        last = next((j for j in reversed(b["jobs"]) if j["kind"] == "personas"), None)
        return {"personas": list(b.get("personas", [])), "proposed": list(b.get("personas_proposed", [])), "can_propose": b.get("brief_done", False),
                "job": self._job_public(run) if run else None, "error": last.get("error") if last and last["status"] == "failed" else None}

    def get_personas(self, bid):
        return self._personas_view(self._loadb(bid))

    def propose_personas(self, bid):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            if not b.get("brief_done"):
                raise Conflict("the brief of the brand is not done: the personas come from it")
            if self._running(b, "personas"):
                raise Conflict("the personas are already being proposed")
            return self._spawn(("brand", bid), "personas", None, lambda jid: self._personas_body(bid, jid))

    def put_personas(self, bid, personas):
        """The personas the person keeps (corrected, or written by hand): only these are written in the brand. The proposal is settled."""
        texts = workflow.personas_of(personas)
        with self._op("brand:" + bid):
            self._mutateb(bid, lambda q: q.update(personas=texts, personas_proposed=[]))
            return self.get_personas(bid)

    def _brand_inputs(self, b) -> dict:
        """What the brand agents are told of a brand: its name, site and description, the fields of its brief with their state, the person's words, its dossier."""
        ident = self._identity(b, self._doc(b["id"]))
        return {"name": b["name"], "site": b.get("site") or "", "description": b.get("description") or "", "words": b.get("answers") or "",
                "brief": [{"key": k, "value": v["value"], "state": v["state"]} for k, v in ident.items() if v["state"] != "absent"],
                "dossier": str(self._bdir(b["id"]) / "brand.json")}

    def _brand_agent(self, bid, jid, cmd, phase):
        """Run one brand agent (`agents personas|names|competitors`): what it proposes, or a ToolError that says why not."""
        b, owner = self._loadb(bid), ("brand", bid)
        self._phase(owner, jid, phase)
        work = self._mdir(bid) / "work" / cmd
        try:
            return self._ask(self._joblog(owner, jid), cmd, self._brand_inputs(b), work, 330)[cmd]
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _personas_body(self, bid, jid):
        texts = self._brand_agent(bid, jid, "personas", "un agent imagine les personas")
        self._mutateb(bid, lambda q: q.update(personas_proposed=texts))

    # ---------- the names of the brand ----------
    def _names_view(self, b):
        run = self._running(b, "names")
        last = next((j for j in reversed(b["jobs"]) if j["kind"] == "names"), None)
        return {"name": b["name"], "names": list(b.get("names", [])), "proposed": list(b.get("names_proposed", [])), "can_propose": b.get("brief_done", False),
                "job": self._job_public(run) if run else None, "error": last.get("error") if last and last["status"] == "failed" else None}

    def get_names(self, bid):
        return self._names_view(self._loadb(bid))

    def propose_names(self, bid):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            if not b.get("brief_done"):
                raise Conflict("the brief of the brand is not done: the names come from it")
            if self._running(b, "names"):
                raise Conflict("the names are already being proposed")
            return self._spawn(("brand", bid), "names", None, lambda jid: self._names_body(bid, jid))

    def put_names(self, bid, names, chosen=None):
        """The names the person keeps (or wrote), written in the brand; `chosen`, one of them, becomes the brand's name. The proposal is settled."""
        kept = workflow.names_of(names)
        name = workflow.chosen_of(chosen, kept)
        with self._op("brand:" + bid):
            self._mutateb(bid, lambda q: q.update(names=kept, names_proposed=[]))
        if name:
            self.update_brand(bid, name=name)  # its id does not change; the dossier carries the new name too
        return self.get_names(bid)

    def _names_body(self, bid, jid):
        names = self._brand_agent(bid, jid, "names", "un agent cherche des noms")
        self._mutateb(bid, lambda q: q.update(names_proposed=names))

    # ---------- competitors of the brand ----------
    def _competitors_view(self, b):
        run = self._running(b, "competitors")
        last = next((j for j in reversed(b["jobs"]) if j["kind"] == "competitors"), None)
        return {"competitors": list(b.get("competitors", [])), "proposed": list(b.get("competitors_proposed", [])), "can_propose": b.get("brief_done", False),
                "job": self._job_public(run) if run else None, "error": last.get("error") if last and last["status"] == "failed" else None}

    def get_competitors(self, bid):
        return self._competitors_view(self._loadb(bid))

    def propose_competitors(self, bid):
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            if not b.get("brief_done"):
                raise Conflict("the brief of the brand is not done: the competitors come from it")
            if self._running(b, "competitors"):
                raise Conflict("the competitors are already being proposed")
            return self._spawn(("brand", bid), "competitors", None, lambda jid: self._competitors_body(bid, jid))

    def put_competitors(self, bid, competitors):
        """The competitors the person keeps (corrected, or written by hand): only these are written in the brand. The proposal is settled."""
        texts = workflow.competitors_of(competitors)
        with self._op("brand:" + bid):
            self._mutateb(bid, lambda q: q.update(competitors=texts, competitors_proposed=[]))
            return self.get_competitors(bid)

    def _competitors_body(self, bid, jid):
        texts = self._brand_agent(bid, jid, "competitors", "un agent cherche les concurrents")
        self._mutateb(bid, lambda q: q.update(competitors_proposed=texts))

    # ---------- the projects ----------
    def _new_pid(self, name) -> str:
        base = slug(name) or "projet"
        taken = set(self._ids())
        pid, n = base, 1
        while pid in taken:
            n += 1
            pid = f"{base}-{n}"
        return pid

    def create_project_in(self, bid, name, src=None):
        name = one_line(name) or "Nouveau projet"
        with self._state:
            b = self._loadb(bid)
            base = None
            if src:
                base = self._load(src)  # NotFound when unknown
                if base["brand"] != bid:
                    raise ValueError("from: give a project of the same brand")
            pid = self._new_pid(name)
            d = self._mdir(bid) / "projets" / pid
            (d / "piece").mkdir(parents=True)
            (d / "logs").mkdir()
            p = {"id": pid, "name": name, "brand": bid, "type": "campagne", "origin": {"from": src} if base else None, "created": time.time(),
                 "since": {}, "brief": {"confirmed": False, "fields": dict(DEFAULT_BRIEF)},
                 "mandates": {"confirmed": False, "proposed": False, "common": DEFAULT_COMMON,
                              "items": [{"id": f"v{i + 1}", "mandate": m} for i, m in enumerate(DEFAULT_MANDATES)]},
                 "pieces": [], "jobs": []}
            if base:  # a declination copies the fields of the brief, nothing else: the brand is the same, the rest is made again
                p["brief"]["fields"] = dict(base["brief"]["fields"])
            self._pidx[pid] = bid
            self._mark(p, "brand", *(["brief"] if workflow.brand_ready(self._bstate(b)) else []))
            write_json(d / "project.json", p)
            return self._view(p)

    def create_project(self, name, src=None, brand=None, site=None):
        """For the callers that make a project in one go: `from` makes a declination in the same brand; otherwise `brand` (a name) finds the
        brand, or makes it (and reads its site)."""
        if src:
            return self.create_project_in(self._bid_of(src), name, src)
        wanted = one_line(brand)
        if not wanted:
            raise ValueError("brand: give the brand's name")
        url = normalise_site(site)  # refused before anything is made
        found = next((i for i in self._bids() if self._loadb(i)["name"].casefold() == wanted.casefold()), None)
        if found is None:
            found = self.create_brand(wanted, url)["id"]
        return self.create_project_in(found, name)

    def update_project(self, pid, name=None):
        def done(p):
            if name is not None:
                if not one_line(name):
                    raise ValueError("name: give the project's name")
                p["name"] = one_line(name)
        self._mutate(pid, done)
        return self.project(pid)

    # ---------- the brand seen from a project (kept for the callers that still use these routes) ----------
    def learn(self, pid, mode="learn", answers=None):
        if mode not in ("learn", "answer", "create"):
            raise ValueError("mode is learn, answer or create")
        if mode == "answer" and not (answers or "").strip():
            raise ValueError("answer: say what you know of the brand")
        bid = self._bid_of(pid)
        if mode == "learn":
            b = self._loadb(bid)
            if not b.get("site"):
                raise ValueError("this brand has no site: the studio cannot search it. Tell what you know of it, or start from nothing")
            if answers:
                self._mutateb(bid, lambda q: q.update(answers=str(answers)))
            return self.discover(bid)
        with self._op("brand:" + bid):
            b = self._loadb(bid)
            log = self._bcmd_log(bid)
            self._ensure_dossier(b, log)
            if mode == "answer":
                self._sh(log, self._py(BRANDKIT, "answer", self._bdir(bid), "identity.one_liner", one_line(answers)[:600]))  # best effort: the words also stay in marque.json

            def done(q):
                q.update(discovered=True, answers=str(answers) if answers else q.get("answers", ""))
                self._retouch(q)
            self._mutateb(bid, done)
        return {"id": None, "status": "done", "progress": 1.0, "message": "sans recherche", "result": None}

    def brand(self, pid):
        b = self._loadb(self._bid_of(pid))
        doc = self._doc(b["id"])
        a = self._assets(b, doc)
        visuals = self._sortable(b, doc)[0]
        slugs = {x["id"]: Path(x["where"]).stem for x in visuals}
        return {"name": b["name"], "evidence": [{**e, "slug": slugs.get(e["id"], "")} for e in a["evidence"]], "logos": a["logos"], "logo": b.get("logo"),
                "colours": [{"hex": c["hex"], "status": "to confirm" if c["state"] == "deduced" else "confirmed", "source": c["source"]} for c in a["colours"]],
                "kept": b.get("kept", False), "answers": b.get("answers", "")}

    def keep(self, pid, kept, logo):
        r = self.keep_brand(self._bid_of(pid), kept, logo)
        return {"kept": r["kept"], "discarded": r["discarded"], "logo": logo,
                "colours": [{"hex": c["hex"], "status": "to confirm" if c["state"] == "deduced" else "confirmed", "source": c["source"]} for c in r["assets"]["colours"]]}

    # ---------- 1. the brand of the project: written from the brand's dossier ----------
    def _brand_kv(self, pid) -> dict:
        f = self._piece_dir(pid) / "brand.md"
        kv = {}
        for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
            m = re.match(r"^[-*]\s+([^:#]+):\s*(.*)$", line.strip())
            if m:
                kv[m.group(1).strip().lower()] = m.group(2).strip()
        return kv

    def _write_brand_md(self, pid, b, log):
        """brand.md of the piece, from the dossier of the brand. The dossier is ready (a logo, nothing to confirm), so the studio takes it as it is."""
        piece = self._piece_dir(pid)
        self._studio(log, "brand", piece, "--from-dossier", self._bdir(b["id"]), "--include-unconfirmed", "--force")
        self._complete_brand_md(pid, b, log)
        self._studio(log, "brand", piece)

    def _complete_brand_md(self, pid, b, log):
        """brand.md must give a name, a background and a text colour. What the dossier lacks is completed with the colours it measured,
        marked to confirm. With none to choose from there is no neutral stand-in: the brief says what is missing."""
        f = self._piece_dir(pid) / "brand.md"
        kv = self._brand_kv(pid)
        if not f.exists() or (kv.get("background") and kv.get("text") and kv.get("name")):
            return
        pool = [c["hex"] for c in self._dossier_colours(self._doc(b["id"]))]
        for k in ("background", "text", "accent", "headline colour"):
            if hex_of(kv.get(k)):
                pool.append(hex_of(kv[k]))
        pool += re.findall(r"#[0-9a-fA-F]{6}\b", kv.get("extra colours", ""))
        pool = list(dict.fromkeys(h.lower() for h in pool))
        add = []
        if not kv.get("name"):
            add.append(f"- name: {b['name']}")
        bg = hex_of(kv.get("background")) or (max(pool, key=luminance) if pool else None)
        if not kv.get("background"):
            if not bg:
                raise ToolError("la marque n'a aucune couleur connue pour le fond : donne ses couleurs (en hexadécimal) dans le brief de la marque")
            add.append(f"- background: {bg} (à confirmer: la plus claire des couleurs mesurées)")
        if not kv.get("text"):
            rest = [h for h in pool if h != bg]
            if not rest:
                raise ToolError("la marque n'a qu'une couleur connue : il en faut une autre pour le texte, donne-la dans le brief de la marque")
            tx = max(rest, key=lambda h: contrast(h, bg))
            add.append(f"- text: {tx} (à confirmer: la plus contrastée des couleurs mesurées)")
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
            b = self._loadb(p["brand"])
            if not workflow.brand_ready(self._bstate(b)):
                raise Conflict("the brand is not ready: sort it, brief it and confirm it first")
            for k in ("objective", "audience", "message"):
                if not (fields.get(k) or "").strip():
                    raise ValueError(f"brief: {k} is required")
            merged = {**p["brief"]["fields"], **{k: workflow.brief_personas_of(v) if k == "personas" else str(v) for k, v in fields.items()}}
            chosen = workflow.formats_of(merged.get("format", ""))
            lines = [f"{k}: {one_line(merged.get(k, '')) if k != 'format' else ', '.join(chosen)}" for k in BRIEF_FILE_KEYS if k == "format" or merged.get(k, "").strip()]
            piece = self._piece_dir(pid)
            self._write_brand_md(pid, b, self._cmd_log(pid))  # the brand as it is now: the piece starts from the brand, not from a copy of an old day
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

    def _mandates_body(self, pid, jid):
        p, log = self._load(pid), self._joblog(pid, jid)
        self._phase(pid, jid, "un agent propose les consignes")
        inputs = {"dir": str(self._piece_dir(pid)), "language": p["brief"]["fields"].get("language") or "fr", "words": self._loadb(p["brand"]).get("answers") or ""}
        proposal, why = None, ""
        try:
            proposal = self._ask(log, "mandates", inputs, self._piece_dir(pid) / "work" / "mandates", 270)
        except ToolError as err:
            why = str(err)
        shutil.rmtree(self._piece_dir(pid) / "work" / "mandates", ignore_errors=True)

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

    def _agent(self, pid, jid, item, common, lang, done: list, total: int) -> tuple:
        """One variant agent (`agents variant`, which writes <piece>/variants/<id>.json): (id, ok, why not)."""
        vid, log = item["id"], self._joblog(pid, jid)
        piece = self._piece_dir(pid)
        wdir = piece / "work" / vid
        try:
            self._ask(log, "variant", {"dir": str(piece), "id": vid, "mandate": item["mandate"], "common": common, "language": lang, "work": str(wdir)}, wdir.parent, 630)
            return vid, True, ""
        except ToolError as err:
            return vid, False, str(err)
        finally:
            shutil.rmtree(wdir, ignore_errors=True)
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

    def _has_image(self, pid, e) -> bool:
        return any((self._piece_dir(pid) / e["dir"] / n).exists() for n in ("image.png", "image.jpg"))

    def put_variant_prompt(self, pid, vid, prompt):
        """The prompt of a variant, shared by its formats: written in the variant file of each of its pieces that still waits for its image."""
        with self._op(pid):
            p = self._load(pid)
            if not (prompt or "").strip():
                raise ValueError("the prompt is empty")
            mine = [e for e in p["pieces"] if e["variant"] == vid]
            if not mine:
                raise NotFound(f"no variant {vid} in the series")
            todo = [e for e in mine if not self._has_image(pid, e) and not self._running(p, "image", e["id"])]
            if not todo:
                raise Conflict("every piece of this variant has its image: redo one of them to change its prompt")
            for e in todo:
                f = self._piece_dir(pid) / e["dir"] / "variants" / f"{vid}.json"
                v = read_json(f)
                if not isinstance(v, dict):
                    raise NotFound(f"no variant for {e['id']}")
                v["image_prompt"] = str(prompt)
                write_json(f, v)
            return [self._piece_view(pid, e) for e in todo]

    def put_variant_text(self, pid, vid, headline, subline=None):
        """The words of a variant corrected, for its formats: the headline (required) and the subline (`""` removes it; None leaves it as it is),
        written in each of its pieces that is not composed yet by `studio pick --headline --subline`."""
        with self._op(pid):
            p = self._load(pid)
            headline = one_line(headline)[:200]
            if not headline:
                raise ValueError("headline: give the headline")
            mine = [e for e in p["pieces"] if e["variant"] == vid]
            if not mine:
                raise NotFound(f"no variant {vid} in the series")
            todo = [e for e in mine if not self._piece_view(pid, e)["composed"]]
            if not todo:
                raise Conflict("every piece of this variant is composed: send one back (redo its image) to change its words")
            for e in todo:
                sub = one_line(subline)[:300] if subline is not None else self._piece_view(pid, e)["subline"]
                self._studio(self._cmd_log(pid), "pick", self._piece_dir(pid) / e["dir"], vid, "--headline", headline, "--subline", sub)
            return [self._piece_view(pid, e) for e in todo]

    # ---------- 6. the image ----------
    def image(self, pid, i):
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            if self._running(p, "image", i):
                raise Conflict("the image is already being drawn")
            d = self._piece_dir(pid) / e["dir"]
            for n in ("image.png", "image.jpg", "image.json", "piece.html", "piece.png", "check.json", "decision.md", "judge.json", "judge.md"):
                (d / n).unlink(missing_ok=True)
            for f in d.glob("reader-*.json"):
                f.unlink()
            self._mutate(pid, lambda q: self._entry(q, i).update(decision=None))
            return self._spawn(pid, "image", i, lambda jid: self._image_body(pid, jid, i))

    def draw_images(self, pid, variant=None):
        """Draw every image that is missing (those of one variant when `variant` is given): one job per piece."""
        p = self._load(pid)
        if variant and not any(e["variant"] == variant for e in p["pieces"]):
            raise ValueError(f"variant: no {variant} in the series")
        todo = [e["id"] for e in p["pieces"] if (not variant or e["variant"] == variant) and not self._has_image(pid, e) and not self._running(p, "image", e["id"])]
        if not todo:
            raise Conflict("every piece has its image, or is being drawn")
        return {"jobs": [self.image(pid, i) for i in todo]}

    def _image_body(self, pid, jid, i):
        e = self._entry(self._load(pid), i)
        d, log = self._piece_dir(pid) / e["dir"], self._joblog(pid, jid)
        self._phase(pid, jid, "en attente d'une place")
        with self._drawing:  # a few images at a time: a whole series is drawn on request, not all at once
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
            for n in ("piece.png", "judge.json", "judge.md"):  # a new piece is judged anew
                (d / n).unlink(missing_ok=True)
            for f in d.glob("reader-*.json"):  # and read anew
                f.unlink()
            self._studio(log, "compose", d)
            if not (d / "piece.png").exists():
                raise ToolError("the piece could not be rendered to an image: no headless Chrome found (set CHROME=/path/to/chrome)")
            self._studio(log, "check", d)
            self._mutate(pid, lambda q: self._mark(q, "image", "piece", "decide"))
            self._spawn(pid, "judge", i, lambda jid: self._judge_body(pid, jid, i))  # it blocks nothing; a judge still reading the old piece keeps no verdict
            for n in range(len(workflow.brief_personas_of(p["brief"]["fields"].get("personas")))):  # one reader per persona of the brief, beside the judge
                self._spawn(pid, "reader", i, lambda jid, n=n: self._reader_body(pid, jid, i, n), reader=n)
            return self._piece_view(pid, e)

    def compose_all(self, pid):
        """Compose and check every piece that has its image and is not composed yet, one after the other. A piece that cannot be composed is
        told apart (`failed`) and the others go on; when none could, the reason of the first is the answer (400)."""
        p = self._load(pid)
        todo = [e["id"] for e in p["pieces"] if self._has_image(pid, e) and not self._piece_view(pid, e)["composed"]]
        if not todo:
            raise Conflict("no piece waits to be composed")
        done, failed = [], []
        for i in todo:
            try:
                self.compose(pid, i)
                done.append(i)
            except (ValueError, Conflict) as err:  # a ToolError is a ValueError
                failed.append({"piece": i, "error": str(err)})
        if not done:
            raise ToolError(failed[0]["error"])
        return {"composed": done, "failed": failed}

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
            pick = read_json(d / "pick.json", {}) or {}
            self._studio(log, "decide", d, verdict, words or "")
            if verdict == "again":
                self._reopen(d, e["variant"], {k: pick[k] for k in ("headline", "subline") if k in pick})  # the words the person corrected stay
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
    def _reopen(d: Path, vid: str, words=None):
        """`studio decide again` clears the pick and archives the variants for a new round. A piece of a series goes back to its
        prompt instead: the variants come back from the round it archived, and the pick with them."""
        rounds = sorted((x for x in (d / "variants").glob("round-*") if x.is_dir()), key=lambda x: int(x.name.split("-")[1]) if x.name.split("-")[1].isdigit() else 0)
        if rounds:
            for f in rounds[-1].glob("*.json"):
                shutil.copy2(f, d / "variants" / f.name)
        write_json(d / "pick.json", {"variant": vid, "at": time.strftime("%Y-%m-%d"), **(words or {})})

    # ---------- 8. the judge ----------
    def _brand_words(self, bid) -> dict:
        """What the judge is told of a brand (its voice and its tone): the fields of its identity that are known, or {} when it has none."""
        if not bid:
            return {}
        try:
            b = self._loadb(bid)
        except NotFound:
            return {}
        ident = self._identity(b, self._doc(bid))
        return {"name": b["name"], **{k: ident[k]["value"] for k in ("what", "who", "voice", "signature", "never") if ident[k]["state"] != "absent"}}

    def _run_judge(self, log, wdir: Path, image: Path, brief: dict, brand: dict, texts=None, lang="fr") -> dict:
        """One judge (`agents judge`): the picture and the brief in, the verdict out, checked. A ToolError says why it failed."""
        try:
            return self._ask(log, "judge", {"image": str(image), "brief": brief, "brand": brand, "texts": texts, "language": lang}, wdir, 430)
        finally:
            shutil.rmtree(wdir, ignore_errors=True)

    def _judge_body(self, pid, jid, i):
        p = self._load(pid)
        e = self._entry(p, i)
        d, log = self._piece_dir(pid) / e["dir"], self._joblog(pid, jid)
        png = d / "piece.png"
        if not png.exists():
            raise ToolError("la pièce n'est plus composée")
        stamp = png.stat().st_mtime_ns
        view = self._piece_view(pid, e, p["jobs"])
        self._phase(pid, jid, "le juge relit la pièce")
        v = self._run_judge(log, self._pdir(pid) / "work" / f"judge-{i}", png, workflow.judge_brief(p["brief"]["fields"]), self._brand_words(p["brand"]),
                            {"headline": view["headline"], "subline": view["subline"]}, p["brief"]["fields"].get("language") or "fr")
        with self._op(pid):
            if not png.exists() or png.stat().st_mtime_ns != stamp:
                return "la pièce a changé pendant que le juge la relisait : son verdict est laissé de côté"
            write_json(d / "judge.json", v)
            (d / "judge.md").write_text(workflow.judge_md(v), encoding="utf-8")
            self._studio(log, "check", d)  # the judge's notes go into check.json, beside the mechanical checks

    def judge_piece(self, pid, i):
        """Run the judge of a composed piece again (after a failure)."""
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            if not self._piece_view(pid, e, p["jobs"])["composed"]:
                raise Conflict("this piece is not composed yet")
            if self._running(p, "judge", i):
                raise Conflict("the judge is already reading this piece")
            return self._spawn(pid, "judge", i, lambda jid: self._judge_body(pid, jid, i))

    # ---------- a piece judged on its own ----------
    def _jg_view(self, j) -> dict:
        d = self._jdir(j["id"])
        img = d / f"piece.{j['ext']}"
        run = self._running(j, "judge")
        last = next((x for x in reversed(j["jobs"]) if x["kind"] == "judge"), None)
        status = "running" if run else "done" if j.get("verdict") else "failed" if last and last["status"] == "failed" else "running"
        brand_name = j.get("brand_name", "")
        return {"id": j["id"], "name": j["name"], "brand": j.get("brand"), "brand_name": brand_name, "brief": dict(j["brief"]),
                "image": f"/files/_jugements/{urllib.parse.quote(j['id'])}/{img.name}?v={int(img.stat().st_mtime)}" if img.exists() else None,
                "at": j["created"], "status": status, "verdict": j.get("verdict") if status == "done" else None,
                "error": last.get("error") if status == "failed" else None, "missing": workflow.judge_missing(j["brief"]), "job": run["id"] if run else None,
                "readers": [workflow.reader_view(n, persona, self._last_reader(j["jobs"], None, n), (j.get("readings") or {}).get(str(n)))
                            for n, persona in enumerate(j["brief"].get("personas") or [])]}

    def list_judgements(self):
        return [{k: v[k] for k in ("id", "name", "brand", "brand_name", "status", "at")} for v in (self._jg_view(self._loadj(jid)) for jid in self._jids())]

    def judgement(self, jid):
        return self._jg_view(self._loadj(jid))

    def create_judgement(self, data, ctype="", name="", meta=None):
        """A piece dropped to be judged on its own: its folder in `jugements/`, the picture, the brief it answers, its brand if any; the judge starts."""
        ext = workflow.judge_image_ext(data, ctype)
        m = workflow.judge_meta(meta)
        brand_name = ""
        if m["brand"]:
            try:
                brand_name = self._loadb(m["brand"])["name"]
            except NotFound:
                raise ValueError(f"brand: no brand {m['brand']}") from None
        with self._state:
            jid = "j-" + time.strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
            d = self._jdir(jid)
            (d / "logs").mkdir(parents=True)
            (d / f"piece.{ext}").write_bytes(data)
            label = m["name"] or one_line(Path(name or "").stem) or "Pièce à juger"
            write_json(d / "jugement.json", {"id": jid, "name": label[:120], "brand": m["brand"], "brand_name": brand_name, "brief": m["brief"],
                                             "ext": ext, "created": time.time(), "verdict": None, "jobs": []})
        self._spawn(("judgement", jid), "judge", None, lambda job: self._judgement_body(jid, job))
        for n in range(len(m["brief"]["personas"])):  # one reader per persona of the brief, beside the judge
            self._spawn(("judgement", jid), "reader", None, lambda job, n=n: self._jreader_body(jid, job, n), reader=n)
        return self.judgement(jid)

    def _judgement_body(self, jid, job):
        owner, j = ("judgement", jid), self._loadj(jid)
        d = self._jdir(jid)
        self._phase(owner, job, "le juge relit la pièce")
        v = self._run_judge(self._joblog(owner, job), d / "work", d / f"piece.{j['ext']}", j["brief"], self._brand_words(j.get("brand")))
        (d / "judge.md").write_text(workflow.judge_md(v), encoding="utf-8")
        img = d / f"piece.{j['ext']}"
        mime = "image/png" if j["ext"] == "png" else "image/jpeg"
        uri = f"data:{mime};base64," + base64.b64encode(img.read_bytes()).decode()
        (d / "page.html").write_text(workflow.judge_page(v, uri, j["name"], j.get("brand_name", ""), time.strftime("%Y-%m-%d", time.localtime(j["created"]))),
                                     encoding="utf-8")
        self._mutatej(jid, lambda q: q.update(verdict=v))

    def run_judgement(self, jid):
        """Run the judge of a judgement again (after a failure, or to read it once more)."""
        with self._op("judgement:" + jid):
            j = self._loadj(jid)
            if self._running(j, "judge"):
                raise Conflict("the judge is already reading this piece")
            self._mutatej(jid, lambda q: q.update(verdict=None))
            return self._spawn(("judgement", jid), "judge", None, lambda job: self._judgement_body(jid, job))

    def judgement_page(self, jid):
        """The flat page of a judgement (the piece at the top, the list under it), as the file written beside it."""
        v = self.judgement(jid)
        f = self._jdir(jid) / "page.html"
        if v["status"] != "done" or not f.is_file():
            raise Conflict("the judge has not given its verdict yet")
        return Download(f"{jid}.html", "text/html; charset=utf-8", f.read_bytes())

    # ---------- rounds: a piece judged three times, the remarks in three shelves (`agents rounds`) ----------
    def judgement_rounds(self, jid):
        j = self._loadj(jid)
        last = next((x for x in reversed(j["jobs"]) if x["kind"] == "rounds"), None)
        run = self._running(j, "rounds")
        if run:
            return workflow.rounds_view("running", job=run["id"])
        if j.get("rounds"):
            return workflow.rounds_view("done", j["rounds"]["synthesis"])
        return workflow.rounds_view("failed", error=last.get("error")) if last and last["status"] == "failed" else workflow.rounds_view("none")

    def run_judgement_rounds(self, jid):
        """Judge the piece three times, then put the remarks side by side; again after a failure, or to read it anew."""
        with self._op("judgement:" + jid):
            if self._running(self._loadj(jid), "rounds"):
                raise Conflict("the rounds are already running on this piece")
            self._mutatej(jid, lambda q: q.update(rounds=None))
            return self._spawn(("judgement", jid), "rounds", None, lambda job: self._rounds_body(jid, job))

    def _rounds_body(self, jid, job):
        owner, j = ("judgement", jid), self._loadj(jid)
        d = self._jdir(jid)
        self._phase(owner, job, "le juge relit la pièce, trois fois")
        wdir = d / "work-rounds"
        try:
            r = self._ask(self._joblog(owner, job), "rounds", {"image": str(d / f"piece.{j['ext']}"), "brief": j["brief"], "brand": self._brand_words(j.get("brand"))},
                          wdir, 1000)
        finally:
            shutil.rmtree(wdir, ignore_errors=True)
        self._mutatej(jid, lambda q: q.update(rounds=r))

    # ---------- 9. the readers: one per persona of the brief, each in a call of its own ----------
    @staticmethod
    def _last_reader(jobs, piece, n):
        return next((j for j in reversed(jobs) if j["kind"] == "reader" and j.get("piece") == piece and j.get("reader") == n), None)

    def _readers_state(self, pid, e, d, composed, jobs=None):
        """The readers of a composed piece, one per persona of the project's brief ([] without persona, or while the piece is not composed)."""
        if not composed:
            return []
        p = self._load(pid)
        jobs = p["jobs"] if jobs is None else jobs
        return [workflow.reader_view(n, persona, self._last_reader(jobs, e["id"], n), read_json(d / f"reader-{n}.json"))
                for n, persona in enumerate(workflow.brief_personas_of(p["brief"]["fields"].get("personas")))]

    def _run_reader(self, log, wdir: Path, image: Path, persona: str, texts=None, lang="fr") -> dict:
        """One reader (`agents reader`): the picture and its persona in, the reading out, checked. A ToolError says why it failed."""
        try:
            return self._ask(log, "reader", {"image": str(image), "persona": persona, "texts": texts, "language": lang}, wdir, 430)
        finally:
            shutil.rmtree(wdir, ignore_errors=True)

    def _reader_body(self, pid, jid, i, n):
        p = self._load(pid)
        e = self._entry(p, i)
        d, log = self._piece_dir(pid) / e["dir"], self._joblog(pid, jid)
        png = d / "piece.png"
        personas = workflow.brief_personas_of(p["brief"]["fields"].get("personas"))
        if not png.exists():
            raise ToolError("la pièce n'est plus composée")
        if n >= len(personas):
            raise ToolError("ce persona n'est plus dans le brief")
        stamp = png.stat().st_mtime_ns
        view = self._piece_view(pid, e, p["jobs"])
        self._phase(pid, jid, "un lecteur lit la pièce")
        r = self._run_reader(log, self._pdir(pid) / "work" / f"reader-{i}-{n}", png, personas[n], {"headline": view["headline"], "subline": view["subline"]},
                             p["brief"]["fields"].get("language") or "fr")
        with self._op(pid):
            if not png.exists() or png.stat().st_mtime_ns != stamp:
                return "la pièce a changé pendant que le lecteur la lisait : sa lecture est laissée de côté"
            write_json(d / f"reader-{n}.json", {"persona": personas[n], "reading": r})

    def run_reader(self, pid, i, n):
        """Run reader `n` of a composed piece again, alone."""
        with self._op(pid):
            p = self._load(pid)
            e = self._entry(p, i)
            view = self._piece_view(pid, e, p["jobs"])
            if not view["composed"]:
                raise Conflict("this piece is not composed yet")
            if not 0 <= n < len(view["readers"]):
                raise NotFound(f"no reader {n}")
            if view["readers"][n]["status"] == "running":
                raise Conflict("this reader is already reading the piece")
            return self._spawn(pid, "reader", i, lambda jid: self._reader_body(pid, jid, i, n), reader=n)

    def _jreader_body(self, jid, job, n):
        owner, j = ("judgement", jid), self._loadj(jid)
        d = self._jdir(jid)
        persona = j["brief"]["personas"][n]
        self._phase(owner, job, "un lecteur lit la pièce")
        r = self._run_reader(self._joblog(owner, job), d / f"lecteur-{n}", d / f"piece.{j['ext']}", persona)
        self._mutatej(jid, lambda q: q.setdefault("readings", {}).update({str(n): {"persona": persona, "reading": r}}))

    def run_judgement_reader(self, jid, n):
        """Run reader `n` of a judgement again, alone."""
        with self._op("judgement:" + jid):
            v = self.judgement(jid)
            if not 0 <= n < len(v["readers"]):
                raise NotFound(f"no reader {n}")
            if v["readers"][n]["status"] == "running":
                raise Conflict("this reader is already reading the piece")
            return self._spawn(("judgement", jid), "reader", None, lambda job: self._jreader_body(jid, job, n), reader=n)

    # ---------- taking the pieces out of the studio ----------
    def download_piece(self, pid, i):
        """The composed piece as a png file, at the size of its format (the file `studio compose` made)."""
        e = self._entry(self._load(pid), i)
        f = self._piece_dir(pid) / e["dir"] / "piece.png"
        if not self._piece_view(pid, e)["composed"]:
            raise Conflict("this piece is not composed yet")
        return Download(f"{pid}-{i}.png", "image/png", f.read_bytes())

    def download_project(self, pid):
        """Every piece kept, in a zip (the standard library's)."""
        p = self._load(pid)
        files = []
        for e in p["pieces"]:
            f = self._piece_dir(pid) / e["dir"] / "piece.png"
            if (e.get("decision") or {}).get("verdict") == "keep" and f.is_file():
                files.append((f"{pid}-{e['id']}.png", f.read_bytes()))
        if not files:
            raise Conflict("no piece is kept yet")
        return Download(f"{pid}.zip", "application/zip", workflow.zip_of(files))

    # ---------- the files of a project, and of a brand ----------
    def file(self, pid, rel) -> Path:
        """A file served to the interface, or NotFound. Anything that leaves its folder is refused.

        `/files/<project>/piece/...`   the piece folder of the project;
        `/files/<project>/brand/...`   the brand dossier of the project's brand (kept: the pictures the brand routes of a project point to);
        `/files/_marques/<brand>/brand/...`   the brand dossier of a brand;
        `/files/_jugements/<j>/piece.png`   a piece judged on its own (its picture, or its page.html)."""
        if not rel or "\x00" in rel:
            raise NotFound("no such file")
        if pid == "_jugements":  # a piece judged on its own: its picture and its page, nothing else of its folder
            jid, _, name = rel.partition("/")
            f = self._jdir(jid) / name
            if name not in ("piece.png", "piece.jpg", "page.html") or not (self._jdir(jid) / "jugement.json").is_file() or not f.is_file() or f.is_symlink():
                raise NotFound("no such file")
            return f
        if pid == "_marques":
            bid, _, rest = rel.partition("/")
            if not (self._mdir(bid) / "marque.json").is_file():
                raise NotFound("no such file")
            first, _, inner = rest.partition("/")
            root = (self._mdir(bid) / "brand").resolve() if first == "brand" else None
        else:
            bid = self._bid_of(pid)
            first, _, inner = rel.partition("/")
            root = {"piece": (self._pdir(pid) / "piece"), "brand": self._mdir(bid) / "brand"}.get(first)
            root = root.resolve() if root else None
        if root is None:
            raise NotFound("no such file")
        f = (root / inner).resolve()
        if not f.is_relative_to(root) or not f.is_file():
            raise NotFound("no such file")
        return f


def shlex_quote(a) -> str:
    s = str(a)
    s = s if len(s) <= 160 else s[:160] + f"… [{len(s)} chars]"
    return s if re.fullmatch(r"[\w@%+=:,./-]+", s) else "'" + s.replace("'", "'\\''") + "'"
