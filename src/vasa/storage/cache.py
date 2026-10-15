import json
from collections.abc import Awaitable
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis

from vasa.contracts.models import CallSession, CallState, TenantContext

MAX_SESSION_BYTES = 65536
_PUT_SESSION = """
local existing = redis.call('GET', KEYS[1])
if existing then
    if string.len(existing) > tonumber(ARGV[5]) then
        return 0
    end
    local ok, data = pcall(cjson.decode, existing)
    if not ok or type(data) ~= 'table' or data.tenant_id ~= ARGV[3] or data.id ~= ARGV[4] then
        return 0
    end
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""


class CallRegistry:
    """Bounded, expiring state in a tenant-specific namespace; not authentication."""

    def __init__(self, client: Redis, ttl_seconds: int = 3600) -> None:
        if (
            not isinstance(ttl_seconds, int)
            or isinstance(ttl_seconds, bool)
            or not 1 <= ttl_seconds <= 86400
        ):
            raise ValueError("call state TTL must be between 1 and 86400 seconds")
        self.client = client
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(tenant_id: UUID, call_id: UUID) -> str:
        return f"vasa:tenant:{tenant_id}:call:{call_id}"

    async def put(self, session: CallSession) -> None:
        payload = json.dumps(
            {
                "id": str(session.id),
                "tenant_id": str(session.tenant_id),
                "instance_id": session.instance_id,
                "external_call_id": session.external_call_id,
                "state": session.state.value,
                "metadata": session.metadata,
            },
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > MAX_SESSION_BYTES:
            raise ValueError("call state exceeds size limit")
        self._decode(payload, session.tenant_id, session.id)
        # Redis shares ScriptCommands annotations with its synchronous client.
        stored = await cast(
            Awaitable[object],
            self.client.eval(
                _PUT_SESSION,
                1,
                self._key(session.tenant_id, session.id),
                payload,
                str(self.ttl_seconds),
                str(session.tenant_id),
                str(session.id),
                str(MAX_SESSION_BYTES),
            ),
        )
        if stored != 1:
            raise ValueError("existing call state namespace mismatch or invalid state")

    @staticmethod
    def _decode(payload: str | bytes, tenant_id: UUID, call_id: UUID) -> CallSession:
        if len(payload if isinstance(payload, bytes) else payload.encode()) > MAX_SESSION_BYTES:
            raise ValueError("call state exceeds size limit")
        data: Any = json.loads(payload)
        if not isinstance(data, dict) or set(data) != {
            "id",
            "tenant_id",
            "instance_id",
            "external_call_id",
            "state",
            "metadata",
        }:
            raise ValueError("invalid call state")
        if data["tenant_id"] != str(tenant_id) or data["id"] != str(call_id):
            raise ValueError("call state namespace mismatch")
        metadata = data["metadata"]
        if not isinstance(metadata, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in metadata.items()
        ):
            raise ValueError("invalid call metadata")
        if not isinstance(data["instance_id"], str) or not isinstance(
            data["external_call_id"], str
        ):
            raise ValueError("invalid call identifiers")
        return CallSession(
            id=call_id,
            tenant_id=tenant_id,
            instance_id=data["instance_id"],
            external_call_id=data["external_call_id"],
            state=CallState(data["state"]),
            metadata=metadata,
        )

    async def get(self, context: TenantContext, call_id: UUID) -> CallSession | None:
        payload = await self.client.get(self._key(context.tenant_id, call_id))
        if payload is None:
            return None
        return self._decode(payload, context.tenant_id, call_id)

    async def delete(self, context: TenantContext, call_id: UUID) -> None:
        await self.client.delete(self._key(context.tenant_id, call_id))
