import asyncio
import ipaddress
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import Field, ValidationError

from vasa.contracts.models import CallSession, CallState, TenantContext
from vasa.contracts.providers import EvolutionClient
from vasa.storage.cache import CallRegistry
from vasa.tools.gateway import ToolError, ToolPayload, _snapshot


class WebhookInput(ToolPayload):
    action: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    payload: dict[str, Any]


class WebhookOutput(ToolPayload):
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class WebhookAction:
    url: str = field(repr=False)
    input_model: type[ToolPayload]
    output_model: type[ToolPayload]
    bearer_token: str = field(default="", repr=False)


def _approved_url(url: str, origins: frozenset[str]) -> None:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            len(url) > 2048
            or not url.isascii()
            or any(character.isspace() for character in url)
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port not in {None, 443}
            or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,63}", host)
            or host.endswith((".localhost", ".local", ".internal", ".invalid", ".test"))
            or f"https://{host}" not in origins
            or not parsed.path.startswith("/")
            or "\\" in url
        ):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return
        raise ValueError
    except ValueError:
        raise ValueError("invalid or unapproved webhook destination") from None


class CustomWebhook:
    name = "custom_webhook"

    def __init__(
        self,
        tenant_id: UUID,
        actions: Mapping[str, WebhookAction],
        *,
        approved_origins: frozenset[str],
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not isinstance(tenant_id, UUID) or not 1 <= len(actions) <= 32:
            raise ValueError("invalid webhook configuration")
        self._actions = dict(actions)
        for name, action in self._actions.items():
            if (
                not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name)
                or len(action.bearer_token) > 4096
                or not action.bearer_token.isascii()
                or any(character.isspace() for character in action.bearer_token)
                or any(
                    not issubclass(model, ToolPayload)
                    or model.model_config.get("extra") != "forbid"
                    or model.model_config.get("strict") is not True
                    for model in (action.input_model, action.output_model)
                )
            ):
                raise ValueError("invalid webhook configuration")
            _approved_url(action.url, approved_origins)
        self._tenant_id = tenant_id
        self._owned = http_client is None
        self._client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=3, pool=3),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            follow_redirects=False,
        )
        self._closed = False

    async def aclose(self) -> None:
        self._closed = True
        if self._owned:
            await self._client.aclose()

    async def execute(self, context: TenantContext, arguments: dict[str, Any]) -> dict[str, Any]:
        if context.tenant_id != self._tenant_id:
            raise ToolError("denied")
        if self._closed:
            raise ToolError("unavailable")
        try:
            inputs = WebhookInput.model_validate(_snapshot(arguments, "invalid_input"))
        except ValidationError:
            raise ToolError("invalid_input") from None
        action = self._actions.get(inputs.action)
        if action is None:
            raise ToolError("denied")
        try:
            payload = action.input_model.model_validate(inputs.payload).model_dump(mode="json")
        except ValidationError:
            raise ToolError("invalid_input") from None
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if action.bearer_token:
            headers["Authorization"] = f"Bearer {action.bearer_token}"
        try:
            async with asyncio.timeout(10):
                async with self._client.stream(
                    "POST",
                    action.url,
                    json={"tenant_id": str(context.tenant_id), "payload": payload},
                    headers=headers,
                    follow_redirects=False,
                ) as response:
                    if not 200 <= response.status_code < 300:
                        raise ToolError("unavailable")
                    if (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                        != "application/json"
                        or response.headers.get("content-encoding", "identity").lower()
                        != "identity"
                    ):
                        raise ToolError("invalid_output")
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(body) + len(chunk) > 32768:
                            raise ToolError("invalid_output")
                        body.extend(chunk)
                    # Nonfinite values are rejected by the shared JSON snapshot validator.
                    result = _snapshot(json.loads(body), "invalid_output")
                    try:
                        result = action.output_model.model_validate(result).model_dump(mode="json")
                    except ValidationError:
                        raise ToolError("invalid_output") from None
                    return {"result": result}
        except ToolError:
            raise
        except (json.JSONDecodeError, UnicodeError, RecursionError):
            raise ToolError("invalid_output") from None
        except TimeoutError:
            raise ToolError("timeout") from None
        except Exception:
            raise ToolError("unavailable") from None


class EndCallInput(ToolPayload):
    reason: str = Field(default="completed", min_length=1, max_length=200)


class EndCallOutput(ToolPayload):
    requested: Literal[True]


class EndCall:
    name = "end_call"

    def __init__(
        self,
        context: TenantContext,
        session: CallSession,
        client: EvolutionClient,
        registry: CallRegistry,
    ) -> None:
        if context.tenant_id != session.tenant_id:
            raise ValueError("call ownership mismatch")
        self._context, self._session = context, session
        self._client, self._registry = client, registry
        self._lock = asyncio.Lock()
        self.end_requested = asyncio.Event()

    async def execute(self, context: TenantContext, arguments: dict[str, Any]) -> dict[str, Any]:
        if context != self._context:
            raise ToolError("denied")
        try:
            EndCallInput.model_validate(_snapshot(arguments, "invalid_input"))
        except ValidationError:
            raise ToolError("invalid_input") from None
        try:
            async with asyncio.timeout(5):
                async with self._lock:
                    if self.end_requested.is_set():
                        return {"requested": True}
                    current = await self._registry.get(context, self._session.id)
                    if (
                        current is None
                        or current.instance_id != self._session.instance_id
                        or current.external_call_id != self._session.external_call_id
                        or current.state
                        in {
                            CallState.RINGING,
                            CallState.ANSWERING,
                            CallState.ENDED,
                            CallState.ERROR,
                        }
                    ):
                        raise ToolError("denied")
                    await self._client.hangup(current.instance_id, current.external_call_id)
                    self.end_requested.set()
                    return {"requested": True}
        except ToolError:
            raise
        except TimeoutError:
            raise ToolError("timeout") from None
        except Exception:
            raise ToolError("unavailable") from None


class KnowledgeInput(ToolPayload):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=3, ge=1, le=5)


class KnowledgeMatch(ToolPayload):
    tenant_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    source_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    chunk_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    text: str = Field(min_length=1, max_length=4000)
    score: float = Field(ge=-1, le=1)


class KnowledgeOutput(ToolPayload):
    matches: list[KnowledgeMatch] = Field(max_length=5)


class KnowledgeRetriever(Protocol):
    async def search(
        self, context: TenantContext, query: str, top_k: int
    ) -> list[KnowledgeMatch]: ...


class KnowledgeSearch:
    name = "knowledge_search"

    def __init__(self, tenant_id: UUID, retriever: KnowledgeRetriever | None = None) -> None:
        self._tenant_id, self._retriever = tenant_id, retriever

    async def execute(self, context: TenantContext, arguments: dict[str, Any]) -> dict[str, Any]:
        if context.tenant_id != self._tenant_id:
            raise ToolError("denied")
        try:
            inputs = KnowledgeInput.model_validate(_snapshot(arguments, "invalid_input"))
        except ValidationError:
            raise ToolError("invalid_input") from None
        if self._retriever is None:
            raise ToolError("unavailable")
        try:
            async with asyncio.timeout(5):
                matches = await self._retriever.search(context, inputs.query, inputs.top_k)
            if len(matches) > inputs.top_k or any(
                match.tenant_id != str(context.tenant_id) for match in matches
            ):
                raise ToolError("invalid_output")
            result = _snapshot(
                {"matches": [match.model_dump(mode="json") for match in matches]}, "invalid_output"
            )
            KnowledgeOutput.model_validate(result)
            return result
        except ToolError:
            raise
        except TimeoutError:
            raise ToolError("timeout") from None
        except ValidationError:
            raise ToolError("invalid_output") from None
        except Exception:
            raise ToolError("unavailable") from None
