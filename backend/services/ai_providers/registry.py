from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import ChatProvider
from .openai_compatible import OpenAICompatibleProvider

_ANTHROPIC = AnthropicProvider()
_OPENAI_COMPATIBLE = OpenAICompatibleProvider()


def get_provider(provider_name: str) -> ChatProvider:
    if (provider_name or "").lower() == "anthropic":
        return _ANTHROPIC
    return _OPENAI_COMPATIBLE
