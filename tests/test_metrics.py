"""Reported native accounting, scope and incomplete coverage semantics."""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from traz.metrics import metrics
from traz.storage import Store

NATIVE = "synthetic-native-thread"


def counters(input=100, cached=80, output=20, reasoning=5):
    return {"input_tokens": input, "cached_input_tokens": cached,
            "output_tokens": output, "reasoning_output_tokens": reasoning,
            "total_tokens": input + output}


def add(left, right):
    return {key: left[key] + right[key] for key in left}


def wrap(kind, payload, second):
    return {"type": kind, "timestamp": f"2026-01-01T00:00:{second:02d}Z", "payload": payload}


def token_count(value, second, last=None):
    return wrap("event_msg", {"type": "token_count", "info": {
        "total_token_usage": value, "last_token_usage": last if last is not None else value}}, second)


def usage(response, value, total, second, *, turn="synthetic-turn", thread=NATIVE, provider_session="opaque-session"):
    return wrap("token_usage_record", {
        "thread_id": thread, "session_id": provider_session, "turn_id": turn,
        "response_id": response, "usage": value,
        "thread_token_usage": total, "turn_token_usage": total,
    }, second)


def completed(turn, duration, second):
    return wrap("event_msg", {"type": "task_complete", "turn_id": turn,
        "root_turn_id": turn, "duration_ms": duration,
        "started_at": 1767225600, "completed_at": 1767225606, "error": None}, second)


def native_records():
    one = counters()
    two = counters(200, 150, 30, 10)
    total = add(one, two)
    return [
        wrap("session_meta", {"id": NATIVE, "synthetic": True}, 0),
        usage("synthetic-response-1", one, one, 1),
        token_count(one, 2),
        usage("synthetic-response-2", two, total, 3),
        token_count(total, 4, last=two),
        token_count(total, 5, last=two),
        completed("synthetic-turn", 6000, 6),
    ]


def raw(records):
    return ("\n".join(json.dumps(record) for record in records) + "\n").encode()


class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "corpus")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def ingest(self, records, suffix=b""):
        return self.store.ingest_bytes(raw(records) + suffix, "synthetic-metrics.jsonl")

    def test_unique_response_check_last_cumulative_and_no_double_counting(self):
        session = self.ingest(native_records())
        before = list(self.store.db.iterdump())
        result = metrics(self.store, session["id"])
        self.assertEqual(result["tokens"]["status"], "reported_consistent")
        self.assertEqual(result["tokens"]["cross_check"]["status"], "matched")
        total = result["tokens"]["totals"]
        self.assertEqual(total["input_tokens"], 300)
        self.assertEqual(total["cached_input_tokens"], 230)
        self.assertEqual(total["uncached_input_tokens"], 70)
        self.assertEqual(total["output_tokens"], 50)
        self.assertEqual(total["reasoning_output_tokens"], 15)
        self.assertEqual(total["non_reasoning_output_tokens"], 35)
        self.assertEqual(total["total_tokens"], 350)
        self.assertAlmostEqual(result["tokens"]["cache_share_of_input"], 230 / 300)
        self.assertEqual(result["tokens"]["unique_response_count"], 2)
        self.assertEqual(result["tokens"]["duplicate_cumulative_sample_count"], 1)
        self.assertEqual(result["timing"]["observed_span_seconds"], 6)
        self.assertEqual(result["timing"]["recorded_turn_duration_ms"], 6000)
        self.assertIsNone(result["timing"]["active_seconds"])
        self.assertIsNone(result["timing"]["human_wait_seconds"])
        self.assertIsNone(result["monetary_cost"])
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_exact_response_replay_after_later_response_is_not_added_or_a_reset(self):
        records = native_records()
        records.append(copy.deepcopy(records[1]))
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["tokens"]["status"], "reported_consistent")
        self.assertEqual(result["tokens"]["duplicate_response_count"], 1)
        self.assertEqual(result["tokens"]["totals"]["total_tokens"], 350)

    def test_conflicting_response_duplicate_invalidates_all_aggregates(self):
        records = native_records()
        duplicate = copy.deepcopy(records[1])
        duplicate["payload"]["usage"] = counters(101, 80, 20, 5)
        records.append(duplicate)
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["tokens"]["status"], "conflicting")
        self.assertEqual(result["tokens"]["conflicting_response_count"], 1)
        self.assertIsNone(result["tokens"]["totals"])
        self.assertIsNone(result["tokens"]["observed_reported_totals"])

    def test_cumulative_reset_remains_conflicting_after_later_recovery(self):
        records = native_records()
        records.extend([token_count(counters(10, 8, 2, 1), 7),
                        token_count(add(counters(), counters(200, 150, 30, 10)), 8)])
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["tokens"]["status"], "conflicting")
        self.assertIsNone(result["tokens"]["totals"])
        self.assertIsNone(result["tokens"]["observed_reported_totals"])
        self.assertIn("cumulative_counter_decreased", [issue["code"] for issue in result["tokens"]["reasons"]])

    def test_per_response_sum_mismatch_invalidates_total(self):
        records = native_records()
        records[3]["payload"]["usage"] = counters(201, 150, 30, 10)
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["tokens"]["cross_check"]["status"], "mismatch")
        self.assertEqual(result["tokens"]["status"], "conflicting")
        self.assertIsNone(result["tokens"]["totals"])

    def test_cumulative_only_is_reported_without_invented_cross_check(self):
        records = [wrap("session_meta", {"id": NATIVE}, 0),
                   token_count(counters(), 1), token_count(counters(), 2)]
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["tokens"]["status"], "reported_cumulative")
        self.assertEqual(result["tokens"]["totals"]["total_tokens"], 120)
        self.assertEqual(result["tokens"]["cross_check"]["status"], "unavailable")
        self.assertIsNone(result["timing"]["recorded_turn_duration_ms"])

    def test_multiple_native_or_thread_scopes_are_unknown(self):
        for change in ("native", "thread"):
            with self.subTest(change=change):
                records = native_records()
                if change == "native":
                    records.append(wrap("session_meta", {"id": "other-native-thread"}, 7))
                else:
                    records[3]["payload"]["thread_id"] = "other-native-thread"
                result = metrics(self.store, self.ingest(records)["id"])
                self.assertEqual(result["scope"]["status"], "unknown")
                self.assertIsNone(result["tokens"]["totals"])
                self.assertIsNone(result["tokens"]["observed_reported_totals"])
                self.assertIsNone(result["timing"]["recorded_turn_duration_ms"])

    def test_opaque_provider_session_id_does_not_define_native_scope(self):
        records = native_records()
        records[3]["payload"]["session_id"] = "another-opaque-provider-session"
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["scope"]["status"], "single")
        self.assertEqual(result["scope"]["usage_session_id_count"], 2)
        self.assertEqual(result["tokens"]["status"], "reported_consistent")

    def test_turn_duplicates_not_added_and_conflicting_duration_is_unknown(self):
        records = native_records()
        records.extend([copy.deepcopy(records[-1]), completed("another-turn", 1500, 7)])
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["timing"]["recorded_turn_duration_ms"], 7500)
        self.assertEqual(result["timing"]["duplicate_turn_count"], 1)
        self.assertEqual(result["timing"]["recorded_turn_count"], 2)
        records.append(completed("synthetic-turn", 7000, 8))
        conflict = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(conflict["timing"]["recorded_turn_status"], "conflicting")
        self.assertIsNone(conflict["timing"]["recorded_turn_duration_ms"])
        self.assertIsNone(conflict["timing"]["observed_recorded_turn_duration_ms"])

    def test_malformed_raw_retains_only_qualified_observed_accounting(self):
        session = self.ingest(native_records(), b"{invalid json}\n")
        result = metrics(self.store, session["id"])
        self.assertFalse(result["coverage"]["raw_complete"])
        self.assertFalse(result["coverage"]["token_measurements_complete"])
        self.assertEqual(result["coverage"]["malformed_records"], 1)
        self.assertEqual(result["tokens"]["status"], "unknown")
        self.assertEqual(result["tokens"]["cross_check"]["status"], "matched")
        self.assertIsNone(result["tokens"]["totals"])
        self.assertEqual(result["tokens"]["observed_reported_totals"]["total_tokens"], 350)
        self.assertIsNone(result["timing"]["recorded_turn_duration_ms"])
        self.assertEqual(result["timing"]["observed_recorded_turn_duration_ms"], 6000)
        self.assertEqual(result["timing"]["observed_span_status"], "partial")

    def test_oversized_record_makes_raw_coverage_incomplete(self):
        session = self.ingest(native_records(), raw([{"type": "compacted", "payload": {"text": "x" * 3000}}]))
        with mock.patch("traz.parsers.MAX_RECORD_BYTES", 2000):
            result = metrics(self.store, session["id"])
        self.assertFalse(result["coverage"]["raw_complete"])
        self.assertEqual(result["coverage"]["malformed_records"], 1)
        self.assertIsNone(result["tokens"]["totals"])
        self.assertEqual(result["tokens"]["observed_reported_totals"]["total_tokens"], 350)

    def test_invalid_counter_types_subsets_or_totals_are_not_aggregated(self):
        mutations = [
            {"input_tokens": True}, {"cached_input_tokens": 101},
            {"reasoning_output_tokens": 21}, {"total_tokens": 121},
            {"input_tokens": -1}, {"output_tokens": 20.0},
        ]
        for changed in mutations:
            with self.subTest(changed=changed):
                records = native_records()
                records[1]["payload"]["usage"].update(changed)
                result = metrics(self.store, self.ingest(records)["id"])
                self.assertIsNone(result["tokens"]["totals"])
                self.assertIsNone(result["tokens"]["observed_reported_totals"])
                self.assertIn("invalid_counters", [issue["code"] for issue in result["tokens"]["reasons"]])

    def test_no_usage_rate_limit_update_is_not_a_zero_or_error(self):
        records = native_records()
        records.append(wrap("event_msg", {"type": "token_count", "info": None, "rate_limits": {}}, 7))
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["tokens"]["status"], "reported_consistent")
        self.assertEqual(result["tokens"]["totals"]["total_tokens"], 350)
        self.assertEqual(result["coverage"]["token_count_updates_without_usage"], 1)

    def test_observed_span_uses_aware_minimum_maximum_without_active_time_claim(self):
        records = native_records()
        records[0]["timestamp"] = "2026-01-01T02:00:00+02:00"
        records[-1]["timestamp"] = "2026-01-01T00:00:20Z"
        records.append(wrap("world_state", {}, 10))
        result = metrics(self.store, self.ingest(records)["id"])
        self.assertEqual(result["timing"]["observed_start"], "2026-01-01T00:00:00Z")
        self.assertEqual(result["timing"]["observed_end"], "2026-01-01T00:00:20Z")
        self.assertEqual(result["timing"]["observed_span_seconds"], 20)
        self.assertIsNone(result["timing"]["active_seconds"])
        self.assertIsNone(result["timing"]["human_wait_seconds"])

    def test_non_codex_remains_unknown(self):
        session = self.store.ingest_bytes(b'{"events":[{"type":"message","content":"synthetic"}]}', "generic.json")
        result = metrics(self.store, session["id"])
        self.assertEqual(result["tokens"]["status"], "unknown")
        self.assertEqual(result["tokens"]["reasons"][0]["code"], "unsupported_source_format")
        self.assertIsNone(result["tokens"]["totals"])

    def test_codex_array_json_preserves_original_framing(self):
        session = self.store.ingest_bytes(json.dumps(native_records()).encode(), "codex-array.json")
        self.assertEqual(session["source_format"], "codex")
        self.assertEqual(session["metadata"]["encoding"], "json")
        result = metrics(self.store, session["id"])
        self.assertTrue(result["coverage"]["raw_complete"])
        self.assertEqual(result["tokens"]["totals"]["total_tokens"], 350)

    def test_archive_integrity_failure_never_returns_aggregates(self):
        session = self.ingest(native_records())
        with gzip.open(self.store.root / session["raw_path"], "wb") as stream:
            stream.write(b'{"type":"session_meta","payload":{"id":"replacement"}}\n')
        result = metrics(self.store, session["id"])
        self.assertEqual(result["coverage"]["archive_integrity"], "failed")
        self.assertIsNone(result["tokens"]["totals"])
        self.assertIsNone(result["tokens"]["observed_reported_totals"])


if __name__ == "__main__":
    unittest.main()
