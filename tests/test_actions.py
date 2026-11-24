"""Synthetic action-registry tests; artifacts are hashed but never executed."""

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from traz.actions import context, list_actions, record_action, record_receipt, verify_file
from traz.analysis import analyze, get_proposal
from traz.learning import evaluate, evaluations
from traz.storage import Store
from tests.test_learning import evaluation, transcript


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "corpus")
        source = self.store.ingest_bytes(transcript(), "synthetic.json", project="fixture")
        self.proposal = analyze(self.store, source["id"])["proposals"][0]
        self.marker = self.root / "must-not-execute"
        self.artifact = self.root / "guard.py"
        self.artifact.write_text(
            "from pathlib import Path\n"
            f"Path({str(self.marker)!r}).write_text('executed')\n"
            "raise RuntimeError('An action artifact must never execute here')\n",
            encoding="utf-8")
        self.digest = hashlib.sha256(self.artifact.read_bytes()).hexdigest()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def record(self, **changes):
        value = {
            "schema_version": "0.1", "proposal_id": self.proposal["id"],
            "change_ref": "fixture:bounded-retry-v1", "owner": "fixture-maintainer",
            "artifact": {"kind": "check", "locator": "fixture:guard.py", "sha256": self.digest},
            "applicability": {"project": "fixture", "task_family": "resource-fetch"},
            "instruction": "Inspect the existing bounded-retry guard before issuing a repeated fetch.",
            "trigger": "A repeated resource fetch is about to be attempted.",
            "retirement": "Retire after a failed acceptance check or replacement revision.",
        }
        return {**value, **changes}

    def action(self, **changes):
        return record_action(self.store, self.record(**changes))

    def receipt(self, action, kind, **changes):
        return {
            "schema_version": "0.1", "receipt_id": "fixture-" + kind,
            "action_id": action["action_id"], "kind": kind,
            "reference": "fixture:reported-" + kind, "details": "Synthetic reported evidence.",
            **changes,
        }

    def select(self, **kwargs):
        return context(self.store, "fixture", "resource-fetch", **kwargs)

    def test_revision_idempotency_immutability_and_inherited_provenance(self):
        first = self.action()
        again = self.action()
        self.assertFalse(first["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(first["action_id"], again["action_id"])
        self.assertEqual(first["source"]["evidence_scope"], self.proposal["scope"])
        self.assertEqual(first["source"]["source_event_ids"], self.proposal["source_event_ids"])
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.action(instruction="Different instruction for the same change reference.")
        second = self.action(change_ref="fixture:bounded-retry-v2", instruction="A revised guard.")
        self.assertNotEqual(first["action_id"], second["action_id"])
        self.assertEqual(len(list_actions(self.store)), 2)
        self.assertEqual(get_proposal(self.store, self.proposal["id"])["status"], "proposed")
        self.assertEqual(evaluations(self.store), [])

    def test_scope_cannot_be_wildcard_or_cross_project(self):
        for project in ("*", "unknown", "other-project"):
            with self.subTest(project=project), self.assertRaises(ValueError):
                self.action(applicability={"project": project, "task_family": "resource-fetch"})
        with self.assertRaises(ValueError):
            self.action(applicability={"project": "fixture"})
        for field, limit in (("instruction", 1600), ("trigger", 600), ("retirement", 500)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.action(**{field: "x" * (limit + 1)})

    def test_imported_claims_cannot_promote_integrity_or_efficacy(self):
        action = self.action()
        for kind in ("materialized", "local_check", "connected", "used"):
            receipt = record_receipt(self.store, self.receipt(action, kind))
            self.assertEqual(receipt["evidence_level"], "reported")
            self.assertTrue(record_receipt(self.store, self.receipt(action, kind))["duplicate"])
        with self.assertRaises(ValueError):
            record_receipt(self.store, self.receipt(action, "artifact_integrity"))
        with self.assertRaises(ValueError):
            record_receipt(self.store, self.receipt(action, "local_check", evidence_level="observed"))
        with self.assertRaisesRegex(ValueError, "different content"):
            record_receipt(self.store, self.receipt(action, "local_check", details="Changed claim."))
        with mock.patch("traz.actions._inspect_file", side_effect=AssertionError("Unbound path read")):
            self.assertEqual(self.select()["cards"], [])
        view = list_actions(self.store)[0]
        self.assertIsNone(view["implementation"]["latest_integrity"])
        self.assertEqual(view["efficacy"]["status"], "unknown")
        self.assertEqual(evaluations(self.store), [])

    def test_verified_file_yields_advice_without_execution_or_effectiveness_claim(self):
        action = self.action()
        record_receipt(self.store, self.receipt(action, "local_check"))
        receipt = verify_file(self.store, action["action_id"], self.artifact)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["evidence_level"], "observed")
        self.assertEqual(receipt["verification_scope"], "file_bytes_only")
        result = self.select()
        self.assertFalse(result["mandatory"])
        self.assertEqual(len(result["cards"]), 1)
        card = result["cards"][0]
        self.assertFalse(card["mandatory"])
        self.assertEqual(card["implementation"]["reported_kinds"], ["local_check"])
        self.assertEqual(card["efficacy"]["status"], "unknown")
        self.assertEqual(card["source"]["proposal_id"], self.proposal["id"])
        self.assertFalse(self.marker.exists())
        self.assertEqual(evaluations(self.store), [])

    def test_exact_declared_optional_constraints_are_required(self):
        action = self.action(applicability={
            "project": "fixture", "task_family": "resource-fetch", "environment": "fixture-env@1"})
        verify_file(self.store, action["action_id"], self.artifact)
        self.assertEqual(self.select()["cards"], [])
        self.assertEqual(self.select(context={"environment": "other-env@1"})["cards"], [])
        self.assertEqual(context(self.store, "other-project", "resource-fetch")["cards"], [])
        self.assertEqual(context(self.store, "fixture", "other-task")["cards"], [])
        self.assertEqual(len(self.select(context={"environment": "fixture-env@1"})["cards"]), 1)

    def test_drift_missing_file_and_hash_override_do_not_validate_revision(self):
        action = self.action()
        verify_file(self.store, action["action_id"], self.artifact)
        self.artifact.write_text("Changed synthetic artifact.", encoding="utf-8")
        self.assertEqual(self.select()["excluded"][0]["reason"], "artifact_drift_or_unavailable")
        mismatch = verify_file(self.store, action["action_id"], self.artifact)
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["outcome"], "mismatch")
        with self.assertRaisesRegex(ValueError, "immutable"):
            verify_file(self.store, action["action_id"], self.artifact,
                        expected_sha256=hashlib.sha256(self.artifact.read_bytes()).hexdigest())
        self.artifact.unlink()
        missing = verify_file(self.store, action["action_id"], self.artifact)
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["outcome"], "unavailable")
        self.assertEqual(self.select()["cards"], [])

    def test_repeated_observation_after_failure_is_latest_and_consecutive_is_idempotent(self):
        action = self.action()
        first = verify_file(self.store, action["action_id"], self.artifact)
        duplicate = verify_file(self.store, action["action_id"], self.artifact)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(first["receipt_id"], duplicate["receipt_id"])
        missing = verify_file(self.store, action["action_id"], self.root / "missing")
        self.assertFalse(missing["ok"])
        recovered = verify_file(self.store, action["action_id"], self.artifact)
        self.assertTrue(recovered["ok"])
        self.assertFalse(recovered["duplicate"])
        self.assertNotEqual(recovered["receipt_id"], first["receipt_id"])
        self.assertEqual(recovered["previous_observation_id"], missing["receipt_id"])
        self.assertEqual(list_actions(self.store)[0]["implementation"]["latest_integrity"]["receipt_id"],
                         recovered["receipt_id"])
        self.assertTrue(verify_file(self.store, action["action_id"], self.artifact)["duplicate"])
        self.assertEqual(len(list_actions(self.store)[0]["implementation"]["receipts"]), 3)
        self.assertEqual(len(self.select()["cards"]), 1)

    def test_regular_file_with_unreported_bytes_cannot_verify_an_empty_prefix(self):
        action = self.action(artifact={"kind": "check", "locator": "fixture:virtual",
                                      "sha256": hashlib.sha256(b"").hexdigest()})
        original_fstat = os.fstat

        def zero_size(descriptor):
            info = original_fstat(descriptor)
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_size=0,
                                   st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns,
                                   st_mode=info.st_mode)

        with mock.patch("traz.actions.os.fstat", side_effect=zero_size):
            result = verify_file(self.store, action["action_id"], self.artifact)
        self.assertFalse(result["ok"])
        self.assertEqual(result["outcome"], "changed")
        self.assertIsNone(result["observed_sha256"])

    def test_retirement_is_terminal_for_only_its_revision(self):
        action = self.action()
        verify_file(self.store, action["action_id"], self.artifact)
        record_receipt(self.store, self.receipt(action, "retired"))
        record_receipt(self.store, self.receipt(action, "used"))
        verify_file(self.store, action["action_id"], self.artifact)
        self.assertEqual(self.select()["excluded"][0]["reason"], "retired")
        replacement = self.action(change_ref="fixture:bounded-retry-v2")
        verify_file(self.store, replacement["action_id"], self.artifact)
        self.assertEqual([c["action_id"] for c in self.select()["cards"]], [replacement["action_id"]])

    def test_efficacy_stays_separate_and_requires_exact_complete_scope(self):
        action = self.action()
        verify_file(self.store, action["action_id"], self.artifact)
        report = evaluation(self.proposal)
        evaluate(self.store, report)
        optional = {key: value for key, value in report["scope"].items()
                    if key not in {"project", "task_family"}}
        self.assertEqual(self.select()["cards"][0]["efficacy"]["status"], "unknown")
        exact = self.select(context=optional)["cards"][0]
        self.assertEqual(exact["efficacy"]["status"], "supported_by_reported_evidence")
        self.assertEqual(exact["efficacy"]["evidence_level"], "reported")
        self.assertEqual(list_actions(self.store)[0]["efficacy"]["status"], "unknown")
        record_receipt(self.store, self.receipt(action, "connected"))
        verify_file(self.store, action["action_id"], self.artifact)
        self.assertEqual(len(evaluations(self.store)), 1)

    def test_compatible_regression_cannot_disappear_by_omitting_scope(self):
        action = self.action()
        verify_file(self.store, action["action_id"], self.artifact)
        report = evaluation(self.proposal)
        report["pairs"][0]["candidate"]["correctness"] = 0
        evaluate(self.store, report)
        optional = {key: value for key, value in report["scope"].items()
                    if key not in {"project", "task_family"}}
        partial = self.select()
        self.assertEqual(partial["cards"], [])
        self.assertEqual(partial["excluded"][0]["reason"], "need_full_scope_to_resolve_regression")
        exact = self.select(context=optional)
        self.assertEqual(exact["cards"], [])
        self.assertEqual(exact["excluded"][0]["reason"], "reported_efficacy_regression")
        unknown = self.select(context={**optional, "model": "unknown"})
        self.assertEqual(unknown["excluded"][0]["reason"], "need_full_scope_to_resolve_regression")
        unrelated = self.select(context={**optional, "model": "different-model@1"})
        self.assertEqual(len(unrelated["cards"]), 1)
        self.assertEqual(unrelated["cards"][0]["efficacy"]["status"], "unknown")
        self.assertEqual(len(evaluations(self.store)), 1)

    def test_entire_context_envelope_obeys_card_and_character_limits(self):
        for i in range(6):
            action = self.action(change_ref=f"fixture:revision-{i}")
            verify_file(self.store, action["action_id"], self.artifact)
        for budget in (512, 2000, 6000):
            with self.subTest(budget=budget):
                result = self.select(max_chars=budget)
                self.assertLessEqual(len(encoded(result)), budget)
                self.assertLessEqual(len(result["cards"]), 5)
        self.assertEqual(len(self.select(limit=1)["cards"]), 1)
        for kwargs in ({"limit": 6}, {"max_chars": 6001}, {"limit": True}, {"max_chars": 511}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.select(**kwargs)

    def test_budget_holds_when_exclusion_count_grows_without_cards(self):
        project = "p" * 100
        with mock.patch("traz.actions.list_actions", return_value=[]):
            probe = context(self.store, project, "x")
            family = "x" * (1 + 512 - len(encoded(probe)))
            self.assertTrue(1 <= len(family) <= 200)
            self.assertEqual(len(encoded(context(self.store, project, family, max_chars=512))), 512)
        mismatched = [{"action_id": f"a_{i}", "applicability": {"project": "other"}} for i in range(100)]
        with mock.patch("traz.actions.list_actions", return_value=mismatched):
            result = context(self.store, project, family, max_chars=512)
        self.assertEqual(result["excluded_count"], 100)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["cards"], [])
        self.assertLessEqual(len(encoded(result)), 512)


if __name__ == "__main__":
    unittest.main()
