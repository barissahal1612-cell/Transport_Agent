"""Session memory extension point (disabled in Phase 1).

No AgentCore Memory resource is used in Phase 1.
"""

from typing import Any, Optional


def get_memory_session_manager(session_id: str, actor_id: str) -> Optional[Any]:
    """Always return None: memory is disabled in Phase 1."""
    return None
