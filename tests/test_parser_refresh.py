"""Synthetic regressions for metadata observed in newer Codex rollouts."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from traz.parsers import parse_file
from traz.storage import Store


class ParserRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="traz-parser-test-")
        self.store = Store(Path(self.directory.name) / "corpus")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def ingest(self, records):
        data = "\n".join(json.dumps(r) for r in records).encode()
        return self.store.ingest_bytes(data, "synthetic.jsonl", format="codex")

    def test_known_metadata_retained_without_shifting_evidence_ids(self):
        session = self.ingest([
            {"type": "session_meta", "payload": {"id": "synthetic-native"}},
            {"type": "world_state", "payload": {"full": True, "state": {}}},
            {"type": "response_item", "payload": {"type": "message", "role": "user", "content": "task"}},
            {"type": "token_usage_record", "payload": {"usage": {"total_tokens": 10}}},
            {"type": "compacted", "payload": {"message": "summary", "replacement_history": [
                {"type": "message", "role": "user", "content": "task"}]}},
            {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "done"}},
        ])
        self.assertEqual(session["parse_status"], "ok")
        self.assertEqual(session["metadata"]["retained_metadata_records"],
                         {"world_state": 1, "token_usage_record": 1, "compacted": 1})
        events = self.store.events(session["id"])
        self.assertEqual([(e["event_id"], e["source_line"]) for e in events], [(1, 3), (2, 6)])
        self.assertTrue(self.store.verify(session["id"])["ok"])

    def test_unknown_metadata_still_warns(self):
        result = self.ingest([{"type": "future_state", "payload": {}},
                              {"type": "message", "content": "known"}])
        self.assertEqual(result["parse_status"], "partial")
        self.assertEqual(result["metadata"]["warning_count"], 1)

    def test_refresh_changes_only_metadata_and_preserves_review_references(self):
        result = self.ingest([{"type": "message", "content": "stable"}])
        before = self.store.events(result["id"])
        with self.store.db:
            self.store.db.execute("UPDATE sessions SET parse_status='partial', warnings_json='[\"old warning\"]' WHERE id=?", (result["id"],))
        updated = self.store.refresh_metadata(result["id"])
        self.assertEqual(updated["parse_status"], "ok")
        self.assertEqual(updated["warnings"], [])
        self.assertEqual(self.store.events(result["id"]), before)
        self.assertEqual(updated["logical_session_id"], result["logical_session_id"])
        manifest = (self.store.root / result["raw_path"]).with_suffix(".meta.json")
        self.assertEqual(json.loads(manifest.read_text())["parse_status"], "ok")

    def test_refresh_preserves_opencode_jsonl_framing_and_evidence(self):
        records = [{"info": {"id": str(index), "role": "user"},
                    "parts": [{"type": "text", "text": str(index)}]}
                   for index in range(2)]
        data = "\n".join(json.dumps(record) for record in records).encode()
        original = self.store.ingest_bytes(data, "opencode.jsonl", format="auto")
        self.assertEqual(original["source_format"], "opencode")
        self.assertEqual(original["metadata"]["encoding"], "jsonl")
        evidence = self.store.events(original["id"])
        updated = self.store.refresh_metadata(original["id"])
        self.assertEqual(updated["parse_status"], "ok")
        self.assertEqual(updated["source_format"], "opencode")
        self.assertEqual(updated["metadata"]["encoding"], "jsonl")
        self.assertEqual(updated["logical_session_id"], original["logical_session_id"])
        self.assertEqual(self.store.events(original["id"]), evidence)
        self.assertTrue(self.store.verify(original["id"])["ok"])

    def test_refresh_refuses_any_semantic_change_before_writing(self):
        result = self.ingest([{"type": "message", "content": "original"}])
        before = self.store.session(result["id"])
        parser = parse_file(self.store.root / result["raw_path"], "codex", compressed=True)
        original_event = next(iter(parser))
        changed = {**original_event, "content": "changed interpretation"}
        class ChangedParser:
            metadata = parser.metadata
            def __iter__(self):
                yield changed
        with patch("traz.storage.parse_file", return_value=ChangedParser()):
            with self.assertRaisesRegex(ValueError, "would change"):
                self.store.refresh_metadata(result["id"])
        self.assertEqual(self.store.session(result["id"]), before)
        self.assertEqual(self.store.events(result["id"])[0]["content"], "original")


if __name__ == "__main__":
    unittest.main()
