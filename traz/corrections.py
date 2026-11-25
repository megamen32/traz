"""Find user corrections in a session and measure the work that preceded them.

A correction is a user message that signals the agent did the wrong thing, did
not finish, or took too long. These messages are the cheapest available labels
of agent failure. Matching is lexical and therefore a heuristic observation,
not a verdict about cause.
"""

from __future__ import annotations

from datetime import datetime
import re

CORRECTIONS_VERSION = "0.1.0"

# Lowercase substrings. Russian and English, including profanity, because
# frustration is the strongest signal the user gives.
PATTERNS = {
    "not_done": (
        "ты починил", "починил или нет", "сделал или нет", "так что в итоге", "всё ещё не", "все еще не",
        "до сих пор не", "так и не", "did you fix", "is it fixed", "still not", "still broken", "still doesn't",
    ),
    "not_understood": (
        "не понял", "непонятно", "что ты имеешь", "объясни нормально", "проще", "i don't understand",
        "what do you mean", "not clear",
    ),
    "wrong_direction": (
        "не то", "не это", "я же просил", "я просил", "я сказал", "не надо было", "зачем ты", "зачем",
        "какая нахуя", "нахуя", "нахрена", "not what i", "i asked", "i said", "why did you", "that's wrong",
        "wrong",
    ),
    "repeat": ("опять", "снова", "again", "сколько можно", "в который раз"),
    "stop": ("стоп", "хватит", "остановись", "stop", "enough"),
    "frustration": ("нихуя", "хуй*", "хуя", "бля*", "ебуч*", "ебан*", "заеба*", "пизд*", "wtf", "fuck*"),
}
# A trailing "*" matches a word stem; other needles match whole words or phrases.

# Injected harness text is not a user correction.
INJECTED_PREFIXES = ("# agents.md", "<skill", "<environment_context", "<user_instructions", "<permissions",
                     "<system", "<command-", "# claude.md", "<local-command")
MAX_USER_TEXT = 4000


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_user_text(event):
    if event.get("type") != "message" or event.get("role") != "user":
        return False
    text = event.get("content")
    if not isinstance(text, str) or not text.strip():
        return False
    stripped = text.lstrip().lower()
    return len(text) <= MAX_USER_TEXT and not stripped.startswith(INJECTED_PREFIXES)


def classify(text: str) -> list[str]:
    lowered = " " + text.lower() + " "
    found = []
    for label, needles in PATTERNS.items():
        for needle in needles:
            stem = needle.endswith("*")
            pattern = r"(?<!\w)" + re.escape(needle.rstrip("*")) + ("" if stem else r"(?!\w)")
            if re.search(pattern, lowered):
                found.append(label)
                break
    return found


def corrections(store, session_id: str, *, excerpt: int = 300) -> dict:
    """Report corrections, the user turn they answer, and the work in between."""
    session = store.session(session_id)
    events = store.events(session["id"])
    turns = []
    current = None
    for event in events:
        if _is_user_text(event):
            current = {"event": event, "tool_calls": 0, "tool_errors": 0, "last_time": _time(event.get("timestamp"))}
            turns.append(current)
        elif current is not None:
            if event.get("type") == "tool_call":
                current["tool_calls"] += 1
            elif event.get("type") == "tool_result" and event.get("status") == "error":
                current["tool_errors"] += 1
            stamp = _time(event.get("timestamp"))
            if stamp:
                current["last_time"] = stamp

    found = []
    for index, turn in enumerate(turns):
        labels = classify(turn["event"]["content"])
        if not labels or index == 0:
            continue
        previous = turns[index - 1]
        start, end = _time(previous["event"].get("timestamp")), _time(turn["event"].get("timestamp"))
        found.append({
            "event_id": turn["event"]["event_id"],
            "labels": labels,
            "text": turn["event"]["content"][:excerpt],
            "answers_event_id": previous["event"]["event_id"],
            "answers_text": previous["event"]["content"][:excerpt],
            "tool_calls_before": previous["tool_calls"],
            "tool_errors_before": previous["tool_errors"],
            "minutes_before": round((end - start).total_seconds() / 60, 1) if start and end else None,
        })
    found.sort(key=lambda item: (item["tool_calls_before"], item["minutes_before"] or 0), reverse=True)
    longest = max(turns, key=lambda t: t["tool_calls"], default=None)
    return {
        "session_id": session["id"],
        "version": CORRECTIONS_VERSION,
        "user_turns": len(turns),
        "correction_count": len(found),
        "correction_rate": round(len(found) / max(len(turns) - 1, 1), 3),
        "longest_turn": {
            "event_id": longest["event"]["event_id"], "tool_calls": longest["tool_calls"],
            "text": longest["event"]["content"][:excerpt],
        } if longest else None,
        "corrections": found,
        "limitation": "Lexical match on user messages. A label marks where to look, not why the agent failed.",
    }
