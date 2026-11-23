"""Conservative transcript normalization. Original bytes remain in the corpus.

JSONL is read incrementally. Oversized or malformed records are reported rather
than silently treated as successful tool calls. This module never executes input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import re
from typing import Any, Iterator

MAX_RECORD_BYTES = 2 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_WARNINGS = 50
FORMATS = ("auto", "jsonl", "json", "codex", "opencode", "normalized", "generic", "text")


def _invalid_constant(value: str):
    raise ValueError(f"Non-finite number {value} is not valid transcript JSON")


def _loads(value):
    return json.loads(value, parse_constant=_invalid_constant)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            _text(item.get("text", item.get("content", "")))
            if isinstance(item, dict) else _text(item)
            for item in value
        )
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _timestamp(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            if abs(value) > 100_000_000_000:
                value /= 1000
            return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")
        except (OverflowError, ValueError, OSError):
            return None
    return str(value)


def _arguments(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return _loads(value)
        except (ValueError, RecursionError):
            pass
    return value if value is not None else {}


def _status(value: Any, content: Any = None) -> str:
    if value in ("error", "failed", "failure"):
        return "error"
    if isinstance(content, dict):
        # A provider's explicit error flag wins over a conflicting zero exit
        # code. Never turn contradictory outcome evidence into success.
        if content.get("isError") is True:
            return "error"
        code = content.get("exit_code")
        if isinstance(code, int) and not isinstance(code, bool):
            return "success" if code == 0 else "error"
    if isinstance(content, str):
        # Codex's shell transcript envelopes include explicit process outcome.
        try:
            structured = _loads(content) if content.lstrip().startswith("{") else None
        except (ValueError, RecursionError):
            structured = None
        if isinstance(structured, dict):
            status = _status(None, structured)
            if status != "unknown":
                return status
        header = content.split("Output:\n", 1)[0]
        match = re.search(r"(?m)^(?:Process exited with code|Exit code:)\s*(-?\d+)\s*$", header)
        if match:
            return "success" if int(match.group(1)) == 0 else "error"
    if value in ("success", "completed", "succeeded"):
        return "success"
    return "unknown"


@dataclass
class ParsedTranscript:
    path: Path
    requested_format: str = "auto"
    compressed: bool = False
    source_name: str | None = None
    metadata: dict = field(default_factory=lambda: {
        "source_format": "unknown", "parse_status": "ok", "warnings": [],
        "warning_count": 0, "malformed_records": 0, "skipped_records": 0,
        "native_session_id": None, "session_metadata": {},
    })

    def _open(self):
        return gzip.open(self.path, "rb") if self.compressed else self.path.open("rb")

    def _warn(self, message: str, *, line: int | None = None, malformed: bool = False):
        self.metadata["warning_count"] += 1
        if malformed:
            self.metadata["malformed_records"] += 1
        self.metadata["parse_status"] = "partial"
        if len(self.metadata["warnings"]) < MAX_WARNINGS:
            prefix = f"line {line}: " if line is not None else ""
            self.metadata["warnings"].append(prefix + message)

    def _track_model(self, model: Any):
        if not isinstance(model, str) or not model.strip():
            return
        native = self.metadata["session_metadata"]
        observed = native.setdefault("models_seen", [])
        if not isinstance(observed, list):
            observed = native["models_seen"] = []
        if model not in observed:
            observed.append(model)
        scoped = observed[0] if len(observed) == 1 else "unknown"
        native["model"] = scoped
        context = native.get("turn_context")
        if isinstance(context, dict):
            context["model"] = scoped

    def _records(self) -> Iterator[tuple[Any, int | None]]:
        requested = self.requested_format
        if requested not in FORMATS:
            raise ValueError(f"Unsupported format {requested!r}; choose one of {FORMATS}")
        name = (self.source_name or self.path.name).lower()
        with self._open() as stream:
            first = stream.read(8192)
        if requested in ("auto", "normalized", "generic"):
            stripped = first.lstrip(b"\xef\xbb\xbf \t\r\n")
            if name.endswith((".jsonl", ".ndjson")):
                encoding = "jsonl"
            elif name.endswith(".json") or stripped.startswith(b"["):
                encoding = "json"
            elif stripped.startswith(b"{"):
                # A complete first JSON line followed by another record is JSONL.
                line = first.split(b"\n", 1)[0]
                try:
                    root = _loads(line)
                    encoding = "json" if isinstance(root, dict) and any(k in root for k in ("events", "messages")) else "jsonl"
                except (ValueError, UnicodeDecodeError, RecursionError):
                    encoding = "json"
            else:
                encoding = "text"
        elif requested in ("codex", "jsonl"):
            encoding = "jsonl"
        elif requested in ("json", "opencode"):
            encoding = "json"
        else:
            encoding = "text"
        self.metadata["encoding"] = encoding
        self.metadata["source_format"] = requested if requested not in ("auto", "normalized", "generic") else encoding

        if encoding == "text":
            with self._open() as stream:
                content = stream.read(MAX_RECORD_BYTES + 1)
            if len(content) > MAX_RECORD_BYTES:
                self._warn("Text preview truncated at 2 MiB; full original is archived")
                content = content[:MAX_RECORD_BYTES]
            self.metadata["source_format"] = "text"
            self._warn("Unstructured text: no tool or outcome facts inferred")
            yield {"type": "message", "role": "unknown", "content": content.decode("utf-8", errors="replace")}, None
            return

        if encoding == "json":
            with self._open() as stream:
                content = stream.read(MAX_JSON_BYTES + 1)
            if len(content) > MAX_JSON_BYTES:
                self._warn("JSON document exceeds 64 MiB parse limit; original is archived. Export JSONL for incremental import.")
                self.metadata["parse_status"] = "unparsed"
                return
            try:
                obj = _loads(content)
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                self._warn(f"Invalid JSON: {exc}", malformed=True)
                self.metadata["parse_status"] = "unparsed"
                return
            if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
                info = obj.get("info", {})
                if isinstance(info, dict):
                    self.metadata["native_session_id"] = info.get("id")
                    self.metadata["session_metadata"] = info
                self.metadata["source_format"] = "opencode"
                for message in obj["messages"]:
                    yield {"__opencode_message__": message}, None
            elif isinstance(obj, dict) and isinstance(obj.get("events"), list):
                self.metadata["source_format"] = "normalized"
                self.metadata["native_session_id"] = obj.get("session_id")
                meta = obj.get("metadata", {})
                self.metadata["session_metadata"] = meta if isinstance(meta, dict) else {}
                for record in obj["events"]:
                    yield record, None
            elif isinstance(obj, list):
                for record in obj:
                    yield record, None
            else:
                yield obj, None
            return

        with self._open() as stream:
            line_number = 0
            while True:
                line = stream.readline(MAX_RECORD_BYTES + 1)
                if not line:
                    break
                line_number += 1
                if len(line) > MAX_RECORD_BYTES:
                    while line and not line.endswith(b"\n"):
                        line = stream.readline(MAX_RECORD_BYTES + 1)
                    self._warn("Record exceeds 2 MiB parse limit; original is archived", line=line_number, malformed=True)
                    continue
                if not line.strip():
                    continue
                if line_number == 1:
                    line = line.removeprefix(b"\xef\xbb\xbf")
                try:
                    yield _loads(line), line_number
                except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                    self._warn(f"Invalid JSONL record: {exc}", line=line_number, malformed=True)

    def _event(self, record: dict, line: int | None, **updates) -> dict:
        meta = record.get("metadata", {})
        result = {
            "type": record.get("type", "message"), "role": record.get("role", "unknown"),
            "tool": record.get("tool"), "arguments": _arguments(record.get("arguments")),
            "call_id": record.get("call_id"), "content": _text(record.get("content")),
            "status": _status(record.get("status"), record.get("content")),
            "timestamp": _timestamp(record.get("timestamp")), "source_line": line,
            "metadata": dict(meta) if isinstance(meta, dict) else {},
        }
        if isinstance(record.get("usage"), dict):
            result["metadata"]["usage"] = record["usage"]
        if "status" in record:
            result["metadata"]["reported_status"] = record["status"]
        original_content = record.get("content")
        if isinstance(original_content, str) and original_content.lstrip().startswith("{"):
            try:
                original_content = _loads(original_content)
            except (ValueError, RecursionError):
                pass
        if isinstance(original_content, dict):
            for source, target in (("isError", "reported_is_error"), ("exit_code", "reported_exit_code")):
                if source in original_content:
                    result["metadata"][target] = original_content[source]
            if original_content.get("isError") is True and original_content.get("exit_code") == 0:
                result["metadata"]["status_conflict"] = True
        if record.get("status") in ("success", "completed", "succeeded") and result["status"] == "error":
            result["metadata"]["status_conflict"] = True
        result.update(updates)
        return result

    def _opencode(self, record: Any, line: int | None) -> Iterator[dict]:
        if not isinstance(record, dict):
            self._warn("OpenCode message is not an object", line=line, malformed=True)
            return
        info = record.get("info", {})
        if not isinstance(info, dict):
            info = {}
        times = info.get("time", {})
        stamp = _timestamp(times.get("created")) if isinstance(times, dict) else None
        role = info.get("role", record.get("role", "unknown"))
        parts = record.get("parts", [])
        if not isinstance(parts, list):
            self._warn("OpenCode message parts is not a list", line=line, malformed=True)
            return
        for part in parts:
            if not isinstance(part, dict):
                self._warn("OpenCode part is not an object", line=line, malformed=True)
                continue
            kind = part.get("type")
            if kind in ("text", "reasoning"):
                yield self._event({}, line, type="message", role=role, content=_text(part.get("text")), timestamp=stamp,
                                  metadata={"native_message_id": info.get("id"), "part_type": kind})
            elif kind == "tool":
                state = part.get("state", {})
                if not isinstance(state, dict):
                    state = {}
                timing = state.get("time", {})
                if not isinstance(timing, dict):
                    timing = {}
                common = {"tool": part.get("tool"), "call_id": part.get("callID", part.get("call_id")),
                          "arguments": _arguments(state.get("input")), "role": "assistant"}
                yield self._event({}, line, type="tool_call", timestamp=_timestamp(timing.get("start")) or stamp,
                                  metadata={"native_message_id": info.get("id")}, **common)
                if state.get("status") in ("completed", "error", "failed"):
                    content = state.get("error") if state.get("status") in ("error", "failed") else state.get("output")
                    yield self._event({}, line, type="tool_result", tool=common["tool"], call_id=common["call_id"],
                                      role="tool", content=_text(content), status=_status(state.get("status"), content),
                                      timestamp=_timestamp(timing.get("end")) or stamp,
                                      metadata={"native_message_id": info.get("id")})
            elif kind == "step-finish":
                usage = {key: part[key] for key in ("tokens", "cost", "reason") if key in part}
                yield self._event({}, line, type="metric", role=role, timestamp=stamp, metadata={"usage": usage})
            else:
                self.metadata["skipped_records"] += 1
        if info.get("error"):
            yield self._event({}, line, type="message", role=role, timestamp=stamp, content=_text(info["error"]), status="error")

    def _normalize(self, record: Any, line: int | None) -> Iterator[dict]:
        if not isinstance(record, dict):
            self._warn("Record is not a JSON object", line=line, malformed=True)
            return
        if "__opencode_message__" in record:
            yield from self._opencode(record["__opencode_message__"], line)
            return
        if "parts" in record and "info" in record:
            self.metadata["source_format"] = "opencode"
            yield from self._opencode(record, line)
            return
        kind = record.get("type")
        payload = record.get("payload", {})
        if kind in ("session_meta", "response_item", "event_msg", "turn_context") and isinstance(payload, dict):
            self.metadata["source_format"] = "codex"
            if kind == "session_meta":
                self.metadata["native_session_id"] = payload.get("id")
                self.metadata["session_metadata"] = payload
                self._track_model(payload.get("model"))
                return
            if kind == "turn_context":
                # Retain context in the raw source without pretending it is work.
                self.metadata["session_metadata"].setdefault("turn_context", payload)
                self._track_model(payload.get("model"))
                return
            ptype = payload.get("type")
            stamp = _timestamp(record.get("timestamp"))
            meta = {"codex_record_type": kind}
            if ptype in ("function_call", "custom_tool_call"):
                yield self._event({}, line, type="tool_call", role="assistant", tool=payload.get("name"),
                                  arguments=_arguments(payload.get("arguments", payload.get("input"))),
                                  call_id=payload.get("call_id"), timestamp=stamp, metadata=meta)
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                content = payload.get("output")
                yield self._event({}, line, type="tool_result", role="tool", call_id=payload.get("call_id"),
                                  content=_text(content), status=_status(payload.get("status"), content),
                                  timestamp=stamp, metadata=meta)
            elif ptype == "message":
                yield self._event({}, line, type="message", role=payload.get("role", "unknown"),
                                  content=_text(payload.get("content")), timestamp=stamp, metadata=meta)
            elif ptype in ("user_message", "agent_message"):
                yield self._event({}, line, type="message", role="user" if ptype == "user_message" else "assistant",
                                  content=_text(payload.get("message")), timestamp=stamp, metadata=meta)
            elif ptype == "token_count":
                yield self._event({}, line, type="metric", timestamp=stamp,
                                  metadata={"usage": payload.get("info"), "codex_record_type": kind})
            elif ptype in ("error", "warning"):
                yield self._event({}, line, type="message", role="system", content=_text(payload.get("message")),
                                  status="error" if ptype == "error" else "unknown", timestamp=stamp, metadata=meta)
            else:
                self.metadata["skipped_records"] += 1
            return
        if kind in ("tool_call", "tool_result", "message", "metric"):
            if self.metadata["source_format"] not in ("codex", "opencode", "text"):
                self.metadata["source_format"] = "normalized"
            yield self._event(record, line)
            return
        if record.get("role") and "content" in record:
            self.metadata["source_format"] = "normalized"
            yield self._event(record, line, type="message")
            return
        self.metadata["skipped_records"] += 1
        self._warn("Unrecognized record schema; original is archived", line=line)

    def __iter__(self) -> Iterator[dict]:
        index = 0
        calls: dict[str, str | None] = {}
        recent_messages: list[tuple[str, str, str]] = []
        for record, line in self._records():
            for event in self._normalize(record, line):
                index += 1
                event["event_id"] = index
                call_id = event.get("call_id")
                if call_id is not None and not isinstance(call_id, str):
                    if isinstance(call_id, int) and not isinstance(call_id, bool):
                        call_id = str(call_id)
                    else:
                        self._warn("Invalid call ID was not used for tool correlation", line=line, malformed=True)
                        call_id = None
                    event["call_id"] = call_id
                if not isinstance(event.get("role"), str):
                    event["role"] = "unknown"
                if event.get("tool") is not None and not isinstance(event.get("tool"), str):
                    event["tool"] = None
                    self._warn("Invalid tool name was not used for tool correlation", line=line, malformed=True)
                if event["type"] == "tool_call" and call_id:
                    calls[call_id] = event.get("tool")
                    if len(calls) > 10_000:
                        calls.pop(next(iter(calls)))
                elif event["type"] == "tool_result" and call_id:
                    event["tool"] = event.get("tool") or calls.get(call_id)
                layer = event["metadata"].get("codex_record_type")
                if event["type"] == "message" and layer:
                    key = (event["role"], event["content"], layer)
                    if any(role == key[0] and content == key[1] and other_layer != layer
                           for role, content, other_layer in recent_messages):
                        event["metadata"]["duplicate_mirror"] = True
                    recent_messages.append(key)
                    recent_messages = recent_messages[-8:]
                yield event
        if self.metadata["warning_count"] > MAX_WARNINGS:
            self.metadata["warnings"].append(f"{self.metadata['warning_count'] - MAX_WARNINGS} additional warnings omitted")
        if index == 0 and self.metadata["parse_status"] == "partial":
            self.metadata["parse_status"] = "unparsed"


def parse_file(path: str | Path, format: str = "auto", *, compressed: bool = False,
               source_name: str | None = None) -> ParsedTranscript:
    """Return a one-pass event iterator with metadata finalized after iteration."""
    if format not in FORMATS:
        raise ValueError(f"Unsupported format {format!r}; choose one of {FORMATS}")
    return ParsedTranscript(Path(path), format, compressed, source_name)
