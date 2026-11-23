"""Validate reported paired experiments and maintain scoped, reversible evidence."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math

from .analysis import get_proposal, proposals as _base_proposals, _json

RESOURCES = ("latency_seconds", "tokens", "cost")
QUALITY = ("correctness", "completion")
SCOPE_KEYS = ("project", "harness", "model", "environment", "task_family")
PARAMETER_METRIC = {"latency": "latency_seconds", "tokens": "tokens", "cost": "cost"}


def _schema(store):
    store.db.executescript("""
        CREATE TABLE IF NOT EXISTS traz_evaluations (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL UNIQUE, proposal_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, record TEXT NOT NULL, result TEXT NOT NULL,
            recorded_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS traz_evaluations_proposal ON traz_evaluations(proposal_id);
    """)


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(name + " must be a nonempty string of at most 4096 characters")
    return value


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(name + " must be an object")
    return value


def _time(value, name):
    _text(value, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(name + " must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(name + " must include a timezone")
    return parsed


def _number(value, name, *, unknown=False, quality=False):
    if value is None and unknown:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not _finite(value) or value < 0:
        raise ValueError(name + " must be a finite nonnegative number" + (" or null" if unknown else ""))
    if quality and value > 1:
        raise ValueError(name + " must be between 0 and 1")
    return value


def _finite(value):
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _metrics(value, name, *, overhead=False):
    value = _object(value, name)
    required = RESOURCES if overhead else QUALITY + RESOURCES
    for key in required:
        if key not in value:
            raise ValueError(name + "." + key + " is required (use null for unknown resource values)")
        _number(value[key], name + "." + key, unknown=key in RESOURCES, quality=key in QUALITY)
    return value


def _total(metrics, overhead, key):
    if metrics[key] is None or overhead[key] is None:
        return None
    result = metrics[key] + overhead[key]
    if not _finite(result):
        raise ValueError("Combined resource values must be finite")
    return result


def _known(value):
    return value is not None and str(value).lower() not in {"unknown", "auto", "generic", "text"}


def _validate(record, proposal):
    _object(record, "evaluation")
    if record.get("_template"):
        raise ValueError("This is an unfilled evaluation template, not an experimental result")
    if record.get("schema_version") != "0.1":
        raise ValueError("schema_version must be '0.1'")
    for key in ("evaluation_id", "proposal_id", "change_ref"):
        _text(record.get(key), key)
    scope = _object(record.get("scope"), "scope")
    if set(scope) != set(SCOPE_KEYS):
        raise ValueError("scope must have exactly project, harness, model, environment, task_family")
    for key in SCOPE_KEYS:
        _text(scope[key], "scope." + key)
        if not _known(scope[key]):
            raise ValueError("scope." + key + " must identify the tested configuration")
        expected = proposal["scope"].get(key)
        # Export format is not a runtime harness version. Native 'codex' and
        # 'opencode' can be refined to 'codex@x.y' / 'opencode@x.y'.
        if _known(expected) and scope[key] != expected:
            if key != "harness" or not scope[key].startswith(str(expected) + "@"):
                raise ValueError("scope." + key + " differs from the proposal's known scope")
    verifier = _object(record.get("verifier"), "verifier")
    if verifier.get("kind") != "reported":
        raise ValueError("Only verifier.kind='reported' is supported; importing a claim is not independent verification")
    _text(verifier.get("reference"), "verifier.reference")
    holdout = _object(record.get("holdout"), "holdout")
    _text(holdout.get("reference"), "holdout.reference")
    frozen = _time(holdout.get("frozen_at"), "holdout.frozen_at")
    started = _time(record.get("started_at"), "started_at")
    if frozen > started:
        raise ValueError("The holdout must be frozen before the experiment starts")
    if started > datetime.now(timezone.utc):
        raise ValueError("started_at cannot be in the future")
    discovery = holdout.get("discovery_session_ids")
    if not isinstance(discovery, list) or not discovery:
        raise ValueError("holdout.discovery_session_ids must name the proposal's discovery sessions")
    for item in discovery:
        _text(item, "discovery session ID")
    source_ids = set(proposal["source_task_ids"]) | {proposal["session_id"], proposal["logical_session_id"]}
    if proposal["session_id"] not in discovery and proposal["logical_session_id"] not in discovery:
        raise ValueError("The proposal source session must be listed as discovery evidence")
    task_ids = holdout.get("task_ids")
    if not isinstance(task_ids, list) or not task_ids:
        raise ValueError("holdout.task_ids must be a nonempty list")
    for item in task_ids:
        _text(item, "holdout task ID")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("holdout task IDs must be unique")
    if set(task_ids) & (set(discovery) | source_ids):
        raise ValueError("Holdout tasks must be disjoint from discovery/source tasks")
    primary = record.get("primary_metric")
    if primary not in RESOURCES:
        raise ValueError("primary_metric must be latency_seconds, tokens, or cost")
    expected = PARAMETER_METRIC.get(proposal["contradiction"]["improve"])
    if expected and primary != expected:
        raise ValueError("primary_metric must match the proposal's improving parameter")
    pairs = record.get("pairs")
    if not isinstance(pairs, list) or not pairs or len(pairs) > 10000:
        raise ValueError("pairs must contain between 1 and 10000 paired tasks")
    seen = set()
    totals = []
    for i, pair in enumerate(pairs):
        _object(pair, "pair")
        task_id = _text(pair.get("task_id"), "pair.task_id")
        if task_id in seen:
            raise ValueError("Each holdout task may appear only once per evaluation")
        seen.add(task_id)
        baseline = _metrics(pair.get("baseline"), "baseline")
        candidate = _metrics(pair.get("candidate"), "candidate")
        bo = _metrics(pair.get("baseline_overhead"), "baseline_overhead", overhead=True)
        co = _metrics(pair.get("candidate_overhead"), "candidate_overhead", overhead=True)
        btotal = {key: _total(baseline, bo, key) for key in RESOURCES}
        ctotal = {key: _total(candidate, co, key) for key in RESOURCES}
        if btotal[primary] is None or ctotal[primary] is None:
            raise ValueError("The primary resource metric and its overhead cannot be unknown")
        totals.append({"task_id": task_id, "baseline": btotal, "candidate": ctotal})
    if seen != set(task_ids):
        raise ValueError("Paired task IDs must exactly match the frozen holdout task IDs")
    return totals


def evaluate(store, record):
    """Record a reported result. Does not run tasks or mutate agent instructions."""
    _schema(store)
    _object(record, "evaluation")
    proposal = get_proposal(store, record.get("proposal_id"))
    totals = _validate(record, proposal)
    canonical = _json(record)
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    existing = store.db.execute("SELECT fingerprint,result FROM traz_evaluations WHERE id=?", (record["evaluation_id"],)).fetchone()
    if existing:
        if existing[0] != fingerprint:
            raise ValueError("evaluation_id already exists with different content; append a new experiment ID")
        result = json.loads(existing[1])
        result["duplicate"] = True
        return result
    primary = record["primary_metric"]
    baseline_total = sum(item["baseline"][primary] for item in totals)
    candidate_total = sum(item["candidate"][primary] for item in totals)
    if not _finite(baseline_total) or not _finite(candidate_total):
        raise ValueError("Aggregate metric must be finite")
    regressions = []
    incomplete = []
    for pair, measured in zip(record["pairs"], totals):
        for key in QUALITY:
            if pair["candidate"][key] < pair["baseline"][key]:
                regressions.append({"task_id": pair["task_id"], "metric": key})
            if pair["candidate"][key] != 1:
                incomplete.append({"task_id": pair["task_id"], "metric": key})
        protected = PARAMETER_METRIC.get(proposal["contradiction"]["protect"])
        if protected:
            b, c = measured["baseline"][protected], measured["candidate"][protected]
            if b is None or c is None:
                incomplete.append({"task_id": pair["task_id"], "metric": protected})
            elif c > b:
                regressions.append({"task_id": pair["task_id"], "metric": protected})
    # Some catalogue parameters require separate operational measures. Do not
    # declare them protected merely because correctness happens to be unchanged.
    protected_param = proposal["contradiction"]["protect"]
    if protected_param not in {"correctness", "completion", *PARAMETER_METRIC}:
        incomplete.append({"metric": protected_param, "reason": "No validator for this protected parameter in v0.1"})
    improving_param = proposal["contradiction"]["improve"]
    if improving_param not in PARAMETER_METRIC:
        incomplete.append({"metric": improving_param, "reason": "No improvement validator for this parameter in v0.1"})
    if candidate_total > baseline_total:
        regressions.append({"metric": primary, "reason": "Total including overhead increased"})
    if regressions:
        outcome, state = "regressed", "regressed"
    elif incomplete or candidate_total >= baseline_total:
        outcome, state = "not_supported", "proposed"
    else:
        outcome, state = "supported", "supported_by_reported_evidence"
    now = datetime.now(timezone.utc).isoformat()
    result = {
        "evaluation_id": record["evaluation_id"], "proposal_id": proposal["id"],
        "outcome": outcome, "state": state, "scope": record["scope"],
        "change_ref": record["change_ref"], "evidence_level": "reported",
        "primary_metric": primary,
        "baseline_total": baseline_total, "candidate_total": candidate_total,
        "relative_improvement": (baseline_total - candidate_total) / baseline_total if baseline_total else None,
        "task_count": len(totals), "totals": totals,
        "regressions": regressions, "unmet_requirements": incomplete,
        "recorded_at": now, "duplicate": False,
        "limitation": "Imported measurements and holdout provenance are reported claims. This validates arithmetic and consistency, not task execution, independence, or generalization.",
    }
    cursor = store.db.execute(
        "INSERT OR IGNORE INTO traz_evaluations(id,proposal_id,fingerprint,record,result,recorded_at) VALUES(?,?,?,?,?,?)",
        (record["evaluation_id"], proposal["id"], fingerprint, canonical, _json(result), now),
    )
    store.db.commit()
    if not cursor.rowcount:
        saved = store.db.execute("SELECT fingerprint,result FROM traz_evaluations WHERE id=?", (record["evaluation_id"],)).fetchone()
        if saved[0] != fingerprint:
            raise ValueError("evaluation_id already exists with different content; append a new experiment ID")
        result = json.loads(saved[1])
        result["duplicate"] = True
    return result


def evaluations(store, proposal_id=None):
    _schema(store)
    if proposal_id:
        rows = store.db.execute("SELECT record,result FROM traz_evaluations WHERE proposal_id=? ORDER BY sequence", (proposal_id,))
    else:
        rows = store.db.execute("SELECT record,result FROM traz_evaluations ORDER BY sequence")
    return [{"record": json.loads(row[0]), "result": json.loads(row[1])} for row in rows]


def _evidence(store, scope=None):
    if scope is not None and (not isinstance(scope, dict) or set(scope) != set(SCOPE_KEYS)):
        raise ValueError("Evidence scope requires exactly project, harness, model, environment, task_family")
    grouped = defaultdict(list)
    for item in evaluations(store):
        record = item["record"]
        if scope is not None and record["scope"] != scope:
            continue
        grouped[(record["proposal_id"], _json(record["scope"]), record["change_ref"])].append(item)
    evidence = []
    for (proposal_id, scoped, change_ref), items in grouped.items():
        outcomes = [item["result"]["outcome"] for item in items]
        state = "regressed" if "regressed" in outcomes else "supported_by_reported_evidence" if "supported" in outcomes else "proposed"
        proposal = get_proposal(store, proposal_id)
        evidence.append({
            "proposal_id": proposal_id, "scope": json.loads(scoped), "change_ref": change_ref,
            "state": state, "evidence_level": "reported", "contradiction": proposal["contradiction"],
            "principles": proposal["principles"],
            "evaluation_ids": [item["record"]["evaluation_id"] for item in items],
            "unique_tasks": sorted({pair["task_id"] for item in items for pair in item["record"]["pairs"]}),
            "recommendation": "candidate_for_reuse_in_exact_scope" if scope is not None and state == "supported_by_reported_evidence" else "do_not_promote" if state == "regressed" else "inspect_scoped_evidence",
            "limitation": "Any reported regression revokes support for this change in this exact scope. Repeated task IDs do not count as new tasks. A changed patch needs a different change_ref.",
        })
    return evidence


def matrix(store, improve=None, protect=None, *, scope=None):
    path = Path(__file__).with_name("data") / "matrix.json"
    catalog = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"schema_version": "0.1", "status": "expert_hypotheses", "cells": []}
    matches = lambda cell: (improve is None or cell["improve"] == improve) and (protect is None or cell["protect"] == protect)
    cells = [cell for cell in catalog["cells"] if matches(cell)]
    evidence = [item for item in _evidence(store, scope) if matches(item["contradiction"])]
    return {
        "schema_version": "0.1", "status": "experimental", "cells": cells,
        "reported_evidence": evidence, "scope_filter": scope,
        "global_support": False,
        "limitation": "Seed cells are expert hypotheses. Evidence is configuration-specific and reported. No scope filter means an inventory, not a globally supported recommendation.",
    }


def proposals(store, session_id=None):
    """Expose scoped outcomes without claiming any universal proposal status."""
    items = _base_proposals(store, session_id)
    evidence = _evidence(store)
    for item in items:
        item["scoped_evidence"] = [entry for entry in evidence if entry["proposal_id"] == item["id"]]
    return items


def evidence_template(store, proposal_id):
    """An intentionally non-importable form; only real measured results are evidence."""
    proposal = get_proposal(store, proposal_id)
    return {
        "_template": True,
        "_instructions": "Replace every placeholder and unknown required measurement with real observations. Freeze the task manifest before running paired tasks. Remove _template only after recording results. Do not copy synthetic fixture results into a real corpus.",
        "schema_version": "0.1", "evaluation_id": "REPLACE_WITH_UNIQUE_EXPERIMENT_ID",
        "proposal_id": proposal_id,
        "scope": {key: value if _known(value) else "REPLACE_WITH_TESTED_" + key.upper() for key, value in proposal["scope"].items()},
        "change_ref": "REPLACE_WITH_PATCH_OR_CONFIGURATION_VERSION",
        "verifier": {"kind": "reported", "reference": "REPLACE_WITH_ACCEPTANCE_REPORT_REFERENCE"},
        "holdout": {
            "reference": "REPLACE_WITH_FROZEN_MANIFEST_REFERENCE",
            "frozen_at": "REPLACE_WITH_ISO_TIMESTAMP_WITH_TIMEZONE",
            "discovery_session_ids": [proposal["session_id"], proposal["logical_session_id"]],
            "task_ids": ["REPLACE_WITH_HOLDOUT_TASK_ID"],
        },
        "started_at": "REPLACE_WITH_ISO_TIMESTAMP_WITH_TIMEZONE",
        "primary_metric": PARAMETER_METRIC.get(proposal["contradiction"]["improve"], "latency_seconds"),
        "pairs": [{
            "task_id": "REPLACE_WITH_HOLDOUT_TASK_ID",
            "baseline": {key: None for key in QUALITY + RESOURCES},
            "candidate": {key: None for key in QUALITY + RESOURCES},
            "baseline_overhead": {key: None for key in RESOURCES},
            "candidate_overhead": {key: None for key in RESOURCES},
        }],
    }


def summary(store):
    _schema(store)
    observed = _base_proposals(store)
    evals = evaluations(store)
    evidence = _evidence(store)
    return {
        "proposal_count": len(observed), "evaluation_count": len(evals),
        "reported_support_scopes": sum(e["state"] == "supported_by_reported_evidence" for e in evidence),
        "regressed_scopes": sum(e["state"] == "regressed" for e in evidence),
        "independently_verified_count": 0,
        "limitation": "v0.1 validates imported paired reports. It does not execute or independently verify experiments.",
    }
