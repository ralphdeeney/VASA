import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, WebSocketException

from vasa.evolution.models import (
    MAX_BODY_BYTES,
    ConnectionStatus,
    EvolutionError,
    IncomingCall,
    PairingQR,
    validate_id,
)
from vasa.evolution.stream import CallLifecycle, MediaStream

EVENT_PING_INTERVAL_SECONDS = 20.0
EVENT_PING_TIMEOUT_SECONDS = 20.0


def websocket_failure(error: InvalidStatus) -> EvolutionError:
    if error.response.status_code == 503:
        try:
            body = error.response.body
            if body is not None and len(body) <= MAX_BODY_BYTES:
                result = json.loads(body)
                if isinstance(result, dict) and result.get("code") == "LICENSE_REQUIRED":
                    return EvolutionError("license_required")
        except (ValueError, UnicodeError, RecursionError):
            pass
    return EvolutionError("unavailable")


class EvolutionCalls:
    def __init__(
        self,
        base_url: str,
        admin_key: str,
        stream_key: str,
        instance_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid Evolution base URL")
        for key in (admin_key, stream_key, instance_key):
            if len(key.encode("utf-8")) < 32 or len(key) > 4096:
                raise ValueError("Evolution keys must have at least 32 UTF-8 bytes")
        self._base_url = base_url.rstrip("/")
        self._ws_url = urlunsplit(
            (
                "wss" if parsed.scheme == "https" else "ws",
                parsed.netloc,
                parsed.path.rstrip("/"),
                "",
                "",
            )
        )
        self._admin_key = admin_key
        self._stream_key = stream_key
        self._instance_key = instance_key
        self._media_lifecycles: dict[tuple[str, str], CallLifecycle] = {}
        # websockets DEBUG logging prints signed query strings. A private disabled
        # logger prevents credential disclosure even when host logging enables DEBUG.
        self._ws_logger = logging.Logger("vasa.evolution.transport")
        self._ws_logger.disabled = True
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            timeout=10,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
        )

    def token_for_instance(self, instance_id: str) -> str:
        validate_id(instance_id)
        return hmac.new(
            self._instance_key.encode(), ("vasa:instance:" + instance_id).encode(), hashlib.sha256
        ).hexdigest()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        key: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with (
                asyncio.timeout(10),
                self._http.stream(
                    method,
                    self._base_url + path,
                    headers={"apikey": key},
                    json=body,
                    timeout=10,
                    follow_redirects=False,
                ) as response,
            ):
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BODY_BYTES:
                        raise EvolutionError("invalid_response")
                    content.extend(chunk)
                try:
                    result = json.loads(content)
                except (ValueError, UnicodeError, RecursionError):
                    raise EvolutionError("invalid_response") from None
                if not isinstance(result, dict):
                    raise EvolutionError("invalid_response")
                if response.status_code == 503 and result.get("code") == "LICENSE_REQUIRED":
                    raise EvolutionError("license_required")
                if not response.is_success:
                    raise EvolutionError("unavailable")
                return result
        except (httpx.HTTPError, TimeoutError, OSError):
            raise EvolutionError("unavailable") from None

    async def create_instance(self, instance_id: str, name: str) -> None:
        validate_id(instance_id)
        if not name.strip() or len(name) > 200:
            raise ValueError("invalid instance name")
        result = await self._request(
            "POST",
            "/instance/create",
            self._admin_key,
            {
                "instanceId": instance_id,
                "name": name,
                "token": self.token_for_instance(instance_id),
                "advancedSettings": {"rejectCall": False},
            },
        )
        data = result.get("data")
        if not isinstance(data, dict) or data.get("id") != instance_id:
            raise EvolutionError("invalid_response")

    async def connect(self, instance_id: str) -> None:
        await self._request(
            "POST",
            "/instance/connect",
            self.token_for_instance(instance_id),
            {
                "subscribe": ["CALL", "CONNECTION", "QRCODE"],
                "websocketEnable": "true",
                "webhookUrl": "",
                "rabbitmqEnable": "false",
                "natsEnable": "false",
            },
        )

    async def disconnect(self, instance_id: str) -> None:
        await self._request("POST", "/instance/disconnect", self.token_for_instance(instance_id))

    async def delete_instance(self, instance_id: str) -> None:
        await self._request(
            "DELETE", "/instance/delete/" + validate_id(instance_id), self._admin_key
        )

    async def status(self, instance_id: str) -> ConnectionStatus:
        result = await self._request(
            "GET", "/instance/status", self.token_for_instance(instance_id)
        )
        data = result.get("data")
        if (
            not isinstance(data, dict)
            or type(data.get("Connected")) is not bool
            or type(data.get("LoggedIn")) is not bool
            or not isinstance(data.get("Name"), str)
        ):
            raise EvolutionError("invalid_response")
        return ConnectionStatus(data["Connected"], data["LoggedIn"], data["Name"])

    async def phone_number(self, instance_id: str) -> str:
        """Read only the selected instance's canonical phone JID; never expose its record."""
        result = await self._request(
            "GET", "/instance/info/" + validate_id(instance_id), self._admin_key
        )
        data = result.get("data")
        if not isinstance(data, dict) or data.get("id") != instance_id:
            raise EvolutionError("invalid_response")
        jid = data.get("jid", "")
        if not isinstance(jid, str):
            raise EvolutionError("invalid_response")
        match = re.fullmatch(r"([1-9][0-9]{6,14})(?::[0-9]{1,5})?@s\.whatsapp\.net", jid)
        return "+" + match.group(1) if match else ""

    async def qr(self, instance_id: str) -> PairingQR:
        result = await self._request("GET", "/instance/qr", self.token_for_instance(instance_id))
        data = result.get("data")
        if not isinstance(data, dict):
            raise EvolutionError("invalid_response")
        qr, stage = data.get("qrcode", ""), data.get("passkeyStage", "")
        if not isinstance(qr, str) or not isinstance(stage, str):
            raise EvolutionError("invalid_response")
        return PairingQR(qr, stage)

    async def answer(self, instance_id: str, call_id: str, caller_jid: str) -> None:
        await self._call_control("answer", instance_id, call_id, caller_jid)

    async def reject(self, instance_id: str, call_id: str, caller_jid: str) -> None:
        await self._call_control("reject", instance_id, call_id, caller_jid)

    async def hangup(self, instance_id: str, call_id: str) -> None:
        await self._call_control("hangup", instance_id, call_id)

    async def _call_control(
        self,
        action: str,
        instance_id: str,
        call_id: str,
        caller_jid: str | None = None,
    ) -> None:
        body = {"callId": validate_id(call_id)}
        if caller_jid is not None:
            if len(caller_jid) > 255 or not re.fullmatch(
                r"[0-9]+(?::[0-9]+)?@(s\.whatsapp\.net|lid)", caller_jid
            ):
                raise ValueError("invalid caller JID")
            body["callCreator"] = caller_jid
        await self._request("POST", "/call/" + action, self.token_for_instance(instance_id), body)

    @asynccontextmanager
    async def open_media(self, instance_id: str, call_id: str) -> AsyncIterator[MediaStream]:
        validate_id(instance_id)
        validate_id(call_id)
        exp = int(time.time()) + 60
        token = hmac.new(
            self._stream_key.encode(), f"{instance_id}|{call_id}|{exp}".encode(), hashlib.sha256
        ).hexdigest()
        key = (instance_id, call_id)
        if key in self._media_lifecycles or len(self._media_lifecycles) >= 10:
            raise EvolutionError("unavailable")
        lifecycle = CallLifecycle()
        self._media_lifecycles[key] = lifecycle
        uri = (
            self._ws_url
            + "/call/stream/"
            + call_id
            + "?"
            + urlencode(
                {
                    "instance": instance_id,
                    "exp": exp,
                    "token": token,
                }
            )
        )
        try:
            async with connect(
                uri,
                open_timeout=10,
                close_timeout=3,
                max_size=MAX_BODY_BYTES,
                max_queue=4,
                write_limit=8192,
                proxy=None,
                logger=self._ws_logger,
            ) as connection:
                stream = MediaStream(connection, call_id, lifecycle)
                try:
                    await stream.start()
                    yield stream
                finally:
                    await stream.close()
        except InvalidStatus as error:
            raise websocket_failure(error) from None
        except (WebSocketException, TimeoutError, OSError):
            raise EvolutionError("unavailable") from None
        finally:
            self._media_lifecycles.pop(key, None)

    def parse_event(self, raw: str | bytes, instance_id: str) -> IncomingCall | None:
        validate_id(instance_id)
        if len(raw) > MAX_BODY_BYTES:
            raise EvolutionError("invalid_response")
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), str):
                raise EvolutionError("invalid_response")
            payload = json.loads(envelope["payload"])
        except (ValueError, UnicodeError, RecursionError):
            raise EvolutionError("invalid_response") from None
        if (
            not isinstance(payload, dict)
            or payload.get("instanceId") != instance_id
            or not isinstance(payload.get("instanceToken"), str)
            or not hmac.compare_digest(
                payload["instanceToken"].encode(), self.token_for_instance(instance_id).encode()
            )
        ):
            raise EvolutionError("invalid_response")
        if payload.get("event") == "CallTerminate":
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("CallID"), str):
                raise EvolutionError("invalid_response")
            try:
                validate_id(data["CallID"])
            except ValueError:
                raise EvolutionError("invalid_response") from None
            if envelope.get("queue") != f"{instance_id}.callterminate".lower():
                raise EvolutionError("invalid_response")
            lifecycle = self._media_lifecycles.get((instance_id, data["CallID"]))
            if lifecycle is not None and not lifecycle.remote_terminated:
                lifecycle.terminate()
                print("CALL_LIFECYCLE=remote_terminate", flush=True)
            return None
        if payload.get("event") != "CallOffer":
            return None
        data = payload.get("data")
        if not isinstance(data, dict):
            raise EvolutionError("invalid_response")
        call_id, jid = data.get("CallID"), data.get("CallCreator")
        if (
            not isinstance(call_id, str)
            or not isinstance(jid, str)
            or len(jid) > 255
            or not re.fullmatch(r"[0-9]+(?::[0-9]+)?@(s\.whatsapp\.net|lid)", jid)
        ):
            raise EvolutionError("invalid_response")
        try:
            validate_id(call_id)
        except ValueError:
            raise EvolutionError("invalid_response") from None
        if envelope.get("queue") != f"{instance_id}.calloffer".lower():
            raise EvolutionError("invalid_response")
        return IncomingCall(instance_id, call_id, jid)

    async def events(self, instance_id: str) -> AsyncIterator[IncomingCall]:
        validate_id(instance_id)
        uri = (
            self._ws_url + "/ws?" + urlencode({"token": self._admin_key, "instanceId": instance_id})
        )
        try:
            async with connect(
                uri,
                open_timeout=10,
                close_timeout=3,
                max_size=MAX_BODY_BYTES,
                max_queue=4,
                ping_interval=EVENT_PING_INTERVAL_SECONDS,
                ping_timeout=EVENT_PING_TIMEOUT_SECONDS,
                proxy=None,
                logger=self._ws_logger,
            ) as connection:
                # Calls may be hours apart. Only WebSocket ping/pong health bounds
                # liveness here; the media read deadline does not apply to events.
                async for raw in connection:
                    event = self.parse_event(raw, instance_id)
                    if event is not None:
                        yield event
        except InvalidStatus as error:
            raise websocket_failure(error) from None
        except (WebSocketException, TimeoutError, OSError):
            raise EvolutionError("unavailable") from None
