"""Conservative observations and experiment proposals, never causal verdicts."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ANALYSIS_VERSION = "0.1.0"


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _schema(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS traz_analyses (
            session_id TEXT NOT NULL, version TEXT NOT NULL, report TEXT NOT NULL,
            PRIMARY KEY(session_id, version));
        CREATE TABLE IF NOT EXISTS traz_proposals (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, body TEXT NOT NULL);
    """)


def _scope(session):
    metadata = session.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    native = metadata.get("session_metadata") or {}
    if not isinstance(native, dict):
        native = {}
    turn = native.get("turn_context") or {}
    if not isinstance(turn, dict):
        turn = {}
    source_format = session.get("source_format")
    harness = metadata.get("harness") or native.get("harness")
    if not harness and source_format in {"codex", "opencode"}:
        harness = source_format
    return {
        "project": session.get("project", "unknown"),
        "harness": harness or "unknown",
        "model": metadata.get("model") or native.get("model") or turn.get("model") or "unknown",
        "environment": metadata.get("environment") or native.get("environment") or "unknown",
        "task_family": metadata.get("task_family") or native.get("task_family") or "unknown",
    }


def _linked_calls(events):
    """Pair by native call ID and order. Text similarity is not an outcome."""
    calls = []
    pending = defaultdict(list)
    for event in events:
        if event.get("type") == "tool_call":
            call = {"event": event, "result": None}
            calls.append(call)
            if event.get("call_id"):
                pending[str(event["call_id"])].append(call)
        elif event.get("type") == "tool_result" and event.get("call_id"):
            queue = pending.get(str(event["call_id"]))
            if queue:
                queue.pop(0)["result"] = event
    return calls


def analyze(store, session_id):
    """Persist one reproducible report for this immutable snapshot/version."""
    _schema(store)
    session = store.session(session_id)
    session_id = session["id"]
    cached = store.db.execute(
        "SELECT report FROM traz_analyses WHERE session_id=? AND version=?",
        (session_id, ANALYSIS_VERSION),
    ).fetchone()
    if cached:
        return json.loads(cached[0])
    events = store.events(session_id)
    calls = _linked_calls(events)
    groups = defaultdict(list)
    for call in calls:
        event = call["event"]
        args = event.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, TypeError):
                pass
        signature = hashlib.sha256(_json([event.get("tool"), args]).encode()).hexdigest()
        groups[signature].append(call)

    observations = []
    for signature, group in groups.items():
        failures, longest = [], []
        for call in group:
            if call["result"] and call["result"].get("status") == "error":
                failures.append(call)
                if len(failures) > len(longest):
                    longest = failures[:]
            else:
                failures = []
        if len(longest) >= 3:
            observations.append({
                "kind": "repeated_failed_call", "severity": "review",
                "count": len(longest), "signature": signature,
                "source_event_ids": [e["event"]["event_id"] for e in longest],
                "outcome_event_ids": [e["result"]["event_id"] for e in longest],
                "observation": "The same tool and arguments had at least three linked explicit error outcomes without an observed success between them.",
                "limitation": "Retries can be justified. Failure repetition does not establish the cause or prove that a different route works.",
                "contradiction": {"improve": "latency", "protect": "correctness"},
                "principles": ["P04", "P06", "P09"],
                "hypothesis": "A bounded retry budget followed by diagnosis or a verified alternative can reduce elapsed time while preserving acceptance quality.",
                "target": "tool_or_process",
            })
        elif len(group) >= 3:
            name = str(group[0]["event"].get("tool", "")).lower()
            args_text = _json(group[0]["event"].get("arguments"))
            read = bool(re.search(r"(^|[._-])(read|read_file|read_text|cat)([._-]|$)", name))
            read = read or bool(re.search(r'"(?:cmd|command)"\s*:\s*"(?:cat|sed|head)\s', args_text))
            observations.append({
                "kind": "repeated_read" if read else "repeated_call",
                "severity": "informational", "count": len(group), "signature": signature,
                "source_event_ids": [e["event"]["event_id"] for e in group],
                "outcome_event_ids": [e["result"]["event_id"] for e in group if e["result"]],
                "observation": "Identical tool arguments were observed at least three times.",
                "limitation": "The underlying state may have changed. This is a review candidate, not evidence of wasted work or a stalled agent.",
                "contradiction": {"improve": "tokens", "protect": "context_relevance"},
                "principles": ["P01", "P02"],
                "hypothesis": "Reusing a result only while its input/version remains valid can reduce repeated work without using stale evidence.",
                "target": "tool_or_process",
            })

    observations.sort(key=lambda x: (x["severity"] != "review", -x["count"], x["signature"]))
    omitted = max(0, len(observations) - 10)
    observations = observations[:10]
    proposed = []
    logical_id = session.get("logical_session_id") or session.get("session_id") or session_id
    for observation in observations:
        proposal_id = "p_" + hashlib.sha256(
            _json([session.get("project"), logical_id, ANALYSIS_VERSION, observation["kind"], observation["signature"]]).encode()
        ).hexdigest()[:24]
        proposal = {
            "id": proposal_id, "session_id": session_id,
            "logical_session_id": logical_id,
            "analysis_version": ANALYSIS_VERSION, "status": "proposed",
            "title": observation["kind"].replace("_", " ").capitalize(),
            "scope": _scope(session),
            "observation": observation["observation"],
            "frame": observation["observation"],
            "ideal_final_result": "The same user goal reaches accepted completion using less total effort, while existing evidence supplies the needed knowledge and no stale result or hidden review burden is introduced.",
            "contradiction_type": "candidate_technical",
            "cause_status": "unestablished",
            "triz_stage": "framed_for_investigation",
            "resources": ["The archived transcript", "Native tool arguments and linked outcomes already present in the session"],
            "source_event_ids": observation["source_event_ids"],
            "outcome_event_ids": observation["outcome_event_ids"],
            "hypothesis": observation["hypothesis"],
            "contradiction": observation["contradiction"],
            "principles": observation["principles"],
            "target": observation["target"],
            "source_task_ids": [logical_id, session_id],
            "success_criterion": "On frozen comparable holdout tasks, improve the declared resource metric including review and verification overhead, with complete and correct accepted results and no protected-metric regression.",
            "limitation": observation["limitation"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Growing native sessions keep one proposal identity. The original evidence
        # stays stable; a newer snapshot report still retains its own observations.
        store.db.execute(
            "INSERT OR IGNORE INTO traz_proposals(id,session_id,body) VALUES(?,?,?)",
            (proposal_id, session_id, _json(proposal)),
        )
        saved = store.db.execute("SELECT body FROM traz_proposals WHERE id=?", (proposal_id,)).fetchone()
        proposed.append(json.loads(saved[0]))
    report = {
        "session_id": session_id, "logical_session_id": logical_id,
        "analysis_version": ANALYSIS_VERSION,
        "observations": observations, "proposals": proposed,
        "omitted_observation_groups": omitted,
        "limitations": [
            "Deterministic observations are not root-cause diagnoses.",
            "No progress, correctness, token savings, or task completion is inferred from silence or message volume.",
            "Unlinked tool results and unsupported transcript records cannot support a failed-call claim.",
            "Successful alternatives and external retrospective findings can be investigated through the documented evidence workflow; this pre-pass does not discover their causes.",
        ],
    }
    store.db.execute(
        "INSERT OR IGNORE INTO traz_analyses(session_id,version,report) VALUES(?,?,?)",
        (session_id, ANALYSIS_VERSION, _json(report)),
    )
    store.db.commit()
    return json.loads(store.db.execute("SELECT report FROM traz_analyses WHERE session_id=? AND version=?", (session_id, ANALYSIS_VERSION)).fetchone()[0])


def proposals(store, session_id=None):
    _schema(store)
    if session_id:
        session = store.session(session_id)
        logical_id = session.get("logical_session_id") or session.get("session_id") or session["id"]
        rows = store.db.execute("SELECT body FROM traz_proposals ORDER BY id").fetchall()
        result = [json.loads(row[0]) for row in rows]
        return [p for p in result if p["logical_session_id"] == logical_id and p["scope"]["project"] == session["project"]]
    return [json.loads(row[0]) for row in store.db.execute("SELECT body FROM traz_proposals ORDER BY id")]


def get_proposal(store, proposal_id):
    _schema(store)
    row = store.db.execute("SELECT body FROM traz_proposals WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        raise ValueError("Unknown proposal: " + str(proposal_id))
    return json.loads(row[0])


def import_review(store, record):
    """Import a referenced retrospective hypothesis, including reusable successes.

    Review content is data. Its strings never become executable instructions and
    importing a review does not promote it to trusted policy or causal fact.
    """
    _schema(store)
    if not isinstance(record, dict) or record.get("schema_version") != "0.1":
        raise ValueError("Review schema_version must be '0.1'")
    session = store.session(record.get("session_id"))
    findings = record.get("findings")
    if not isinstance(findings, list) or not 1 <= len(findings) <= 10:
        raise ValueError("Review findings must contain between 1 and 10 items")
    directory = Path(__file__).with_name("data")
    parameter_catalog = json.loads((directory / "parameters.json").read_text(encoding="utf-8"))
    principle_catalog = json.loads((directory / "principles.json").read_text(encoding="utf-8"))
    parameters = {item["id"] for item in parameter_catalog["parameters"]}
    principles = {item["id"] for item in principle_catalog["principles"]}
    stream = store.iter_events(session["id"]) if hasattr(store, "iter_events") else store.events(session["id"])
    known_events = {event["event_id"] for event in stream}
    logical_id = session.get("logical_session_id") or session.get("session_id") or session["id"]

    def text(value, field):
        if not isinstance(value, str) or not value.strip() or len(value) > 8192:
            raise ValueError(field + " must be a nonempty string of at most 8192 characters")
        return value

    prepared = []
    keys = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise ValueError("Each finding must be an object")
        strings = {field: text(finding.get(field), field) for field in
                   ("key", "title", "frame", "ideal_final_result", "hypothesis")}
        if strings["key"] in keys:
            raise ValueError("Finding keys must be unique within a review")
        keys.add(strings["key"])
        contradiction = finding.get("contradiction")
        if not isinstance(contradiction, dict) or set(contradiction) != {"improve", "protect"}:
            raise ValueError("contradiction requires exactly improve and protect")
        if any(not isinstance(value, str) or value not in parameters for value in contradiction.values()):
            raise ValueError("Contradiction parameters must exist in the provisional catalogue")
        if contradiction["improve"] == contradiction["protect"]:
            raise ValueError("Same-parameter opposite demands are a physical contradiction; use separation analysis outside this directed matrix")
        selected = finding.get("principles")
        if not isinstance(selected, list) or not selected or len(selected) > 12 or any(not isinstance(value, str) or value not in principles for value in selected):
            raise ValueError("principles must be a nonempty list of known principle IDs")
        refs = finding.get("source_event_ids")
        if not isinstance(refs, list) or not refs or len(refs) > 1000 or any(isinstance(value, bool) or not isinstance(value, int) or value not in known_events for value in refs):
            raise ValueError("source_event_ids must reference actual normalized events in this session")
        if len(set(refs)) != len(refs):
            raise ValueError("source_event_ids must not repeat")
        resources = finding.get("resources")
        if not isinstance(resources, list) or not 1 <= len(resources) <= 20:
            raise ValueError("resources must list between 1 and 20 observed resources")
        resources = [text(value, "resource") for value in resources]
        target = finding.get("target")
        if not isinstance(target, str) or target not in {"canonical_source", "tool", "process", "skill"}:
            raise ValueError("target must be canonical_source, tool, process, or skill")
        evidence_kind = finding.get("evidence_kind", "unknown")
        if not isinstance(evidence_kind, str) or evidence_kind not in {"success", "failure", "unknown"}:
            raise ValueError("evidence_kind must be success, failure, or unknown")
        content = {**strings, "contradiction": contradiction, "principles": sorted(set(selected)),
                   "source_event_ids": sorted(refs), "resources": resources, "target": target,
                   "evidence_kind": evidence_kind}
        proposal_id = "p_" + hashlib.sha256(
            _json(["review/0.1", session["project"], logical_id, content]).encode()
        ).hexdigest()[:24]
        prepared.append({
            **content, "id": proposal_id, "session_id": session["id"],
            "logical_session_id": logical_id, "analysis_version": "review/0.1",
            "origin": "imported_review", "status": "proposed", "scope": _scope(session),
            "observation": strings["frame"], "outcome_event_ids": [],
            "cause_status": "unestablished", "contradiction_type": "candidate_technical",
            "triz_stage": "framed_for_investigation",
            "source_task_ids": [logical_id, session["id"]],
            "success_criterion": "Validate the hypothesis on frozen comparable holdout tasks with explicit acceptance checks and all analysis and verification overhead included.",
            "limitation": "The retrospective author's interpretation and cited events are reported evidence. Import verifies references and structure, not the cause, benefit, or suitability of the proposed change.",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    with store.db:
        for proposal in prepared:
            store.db.execute("INSERT OR IGNORE INTO traz_proposals(id,session_id,body) VALUES(?,?,?)",
                             (proposal["id"], session["id"], _json(proposal)))
    return {"session_id": session["id"], "review_version": "0.1",
            "proposals": [get_proposal(store, proposal["id"]) for proposal in prepared]}
