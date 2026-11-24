"""Conservative accounting from native Codex records, independent of event IDs.

Cumulative counters are sampled, never added together. Per-response usage provides
a separate check when available. These are reported counts, not billing records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import zlib

from .parsers import parse_file

METRICS_VERSION = "0.1.0"
COUNTERS = ("input_tokens", "cached_input_tokens", "output_tokens",
            "reasoning_output_tokens", "total_tokens")
MAX_REASONS = 50


class Issues:
    def __init__(self):
        self.items = []
        self.count = 0
        self.conflicting = False

    def add(self, code, *, line=None, detail=None, conflicting=False):
        self.count += 1
        self.conflicting = self.conflicting or conflicting
        if len(self.items) < MAX_REASONS:
            item = {"code": code}
            if line is not None:
                item["source_line"] = line
            if detail:
                item["detail"] = detail
            self.items.append(item)


def _identity(value):
    return value if isinstance(value, str) and value.strip() and len(value) <= 4096 else None


def _counts(value):
    if not isinstance(value, dict):
        raise ValueError("Counter set is not an object")
    result = {}
    for field in COUNTERS:
        number = value.get(field)
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise ValueError(field + " must be a nonnegative integer")
        result[field] = number
    if result["cached_input_tokens"] > result["input_tokens"]:
        raise ValueError("Cached input exceeds total input")
    if result["reasoning_output_tokens"] > result["output_tokens"]:
        raise ValueError("Reasoning output exceeds total output")
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        raise ValueError("Total tokens differs from input plus output")
    return result


def _aware_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value is not None else None


def _enriched(counts):
    return {
        **counts,
        "uncached_input_tokens": counts["input_tokens"] - counts["cached_input_tokens"],
        "non_reasoning_output_tokens": counts["output_tokens"] - counts["reasoning_output_tokens"],
    }


def _empty(session):
    return {
        "schema_version": "0.1", "metrics_version": METRICS_VERSION,
        "snapshot_id": session["id"],
        "logical_session_id": session.get("logical_session_id"),
        "source_format": session.get("source_format"),
        "scope": {"status": "unknown", "native_session_ids": [], "thread_ids": [],
                  "usage_session_id_count": 0, "reasons": []},
        "coverage": {"record_count": 0, "raw_complete": False, "parse_status": "not_read",
                     "malformed_records": 0, "parse_warning_count": 0, "parse_warnings": [],
                     "token_measurements_complete": False, "archive_integrity": "not_checked"},
        "tokens": {
            "status": "unknown", "totals": None, "cache_share_of_input": None,
            "observed_reported_totals": None, "observed_cache_share_of_input": None,
            "observed_reporting_scope": "Only successfully parsed accounting records in this native thread snapshot; omitted records and child threads are not included.",
            "unique_response_count": 0, "duplicate_response_count": 0,
            "conflicting_response_count": 0, "cumulative_sample_count": 0,
            "duplicate_cumulative_sample_count": 0, "cumulative_streams": [],
            "cross_check": {"status": "unavailable"}, "reason_count": 0, "reasons": [],
        },
        "timing": {
            "observed_start": None, "observed_end": None, "observed_span_seconds": None,
            "observed_span_status": "unknown", "observed_timestamp_count": 0,
            "missing_timestamps": 0, "invalid_timestamps": 0,
            "recorded_turn_duration_ms": None, "recorded_turn_duration_seconds": None,
            "observed_recorded_turn_duration_ms": None, "observed_recorded_turn_duration_seconds": None,
            "recorded_turn_count": 0, "duplicate_turn_count": 0,
            "recorded_turn_status": "unknown", "active_seconds": None,
            "human_wait_seconds": None, "reason_count": 0, "reasons": [],
        },
        "monetary_cost": None,
        "limitations": [
            "Counts are reported by the native transcript, not verified provider invoices.",
            "Input includes cached input; reasoning tokens are a subset of output. Do not add these subsets twice.",
            "Observed span includes every interval between known record timestamps, including idle time.",
            "Summed recorded turn durations may include tools and waits and may overlap. They are not active model thinking time.",
            "Missing, malformed, reset, contradictory, or mixed-scope accounting cannot support a trusted total.",
        ],
    }


def metrics(store, id: str) -> dict:
    """Return read-only metrics for one immutable archived Codex snapshot."""
    session = store.session(id)
    result = _empty(session)
    if session.get("source_format") != "codex":
        result["tokens"]["reasons"] = [{"code": "unsupported_source_format",
                                        "detail": "Native Codex accounting is required; other exporters remain unknown."}]
        result["tokens"]["reason_count"] = 1
        result["timing"]["reasons"] = [{"code": "unsupported_source_format"}]
        result["timing"]["reason_count"] = 1
        return result
    try:
        integrity = store.verify(session["id"])
    except (OSError, ValueError, EOFError, zlib.error) as exc:
        integrity = {"ok": False, "results": [{"error": type(exc).__name__}]}
    if not integrity["ok"]:
        result["coverage"]["archive_integrity"] = "failed"
        result["tokens"]["reasons"] = [{"code": "archive_integrity_failed"}]
        result["tokens"]["reason_count"] = 1
        result["timing"]["reasons"] = [{"code": "archive_integrity_failed"}]
        result["timing"]["reason_count"] = 1
        return result
    result["coverage"]["archive_integrity"] = "verified"
    encoding = session.get("metadata", {}).get("encoding")
    framing = encoding if encoding in ("json", "jsonl") else "codex"
    parser = parse_file(Path(store.root) / session["raw_path"], framing, compressed=True,
                        source_name=session["source_name"])
    token_issues, time_issues, scope_issues = Issues(), Issues(), Issues()
    native_ids, thread_ids, usage_session_ids = set(), set(), set()
    responses = {}
    response_counter_samples = {}
    response_sum = {field: 0 for field in COUNTERS}
    cumulative = {}
    turn_cumulative = {}
    turns = {}
    first_time = last_time = None
    token_usage_records = token_count_records = task_complete_records = 0
    token_count_updates_without_usage = 0
    invalid_shapes = 0

    def record_counts(value, line, source):
        try:
            return _counts(value)
        except ValueError as exc:
            token_issues.add("invalid_counters", line=line, detail=source + ": " + str(exc))
            return None

    def cumulative_sample(source, counts, line):
        if counts is None:
            return
        previous = cumulative.get(source)
        result["tokens"]["cumulative_sample_count"] += 1
        if previous is not None:
            if counts == previous:
                result["tokens"]["duplicate_cumulative_sample_count"] += 1
            if any(counts[field] < previous[field] for field in COUNTERS):
                token_issues.add("cumulative_counter_decreased", line=line, detail=source, conflicting=True)
        cumulative[source] = counts

    try:
        for record, line in parser.records():
            result["coverage"]["record_count"] += 1
            if not isinstance(record, dict):
                invalid_shapes += 1
                continue
            raw_timestamp = record.get("timestamp")
            timestamp = _aware_time(raw_timestamp)
            if timestamp is not None:
                result["timing"]["observed_timestamp_count"] += 1
                first_time = timestamp if first_time is None else min(first_time, timestamp)
                last_time = timestamp if last_time is None else max(last_time, timestamp)
            elif raw_timestamp is None:
                result["timing"]["missing_timestamps"] += 1
            else:
                result["timing"]["invalid_timestamps"] += 1
            kind = record.get("type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                if kind in ("session_meta", "event_msg", "token_usage_record", "task_complete"):
                    invalid_shapes += 1
                continue
            if kind == "session_meta":
                native = _identity(payload.get("id"))
                if native is None:
                    scope_issues.add("invalid_native_session_id", line=line)
                else:
                    native_ids.add(native)
            if kind == "event_msg" and payload.get("type") == "token_count":
                token_count_records += 1
                info = payload.get("info")
                if info is None:
                    # Rate-limit-only updates may legitimately have no usage.
                    # This supplies no new count and is never treated as zero.
                    token_count_updates_without_usage += 1
                elif not isinstance(info, dict):
                    token_issues.add("invalid_token_count_info", line=line)
                else:
                    cumulative_sample("event_msg.total_token_usage",
                                      record_counts(info.get("total_token_usage"), line, "total_token_usage"), line)
                # last_token_usage repeats one response and is deliberately not added.
            if kind == "token_usage_record":
                token_usage_records += 1
                thread = _identity(payload.get("thread_id"))
                if thread is None:
                    scope_issues.add("invalid_thread_id", line=line)
                else:
                    thread_ids.add(thread)
                # session_id is an exporter/provider namespace, not automatically
                # the native thread namespace. Record its observed diversity only.
                opaque_session = _identity(payload.get("session_id"))
                if opaque_session is not None:
                    usage_session_ids.add(opaque_session)
                usage = record_counts(payload.get("usage"), line, "usage")
                response_id = _identity(payload.get("response_id"))
                turn_id = _identity(payload.get("turn_id"))
                thread_counts = record_counts(payload["thread_token_usage"], line, "thread_token_usage") if "thread_token_usage" in payload else None
                turn_counts = record_counts(payload["turn_token_usage"], line, "turn_token_usage") if "turn_token_usage" in payload else None
                duplicate_measurement = False
                if response_id is None:
                    token_issues.add("missing_response_id", line=line)
                elif usage is not None:
                    signature = (thread, turn_id, tuple(usage[field] for field in COUNTERS))
                    previous = responses.get(response_id)
                    if previous is None:
                        responses[response_id] = signature
                        for field in COUNTERS:
                            response_sum[field] += usage[field]
                    elif previous == signature:
                        result["tokens"]["duplicate_response_count"] += 1
                        duplicate_measurement = response_counter_samples.get(response_id) == (thread_counts, turn_counts)
                    else:
                        result["tokens"]["conflicting_response_count"] += 1
                        token_issues.add("conflicting_response_duplicate", line=line, conflicting=True)
                    response_counter_samples.setdefault(response_id, (thread_counts, turn_counts))
                # An exact replay of a known response's accounting does not
                # represent a new counter reset, even if later responses precede it.
                if "thread_token_usage" in payload and not duplicate_measurement:
                    cumulative_sample("token_usage_record.thread_token_usage",
                                      thread_counts, line)
                if "turn_token_usage" in payload and not duplicate_measurement:
                    if turn_id is None:
                        token_issues.add("missing_turn_id_for_turn_counters", line=line)
                    elif turn_counts is not None:
                        previous = turn_cumulative.get(turn_id)
                        if previous is not None and any(turn_counts[field] < previous[field] for field in COUNTERS):
                            token_issues.add("turn_counter_decreased", line=line, conflicting=True)
                        turn_cumulative[turn_id] = turn_counts
            is_completed = kind == "task_complete" or (kind == "event_msg" and payload.get("type") == "task_complete")
            if is_completed:
                task_complete_records += 1
                turn_id = _identity(payload.get("turn_id"))
                duration = payload.get("duration_ms")
                if turn_id is None:
                    time_issues.add("missing_completed_turn_id", line=line)
                elif isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
                    time_issues.add("invalid_recorded_turn_duration", line=line)
                else:
                    # Stable turn identity and duration define the measurement.
                    # Preserve optional start/end markers in the duplicate signature.
                    signature = (duration, payload.get("started_at"), payload.get("completed_at"))
                    if turn_id not in turns:
                        turns[turn_id] = signature
                    elif turns[turn_id] == signature:
                        result["timing"]["duplicate_turn_count"] += 1
                    else:
                        time_issues.add("conflicting_completed_turn_duplicate", line=line, conflicting=True)
    except (OSError, ValueError, TypeError, RecursionError, EOFError, zlib.error) as exc:
        token_issues.add("raw_read_failed", detail=type(exc).__name__)
        time_issues.add("raw_read_failed", detail=type(exc).__name__)
        result["coverage"]["read_error"] = str(exc)

    raw_complete = parser.metadata.get("parse_status") == "ok" and invalid_shapes == 0 and "read_error" not in result["coverage"]
    result["coverage"].update(
        raw_complete=raw_complete, parse_status=parser.metadata.get("parse_status"),
        malformed_records=parser.metadata.get("malformed_records", 0),
        parse_warning_count=parser.metadata.get("warning_count", 0),
        parse_warnings=parser.metadata.get("warnings", []),
        invalid_record_shapes=invalid_shapes,
        token_usage_records=token_usage_records, token_count_records=token_count_records,
        token_count_updates_without_usage=token_count_updates_without_usage,
        task_complete_records=task_complete_records,
    )
    if not raw_complete:
        token_issues.add("incomplete_raw_coverage")
        time_issues.add("incomplete_raw_coverage")
    if len(native_ids) > 1 or len(thread_ids) > 1:
        scope_issues.add("multiple_native_thread_scopes")
    if native_ids and thread_ids and native_ids != thread_ids:
        scope_issues.add("native_thread_scope_mismatch")
    if not native_ids and not thread_ids:
        scope_issues.add("missing_native_thread_scope")
    scope_known = scope_issues.count == 0
    result["scope"].update(status="single" if scope_known else "unknown",
                           native_session_ids=sorted(native_ids), thread_ids=sorted(thread_ids),
                           usage_session_id_count=len(usage_session_ids),
                           reasons=scope_issues.items, reason_count=scope_issues.count)
    if not scope_known:
        token_issues.add("unknown_native_thread_scope")
        time_issues.add("unknown_native_thread_scope")

    result["tokens"]["unique_response_count"] = len(responses)
    result["tokens"]["cumulative_streams"] = sorted(cumulative)
    final = None
    if cumulative:
        endpoints = list(cumulative.values())
        if any(endpoint != endpoints[0] for endpoint in endpoints[1:]):
            token_issues.add("cumulative_endpoints_disagree", conflicting=True)
        else:
            final = endpoints[0]
    else:
        token_issues.add("no_cumulative_accounting")
    if final is not None and token_usage_records:
        match = response_sum == final
        result["tokens"]["cross_check"] = {
            "status": "matched" if match else "mismatch",
            "unique_responses": len(responses),
            "basis": "sum of usage once per unique response_id compared with final cumulative counters",
        }
        if not match:
            token_issues.add("per_response_sum_disagrees_with_cumulative", conflicting=True)
    elif final is not None:
        result["tokens"]["cross_check"] = {
            "status": "unavailable", "reason": "No per-response token_usage_record observations",
        }
    accounting_consistent = (final is not None and scope_known and not token_issues.conflicting
                             and token_issues.count == int(not raw_complete))
    if accounting_consistent and (raw_complete or result["tokens"]["cross_check"]["status"] == "matched"):
        result["tokens"]["observed_reported_totals"] = _enriched(final)
        result["tokens"]["observed_cache_share_of_input"] = final["cached_input_tokens"] / final["input_tokens"] if final["input_tokens"] else None
    if token_issues.count == 0 and final is not None:
        result["tokens"]["status"] = "reported_consistent" if token_usage_records else "reported_cumulative"
        result["tokens"]["totals"] = _enriched(final)
        result["tokens"]["cache_share_of_input"] = final["cached_input_tokens"] / final["input_tokens"] if final["input_tokens"] else None
        result["coverage"]["token_measurements_complete"] = True
    else:
        result["tokens"]["status"] = "conflicting" if token_issues.conflicting else "unknown"
    result["tokens"].update(reason_count=token_issues.count, reasons=token_issues.items)

    timing = result["timing"]
    timing["observed_start"] = _iso(first_time)
    timing["observed_end"] = _iso(last_time)
    if first_time is not None and last_time is not None:
        timing["observed_span_seconds"] = (last_time - first_time).total_seconds()
        timing["observed_span_status"] = "observed" if raw_complete and not timing["invalid_timestamps"] else "partial"
    if not task_complete_records:
        time_issues.add("no_recorded_completed_turns")
    timing["recorded_turn_count"] = len(turns)
    if turns and time_issues.count == int(not raw_complete) and scope_known:
        observed_milliseconds = sum(turn[0] for turn in turns.values())
        timing["observed_recorded_turn_duration_ms"] = observed_milliseconds
        timing["observed_recorded_turn_duration_seconds"] = observed_milliseconds / 1000
    if turns and time_issues.count == 0:
        milliseconds = sum(turn[0] for turn in turns.values())
        timing["recorded_turn_duration_ms"] = milliseconds
        timing["recorded_turn_duration_seconds"] = milliseconds / 1000
        timing["recorded_turn_status"] = "reported"
    else:
        timing["recorded_turn_status"] = "conflicting" if time_issues.conflicting else "unknown"
    timing.update(reason_count=time_issues.count, reasons=time_issues.items)
    return result
