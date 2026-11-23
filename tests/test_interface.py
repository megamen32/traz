from copy import deepcopy
import http.client
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import unittest

from traz.server import LocalServer

REPO = Path(__file__).resolve().parents[1]


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="traz-http-test-")
        self.server = LocalServer(self.directory.name, port=0, token="synthetic-test-token")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, method, path, body=None, *, auth=True, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        hdrs = {"Authorization": "Bearer synthetic-test-token"} if auth else {}
        hdrs.update(headers or {})
        connection.request(method, path, body=body, headers=hdrs)
        response = connection.getresponse()
        data = response.read()
        result = (response.status, response.getheader("Content-Type"), data)
        connection.close()
        return result

    def test_upload_analyze_evaluate_regress_through_actual_http(self):
        fixture = (REPO / "examples/session-codex.jsonl").read_bytes()
        status, _, data = self.request("POST", "/api/ingest", fixture, headers={"X-Filename": "session.jsonl", "X-Project": "demo"})
        self.assertEqual(status, 200, data)
        imported = json.loads(data)
        proposal = imported["analysis"]["proposals"][0]
        self.assertEqual(imported["session"]["parse_status"], "ok")
        record = json.loads((REPO / "examples/evaluation-example.json").read_text())
        record["proposal_id"] = proposal["id"]
        record["holdout"]["discovery_session_ids"] = [imported["session"]["id"]]
        status, _, data = self.request("POST", "/api/evaluate", json.dumps(record))
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["outcome"], "supported")
        regression = deepcopy(record)
        regression["evaluation_id"] = "synthetic-http-regression"
        regression["pairs"][0]["candidate"]["correctness"] = 0
        status, _, data = self.request("POST", "/api/evaluate", json.dumps(regression))
        self.assertEqual(status, 200, data)
        self.assertEqual(json.loads(data)["outcome"], "regressed")
        status, _, data = self.request("GET", "/api/proposals")
        self.assertEqual(json.loads(data)[0]["scoped_evidence"][0]["state"], "regressed")
        status, _, data = self.request("GET", "/api/summary")
        self.assertEqual(json.loads(data)["session_count"], 1)
        self.assertEqual(json.loads(data)["evaluation_count"], 2)

    def test_api_requires_token_and_rejects_foreign_origin_or_host(self):
        status, _, _ = self.request("GET", "/api/sessions", auth=False)
        self.assertEqual(status, 401)
        status, _, _ = self.request("GET", "/api/sessions", headers={"Authorization": "Bearer é"})
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/api/ingest", b"private", headers={"Origin": "https://example.invalid"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("GET", "/api/sessions", headers={"Host": "attacker.invalid"})
        self.assertEqual(status, 403)
        status, _, data = self.request("GET", "/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), [])

    def test_invalid_report_does_not_stop_server_and_assets_are_available(self):
        for body in (b"{broken", b"[]", b"null"):
            status, _, _ = self.request("POST", "/api/evaluate", body)
            self.assertEqual(status, 400)
        for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
            status, content_type, body = self.request("GET", path, auth=False)
            self.assertEqual(status, 200)
            self.assertIn(mime, content_type)
            self.assertGreater(len(body), 100)
        status, _, _ = self.request("GET", "/../../index.sqlite3")
        self.assertEqual(status, 404)


class CLIWorkflowTests(unittest.TestCase):
    def test_source_checkout_cli_archive_roundtrip(self):
        with TemporaryDirectory(prefix="traz-cli-test-") as root:
            def cli(*args):
                result = subprocess.run([sys.executable, "-m", "traz", "--root", root, *args], cwd=REPO, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            fixture = REPO / "examples/session-codex.jsonl"
            session = cli("ingest", str(fixture), "--project", "demo")[0]
            report = cli("analyze", session["id"])
            self.assertEqual(report["observations"][0]["kind"], "repeated_failed_call")
            template = cli("evaluation-template", report["proposals"][0]["id"])
            self.assertIs(template["_template"], True)
            self.assertTrue(cli("verify")["ok"])
            restored = Path(root) / "restored.jsonl"
            cli("export", session["id"], str(restored))
            self.assertEqual(restored.read_bytes(), fixture.read_bytes())


if __name__ == "__main__":
    unittest.main()
