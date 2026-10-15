import json

import httpx
import pytest

from tests.llm.test_providers import MESSAGES, context, openai_parts
from tests.llm.test_tools import TOOLS, tool_parts
from vasa.config import Settings
from vasa.llm import OpenAIProvider
from vasa.llm.common import LLMError
from vasa.llm.diagnostic import diagnose, shape
from vasa.llm.sse import SSEEvent

SECRET = "secret-key-response-prompt-reasoning"


class Stream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts
        self.closed = False

    async def __aiter__(self):
        for part in self.parts:
            yield part

    async def aclose(self):
        self.closed = True


def test_remote_names_values_are_redacted():
    metadata = shape(
        SSEEvent(
            SECRET,
            json.dumps(
                {
                    SECRET: SECRET,
                    "choices": [
                        {
                            "index": SECRET,
                            "finish_reason": SECRET,
                            "delta": {
                                "content": SECRET,
                                "reasoning_content": SECRET,
                                "tool_calls": SECRET,
                                SECRET: SECRET,
                            },
                        }
                    ],
                }
            ),
        )
    )
    assert SECRET not in json.dumps(metadata)
    assert metadata["choices"][0]["index_type"] == "string"
    assert metadata["choices"][0]["delta"]["unknown_key_count"] == 1


@pytest.mark.parametrize(
    "index,kind,value",
    [
        (0, "integer", 0),
        ("0", "string", "0"),
        (None, "null", None),
        (True, "boolean", None),
        (100, "integer", None),
        ({"key": SECRET}, "other", None),
    ],
)
def test_index_metadata_is_bounded(index, kind, value):
    metadata = shape(SSEEvent("message", json.dumps({"choices": [{"index": index}]})))
    assert metadata["choices"][0]["index_type"] == kind
    assert metadata["choices"][0]["index_value"] == value
    assert SECRET not in json.dumps(metadata)


@pytest.mark.parametrize("data", ["not json " + SECRET, "[]", "null"])
def test_non_object_or_invalid_json_never_rendered(data):
    assert SECRET not in json.dumps(shape(SSEEvent("message", data)))


@pytest.mark.parametrize(
    "status,ctype,encoding",
    [
        (200, "text/event-stream; charset=utf-8", "identity"),
        (401, SECRET, SECRET),
        (200, "text/event-stream", "gzip"),
    ],
)
async def test_single_request_headers_sanitized_and_stream_closed(status, ctype, encoding, capsys):
    requests = []
    stream = Stream(openai_parts(SECRET))

    def handle(request):
        requests.append(request)
        return httpx.Response(
            status, headers={"content-type": ctype, "content-encoding": encoding}, stream=stream
        )

    settings = Settings(
        _env_file=None,
        openai_api_key=SECRET,
        openai_base_url="https://gateway.example/v1",
        openai_model="cx/gpt-5.6-sol",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await diagnose(settings, client)
    assert result == (0 if status == 200 and encoding == "identity" else 1)
    assert len(requests) == 1 and stream.closed
    assert requests[0].url.path == "/v1/chat/completions"
    assert requests[0].headers["accept-encoding"] == "identity"
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    rows = [json.loads(line) for line in output.out.splitlines()]
    assert rows[0]["http_status"] == status
    if result == 0:
        assert rows[-1]["done_received"] is True


@pytest.mark.parametrize("tools", [False, True])
async def test_standard_text_and_tools_remain_valid(tools):
    parts = tool_parts("openai") if tools else openai_parts("Hello")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/event-stream; charset=utf-8"},
                stream=Stream(parts),
            )
        )
    ) as client:
        provider = OpenAIProvider("fixture-key", http_client=client, tools=TOOLS if tools else None)
        events = [event async for event in provider.respond(context(), MESSAGES)]
        assert events[0]["type"] == ("tool_call" if tools else "text")


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_index",
        "string_index",
        "empty_choices",
        "missing_finish",
        "missing_done",
        "invalid_delta",
    ],
)
async def test_synthetic_incompatibilities_still_rejected(mutation):
    # These are hypotheses, NOT captured 9Router fixtures. Do not relax the parser
    # until the operator provides the actual structural diagnostic.
    choice = {"index": 0, "delta": {"content": "Hello"}, "finish_reason": "stop"}
    if mutation == "missing_index":
        del choice["index"]
    if mutation == "string_index":
        choice["index"] = "0"
    if mutation == "invalid_delta":
        choice["delta"] = None
    if mutation == "missing_finish":
        choice["finish_reason"] = None
    choices = [] if mutation == "empty_choices" else [choice]
    parts = [("data: " + json.dumps({"choices": choices}) + "\n\n").encode()]
    if mutation != "missing_done":
        parts.append(b"data: [DONE]\n\n")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=Stream(parts)
            )
        )
    ) as client:
        provider = OpenAIProvider("fixture-key", http_client=client)
        with pytest.raises(LLMError):
            _ = [event async for event in provider.respond(context(), MESSAGES)]
