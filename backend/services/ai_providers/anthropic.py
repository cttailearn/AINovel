from __future__ import annotations

from typing import Any, Dict, List

from .base import PreparedRequest


class AnthropicProvider:
    name = "anthropic"

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
    ) -> PreparedRequest:
        return PreparedRequest(
            endpoint=f"{model_url.rstrip('/')}/v1/messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            body={
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )

    def build_probe_request(
        self,
        *,
        model_url: str,
        api_key: str,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> PreparedRequest:
        return PreparedRequest(
            endpoint=f"{model_url.rstrip('/')}/v1/messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
            },
            body={
                "model": model_name,
                "max_tokens": 1,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )

    def extract_text(self, payload: Dict[str, Any]) -> str:
        if not payload:
            return ""
        content = payload.get("content")
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts).strip()
        if isinstance(content, str):
            return content.strip()
        return ""

    def extract_usage_tokens(self, payload: Dict[str, Any]) -> Dict[str, int]:
        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        total_tokens = int(
            usage.get("total_tokens") or (prompt_tokens + completion_tokens)
        )
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
