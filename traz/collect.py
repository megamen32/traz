"""Collect explicitly connected local files as stable, lossless snapshots.

There is no filesystem discovery, network client, command executor, or scheduler
here. All configuration and run history live in the private corpus.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import uuid

from .parsers import FORMATS

CHUNK = 1024 * 1024
MANIFEST_LIMIT = 1024 * 1024
SOURCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{field} must be a nonempty string of at most {maximum} characters")
    return value


def validate_manifest(manifest: dict) -> dict:
    """Validate all entries before saving or collecting any source."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "0.1":
        raise ValueError("Source manifest must be an object with schema_version '0.1'")
    if set(manifest) - {"schema_version", "sources"}:
        raise ValueError("Source manifest supports only schema_version and sources")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or len(sources) > 1000:
        raise ValueError("sources must be a list containing at most 1000 explicit local files")
    normalized = []
    seen = set()
    for index, source in enumerate(sources):
        field = f"sources[{index}]"
        if not isinstance(source, dict):
            raise ValueError(field + " must be an object")
        if set(source) - {"id", "name", "path", "format", "project", "session_id"}:
            raise ValueError(field + " supports only id, name, path, format, project, session_id")
        source_id = _text(source.get("id"), field + ".id", 128)
        if not SOURCE_ID.fullmatch(source_id) or source_id in seen:
            raise ValueError(field + ".id must be unique and use letters, digits, dot, colon, underscore or hyphen")
        seen.add(source_id)
        raw_path = _text(source.get("path"), field + ".path", 8192)
        if "://" in raw_path:
            raise ValueError(field + ".path must name a local file, not a network endpoint")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            raise ValueError(field + ".path must be an absolute local path")
        # Normalize lexical components without resolving a symlink which may
        # later be retargeted. Its current target is checked while collecting.
        path = Path(os.path.abspath(path))
        fmt = source.get("format", "auto")
        if fmt not in FORMATS:
            raise ValueError(field + f".format must be one of {FORMATS}")
        entry = {
            "id": source_id,
            "name": _text(source.get("name", source_id), field + ".name", 500),
            "path": str(path), "format": fmt,
            "project": _text(source.get("project", "default"), field + ".project", 200),
        }
        if source.get("session_id") is not None:
            entry["session_id"] = _text(source["session_id"], field + ".session_id", 500)
        normalized.append(entry)
    result = {"schema_version": "0.1", "sources": normalized}
    if len(_json(result).encode("utf-8")) > MANIFEST_LIMIT:
        raise ValueError("Source manifest exceeds 1 MiB")
    return result


def save_manifest(store, manifest: dict) -> Path:
    """Atomically save a validated connection manifest with private permissions."""
    normalized = validate_manifest(manifest)
    target = store.root / "sources.json"
    descriptor, temporary = tempfile.mkstemp(prefix="sources-", suffix=".json", dir=store.root / "staging")
    stage = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(_json(normalized) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(stage, target)
    finally:
        stage.unlink(missing_ok=True)
    _schema(store)
    now = _now()
    for source in normalized["sources"]:
        _register(store, source, now)
    return target


def load_manifest(store) -> dict:
    path = store.root / "sources.json"
    with path.open("rb") as stream:
        data = stream.read(MANIFEST_LIMIT + 1)
    if len(data) > MANIFEST_LIMIT:
        raise ValueError("Saved source manifest exceeds 1 MiB")
    return validate_manifest(json.loads(data))


def _schema(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS traz_collection_sources (
            id TEXT PRIMARY KEY,
            config_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_checked_at TEXT,
            last_status TEXT NOT NULL,
            last_error TEXT,
            last_snapshot_id TEXT REFERENCES sessions(id),
            logical_session_id TEXT,
            last_success_at TEXT,
            last_signature_json TEXT,
            last_analysis_snapshot_id TEXT,
            last_analysis_version TEXT,
            last_analysis_at TEXT
        );
        CREATE TABLE IF NOT EXISTS traz_collection_runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            manifest_json TEXT NOT NULL,
            report_json TEXT
        );
    """)


def connections(store) -> list[dict]:
    """List retained connection history, including sources omitted from a manifest."""
    _schema(store)
    try:
        active = {source["id"] for source in load_manifest(store)["sources"]}
    except FileNotFoundError:
        active = set()
    result = []
    for row in store.db.execute("SELECT * FROM traz_collection_sources ORDER BY id"):
        item = dict(row)
        item["source"] = json.loads(item.pop("config_json"))
        signature = item.pop("last_signature_json")
        item["last_signature"] = json.loads(signature) if signature else None
        item["configured"] = item["id"] in active
        result.append(item)
    return result


def _signature(info):
    return {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


class SourceChanged(Exception):
    """The copy did not correspond to one metadata-stable source state."""


class SourceDeferred(Exception):
    """Both bounded attempts failed to capture a stable source snapshot."""


def _remove_snapshot(path):
    if path is not None:
        path.unlink(missing_ok=True)
        path.parent.rmdir()


def _copy_once(store, source: dict):
    path = Path(source["path"])
    if path.resolve().is_relative_to(store.root):
        raise ValueError("A connection cannot collect the corpus's own files")
    # O_NONBLOCK prevents a replaced named pipe from blocking before fstat.
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    snapshot = None
    try:
        with os.fdopen(descriptor, "rb", buffering=0) as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Connected source is not a regular file")
            directory = Path(tempfile.mkdtemp(prefix="collect-", dir=store.root / "staging"))
            snapshot = directory / path.name
            output_fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            remaining = before.st_size
            digest = hashlib.sha256()
            with os.fdopen(output_fd, "wb") as output:
                while remaining:
                    block = stream.read(min(CHUNK, remaining))
                    if not block:
                        raise SourceChanged("Source shrank while it was being copied")
                    output.write(block)
                    digest.update(block)
                    remaining -= len(block)
                output.flush()
                os.fsync(output.fileno())
            after = os.fstat(stream.fileno())
            try:
                current = path.stat()
            except FileNotFoundError as exc:
                raise SourceChanged("Source path disappeared during copying") from exc
            if _signature(before) != _signature(after) or _signature(before) != _signature(current):
                raise SourceChanged("Source changed or its path was replaced during copying")
            return snapshot, _signature(before), digest.hexdigest()
    except BaseException:
        _remove_snapshot(snapshot)
        raise


def _stable_snapshot(store, source: dict):
    changed = None
    for attempt in (1, 2):
        try:
            path, signature, sha = _copy_once(store, source)
            return path, signature, sha, attempt
        except SourceChanged as exc:
            changed = str(exc)
        except OSError as exc:
            if attempt == 1:
                raise
            changed = "Source became unavailable after a changed snapshot: " + str(exc)
    raise SourceDeferred(changed or "Stable source snapshot unavailable")


def _register(store, source, now):
    with store.db:
        store.db.execute("BEGIN IMMEDIATE")
        previous = store.db.execute("SELECT config_json FROM traz_collection_sources WHERE id=?",
                                    (source["id"],)).fetchone()
        prior_config = json.loads(previous[0]) if previous is not None else None
        changed = prior_config is not None and any(
            prior_config.get(field) != source.get(field)
            for field in ("path", "project", "format", "session_id"))
        store.db.execute("""INSERT INTO traz_collection_sources
            (id,config_json,created_at,updated_at,last_status) VALUES(?,?,?,?, 'connected')
            ON CONFLICT(id) DO UPDATE SET config_json=excluded.config_json,updated_at=excluded.updated_at""",
            (source["id"], _json(source), now, now))
        if changed:
            # The current configuration has not been collected. Its prior raw
            # snapshots and completed collection reports remain unchanged.
            store.db.execute("""UPDATE traz_collection_sources SET last_checked_at=NULL,
                last_status='connected',last_error=NULL,last_snapshot_id=NULL,
                logical_session_id=NULL,last_success_at=NULL,last_signature_json=NULL,
                last_analysis_snapshot_id=NULL,last_analysis_version=NULL,last_analysis_at=NULL
                WHERE id=?""", (source["id"],))


def _analysis_cached(store, snapshot_id, version):
    exists = store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='traz_analyses'").fetchone()
    return bool(exists and store.db.execute(
        "SELECT 1 FROM traz_analyses WHERE session_id=? AND version=?", (snapshot_id, version)).fetchone())


def collect(store, manifest: dict, analyze_sessions: bool = True) -> dict:
    """Persist connections and collect each explicit local source once.

    One changed copy is retried once. Failures are retained per source so one
    unavailable file cannot prevent the other authorized sources from importing.
    The return value distinguishes raw archive coverage from parser/analysis coverage.
    """
    if not isinstance(analyze_sessions, bool):
        raise ValueError("analyze_sessions must be boolean")
    manifest = validate_manifest(manifest)
    save_manifest(store, manifest)
    _schema(store)
    started = _now()
    run_id = "collect_" + uuid.uuid4().hex
    report = {"schema_version": "0.1", "run_id": run_id, "started_at": started,
              "finished_at": None, "analysis_requested": analyze_sessions, "sources": []}
    store.db.execute("INSERT INTO traz_collection_runs(id,started_at,manifest_json) VALUES(?,?,?)",
                     (run_id, started, _json(manifest)))
    store.db.commit()
    for source in manifest["sources"]:
        checked = _now()
        _register(store, source, checked)
        result = {"source_id": source["id"], "name": source["name"], "path": source["path"],
                  "checked_at": checked, "analysis_status": "not_requested" if not analyze_sessions else "not_run"}
        snapshot = None
        try:
            snapshot, signature, sha, attempts = _stable_snapshot(store, source)
            try:
                imported = store.session(sha)
            except KeyError:
                imported = store.ingest(snapshot, format=source["format"], project=source["project"],
                                        session_id=source.get("session_id"))
            else:
                if imported["project"] != source["project"]:
                    raise ValueError("Identical content already belongs to a different project; no duplicate evidence created")
                if source.get("session_id") and source["session_id"] != imported["session_id"]:
                    raise ValueError("Identical content already has a different native session identity; existing evidence was retained")
                integrity = store.verify(sha)
                if not integrity["ok"]:
                    raise ValueError("Existing archived snapshot failed its integrity check")
                imported["duplicate"] = True
            if imported["sha256"] != sha:
                raise ValueError("Private staging snapshot changed before archival completed")
            result.update(status="unchanged" if imported.get("duplicate") else "archived",
                          snapshot_id=imported["id"], logical_session_id=imported["logical_session_id"],
                          duplicate=bool(imported.get("duplicate")), attempts=attempts,
                          raw_bytes=imported["raw_bytes"], events_count=imported["events_count"],
                          source_format=imported["source_format"], parse_status=imported["parse_status"],
                          warnings=imported["warnings"])
            succeeded = _now()
            # The connection advances only after the immutable raw object and
            # session row were successfully archived (or their integrity verified).
            store.db.execute("""UPDATE traz_collection_sources SET last_checked_at=?,last_status=?,
                last_error=NULL,last_snapshot_id=?,logical_session_id=?,last_success_at=?,
                last_signature_json=? WHERE id=?""",
                (checked, result["status"], imported["id"], imported["logical_session_id"], succeeded,
                 _json(signature), source["id"]))
            store.db.commit()
            if analyze_sessions:
                from .analysis import ANALYSIS_VERSION, analyze
                try:
                    cached = _analysis_cached(store, imported["id"], ANALYSIS_VERSION)
                    if not cached:
                        analyze(store, imported["id"])
                    result["analysis_status"] = "cached" if cached else "analyzed"
                    result["analysis_version"] = ANALYSIS_VERSION
                    store.db.execute("""UPDATE traz_collection_sources SET last_analysis_snapshot_id=?,
                        last_analysis_version=?,last_analysis_at=? WHERE id=?""",
                        (imported["id"], ANALYSIS_VERSION, _now(), source["id"]))
                    store.db.commit()
                except (ValueError, KeyError, OSError, TypeError, RecursionError, sqlite3.Error) as exc:
                    store.db.rollback()
                    result["analysis_status"] = "failed"
                    result["analysis_error"] = f"{type(exc).__name__}: {exc}"
                    store.db.execute("UPDATE traz_collection_sources SET last_status='analysis_failed',last_error=? WHERE id=?",
                                     (result["analysis_error"], source["id"]))
                    store.db.commit()
        except SourceDeferred as exc:
            result.update(status="deferred", error=str(exc), attempts=2)
        except (ValueError, KeyError, OSError, TypeError, RecursionError, sqlite3.Error) as exc:
            store.db.rollback()
            result.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            _remove_snapshot(snapshot)
        if result["status"] in ("failed", "deferred"):
            store.db.execute("UPDATE traz_collection_sources SET last_checked_at=?,last_status=?,last_error=? WHERE id=?",
                             (checked, result["status"], result["error"], source["id"]))
            store.db.commit()
        report["sources"].append(result)
    results = report["sources"]
    coverage = {"requested": len(results)}
    for status in ("archived", "unchanged", "deferred", "failed"):
        coverage[status] = sum(item["status"] == status for item in results)
    coverage["analysis_failed"] = sum(item["analysis_status"] == "failed" for item in results)
    coverage["parse_incomplete"] = sum(item.get("parse_status") not in (None, "ok") for item in results)
    coverage["archive_complete"] = not coverage["failed"] and not coverage["deferred"]
    coverage["parse_complete"] = coverage["archive_complete"] and not coverage["parse_incomplete"]
    coverage["analysis_complete"] = (coverage["parse_complete"] and not coverage["analysis_failed"]) if analyze_sessions else None
    coverage["complete"] = coverage["parse_complete"] and not coverage["analysis_failed"]
    report["coverage"] = coverage
    report["finished_at"] = _now()
    report["limitation"] = "Stable filesystem metadata is a bounded snapshot check, not proof that the native session is finished. Parse coverage and reported learning evidence remain separate. No schedule was created."
    store.db.execute("UPDATE traz_collection_runs SET finished_at=?,report_json=? WHERE id=?",
                     (report["finished_at"], _json(report), run_id))
    store.db.commit()
    return report
