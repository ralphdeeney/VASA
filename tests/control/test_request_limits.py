import json

import pytest
from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

from tests.control.fixtures import PASSWORD, ControlHarness
from vasa.request_limits import MAX_CONTROL_BODY_BYTES, ControlBodyLimit


@pytest.mark.integration
async def test_real_login_accepts_boundary_body_and_rejects_one_extra_byte(
    control_harness: ControlHarness,
) -> None:
    harness = control_harness
    client = harness.client()
    credentials = json.dumps({"email": harness.users[0].email, "password": PASSWORD}).encode()
    body = credentials + b" " * (MAX_CONTROL_BODY_BYTES - len(credentials))
    assert len(body) == MAX_CONTROL_BODY_BYTES
    accepted = client.post(
        "/api/auth/login", content=body, headers={"content-type": "application/json"}
    )
    assert accepted.status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    rejected = client.post(
        "/api/auth/login", content=body + b" ", headers={"content-type": "application/json"}
    )
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": "request_too_large"}
    assert PASSWORD not in accepted.text + rejected.text
    assert client.get("/api/auth/me").status_code == 200


@pytest.mark.parametrize("declared_length", [None, b"1", b"8193"])
async def test_cumulative_asgi_chunks_cannot_bypass_body_limit(
    declared_length: bytes | None,
) -> None:
    # TestClient/httpx materialize generators; direct ASGI messages prove true multi-frame input.
    requests = [
        {"type": "http.request", "body": b"x" * 4096, "more_body": True},
        {"type": "http.request", "body": b"x" * 4096, "more_body": True},
        {"type": "http.request", "body": b"x", "more_body": False},
    ]
    responses: list[Message] = []
    reached_application = False

    async def receive() -> Message:
        return requests.pop(0)

    async def send(message: Message) -> None:
        responses.append(message)

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal reached_application
        reached_application = True
        await JSONResponse({"status": "unexpected"})(scope, receive, send)

    headers = (
        [(b"transfer-encoding", b"chunked")]
        if declared_length is None
        else [(b"content-length", declared_length)]
    )
    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": headers,
    }
    await ControlBodyLimit(application)(scope, receive, send)
    assert not reached_application
    assert responses[0]["type"] == "http.response.start"
    assert responses[0]["status"] == 413
    assert json.loads(responses[1]["body"]) == {"detail": "request_too_large"}
    assert requests == []
