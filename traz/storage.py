"""Lossless local corpus, immutable source objects and a rebuildable SQLite index."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import hashlib
from itertools import zip_longest
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import BinaryIO

from .parsers import FORMATS, parse_file

CHUNK = 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Store:
    """A private, local corpus. Use one instance per thread/request."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        if self.root == Path(self.root.anchor):
            raise ValueError("Choose a dedicated corpus directory, not a filesystem root")
        if any((parent / ".git").exists() for parent in (self.root, *self.root.parents)):
            raise ValueError("The corpus must be outside Git checkouts so private transcripts cannot be committed")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        for name in ("raw", "staging"):
            (self.root / name).mkdir(mode=0o700, exist_ok=True)
            os.chmod(self.root / name, 0o700)
        database = self.root / "index.sqlite3"
        self.db = sqlite3.connect(database, timeout=30)
        os.chmod(database, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL UNIQUE,
                project TEXT NOT NULL,
                session_id TEXT,
                logical_session_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_format TEXT NOT NULL,
                parse_status TEXT NOT NULL,
                events_count INTEGER NOT NULL DEFAULT 0,
                raw_path TEXT NOT NULL,
                raw_bytes INTEGER NOT NULL,
                imported_at TEXT NOT NULL,
                warnings_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS events (
                session_id TEXT NOT NULL REFERENCES sessions(id),
                event_id INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                PRIMARY KEY (session_id, event_id)
            );
            CREATE INDEX IF NOT EXISTS sessions_project ON sessions(project);
            CREATE INDEX IF NOT EXISTS sessions_logical ON sessions(project, logical_session_id);
        """)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict:
        if row is None:
            raise KeyError("Session not found")
        result = dict(row)
        result["warnings"] = json.loads(result.pop("warnings_json"))
        result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    def session(self, id: str) -> dict:
        row = self.db.execute("SELECT * FROM sessions WHERE id = ?", (id,)).fetchone()
        if row is not None:
            return self._row(row)
        if not isinstance(id, str) or len(id) < 8 or any(c not in "0123456789abcdef" for c in id):
            raise KeyError(f"Unknown session {id!r}; use a full ID or at least 8 hash characters")
        matches = self.db.execute("SELECT * FROM sessions WHERE id LIKE ? LIMIT 2", (id + "%",)).fetchall()
        if len(matches) != 1:
            raise KeyError(f"Session prefix {id!r} is {'ambiguous' if matches else 'unknown'}")
        return self._row(matches[0])

    def list_sessions(self, limit: int = 100) -> list[dict]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        rows = self.db.execute("SELECT * FROM sessions ORDER BY imported_at DESC, id LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def events(self, id: str) -> list[dict]:
        source = self.session(id)
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT payload_json FROM events WHERE session_id = ? ORDER BY event_id", (source["id"],))]

    def iter_events(self, id: str):
        source = self.session(id)
        for row in self.db.execute("SELECT payload_json FROM events WHERE session_id = ? ORDER BY event_id", (source["id"],)):
            yield json.loads(row[0])

    def _check_source(self, relative: str, expected_hash: str) -> tuple[int, str]:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root / "raw"):
            raise ValueError("Archive path escapes corpus raw directory")
        digest = hashlib.sha256()
        size = 0
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected_hash:
            raise ValueError(f"Archive SHA-256 mismatch for {expected_hash}")
        return size, actual

    def _manifest(self, archive_path: Path, metadata: dict, *, replace: bool = False):
        """Keep import provenance beside raw bytes, independently of the index."""
        destination = archive_path.with_suffix(".meta.json")
        descriptor, temporary = tempfile.mkstemp(prefix="manifest-", dir=self.root / "staging")
        stage = Path(temporary)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(metadata, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            if replace:
                os.replace(stage, destination)
            else:
                try:
                    os.link(stage, destination)
                except FileExistsError:
                    existing = json.loads(destination.read_text(encoding="utf-8"))
                    if existing.get("project") != metadata.get("project"):
                        raise ValueError("Archived content already belongs to another project in its recovery manifest")
        finally:
            stage.unlink(missing_ok=True)

    def _ingest(self, stream: BinaryIO, name: str, format: str, project: str, session_id: str | None) -> dict:
        if format not in FORMATS:
            raise ValueError(f"Unsupported format {format!r}; choose one of {FORMATS}")
        if not isinstance(project, str) or not project.strip():
            raise ValueError("project must be a nonempty string")
        if session_id is not None and (not isinstance(session_id, str) or not session_id.strip()):
            raise ValueError("session_id must be a nonempty string when provided")
        digest = hashlib.sha256()
        size = 0
        descriptor, temporary = tempfile.mkstemp(prefix="source-", suffix=".gz", dir=self.root / "staging")
        stage = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as output:
                with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as archive:
                    while chunk := stream.read(CHUNK):
                        digest.update(chunk)
                        size += len(chunk)
                        archive.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            sha = digest.hexdigest()
            prior = self.db.execute("SELECT * FROM sessions WHERE id = ?", (sha,)).fetchone()
            if prior is not None:
                existing = self._row(prior)
                if existing["project"] != project:
                    raise ValueError(f"Identical content already belongs to project {existing['project']!r}; duplicate evidence across projects is not imported")
                self._check_source(existing["raw_path"], sha)
                existing["duplicate"] = True
                return existing
            relative = f"raw/{sha[:2]}/{sha}.gz"
            destination = self.root / relative
            destination.parent.mkdir(mode=0o700, exist_ok=True)
            # An exclusive hardlink atomically publishes complete bytes without
            # overwriting an immutable object another importer just produced.
            try:
                os.link(stage, destination)
            except FileExistsError:
                self._check_source(relative, sha)
            self._manifest(destination, {
                "schema_version": "0.1", "id": sha, "sha256": sha, "project": project,
                "session_id": session_id, "source_name": Path(name).name, "requested_format": format,
                "raw_path": relative, "raw_bytes": size, "imported_at": _now(), "parse_status": "pending",
            })
            parser = parse_file(destination, format, compressed=True, source_name=name)
            count = 0
            with self.db:
                # Serialize writers and check again after acquiring the lock.
                self.db.execute("BEGIN IMMEDIATE")
                prior = self.db.execute("SELECT * FROM sessions WHERE id = ?", (sha,)).fetchone()
                if prior is not None:
                    existing = self._row(prior)
                    if existing["project"] != project:
                        raise ValueError("Identical content was concurrently imported under another project")
                    existing["duplicate"] = True
                    return existing
                self.db.execute("""INSERT INTO sessions
                    (id, sha256, project, session_id, logical_session_id, source_name,
                     source_format, parse_status, events_count, raw_path, raw_bytes, imported_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'unknown', 'parsing', 0, ?, ?, ?)""",
                    (sha, sha, project, session_id, session_id or sha, Path(name).name, relative, size, _now()))
                try:
                    for event in parser:
                        count += 1
                        self.db.execute("INSERT INTO events VALUES (?, ?, ?)",
                                        (sha, event["event_id"], json.dumps(event, ensure_ascii=False)))
                except (OSError, ValueError, TypeError, RecursionError) as exc:
                    parser.metadata["warnings"].append(f"Parser stopped: {type(exc).__name__}: {exc}. Original retained.")
                    parser.metadata["parse_status"] = "partial" if count else "unparsed"
                meta = parser.metadata
                native_id = session_id or meta.get("native_session_id")
                if native_id is not None:
                    native_id = str(native_id)
                warnings = meta.pop("warnings", [])
                self.db.execute("""UPDATE sessions SET session_id=?, logical_session_id=?,
                    source_format=?, parse_status=?, events_count=?, warnings_json=?, metadata_json=?
                    WHERE id=?""", (native_id, native_id or sha, meta["source_format"], meta["parse_status"], count,
                                    json.dumps(warnings, ensure_ascii=False), json.dumps(meta, ensure_ascii=False), sha))
            result = self.session(sha)
            result["duplicate"] = False
            self._manifest(destination, {"schema_version": "0.1", **result}, replace=True)
            return result
        finally:
            stage.unlink(missing_ok=True)

    def ingest(self, path: str | Path, format: str = "auto", project: str = "default", session_id: str | None = None) -> dict:
        source = Path(path).expanduser()
        if not source.is_file():
            raise ValueError(f"Transcript is not a regular file: {source}")
        with source.open("rb") as stream:
            return self._ingest(stream, source.name, format, project, session_id)

    def ingest_bytes(self, data: bytes, name: str, format: str = "auto", project: str = "default", session_id: str | None = None) -> dict:
        from io import BytesIO
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        return self._ingest(BytesIO(data), name, format, project, session_id)

    def refresh_metadata(self, id: str) -> dict:
        """Refresh parse coverage only when every existing event stays identical.

        Authored reviews cite normalized event IDs. A parser upgrade must never
        silently repoint that evidence. Changes to event interpretation require
        a separate versioned migration, which this operation explicitly refuses.
        """
        source = self.session(id)
        self._check_source(source["raw_path"], source["sha256"])
        # Semantic source type and file framing differ, for example OpenCode
        # messages exported as JSONL. Replay the originally observed framing.
        encoding = source["metadata"].get("encoding")
        parse_format = encoding if encoding in ("jsonl", "json", "text") else source["source_format"]
        parser = parse_file(self.root / source["raw_path"], parse_format,
                            compressed=True, source_name=source["source_name"])
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            for before, after in zip_longest(self.iter_events(source["id"]), parser):
                if before != after:
                    raise ValueError("Parser refresh would change cited events; no metadata was updated")
            meta = dict(parser.metadata)
            warnings = meta.pop("warnings", [])
            self.db.execute("""UPDATE sessions SET source_format=?, parse_status=?,
                warnings_json=?, metadata_json=? WHERE id=?""",
                (meta["source_format"], meta["parse_status"], json.dumps(warnings, ensure_ascii=False),
                 json.dumps(meta, ensure_ascii=False), source["id"]))
        result = self.session(source["id"])
        self._manifest(self.root / source["raw_path"], {"schema_version": "0.1", **result}, replace=True)
        return result

    def verify(self, id: str | None = None) -> dict:
        sources = [self.session(id)] if id is not None else [self._row(row) for row in self.db.execute("SELECT * FROM sessions ORDER BY id")]
        results = []
        for source in sources:
            item = {"id": source["id"], "ok": True}
            try:
                size, _ = self._check_source(source["raw_path"], source["sha256"])
                if size != source["raw_bytes"]:
                    raise ValueError("Archive size differs from recorded source size")
                item["raw_bytes"] = size
            except (OSError, ValueError, EOFError) as exc:
                item.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            results.append(item)
        return {"ok": all(item["ok"] for item in results), "checked": len(results), "results": results}

    def export_raw(self, id: str, destination: str | Path) -> dict:
        source = self.session(id)
        target = Path(destination).expanduser().absolute()
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite {target}")
        if not target.parent.is_dir():
            raise ValueError("Export parent directory must already exist")
        descriptor, temporary = tempfile.mkstemp(prefix=".traz-export-", dir=target.parent)
        stage = Path(temporary)
        try:
            digest = hashlib.sha256()
            size = 0
            with os.fdopen(descriptor, "wb") as output, gzip.open(self.root / source["raw_path"], "rb") as original:
                while chunk := original.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != source["sha256"] or size != source["raw_bytes"]:
                raise ValueError("Archive integrity check failed; export was not published")
            os.link(stage, target)
            return {"id": source["id"], "destination": str(target), "raw_bytes": size, "sha256": source["sha256"]}
        finally:
            stage.unlink(missing_ok=True)
