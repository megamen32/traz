"""Immutable interventions and bounded advice for future tasks.

Artifact integrity, reported implementation receipts and measured efficacy are
different facts. This module never runs artifacts or resumes source sessions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .analysis import get_proposal
from .learning import _evidence

KINDS = {"code", "check", "process", "skill", "guidance"}
RECEIPT_KINDS = {"materialized", "local_check", "connected", "used", "retired"}
SCOPE_KEYS = {"project", "task_family", "harness", "model", "environment"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CHUNK = 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, name, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise ValueError(f"{name} must be a nonempty string of at most {limit} characters")
    return value


def _hash(value):
    value = _text(value, "sha256", 64).lower()
    if not SHA256.fullmatch(value):
        raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
    return value


def _schema(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS traz_actions (
            id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, change_ref TEXT NOT NULL,
            body TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(proposal_id, change_ref)
        );
        CREATE TABLE IF NOT EXISTS traz_action_receipts (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
            action_id TEXT NOT NULL REFERENCES traz_actions(id),
            body TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS traz_action_receipts_action ON traz_action_receipts(action_id,sequence);
    """)


def _action(store, action_id):
    _schema(store)
    row = store.db.execute("SELECT body,created_at FROM traz_actions WHERE id=?", (action_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown action: " + str(action_id))
    return {**json.loads(row[0]), "action_id": action_id, "created_at": row[1]}


def _receipts(store, action_id):
    return [{**json.loads(row[0]), "recorded_at": row[1]} for row in store.db.execute(
        "SELECT body,created_at FROM traz_action_receipts WHERE action_id=? ORDER BY sequence", (action_id,))]


def _append_receipt(store, body):
    canonical = _json(body)
    with store.db:
        cursor = store.db.execute("INSERT OR IGNORE INTO traz_action_receipts(id,action_id,body,created_at) VALUES(?,?,?,?)",
                                  (body["receipt_id"], body["action_id"], canonical, _now()))
        row = store.db.execute("SELECT body,created_at FROM traz_action_receipts WHERE id=?", (body["receipt_id"],)).fetchone()
        if row[0] != canonical:
            raise ValueError("receipt_id already exists with different content")
    return {**body, "recorded_at": row[1], "duplicate": not bool(cursor.rowcount)}


def _view(store, action, evidence=None):
    receipts = _receipts(store, action["action_id"])
    observed = [receipt for receipt in receipts
                if receipt["kind"] == "artifact_integrity" and receipt["evidence_level"] == "observed"]
    implementation = {
        "planned": True,
        "reported_kinds": sorted({r["kind"] for r in receipts if r["evidence_level"] == "reported"}),
        "retired": any(r["kind"] == "retired" for r in receipts),
        "latest_integrity": observed[-1] if observed else None,
        "receipts": receipts,
        "limitation": "Observed file integrity proves bytes only. Test, connection and use claims remain reported.",
    }
    scoped = [e for e in (_evidence(store) if evidence is None else evidence)
              if e["proposal_id"] == action["proposal_id"] and e["change_ref"] == action["change_ref"]]
    return {**action, "implementation": implementation,
            "efficacy": {"status": "unknown", "scoped_reported_evidence": scoped},
            "mandatory": False}


def record_action(store, record: dict) -> dict:
    """Register one immutable revision; a changed revision needs a new change_ref."""
    _schema(store)
    fields = {"schema_version", "proposal_id", "change_ref", "owner", "artifact",
              "applicability", "instruction", "trigger", "retirement"}
    if not isinstance(record, dict) or set(record) != fields or record.get("schema_version") != "0.1":
        raise ValueError("Action requires schema_version 0.1 and exactly " + ", ".join(sorted(fields)))
    proposal = get_proposal(store, record["proposal_id"])
    artifact = record["artifact"]
    if not isinstance(artifact, dict) or set(artifact) != {"kind", "locator", "sha256"}:
        raise ValueError("artifact requires exactly kind, locator, sha256")
    if not isinstance(artifact["kind"], str) or artifact["kind"] not in KINDS:
        raise ValueError("Unknown artifact kind")
    applicability = record["applicability"]
    if not isinstance(applicability, dict) or not {"project", "task_family"} <= set(applicability) or set(applicability) - SCOPE_KEYS:
        raise ValueError("applicability requires project and task_family, with optional harness, model and environment")
    for key, value in applicability.items():
        _text(value, "applicability." + key, 200)
        if value.strip().lower() in {"*", "unknown", "auto"}:
            raise ValueError("Applicability must name exact declared values; wildcards and unknown are not constraints")
    source_project = proposal["scope"].get("project")
    if source_project and source_project != "unknown" and applicability["project"] != source_project:
        raise ValueError("Applicability project differs from the proposal's project; source constraints cannot be widened silently")
    body = {
        "schema_version": "0.1", "proposal_id": proposal["id"],
        "change_ref": _text(record["change_ref"], "change_ref", 1000),
        "owner": _text(record["owner"], "owner", 300),
        "artifact": {"kind": artifact["kind"], "locator": _text(artifact["locator"], "artifact.locator", 2048),
                     "sha256": _hash(artifact["sha256"])},
        "applicability": dict(applicability),
        "instruction": _text(record["instruction"], "instruction", 1600),
        "trigger": _text(record["trigger"], "trigger", 600),
        "retirement": _text(record["retirement"], "retirement", 500),
        "source": {
            "proposal_id": proposal["id"], "session_id": proposal["session_id"],
            "logical_session_id": proposal["logical_session_id"],
            "source_event_ids": proposal.get("source_event_ids", []),
            "outcome_event_ids": proposal.get("outcome_event_ids", []),
            "evidence_scope": proposal["scope"],
            "analysis_version": proposal["analysis_version"],
            "cause_status": proposal.get("cause_status", "unestablished"),
        },
    }
    canonical = _json(body)
    action_id = "a_" + hashlib.sha256(canonical.encode()).hexdigest()
    with store.db:
        cursor = store.db.execute("INSERT OR IGNORE INTO traz_actions(id,proposal_id,change_ref,body,created_at) VALUES(?,?,?,?,?)",
                                  (action_id, proposal["id"], body["change_ref"], canonical, _now()))
        saved = store.db.execute("SELECT id,body FROM traz_actions WHERE proposal_id=? AND change_ref=?",
                                 (proposal["id"], body["change_ref"])).fetchone()
        if saved[0] != action_id or saved[1] != canonical:
            raise ValueError("change_ref already identifies different immutable contents; use a new change_ref")
    result = _view(store, _action(store, action_id))
    result["duplicate"] = not bool(cursor.rowcount)
    return result


def record_receipt(store, record: dict) -> dict:
    """Import a reported receipt. Input cannot claim observed verification."""
    _schema(store)
    required = {"schema_version", "receipt_id", "action_id", "kind", "reference"}
    if not isinstance(record, dict) or not required <= set(record) or set(record) - (required | {"details"}) or record.get("schema_version") != "0.1":
        raise ValueError("Receipt requires schema_version 0.1, receipt_id, action_id, kind, reference and optional details")
    action = _action(store, record["action_id"])
    kind = record["kind"]
    if not isinstance(kind, str) or kind not in RECEIPT_KINDS:
        raise ValueError("Imported receipts support materialized, local_check, connected, used or retired; they cannot assert observed integrity")
    details = record.get("details", "")
    if not isinstance(details, str) or len(details) > 2000 or "\x00" in details:
        raise ValueError("details must be a string of at most 2000 characters")
    body = {
        "schema_version": "0.1", "receipt_id": _text(record["receipt_id"], "receipt_id", 200),
        "action_id": action["action_id"], "kind": kind,
        "reference": _text(record["reference"], "reference", 2048),
        "details": details, "evidence_level": "reported",
    }
    return _append_receipt(store, body)


def list_actions(store) -> list[dict]:
    _schema(store)
    evidence = _evidence(store)
    return [_view(store, {**json.loads(row[1]), "action_id": row[0], "created_at": row[2]}, evidence)
            for row in store.db.execute("SELECT id,body,created_at FROM traz_actions ORDER BY created_at,id")]


def _signature(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def _inspect_file(path, expected):
    """Read only a caller-bound regular file; do not evaluate its content."""
    result = {"path": str(path), "expected_sha256": expected, "observed_sha256": None,
              "signature": None, "ok": False, "outcome": "unavailable"}
    try:
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", buffering=0) as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Artifact must be a regular local file")
            digest = hashlib.sha256()
            remaining = before.st_size
            while remaining:
                block = stream.read(min(CHUNK, remaining))
                if not block:
                    result.update(outcome="changed", signature=_signature(before))
                    return result
                digest.update(block)
                remaining -= len(block)
            # Some virtual regular files report size zero despite yielding bytes.
            # Growing or virtual files must not verify a mere prefix as complete.
            if stream.read(1):
                result.update(outcome="changed", signature=_signature(before))
                return result
            after = os.fstat(stream.fileno())
            current = Path(path).stat()
        result.update(observed_sha256=digest.hexdigest(), signature=_signature(after))
        if _signature(before) != _signature(after) or _signature(after) != _signature(current):
            result["outcome"] = "changed"
        else:
            result["ok"] = result["observed_sha256"] == expected
            result["outcome"] = "matched" if result["ok"] else "mismatch"
    except (OSError, ValueError) as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    return result


def verify_file(store, action_id, path, *, expected_sha256=None) -> dict:
    """Observe an explicitly supplied file's bytes, never tests or efficacy."""
    action = _action(store, action_id)
    expected = action["artifact"]["sha256"]
    if expected_sha256 is not None and _hash(expected_sha256) != expected:
        raise ValueError("Expected hash differs from the immutable action revision")
    if not isinstance(path, (str, Path)) or not str(path).strip() or "://" in str(path):
        raise ValueError("Pass an explicit local artifact path")
    path = Path(os.path.abspath(Path(path).expanduser()))
    observed = _inspect_file(path, expected)
    body = {
        "schema_version": "0.1", "action_id": action_id, "kind": "artifact_integrity",
        "reference": "explicit_local_file", "evidence_level": "observed",
        "verification_scope": "file_bytes_only", **observed,
    }
    previous = [r for r in _receipts(store, action_id)
                if r["kind"] == "artifact_integrity" and r["evidence_level"] == "observed"]
    if previous:
        latest = previous[-1]
        payload = {key: value for key, value in latest.items()
                   if key not in {"receipt_id", "recorded_at", "previous_observation_id"}}
        if payload == body:
            return {**latest, "duplicate": True}
        # A repeated outcome after a different observation is a new event.
        # Only consecutive identical observations are idempotent.
        body["previous_observation_id"] = latest["receipt_id"]
    body["receipt_id"] = "v_" + hashlib.sha256(_json(body).encode()).hexdigest()
    return _append_receipt(store, body)


def context(store, project, task_family, *, context=None, limit=5, max_chars=6000) -> dict:
    """Return bounded advisory cards without executing or relaunching any task."""
    _text(project, "project", 200)
    _text(task_family, "task_family", 200)
    if project.strip() == "*" or task_family.strip() == "*":
        raise ValueError("Context requires an exact project and task family")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5:
        raise ValueError("limit must be between 1 and 5")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 512 <= max_chars <= 6000:
        raise ValueError("max_chars must be between 512 and 6000")
    optional = {} if context is None else context
    if not isinstance(optional, dict) or set(optional) - {"harness", "model", "environment"}:
        raise ValueError("context supports only harness, model and environment")
    for key, value in optional.items():
        _text(value, "context." + key, 200)
    requested = {"project": project, "task_family": task_family, **optional}
    result = {"schema_version": "0.1", "project": project, "task_family": task_family,
              "mandatory": False, "cards": [], "excluded": [], "excluded_count": 0,
              "truncated": False,
              "notice": "Advisory for the current task only. Artifact integrity is not proof of efficacy. Source sessions are provenance, never work to resume."}
    if len(_json(result)) > max_chars:
        raise ValueError("Context scope exceeds the character budget")
    candidates, excluded = [], []
    for action in list_actions(store):
        action_id = action["action_id"]
        declared = action["applicability"]
        if any(requested.get(key) != value for key, value in declared.items()):
            excluded.append({"action_id": action_id, "reason": "scope_mismatch_or_missing_constraint"})
            continue
        implementation = action["implementation"]
        if implementation["retired"]:
            excluded.append({"action_id": action_id, "reason": "retired"})
            continue
        observed = implementation["latest_integrity"]
        if not observed or not observed["ok"]:
            excluded.append({"action_id": action_id, "reason": "no_matching_observed_integrity"})
            continue
        # Only a path independently bound by verify_file can be read here.
        # Imported artifact.locator and reported references never become paths.
        current = _inspect_file(Path(observed["path"]), action["artifact"]["sha256"])
        if not current["ok"]:
            excluded.append({"action_id": action_id, "reason": "artifact_drift_or_unavailable"})
            continue
        efficacy = {"status": "unknown", "evidence_level": "unknown", "evaluation_ids": []}
        known_requested = {key: value for key, value in requested.items()
                           if value.strip().lower() not in {"unknown", "auto", "*"}}
        full_scope = set(known_requested) == SCOPE_KEYS
        compatible_regression = any(
            e["state"] == "regressed" and all(e["scope"].get(key) == value
                                             for key, value in known_requested.items())
            for e in action["efficacy"]["scoped_reported_evidence"])
        if compatible_regression:
            reason = "reported_efficacy_regression" if full_scope else "need_full_scope_to_resolve_regression"
            excluded.append({"action_id": action_id, "reason": reason})
            continue
        if full_scope:
            matching = [e for e in action["efficacy"]["scoped_reported_evidence"] if e["scope"] == requested]
            if matching:
                efficacy = {"status": matching[0]["state"], "evidence_level": "reported",
                            "evaluation_ids": matching[0]["evaluation_ids"][:3]}
        source = action["source"]
        refs = source["source_event_ids"]
        card = {
            "action_id": action_id, "change_ref": action["change_ref"], "owner": action["owner"],
            "artifact": action["artifact"], "applicability": declared,
            "instruction": action["instruction"], "trigger": action["trigger"],
            "retirement": action["retirement"], "mandatory": False,
            "implementation": {"artifact_integrity": "observed_hash_match",
                               "verification_scope": "file_bytes_only",
                               "reported_kinds": implementation["reported_kinds"]},
            "efficacy": efficacy,
            "source": {"proposal_id": action["proposal_id"], "session_id": source["session_id"],
                       "logical_session_id": source["logical_session_id"],
                       "event_ids": refs[:5], "event_count": len(refs),
                       "evidence_scope": source["evidence_scope"]},
        }
        candidates.append(card)
    candidates.sort(key=lambda card: (card["efficacy"]["status"] != "supported_by_reported_evidence", card["action_id"]))
    for card in candidates:
        if len(result["cards"]) >= limit or len(_json({**result, "cards": result["cards"] + [card]})) > max_chars:
            excluded.append({"action_id": card["action_id"], "reason": "context_budget"})
            continue
        result["cards"].append(card)
    result["excluded_count"] = len(excluded)
    for item in excluded:
        if len(_json({**result, "excluded": result["excluded"] + [item]})) <= max_chars:
            result["excluded"].append(item)
        else:
            result["truncated"] = True
    # Counts may add digits after a near-budget card was selected.
    while len(_json(result)) > max_chars and result["excluded"]:
        result["excluded"].pop()
        result["truncated"] = True
    while len(_json(result)) > max_chars and result["cards"]:
        result["cards"].pop()
        result["excluded_count"] += 1
        result["truncated"] = True
    if len(_json(result)) > max_chars:
        result["notice"] = "Advisory only. Artifact integrity is not efficacy."
        result["truncated"] = True
    return result
