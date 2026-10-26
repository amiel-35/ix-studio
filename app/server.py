"""server: the studio's interface and its API, on one local port.

    python3 app/server.py [--port 8765] [--host 127.0.0.1]

Serves app/static/ and answers /api/* (see API.md) with a backend: STUDIO_BACKEND=studio (default) drives scripts/studio
and scripts/brandkit and keeps its projects in STUDIO_HOME; STUDIO_BACKEND=stub is the simulated one (backend_stub).
GET /api/projects/<p>/pieces/<i>/download and GET /api/projects/<p>/download answer a file (a png, a zip) as an attachment, and so does GET /api/projects/<p>/storyboard/film (the mp4).
GET /files/<project>/<path> serves the pictures of a project (its piece/ folder, and the brand/ folder of its brand) and
GET /files/_marques/<brand>/<path> those of a brand (its brand/ folder). Stdlib only. Listens
on 127.0.0.1 unless told otherwise; on a central server it sits behind a proxy that terminates TLS, and `authenticate`
is where its auth plugs in.
"""

import argparse
import hmac
import json
import mimetypes
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import workflow  # noqa: E402
from workflow import Conflict, Download, NotFound  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
B = r"(?P<b>[\w-]+)"
P = r"(?P<p>[\w-]+)"
I = r"(?P<i>[\w-]+)"
J = r"(?P<j>[\w-]+)"

# (method, path pattern, backend call taking (backend, match groups, json body))
ROUTES = [
    ("GET", r"/api/machine", lambda b, m, d: b.machine()),
    ("GET", r"/api/engines", lambda b, m, d: b.get_engines()),
    ("PUT", r"/api/engines/image", lambda b, m, d: b.put_engines("image", d)),
    ("PUT", r"/api/engines/text", lambda b, m, d: b.put_engines("text", d)),
    ("GET", r"/api/tasks", lambda b, m, d: b.tasks()),
    ("GET", r"/api/projects", lambda b, m, d: b.list_projects()),
    ("POST", r"/api/projects", lambda b, m, d: b.create_project(d.get("name"), d.get("from"), d.get("brand"), d.get("site"))),
    ("GET", r"/api/brands", lambda b, m, d: b.list_brands()),
    ("POST", r"/api/brands", lambda b, m, d: b.create_brand(d.get("name"), d.get("site"))),
    ("GET", rf"/api/brands/{B}", lambda b, m, d: b.brand_view(m["b"])),
    ("PUT", rf"/api/brands/{B}", lambda b, m, d: b.update_brand(m["b"], d.get("name"), d.get("site"), d.get("description"))),
    ("POST", rf"/api/brands/{B}/logo", lambda b, m, d: b.add_logo(m["b"], d["raw"], d["type"], d["name"])),
    ("POST", rf"/api/brands/{B}/discover", lambda b, m, d: b.discover(m["b"])),
    ("POST", rf"/api/brands/{B}/keep", lambda b, m, d: b.keep_brand(m["b"], d.get("kept", []), d.get("logo"))),
    ("GET", rf"/api/brands/{B}/brief", lambda b, m, d: b.get_brand_brief(m["b"])),
    ("PUT", rf"/api/brands/{B}/brief", lambda b, m, d: b.put_brand_brief(m["b"], d.get("fields", {}))),
    ("POST", rf"/api/brands/{B}/confirm", lambda b, m, d: b.confirm(m["b"], d.get("keys"))),
    ("GET", rf"/api/brands/{B}/personas", lambda b, m, d: b.get_personas(m["b"])),
    ("PUT", rf"/api/brands/{B}/personas", lambda b, m, d: b.put_personas(m["b"], d.get("personas"))),
    ("POST", rf"/api/brands/{B}/personas/propose", lambda b, m, d: b.propose_personas(m["b"])),
    ("GET", rf"/api/brands/{B}/names", lambda b, m, d: b.get_names(m["b"])),
    ("PUT", rf"/api/brands/{B}/names", lambda b, m, d: b.put_names(m["b"], d.get("names"), d.get("chosen"))),
    ("POST", rf"/api/brands/{B}/names/propose", lambda b, m, d: b.propose_names(m["b"])),
    # logos
    ("GET", rf"/api/brands/{B}/logo/tracks", lambda b, m, d: b.get_logos(m["b"])),
    ("PUT", rf"/api/brands/{B}/logo/tracks", lambda b, m, d: b.put_logos(m["b"], d.get("keep"))),
    ("POST", rf"/api/brands/{B}/logo/propose", lambda b, m, d: b.propose_logos(m["b"])),
    ("POST", rf"/api/brands/{B}/logo/choose", lambda b, m, d: b.choose_logo(m["b"], d.get("id"))),
    # competitors
    ("GET", rf"/api/brands/{B}/competitors", lambda b, m, d: b.get_competitors(m["b"])),
    ("PUT", rf"/api/brands/{B}/competitors", lambda b, m, d: b.put_competitors(m["b"], d.get("competitors"))),
    ("POST", rf"/api/brands/{B}/competitors/propose", lambda b, m, d: b.propose_competitors(m["b"])),
    # research
    ("GET", rf"/api/brands/{B}/research", lambda b, m, d: b.get_research(m["b"])),
    ("PUT", rf"/api/brands/{B}/research", lambda b, m, d: b.put_research(m["b"], d.get("research"))),
    ("POST", rf"/api/brands/{B}/research/propose", lambda b, m, d: b.propose_research(m["b"])),
    ("POST", rf"/api/brands/{B}/projects", lambda b, m, d: b.create_project_in(m["b"], d.get("name"), d.get("from"))),
    ("GET", rf"/api/projects/{P}", lambda b, m, d: b.project(m["p"])),
    ("PUT", rf"/api/projects/{P}", lambda b, m, d: b.update_project(m["p"], d.get("name"))),
    ("POST", rf"/api/projects/{P}/brand/learn", lambda b, m, d: b.learn(m["p"], d.get("mode", "learn"), d.get("answers"))),
    ("GET", rf"/api/projects/{P}/brand", lambda b, m, d: b.brand(m["p"])),
    ("POST", rf"/api/projects/{P}/brand/keep", lambda b, m, d: b.keep(m["p"], d.get("kept", []), d.get("logo"))),
    ("GET", rf"/api/projects/{P}/brief", lambda b, m, d: b.get_brief(m["p"])),
    ("PUT", rf"/api/projects/{P}/brief", lambda b, m, d: b.put_brief(m["p"], d.get("fields", {}))),
    # interview
    ("GET", rf"/api/projects/{P}/interview", lambda b, m, d: b.get_interview(m["p"])),
    ("POST", rf"/api/projects/{P}/interview", lambda b, m, d: b.start_interview(m["p"], d.get("answers"))),
    # texts
    ("GET", rf"/api/projects/{P}/texts", lambda b, m, d: b.get_texts(m["p"])),
    ("PUT", rf"/api/projects/{P}/texts", lambda b, m, d: b.put_texts(m["p"], d.get("texts"))),
    ("POST", rf"/api/projects/{P}/texts/propose", lambda b, m, d: b.propose_texts(m["p"])),
    ("GET", rf"/api/projects/{P}/mandates", lambda b, m, d: b.get_mandates(m["p"])),
    ("PUT", rf"/api/projects/{P}/mandates", lambda b, m, d: b.put_mandates(m["p"], d.get("items"), d.get("common"))),
    ("POST", rf"/api/projects/{P}/diverge", lambda b, m, d: b.diverge(m["p"])),
    ("GET", rf"/api/projects/{P}/variants", lambda b, m, d: b.variants(m["p"])),
    ("PUT", rf"/api/projects/{P}/variants/(?P<v>[\w-]+)/prompt", lambda b, m, d: b.put_variant_prompt(m["p"], m["v"], d.get("prompt"))),
    ("PUT", rf"/api/projects/{P}/variants/(?P<v>[\w-]+)/text", lambda b, m, d: b.put_variant_text(m["p"], m["v"], d.get("headline"), d.get("subline"))),
    # storyboard
    ("GET", rf"/api/projects/{P}/storyboard", lambda b, m, d: b.get_storyboard(m["p"])),
    ("PUT", rf"/api/projects/{P}/storyboard", lambda b, m, d: b.put_storyboard(m["p"], d.get("script"), d.get("shots"))),
    ("POST", rf"/api/projects/{P}/storyboard/propose", lambda b, m, d: b.propose_storyboard(m["p"])),
    ("POST", rf"/api/projects/{P}/storyboard/render", lambda b, m, d: b.render_film(m["p"])),
    ("GET", rf"/api/projects/{P}/storyboard/film", lambda b, m, d: b.download_film(m["p"])),
    ("POST", rf"/api/projects/{P}/pick", lambda b, m, d: b.pick(m["p"], d.get("variants", []))),
    ("POST", rf"/api/projects/{P}/images", lambda b, m, d: b.draw_images(m["p"], d.get("variant"))),
    ("POST", rf"/api/projects/{P}/compose", lambda b, m, d: b.compose_all(m["p"])),
    ("GET", rf"/api/projects/{P}/download", lambda b, m, d: b.download_project(m["p"])),
    ("GET", rf"/api/projects/{P}/pieces/{I}", lambda b, m, d: b.piece(m["p"], m["i"])),
    ("GET", rf"/api/projects/{P}/pieces/{I}/download", lambda b, m, d: b.download_piece(m["p"], m["i"])),
    ("PUT", rf"/api/projects/{P}/pieces/{I}/prompt", lambda b, m, d: b.put_prompt(m["p"], m["i"], d.get("prompt"))),
    ("POST", rf"/api/projects/{P}/pieces/{I}/image", lambda b, m, d: b.image(m["p"], m["i"])),
    ("POST", rf"/api/projects/{P}/pieces/{I}/compose", lambda b, m, d: b.compose(m["p"], m["i"])),
    ("POST", rf"/api/projects/{P}/pieces/{I}/decide", lambda b, m, d: b.decide(m["p"], m["i"], d.get("verdict"), d.get("words", ""))),
    ("POST", rf"/api/projects/{P}/pieces/{I}/judge", lambda b, m, d: b.judge_piece(m["p"], m["i"])),
    ("POST", rf"/api/projects/{P}/pieces/{I}/readers/(?P<n>[0-9])/run", lambda b, m, d: b.run_reader(m["p"], m["i"], int(m["n"]))),
    ("GET", r"/api/judgements", lambda b, m, d: b.list_judgements()),
    ("POST", r"/api/judgements", lambda b, m, d: b.create_judgement(d["raw"], d["type"], d["name"], d["meta"])),
    ("GET", rf"/api/judgements/{J}", lambda b, m, d: b.judgement(m["j"])),
    ("POST", rf"/api/judgements/{J}/run", lambda b, m, d: b.run_judgement(m["j"])),
    ("POST", rf"/api/judgements/{J}/readers/(?P<n>[0-9])/run", lambda b, m, d: b.run_judgement_reader(m["j"], int(m["n"]))),
    ("GET", rf"/api/judgements/{J}/rounds", lambda b, m, d: b.judgement_rounds(m["j"])),
    ("POST", rf"/api/judgements/{J}/rounds", lambda b, m, d: b.run_judgement_rounds(m["j"])),
    ("GET", rf"/api/judgements/{J}/page", lambda b, m, d: b.judgement_page(m["j"])),
    ("GET", r"/api/jobs/(?P<j>[\w-]+)", lambda b, m, d: b.job(m["j"])),
]


# the routes that take a file, not JSON: the body is the file itself, its type is the request's Content-Type and its name an X-Filename header;
# what comes with it, if anything, is an X-Judge header (JSON, URL-encoded). Each with the size beyond which the body is refused (bytes)
RAW_ROUTES = {rf"/api/brands/{B}/logo": workflow.LOGO_MAX, r"/api/judgements": workflow.JUDGE_MAX}
RAW_DRAIN = 16 * 1024 * 1024  # a refused body up to this size is read and thrown away, so the answer reaches the browser; beyond, the connection closes


def authenticate(headers) -> bool:
    """The one place the authentication plugs in. Local: STUDIO_AUTH=none (default). STUDIO_AUTH=token: a bearer
    token, STUDIO_TOKEN. A central server replaces this function with its own (session, SSO, roles)."""
    mode = os.environ.get("STUDIO_AUTH", "none")
    if mode == "none":
        return True
    if mode == "token":
        want = os.environ.get("STUDIO_TOKEN", "")
        got = (headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return bool(want) and hmac.compare_digest(got, want)
    return False


def make_handler(backend):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ix-studio"

        def log_message(self, fmt, *args):  # quiet: one line per API call is enough
            if os.environ.get("STUDIO_LOG"):
                super().log_message(fmt, *args)

        def send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def api(self, method):
            path = self.path.split("?", 1)[0].rstrip("/")
            if path == "/api/health":
                return self.send(200, {**backend.health(), "auth": os.environ.get("STUDIO_AUTH", "none")})
            if not authenticate(self.headers):
                return self.send(401, {"error": "authentication required"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                raw_max = next((mx for pat, mx in RAW_ROUTES.items() if re.fullmatch(pat, path)), None) if method == "POST" else None
                if raw_max is not None:
                    if n > raw_max:
                        if n <= RAW_DRAIN:
                            self.rfile.read(n)
                        else:
                            self.close_connection = True
                        return self.send(400, {"error": f"the file is too big ({raw_max // (1024 * 1024)} MB at most)"})
                    name = urllib.parse.unquote(self.headers.get("X-Filename") or "")
                    body = {"raw": self.rfile.read(n) if n else b"", "type": self.headers.get("Content-Type") or "", "name": name,
                            "meta": urllib.parse.unquote(self.headers.get("X-Judge") or "")}
                else:
                    body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                    if not isinstance(body, dict):
                        raise ValueError("the body must be a JSON object")
            except ValueError as err:
                return self.send(400, {"error": f"bad JSON: {err}"})
            for verb, pat, call in ROUTES:
                m = re.fullmatch(pat, path)
                if m and verb == method:
                    try:
                        out = call(backend, m.groupdict(), body)
                        if isinstance(out, Download):  # a file, not JSON: sent as an attachment
                            return self.send(200, out.data, out.ctype, {"Content-Disposition": f'attachment; filename="{out.name}"', "X-Content-Type-Options": "nosniff"})
                        return self.send(200, out)
                    except NotFound as err:
                        return self.send(404, {"error": str(err)})
                    except Conflict as err:
                        return self.send(409, {"error": str(err)})
                    except ValueError as err:
                        return self.send(400, {"error": str(err)})
            return self.send(404, {"error": f"no route {method} {path}"})

        def static(self):
            rel = urllib.parse.unquote(self.path.split("?", 1)[0]).lstrip("/") or "index.html"
            f = (STATIC / rel).resolve()
            if not f.is_relative_to(STATIC) or not f.is_file():
                return self.send(404, b"not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self.send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))

        def files(self):
            """A picture of a project or of a brand: only inside their own folders, under the same authentication as the API."""
            if not authenticate(self.headers):
                return self.send(401, b"authentication required", "text/plain; charset=utf-8")
            pid, _, rel = urllib.parse.unquote(self.path.split("?", 1)[0])[len("/files/"):].partition("/")
            try:
                f = backend.file(pid, rel) if hasattr(backend, "file") else None
            except NotFound:
                f = None
            if f is None:  # the simulated backend has no files of its own: its pictures are in static/stub
                return self.send(404, b"not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            self.send(200, f.read_bytes(), ctype, {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox"})

        def do_GET(self):
            if self.path.startswith("/api/"):
                self.api("GET")
            elif self.path.startswith("/files/"):
                self.files()
            else:
                self.static()

        def do_POST(self):
            self.api("POST")

        def do_PUT(self):
            self.api("PUT")

    return Handler


class StudioServer(ThreadingHTTPServer):
    request_queue_size = 128  # a browser opens a dozen connections at once; the default of 5 resets some of them
    daemon_threads = True


def make_backend(kind=None):
    """The backend STUDIO_BACKEND names: studio (default, the real one) or stub (the simulated one)."""
    kind = kind or os.environ.get("STUDIO_BACKEND", "studio")
    if kind == "stub":
        from backend_stub import StubBackend
        return StubBackend()
    if kind == "studio":
        from backend_studio import StudioBackend
        return StudioBackend()
    raise SystemExit(f"STUDIO_BACKEND is studio or stub, not {kind!r}")


def serve(host="127.0.0.1", port=8765, backend=None):
    httpd = StudioServer((host, port), make_handler(backend or make_backend()))
    return httpd


def main(argv=None):
    a = argparse.ArgumentParser(prog="server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--port", type=int, default=int(os.environ.get("STUDIO_PORT", 8765)))
    args = a.parse_args(argv)
    backend = make_backend()
    httpd = serve(args.host, args.port, backend)
    home = f", projects in {backend.home}" if hasattr(backend, "home") else ""
    print(f"studio: http://{args.host}:{args.port}/  (backend {backend.name}{home}, auth {os.environ.get('STUDIO_AUTH', 'none')})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
