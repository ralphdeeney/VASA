"""Secret-safe operator authentication diagnosis; never creates or resets an account.

Run in the VASA container after a permitted deployment. One synthetic failed login
uses the normal rate limiter; do not repeatedly run it during customer sign-ins.
"""

import argparse
import asyncio
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from sqlalchemy import text

from vasa.config import Settings
from vasa.storage.database import Database

REASONS = frozenset(
    {
        "invalid_credentials",
        "invalid_origin",
        "account_inactive",
        "email_verification_required",
        "unavailable",
        "too_many_attempts",
        "authentication_required",
        "permission_denied",
        "workspace_inactive",
    }
)


def safe_reason(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return "unclassified"
    reason = payload.get("detail") if isinstance(payload, dict) else None
    return reason if isinstance(reason, str) and reason in REASONS else "unclassified"


async def diagnose(settings: Settings, origin: str) -> list[str]:
    # Validate before use; never echo the supplied origin, env or exception material.
    validated = Settings.model_validate({"public_origin": origin}).public_origin
    if not validated:
        return ["AUTH_DIAGNOSTIC=invalid_configuration"]
    markers = [
        "AUTH_SAAS_ENABLED=" + ("yes" if settings.saas_enabled else "no"),
        "AUTH_CANONICAL_ORIGIN_CONFIGURED=" + ("yes" if settings.public_origin else "no"),
    ]
    database = Database(settings.database_url.get_secret_value(), timeout_seconds=3)
    try:
        async with database.session() as session:
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            markers.append(
                "AUTH_SCHEMA="
                + (revision if revision in {f"000{i}" for i in range(1, 8)} else "unexpected")
            )
            count = await session.scalar(text("SELECT count(*) FROM users"))
            markers.append("AUTH_USERS_PRESENT=" + ("yes" if count else "no"))
    except Exception:
        markers.append("AUTH_DATABASE=unavailable")
    finally:
        await database.aclose()
    headers = {"Host": urlsplit(validated).netloc, "Origin": validated}
    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8080", trust_env=False, timeout=5
        ) as client:
            login = await client.get("/login", headers=headers)
            markers.append(f"AUTH_LOGIN_PAGE_STATUS={login.status_code}")
            response = await client.post(
                "/api/auth/login",
                headers=headers,
                json={
                    "email": f"diagnostic-{uuid4().hex}@example.invalid",
                    "password": "synthetic-non-account-password",
                },
            )
            markers.extend(
                [
                    f"AUTH_LOGIN_PROBE_STATUS={response.status_code}",
                    "AUTH_LOGIN_PROBE_REASON=" + safe_reason(response),
                ]
            )
    except Exception:
        markers.append("AUTH_HTTP=unavailable")
    return markers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--origin", required=True, help="Canonical public HTTPS origin (no credentials)"
    )
    options = parser.parse_args()
    try:
        markers = asyncio.run(diagnose(Settings(), options.origin))
    except Exception:
        markers = ["AUTH_DIAGNOSTIC=invalid_configuration"]
    print("\n".join(markers))


if __name__ == "__main__":
    main()
