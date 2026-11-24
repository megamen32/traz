"""Exercise the public action interface without executing an artifact or session."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


REPO = Path(__file__).resolve().parents[1]


class ActionCLIWorkflowTests(unittest.TestCase):
    def test_new_task_context_is_bounded_scoped_and_separate_from_efficacy(self):
        with TemporaryDirectory(prefix="traz-action-cli-") as directory:
            root = Path(directory) / "corpus"

            def cli(*args, expected=0):
                result = subprocess.run(
                    [sys.executable, "-m", "traz", "--root", str(root), *args],
                    cwd=REPO, capture_output=True, text=True, timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                return json.loads(result.stdout), result.stdout.strip()

            session, _ = cli("ingest", str(REPO / "examples/session-codex.jsonl"), "--project", "demo")
            analysis, _ = cli("analyze", session[0]["id"])
            artifact = Path(directory) / "guidance.txt"
            artifact.write_text("Synthetic advice for a new task. Never resume its source task.\n")
            record = {
                "schema_version": "0.1",
                "proposal_id": analysis["proposals"][0]["id"],
                "change_ref": "synthetic-cli-guidance-v1",
                "owner": "synthetic-existing-runner",
                "artifact": {
                    "kind": "guidance", "locator": str(artifact),
                    "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                },
                "applicability": {"project": "demo", "task_family": "package-release"},
                "instruction": "Read the scoped evidence before the relevant new task.",
                "trigger": "A new package-release task is explicitly assigned.",
                "retirement": "Retire when the existing package gate replaces this advice.",
            }
            record_path = Path(directory) / "action.json"
            record_path.write_text(json.dumps(record))
            action, _ = cli("action", str(record_path))
            before, _ = cli("context", "--project", "demo", "--task-family", "package-release")
            self.assertEqual(before["cards"], [])
            observed, _ = cli("action-verify", action["action_id"], str(artifact))
            self.assertIs(observed["ok"], True)
            self.assertEqual(observed["verification_scope"], "file_bytes_only")
            receipt = {
                "schema_version": "0.1", "receipt_id": "synthetic-connected",
                "action_id": action["action_id"], "kind": "connected",
                "reference": "synthetic:runner-receipt",
                "details": "Fixture claim only; no real runner was connected.",
            }
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))
            imported, _ = cli("action-receipt", str(receipt_path))
            self.assertEqual(imported["evidence_level"], "reported")
            ctx, rendered = cli("context", "--project", "demo", "--task-family", "package-release")
            self.assertEqual(len(ctx["cards"]), 1)
            self.assertLessEqual(len(rendered), 6000)
            self.assertIs(ctx["mandatory"], False)
            foreign, _ = cli("context", "--project", "other", "--task-family", "package-release")
            self.assertEqual(foreign["cards"], [])
            artifact.write_text("Changed bytes must not inherit the previous integrity receipt.\n")
            drift, _ = cli("context", "--project", "demo", "--task-family", "package-release")
            self.assertEqual(drift["cards"], [])
            mismatch, _ = cli("action-verify", action["action_id"], str(artifact), expected=1)
            self.assertIs(mismatch["ok"], False)
            summary, _ = cli("summary")
            self.assertEqual(summary["evaluation_count"], 0)
            self.assertEqual(summary["session_count"], 1)
            self.assertEqual(summary["independently_verified_count"], 0)


if __name__ == "__main__":
    unittest.main()
