# Loop guard

`traz/loop_guard.py` stops long silent tool runs. It counts tool calls since the
user's last message. Every `TRAZ_LOOP_LIMIT` calls (default 25) it adds a message
to the agent's context: reply to the user now with the goal, the cheapest
decisive check and whether it ran, the blocker, and the next action or one
question. A user message resets the counter.

It never blocks a tool, makes no network calls, and uses only the standard
library. State is one small counter file per session under the system temp
directory, or under `TRAZ_LOOP_STATE`.

## Claude Code

This repository enables it in `.claude/settings.json`. To enable it for every
project, copy the file somewhere stable and add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 /path/to/loop_guard.py"}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 /path/to/loop_guard.py"}]}]
  }
}
```

## Other harnesses

The script reads one JSON object on stdin with `hook_event_name`
(`UserPromptSubmit` or `PostToolUse`) and `session_id`, and prints Claude Code
hook output. OpenCode hook support has not been tested here.

## Codex

Codex CLI 0.170.0 uses the same event names, input fields and
`hookSpecificOutput.additionalContext` output (checked against the schemas in
the installed binary, not yet against a live session). Hooks need
`hooks = true` under `[features]` in `~/.codex/config.toml`. Add the command
to `~/.codex/hooks.json` under `UserPromptSubmit` and `PostToolUse` (matcher
`*`). Codex runs a new hook only after you trust it in the `/hooks` review.

## Status

Mechanism tested with synthetic events. Whether it shortens real sessions has
not been measured. Compare `traz corrections` results before and after enabling it.
