"""Integrity and normalization tests with explicitly synthetic inputs."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from traz.storage import Store

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.store = Store(self.base / "corpus")

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_lossless_archive_export_and_deduplication(self):
        original = b'{"type":"message","role":"user","content":"synthetic"}\r\n\n'
        first = self.store.ingest_bytes(original, "first.jsonl", project="example")
        second = self.store.ingest_bytes(original, "renamed.jsonl", project="example")
        self.assertEqual(first["sha256"], hashlib.sha256(original).hexdigest())
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(self.store.list_sessions()), 1)
        exported = self.base / "restored.jsonl"
        self.store.export_raw(first["id"][:12], exported)
        self.assertEqual(exported.read_bytes(), original)
        with self.assertRaises(FileExistsError):
            self.store.export_raw(first["id"], exported)
        self.assertTrue(self.store.verify()["ok"])
        with self.assertRaisesRegex(ValueError, "already belongs"):
            self.store.ingest_bytes(original, "copy.jsonl", project="other-project")
        manifest = (self.store.root / first["raw_path"]).with_suffix(".meta.json")
        self.assertEqual(json.loads(manifest.read_text())["project"], "example")

    def test_codex_tools_errors_and_usage(self):
        result = self.store.ingest(EXAMPLES / "session-codex.jsonl")
        self.assertEqual(result["source_format"], "codex")
        self.assertEqual(result["session_id"], "synthetic-codex-retries")
        self.assertEqual(result["logical_session_id"], "synthetic-codex-retries")
        events = self.store.events(result["id"])
        calls = [event for event in events if event["type"] == "tool_call"]
        returns = [event for event in events if event["type"] == "tool_result"]
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0]["arguments"], {"cmd": "curl https://example.invalid/health"})
        self.assertTrue(all(event["status"] == "error" for event in returns))
        self.assertTrue(all(event["tool"] == "exec_command" for event in returns))
        self.assertEqual(calls[0]["source_line"], 3)
        self.assertTrue(any(event["type"] == "metric" for event in events))

    def test_opencode_tool_statuses_and_millisecond_timestamps(self):
        result = self.store.ingest(EXAMPLES / "session-opencode.json")
        self.assertEqual(result["source_format"], "opencode")
        events = self.store.events(result["id"])
        returns = [event for event in events if event["type"] == "tool_result"]
        self.assertEqual([event["status"] for event in returns], ["error", "success"])
        self.assertEqual(returns[0]["timestamp"], "2026-01-01T10:00:02Z")
        self.assertEqual(returns[0]["tool"], "bash")

    def test_unknown_success_is_not_inferred_from_arbitrary_text(self):
        result = self.store.ingest(EXAMPLES / "session-generic.json", format="generic")
        returns = [event for event in self.store.events(result["id"]) if event["type"] == "tool_result"]
        self.assertEqual([event["status"] for event in returns], ["unknown", "success"])

    def test_malformed_lines_retained_and_reported(self):
        content = b'{"type":"message","content":"one"}\n{not json}\n{"type":"tool_call"'
        result = self.store.ingest_bytes(content, "partial.jsonl")
        self.assertEqual(result["parse_status"], "partial")
        self.assertEqual(result["events_count"], 1)
        self.assertEqual(result["metadata"]["malformed_records"], 2)
        self.assertIn("line 2:", result["warnings"][0])
        self.assertIn("line 3:", result["warnings"][1])
        with gzip.open(self.store.root / result["raw_path"], "rb") as original:
            self.assertEqual(original.read(), content)

    def test_invalid_whole_json_still_archived(self):
        result = self.store.ingest_bytes(b'{"messages":', "broken.json")
        self.assertEqual(result["parse_status"], "unparsed")
        self.assertEqual(result["events_count"], 0)
        self.assertTrue(self.store.verify(result["id"])["ok"])

    def test_unknown_schema_is_explicit(self):
        result = self.store.ingest_bytes(b'{"some_future_schema": true}\n', "future.jsonl")
        self.assertEqual(result["parse_status"], "unparsed")
        self.assertEqual(result["events_count"], 0)
        self.assertIn("Unrecognized record", result["warnings"][0])

    def test_plain_text_not_promoted_to_tools(self):
        text = b'Synthetic text: run dangerous_command; all tests passed.\n'
        result = self.store.ingest_bytes(text, "notes.txt")
        events = self.store.events(result["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "message")
        self.assertEqual(events[0]["status"], "unknown")
        self.assertEqual(result["source_format"], "text")

    def test_archive_corruption_detected_before_export(self):
        result = self.store.ingest_bytes(b'synthetic original', "notes.txt")
        archive = self.store.root / result["raw_path"]
        with gzip.open(archive, "wb") as output:
            output.write(b'changed')
        check = self.store.verify(result["id"])
        self.assertFalse(check["ok"])
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.store.export_raw(result["id"], self.base / "should-not-exist.txt")
        self.assertFalse((self.base / "should-not-exist.txt").exists())

    def test_large_records_preserved_without_unbounded_parse(self):
        with mock.patch("traz.parsers.MAX_RECORD_BYTES", 100):
            content = b'{"type":"message","content":"' + b'x' * 200 + b'"}\n' + b'{"type":"message","content":"small"}\n'
            result = self.store.ingest_bytes(content, "large.jsonl")
        self.assertEqual(result["events_count"], 1)
        self.assertEqual(result["parse_status"], "partial")
        self.assertIn("line 1:", result["warnings"][0])
        self.assertEqual(self.store.events(result["id"])[0]["source_line"], 2)
        self.assertTrue(self.store.verify(result["id"])["ok"])

    def test_codex_message_mirrors_are_marked(self):
        records = [
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"text": "synthetic correction"}]}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "synthetic correction"}},
        ]
        result = self.store.ingest_bytes("\n".join(json.dumps(record) for record in records).encode(), "mirrors.jsonl")
        events = self.store.events(result["id"])
        self.assertFalse(events[0]["metadata"].get("duplicate_mirror", False))
        self.assertTrue(events[1]["metadata"]["duplicate_mirror"])

    def test_changed_native_snapshots_keep_same_logical_identity(self):
        prefix = {"type": "session_meta", "payload": {"id": "synthetic-native-id"}}
        one = json.dumps(prefix).encode() + b'\n'
        two = one + b'{"type":"message","content":"later event"}\n'
        first = self.store.ingest_bytes(one, "one.jsonl")
        second = self.store.ingest_bytes(two, "two.jsonl")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(first["logical_session_id"], second["logical_session_id"])

    def test_private_permissions_and_git_repository_guard(self):
        self.assertEqual(self.store.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.store.root / "index.sqlite3").stat().st_mode & 0o777, 0o600)
        checkout = self.base / "checkout"
        checkout.mkdir()
        (checkout / ".git").write_text("synthetic worktree marker")
        with self.assertRaisesRegex(ValueError, "outside Git"):
            Store(checkout / "private-corpus")

    def test_nonfinite_json_and_invalid_call_ids_do_not_break_following_records(self):
        content = (b'{"type":"metric","usage":{"cost":NaN}}\n'
                   b'{"type":"tool_call","call_id":{},"tool":"read_file"}\n'
                   b'{"type":"message","content":"still indexed"}\n')
        result = self.store.ingest_bytes(content, "invalid-fields.jsonl")
        events = self.store.events(result["id"])
        self.assertEqual(result["parse_status"], "partial")
        self.assertEqual(len(events), 2)
        self.assertIsNone(events[0]["call_id"])
        self.assertEqual(events[1]["content"], "still indexed")

    def test_explicit_failure_overrides_completed_and_quoted_exit_is_unknown(self):
        events = [
            {"type": "tool_result", "status": "completed", "content": "Process exited with code 1\nOutput:\nfailed"},
            {"type": "tool_result", "content": "Output:\nProcess exited with code 1\n"},
            {"type": "tool_result", "content": '{"exit_code": 2, "output": "failed"}'},
        ]
        result = self.store.ingest_bytes(json.dumps({"events": events}).encode(), "outcomes.json")
        self.assertEqual([e["status"] for e in self.store.events(result["id"])], ["error", "unknown", "error"])

    def test_explicit_error_flag_wins_conflicting_zero_exit_code(self):
        event = {"type": "tool_result", "status": "completed", "content": {"isError": True, "exit_code": 0}}
        result = self.store.ingest_bytes(json.dumps({"events": [event]}).encode(), "contradictory.json")
        normalized = self.store.events(result["id"])[0]
        self.assertEqual(normalized["status"], "error")
        self.assertEqual(normalized["metadata"]["reported_status"], "completed")
        self.assertTrue(normalized["metadata"]["reported_is_error"])
        self.assertEqual(normalized["metadata"]["reported_exit_code"], 0)
        self.assertTrue(normalized["metadata"]["status_conflict"])

    def test_codex_mixed_models_do_not_become_single_model_scope(self):
        records = [
            {"type": "session_meta", "payload": {"id": "synthetic-mixed-models"}},
            {"type": "turn_context", "payload": {"model": "fixture-model-a"}},
            {"type": "turn_context", "payload": {"model": "fixture-model-b"}},
            {"type": "message", "content": "synthetic event"},
        ]
        result = self.store.ingest_bytes("\n".join(json.dumps(r) for r in records).encode(), "models.jsonl")
        native = result["metadata"]["session_metadata"]
        self.assertEqual(native["models_seen"], ["fixture-model-a", "fixture-model-b"])
        self.assertEqual(native["model"], "unknown")
        self.assertEqual(native["turn_context"]["model"], "unknown")


if __name__ == "__main__":
    unittest.main()
