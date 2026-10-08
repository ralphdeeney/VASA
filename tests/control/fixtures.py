from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy import delete, select

from vasa.app import create_app
from vasa.config import Settings
from vasa.control.auth import hash_password
from vasa.control.models import User, WhatsAppInstance
from vasa.storage.database import Database
from vasa.storage.models import Tenant

PASSWORD = "test-only-vasa-password"


@dataclass
class EvolutionStub:
    calls: list[tuple[str, ...]] = field(default_factory=list)
    error: Exception | None = None

    def record(self, operation: str, *arguments: str) -> None:
        self.calls.append((operation, *arguments))
        if self.error is not None:
            raise self.error

    async def create_instance(self, instance_id: str, name: str) -> None:
        self.record("create_instance", instance_id, name)

    async def connect(self, instance_id: str) -> None:
        self.record("connect", instance_id)

    async def disconnect(self, instance_id: str) -> None:
        self.record("disconnect", instance_id)

    async def delete_instance(self, instance_id: str) -> None:
        self.record("delete_instance", instance_id)

    async def status(self, instance_id: str) -> SimpleNamespace:
        self.record("status", instance_id)
        return SimpleNamespace(connected=True, logged_in=True, name="Paired test instance")

    async def qr(self, instance_id: str) -> SimpleNamespace:
        self.record("qr", instance_id)
        return SimpleNamespace(qrcode="data:image/png;base64,dGVzdA==", passkey_stage="qr")


@dataclass
class ControlHarness:
    settings: Settings
    database: Database
    redis: Redis
    tenants: tuple[Tenant, Tenant]
    users: tuple[User, User]
    instances: tuple[WhatsAppInstance, WhatsAppInstance]
    evolution: EvolutionStub = field(default_factory=EvolutionStub)
    clients: list[TestClient] = field(default_factory=list)
    cleanup_keys: set[str] = field(default_factory=set)

    @staticmethod
    def session_key(token: str) -> str:
        return f"vasa:auth:session:{sha256(token.encode()).hexdigest()}"

    def client(self, *, settings: Settings | None = None) -> TestClient:
        address = f"vasa-test-{uuid4().hex}"
        self.cleanup_keys.add(f"vasa:auth:login:{sha256(address.encode()).hexdigest()}")
        configuration = settings or self.settings
        client = TestClient(
            create_app(configuration),
            base_url="https://testserver"
            if configuration.environment == "production"
            else "http://testserver",
            client=(address, 51000),
        )
        client.__enter__()
        client.app.state.evolution = self.evolution
        self.clients.append(client)
        return client

    def login(self, client: TestClient, user_index: int = 0) -> str:
        response = client.post(
            "/api/auth/login", json={"email": self.users[user_index].email, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        token = client.cookies.get("vasa_session")
        assert token is not None
        self.cleanup_keys.add(self.session_key(token))
        return str(response.json()["csrf_token"])


@pytest.fixture
async def control_harness(
    dependency_settings: Settings, redis_client: Redis
) -> AsyncIterator[ControlHarness]:
    database = Database(dependency_settings.database_url.get_secret_value())
    tenant_ids = (uuid4(), uuid4())
    try:
        async with database.session() as session:
            try:
                await session.execute(select(User.id).limit(1))
                await session.execute(select(WhatsAppInstance.id).limit(1))
            except Exception as exc:
                pytest.fail(
                    f"Real control schema is unavailable ({type(exc).__name__}); start "
                    "dedicated VASA services and run uv run --frozen alembic upgrade head.",
                    pytrace=False,
                )
            tenants = tuple(
                Tenant(id=tenant_id, name="Control fixture") for tenant_id in tenant_ids
            )
            session.add_all(tenants)
            await session.flush()
            users = tuple(
                User(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    email=f"control-{uuid4().hex}@example.invalid",
                    password_hash=hash_password(PASSWORD),
                )
                for tenant in tenants
            )
            instances = tuple(
                WhatsAppInstance(
                    id=uuid4(),
                    tenant_id=tenant.id,
                    external_id=f"test-instance-{uuid4().hex}",
                    name=f"Tenant {index} instance",
                )
                for index, tenant in enumerate(tenants)
            )
            session.add_all([*users, *instances])
            await session.commit()
        fixture = ControlHarness(
            dependency_settings, database, redis_client, tenants, users, instances
        )
        try:
            yield fixture
        finally:
            for client in reversed(fixture.clients):
                token = client.cookies.get("vasa_session")
                if token:
                    fixture.cleanup_keys.add(fixture.session_key(token))
                client.__exit__(None, None, None)
            if fixture.cleanup_keys:
                await redis_client.delete(*fixture.cleanup_keys)
    finally:
        try:
            async with database.session() as session:
                await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
                await session.commit()
        finally:
            await database.aclose()
