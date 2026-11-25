"""Small local command line interface. No model calls or shell execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

from . import __version__
from .storage import Store


def default_root() -> Path:
    explicit = os.environ.get("TRAZ_HOME")
    if explicit:
        return Path(explicit).expanduser()
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "traz"


def emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TRAZ: preserve sessions, test improvements, retain evidence.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--root", type=Path, default=default_root(), help="private corpus directory, outside the source repository")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="initialize an external corpus")
    connect = sub.add_parser("connect", help="register explicit local transcript sources")
    connect.add_argument("file", type=Path)
    collect = sub.add_parser("collect", help="archive stable snapshots of connected sources")
    collect.add_argument("--manifest", type=Path, help="register this source manifest before collecting")
    collect.add_argument("--no-analyze", action="store_true")
    sub.add_parser("sources", help="show connected sources and their last collection outcome")
    imp = sub.add_parser("ingest", help="archive and index transcript files without modifying the originals")
    imp.add_argument("paths", nargs="+", type=Path)
    imp.add_argument("--format", default="auto", help="auto, codex, opencode, json, jsonl, normalized, generic, or text")
    imp.add_argument("--project", default="default")
    imp.add_argument("--session-id", help="native session ID, only for a single input file")
    ls = sub.add_parser("sessions", help="list imported snapshots")
    ls.add_argument("--limit", type=int, default=100)
    show = sub.add_parser("show", help="inspect one imported snapshot")
    show.add_argument("session")
    show.add_argument("--events", action="store_true")
    ana = sub.add_parser("analyze", help="derive conservative observations and candidate experiments")
    ana.add_argument("session", help="SHA-256 snapshot ID")
    cor = sub.add_parser("corrections", help="find user corrections and the work that preceded each one")
    cor.add_argument("session")
    met = sub.add_parser("metrics", help="measure observed Codex accounting without summing cumulative counters")
    met.add_argument("session")
    refresh = sub.add_parser("refresh-metadata", help="refresh parser coverage only if all cited events stay identical")
    refresh.add_argument("session")
    pro = sub.add_parser("proposals", help="show proposals and reported evaluation state")
    pro.add_argument("--session")
    ev = sub.add_parser("evaluate", help="record a paired experiment report; never executes its contents")
    ev.add_argument("file", type=Path)
    tpl = sub.add_parser("evaluation-template", help="create an unfilled experiment report for one proposal")
    tpl.add_argument("proposal")
    review = sub.add_parser("review", help="import a structured, source-cited retrospective as hypotheses")
    review.add_argument("file", type=Path)
    action = sub.add_parser("action", help="record an immutable intervention artifact without applying it")
    action.add_argument("file", type=Path)
    receipt = sub.add_parser("action-receipt", help="append a reported implementation or retirement receipt")
    receipt.add_argument("file", type=Path)
    check = sub.add_parser("action-verify", help="observe artifact bytes at an explicit local path; does not execute them")
    check.add_argument("action")
    check.add_argument("path", type=Path)
    check.add_argument("--expected-sha256")
    sub.add_parser("actions", help="inspect implementation receipts separately from efficacy evidence")
    ctx = sub.add_parser("context", help="retrieve bounded applicable advice for a new task; never starts a session")
    ctx.add_argument("--project", required=True)
    ctx.add_argument("--task-family", required=True)
    for key in ("harness", "model", "environment"):
        ctx.add_argument("--" + key)
    ctx.add_argument("--limit", type=int, default=5)
    ctx.add_argument("--max-chars", type=int, default=6000)
    evs = sub.add_parser("evaluations", help="inspect the append-only reported experiment ledger")
    evs.add_argument("--proposal")
    mat = sub.add_parser("matrix", help="inspect the sparse hypothesis matrix and reported evidence")
    mat.add_argument("--improve")
    mat.add_argument("--protect")
    for key in ("project", "harness", "model", "environment", "task-family"):
        mat.add_argument("--" + key)
    ver = sub.add_parser("verify", help="verify archived original bytes against their SHA-256")
    ver.add_argument("session", nargs="?")
    exp = sub.add_parser("export", help="restore an original transcript to a new destination")
    exp.add_argument("session")
    exp.add_argument("destination", type=Path)
    sub.add_parser("summary", help="summarize local corpus and evidence state")
    srv = sub.add_parser("serve", help="start the optional local upload interface")
    srv.add_argument("--port", type=int, default=8765)
    return p


def main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.command == "serve":
            from .server import serve
            serve(args.root, args.port)
            return 0
        from .analysis import analyze, import_review
        from .learning import evaluate, evaluations, evidence_template, matrix, proposals, summary
        with Store(args.root.expanduser()) as store:
            if args.command == "init":
                result = {"root": str(store.root.resolve()), "version": __version__, "status": "ready"}
            elif args.command in ("connect", "collect", "sources"):
                from .collect import collect, connections, load_manifest, save_manifest
                if args.command == "sources":
                    result = connections(store)
                else:
                    manifest_path = args.file if args.command == "connect" else args.manifest
                    if manifest_path:
                        if manifest_path.stat().st_size > 8 * 1024 * 1024:
                            raise ValueError("source manifest exceeds 8 MiB")
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    else:
                        manifest = load_manifest(store)
                    if args.command == "connect":
                        saved = save_manifest(store, manifest)
                        result = {"status": "connected", "manifest": str(saved), "sources": connections(store)}
                    else:
                        result = collect(store, manifest, analyze_sessions=not args.no_analyze)
                        emit(result)
                        return 0 if result["coverage"]["complete"] else 1
            elif args.command == "ingest":
                if args.session_id and len(args.paths) != 1:
                    raise ValueError("--session-id requires exactly one input file")
                result = [store.ingest(path, format=args.format, project=args.project, session_id=args.session_id) for path in args.paths]
            elif args.command == "sessions":
                if not 1 <= args.limit <= 10000:
                    raise ValueError("--limit must be between 1 and 10000")
                result = store.list_sessions(limit=args.limit)
            elif args.command == "show":
                result = store.session(args.session)
                if args.events:
                    result["events"] = store.events(args.session)
            elif args.command == "analyze":
                result = analyze(store, args.session)
            elif args.command == "corrections":
                from .corrections import corrections
                result = corrections(store, args.session)
            elif args.command == "metrics":
                from .metrics import metrics
                result = metrics(store, args.session)
            elif args.command == "refresh-metadata":
                result = store.refresh_metadata(args.session)
            elif args.command == "proposals":
                result = proposals(store, args.session)
            elif args.command == "evaluate":
                if args.file.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("evaluation report exceeds 8 MiB")
                result = evaluate(store, json.loads(args.file.read_text(encoding="utf-8")))
            elif args.command == "evaluation-template":
                result = evidence_template(store, args.proposal)
            elif args.command == "evaluations":
                result = evaluations(store, args.proposal)
            elif args.command == "review":
                if args.file.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("retrospective report exceeds 8 MiB")
                result = import_review(store, json.loads(args.file.read_text(encoding="utf-8")))
            elif args.command in ("action", "action-receipt", "action-verify", "actions", "context"):
                from .actions import context, list_actions, record_action, record_receipt, verify_file
                if args.command in ("action", "action-receipt"):
                    if args.file.stat().st_size > 8 * 1024 * 1024:
                        raise ValueError("action document exceeds 8 MiB")
                    record = json.loads(args.file.read_text(encoding="utf-8"))
                    result = record_action(store, record) if args.command == "action" else record_receipt(store, record)
                elif args.command == "action-verify":
                    result = verify_file(store, args.action, args.path, expected_sha256=args.expected_sha256)
                    emit(result)
                    return 0 if result["ok"] else 1
                elif args.command == "actions":
                    result = list_actions(store)
                else:
                    current = {key: getattr(args, key) for key in ("harness", "model", "environment") if getattr(args, key) is not None}
                    result = context(store, args.project, args.task_family, context=current,
                                     limit=args.limit, max_chars=args.max_chars)
                    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                    return 0
            elif args.command == "matrix":
                scope = {key: getattr(args, key) for key in ("project", "harness", "model", "environment", "task_family") if getattr(args, key) is not None}
                result = matrix(store, args.improve, args.protect, scope=scope or None)
            elif args.command == "verify":
                result = store.verify(args.session)
                emit(result)
                return 0 if result["ok"] else 1
            elif args.command == "export":
                store.export_raw(args.session, args.destination)
                result = {"session_id": args.session, "destination": str(args.destination.resolve()), "status": "exported"}
            else:
                result = summary(store)
                result["session_count"] = store.db.execute("SELECT count(*) FROM sessions").fetchone()[0]
            emit(result)
        return 0
    except (ValueError, KeyError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}, ensure_ascii=False), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
