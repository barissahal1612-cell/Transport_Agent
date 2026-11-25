"""Model loader extension point (inert in Phase 1).

Phase 1 makes no Amazon Bedrock calls; the agent returns a deterministic
placeholder response. When a model is added in a later phase, the model ID
must use the inference profile format with a scope prefix (for example
``global.<foundation-model-id>``), and the foundation model ID must be chosen
at deploy time from the output of::

    aws bedrock list-foundation-models --by-provider Anthropic \
        --query "modelSummaries[?modelLifecycle.status=='ACTIVE']"

No model ID is hardcoded here.
"""

from typing import Any


def load_model() -> Any:
    """Not available in Phase 1; no model is configured."""
    raise NotImplementedError("Model loading is disabled in Phase 1 (no Bedrock calls).")
