import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from vasa.contracts.models import TenantContext
from vasa.tools.gateway import ToolError
from vasa.tools.webhooks_config import load_webhooks


def configuration(path: Path, owner: TenantContext) -> None:
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string", "maxLength": 40}},
        "required": ["name"],
        "additionalProperties": False,
    }
    path.write_text(
        json.dumps(
            {
                "tenants": {
                    str(owner.tenant_id): {
                        "approved_origins": ["https://hooks.example.com"],
                        "actions": {
                            "notify": {
                                "url": "https://hooks.example.com/run",
                                "token_env": "VASA_WEBHOOK_TEST",
                                "input_schema": schema,
                                "output_schema": schema,
                            }
                        },
                    }
                }
            }
        )
    )
    path.chmod(0o600)


async def test_private_tenant_workflow_schema_and_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "workflows.json"
    owner = TenantContext(uuid4(), uuid4())
    configuration(path, owner)
    monkeypatch.setenv("VASA_WEBHOOK_TEST", "synthetic-private-token")
    tool, specs = load_webhooks(path, owner)
    assert tool is not None and specs[0]["name"] == "custom_webhook"
    assert "synthetic-private-token" not in json.dumps(specs)
    assert load_webhooks(path, TenantContext(uuid4(), uuid4())) == (None, [])
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(b'{"name":"accepted"}'),
        )

    await tool.aclose()
    tool._closed = False
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        tool._client, tool._owned = client, False
        for invalid in ({"name": 1}, {"name": "x" * 41}, {"name": "ok", "secret": "bad"}, {}):
            with pytest.raises(ToolError, match="invalid_input"):
                await tool.execute(owner, {"action": "notify", "payload": invalid})
        assert not requests
        assert await tool.execute(owner, {"action": "notify", "payload": {"name": "hello"}}) == {
            "result": {"name": "accepted"}
        }
        assert requests[0].headers["authorization"] == "Bearer synthetic-private-token"


def test_unsafe_workflow_file_or_missing_binding_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = TenantContext(uuid4(), uuid4())
    path = tmp_path / "workflows.json"
    configuration(path, owner)
    monkeypatch.delenv("VASA_WEBHOOK_TEST", raising=False)
    with pytest.raises(ValueError, match="unavailable or invalid"):
        load_webhooks(path, owner)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        load_webhooks(path, owner)
    path.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(path)
    with pytest.raises(ValueError):
        load_webhooks(alias, owner)
    data = json.loads(path.read_text())
    data["tenants"][str(owner.tenant_id)]["actions"]["notify"]["input_schema"]["$ref"] = (
        "https://forbidden.example/schema"
    )
    path.write_text(json.dumps(data))
    monkeypatch.setenv("VASA_WEBHOOK_TEST", "synthetic-token")
    with pytest.raises(ValueError):
        load_webhooks(path, owner)
