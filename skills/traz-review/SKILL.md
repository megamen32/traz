---
name: traz-review
description: Use when the user asks to review many past agent sessions (for example "analyse all Codex sessions from today") to find repeated failures and decide what to change. Produces at most three concrete changes ranked by wasted effort, and checks whether earlier changes worked. Not for unblocking a live session; use traz for that.
---

# TRAZ review: learn from many sessions

Output is not a report. Output is at most three ready changes (diffs) that the
user approves or rejects, plus a verdict on earlier changes. Nothing is written
to rules, skills or code without the user's approval.

## 1. Collect

- Take the exact window the user named. Find transcripts by explicit location
  (Codex: `~/.codex/sessions/YYYY/MM/DD/*.jsonl`; Claude Code:
  `~/.claude/projects/*/*.jsonl`). Do not guess a newest file.
- Archive them losslessly: `python -m traz --root CORPUS ingest FILE --project P`.
  The corpus lives outside any repository.

## 2. Find the failures (user corrections are the labels)

- For each session: `python -m traz --root CORPUS corrections SNAPSHOT`.
  It lists user messages such as "did you fix it?", "not what I asked",
  profanity or "again", with the tool calls and minutes spent before each.
- Rank by waste: tool calls and minutes before the correction. Sessions with a
  very long silent turn (`longest_turn`) and no correction are also candidates.
- Optional: run the installed Retro skill on the top sessions for mechanical
  facts (retries, polling, oversized output). Treat its counts as facts, not causes.

## 3. Explain each top failure (read the evidence, not the summary)

Read the events around each correction. For each, answer:

- Goal in the user's words, and what the agent did instead.
- The cheapest decisive check, and when it was first run (or never).
  In practice this is the most common root cause.
- The contradiction that drove the behaviour and its separation.
- Whether the same pattern appears in other sessions in the window.

Frequency is a reason to look, not proof. Keep a cause as a hypothesis until
the evidence shows the mechanism.

## 4. Propose at most three changes

Use the same ladder as traz: code or tool contract, then check or hook, then
one or two lines in AGENTS.md or CLAUDE.md, then a skill. Each proposal has:

- The pattern and the sessions it came from (snapshot and event IDs).
- The exact diff and where it goes.
- The metric that should fall (corrections per session for this pattern, tool
  calls before the decisive check) and a review date.

## 5. Judge earlier changes

List earlier changes (`python -m traz actions`). For each one whose review date
has passed, check whether its pattern still appears in the new window.
Recommend: keep, revise, or remove. A rule that changed nothing gets removed.
Record the decision with `python -m traz action-receipt` once the user agrees.
