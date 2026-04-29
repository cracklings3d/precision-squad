"""Shared opencode model resolution helpers."""

from __future__ import annotations

import os


def resolve_opencode_model(model: str | None) -> str | None:
    """Resolve an explicit or environment-provided opencode model identifier."""
    explicit = (model or "").strip()
    configured = os.getenv("CUSTOM_OPENAI_MODEL_NAME", "").strip()
    candidate = explicit or configured
    if not candidate:
        return None
    if "/" in candidate:
        return candidate
    if candidate != "custom-openai-model":
        return candidate
    if not configured:
        return candidate
    if "/" in configured:
        return configured
    return f"{candidate}/{configured}"
