"""Connection and stable snapshot semantics using only synthetic local files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from traz.collect import collect, connections, load_manifest, save_manifest
from traz.storage import Store


def native_source():
    records = [{"type": "session_meta", "payload": {"id": "synthetic-connected-session"}}]
    for index in range(3):
        records.append({"type": "response_item", "payload": {
            "type": "function_call", "name": "synthetic_tool",
            "arguments": "{\"synthetic\": true}", "call_id": str(index)}})
        records.append({"type": "response_item", "payload": {
            "type": "function_call_output", "call_id": str(index),
            "output": "Process exited with code 1\nOutput:\nSynthetic failure"}})
    return ("\n".join(json.dumps(record) for record in records) + "\n").encode()


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.source = self.base / "native-session.jsonl"
        self.source.write_bytes(native_source())
        self.store = Store(self.base / "corpus")
        self.manifest = {"schema_version": "0.1", "sources": [{
            "id": "synthetic-session", "name": "Synthetic connected session",
            "path": str(self.source), "format": "codex", "project": "fixture",
        }]}

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_connection_archives_original_and_resumes_without_duplicate_analysis(self):
        original = self.source.read_bytes()
        first = collect(self.store, self.manifest)
        item = first["sources"][0]
        self.assertEqual(item["status"], "archived")
        self.assertEqual(item["analysis_status"], "analyzed")
        self.assertTrue(first["coverage"]["complete"])
        self.assertEqual(self.source.read_bytes(), original)
        with mock.patch("traz.analysis.analyze", side_effect=AssertionError("Cached analysis must not rerun")):
            second = collect(self.store, load_manifest(self.store))
        self.assertEqual(second["sources"][0]["status"], "unchanged")
        self.assertEqual(second["sources"][0]["analysis_status"], "cached")
        self.assertEqual(len(self.store.list_sessions()), 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM traz_analyses").fetchone()[0], 1)
        saved = connections(self.store)[0]
        self.assertEqual(saved["last_snapshot_id"], item["snapshot_id"])
        self.assertEqual(saved["last_analysis_snapshot_id"], item["snapshot_id"])
        self.assertTrue(saved["configured"])
        self.assertEqual((self.store.root / "sources.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM traz_collection_runs").fetchone()[0], 2)
        self.assertEqual(list((self.store.root / "staging").iterdir()), [])

    def test_growth_is_new_snapshot_of_same_logical_case(self):
        first = collect(self.store, self.manifest)
        with self.source.open("ab") as output:
            output.write(b'{"type":"message","content":"Synthetic later event"}\n')
        second = collect(self.store, self.manifest)
        before, after = first["sources"][0], second["sources"][0]
        self.assertNotEqual(before["snapshot_id"], after["snapshot_id"])
        self.assertEqual(before["logical_session_id"], after["logical_session_id"])
        self.assertEqual(len(self.store.list_sessions()), 2)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM traz_proposals").fetchone()[0], 1)
        self.assertEqual(len(connections(self.store)), 1)
        self.assertEqual(connections(self.store)[0]["last_snapshot_id"], after["snapshot_id"])
        self.assertTrue(self.store.verify()["ok"])

    def test_missing_source_retains_connection_and_previous_archive(self):
        first = collect(self.store, self.manifest, analyze_sessions=False)
        self.source.unlink()  # Simulate an external native log removal.
        second = collect(self.store, self.manifest, analyze_sessions=False)
        self.assertEqual(second["coverage"]["failed"], 1)
        self.assertFalse(second["coverage"]["archive_complete"])
        saved = connections(self.store)[0]
        self.assertTrue(saved["configured"])
        self.assertEqual(saved["last_snapshot_id"], first["sources"][0]["snapshot_id"])
        self.assertEqual(saved["last_status"], "failed")
        self.assertTrue(self.store.verify()["ok"])

    def test_one_missing_file_does_not_skip_other_explicit_sources(self):
        self.manifest["sources"].insert(0, {
            "id": "missing", "path": str(self.base / "missing.jsonl"), "project": "fixture",
        })
        report = collect(self.store, self.manifest, analyze_sessions=False)
        self.assertEqual([source["status"] for source in report["sources"]], ["failed", "archived"])
        self.assertEqual(report["coverage"]["requested"], 2)
        self.assertEqual(report["coverage"]["archived"], 1)
        self.assertEqual(report["coverage"]["failed"], 1)

    def test_first_changing_copy_is_retried_and_only_stable_bytes_are_archived(self):
        real_fstat = os.fstat
        inode = self.source.stat().st_ino
        calls = 0

        def changing_fstat(fd):
            nonlocal calls
            state = real_fstat(fd)
            if state.st_ino == inode:
                calls += 1
                if calls == 2:
                    with self.source.open("ab") as output:
                        output.write(b'{"type":"message","content":"Synthetic concurrent append"}\n')
                    return real_fstat(fd)
            return state

        with mock.patch("traz.collect.os.fstat", side_effect=changing_fstat):
            report = collect(self.store, self.manifest, analyze_sessions=False)
        item = report["sources"][0]
        self.assertEqual(item["status"], "archived")
        self.assertEqual(item["attempts"], 2)
        self.assertEqual(len(self.store.list_sessions()), 1)
        target = self.base / "restored.jsonl"
        self.store.export_raw(item["snapshot_id"], target)
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        self.assertEqual(list((self.store.root / "staging").iterdir()), [])

    def test_continuously_changing_source_is_deferred_after_two_attempts(self):
        real_fstat = os.fstat
        inode = self.source.stat().st_ino
        calls = 0

        def changing_fstat(fd):
            nonlocal calls
            state = real_fstat(fd)
            if state.st_ino == inode:
                calls += 1
                if calls in (2, 4):
                    with self.source.open("ab") as output:
                        output.write(b"\n")
                    return real_fstat(fd)
            return state

        with mock.patch("traz.collect.os.fstat", side_effect=changing_fstat):
            report = collect(self.store, self.manifest)
        self.assertEqual(calls, 4)
        self.assertEqual(report["sources"][0]["status"], "deferred")
        self.assertEqual(report["sources"][0]["attempts"], 2)
        self.assertEqual(report["coverage"]["deferred"], 1)
        self.assertFalse(report["coverage"]["complete"])
        self.assertEqual(self.store.list_sessions(), [])
        self.assertIsNone(connections(self.store)[0]["last_snapshot_id"])
        self.assertEqual(list((self.store.root / "staging").iterdir()), [])

    def test_replaced_path_is_detected_even_if_open_file_metadata_does_not_change(self):
        real_fstat = os.fstat
        old_inode = self.source.stat().st_ino
        calls = 0
        replacement = self.base / "replacement.jsonl"
        replacement.write_bytes(native_source() + b'{"type":"message","content":"replacement"}\n')

        def replacing_fstat(fd):
            nonlocal calls
            state = real_fstat(fd)
            if state.st_ino == old_inode:
                calls += 1
                if calls == 2:
                    os.replace(replacement, self.source)
            return state

        with mock.patch("traz.collect.os.fstat", side_effect=replacing_fstat):
            report = collect(self.store, self.manifest, analyze_sessions=False)
        self.assertEqual(report["sources"][0]["attempts"], 2)
        self.assertEqual(report["sources"][0]["status"], "archived")
        self.assertEqual(report["sources"][0]["raw_bytes"], self.source.stat().st_size)

    def test_partial_parse_is_not_reported_as_complete_analysis(self):
        with self.source.open("ab") as output:
            output.write(b"{not valid JSON}\n")
        report = collect(self.store, self.manifest)
        self.assertEqual(report["coverage"]["archived"], 1)
        self.assertTrue(report["coverage"]["archive_complete"])
        self.assertEqual(report["coverage"]["parse_incomplete"], 1)
        self.assertFalse(report["coverage"]["parse_complete"])
        self.assertFalse(report["coverage"]["analysis_complete"])
        self.assertFalse(report["coverage"]["complete"])
        self.assertTrue(report["sources"][0]["warnings"])

    def test_analysis_failure_preserves_archive_and_next_collect_can_resume(self):
        with mock.patch("traz.analysis.analyze", side_effect=ValueError("Synthetic analysis failure")):
            first = collect(self.store, self.manifest)
        self.assertTrue(first["coverage"]["archive_complete"])
        self.assertEqual(first["coverage"]["analysis_failed"], 1)
        self.assertFalse(first["coverage"]["complete"])
        self.assertEqual(connections(self.store)[0]["last_status"], "analysis_failed")
        saved_id = first["sources"][0]["snapshot_id"]
        second = collect(self.store, self.manifest)
        self.assertEqual(second["sources"][0]["snapshot_id"], saved_id)
        self.assertEqual(second["sources"][0]["analysis_status"], "analyzed")
        self.assertTrue(second["coverage"]["complete"])

    def test_manifest_omission_never_deletes_connection_or_source(self):
        collect(self.store, self.manifest, analyze_sessions=False)
        collect(self.store, {"schema_version": "0.1", "sources": []}, analyze_sessions=False)
        self.assertEqual(len(connections(self.store)), 1)
        self.assertFalse(connections(self.store)[0]["configured"])
        self.assertEqual(len(self.store.list_sessions()), 1)
        self.assertTrue(self.source.exists())

    def test_changed_source_configuration_starts_uncollected_without_losing_history(self):
        changes = {"path": str(self.base / "not-collected.jsonl"),
                   "project": "different-project", "format": "auto",
                   "session_id": "different-native-session"}
        for field, value in changes.items():
            with self.subTest(field=field):
                first = collect(self.store, self.manifest)
                snapshot_id = first["sources"][0]["snapshot_id"]
                prior_events = self.store.events(snapshot_id)
                prior_runs = [tuple(row) for row in self.store.db.execute(
                    "SELECT * FROM traz_collection_runs ORDER BY id")]
                changed = json.loads(json.dumps(self.manifest))
                changed["sources"][0][field] = value
                save_manifest(self.store, changed)
                current = connections(self.store)[0]
                self.assertEqual(current["last_status"], "connected")
                self.assertEqual(current["source"][field], value)
                self.assertTrue(current["configured"])
                for key in ("last_snapshot_id", "logical_session_id", "last_success_at",
                            "last_signature", "last_checked_at", "last_error",
                            "last_analysis_snapshot_id", "last_analysis_version", "last_analysis_at"):
                    self.assertIsNone(current[key], key)
                self.assertEqual(self.store.events(snapshot_id), prior_events)
                self.assertTrue(self.store.verify(snapshot_id)["ok"])
                self.assertEqual([tuple(row) for row in self.store.db.execute(
                    "SELECT * FROM traz_collection_runs ORDER BY id")], prior_runs)

    def test_name_only_change_preserves_current_snapshot_and_analysis(self):
        collect(self.store, self.manifest)
        before = connections(self.store)[0]
        self.manifest["sources"][0]["name"] = "Renamed synthetic connection"
        save_manifest(self.store, self.manifest)
        after = connections(self.store)[0]
        self.assertEqual(after["source"]["name"], "Renamed synthetic connection")
        for key in ("last_status", "last_snapshot_id", "logical_session_id", "last_success_at",
                    "last_signature", "last_checked_at", "last_error",
                    "last_analysis_snapshot_id", "last_analysis_version", "last_analysis_at"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM traz_collection_runs").fetchone()[0], 1)

    def test_invalid_manifests_cannot_replace_saved_configuration(self):
        save_manifest(self.store, self.manifest)
        connected = connections(self.store)
        self.assertEqual(len(connected), 1)
        self.assertEqual(connected[0]["last_status"], "connected")
        self.assertIsNone(connected[0]["last_snapshot_id"])
        self.assertTrue(connected[0]["configured"])
        original = (self.store.root / "sources.json").read_bytes()
        invalid = {"schema_version": "0.1", "sources": [{
            "id": "bad", "path": "https://example.invalid/transcript.json",
        }]}
        with self.assertRaisesRegex(ValueError, "local file"):
            collect(self.store, invalid)
        self.assertEqual((self.store.root / "sources.json").read_bytes(), original)
        invalid["sources"][0] = {"id": "bad", "path": str(self.source), "command": "never executed"}
        with self.assertRaisesRegex(ValueError, "supports only"):
            collect(self.store, invalid)
        self.assertEqual(self.source.read_bytes(), native_source())

    def test_collector_rejects_its_own_corpus_as_a_source(self):
        source = {"id": "own-state", "path": str(self.store.root / "index.sqlite3"), "project": "fixture"}
        report = collect(self.store, {"schema_version": "0.1", "sources": [source]}, analyze_sessions=False)
        self.assertEqual(report["sources"][0]["status"], "failed")
        self.assertIn("own files", report["sources"][0]["error"])
        self.assertEqual(self.store.list_sessions(), [])

    def test_duplicate_bytes_cannot_be_silently_reassigned_to_another_native_id(self):
        first = collect(self.store, self.manifest, analyze_sessions=False)
        self.manifest["sources"][0]["session_id"] = "different-synthetic-session"
        second = collect(self.store, self.manifest, analyze_sessions=False)
        self.assertEqual(second["sources"][0]["status"], "failed")
        self.assertIn("different native session identity", second["sources"][0]["error"])
        self.assertIsNone(connections(self.store)[0]["last_snapshot_id"])
        self.assertTrue(self.store.verify(first["sources"][0]["snapshot_id"])["ok"])
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM traz_collection_runs").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
