"""Check or restore only registered paired instances; never create or pair one."""

import asyncio
import logging
import sys
from contextlib import AsyncExitStack

from vasa.config import Settings
from vasa.evolution.client import EvolutionCalls
from vasa.storage.database import Database
from vasa.voice_worker import resolve_all


async def inspect(restore: bool) -> None:
    settings = Settings()
    async with asyncio.timeout(90), AsyncExitStack() as resources:
        database = Database(settings.database_url.get_secret_value())
        resources.push_async_callback(database.aclose)
        client = EvolutionCalls(
            settings.evolution_base_url,
            settings.evolution_admin_key.get_secret_value(),
            settings.evolution_stream_key.get_secret_value(),
            settings.evolution_instance_key.get_secret_value(),
        )
        resources.push_async_callback(client.aclose)
        targets = await resolve_all(database)
        expected = {external for _, _, external in targets}
        if not expected or len(expected) > 32:
            raise ValueError("instances")
        result = await client._request(
            "GET", "/instance/all", settings.evolution_admin_key.get_secret_value()
        )
        rows = result.get("data")
        if (
            not isinstance(rows, list)
            or len(rows) != len(expected)
            or any(not isinstance(row, dict) or row.get("id") not in expected for row in rows)
            or {row["id"] for row in rows} != expected
        ):
            raise ValueError("unexpected instances")
        for external in expected:
            status = await client.status(external)
            if restore and not (status.connected and status.logged_in):
                # Existing persisted device lookup; no create, pair, logout or QR endpoint.
                await client.connect(external)
                for _ in range(30):
                    await asyncio.sleep(2)
                    status = await client.status(external)
                    if status.connected and status.logged_in:
                        break
            if not status.connected or not status.logged_in:
                raise ValueError("instance unavailable")
        print("EVOLUTION_REGISTERED_INSTANCES_OK", flush=True)


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        if len(sys.argv) > 2 or (len(sys.argv) == 2 and sys.argv[1] != "restore"):
            raise ValueError("invocation")
        asyncio.run(inspect(len(sys.argv) == 2))
    except Exception:
        print("EVOLUTION_REGISTERED_INSTANCES_FAILED", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
