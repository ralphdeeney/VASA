import hashlib
import hmac
import json
import traceback
from collections.abc import AsyncIterator

import httpx
import pytest

from vasa.evolution import EvolutionCalls, EvolutionError

ADMIN = "admin-secret-" + "a" * 32
STREAM = "stream-secret-" + "s" * 32
INSTANCE = "instance-secret-" + "i" * 32
INSTANCE_ID = "d91c747b-00bc-43b6-928b-7c84d39ff6a2"


@pytest.fixture
async def calls() -> AsyncIterator[EvolutionCalls]:
    client = EvolutionCalls("http://127.0.0.1:8080", ADMIN, STREAM, INSTANCE)
    yield client
    await client.aclose()


def test_derived_instance_tokens_are_scoped_and_match_contract(calls: EvolutionCalls) -> None:
    expected = hmac.new(
        INSTANCE.encode(), ("vasa:instance:" + INSTANCE_ID).encode(), hashlib.sha256
    ).hexdigest()
    assert calls.token_for_instance(INSTANCE_ID) == expected
    assert calls.token_for_instance("other") != expected
    for secret in (ADMIN, INSTANCE, STREAM):
        assert secret not in repr(calls)


@pytest.mark.parametrize("identifier", ["../instance", "a?token=x", "a|x", "a/b", "", "a" * 129])
def test_rejects_noncanonical_identifiers(calls: EvolutionCalls, identifier: str) -> None:
    with pytest.raises(ValueError, match="invalid Evolution identifier"):
        calls.token_for_instance(identifier)


@pytest.mark.parametrize(
    "base", ["ftp://x", "http://user:pass@x", "http://x?secret=y", "http://x#x"]
)
def test_rejects_unsafe_urls(base: str) -> None:
    with pytest.raises(ValueError, match="invalid Evolution base URL"):
        EvolutionCalls(base, ADMIN, STREAM, INSTANCE)


async def test_verified_http_paths_payloads_auth_and_dtos() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/instance/create":
            return httpx.Response(200, json={"data": {"id": INSTANCE_ID}})
        if request.url.path == "/instance/status":
            return httpx.Response(
                200, json={"data": {"Connected": True, "LoggedIn": False, "Name": "Business"}}
            )
        if request.url.path == "/instance/qr":
            return httpx.Response(200, json={"data": {"qrcode": "data:image/png;base64,AAAA"}})
        return httpx.Response(200, json={"message": "success"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = EvolutionCalls("http://evolution:8080", ADMIN, STREAM, INSTANCE, http_client=http)
        await client.create_instance(INSTANCE_ID, "Business")
        await client.connect(INSTANCE_ID)
        status = await client.status(INSTANCE_ID)
        assert (status.connected, status.logged_in, status.name) == (True, False, "Business")
        qr = await client.qr(INSTANCE_ID)
        assert qr.qrcode == "data:image/png;base64,AAAA"
        assert qr.passkey_stage == ""
        await client.answer(INSTANCE_ID, "ABC123", "12345@lid")
        await client.reject(INSTANCE_ID, "ABC123", "12345@lid")
        await client.hangup(INSTANCE_ID, "ABC123")
        await client.disconnect(INSTANCE_ID)
        await client.delete_instance(INSTANCE_ID)
        await client.aclose()
        assert not http.is_closed  # externally supplied client's lifetime stays with its owner

    assert [(r.method, r.url.path) for r in requests] == [
        ("POST", "/instance/create"),
        ("POST", "/instance/connect"),
        ("GET", "/instance/status"),
        ("GET", "/instance/qr"),
        ("POST", "/call/answer"),
        ("POST", "/call/reject"),
        ("POST", "/call/hangup"),
        ("POST", "/instance/disconnect"),
        ("DELETE", "/instance/delete/" + INSTANCE_ID),
    ]
    derived = client.token_for_instance(INSTANCE_ID)
    assert [r.headers["apikey"] for r in requests] == [ADMIN] + [derived] * 7 + [ADMIN]
    assert json.loads(requests[0].content) == {
        "instanceId": INSTANCE_ID,
        "name": "Business",
        "token": derived,
        "advancedSettings": {"rejectCall": False},
    }
    assert json.loads(requests[1].content)["subscribe"] == ["CALL", "CONNECTION", "QRCODE"]
    assert json.loads(requests[4].content) == {"callId": "ABC123", "callCreator": "12345@lid"}
    assert json.loads(requests[6].content) == {"callId": "ABC123"}


@pytest.mark.parametrize(
    "status,body,code",
    [
        (503, {"code": "LICENSE_REQUIRED", "error": ADMIN}, "license_required"),
        (500, {"error": ADMIN}, "unavailable"),
        (200, {"data": {"Connected": "true", "LoggedIn": True, "Name": "x"}}, "invalid_response"),
        (200, [], "invalid_response"),
    ],
)
async def test_sanitizes_failures(status: int, body: object, code: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body))
    ) as http:
        client = EvolutionCalls("http://evolution:8080", ADMIN, STREAM, INSTANCE, http_client=http)
        with pytest.raises(EvolutionError) as caught:
            await client.status(INSTANCE_ID)
        assert caught.value.code == code
        assert ADMIN not in str(caught.value)


async def test_network_exception_traceback_does_not_expose_secret() -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(ADMIN)

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:
        client = EvolutionCalls("http://evolution:8080", ADMIN, STREAM, INSTANCE, http_client=http)
        with pytest.raises(EvolutionError) as caught:
            await client.status(INSTANCE_ID)
        assert caught.value.code == "unavailable"
        assert ADMIN not in "".join(traceback.format_exception(caught.value))


async def test_oversize_upstream_response_is_rejected() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 1_048_577))
    ) as http:
        client = EvolutionCalls("http://evolution:8080", ADMIN, STREAM, INSTANCE, http_client=http)
        with pytest.raises(EvolutionError, match="invalid_response"):
            await client.status(INSTANCE_ID)


@pytest.mark.parametrize("length,accepted", [(200, True), (201, False)])
async def test_create_instance_name_boundary_matches_control(length: int, accepted: bool) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert len(json.loads(request.content)["name"]) == 200
        return httpx.Response(200, json={"data": {"id": INSTANCE_ID}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = EvolutionCalls("http://evolution:8080", ADMIN, STREAM, INSTANCE, http_client=http)
        if accepted:
            await client.create_instance(INSTANCE_ID, "n" * length)
            assert len(requests) == 1
        else:
            with pytest.raises(ValueError, match="invalid instance name"):
                await client.create_instance(INSTANCE_ID, "n" * length)
            assert not requests


def event_payload(client: EvolutionCalls, **changes: object) -> str:
    payload: dict[str, object] = {
        "instanceId": INSTANCE_ID,
        "instanceToken": client.token_for_instance(INSTANCE_ID),
        "event": "CallOffer",
        "data": {"CallID": "ABC123", "CallCreator": "12345@lid"},
    }
    payload.update(changes)
    return json.dumps({"queue": INSTANCE_ID + ".calloffer", "payload": json.dumps(payload)})


def test_event_parser_requires_bound_instance_token(calls: EvolutionCalls) -> None:
    event = calls.parse_event(event_payload(calls), INSTANCE_ID)
    assert event is not None
    assert (event.instance_id, event.call_id, event.caller_jid) == (
        INSTANCE_ID,
        "ABC123",
        "12345@lid",
    )
    assert calls.parse_event(event_payload(calls, event="CallTerminate"), INSTANCE_ID) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"instanceId": "other"},
        {"instanceToken": "foreign-token"},
        {"instanceToken": "☃"},
        {"data": {"CallID": "../../foo", "CallCreator": "12345@lid"}},
        {"data": {"CallID": "ABC123", "CallCreator": "foo@attacker"}},
        {"data": {"callId": "ABC123", "callCreator": "12345@lid"}},
    ],
)
def test_invalid_events_fail_closed(calls: EvolutionCalls, changes: dict[str, object]) -> None:
    with pytest.raises(EvolutionError, match="invalid_response"):
        calls.parse_event(event_payload(calls, **changes), INSTANCE_ID)


@pytest.mark.parametrize("raw", ["{", "[]", '{"payload":{}}', "x" * 1_048_577])
def test_bounds_and_validates_event_envelope(calls: EvolutionCalls, raw: str) -> None:
    with pytest.raises(EvolutionError, match="invalid_response"):
        calls.parse_event(raw, INSTANCE_ID)
