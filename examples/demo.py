"""Exercise the learning ledger with synthetic data in a disposable corpus."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from traz.analysis import analyze
from traz.learning import evaluate, matrix
from traz.storage import Store


def main():
    examples = Path(__file__).parent
    with TemporaryDirectory(prefix="traz-synthetic-demo-") as directory, Store(directory) as store:
        session = store.ingest(examples / "session-codex.jsonl", project="demo")
        report = analyze(store, session["id"])
        proposal = report["proposals"][0]
        record = json.loads((examples / "evaluation-example.json").read_text())
        record["proposal_id"] = proposal["id"]
        record["holdout"]["discovery_session_ids"] = [session["id"], session["logical_session_id"]]
        positive = evaluate(store, record)
        first = matrix(store, scope=record["scope"])["reported_evidence"][0]
        regression = deepcopy(record)
        regression["evaluation_id"] = "SYNTHETIC-regression"
        regression["pairs"][0]["candidate"]["latency_seconds"] = 150
        negative = evaluate(store, regression)
        final = matrix(store, scope=record["scope"])["reported_evidence"][0]
        integrity = store.verify()
        if positive["outcome"] != "supported" or final["state"] != "regressed" or not integrity["ok"]:
            raise RuntimeError("The synthetic learning loop did not meet its acceptance checks")
        print(json.dumps({
            "synthetic_only": True,
            "purpose": "Verify bookkeeping and state changes, not real agent improvement",
            "archive_integrity": integrity["ok"],
            "observations": len(report["observations"]),
            "after_positive_report": first["state"],
            "after_regression_report": final["state"],
            "regression_outcome": negative["outcome"],
            "independently_verified": False,
            "corpus": "Disposable demonstration; no user transcript was read",
        }, indent=2))


if __name__ == "__main__":
    main()
