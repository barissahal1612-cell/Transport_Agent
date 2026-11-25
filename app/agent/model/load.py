"""Bedrock model loader.

The model ID is never hardcoded. It is read from ``LOGISTIC_AI_MODEL_ID`` and
must be an inference profile ID with a scope prefix (``global.``, ``us.``,
``eu.`` ...). Discover the foundation model at deploy time with::

    aws bedrock list-foundation-models --by-provider Anthropic \
        --query "modelSummaries[?modelLifecycle.status=='ACTIVE']"

and prefix it, e.g. ``global.<foundation-model-id>``.
"""
from __future__ import annotations

import os
from typing import Any

from logistic_ai_shared_auth.common.errors import ConfigError

MODEL_ID_ENV = "LOGISTIC_AI_MODEL_ID"
MAX_TOKENS_ENV = "LOGISTIC_AI_MAX_TOKENS"
DEFAULT_MAX_TOKENS = 4096  # long table answers (e.g. all delayed trucks) exceed small caps
DEFAULT_TEMPERATURE = 0.1  # low: factual data answers
INFERENCE_PROFILE_PREFIXES: tuple[str, ...] = (
    "global.", "us.", "eu.", "apac.", "jp.", "au.", "ca.", "us-gov.",
)


def get_model_id() -> str:
    """Read and validate the inference profile ID from the environment."""
    model_id = (os.environ.get(MODEL_ID_ENV) or "").strip()
    if not model_id:
        raise ConfigError(
            f"{MODEL_ID_ENV} is not set. Set it to an inference profile ID such as "
            "'global.<foundation-model-id>' (discover with "
            "'aws bedrock list-foundation-models --by-provider Anthropic')."
        )
    prefix = next((p for p in INFERENCE_PROFILE_PREFIXES if model_id.startswith(p)), None)
    if prefix is None or len(model_id) == len(prefix):
        raise ConfigError(
            f"{MODEL_ID_ENV}={model_id!r} is not an inference profile ID. "
            "It must start with a scope prefix ('global.', 'us.', 'eu.', ...) "
            "followed by the foundation model ID."
        )
    return model_id


def get_region() -> str | None:
    """Region from AWS_REGION, then AWS_DEFAULT_REGION; None lets boto3 decide."""
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or None


def get_max_tokens() -> int:
    """Output token cap from ``LOGISTIC_AI_MAX_TOKENS`` (positive int); invalid -> default."""
    raw = (os.environ.get(MAX_TOKENS_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_TOKENS
    return value if value > 0 else DEFAULT_MAX_TOKENS


def load_model() -> Any:
    """Return a strands BedrockModel (no Bedrock call is made here)."""
    model_id = get_model_id()
    from strands.models import BedrockModel  # lazy: keeps cold start fast

    return BedrockModel(
        model_id=model_id,
        region_name=get_region(),
        max_tokens=get_max_tokens(),
        temperature=DEFAULT_TEMPERATURE,
    )
