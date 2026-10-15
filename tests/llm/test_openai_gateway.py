import json

import httpx
import pytest

from tests.llm.test_providers import MESSAGES, context, openai_parts
from tests.llm.test_tools import TOOLS, tool_parts
from vasa.config import Settings
from vasa.llm import OpenAIProvider


def test_openai_base_url_default_preserves_official_settings(monkeypatch) -> None:
    for name in ("VASA_OPENAI_BASE_URL", "VASA_OPENAI_MODEL", "VASA_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=None)
    assert settings.openai_base_url == "https://api.openai.com/v1"
    assert settings.openai_model == "gpt-4o-mini"


def test_openai_gateway_environment_keeps_key_secret(monkeypatch) -> None:
    monkeypatch.setenv("VASA_OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("VASA_OPENAI_MODEL", "cx/gpt-5.6-sol")
    monkeypatch.setenv("VASA_OPENAI_API_KEY", "fixture-only-gateway-key")
    settings = Settings(_env_file=None)
    assert settings.openai_base_url == "https://gateway.example/v1"
    assert settings.openai_model == "cx/gpt-5.6-sol"
    assert settings.openai_api_key.get_secret_value() == "fixture-only-gateway-key"
    assert "fixture-only-gateway-key" not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize(
    "base_url",
    [
        "https://api.openai.com/v1",
        "https://gateway.example/v1/",
        "https://gateway.example/proxy/v1",
    ],
)
@pytest.mark.parametrize("tools", [False, True])
async def test_gateway_request_url_model_auth_and_streamed_events(base_url, tools, capsys) -> None:
    requests = []

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for part in tool_parts("openai") if tools else openai_parts("Gateway response"):
                yield part

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=Stream())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIProvider(
            "fixture-only-gateway-key",
            base_url=base_url,
            model="cx/gpt-5.6-sol",
            tools=TOOLS if tools else None,
            http_client=client,
        )
        try:
            events = [event async for event in provider.respond(context(), MESSAGES)]
        finally:
            await provider.aclose()
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == base_url.rstrip("/") + "/chat/completions"
    assert request.method == "POST"
    assert request.headers["authorization"] == "Bearer fixture-only-gateway-key"
    assert request.headers["accept"] == "text/event-stream"
    body = json.loads(request.content)
    assert body["model"] == "cx/gpt-5.6-sol" and body["stream"] is True
    assert body["messages"] == MESSAGES
    if tools:
        assert body["tools"] == [{"type": "function", "function": TOOLS[0]}]
        assert body["parallel_tool_calls"] is False
        assert events == [
            {
                "type": "tool_call",
                "id": "call_1",
                "name": "knowledge_search",
                "arguments": {"query": "hours"},
            }
        ]
    else:
        assert "tools" not in body
        assert events == [{"type": "text", "text": "Gateway response"}]
    output = capsys.readouterr()
    assert "fixture-only-gateway-key" not in output.out + output.err
