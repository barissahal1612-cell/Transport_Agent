"""System prompt extension point (inert in Phase 1; no model is invoked)."""

SYSTEM_PROMPT: str = ""


def get_system_prompt() -> str:
    """Return the system prompt. Empty in Phase 1."""
    return SYSTEM_PROMPT
