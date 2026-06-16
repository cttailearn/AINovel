from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class PreparedRequest:
    endpoint: str
    headers: Dict[str, str]
    body: Dict[str, Any]


class ChatProvider(Protocol):
    name: str

    def build_chat_request(
        self,
        *,
        model_url: str,
        api_key: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> PreparedRequest: ...

    def build_probe_request(
        self,
        *,
        model_url: str,
        api_key: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> PreparedRequest: ...

    def extract_text(self, payload: Dict[str, Any]) -> str: ...

    def extract_usage_tokens(self, payload: Dict[str, Any]) -> Dict[str, int]: ...
