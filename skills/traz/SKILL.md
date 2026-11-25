---
name: traz
description: Use when the user invokes TRAZ during a session because the agent is doing the wrong thing, not finishing, or taking too long on something simple. Unblocks the current task first, then makes the failure impossible to repeat with the strongest available mechanism. For analysing many past sessions use traz-review instead.
---

# TRAZ: unblock now, prevent forever

The user called TRAZ because something went wrong. Their correction is the
evidence. Do not defend the previous approach. Do not write a report instead
of acting. This invocation ends with the task moving and one prevention in place.

## 1. Unblock (first, within a few tool calls)

1. Write the user's goal in their own words, one line. If your recent work
   drifted from it, say so plainly.
2. Name the cheapest decisive check: the thing the user would do to see that it
   works (open the page and log in, run the command, call the endpoint with real
   credentials). Has it been run? If not, run it now, before any more diagnosis.
   Anonymous probes, partial checks and log reading do not replace it.
3. Classify the blocker and act:
   - Technical, reversible: do the next action now.
   - Needs the owner's decision (accept or revert a config, spend money, touch
     an irreversible state): ask ONE question with concrete options and your
     recommended default. Do not keep investigating around it.
   - Irreversible or destructive: ask first, as usual.
4. Stop anything that repeats without new information: equivalent commands,
   polling, brute-force search, waiting on a process you do not own.

A file that records a plan is not progress. Write one only if the user asks.

## 2. Prevent (TRIZ, short)

Answer briefly, from the evidence in this session:

- What did the user want, and what did the agent do instead?
- Contradiction: which reasonable rule pushed the agent the wrong way (for
  example "be careful in production" against "finish the task")?
- Resolution by separation, not compromise: under which condition, time or
  level does each side apply (for example caution only for irreversible steps)?

Then put the fix in the strongest place you can reach, in this order:

1. Code or tool contract (fix the broken test, script, default or error message).
2. Automatic check or hook (it runs without anyone remembering it).
3. One or two lines in the relevant AGENTS.md or CLAUDE.md.
4. A skill change, only when judgment is truly required.

Make the change now if it is in reach and reversible, and verify it once. If
it belongs to another owner or repository, give the user the exact diff.

## 3. Reply

Three short lines, in the user's language:

- What went wrong (one sentence, no hedging).
- What you did now and its observed result.
- What now prevents it, and where.

Then return to the original task. Optional: record the change in the TRAZ
corpus (`python -m traz action`, see docs/ACTIONS.md) after the user is answered.
