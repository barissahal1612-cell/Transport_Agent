"""Payload parsing for the Logistics AI Agent_Backend.

The payload carries a ``prompt`` and an informational ``actorId``. ``actorId``
is never a source of role or authorization information (Req 3.7, 13.9).
"""

from typing import Any

EMPTY_PROMPT_ERROR = "prompt is required and must not be empty"
INVALID_PAYLOAD_ERROR = "payload must be a JSON object"
INVALID_PROMPT_ERROR = "prompt must be a string"
INVALID_ACTOR_ID_ERROR = "actorId must be a string"


def parse_payload(payload: Any) -> tuple[str, str | None, str | None]:
    """Parse a request payload into ``(prompt, actor_id, parse_error)``.

    On a validation failure ``parse_error`` is a non-empty message, ``prompt``
    is ``""`` and the caller must not invoke the model or agent. A missing,
    ``None`` or whitespace-only ``prompt`` is a validation error. ``actor_id``
    is ``None`` when absent or ``None``. A valid prompt is returned unchanged.
    """
    if not isinstance(payload, dict):
        return "", None, INVALID_PAYLOAD_ERROR

    actor_id = payload.get("actorId")
    if actor_id is not None and not isinstance(actor_id, str):
        return "", None, INVALID_ACTOR_ID_ERROR

    prompt = payload.get("prompt")
    if prompt is None:
        return "", actor_id, EMPTY_PROMPT_ERROR
    if not isinstance(prompt, str):
        return "", actor_id, INVALID_PROMPT_ERROR
    if not prompt.strip():
        return "", actor_id, EMPTY_PROMPT_ERROR

    return prompt, actor_id, None


# --------------------------------------------------------------------------- history
MAX_HISTORY_MESSAGES = 10
MAX_HISTORY_CONTENT_CHARS = 2000
_HISTORY_ROLES = frozenset({"user", "assistant"})


def parse_history(payload: Any) -> list[dict[str, str]]:
    """Return the validated prior chat messages of the current request.

    The history is client supplied and therefore untrusted data: only dicts with
    ``role`` in {user, assistant} and a non-blank ``str`` content are kept (``system``/
    ``tool`` roles and anything else are dropped), at most the last
    ``MAX_HISTORY_MESSAGES`` messages, each truncated to ``MAX_HISTORY_CONTENT_CHARS``.
    The result strictly alternates user/assistant, starts with ``user`` and ends with
    ``assistant`` (the new prompt is the next user turn), as the model API requires.
    A missing or malformed history yields ``[]``; it is never an error.
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("history")
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if not isinstance(role, str) or role not in _HISTORY_ROLES or not isinstance(content, str):
            continue
        if not content.strip():
            continue
        cleaned.append({"role": role, "content": content[:MAX_HISTORY_CONTENT_CHARS]})
    cleaned = cleaned[-MAX_HISTORY_MESSAGES:]
    merged: list[dict[str, str]] = []
    for msg in cleaned:
        if not merged and msg["role"] != "user":
            continue  # must start with a user turn
        if merged and merged[-1]["role"] == msg["role"]:
            joined = merged[-1]["content"] + "\n" + msg["content"]
            merged[-1] = {"role": msg["role"], "content": joined[:MAX_HISTORY_CONTENT_CHARS]}
        else:
            merged.append(msg)
    while merged and merged[-1]["role"] == "user":
        merged.pop()  # unanswered turn (failed request): the new prompt follows directly
    return merged


def history_to_strands_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Convert validated history to Strands ``Message`` dicts (text blocks only)."""
    return [{"role": m["role"], "content": [{"text": m["content"]}]} for m in history]
