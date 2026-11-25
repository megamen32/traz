#!/usr/bin/env python3
"""Hook that interrupts long silent tool runs. Standard library only.

Counts tool calls since the last user message. At every LIMIT calls it tells
the agent to stop and report to the user: goal, the cheapest decisive check
and whether it has run, the blocker, and one question. A user message resets
the counter. It never blocks a tool and never runs anything from its input.

Wire it as a Claude Code hook for UserPromptSubmit and PostToolUse (see
docs/LOOP_GUARD.md). Environment: TRAZ_LOOP_LIMIT (default 25),
TRAZ_LOOP_STATE (default: a per-user directory under the system temp dir).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import tempfile

DEFAULT_LIMIT = 25

MESSAGE = (
    "TRAZ loop guard: {count} tool calls since the user's last message. Stop and reply to the user "
    "now, in at most five lines: (1) their goal in their words, (2) the cheapest check that would "
    "decide it the way the user would see it, and whether you have run it, (3) what is blocking you, "
    "(4) the next action, or ONE question if it needs their decision. Do not write a report file "
    "instead of replying. Continue only if the next action is reversible and clearly advances the goal."
)


def _limit() -> int:
    try:
        value = int(os.environ.get("TRAZ_LOOP_LIMIT", DEFAULT_LIMIT))
    except ValueError:
        return DEFAULT_LIMIT
    return value if value > 0 else DEFAULT_LIMIT


def _state_dir() -> Path:
    explicit = os.environ.get("TRAZ_LOOP_STATE")
    if explicit:
        return Path(explicit)
    user = re.sub(r"[^A-Za-z0-9_.-]", "_", os.environ.get("USER", "user"))
    return Path(tempfile.gettempdir()) / f"traz-loop-guard-{user}"


def _state_file(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")[:128]
    return _state_dir() / f"{safe}.json"


def _read(path: Path) -> int:
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("count", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def _write(path: Path, count: int) -> None:
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"count": count}), encoding="utf-8")
        temporary.replace(path)
    except OSError:
        pass


def handle(payload: dict) -> dict | None:
    """Return the hook output for one event, or None for no output."""
    event = payload.get("hook_event_name")
    path = _state_file(str(payload.get("session_id", "")))
    if event == "UserPromptSubmit":
        _write(path, 0)
        return None
    if event != "PostToolUse":
        return None
    count = _read(path) + 1
    _write(path, count)
    if count % _limit():
        return None
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                   "additionalContext": MESSAGE.format(count=count)}}


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    output = handle(payload)
    if output:
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
