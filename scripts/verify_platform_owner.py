"""One private, real owner login/check/logout; fixed HTTPS origin and safe output."""

import asyncio
import json
import sys

import httpx


async def verify(email: str, password: str, client: httpx.AsyncClient) -> None:
    csrf = ""
    try:
        response = await client.post(
            "/api/auth/admin/login", json={"username": "admin", "password": password}
        )
        if response.status_code != 200 or len(response.content) > 65536:
            raise ValueError()
        csrf = response.json().get("csrf_token", "")
        if not isinstance(csrf, str) or not 20 <= len(csrf) <= 128:
            raise ValueError()
        account = await client.get("/api/saas/admin/account")
        if account.status_code != 200 or len(account.content) > 65536:
            raise ValueError()
        data = account.json()
        if data != {"email": email.lower().strip(), "username": "admin", "role": "super_admin"}:
            raise ValueError()
        page = await client.get("/admin")
        if page.status_code != 200:
            raise ValueError()
    finally:
        if csrf:
            logout = await client.post("/api/auth/logout", headers={"x-csrf-token": csrf})
            if logout.status_code != 200:
                raise ValueError()


async def execute() -> None:
    content = sys.stdin.read(4097)
    data = json.loads(content)
    if (
        len(content) > 4096
        or not isinstance(data, dict)
        or set(data) != {"email", "password"}
        or not all(isinstance(value, str) for value in data.values())
    ):
        raise ValueError()
    async with httpx.AsyncClient(
        base_url="https://vasa.litatech.xyz",
        timeout=15,
        follow_redirects=False,
        headers={"User-Agent": "VASA-Health-Diagnostic/1.0"},
    ) as client:
        await verify(data["email"], data["password"], client)


def main() -> int:
    try:
        asyncio.run(execute())
    except Exception:
        print("PLATFORM_OWNER_LOGIN_FAILED")
        return 1
    print("PLATFORM_OWNER_LOGIN_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
