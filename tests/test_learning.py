"""Behavior tests for conservative observations and scoped reported evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from traz.storage import Store
from traz.analysis import analyze, get_proposal, proposals, import_review
from traz.learning import evaluate, evaluations, matrix, summary, evidence_template
from traz.learning import proposals as learning_proposals


def transcript(*, statuses=("error", "error", "error"), native_id="source-task", extra=False):
    events = []
    for i, status in enumerate(statuses):
        events.append({"type": "tool_call", "tool": "fetch_resource", "arguments": {"resource": "fixture-only"}, "call_id": str(i)})
        events.append({"type": "tool_result", "call_id": str(i), "status": status, "content": "Synthetic outcome"})
    if extra:
        events.append({"type": "message", "role": "assistant", "content": "Synthetic continuation"})
    return json.dumps({"session_id": native_id, "events": events}).encode()


def evaluation(proposal):
    return {
        "schema_version": "0.1", "evaluation_id": "fixture-evaluation-1",
        "proposal_id": proposal["id"],
        "scope": {"project": "fixture", "harness": "fixture-runner@1", "model": "fixture-model@1", "environment": "fixture-environment@1", "task_family": "resource-fetch"},
        "change_ref": "fixture:bounded-retry-v1", "verifier": {"kind": "reported", "reference": "fixture:acceptance-checks"},
        "holdout": {"reference": "fixture:frozen-manifest-v1", "frozen_at": "2026-01-01T00:00:00Z", "discovery_session_ids": [proposal["session_id"]], "task_ids": ["heldout-1"]},
        "started_at": "2026-01-02T00:00:00Z", "primary_metric": "latency_seconds",
        "pairs": [{"task_id": "heldout-1",
            "baseline": {"correctness": 1, "completion": 1, "latency_seconds": 100, "tokens": 1000, "cost": 0.05},
            "candidate": {"correctness": 1, "completion": 1, "latency_seconds": 60, "tokens": 700, "cost": 0.03},
            "baseline_overhead": {"latency_seconds": 5, "tokens": 0, "cost": 0},
            "candidate_overhead": {"latency_seconds": 10, "tokens": 100, "cost": 0.005},
        }],
    }


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "corpus")
        self.source = self.store.ingest_bytes(transcript(), "fixture.json", project="fixture")
        self.report = analyze(self.store, self.source["id"])
        self.proposal = self.report["proposals"][0]

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_only_linked_errors_support_failure_observation(self):
        self.assertEqual(self.report["observations"][0]["kind"], "repeated_failed_call")
        self.assertEqual(len(self.report["observations"][0]["outcome_event_ids"]), 3)
        other = self.store.ingest_bytes(transcript(statuses=("error", "unknown", "error")), "unknown.json", project="fixture")
        report = analyze(self.store, other["id"])
        self.assertNotIn("repeated_failed_call", [o["kind"] for o in report["observations"]])

    def test_success_interrupts_consecutive_failure_claim(self):
        other = self.store.ingest_bytes(transcript(statuses=("error", "error", "success", "error", "error")), "success.json", project="fixture")
        report = analyze(self.store, other["id"])
        self.assertNotIn("repeated_failed_call", [o["kind"] for o in report["observations"]])

    def test_analysis_is_idempotent_and_retains_source_refs(self):
        self.assertEqual(analyze(self.store, self.source["id"]), self.report)
        self.assertEqual(len(proposals(self.store)), 1)
        self.assertEqual(get_proposal(self.store, self.proposal["id"])["status"], "proposed")
        self.assertTrue(self.proposal["source_event_ids"])
        self.assertTrue(self.proposal["ideal_final_result"])
        self.assertEqual(self.proposal["cause_status"], "unestablished")
        self.assertEqual(self.proposal["triz_stage"], "framed_for_investigation")

    def test_growing_session_snapshots_reuse_proposal_identity(self):
        later = self.store.ingest_bytes(transcript(extra=True), "later.json", project="fixture")
        report = analyze(self.store, later["id"])
        self.assertNotEqual(later["id"], self.source["id"])
        self.assertEqual(report["proposals"][0]["id"], self.proposal["id"])
        self.assertEqual(len(proposals(self.store)), 1)

    def test_same_native_id_in_another_project_is_separate(self):
        other = self.store.ingest_bytes(transcript(extra=True), "other.json", project="other-project")
        report = analyze(self.store, other["id"])
        self.assertNotEqual(report["proposals"][0]["id"], self.proposal["id"])
        self.assertEqual(len(proposals(self.store, other["id"])), 1)

    def test_supported_report_uses_overhead_and_exact_scope(self):
        record = evaluation(self.proposal)
        result = evaluate(self.store, record)
        self.assertEqual(result["state"], "supported_by_reported_evidence")
        self.assertEqual(result["baseline_total"], 105)
        self.assertEqual(result["candidate_total"], 70)
        self.assertEqual(result["evidence_level"], "reported")
        global_view = matrix(self.store)
        self.assertFalse(global_view["global_support"])
        self.assertEqual(global_view["reported_evidence"][0]["recommendation"], "inspect_scoped_evidence")
        selected = matrix(self.store, scope=record["scope"])
        self.assertEqual(selected["reported_evidence"][0]["recommendation"], "candidate_for_reuse_in_exact_scope")
        other_scope = {**record["scope"], "environment": "different-environment@1"}
        self.assertEqual(matrix(self.store, scope=other_scope)["reported_evidence"], [])
        self.assertEqual(summary(self.store)["independently_verified_count"], 0)
        self.assertEqual(learning_proposals(self.store)[0]["status"], "proposed")
        self.assertEqual(learning_proposals(self.store)[0]["scoped_evidence"][0]["state"], "supported_by_reported_evidence")

    def test_template_cannot_be_imported_as_evidence(self):
        form = evidence_template(self.store, self.proposal["id"])
        self.assertEqual(form["proposal_id"], self.proposal["id"])
        with self.assertRaisesRegex(ValueError, "template"):
            evaluate(self.store, form)

    def test_evaluation_idempotency_and_conflict(self):
        record = evaluation(self.proposal)
        evaluate(self.store, record)
        self.assertTrue(evaluate(self.store, record)["duplicate"])
        self.assertEqual(len(evaluations(self.store)), 1)
        record["pairs"][0]["candidate"]["tokens"] = 701
        with self.assertRaisesRegex(ValueError, "different content"):
            evaluate(self.store, record)

    def test_regression_revokes_same_change_even_after_later_success(self):
        record = evaluation(self.proposal)
        evaluate(self.store, record)
        bad = copy.deepcopy(record)
        bad["evaluation_id"] = "fixture-evaluation-2"
        bad["pairs"][0]["candidate"]["correctness"] = 0
        self.assertEqual(evaluate(self.store, bad)["state"], "regressed")
        good = copy.deepcopy(record)
        good["evaluation_id"] = "fixture-evaluation-3"
        evaluate(self.store, good)
        evidence = matrix(self.store, scope=record["scope"])["reported_evidence"][0]
        self.assertEqual(evidence["state"], "regressed")
        self.assertEqual(evidence["recommendation"], "do_not_promote")
        self.assertEqual(len(evidence["unique_tasks"]), 1)
        self.assertEqual(len(evaluations(self.store)), 3)

    def test_hidden_overhead_can_reverse_apparent_improvement(self):
        record = evaluation(self.proposal)
        record["pairs"][0]["candidate_overhead"]["latency_seconds"] = 60
        self.assertEqual(evaluate(self.store, record)["outcome"], "regressed")

    def test_missing_quality_does_not_become_success(self):
        record = evaluation(self.proposal)
        del record["pairs"][0]["candidate"]["correctness"]
        with self.assertRaisesRegex(ValueError, "correctness is required"):
            evaluate(self.store, record)
        self.assertEqual(evaluations(self.store), [])

    def test_invalid_numbers_are_rejected(self):
        for value in (float("nan"), float("inf"), -1, True, 10 ** 400):
            with self.subTest(value=value):
                record = evaluation(self.proposal)
                record["pairs"][0]["candidate"]["latency_seconds"] = value
                with self.assertRaises(ValueError):
                    evaluate(self.store, record)

    def test_unknown_cost_stays_unknown(self):
        record = evaluation(self.proposal)
        record["pairs"][0]["candidate"]["cost"] = None
        result = evaluate(self.store, record)
        self.assertIsNone(result["totals"][0]["candidate"]["cost"])
        self.assertEqual(result["outcome"], "supported")

    def test_reject_discovery_holdout_overlap(self):
        record = evaluation(self.proposal)
        record["holdout"]["task_ids"] = [self.proposal["session_id"]]
        record["pairs"][0]["task_id"] = self.proposal["session_id"]
        with self.assertRaisesRegex(ValueError, "disjoint"):
            evaluate(self.store, record)

    def test_reject_unfrozen_holdout_and_unmatched_task(self):
        record = evaluation(self.proposal)
        record["holdout"]["frozen_at"] = "2026-01-03T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "frozen before"):
            evaluate(self.store, record)
        record = evaluation(self.proposal)
        record["pairs"][0]["task_id"] = "unlisted-task"
        with self.assertRaisesRegex(ValueError, "exactly match"):
            evaluate(self.store, record)

    def test_project_mismatch_and_fake_independence_are_rejected(self):
        record = evaluation(self.proposal)
        record["scope"]["project"] = "other"
        with self.assertRaisesRegex(ValueError, "known scope"):
            evaluate(self.store, record)
        record = evaluation(self.proposal)
        record["verifier"]["kind"] = "independent"
        with self.assertRaisesRegex(ValueError, "not independent"):
            evaluate(self.store, record)

    def test_failing_faster_never_counts_as_accepted_improvement(self):
        record = evaluation(self.proposal)
        for side in ("baseline", "candidate"):
            record["pairs"][0][side]["correctness"] = 0
            record["pairs"][0][side]["completion"] = 0
        self.assertEqual(evaluate(self.store, record)["outcome"], "not_supported")

    def review(self):
        return {"schema_version": "0.1", "session_id": self.source["id"], "findings": [{
            "key": "fixture-existing-cache", "title": "Fixture reviewed approach",
            "frame": "A reviewer reports that an existing cache could answer the repeated request.",
            "ideal_final_result": "The required current answer is available with no repeated external call.",
            "hypothesis": "An existing version-aware cache may preserve correctness while reducing time.",
            "contradiction": {"improve": "latency", "protect": "correctness"},
            "principles": ["P01", "P02"], "source_event_ids": self.proposal["source_event_ids"],
            "resources": ["The transcript's recorded requests and outcomes"],
            "target": "tool", "evidence_kind": "success",
        }]}

    def test_imported_success_is_a_hypothesis_and_deduplicates(self):
        review = self.review()
        result = import_review(self.store, review)
        imported = result["proposals"][0]
        self.assertEqual(imported["evidence_kind"], "success")
        self.assertEqual(imported["status"], "proposed")
        self.assertEqual(imported["cause_status"], "unestablished")
        self.assertEqual(imported["source_event_ids"], sorted(self.proposal["source_event_ids"]))
        self.assertEqual(result, import_review(self.store, review))
        self.assertEqual(len(proposals(self.store)), 2)

    def test_review_rejects_missing_refs_unknown_params_and_physical_matrix(self):
        review = self.review()
        review["findings"][0]["source_event_ids"] = [99999]
        with self.assertRaisesRegex(ValueError, "actual normalized events"):
            import_review(self.store, review)
        review = self.review()
        review["findings"][0]["contradiction"]["improve"] = "imaginary"
        with self.assertRaisesRegex(ValueError, "catalogue"):
            import_review(self.store, review)
        review = self.review()
        review["findings"][0]["contradiction"] = {"improve": "latency", "protect": "latency"}
        with self.assertRaisesRegex(ValueError, "physical contradiction"):
            import_review(self.store, review)

    def test_review_batch_is_atomic_and_cannot_promote_itself(self):
        review = self.review()
        first = review["findings"][0]
        first["status"] = "independently_verified"
        bad = copy.deepcopy(first)
        bad["key"] = "second-invalid"
        bad["source_event_ids"] = []
        review["findings"].append(bad)
        with self.assertRaises(ValueError):
            import_review(self.store, review)
        self.assertEqual(len(proposals(self.store)), 1)
        review["findings"].pop()
        self.assertEqual(import_review(self.store, review)["proposals"][0]["status"], "proposed")

    def test_unknown_parameter_metric_cannot_gain_spurious_support(self):
        review = self.review()
        review["findings"][0]["contradiction"] = {"improve": "adaptability", "protect": "correctness"}
        proposal = import_review(self.store, review)["proposals"][0]
        record = evaluation(proposal)
        result = evaluate(self.store, record)
        self.assertEqual(result["outcome"], "not_supported")
        self.assertIn("adaptability", [item["metric"] for item in result["unmet_requirements"]])


if __name__ == "__main__":
    unittest.main()
