from __future__ import annotations

from services.ai_providers import get_provider
from services.ai_service import parse_json_object


def test_anthropic_provider_builds_messages_endpoint():
    provider = get_provider("anthropic")

    prepared = provider.build_chat_request(
        model_url="https://api.example.com/",
        api_key="sk-test",
        model_name="claude-3-5-sonnet",
        system_prompt="system",
        user_prompt="hello",
        temperature=0.3,
        max_tokens=128,
    )

    assert prepared.endpoint == "https://api.example.com/v1/messages"
    assert prepared.headers["anthropic-version"] == "2023-06-01"
    assert prepared.body["messages"] == [{"role": "user", "content": "hello"}]
    assert prepared.body["system"] == "system"


def test_openai_compatible_provider_omits_empty_system_in_probe():
    provider = get_provider("openai")

    prepared = provider.build_probe_request(
        model_url="https://api.example.com/",
        api_key="sk-test",
        model_name="gpt-4o-mini",
        system_prompt="",
        user_prompt="ping",
    )

    assert prepared.endpoint == "https://api.example.com/v1/chat/completions"
    assert prepared.body["messages"] == [{"role": "user", "content": "ping"}]


def test_provider_extract_usage_tokens_are_provider_specific():
    anthropic = get_provider("anthropic")
    openai = get_provider("openai")

    assert anthropic.extract_usage_tokens(
        {"usage": {"input_tokens": 12, "output_tokens": 7}}
    ) == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }
    assert openai.extract_usage_tokens(
        {"usage": {"prompt_tokens": 5, "completion_tokens": 9}}
    ) == {
        "prompt_tokens": 5,
        "completion_tokens": 9,
        "total_tokens": 14,
    }


def test_parse_json_object_extracts_json_block_from_markdown():
    payload = """```json
    {
      "ok": true,
      "count": 2
    }
    ```"""

    assert parse_json_object(payload) == {"ok": True, "count": 2}
