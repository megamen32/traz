"""Correction detection and loop guard, with explicitly synthetic inputs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from traz import loop_guard
from traz.cli import main
from traz.corrections import classify, corrections
from traz.storage import Store

ROOT = Path(__file__).resolve().parents[1]


def _line(kind, stamp, **fields):
    return json.dumps({"timestamp": stamp, "type": "response_item", "payload": {"type": kind, **fields}}, ensure_ascii=False)


def _user(text, stamp):
    return _line("message", stamp, role="user", content=[{"type": "input_text", "text": text}])


def _call(index, stamp):
    return _line("function_call", stamp, name="exec_command", call_id=f"c{index}",
                 arguments=json.dumps({"cmd": f"echo synthetic {index}"}))


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.store = Store(self.base / "corpus")

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def test_classify(self):
        self.assertIn("not_done", classify("Нихуя не понял. Ты починил или нет?"))
        self.assertIn("frustration", classify("Нихуя не понял. Ты починил или нет?"))
        self.assertIn("not_understood", classify("Нихуя не понял"))
        self.assertIn("wrong_direction", classify("That's not what I asked for"))
        self.assertEqual(classify("Please add a test for the parser"), [])
        self.assertEqual(classify("исправь стопку тарелок"), [])

    def test_corrections_measure_preceding_work(self):
        lines = [json.dumps({"timestamp": "2026-01-01T10:00:00Z", "type": "session_meta",
                             "payload": {"id": "synthetic-corrections"}}),
                 _user("Synthetic: the admin page does not show", "2026-01-01T10:00:00Z")]
        lines += [_call(i, f"2026-01-01T10:{i + 1:02d}:00Z") for i in range(30)]
        lines.append(_user("# AGENTS.md injected text that says again and again", "2026-01-01T10:31:00Z"))
        lines.append(_user("Ты починил или нет?", "2026-01-01T10:40:00Z"))
        lines.append(_call(99, "2026-01-01T10:41:00Z"))
        lines.append(_user("Thanks, looks good", "2026-01-01T10:45:00Z"))
        path = self.base / "session.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        session = self.store.ingest(path, format="codex")
        report = corrections(self.store, session["id"])
        self.assertEqual(report["user_turns"], 3)
        self.assertEqual(report["correction_count"], 1)
        item = report["corrections"][0]
        self.assertIn("not_done", item["labels"])
        self.assertEqual(item["tool_calls_before"], 30)
        self.assertEqual(item["minutes_before"], 40.0)
        self.assertTrue(item["answers_text"].startswith("Synthetic: the admin page"))
        self.assertEqual(report["longest_turn"]["tool_calls"], 30)

    def test_cli(self):
        session = self.store.ingest(ROOT / "examples" / "session-codex.jsonl")
        self.store.close()
        with mock.patch("sys.stdout") as out:
            code = main(["--root", str(self.base / "corpus"), "corrections", session["id"]])
        self.assertEqual(code, 0)
        printed = "".join(call.args[0] for call in out.write.call_args_list)
        self.assertEqual(json.loads(printed)["session_id"], session["id"])
        self.store = Store(self.base / "corpus")


class LoopGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"TRAZ_LOOP_STATE": self.temporary.name, "TRAZ_LOOP_LIMIT": "3"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def tool(self, session="s1"):
        return loop_guard.handle({"hook_event_name": "PostToolUse", "session_id": session})

    def test_fires_at_limit_and_resets_on_user_message(self):
        self.assertIsNone(self.tool())
        self.assertIsNone(self.tool())
        output = self.tool()
        self.assertIn("3 tool calls", output["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.tool())
        loop_guard.handle({"hook_event_name": "UserPromptSubmit", "session_id": "s1"})
        self.assertIsNone(self.tool())
        self.assertIsNone(self.tool())
        self.assertIsNotNone(self.tool())

    def test_sessions_are_independent_and_ids_are_sanitized(self):
        self.tool("a")
        self.tool("a")
        self.assertIsNone(self.tool("../../b"))
        self.assertTrue(all(p.parent == Path(self.temporary.name) for p in Path(self.temporary.name).iterdir()))

    def test_script_runs_standalone_and_ignores_bad_input(self):
        script = ROOT / "traz" / "loop_guard.py"
        for data in ("not json", "[]", ""):
            run = subprocess.run([sys.executable, "-I", str(script)], input=data, text=True,
                                 capture_output=True, env=dict(os.environ))
            self.assertEqual((run.returncode, run.stdout), (0, ""))
        for _ in range(3):
            run = subprocess.run([sys.executable, "-I", str(script)], text=True, capture_output=True,
                                 input=json.dumps({"hook_event_name": "PostToolUse", "session_id": "cli"}),
                                 env=dict(os.environ))
        self.assertIn("loop guard", json.loads(run.stdout)["hookSpecificOutput"]["additionalContext"])


if __name__ == "__main__":
    unittest.main()
