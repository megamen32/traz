"""Optional loopback-only interface. It reads files, never transcript instructions."""

from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from .storage import Store

MAX_UPLOAD = 32 * 1024 * 1024
WEB = Path(__file__).parent / "web"


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root: Path | str, port: int = 8765, token: str | None = None):
        if not 0 <= port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        self.root = Path(root).expanduser()
        self.token = token or secrets.token_urlsafe(32)
        with Store(self.root):
            pass
        super().__init__(("127.0.0.1", port), Handler)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/#token={self.token}"


class Handler(BaseHTTPRequestHandler):
    server: LocalServer

    def log_message(self, fmt: str, *args: object) -> None:
        # URLs can contain file names and session identifiers. Keep them local.
        pass

    def reply(self, status: int, payload: object, content_type: str = "application/json; charset=utf-8") -> None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self, require_token: bool) -> bool:
        permitted = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in permitted:
            self.reply(403, {"error": "Use the loopback URL printed by traz serve."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + host for host in permitted}:
            self.reply(403, {"error": "Cross-origin requests are not allowed."})
            return False
        if require_token and not hmac.compare_digest(self.headers.get("Authorization", "").encode("utf-8"), ("Bearer " + self.server.token).encode("utf-8")):
            self.reply(401, {"error": "Open the complete local URL printed by traz serve, including its token fragment."})
            return False
        return True

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if not self.allowed(url.path.startswith("/api/")):
            return
        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
        if url.path in assets:
            file, mime = assets[url.path]
            self.reply(200, (WEB / file).read_bytes(), mime)
            return
        try:
            from .learning import matrix, proposals, summary
            with Store(self.server.root) as store:
                if url.path == "/api/sessions":
                    data = store.list_sessions(limit=200)
                elif url.path == "/api/proposals":
                    data = proposals(store)
                elif url.path == "/api/summary":
                    data = summary(store)
                    data["session_count"] = store.db.execute("SELECT count(*) FROM sessions").fetchone()[0]
                elif url.path == "/api/matrix":
                    query = parse_qs(url.query)
                    scope = {key: query[key][0] for key in ("project", "harness", "model", "environment", "task_family") if key in query}
                    data = matrix(store, query.get("improve", [None])[0], query.get("protect", [None])[0], scope=scope or None)
                elif url.path.startswith("/api/session/"):
                    data = store.session(url.path[len("/api/session/"):])
                else:
                    self.reply(404, {"error": "Not found"})
                    return
            self.reply(200, data)
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            self.reply(400, {"error": str(exc)})

    def do_POST(self) -> None:
        if not self.allowed(True):
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > MAX_UPLOAD:
                self.reply(413, {"error": "Upload limit is 32 MiB; use the CLI for larger transcripts."})
                return
            self.connection.settimeout(30)
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete request body")
            from .analysis import analyze
            from .learning import evaluate
            with Store(self.server.root) as store:
                if self.path == "/api/ingest":
                    name = Path(unquote(self.headers.get("X-Filename", "session.jsonl"))).name
                    fmt = self.headers.get("X-Format", "auto")
                    project = unquote(self.headers.get("X-Project", "default")).strip() or "default"
                    if len(project) > 200 or len(name) > 255:
                        raise ValueError("Project or filename is too long")
                    session = store.ingest_bytes(body, name, format=fmt, project=project)
                    report = analyze(store, session["id"])
                    data = {"session": session, "analysis": report}
                elif self.path.startswith("/api/analyze/"):
                    data = analyze(store, self.path[len("/api/analyze/"):])
                elif self.path == "/api/evaluate":
                    if length > 8 * 1024 * 1024:
                        raise ValueError("Evaluation report exceeds 8 MiB")
                    data = evaluate(store, json.loads(body))
                else:
                    self.reply(404, {"error": "Not found"})
                    return
            self.reply(200, data)
        except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
            self.reply(400, {"error": str(exc)})


def serve(root: Path | str, port: int = 8765) -> None:
    with LocalServer(root, port) as server:
        print("TRAZ local workspace: " + server.url, flush=True)
        print("The corpus stays on this computer. Stop with Ctrl+C.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
