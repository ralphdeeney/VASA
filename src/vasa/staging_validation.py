"""Read-only staging checks; no accounts, paid provider calls or secret output."""

import asyncio
import logging
from contextlib import AsyncExitStack
from html.parser import HTMLParser

import httpx

from vasa.config import Settings
from vasa.evolution.client import EvolutionCalls
from vasa.storage.database import Database
from vasa.voice_worker import resolve_all

MARKERS = frozenset(
    {
        "STAGING_LOGIN_OK",
        "STAGING_DASHBOARD_AUTH_OK",
        "STAGING_STATIC_OK",
        "STAGING_EVOLUTION_HTTP_OK",
        "STAGING_EVOLUTION_LICENSE_OK",
        "STAGING_INSTANCES_OK",
    }
)
ACTIVE_STAGE = "settings"


def stage(value: str) -> None:
    global ACTIVE_STAGE
    ACTIVE_STAGE = value


class Assets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        path = (
            values.get("src")
            if tag == "script"
            else (
                values.get("href") if tag == "link" and values.get("rel") == "stylesheet" else None
            )
        )
        if path is not None:
            self.paths.add(path)


async def get(client: httpx.AsyncClient, url: str, status: int = 200) -> httpx.Response:
    async with client.stream("GET", url, follow_redirects=False) as response:
        if response.status_code != status:
            raise ValueError("status")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 65536:
                raise ValueError("limit")
        return httpx.Response(status, headers=response.headers, content=bytes(body))


async def web_checks(settings: Settings, client: httpx.AsyncClient) -> None:
    stage("login")
    login = await get(client, "http://127.0.0.1:8080/login")
    if login.headers.get("content-type", "").split(";", 1)[0] != "text/html":
        raise ValueError("media type")
    assets = Assets()
    assets.feed(login.text)
    expected = {"/dashboard/assets/styles.css", "/dashboard/assets/login.js"}
    if assets.paths != expected:
        raise ValueError("assets")
    print("STAGING_LOGIN_OK", flush=True)
    stage("dashboard_auth")
    client.cookies.clear()
    await get(client, "http://127.0.0.1:8080/dashboard", 401)
    print("STAGING_DASHBOARD_AUTH_OK", flush=True)
    stage("static")
    for path in sorted(expected):
        await get(client, "http://127.0.0.1:8080" + path)
    print("STAGING_STATIC_OK", flush=True)
    stage("evolution_http")
    base = settings.evolution_base_url.rstrip("/")
    if (await get(client, base + "/server/ok")).json() != {"status": "ok"}:
        raise ValueError("process")
    print("STAGING_EVOLUTION_HTTP_OK", flush=True)
    stage("license")
    if (await get(client, base + "/license/status")).json().get("status") != "active":
        raise ValueError("license")
    print("STAGING_EVOLUTION_LICENSE_OK", flush=True)


async def validate() -> None:
    stage("settings")
    settings = Settings()
    async with asyncio.timeout(75), AsyncExitStack() as resources:
        http = await resources.enter_async_context(
            httpx.AsyncClient(timeout=10, follow_redirects=False)
        )
        await web_checks(settings, http)
        stage("instances")
        database = Database(settings.database_url.get_secret_value())
        resources.push_async_callback(database.aclose)
        calls = EvolutionCalls(
            settings.evolution_base_url,
            settings.evolution_admin_key.get_secret_value(),
            settings.evolution_stream_key.get_secret_value(),
            settings.evolution_instance_key.get_secret_value(),
        )
        resources.push_async_callback(calls.aclose)
        targets = await resolve_all(database)
        if not targets:
            raise ValueError("no registered instances")
        for _, _, external_id in targets:
            status = await calls.status(external_id)
            if not status.connected or not status.logged_in:
                raise ValueError("instance disconnected")
        print("STAGING_INSTANCES_OK", flush=True)


def main() -> int:
    logging.disable(logging.CRITICAL)
    try:
        asyncio.run(validate())
        return 0
    except Exception:
        print("STAGING_VALIDATION_FAILED=" + ACTIVE_STAGE, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
