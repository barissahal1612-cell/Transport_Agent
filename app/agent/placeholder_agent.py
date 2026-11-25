"""Phase 1 placeholder agent.

A thin, Strands-compatible wrapper that never calls Amazon Bedrock. For every
valid prompt it streams the same fixed ``PLACEHOLDER_RESPONSE`` text as async
chunks. The prompt is intentionally ignored and never logged.

Nothing is created at import time; call ``build_placeholder_agent()`` lazily
(e.g. from ``main._get_agent()``).
"""

from collections.abc import AsyncIterator

PLACEHOLDER_RESPONSE: str = (
    "Yapay zekâ yanıtları henüz kullanılamıyor. "
    "Logistics AI Assistant bu aşamada yalnızca kimlik doğrulama ve yetkilendirme sağlar."
)

# Fixed chunk boundaries so that the streamed text is identical on every call.
_CHUNK_SIZE: int = 16


def _split_chunks(text: str, size: int = _CHUNK_SIZE) -> tuple[str, ...]:
    return tuple(text[i : i + size] for i in range(0, len(text), size))


_CHUNKS: tuple[str, ...] = _split_chunks(PLACEHOLDER_RESPONSE)


class PlaceholderAgent:
    """Agent skeleton that streams a constant response without any model call."""

    async def stream(self, prompt: str) -> AsyncIterator[str]:
        """Yield the fixed Placeholder_Response in chunks; ``prompt`` is unused."""
        del prompt  # not used, not logged
        for chunk in _CHUNKS:
            yield chunk


def build_placeholder_agent() -> PlaceholderAgent:
    """Create the placeholder agent. Makes no network or Bedrock calls."""
    return PlaceholderAgent()
