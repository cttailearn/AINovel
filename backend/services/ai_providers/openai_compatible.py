from __future__ import annotations

from typing import Any, Dict, List

from .base import PreparedRequest


class OpenAICompatibleProvider:
    name = "openai-compatible"

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
            endpoint=f"{model_url.rstrip('/')}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            body={
                "model": model_name,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
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
        messages: List[Dict[str, str]]
        if system_prompt:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        else:
            messages = [{"role": "user", "content": user_prompt}]
        return PreparedRequest(
            endpoint=f"{model_url.rstrip('/')}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            body={
                "model": model_name,
                "max_tokens": 1,
                "messages": messages,
            },
        )

    def extract_text(self, payload: Dict[str, Any]) -> str:
        if not payload:
            return ""
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        return (message.get("content") or "").strip()

    def extract_usage_tokens(self, payload: Dict[str, Any]) -> Dict[str, int]:
        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total_tokens = int(
            usage.get("total_tokens") or (prompt_tokens + completion_tokens)
        )
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
