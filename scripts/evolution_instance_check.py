"""Check or restore only registered paired instances; never create or pair one."""

import asyncio
import logging
import sys
from contextlib import AsyncExitStack

from sqlalchemy import text
from sqlalchemy.engine import make_url

from vasa.config import Settings
from vasa.evolution.client import EvolutionCalls
from vasa.storage.database import Database
from vasa.voice_worker import resolve_all


async def inspect(restore: bool, preserve_offline: bool = False) -> None:
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
        print("EVOLUTION_INSTANCE_STAGE=database", flush=True)
        targets = await resolve_all(database)
        expected = {external for _, _, external in targets}
        print("EVOLUTION_INSTANCE_REGISTERED_COUNT=" + str(len(expected)), flush=True)
        if not expected or len(expected) > 32:
            raise ValueError("instances")
        print("EVOLUTION_INSTANCE_STAGE=list", flush=True)
        result = await client._request(
            "GET", "/instance/all", settings.evolution_admin_key.get_secret_value()
        )
        rows = result.get("data")
        if isinstance(rows, list):
            print("EVOLUTION_INSTANCE_UPSTREAM_COUNT=" + str(len(rows)), flush=True)
        if (
            not isinstance(rows, list)
            or len(rows) != len(expected)
            or any(not isinstance(row, dict) or row.get("id") not in expected for row in rows)
            or {row["id"] for row in rows} != expected
        ):
            raise ValueError("unexpected instances")
        print("EVOLUTION_INSTANCE_STAGE=paired_device", flush=True)
        auth_url = make_url(settings.database_url.get_secret_value()).set(
            database="vasa_evolution_auth"
        )
        auth = Database(auth_url.render_as_string(hide_password=False))
        resources.push_async_callback(auth.aclose)
        for row in rows:
            jid = row.get("jid")
            if not isinstance(jid, str) or not jid or len(jid) > 256:
                raise ValueError("unpaired instance")
            async with auth.session() as session:
                paired = await session.scalar(
                    text("SELECT EXISTS (SELECT 1 FROM whatsmeow_device WHERE jid=:jid)"),
                    {"jid": jid},
                )
            if paired is not True:
                raise ValueError("paired device missing")
        print("EVOLUTION_INSTANCE_STAGE=status", flush=True)
        connectivity = set()
        for external in expected:
            status = await client.status(external)
            print("EVOLUTION_INSTANCE_CONNECTED=" + str(int(status.connected)), flush=True)
            print("EVOLUTION_INSTANCE_LOGGED_IN=" + str(int(status.logged_in)), flush=True)
            if not restore and status.connected != status.logged_in:
                raise ValueError("partial connectivity baseline")
            if preserve_offline and (status.connected or status.logged_in):
                raise ValueError("offline baseline changed")
            if restore and not (status.connected and status.logged_in):
                # Existing persisted device lookup; no create, pair, logout or QR endpoint.
                # The pinned reconnect endpoint loads persisted settings. The generic
                # connect helper would overwrite subscriptions and webhook settings.
                await client._request(
                    "POST", "/instance/reconnect", client.token_for_instance(external)
                )
                for _ in range(30):
                    await asyncio.sleep(2)
                    status = await client.status(external)
                    if status.connected and status.logged_in:
                        break
            if restore and (not status.connected or not status.logged_in):
                raise ValueError("instance unavailable")
            connectivity.add(status.connected and status.logged_in)
        if len(connectivity) != 1:
            raise ValueError("mixed connectivity baseline")
        print(
            "EVOLUTION_INSTANCE_BASELINE=" + ("online" if True in connectivity else "offline"),
            flush=True,
        )
        print("EVOLUTION_REGISTERED_INSTANCES_OK", flush=True)


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        if len(sys.argv) > 2 or (
            len(sys.argv) == 2 and sys.argv[1] not in {"restore", "preserve-offline"}
        ):
            raise ValueError("invocation")
        if len(sys.argv) == 2 and sys.argv[1] == "preserve-offline":
            asyncio.run(inspect(False, preserve_offline=True))
        else:
            asyncio.run(inspect(len(sys.argv) == 2))
    except Exception:
        print("EVOLUTION_REGISTERED_INSTANCES_FAILED", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
