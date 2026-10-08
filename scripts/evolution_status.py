"""Report process and license readiness separately without credential-bearing response fields."""

import asyncio

import httpx

from vasa.config import Settings


async def main() -> None:
    settings = Settings()
    async with httpx.AsyncClient(base_url=settings.evolution_base_url, timeout=10) as client:
        response = await client.get("/server/ok")
        response.raise_for_status()
        assert response.json() == {"status": "ok"}
        response = await client.get("/license/status")
        response.raise_for_status()
        status = response.json().get("status")
        assert status in {"active", "inactive"}
        print(f"Evolution process: healthy; license: {status}.")
        if status != "active":
            print("Call and pairing endpoints remain blocked until vendor license activation.")


if __name__ == "__main__":
    asyncio.run(main())
