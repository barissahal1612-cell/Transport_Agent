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
